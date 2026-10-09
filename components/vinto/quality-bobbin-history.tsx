"use client";

import { ArrowLeft, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { POSITIONS, POSITION_LABELS, computeHumidity, formatHumidity, type QualityCapture } from "@/lib/vinto/quality-captures";
import { qualityStatusLabel, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import {
    HISTORY_FAILURE_MESSAGES, HISTORY_MESSAGES, PLANT_TIME_ZONE, captureStatusLabel, formatPlantInstant, historyForBobbin,
    type QualityHistoryEntry, type QualityHistoryLoad, type QualityHistoryMeta,
} from "@/lib/vinto/quality-history";
import type { Resource } from "@/lib/vinto/use-central";

// Historial de controles de Calidad de UNA Bobina (GET /api/quality/bobbins/{id}/captures, PostgreSQL). SOLO lectura: no envía, no edita,
// no libera ni rechaza y no escribe en el navegador. El encabezado sale del item del inbox (Bobina seleccionada); los controles, en el orden
// del backend. La humedad de P1-19 se calcula con computeHumidity de Q2 SOLO para mostrarla. Nunca se muestran datos demo ni locales.

type Props = {
    item: QualityBobbinInboxItem; // Bobina seleccionada en el inbox
    resource: Resource<QualityHistoryLoad>;
    refresh: () => void;
    back: () => void;
};

function Fact({ label, value }: { label: string; value: string }) {
    return <div className="min-w-0"><dt className="text-xs font-semibold text-emerald-800">{label}</dt><dd className="mt-1 break-words font-bold">{value}</dd></div>;
}

function Meta({ label, value }: { label: string; value: string }) {
    return <div className="min-w-0"><dt className="text-xs font-semibold text-slate-600">{label}</dt><dd className="mt-0.5 break-words text-sm font-semibold">{value}</dd></div>;
}

function HumidityDetail({ capture }: { capture: QualityCapture }) {
    const values = capture.values;
    const humidity = computeHumidity(values); // misma fórmula y redondeo por posición que Q2; no se guarda
    const notes = values.observaciones;
    return <div className="mt-4">
        <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[480px] text-left text-sm">
            <caption className="sr-only">Pesos registrados y humedad calculada del control {capture.id}</caption>
            <thead><tr className="border-b text-xs uppercase text-slate-600"><th scope="col" className="px-2 py-2">Posición</th><th scope="col" className="px-2 py-2">Peso húmedo</th><th scope="col" className="px-2 py-2">Peso seco</th><th scope="col" className="px-2 py-2">Humedad (%)</th></tr></thead>
            <tbody>{POSITIONS.map(p => <tr key={p} className="border-b">
                <th scope="row" className="px-2 py-2 font-semibold">{POSITION_LABELS[p]}</th>
                <td className="px-2 py-2 tabular-nums">{values[`peso_humedo_${p}`]} kg</td><td className="px-2 py-2 tabular-nums">{values[`peso_seco_${p}`]} kg</td>
                <td className="px-2 py-2 font-bold tabular-nums">{formatHumidity(humidity[p])} %</td></tr>)}
                <tr><th scope="row" className="px-2 py-2 font-black" colSpan={3}>Promedio humedad</th><td className="px-2 py-2 font-black tabular-nums">{formatHumidity(humidity.promedio)} %</td></tr></tbody>
        </table></div>
        <p className="mt-2 text-xs text-slate-600">Humedad (%) = ((Peso húmedo − Peso seco) / Peso húmedo) × 100. Calculada solo para mostrarla; no se guarda ni decide la liberación.</p>
        {notes !== undefined && notes !== "" && <div className="mt-3"><p className="text-xs font-semibold text-slate-600">Observaciones</p><p className="mt-1 whitespace-pre-wrap break-words text-sm">{notes}</p></div>}
    </div>;
}

function EntryCard({ entry, index, total }: { entry: QualityHistoryEntry; index: number; total: number }) {
    const meta: QualityHistoryMeta = entry.meta;
    const headingId = `quality-control-${meta.id}`;
    return <li aria-labelledby={headingId} className="rounded-xl border bg-white p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 id={headingId} className="min-w-0 break-words font-black"><span className="sr-only">Control {index + 1} de {total}: </span>{meta.form.code} · {meta.form.name}</h3>
            <div className="flex flex-wrap gap-1.5"><span className="rounded-full border px-2 py-0.5 text-xs font-semibold">Versión {meta.form.version_number}</span><span className="rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-xs font-semibold">{captureStatusLabel(meta.status)}</span></div>
        </div>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <Meta label="Ensayo (hora de planta)" value={formatPlantInstant(meta.captured_at)}/>
            <Meta label="Envío (hora de planta)" value={meta.submitted_at === null ? HISTORY_MESSAGES.noSubmitted : formatPlantInstant(meta.submitted_at)}/>
        </dl>
        {entry.kind === "humidity" && <HumidityDetail capture={entry.capture}/>}
        {entry.kind === "unsupported" && <p className="mt-3 rounded-lg border bg-slate-50 p-3 text-sm text-slate-700">{HISTORY_MESSAGES.unsupported}</p>}
        {entry.kind === "invalid" && <p role="alert" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{HISTORY_MESSAGES.invalidEntry}</p>}
        <p className="mt-3 break-all text-xs text-slate-500">ID de captura: {meta.id}</p>
    </li>;
}

function Body({ view, refresh }: { view: Resource<QualityHistoryLoad>; refresh: () => void }) {
    if (view.status === "idle" || view.status === "loading") return <p role="status" className="p-6 text-sm font-semibold text-slate-700">Cargando historial de controles…</p>;
    // "error" del recurso: 401 (el padre ya vuelve al Login) o un fallo inesperado del cliente; el resto llega clasificado en data.
    const failure = view.status === "error" ? (view.kind === "session" ? "session" : "unavailable") : view.data.ok ? null : view.data.failure;
    if (failure !== null) return <div role="alert" className="m-6 rounded-xl border border-amber-300 bg-amber-50 p-5"><p className="font-black text-amber-950">No se pudo cargar el historial de controles</p><p className="mt-1 text-sm text-amber-950">{HISTORY_FAILURE_MESSAGES[failure]}</p>
        <Button className="mt-4 bg-[#146b4f]" disabled={view.refreshing} onClick={refresh}>{view.refreshing ? "Reintentando…" : "Reintentar"}</Button></div>;
    if (view.status !== "ready" || !view.data.ok) return null;
    const entries = view.data.history.entries;
    if (entries.length === 0) return <p className="p-6 text-sm text-slate-700">{HISTORY_MESSAGES.empty}</p>;
    return <ol className="space-y-4 p-4 md:p-6">{entries.map((e, i) => <EntryCard key={e.meta.id} entry={e} index={i} total={entries.length}/>)}</ol>;
}

export function QualityBobbinHistory({ item, resource, refresh, back }: Props) {
    const { bobbin, production, quality } = item;
    const view = historyForBobbin(resource, bobbin.id); // un resultado tardío de otra Bobina nunca se presenta
    const count = view.status === "ready" && view.data.ok ? view.data.history.entries.length : null;
    const refreshing = (view.status === "ready" || view.status === "error") && view.refreshing;
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950">
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver al inbox</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">Calidad · Solo lectura</p><h1 className="mt-2 text-2xl font-black">Historial de controles · Bobina {bobbin.code}</h1></div>
            <dl className="grid gap-3 border-b bg-emerald-50 p-5 sm:grid-cols-2 md:grid-cols-4">
                <Fact label="Bobina" value={bobbin.code}/><Fact label="Máquina" value={bobbin.machine.code}/><Fact label="OT" value={production.work_order.number}/><Fact label="Línea / PV" value={`${production.line.line_code} / ${production.line.pv_reference}`}/>
                <Fact label="Artículo" value={`${production.line.article.code} · ${production.line.article.description}`}/><Fact label="Fecha operativa" value={production.operating_date}/><Fact label="Turno" value={production.shift.name}/><Fact label="Estado de Calidad (inbox)" value={qualityStatusLabel(quality.status)}/>
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5">
                <div><h2 className="font-black">Controles registrados{count !== null && `: ${count}`}</h2><p className="mt-1 text-sm text-slate-700">Del más reciente al más antiguo. Horas de ensayo y envío en hora de planta ({PLANT_TIME_ZONE}).</p></div>
                <Button variant="outline" size="sm" disabled={view.status !== "ready" || refreshing} onClick={refresh}><RefreshCw className="mr-2 h-4 w-4"/>{refreshing ? "Actualizando…" : "Actualizar"}</Button>
            </div>
            <div aria-live="polite" aria-busy={view.status === "loading" || refreshing}><Body view={view} refresh={refresh}/></div>
        </div></section></main>;
}
