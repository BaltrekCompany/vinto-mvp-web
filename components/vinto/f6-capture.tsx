"use client";

import { useRef, useState } from "react";
import { ArrowLeft, Send } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getCapture, submitCapture } from "@/lib/vinto/captures-api";
import { EMPTY_DRAFT, PUNTO_MERMA_OPTIONS, SUBMIT_MESSAGES, TIPO_PRODUCTO_OPTIONS, createAttempt, submitAttempt, submitMessage, type F6Draft, type Option, type PendingAttempt } from "@/lib/vinto/captures";
import { getDeviceKey } from "@/lib/vinto/device";
import type { CaptureContext } from "@/lib/vinto/orders";

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

function Auto({ label, value }: { label: string; value: string }) {
    return <div><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 font-bold">{value}</p></div>;
}

function Choice({ label, value, set, options, disabled }: { label: string; value: string; set: (x: string) => void; options: readonly Option[]; disabled: boolean }) {
    return <div><Label>{label} *</Label><select disabled={disabled} className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-slate-950 disabled:opacity-70" value={value} onChange={e => set(e.target.value)}><option value="">Seleccionar…</option>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>;
}

export function F6Capture({ context, online, attempt, setAttempt, back, onSubmitted, onAssignmentChanged, onSessionLost }: Props) {
    const [draft, setDraft] = useState<F6Draft>(attempt ? { ...attempt.draft } : EMPTY_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const busy = useRef(false);
    const locked = sending || attempt !== null;
    const set = (key: keyof F6Draft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
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

    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/>
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">Cierre de fardos</p><h1 className="mt-2 text-2xl font-black">Registro de control de fardos</h1></div>
            <div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-5"><Auto label="OT" value={context.otId}/><Auto label="Línea / PV" value={`${context.lineId} / ${context.pv}`}/><Auto label="Producto" value={context.productName}/><Auto label="Máquina" value={context.machine}/><Auto label="Turno / fecha" value={`${context.shift} · ${context.date}`}/></div>
            <div className="border-b p-6"><h2 className="font-black">Control de fardos</h2><p className="mb-4 text-sm text-slate-700">Línea genérica para bobina rechazada o recorte de máquina.</p>
                <div className="grid gap-5 md:grid-cols-2">
                    <div><Label>Cantidad de fardos *</Label><Input disabled={locked} className="mt-2 text-slate-950" type="text" inputMode="numeric" value={draft.cantidad_fardos} onChange={e => set("cantidad_fardos")(e.target.value)}/></div>
                    <Choice label="Punto de merma" value={draft.punto_merma} set={set("punto_merma")} options={PUNTO_MERMA_OPTIONS} disabled={locked}/>
                    <Choice label="Tipo de producto" value={draft.tipo_producto} set={set("tipo_producto")} options={TIPO_PRODUCTO_OPTIONS} disabled={locked}/>
                    <div><Label>Peso real total *</Label><div className="relative"><Input disabled={locked} className="mt-2 text-slate-950" type="text" inputMode="decimal" value={draft.peso_kg} onChange={e => set("peso_kg")(e.target.value)}/><span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">kg</span></div></div>
                    <div className="md:col-span-2"><Label>Observaciones</Label><Textarea disabled={locked} className="mt-2 text-slate-950" value={draft.observaciones} onChange={e => set("observaciones")(e.target.value)}/></div>
                </div></div>
            {notice && <div role="alert" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{notice}</div>}
            <div className="flex flex-wrap justify-end gap-2 border-t p-5">
                <Button className="bg-[#146b4f]" disabled={sending} onClick={send}><Send className="mr-2 h-4 w-4"/>{sending ? "Enviando…" : attempt ? "Reintentar envío" : "Enviar registro trazable"}</Button>
            </div>
        </div></section></main>;
}
