"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ContextStrip, ContextValue, SubmitBar, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import {
    EMPTY_P112_DRAFT, P112_LABELS, PENDING_NOTES, createP112Attempt, shortHour, submitP112Attempt,
    type P112Attempt, type P112Capture, type P112Draft, type P112SubmitDeps,
} from "@/lib/vinto/p1-12";
import { getP112, submitP112 } from "@/lib/vinto/p1-12-api";

// VINTO-P1-12 · Producción diaria de papel higiénico (Conversión): captura CENTRAL CANDIDATA de UN PALLET (API + PostgreSQL), M6-B. Solo funciona contra un backend que habilite P1-12 (hoy únicamente
// entornos de prueba: Conversión no es operativo y el formulario no está en la política de captura central). NO es una ficha homologada: los tres campos (cantidad de jabas, hora de inicio y de fin)
// son una hipótesis de prueba tomada de la pantalla legacy. El número oficial de pallet, el peso nominal y total, los balances y las firmas son decisiones PENDIENTES de VINTO y aquí no se resuelven.
//
// Nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, máquina, turno, fecha) se muestra solo como información: el backend vuelve
// a derivarlo. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P112Attempt | null;
    setAttempt: (attempt: P112Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P112Capture) => void; // éxito: el padre decide (refrescar lista, etc.)
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es una firma
    api?: P112SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = { state: "reading" } | { state: "ok" } | { state: "mismatch" } | { state: "error" };
const REAL_API: P112SubmitDeps = { post: submitP112, get: (id) => getP112(id) };

export function P112CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P112Draft>(attempt ? { ...attempt.draft } : EMPTY_P112_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P112Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const set = (key: keyof P112Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP112Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP112Attempt(current, api);
            if (outcome.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(outcome);
                toast.success(message);
                setSaved({ capture: outcome.capture, message, readBack: { state: "reading" } });
                onSubmitted?.(outcome.capture);
                // Consulta posterior: se vuelve a leer la captura por id de la API central y se compara con lo guardado.
                const read = await api.get(outcome.capture.id);
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

    return <CaptureShell kicker="Producción por pallet · Conversión" title="Producción diaria de papel higiénico" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha NO homologada · solo entorno de prueba</p>
            <p className="mt-1">Los tres campos son una hipótesis de prueba tomada de la pantalla legacy: un pallet por captura. No es la definición de 37 campos. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-4" data-section="pending">
            {PENDING_NOTES.map(note => <div key={note.key}><p className="text-xs font-semibold text-emerald-800">{note.label}</p><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es una firma ni un grupo.</p>}
        <div className="grid gap-3 border-b p-5 md:grid-cols-2" data-section="pallet-id">
            <ContextValue label="Número oficial de pallet" value="— pendiente de definición —"/>
            <ContextValue label="Identificador técnico de la captura" value={attempt ? attempt.captureId : saved ? saved.capture.id : "se asigna al enviar"}/>
        </div>
        <CaptureSection title="Pallet" hint="Campos manuales de la hipótesis de prueba. Sin mínimos ni máximos; la hora de fin puede ser menor que la de inicio si el pallet cruza la medianoche.">
            <TextField label={P112_LABELS.cantidad_jabas} required inputMode="numeric" disabled={locked} value={draft.cantidad_jabas} onChange={set("cantidad_jabas")}/>
            <div className="hidden md:block"/>
            <TextField label={P112_LABELS.hora_inicio} required type="time" disabled={locked} value={draft.hora_inicio} onChange={set("hora_inicio")}/>
            <TextField label={P112_LABELS.hora_fin} required type="time" disabled={locked} value={draft.hora_fin} onChange={set("hora_fin")}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · {saved.capture.values.cantidad_jabas} jabas · {shortHour(saved.capture.values.hora_inicio)}–{shortHour(saved.capture.values.hora_fin)} · revisión {saved.capture.revision} · {saved.capture.status}.</p>
            <p className="mt-1">{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
