"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ChoiceField, ContextStrip, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { getCapture, submitCapture } from "@/lib/vinto/captures-api";
import { EMPTY_DRAFT, PUNTO_MERMA_OPTIONS, SUBMIT_MESSAGES, TIPO_PRODUCTO_OPTIONS, createAttempt, submitAttempt, submitMessage, type F6Draft, type PendingAttempt } from "@/lib/vinto/captures";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// F6 · Registro de control de fardos: se envía SOLO a la API central (PostgreSQL). Nunca escribe en vinto-p1-records ni en
// localStorage (salvo la clave técnica vinto-device-key). El encabezado muestra el contexto de la asignación solo como
// información: el backend vuelve a derivar máquina, turno, fecha, OT, PV y producto. El intento pendiente vive en el padre
// para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: PendingAttempt | null;
    setAttempt: (attempt: PendingAttempt | null) => void;
    back: () => void;
    onSubmitted: () => void; // éxito: el padre cierra el formulario y refresca la lista central
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario y refresca la asignación activa
    onSessionLost: () => void;
};

export function F6Capture({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost }: Props) {
    const [draft, setDraft] = useState<F6Draft>(attempt ? { ...attempt.draft } : EMPTY_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const busy = useRef(false);
    const locked = sending || attempt !== null;
    const set = (key: keyof F6Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createAttempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitAttempt(current, { post: submitCapture, get: id => getCapture(id) });
            if (!live()) return; // INT-01: la sesión cambió mientras se enviaba: esta respuesta es de otra sesión y no modifica el estado compartido
            if (outcome.kind === "submitted") { setAttempt(null); toast.success(submitMessage(outcome)); return void onSubmitted(); }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") {
                setAttempt(null); // respuesta definitiva: el intento termina (el formulario se desbloquea salvo stale/no activa)
                if (outcome.reason === "stale" || outcome.reason === "not_active") { toast.error(outcome.message); return void onAssignmentChanged(); }
                return void setNotice(outcome.message);
            }
            setNotice(outcome.message); // not_saved / uncertain: se conserva el intento y se bloquean los campos
        } finally { busy.current = false; setSending(false); }
    }

    return <CaptureShell kicker="Cierre de fardos" title="Registro de control de fardos" onBack={back}>
        <ContextStrip items={contextItems(context)}/>
        <CaptureSection title="Control de fardos" hint="Línea genérica para bobina rechazada o recorte de máquina.">
            <TextField label="Cantidad de fardos" required inputMode="numeric" disabled={locked} value={draft.cantidad_fardos} onChange={set("cantidad_fardos")}/>
            <ChoiceField label="Punto de merma" value={draft.punto_merma} onChange={set("punto_merma")} options={PUNTO_MERMA_OPTIONS} disabled={locked}/>
            <ChoiceField label="Tipo de producto" value={draft.tipo_producto} onChange={set("tipo_producto")} options={TIPO_PRODUCTO_OPTIONS} disabled={locked}/>
            <TextField label="Peso real total" required inputMode="decimal" suffix="kg" disabled={locked} value={draft.peso_kg} onChange={set("peso_kg")}/>
            <TextAreaField label="Observaciones" disabled={locked} value={draft.observaciones} onChange={set("observaciones")}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>
    </CaptureShell>;
}
