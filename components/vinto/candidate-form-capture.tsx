"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ContextStrip, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import type { BobinasCandidate } from "@/lib/vinto/bobinas-candidates";
import type { CandidateAttempt, CandidateCapture, CandidateDraft, CandidateSubmitDeps } from "@/lib/vinto/candidate-form";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";

// Pantalla de captura CENTRAL CANDIDATA de un formulario declarativo (candidate-form.ts): la usan P1-05 y P1-31 y la usarán las fichas simples siguientes. Envía SOLO a la API central
// (POST /api/captures con el código del formulario) y se reconcilia con GET por id; nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT,
// máquina, turno, fecha) es solo informativo: el backend vuelve a derivarlo de la asignación. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo si el resultado es incierto.
// NO es una ficha homologada: las decisiones pendientes de VINTO se muestran en pantalla.

type Props = {
    candidate: BobinasCandidate;
    context: CaptureContext;
    online: boolean;
    attempt: CandidateAttempt | null;
    setAttempt: (attempt: CandidateAttempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: CandidateCapture) => void; // éxito: el padre refresca el historial, etc.
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es una firma
    deps?: CandidateSubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = { state: "reading" } | { state: "ok" } | { state: "mismatch" } | { state: "error" };

export function CandidateFormCapture({ candidate, context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, deps }: Props) {
    const { form, api } = candidate;
    const realDeps: CandidateSubmitDeps = { post: api.submit, get: (id) => api.get(id) };
    const io = deps ?? realDeps;
    const [draft, setDraft] = useState<CandidateDraft>(attempt ? { ...attempt.draft } : form.emptyDraft());
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: CandidateCapture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const set = (key: string) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = form.createAttempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await form.submitAttempt(current, io);
            if (outcome.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(outcome);
                toast.success(message);
                setSaved({ capture: outcome.capture, message, readBack: { state: "reading" } });
                onSubmitted?.(outcome.capture);
                // Consulta posterior: se vuelve a leer la captura por id de la API central y se compara con lo guardado.
                const read = await io.get(outcome.capture.id);
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

    return <CaptureShell kicker={candidate.kicker} title={candidate.title} onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950" data-section="candidate">
            <p className="font-black">Ficha NO homologada · solo donde el backend la publique</p>
            <p className="mt-1">Los campos son los de la definición legacy como punto de partida técnico. Esta captura solo funciona donde el formulario esté habilitado explícitamente y no sustituye ninguna decisión de VINTO.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-2" data-section="pending">
            {candidate.pending.map(note => <div key={note.label}><p className="text-xs font-semibold text-emerald-800">{note.label}</p><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="automatic">
            Campos automáticos (no se digitan): {candidate.automatic.join(", ")}.{user ? <> Sesión iniciada como <b>{user.display_name}</b>: es solo la identificación del usuario autenticado, no una firma.</> : null}
        </p>
        <CaptureSection title={candidate.title} hint="Campos manuales de la definición candidata. Se guardan tal como se digitan; ninguno se calcula ni se valida contra un catálogo.">
            {form.fields.map(field => field.kind === "textarea"
                ? <TextAreaField key={field.key} label={field.label} required={field.required} disabled={locked} value={draft[field.key] ?? ""} onChange={set(field.key)}/>
                : <TextField key={field.key} label={field.label} required={field.required} disabled={locked} value={draft[field.key] ?? ""} onChange={set(field.key)}
                    inputMode={field.kind === "decimal" ? "decimal" : "text"} suffix={field.suffix}/>)}
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · revisión {saved.capture.revision} · {saved.capture.machine.code} · OT {saved.capture.work_order.number}</p>
            <p className="mt-1" data-readback={saved.readBack.state}>{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior no coincide con lo enviado; revisa el registro." : "No se pudo verificar con una consulta posterior; el envío ya fue confirmado por el servidor."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
