"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ChoiceField, ContextStrip, ContextValue, RepeatableGroup, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { addRow, canAddRow, canRemoveRow, errorsFor, removeRow, setCell, type GroupFieldSpec, type GroupSpec, type RowError } from "@/lib/vinto/capture-groups";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import { ADVISORY, P111_GROUPS, PENDING_NOTES, createP111Attempt, emptyP111Draft, submitP111Attempt, type P111Attempt, type P111Capture, type P111Draft, type P111SubmitDeps } from "@/lib/vinto/p1-11";
import { getP111, submitP111 } from "@/lib/vinto/p1-11-api";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// VINTO-P1-11 · Consumo de bobinas (Conversión): captura CENTRAL CANDIDATA con UN grupo repetible de bobinas DECLARADAS (API + PostgreSQL), M6-D. Solo funciona contra un backend que habilite P1-11 (hoy únicamente
// entornos de prueba: Conversión no es operativo y el formulario no está en la política de captura central). NO es una ficha homologada: el N.º de bobina, la posición y los tres saldos son DECLARACIONES de
// prueba; no generan consumo, balance ni movimiento de inventario y no se vinculan con ninguna bobina real. Rodelas, insumos, producción, cuchilla, recetas y firmas son decisiones PENDIENTES de VINTO.
//
// Nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, máquina, turno, fecha) se muestra solo como información: el backend vuelve a derivarlo.
// Los identificadores internos de fila (`rowKey`) nunca viajan. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P111Attempt | null;
    setAttempt: (attempt: P111Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P111Capture) => void;
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es una firma
    api?: P111SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = "reading" | "ok" | "mismatch" | "error";
const REAL_API: P111SubmitDeps = { post: submitP111, get: (id) => getP111(id) };

function FieldFor({ field, value, disabled, onChange }: { field: GroupFieldSpec; value: string; disabled: boolean; onChange: (value: string) => void }) {
    if (field.kind === "choice") return <ChoiceField label={field.label} required={field.required} options={field.options ?? []} disabled={disabled} value={value} onChange={onChange}/>;
    return <TextField label={field.label} required={field.required} suffix={field.unit} inputMode={field.kind === "decimal" ? "decimal" : "text"} disabled={disabled} value={value} onChange={onChange}/>;
}

export function P111CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P111Draft>(() => (attempt ? structuredClone(attempt.draft) as P111Draft : emptyP111Draft()));
    const [errors, setErrors] = useState<RowError[]>([]);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P111Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const updateGroup = (spec: GroupSpec, fn: (rows: P111Draft["groups"][string]) => P111Draft["groups"][string]) => setDraft(old => ({ ...old, groups: { ...old.groups, [spec.code]: fn(old.groups[spec.code] ?? []) } }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP111Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) { setErrors(created.errors); return void setNotice([SUBMIT_MESSAGES.invalid, ...created.errors.filter(e => e.group === "").map(e => e.message)].join(" ")); }
            setErrors([]);
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id y las mismas filas
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP111Attempt(current, api);
            if (!live()) return; // INT-01: la sesión cambió mientras se enviaba: esta respuesta es de otra sesión y no modifica el estado compartido
            if (outcome.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(outcome);
                toast.success(message);
                setSaved({ capture: outcome.capture, message, readBack: "reading" });
                onSubmitted?.(outcome.capture);
                const read = await api.get(outcome.capture.id); // consulta posterior por id: se compara con lo que la API confirmó
                if (!live()) return; // INT-01: la sesión cambió mientras se enviaba: esta respuesta es de otra sesión y no modifica el estado compartido
                setSaved(old => old && { ...old, readBack: !read.ok ? "error" : JSON.stringify(read.data.values) === JSON.stringify(outcome.capture.values) ? "ok" : "mismatch" });
                return;
            }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") {
                setAttempt(null);
                if (outcome.reason === "stale" || outcome.reason === "not_active") { toast.error(outcome.message); return void onAssignmentChanged(); }
                return void setNotice(outcome.message);
            }
            setNotice(outcome.message); // not_saved / uncertain: se conserva el intento y se bloquean campos y filas
        } finally { busy.current = false; setSending(false); }
    }

    const spec = P111_GROUPS[0], rows = draft.groups[spec.code] ?? [];
    return <CaptureShell kicker="Consumo de bobinas · Conversión" title="Consumo de bobinas" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha NO homologada · solo entorno de prueba</p>
            <p className="mt-1" data-advisory>{ADVISORY}</p>
            <p className="mt-1">La hipótesis de prueba es un grupo de bobinas declaradas; no es la definición de 61 campos ni las tres filas fijas de la pantalla legacy. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-5" data-section="pending">
            {PENDING_NOTES.map(note => <div key={note.key}><ContextValue label={note.label} value="— pendiente —"/><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es una firma ni un grupo.</p>}
        <RepeatableGroup key={spec.code} title={spec.label} hint="Una fila por bobina declarada, en el orden en que se capturan. Se pueden repetir posiciones y números; no hay máximo funcional definido (solo el límite técnico del sistema). La unidad «kg» es una etiqueta de la hipótesis legacy."
            rows={rows.map((r, i) => ({ key: r.rowKey, errors: errorsFor(errors, spec.code, i + 1) }))} minRows={spec.minRows} maxRows={spec.maxRows} canAdd={canAddRow(spec, rows)} canRemove={canRemoveRow(spec, rows)}
            disabled={locked} groupErrors={errorsFor(errors, spec.code, null)} onAdd={() => updateGroup(spec, r => addRow(spec, r))} onRemove={i => updateGroup(spec, r => removeRow(spec, r, r[i].rowKey))}
            renderRow={i => spec.fields.map(field => <FieldFor key={field.key} field={field} disabled={locked} value={rows[i].cells[field.key] ?? ""} onChange={v => updateGroup(spec, r => setCell(r, rows[i].rowKey, field.key, v))}/>)}/>
        <CaptureSection title="Observaciones">
            <TextAreaField label="Observaciones" disabled={locked} value={draft.observaciones} onChange={v => setDraft(old => ({ ...old, observaciones: v }))}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · revisión {saved.capture.revision} · {saved.capture.status} · {saved.capture.values._groups.bobinas.length} {saved.capture.values._groups.bobinas.length === 1 ? "bobina declarada" : "bobinas declaradas"}.</p>
            <p className="mt-1" data-readback={saved.readBack}>{saved.readBack === "reading" ? "Consultando la captura en la API central…" : saved.readBack === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
