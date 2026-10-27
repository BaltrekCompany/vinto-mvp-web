"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ContextStrip, ContextValue, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import { CONTEXT_NOTES, EMPTY_P110_DRAFT, P110_LABELS, createP110Attempt, submitP110Attempt, type P110Attempt, type P110Capture, type P110Draft, type P110SubmitDeps } from "@/lib/vinto/p1-10";
import { getP110, submitP110 } from "@/lib/vinto/p1-10-api";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// VINTO-P1-10 · Registro de fardos: captura CENTRAL (API + PostgreSQL), M2-B2. Solo funciona contra un backend que habilite P1-10 (hoy únicamente entornos de prueba:
// Rebobinado no es operativo y el formulario no está en la política de captura central). NO es una ficha homologada: numeración y formato del fardo, tipo del peso,
// relación producto-línea, máquinas permitidas, responsable, firma y fecha operativa/calendario son decisiones PENDIENTES y aquí no se resuelven.
//
// Nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, máquina, turno, fecha) se muestra solo como
// información: el backend vuelve a derivarlo. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P110Attempt | null;
    setAttempt: (attempt: P110Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P110Capture) => void; // éxito: el padre decide (refrescar lista, etc.)
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario y refresca la asignación activa
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es el responsable ni una firma
    api?: P110SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = { state: "reading" } | { state: "ok" } | { state: "mismatch" } | { state: "error" };
const REAL_API: P110SubmitDeps = { post: submitP110, get: (id) => getP110(id) };

export function P110CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P110Draft>(attempt ? { ...attempt.draft } : EMPTY_P110_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P110Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const set = (key: keyof P110Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP110Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP110Attempt(current, api);
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

    return <CaptureShell kicker="Registro de fardos · Rebobinado" title="Registro de fardos" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha NO homologada · solo entorno de prueba</p>
            <p className="mt-1">Las reglas de numeración, peso, responsable, firma y máquinas están pendientes de confirmar por VINTO. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-4" data-section="contextual">
            <div><ContextValue label="Fecha · automático" value={context.date}/><p className="mt-1 text-xs text-slate-700">{CONTEXT_NOTES.fecha.origin}</p><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.fecha.pending}</p></div>
            <div><ContextValue label="Máquina · automático" value={context.machine}/><p className="mt-1 text-xs text-slate-700">{CONTEXT_NOTES.maquina.origin}</p><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.maquina.pending}</p></div>
            <div><ContextValue label="Responsable" value="— pendiente de definición —"/><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.responsable.pending}</p></div>
            <div><ContextValue label="Firma" value="— pendiente de definición —"/><p className="mt-1 text-xs font-semibold text-amber-900">{CONTEXT_NOTES.firma.pending}</p></div>
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es el responsable aprobado ni una firma.</p>}
        <CaptureSection title="Registro de fardos" hint="El producto y la OT salen de la asignación (arriba): no se digitan. El número de fardo no se genera todavía (numeración automática pendiente de VINTO).">
            <TextField label={P110_LABELS.hora_inicio} required type="time" disabled={locked} hint="Hora local de planta (HH:MM). No es la hora de registro del sistema." value={draft.hora_inicio} onChange={set("hora_inicio")}/>
            <TextField label={P110_LABELS.hora_fin} required type="time" disabled={locked} hint="Hora local de planta (HH:MM). No es la hora de registro del sistema." value={draft.hora_fin} onChange={set("hora_fin")}/>
            <TextField label={P110_LABELS.peso_fardo} required suffix="kg" inputMode="decimal" disabled={locked} hint="Tipo declarado: texto. Formato y decimales por confirmar." value={draft.peso_fardo} onChange={set("peso_fardo")}/>
            <TextAreaField label={P110_LABELS.observaciones} disabled={locked} value={draft.observaciones} onChange={set("observaciones")}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · revisión {saved.capture.revision} · {saved.capture.status}.</p>
            <p className="mt-1">{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
