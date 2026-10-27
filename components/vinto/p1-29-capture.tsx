"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ChoiceField, ContextStrip, ContextValue, RepeatableGroup, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { addRow, canAddRow, canRemoveRow, errorsFor, removeRow, setCell, type GroupFieldSpec, type GroupSpec, type RowError } from "@/lib/vinto/capture-groups";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import { CONTEXT_NOTES, P129_GROUPS, P129_PENDING, P129_SIMPLE_FIELDS, createP129Attempt, emptyP129Draft, submitP129Attempt, type P129Attempt, type P129Capture, type P129Draft, type P129SubmitDeps } from "@/lib/vinto/p1-29";
import { getP129, submitP129 } from "@/lib/vinto/p1-29-api";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// VINTO-P1-29 · Producción Tubetera: captura CENTRAL CANDIDATA (API + PostgreSQL), M3-B. «Ficha candidata — No homologada»: la agrupación en campos simples + rodelas + formatos es una
// propuesta técnica; tipo de tubete (sin catálogo), unidad del espesor, operador, visto bueno, nombre de la máquina y el alcance de los grupos son decisiones PENDIENTES y aquí no se
// resuelven. Solo funciona contra un backend que habilite P1-29 (hoy únicamente entornos de prueba: Rebobinado no es operativo y el formulario no está en la política central).
//
// No escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, línea, máquina, turno, fecha operativa) se muestra solo como información:
// el backend lo deriva. Los identificadores internos de fila (`rowKey`) nunca viajan. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo si el resultado es incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P129Attempt | null;
    setAttempt: (attempt: P129Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P129Capture) => void;
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario y refresca la asignación activa
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es el operador ni el visto bueno
    api?: P129SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = "reading" | "ok" | "mismatch" | "error";
const REAL_API: P129SubmitDeps = { post: submitP129, get: (id) => getP129(id) };

function FieldFor({ field, value, disabled, onChange }: { field: GroupFieldSpec; value: string; disabled: boolean; onChange: (value: string) => void }) {
    if (field.kind === "choice") return <ChoiceField label={field.label} required={field.required} options={field.options ?? []} disabled={disabled} value={value} onChange={onChange}/>;
    if (field.kind === "textarea") return <TextAreaField label={field.label} required={field.required} disabled={disabled} value={value} onChange={onChange}/>;
    return <TextField label={field.label} required={field.required} suffix={field.unit} inputMode={field.kind === "decimal" ? "decimal" : field.kind === "integer" ? "numeric" : "text"} disabled={disabled} value={value} onChange={onChange}/>;
}

export function P129CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P129Draft>(() => (attempt ? structuredClone(attempt.draft) as P129Draft : emptyP129Draft()));
    const [errors, setErrors] = useState<RowError[]>([]);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P129Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const setSimple = (key: keyof P129Draft["simple"]) => (value: string) => setDraft(old => ({ ...old, simple: { ...old.simple, [key]: value } }));
    const updateGroup = (spec: GroupSpec, fn: (rows: P129Draft["groups"][string]) => P129Draft["groups"][string]) => setDraft(old => ({ ...old, groups: { ...old.groups, [spec.code]: fn(old.groups[spec.code] ?? []) } }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP129Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) { setErrors(created.errors); return void setNotice([SUBMIT_MESSAGES.invalid, ...created.errors.filter(e => e.group === "").map(e => e.message)].join(" ")); }
            setErrors([]);
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id y las mismas filas
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP129Attempt(current, api);
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

    return <CaptureShell kicker="Producción Tubetera · Rebobinado" title="Producción Tubetera" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha candidata — No homologada · solo entorno de prueba</p>
            <p className="mt-1">La agrupación de campos, los tipos de tubete, el visto bueno, la unidad del espesor y el alcance de las filas están pendientes de confirmar por VINTO. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-3" data-section="contextual">
            <div><ContextValue label="Turno · automático" value={context.shift}/><p className="mt-1 text-xs text-slate-700">{CONTEXT_NOTES.turno.origin}</p><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.turno.pending}</p></div>
            <div><ContextValue label="Operador" value="— pendiente de definición —"/><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.operador.pending}</p></div>
            <div><ContextValue label="Visto bueno del responsable" value="— pendiente de definición —"/><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.visto_bueno_responsable.pending}</p></div>
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es el operador ni el visto bueno del responsable.</p>}
        <CaptureSection title="Lote de producción" hint="Información general del lote (campos manuales de la ficha).">
            {P129_SIMPLE_FIELDS.map(field => field.kind === "textarea"
                ? <TextAreaField key={field.key} label={field.label} required={field.required} disabled={locked} value={draft.simple[field.key]} onChange={setSimple(field.key)}/>
                : <div key={field.key}><TextField label={field.label} required={field.required} type={field.kind === "date" ? "date" : field.kind === "time" ? "time" : "text"} suffix={field.unit} disabled={locked} hint={field.hint} value={draft.simple[field.key]} onChange={setSimple(field.key)}/>
                    {errorsFor(errors, "", null).filter(m => m.startsWith(`${field.label}:`)).map(m => <p key={m} role="alert" className="mt-1 text-xs font-semibold text-amber-900">{m}</p>)}</div>)}
        </CaptureSection>
        {P129_GROUPS.map(spec => { const rows = draft.groups[spec.code] ?? [];
            return <RepeatableGroup key={spec.code} title={spec.label} hint={spec.code === "rodelas" ? "Una fila por rodela / lote de papel kraft (propuesta de agrupación)." : "Una fila por formato producido (propuesta de agrupación)."}
                rows={rows.map((r, i) => ({ key: r.rowKey, errors: errorsFor(errors, spec.code, i + 1) }))} minRows={spec.minRows} maxRows={spec.maxRows} canAdd={canAddRow(spec, rows)} canRemove={canRemoveRow(spec, rows)}
                disabled={locked} groupErrors={errorsFor(errors, spec.code, null)} onAdd={() => updateGroup(spec, r => addRow(spec, r))} onRemove={i => updateGroup(spec, r => removeRow(spec, r, r[i].rowKey))}
                renderRow={i => spec.fields.map(field => <FieldFor key={field.key} field={field} disabled={locked} value={rows[i].cells[field.key] ?? ""} onChange={v => updateGroup(spec, r => setCell(r, rows[i].rowKey, field.key, v))}/>)}/>; })}
        <div className="border-b p-6" data-section="pending"><h2 className="font-black">Decisiones pendientes de VINTO</h2>
            <ul className="mt-3 space-y-2 text-sm">{P129_PENDING.map(item => <li key={item.id} className="rounded-xl border border-amber-200 bg-amber-50 p-3"><span className="font-bold">{item.title}: </span>{item.detail}</li>)}</ul></div>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · revisión {saved.capture.revision} · {saved.capture.status} · {saved.capture.values._groups.rodelas?.length ?? 0} rodelas · {saved.capture.values._groups.formatos?.length ?? 0} formatos.</p>
            <p className="mt-1" data-readback={saved.readBack}>{saved.readBack === "reading" ? "Consultando la captura en la API central…" : saved.readBack === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
