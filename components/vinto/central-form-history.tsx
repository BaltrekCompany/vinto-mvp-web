"use client";

import { Button } from "@/components/ui/button";
import { failureMessage } from "@/lib/vinto/orders";
import type { P110Capture } from "@/lib/vinto/p1-10";
import { shortHour, type P112Capture } from "@/lib/vinto/p1-12";
import { ORIGEN_MERMA_OPTIONS, TIPO_MERMA_OPTIONS, type P116Capture } from "@/lib/vinto/p1-16";
import { optionLabel } from "@/lib/vinto/capture-core";
import type { P129Capture } from "@/lib/vinto/p1-29";
import type { Resource } from "@/lib/vinto/use-central";

// Historial CENTRAL (PostgreSQL) de P1-10, P1-12, P1-16 y P1-29, con el parser ESTRICTO de cada formulario: nunca datos demo ni locales. Sin polling; se refresca al entrar y tras cada envío.
// Un 422 al listar significa que el backend no habilita ese formulario: se informa tal cual, sin lista vacía engañosa.

function Shell({ title, note, resource, refresh, headers, children }: { title: string; note: string; resource: Resource<unknown[]>; refresh: () => void; headers: string[]; children: React.ReactNode }) {
    return <div className="rounded-2xl border bg-white p-6 shadow-sm" aria-live="polite" data-history={title}>
        <div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-black">{title}</h2><p className="mt-1 text-sm text-slate-700">{note}</p></div><Button variant="ghost" size="sm" onClick={refresh}>Actualizar</Button></div>
        {resource.status === "error" ? <p className="mt-4 text-sm text-amber-900">{resource.kind === "invalid" ? "El backend no habilita este formulario para tu sesión." : failureMessage(resource.kind)}</p>
            : resource.status !== "ready" ? <p className="mt-4 text-sm text-slate-600">Consultando registros centrales…</p>
            : resource.data.length === 0 ? <p className="mt-4 text-sm text-slate-600">Todavía no hay registros centrales de este formulario.</p>
            : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[820px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600">{headers.map(h => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>}
    </div>;
}

const common = (c: P110Capture | P112Capture | P116Capture | P129Capture) => <><td className="px-2 py-2">{c.operating_date}</td><td className="px-2 py-2">{c.work_order.number}</td><td className="px-2 py-2">{c.line.line_code} / {c.line.pv_reference}</td><td className="px-2 py-2">{c.machine.code}</td><td className="px-2 py-2">{c.shift.name}</td></>;

export function P110History({ resource, refresh }: { resource: Resource<P110Capture[]>; refresh: () => void }) {
    return <Shell title="Registro de fardos (P1-10) · registros centrales" note="Ficha candidata: registros guardados en PostgreSQL." resource={resource} refresh={refresh} headers={["Fecha operativa", "OT", "Línea / PV", "Máquina", "Turno", "Código / producto", "N.º de fardo", "Peso fardo", "Rev."]}>
        {resource.status === "ready" && resource.data.map(c => <tr key={c.id} className="border-b last:border-0" data-capture={c.id}>{common(c)}<td className="px-2 py-2">{c.values.codigo_numero_de_producto}</td><td className="px-2 py-2">{c.values.numero_de_fardo}</td><td className="px-2 py-2">{c.values.peso_fardo}</td><td className="px-2 py-2">{c.revision}</td></tr>)}
    </Shell>;
}

export function P129History({ resource, refresh }: { resource: Resource<P129Capture[]>; refresh: () => void }) {
    return <Shell title="Producción Tubetera (P1-29) · registros centrales" note="Ficha candidata: registros guardados en PostgreSQL." resource={resource} refresh={refresh} headers={["Fecha operativa", "OT", "Línea / PV", "Máquina", "Turno", "Lote", "Fecha de producción", "Rodelas", "Formatos", "Rev."]}>
        {resource.status === "ready" && resource.data.map(c => <tr key={c.id} className="border-b last:border-0" data-capture={c.id}>{common(c)}<td className="px-2 py-2">{c.values.lote_de_produccion}</td><td className="px-2 py-2">{c.values.fecha_de_produccion}</td><td className="px-2 py-2">{c.values._groups.rodelas?.length ?? 0}</td><td className="px-2 py-2">{c.values._groups.formatos?.length ?? 0}</td><td className="px-2 py-2">{c.revision}</td></tr>)}
    </Shell>;
}

export function P116History({ resource, refresh }: { resource: Resource<P116Capture[]>; refresh: () => void }) {
    return <Shell title="Control de merma (P1-16) · registros centrales" note="Ficha candidata (hipótesis de prueba, una pesada por captura): registros guardados en PostgreSQL." resource={resource} refresh={refresh} headers={["Fecha operativa", "OT", "Línea / PV", "Máquina", "Turno", "Tipo de merma", "Origen", "Peso real (kg)", "Rev."]}>
        {resource.status === "ready" && resource.data.map(c => <tr key={c.id} className="border-b last:border-0" data-capture={c.id}>{common(c)}<td className="px-2 py-2">{optionLabel(TIPO_MERMA_OPTIONS, c.values.tipo_merma)}</td><td className="px-2 py-2">{optionLabel(ORIGEN_MERMA_OPTIONS, c.values.origen_merma)}</td><td className="px-2 py-2">{c.values.peso_merma_kg}</td><td className="px-2 py-2">{c.revision}</td></tr>)}
    </Shell>;
}

export function P112History({ resource, refresh }: { resource: Resource<P112Capture[]>; refresh: () => void }) {
    return <Shell title="Producción por pallet (P1-12) · registros centrales" note="Ficha candidata (hipótesis de prueba, un pallet por captura): registros guardados en PostgreSQL. El número oficial de pallet está pendiente." resource={resource} refresh={refresh} headers={["Fecha operativa", "OT", "Línea / PV", "Máquina", "Turno", "Jabas", "Hora inicio", "Hora fin", "Rev."]}>
        {resource.status === "ready" && resource.data.map(c => <tr key={c.id} className="border-b last:border-0" data-capture={c.id}>{common(c)}<td className="px-2 py-2">{c.values.cantidad_jabas}</td><td className="px-2 py-2">{shortHour(c.values.hora_inicio)}</td><td className="px-2 py-2">{shortHour(c.values.hora_fin)}</td><td className="px-2 py-2">{c.revision}</td></tr>)}
    </Shell>;
}
