"use client";

import { useRef, useState } from "react";
import { ArrowLeft, Send } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getDeviceKey } from "@/lib/vinto/device";
import { getQualityCapture, submitQualityCapture } from "@/lib/vinto/quality-captures-api";
import {
    EMPTY_HUMIDITY_DRAFT, HUMIDITY_MESSAGES, POSITIONS, POSITION_LABELS, WEIGHT_LABELS, bobbinToShow, computeHumidity, createHumidityAttempt, formatHumidity, pendingNotice,
    submitHumidityAttempt, type HumidityDraft, type PendingHumidityAttempt, type Position, type WeightKey,
} from "@/lib/vinto/quality-captures";
import { grammageLabel, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";

// VINTO-P1-19 · Control de humedad de UNA Bobina física: se envía SOLO a POST /api/quality/bobbins/{id}/captures (PostgreSQL). Nunca escribe en
// vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El encabezado sale del item del inbox (la Bobina seleccionada
// es la autoridad visual), no de la asignación activa. La humedad y el promedio son SOLO presentación: no se envían ni se guardan.
// El intento pendiente vive en el padre: Volver no genera un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    item: QualityBobbinInboxItem | null; // Bobina seleccionada; se ignora si hay un intento pendiente (manda la Bobina del intento)
    online: boolean;
    attempt: PendingHumidityAttempt | null;
    setAttempt: (attempt: PendingHumidityAttempt | null) => void;
    back: () => void;
    onSubmitted: () => void; // éxito: el padre cierra el formulario y refresca el inbox (la Bobina sigue pendiente)
    onSessionLost: () => void;
};

function Auto({ label, value }: { label: string; value: string }) {
    return <div><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 font-bold">{value}</p></div>;
}

function Derived({ label, value }: { label: string; value: string }) {
    return <div className="rounded-lg border bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-600">{label}</p><p className="mt-1 text-lg font-black">{value} %</p></div>;
}

export function QualityHumidityCapture({ item, online, attempt, setAttempt, back, onSubmitted, onSessionLost }: Props) {
    const [draft, setDraft] = useState<HumidityDraft>(attempt ? { ...attempt.draft } : EMPTY_HUMIDITY_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? HUMIDITY_MESSAGES.uncertain : null);
    const busy = useRef(false);
    const locked = sending || attempt !== null;
    const shown = bobbinToShow(attempt, item);
    const humidity = computeHumidity(draft);
    const set = (key: keyof HumidityDraft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        if (busy.current || !shown) return; // evita el doble clic
        if (!online) return void setNotice(HUMIDITY_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createHumidityAttempt(draft, shown, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: si la respuesta es incierta, el reintento usa el mismo capture_id y la misma Bobina
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitHumidityAttempt(current, { post: submitQualityCapture, get: id => getQualityCapture(id) });
            if (outcome.kind === "submitted") { setAttempt(null); toast.success(outcome.message); return void onSubmitted(); }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") { setAttempt(null); return void setNotice(outcome.message); } // definitivo: el intento termina y los campos se desbloquean
            setNotice(outcome.message); // not_saved / incierto: se conserva el MISMO intento y se bloquean los campos
        } finally { busy.current = false; setSending(false); }
    }

    if (!shown) return null; // el padre solo monta este formulario con una Bobina seleccionada o con un intento pendiente
    const { bobbin, production } = shown;
    const weight = (key: WeightKey) => <div key={key}><Label>{WEIGHT_LABELS[key]} *</Label><div className="relative"><Input disabled={locked} className="mt-2 text-slate-950" type="text" inputMode="decimal" value={draft[key]} onChange={e => set(key)(e.target.value)}/><span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">kg</span></div></div>;

    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/>
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">Calidad</p><h1 className="mt-2 text-2xl font-black">Control de humedad</h1></div>
            <div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-4"><Auto label="Bobina" value={bobbin.code}/><Auto label="Máquina" value={bobbin.machine.code}/><Auto label="OT" value={production.work_order.number}/><Auto label="Línea / PV" value={`${production.line.line_code} / ${production.line.pv_reference}`}/>
                <Auto label="Artículo" value={`${production.line.article.code} · ${production.line.article.description}`}/><Auto label="Fecha operativa" value={production.operating_date}/><Auto label="Turno" value={production.shift.name}/><Auto label="Gramaje" value={grammageLabel(bobbin.grammage_g_m2)}/></div>
            {attempt && <div role="status" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{pendingNotice(attempt)}</div>}
            <div className="border-b p-6"><h2 className="font-black">Pesos de la muestra</h2><p className="mb-4 text-sm text-slate-700">Se registran solo los pesos; la humedad y el promedio se calculan aquí para mostrarlos y no se envían.</p>
                <div className="grid gap-5 md:grid-cols-2">
                    {POSITIONS.flatMap(p => [weight(`peso_humedo_${p}` as WeightKey), weight(`peso_seco_${p}` as WeightKey)])}
                    <div className="md:col-span-2"><Label>Observaciones</Label><Textarea disabled={locked} className="mt-2 text-slate-950" value={draft.observaciones} onChange={e => set("observaciones")(e.target.value)}/></div>
                </div></div>
            <div className="border-b p-6"><h2 className="font-black">Humedad calculada</h2><div className="mt-3 grid gap-3 md:grid-cols-4">
                {POSITIONS.map((p: Position) => <Derived key={p} label={`Humedad · ${POSITION_LABELS[p]}`} value={formatHumidity(humidity[p])}/>)}<Derived label="Promedio humedad" value={formatHumidity(humidity.promedio)}/></div></div>
            {notice && <div role="alert" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{notice}</div>}
            <div className="flex flex-wrap justify-end gap-2 border-t p-5">
                <Button className="bg-[#146b4f]" disabled={sending} onClick={send}><Send className="mr-2 h-4 w-4"/>{sending ? "Enviando…" : attempt ? "Reintentar envío" : "Registrar control de humedad"}</Button>
            </div>
        </div></section></main>;
}
