"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ContextStrip, SubmitBar, TextAreaField, TextField, contextItems, type ContextItem } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import type { CandidateScreen } from "@/lib/vinto/candidate-screen";
import type { CandidateAttempt, CandidateCapture, CandidateDraft, CandidateSubmitDeps } from "@/lib/vinto/candidate-form";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import type { QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";

// Pantalla de captura CENTRAL CANDIDATA de un formulario declarativo (candidate-form.ts): la usan P1-05 y P1-31 y la usarán las fichas simples siguientes. Envía SOLO a la API central
// (POST /api/captures con el código del formulario) y se reconcilia con GET por id; nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT,
// máquina, turno, fecha) es solo informativo: el backend vuelve a derivarlo de la asignación. El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo si el resultado es incierto.
// Contexto "bobbin" (Calidad ligada a una bobina, P1-21): la bobina seleccionada del inbox (o su snapshot si hay un intento pendiente) es la autoridad; el número de bobina se precarga con su código y no se edita.
// NO es una ficha homologada: las decisiones pendientes de VINTO se muestran en pantalla.

type Props = {
    candidate: CandidateScreen;
    context?: CaptureContext; // contexto "assignment" (Producción): la asignación activa
    bobbin?: QualityBobbinInboxItem; // contexto "bobbin" (Calidad por bobina): la bobina física seleccionada; máquina, turno, fecha y OT los deriva el backend de su F3 de origen
    machine?: { code: string; name: string }; // contexto "machine" (Calidad por máquina): sin bobina, asignación ni OT; el backend resuelve turno, fecha operativa y usuario al registrar
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

export function CandidateFormCapture({ candidate, context, machine, bobbin, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, deps }: Props) {
    const { form, api } = candidate;
    const contextId = form.context === "machine" ? machine?.code : form.context === "bobbin" ? bobbin?.bobbin.id : context?.assignmentId; // assignment_id, código de máquina o id de bobina, según el formulario
    const codeField = form.context === "bobbin" ? candidate.bobbinCodeField : undefined; // campo que declara el número de bobina: precargado y de solo lectura
    const initialDraft = (): CandidateDraft => { const draft = form.emptyDraft(); if (codeField && bobbin) draft[codeField] = bobbin.bobbin.code; return draft; };
    const items: ContextItem[] = form.context === "bobbin"
        ? [{ label: "Bobina", value: bobbin ? `${bobbin.bobbin.code} · ${bobbin.bobbin.id}` : "—" }, { label: "Máquina", value: bobbin ? `${bobbin.bobbin.machine.code} · ${bobbin.bobbin.machine.name}` : "—" },
            { label: "OT", value: bobbin ? bobbin.production.work_order.number : "—" }, { label: "Línea / PV", value: bobbin ? `${bobbin.production.line.line_code} / ${bobbin.production.line.pv_reference}` : "—" },
            { label: "Artículo", value: bobbin ? `${bobbin.production.line.article.code} · ${bobbin.production.line.article.description}` : "—" }, { label: "Turno y fecha operativa", value: "Los deriva el backend de la producción de la bobina" },
            { label: "Registra", value: user?.display_name ?? "Usuario autenticado" }, { label: "Hora", value: "Hora de registro (no del ensayo)" }]
        : form.context === "machine"
        ? [{ label: "Máquina", value: machine ? `${machine.code} · ${machine.name}` : "—" }, { label: "Turno y fecha operativa", value: "Los resuelve el backend al registrar" }, { label: "Registra", value: user?.display_name ?? "Usuario autenticado" }, { label: "Bobina / OT / asignación", value: "No aplica" }, { label: "Hora", value: "Hora de registro (no del ensayo)" }]
        : context ? contextItems(context) : [];
    const realDeps: CandidateSubmitDeps = { post: api.submit, get: (id) => api.get(id) };
    const io = deps ?? realDeps;
    const [draft, setDraft] = useState<CandidateDraft>(attempt ? { ...attempt.draft } : initialDraft());
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
            if (!contextId) return void setNotice(SUBMIT_MESSAGES.notFound);
            const created = form.createAttempt(draft, contextId, getDeviceKey());
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
                const sameBobbin = form.context !== "bobbin" || (read.ok && read.data.bobbin?.id === bobbin?.bobbin.id && outcome.capture.bobbin?.id === bobbin?.bobbin.id); // la captura debe seguir asociada a ESTA bobina
                setSaved(old => old && { ...old, readBack: !read.ok ? { state: "error" } : sameBobbin && JSON.stringify(read.data.values) === JSON.stringify(outcome.capture.values) ? { state: "ok" } : { state: "mismatch" } });
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
        <ContextStrip items={items}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-2" data-section="pending">
            {candidate.pending.map(note => <div key={note.label}><p className="text-xs font-semibold text-emerald-800">{note.label}</p><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="automatic">
            Campos automáticos (no se digitan): {candidate.automatic.join(", ")}.{user ? <> Sesión iniciada como <b>{user.display_name}</b>: es solo la identificación del usuario autenticado, no una firma.</> : null}
        </p>
        {(candidate.unresolved || candidate.calculated) && <div className="border-b border-amber-300 bg-amber-50 px-5 py-3 text-sm text-amber-950" data-section="gaps">
            {candidate.unresolved && <p>Automáticos sin fuente confirmada (no se generan ni se sustituyen por la hora de envío): <b>{candidate.unresolved.join(", ")}</b>.</p>}
            {candidate.calculated && <p>Calculados sin fórmula aprobada (no se calculan, no se guardan ni se muestran como oficiales): <b>{candidate.calculated.join(", ")}</b>.</p>}</div>}
        <CaptureSection title={candidate.title} hint="Campos manuales de la definición candidata. Se guardan tal como se digitan; ninguno se calcula ni se valida contra un catálogo.">
            {form.fields.map(field => field.kind === "textarea"
                ? <TextAreaField key={field.key} label={field.label} required={field.required} disabled={locked} value={draft[field.key] ?? ""} onChange={set(field.key)}/>
                : <TextField key={field.key} label={field.label} required={field.required} disabled={locked || field.key === codeField} value={draft[field.key] ?? ""} onChange={set(field.key)}
                    inputMode={field.kind === "decimal" ? "decimal" : "text"} suffix={field.suffix}/>)}
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · revisión {saved.capture.revision} · {saved.capture.bobbin ? `Bobina ${saved.capture.bobbin.code} · ` : ""}{saved.capture.machine.code} · {saved.capture.work_order ? `OT ${saved.capture.work_order.number}` : `Turno ${saved.capture.shift.name} · fecha operativa ${saved.capture.operating_date}`}</p>
            <p className="mt-1" data-readback={saved.readBack.state}>{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior no coincide con lo enviado; revisa el registro." : "No se pudo verificar con una consulta posterior; el envío ya fue confirmado por el servidor."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
