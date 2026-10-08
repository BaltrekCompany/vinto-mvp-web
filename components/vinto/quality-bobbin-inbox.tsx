"use client";

import { Button } from "@/components/ui/button";
import { CentralStatus } from "@/components/vinto/central-status";
import { grammageLabel, qualityStatusLabel, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import type { Resource } from "@/lib/vinto/use-central";

// Bobinas pendientes de Calidad leídas de PostgreSQL (GET /api/quality/bobbins). El listado es de solo lectura; la ÚNICA acción es abrir el
// control de humedad (VINTO-P1-19) de esa Bobina concreta. No libera ni rechaza.
// Sin polling: se carga al entrar a Ejecución de Calidad y con "Actualizar". No depende de la asignación activa.
const HEADERS = ["Bobina", "Máquina", "OT", "Línea / PV", "Artículo", "Fecha operativa", "Turno", "Hora inicio", "Hora fin", "Gramaje", "Diámetro (mm)", "Peso (kg)", "Cortes", "Observaciones", "Estado", "Acción"];

export function QualityBobbinInbox({ resource, refresh, onRegisterHumidity }: { resource: Resource<QualityBobbinInboxItem[]>; refresh: () => void; onRegisterHumidity: (item: QualityBobbinInboxItem) => void }) {
    if (resource.status !== "ready") return <CentralStatus state={resource} onRetry={refresh} title="No se pudo cargar el inbox de Calidad"/>;
    const items = resource.data;
    return <div className="min-w-0 max-w-full rounded-2xl border bg-white p-6 shadow-sm" aria-live="polite">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-black">Bobinas pendientes de Calidad</h2><p className="mt-1 text-sm text-slate-700">Bobinas producidas pendientes de evaluación. El listado no depende de la asignación actualmente activa.</p></div>
            <div className="flex items-center gap-3"><span className="text-sm font-bold">Pendientes: {items.length}</span><Button variant="ghost" size="sm" disabled={resource.refreshing} onClick={refresh}>{resource.refreshing ? "Actualizando…" : "Actualizar"}</Button></div></div>
        {items.length === 0 ? <p className="mt-4 text-sm text-slate-600">No hay bobinas pendientes de Calidad.</p>
            : <div className="mt-4 max-w-full overflow-x-auto"><table className="w-full min-w-[1320px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600">{HEADERS.map(h => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
                <tbody>{items.map(i => <tr key={i.bobbin.id} className="border-b last:border-0 align-top">
                    <td className="px-2 py-2 font-bold">{i.bobbin.code}</td><td className="px-2 py-2">{i.bobbin.machine.code}</td><td className="px-2 py-2">{i.production.work_order.number}</td>
                    <td className="px-2 py-2">{i.production.line.line_code} / {i.production.line.pv_reference}</td><td className="px-2 py-2"><b>{i.production.line.article.code}</b><br/>{i.production.line.article.description}</td>
                    <td className="px-2 py-2">{i.production.operating_date}</td><td className="px-2 py-2">{i.production.shift.name}</td><td className="px-2 py-2">{i.bobbin.start_time}</td><td className="px-2 py-2">{i.bobbin.end_time}</td>
                    <td className="px-2 py-2">{grammageLabel(i.bobbin.grammage_g_m2)}</td><td className="px-2 py-2">{i.bobbin.diameter_mm}</td><td className="px-2 py-2">{i.bobbin.weight_kg}</td><td className="px-2 py-2">{i.bobbin.number_of_cuts}</td>
                    <td className="px-2 py-2">{i.bobbin.notes ?? "—"}</td><td className="px-2 py-2"><span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-950">{qualityStatusLabel(i.quality.status)}</span></td>
                    <td className="px-2 py-2"><Button size="sm" className="bg-[#146b4f]" onClick={() => onRegisterHumidity(i)}>Registrar humedad</Button></td>
                </tr>)}</tbody></table></div>}
    </div>;
}
