"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureSection, CaptureShell, ContextStrip, ContextValue, SubmitBar, TextAreaField, TextField, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";
import {
    ADVISORY, EMPTY_P113_DRAFT, P113_LABELS, PENDING_NOTES, createP113Attempt, submitP113Attempt,
    type P113Attempt, type P113Capture, type P113Draft, type P113SubmitDeps,
} from "@/lib/vinto/p1-13";
import { getP113, submitP113 } from "@/lib/vinto/p1-13-api";
import { P112_LABELS, shortHour } from "@/lib/vinto/p1-12";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

// VINTO-P1-13 · Producción diaria de servilletas y especiales (Conversión): captura CENTRAL CANDIDATA (API + PostgreSQL), M6-C. Solo funciona contra un backend que habilite P1-13 (hoy únicamente entornos de
// prueba: Conversión no es operativo y el formulario no está en la política de captura central). NO es una ficha homologada: los ocho campos son una hipótesis de prueba tomada de la pantalla legacy. El N.º de
// bobina y los tres saldos son DECLARACIONES: no generan consumo, balance ni movimiento de inventario, y no se vinculan con ninguna bobina real. Receta, insumos, número de pallet, pesos y firmas son decisiones
// PENDIENTES de VINTO y aquí no se resuelven.
//
// Nunca escribe en vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El contexto (OT, máquina, turno, fecha) se muestra solo como información: el backend vuelve a derivarlo.
// El intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P113Attempt | null;
    setAttempt: (attempt: P113Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P113Capture) => void; // éxito: el padre decide (refrescar lista, etc.)
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario
    onSessionLost: () => void;
    user?: { display_name: string } | null; // usuario autenticado, solo informativo: NO es una firma
    api?: P113SubmitDeps; // inyectable para pruebas; por defecto la API central
};

type ReadBack = { state: "reading" } | { state: "ok" } | { state: "mismatch" } | { state: "error" };
const REAL_API: P113SubmitDeps = { post: submitP113, get: (id) => getP113(id) };

export function P113CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P113Draft>(attempt ? { ...attempt.draft } : EMPTY_P113_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P113Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const set = (key: keyof P113Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        const live = beginSessionOperation(); // INT-01: guarda de la sesión que origina este envío
        if (busy.current || saved) return; // evita el doble clic
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createP113Attempt(draft, context.assignmentId, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitP113Attempt(current, api);
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

    return <CaptureShell kicker="Producción diaria · Conversión" title="Producción diaria de servilletas y especiales" onBack={back}>
        <div role="note" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">Ficha NO homologada · solo entorno de prueba</p>
            <p className="mt-1" data-advisory>{ADVISORY}</p>
            <p className="mt-1">Los ocho campos son una hipótesis de prueba tomada de la pantalla legacy. No es la definición de 31 campos. Esta captura solo funciona donde el formulario esté habilitado explícitamente.</p>
        </div>
        <ContextStrip items={contextItems(context)}/>
        <div className="grid gap-3 border-b p-5 md:grid-cols-5" data-section="pending">
            {PENDING_NOTES.map(note => <div key={note.key}><p className="text-xs font-semibold text-emerald-800">{note.label}</p><p className="mt-1 text-xs font-semibold text-amber-900">{note.pending}</p></div>)}
        </div>
        {user && <p className="border-b bg-slate-50 px-5 py-3 text-sm text-slate-700" data-section="session">Sesión iniciada como <b>{user.display_name}</b>. Es solo la identificación del usuario autenticado: no es una firma ni un grupo.</p>}
        <CaptureSection title="Bobina declarada" hint="Declaraciones de prueba del operador. No generan consumo, no modifican inventario y no se vinculan con una bobina real. La unidad «kg» es la etiqueta de la hipótesis legacy; la unidad oficial está pendiente.">
            <TextField label={P113_LABELS.numero_bobina} required disabled={locked} hint="Texto libre: no se consulta ni se valida contra ninguna bobina." value={draft.numero_bobina} onChange={set("numero_bobina")}/>
            <div className="hidden md:block"/>
            <TextField label={P113_LABELS.saldo_inicial_kg} required suffix="kg" inputMode="decimal" disabled={locked} value={draft.saldo_inicial_kg} onChange={set("saldo_inicial_kg")}/>
            <TextField label={P113_LABELS.ingreso_kg} required suffix="kg" inputMode="decimal" disabled={locked} value={draft.ingreso_kg} onChange={set("ingreso_kg")}/>
            <TextField label={P113_LABELS.saldo_final_kg} required suffix="kg" inputMode="decimal" disabled={locked} hint="Sin cálculo de consumo: no se compara con el saldo inicial." value={draft.saldo_final_kg} onChange={set("saldo_final_kg")}/>
        </CaptureSection>
        <div className="grid gap-3 border-b p-5 md:grid-cols-2" data-section="pallet-id">
            <ContextValue label="Número oficial de pallet" value="— pendiente de definición —"/>
            <ContextValue label="Identificador técnico de la captura" value={attempt ? attempt.captureId : saved ? saved.capture.id : "se asigna al enviar"}/>
        </div>
        <CaptureSection title="Pallet" hint="Mismos campos y validaciones que P1-12. Sin mínimos ni máximos; la hora de fin puede ser menor que la de inicio si el pallet cruza la medianoche.">
            <TextField label={P112_LABELS.cantidad_jabas} required inputMode="numeric" disabled={locked} value={draft.cantidad_jabas} onChange={set("cantidad_jabas")}/>
            <div className="hidden md:block"/>
            <TextField label={P112_LABELS.hora_inicio} required type="time" disabled={locked} value={draft.hora_inicio} onChange={set("hora_inicio")}/>
            <TextField label={P112_LABELS.hora_fin} required type="time" disabled={locked} value={draft.hora_fin} onChange={set("hora_fin")}/>
        </CaptureSection>
        <CaptureSection title="Observaciones">
            <TextAreaField label={P113_LABELS.observaciones} disabled={locked} value={draft.observaciones} onChange={set("observaciones")}/>
        </CaptureSection>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950" data-section="saved">
            <p className="font-black">{saved.message}</p>
            <p className="mt-1">Captura {saved.capture.id} · bobina declarada {saved.capture.values.numero_bobina} · {saved.capture.values.cantidad_jabas} jabas · {shortHour(saved.capture.values.hora_inicio)}–{shortHour(saved.capture.values.hora_fin)} · revisión {saved.capture.revision} · {saved.capture.status}.</p>
            <p className="mt-1">{saved.readBack.state === "reading" ? "Consultando la captura en la API central…" : saved.readBack.state === "ok" ? "Verificada con una consulta posterior por id en la API central." : saved.readBack.state === "mismatch" ? "La consulta posterior devolvió valores distintos: revisa el registro." : "No se pudo hacer la consulta posterior; el envío ya fue confirmado."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
