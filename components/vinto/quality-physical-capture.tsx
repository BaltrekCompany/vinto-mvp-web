"use client";

import { useRef, useState } from "react";
import { ArrowLeft, Send } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getDeviceKey } from "@/lib/vinto/device";
import { grammageLabel, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import {
    EMPTY_PHYSICAL_DRAFT, PHYSICAL_GROUPS, PHYSICAL_LABELS, PHYSICAL_MESSAGES, PHYSICAL_SERIES, PHYSICAL_UNITS, SERIES_LABELS, averageLabel, createPhysicalAttempt,
    physicalAverages, physicalBobbinToShow, physicalPendingNotice, submitPhysicalAttempt, type PendingPhysicalAttempt, type PhysicalDraft, type PhysicalKey,
} from "@/lib/vinto/quality-physical";
import { getPhysicalCapture, submitPhysicalCapture } from "@/lib/vinto/quality-physical-api";

// VINTO-P1-20 · Propiedades físicas de UNA Bobina física: se envía SOLO a POST /api/quality/bobbins/{id}/captures (PostgreSQL). Nunca escribe en
// vinto-p1-records ni en localStorage (salvo la clave técnica vinto-device-key). El encabezado sale del item del inbox (o del snapshot del intento
// pendiente), no de la asignación activa. Los promedios son SOLO presentación: no se envían ni se guardan. Unidades y etiquetas provisionales.
// El intento pendiente vive en el padre: Volver no genera un capture_id nuevo mientras el resultado sea incierto.

type Props = {
    item: QualityBobbinInboxItem | null; // Bobina seleccionada; se ignora si hay un intento pendiente (manda la Bobina del intento)
    online: boolean;
    attempt: PendingPhysicalAttempt | null;
    setAttempt: (attempt: PendingPhysicalAttempt | null) => void;
    back: () => void;
    onSubmitted: () => void; // éxito: el padre cierra el formulario y refresca el inbox (la Bobina sigue pendiente)
    onSessionLost: () => void;
};

function Auto({ label, value }: { label: string; value: string }) {
    return <div className="min-w-0"><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 break-words font-bold">{value}</p></div>;
}

function Average({ label, value }: { label: string; value: string }) {
    return <div className="rounded-lg border bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-600">{label}</p><p className="mt-1 break-words text-lg font-black tabular-nums">{value}</p></div>;
}

export function QualityPhysicalCapture({ item, online, attempt, setAttempt, back, onSubmitted, onSessionLost }: Props) {
    const [draft, setDraft] = useState<PhysicalDraft>(attempt ? { ...attempt.draft } : EMPTY_PHYSICAL_DRAFT);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? PHYSICAL_MESSAGES.uncertain : null);
    const busy = useRef(false);
    const locked = sending || attempt !== null;
    const shown = physicalBobbinToShow(attempt, item);
    const averages = physicalAverages(draft);
    const set = (key: keyof PhysicalDraft) => (x: string) => setDraft(old => ({ ...old, [key]: x }));

    async function send() {
        if (busy.current || !shown) return; // evita el doble clic y las solicitudes simultáneas
        if (!online) return void setNotice(PHYSICAL_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            const created = createPhysicalAttempt(draft, shown, getDeviceKey());
            if (!created.ok) return void setNotice(created.errors.join(" "));
            current = created.attempt;
            setAttempt(current); // se conserva desde el primer POST: el reintento usa el mismo capture_id, los mismos valores y la misma Bobina
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitPhysicalAttempt(current, { post: submitPhysicalCapture, get: id => getPhysicalCapture(id) });
            if (outcome.kind === "submitted") { setAttempt(null); toast.success(outcome.message); return void onSubmitted(); }
            if (outcome.kind === "session") { setAttempt(null); return void onSessionLost(); }
            if (outcome.kind === "rejected") { setAttempt(null); return void setNotice(outcome.message); } // definitivo: el intento termina y los campos se desbloquean
            setNotice(outcome.message); // not_saved / incierto: se conserva el MISMO intento y se bloquean los campos
        } finally { busy.current = false; setSending(false); }
    }

    if (!shown) return null; // el padre solo monta este formulario con una Bobina seleccionada o con un intento pendiente
    const { bobbin, production } = shown;
    const field = (key: PhysicalKey) => {
        const unit = PHYSICAL_UNITS[key];
        return <div key={key}><Label htmlFor={`p20-${key}`}>{PHYSICAL_LABELS[key]} *</Label><div className="relative">
            <Input id={`p20-${key}`} disabled={locked} className={`mt-2 text-slate-950${unit ? " pr-14" : ""}`} type="text" inputMode="decimal" autoComplete="off" value={draft[key]} onChange={e => set(key)(e.target.value)}/>
            {unit && <span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">{unit}</span>}</div></div>;
    };

    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/>
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">Calidad · VINTO-P1-20</p><h1 className="mt-2 text-2xl font-black">Propiedades físicas de bobina</h1></div>
            <div className="grid gap-3 border-b bg-emerald-50 p-5 sm:grid-cols-2 md:grid-cols-4"><Auto label="Bobina" value={bobbin.code}/><Auto label="Máquina" value={bobbin.machine.code}/><Auto label="OT" value={production.work_order.number}/><Auto label="Línea / PV" value={`${production.line.line_code} / ${production.line.pv_reference}`}/>
                <Auto label="Artículo" value={`${production.line.article.code} · ${production.line.article.description}`}/><Auto label="Fecha operativa" value={production.operating_date}/><Auto label="Turno" value={production.shift.name}/><Auto label="Número de cortes (Producción)" value={bobbin.number_of_cuts}/>
                <Auto label="Gramaje nominal de Producción" value={grammageLabel(bobbin.grammage_g_m2)}/></div>
            {attempt && <div role="status" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{physicalPendingNotice(attempt)}</div>}
            <div className="border-b p-6"><h2 className="font-black">Mediciones de Calidad</h2><p className="mb-4 text-sm text-slate-700">Se registran solo las mediciones; los promedios se calculan aquí para mostrarlos y no se envían. Unidades y nombres provisionales hasta su validación con VINTO.</p>
                {PHYSICAL_GROUPS.map(group => <fieldset key={group.title} className="mb-5"><legend className="mb-2 text-sm font-black text-slate-800">{group.title}</legend>
                    <div className="grid gap-5 md:grid-cols-3">{group.keys.map(field)}</div></fieldset>)}
                <div><Label htmlFor="p20-observaciones">Observaciones</Label><Textarea id="p20-observaciones" disabled={locked} className="mt-2 text-slate-950" value={draft.observaciones} onChange={e => set("observaciones")(e.target.value)}/></div>
            </div>
            <div className="border-b p-6"><h2 className="font-black">Promedios (solo visualización)</h2><div className="mt-3 grid gap-3 md:grid-cols-3">
                {PHYSICAL_SERIES.map(series => <Average key={series} label={`Promedio ${SERIES_LABELS[series].toLowerCase()}${series === "espesor" ? " (mm)" : ""}`} value={averageLabel(averages[series])}/>)}</div>
                <p className="mt-2 text-xs text-slate-600">Media aritmética provisional de Comando, Medio y Extremo; «—» mientras falte una posición; «≈» indica un valor aproximado con dos decimales más que las mediciones. No se guarda ni decide la liberación.</p></div>
            {notice && <div role="alert" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{notice}</div>}
            <div className="flex flex-wrap justify-end gap-2 border-t p-5">
                <Button className="bg-[#146b4f]" disabled={sending} onClick={send}><Send className="mr-2 h-4 w-4"/>{sending ? "Enviando…" : attempt ? "Reintentar envío" : "Registrar propiedades físicas"}</Button>
            </div>
        </div></section></main>;
}
