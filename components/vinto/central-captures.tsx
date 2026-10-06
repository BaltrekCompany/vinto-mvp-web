"use client";

import { Button } from "@/components/ui/button";
import { PUNTO_MERMA_OPTIONS, TIPO_PRODUCTO_OPTIONS, optionLabel, type CentralCapture } from "@/lib/vinto/captures";
import { failureMessage } from "@/lib/vinto/orders";
import type { Resource } from "@/lib/vinto/use-central";

// F6 recientes leídos de PostgreSQL (GET /api/captures). Sin polling: se carga al entrar a Seguimiento y tras cada envío.
export function CentralCaptures({ resource, refresh }: { resource: Resource<CentralCapture[]>; refresh: () => void }) {
    return <div className="rounded-2xl border bg-white p-6 shadow-sm" aria-live="polite">
        <div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-black">Control de fardos · registros centrales</h2><p className="mt-1 text-sm text-slate-700">Últimos registros F6 guardados en PostgreSQL.</p></div>
            <Button variant="ghost" size="sm" onClick={refresh}>Actualizar</Button></div>
        {resource.status === "error" ? <p className="mt-4 text-sm text-amber-900">{failureMessage(resource.kind)}</p>
            : resource.status !== "ready" ? <p className="mt-4 text-sm text-slate-600">Consultando registros centrales…</p>
            : resource.data.length === 0 ? <p className="mt-4 text-sm text-slate-600">Todavía no hay registros F6 centrales.</p>
            : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[960px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600">{["Fecha operativa", "OT", "Línea / PV", "Producto", "Máquina", "Turno", "Fardos", "Punto de merma", "Tipo", "Peso (kg)", "Rev."].map(h => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
                <tbody>{resource.data.map(c => <tr key={c.id} className="border-b last:border-0"><td className="px-2 py-2">{c.operating_date}</td><td className="px-2 py-2">{c.work_order.number}</td><td className="px-2 py-2">{c.line.line_code} / {c.line.pv_reference}</td><td className="px-2 py-2">{c.line.article.description}</td><td className="px-2 py-2">{c.machine.code}</td><td className="px-2 py-2">{c.shift.name}</td><td className="px-2 py-2">{c.values.cantidad_fardos}</td><td className="px-2 py-2">{optionLabel(PUNTO_MERMA_OPTIONS, c.values.punto_merma)}</td><td className="px-2 py-2">{optionLabel(TIPO_PRODUCTO_OPTIONS, c.values.tipo_producto)}</td><td className="px-2 py-2">{c.values.peso_kg}</td><td className="px-2 py-2">{c.revision}</td></tr>)}</tbody></table></div>}
    </div>;
}
