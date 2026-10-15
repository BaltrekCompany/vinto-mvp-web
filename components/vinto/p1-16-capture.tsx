"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ChoiceField, ContextStrip, SubmitBar, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, optionLabel, submitMessage } from "@/lib/vinto/capture-core";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import {
    EMPTY_P116_DRAFT, ORIGEN_MERMA_OPTIONS, P116_LABELS, PENDING_NOTES, TIPO_MERMA_OPTIONS, createP116Attempt, submitP116Attempt,
    type P116Attempt, type P116Capture, type P116Draft, type P116SubmitDeps,
} from "@/lib/vinto/p1-16";
import { getP116, submitP116 } from "@/lib/vinto/p1-16-api";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// VINTO-P1-16 · Registro de control de merma (Conversión): captura CENTRAL CANDIDATA (API + PostgreSQL), M6-A. Solo funciona contra un backend que habilite P1-16 (hoy únicamente entornos de
// prueba: Conversión no es operativo y el formulario no está en la política de captura central). NO es una ficha homologada: los tres campos son una hipótesis de prueba tomada de la pantalla
// legacy (una pesada por captura); correlativo, firma, grupo, totales y unidad/rango del peso son decisiones PENDIENTES de VINTO y aquí no se resuelven.
//
// Nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, máquina, turno, fecha) se muestra solo como información: el backend vuelve
// a derivarlo. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P116Attempt | null;
    setAttempt: (attempt: P116Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P116Capture) => void; // éxito: el padre decide (refrescar lista, etc.)
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es una firma
    api?: P116SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = { state: "reading" } | { state: "ok" } | { state: "mismatch" } | { state: "error" };
const REAL_API: P116SubmitDeps = { post: submitP116, get: (id) => getP116(id) };

export function P116CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P116Draft>(attempt ? { ...attempt.draft } : EMPTY_P116_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P116Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const set = (key: keyof P116Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP116Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP116Attempt(current, api);
            if (!live()) return; // INT-01: la sesión cambió mientras se enviaba: esta respuesta es de otra sesión y no modifica el estado compartido
            if (outcome.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(outcome);
                toast.success(message);
                setSaved({ capture: outcome.capture, message, readBack: { state: "reading" } });
                onSubmitted?.(outcome.capture);
                // Consulta posterior: se vuelve a leer la captura por id de la API central y se compara con lo guardado.
                const read = await api.get(outcome.capture.id);
                if (!live()) return; // INT-01: la sesión cambió mientras se enviaba: esta respuesta es de otra sesión y no modifica el estado compartido
                setSaved(old => old && { ...old, readBack: !read.ok ? { state: "error" } : JSON.stringify(read.data.values) === JSON.stringify(outcome.capture.values) ? { state: "ok" } : { state: "mismatch" } });
                return;
            }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") {
                setAttempt(null); // respuesta definitiva: el intento termina (el formulario se desbloquea salvo stale/no activa)
                if (outcome.reason === "stale" || outcome.reason === "not_active") { toast.error(outcome.message); return void onAssignmentChanged(); }
                return void setNotice(outcome.message);
            }
            setNotice(outcome.message); // not_saved / uncertain: se conserva el intento y se bloquean los campos
        } finally { busy.current = false; setSending(false); }
    }

    return <CaptureShell kicker="Control de merma · Conversión" title="Registro de control de merma" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha NO homologada · solo entorno de prueba</p>
            <p className="mt-1">Los tres campos son una hipótesis de prueba tomada de la pantalla legacy: una pesada por captura. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-4" data-section="pending">
            {PENDING_NOTES.map(note => <div key={note.key}><p className="text-xs font-semibold text-emerald-800">{note.label}</p><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es una firma ni un grupo.</p>}
        <CaptureSection title="Pesada de merma" hint="Campos manuales de la hipótesis de prueba. El peso se envía como decimal; unidad, rango y decimales por confirmar.">
            <ChoiceField label={P116_LABELS.tipo_merma} disabled={locked} value={draft.tipo_merma} options={TIPO_MERMA_OPTIONS} onChange={set("tipo_merma")}/>
            <ChoiceField label={P116_LABELS.origen_merma} disabled={locked} value={draft.origen_merma} options={ORIGEN_MERMA_OPTIONS} onChange={set("origen_merma")}/>
            <TextField label={P116_LABELS.peso_merma_kg} required suffix="kg" inputMode="decimal" disabled={locked} value={draft.peso_merma_kg} onChange={set("peso_merma_kg")}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · {optionLabel(TIPO_MERMA_OPTIONS, saved.capture.values.tipo_merma)} · {optionLabel(ORIGEN_MERMA_OPTIONS, saved.capture.values.origen_merma)} · {saved.capture.values.peso_merma_kg} kg · revisión {saved.capture.revision} · {saved.capture.status}.</p>
            <p className="mt-1">{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
