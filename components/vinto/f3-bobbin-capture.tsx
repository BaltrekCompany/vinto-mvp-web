"use client";

import { useRef, useState } from "react";
import { ArrowLeft, Send } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { submitBobbin } from "@/lib/vinto/bobbins-api";
import { BOBBIN_MESSAGES, EMPTY_BOBBIN_DRAFT, contextToShow, createBobbinAttempt, pendingNotice, submitBobbinAttempt, type BobbinDraft, type PendingBobbinAttempt } from "@/lib/vinto/bobbins";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";

// F3 · Registro de producción de bobinas: se envía SOLO a POST /api/bobbins (PostgreSQL). Nunca escribe en vinto-p1-records ni en
// localStorage (salvo la clave técnica vinto-device-key). El encabezado es solo informativo: el backend deriva máquina, turno,
// fecha, OT, PV, producto, gramaje y el código correlativo. Un envío incierto se reintenta con el MISMO capture_id (idempotente);
// el intento pendiente vive en el padre para que Volver no genere un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    context: CaptureContext | null; // contexto ACTUAL del selector; se ignora si hay un intento pendiente (manda el contexto original del intento)
    online: boolean;
    attempt: PendingBobbinAttempt | null;
    setAttempt: (attempt: PendingBobbinAttempt | null) => void;
    back: () => void;
    onSubmitted: () => void; // éxito: el padre cierra el formulario y refresca la asignación
    onAssignmentChanged: () => void; // stale / no activa: el padre cierra el formulario y refresca la asignación activa
    onSessionLost: () => void;
};

function Auto({ label, value }: { label: string; value: string }) {
    return <div><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 font-bold">{value}</p></div>;
}

function Unit({ children }: { children: string }) {
    return <span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">{children}</span>;
}

export function F3BobbinCapture({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost }: Props) {
    const [draft, setDraft] = useState<BobbinDraft>(attempt ? { ...attempt.draft } : EMPTY_BOBBIN_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? BOBBIN_MESSAGES.uncertain : null);
    const busy = useRef(false);
    const locked = sending || attempt !== null;
    // Con un intento pendiente se muestra y se reintenta SIEMPRE su contexto original (OT/línea/máquina/turno/fecha y assignment_id),
    // aunque el selector apunte ahora a otra máquina. Sin intento, el contexto actual.
    const shown = contextToShow(attempt, context);
    const set = (key: keyof BobbinDraft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        if (busy.current) return; // evita el doble clic
        if (!online) return void setNotice(BOBBIN_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            if (!shown) return void setNotice(BOBBIN_MESSAGES.notFound);
            const created = createBobbinAttempt(draft, shown, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitBobbinAttempt(current, { post: submitBobbin });
            if (outcome.kind === "submitted") { setAttempt(null); toast.success(outcome.message); return void onSubmitted(); }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") {
                setAttempt(null); // respuesta definitiva: el intento termina (los campos se desbloquean salvo stale/no activa)
                if (outcome.reason === "stale" || outcome.reason === "not_active") { toast.error(outcome.message); return void onAssignmentChanged(); }
                return void setNotice(outcome.message);
            }
            setNotice(outcome.message); // incierto: se conserva el MISMO intento y se bloquean los campos
        } finally { busy.current = false; setSending(false); }
    }

    if (!shown) return null; // el padre solo monta F3 con intento pendiente o con contexto
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/>
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">Bobina madre</p><h1 className="mt-2 text-2xl font-black">Registro de producción de bobinas</h1></div>
            <div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-5"><Auto label="OT" value={shown.otId}/><Auto label="Línea / PV" value={`${shown.lineId} / ${shown.pv}`}/><Auto label="Producto" value={shown.productName}/><Auto label="Máquina" value={shown.machine}/><Auto label="Turno / fecha" value={`${shown.shift} · ${shown.date}`}/></div>
            {attempt && <div role="status" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{pendingNotice(attempt)}</div>}
            <div className="grid gap-3 border-b bg-slate-50 p-5 text-sm md:grid-cols-2"><p><b>Código de bobina:</b> se asignará al guardar</p><p><b>Gramaje:</b> se tomará del maestro central</p></div>
            <div className="border-b p-6"><h2 className="font-black">Datos de la bobina</h2><p className="mb-4 text-sm text-slate-700">Hora inicio: cuándo terminó la bobina anterior. Hora fin: cuándo terminó esta bobina.</p>
                <div className="grid gap-5 md:grid-cols-2">
                    <div><Label>Hora inicio *</Label><Input disabled={locked} className="mt-2 text-slate-950" type="time" value={draft.hora_inicio} onChange={e => set("hora_inicio")(e.target.value)}/></div>
                    <div><Label>Hora fin *</Label><Input disabled={locked} className="mt-2 text-slate-950" type="time" value={draft.hora_fin} onChange={e => set("hora_fin")(e.target.value)}/></div>
                    <div><Label>Diámetro *</Label><div className="relative"><Input disabled={locked} className="mt-2 text-slate-950" type="text" inputMode="decimal" value={draft.diametro} onChange={e => set("diametro")(e.target.value)}/><Unit>mm</Unit></div></div>
                    <div><Label>Peso *</Label><div className="relative"><Input disabled={locked} className="mt-2 text-slate-950" type="text" inputMode="decimal" value={draft.peso_kg} onChange={e => set("peso_kg")(e.target.value)}/><Unit>kg</Unit></div></div>
                    <div className="md:col-span-2"><Label>Número de cortes *</Label><Input disabled={locked} className="mt-2 text-slate-950" type="text" value={draft.numero_de_cortes} onChange={e => set("numero_de_cortes")(e.target.value)}/></div>
                    <div className="md:col-span-2"><Label>Observaciones</Label><Textarea disabled={locked} className="mt-2 text-slate-950" value={draft.observaciones} onChange={e => set("observaciones")(e.target.value)}/></div>
                </div></div>
            {notice && <div role="alert" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{notice}</div>}
            <div className="flex flex-wrap justify-end gap-2 border-t p-5">
                <Button className="bg-[#146b4f]" disabled={sending} onClick={send}><Send className="mr-2 h-4 w-4"/>{sending ? "Enviando…" : attempt ? "Reintentar envío" : "Registrar bobina"}</Button>
            </div>
        </div></section></main>;
}
