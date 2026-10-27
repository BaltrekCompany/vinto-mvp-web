"use client";

import { Button } from "@/components/ui/button";
import type { CandidateScreen } from "@/lib/vinto/candidate-screen";
import type { CandidateCapture } from "@/lib/vinto/candidate-form";
import { failureMessage } from "@/lib/vinto/orders";
import type { Resource } from "@/lib/vinto/use-central";

// Historial CENTRAL (PostgreSQL) de un formulario candidato declarativo, con el parser ESTRICTO del formulario: nunca datos demo ni locales. Una columna por campo declarado; los valores se muestran
// tal cual se guardaron (sin sumas, totales ni cálculos). Sin polling: se refresca al entrar y tras cada envío. Un 422 al listar significa que el backend no habilita ese formulario.
export function CandidateHistory({ candidate, resource, refresh }: { candidate: CandidateScreen; resource: Resource<CandidateCapture[]>; refresh: () => void }) {
    const title = `${candidate.title} (${candidate.code.replace("VINTO-", "")}) · registros centrales`;
    const machineLevel = candidate.form.context === "machine"; // Calidad por máquina: sin OT ni línea; con hora de registro y usuario
    const bobbinLevel = candidate.form.context === "bobbin"; // Calidad por bobina: con la bobina, OT y línea de la F3 de origen; sin asignación
    // MF-08: además de los campos vigentes, las columnas calculadas por el backend y los campos retirados de versiones anteriores (solo lectura, marcados «versión anterior»).
    const extra = [...candidate.form.calculated, ...candidate.form.legacy];
    const extraLabels = [...candidate.form.calculated.map(f => f.label), ...candidate.form.legacy.map(f => `${f.label} (versión anterior)`)];
    const headers = bobbinLevel ? ["Fecha operativa", "Bobina", "OT", "Línea / PV", "Máquina", "Turno", "Hora de registro", ...candidate.form.fields.map(f => f.label), ...extraLabels, "Rev."] : machineLevel ? ["Fecha operativa", "Máquina", "Turno", "Hora de registro", "Registrado por", ...candidate.form.fields.map(f => f.label), ...extraLabels, "Rev."] : ["Fecha operativa", "OT", "Línea / PV", "Máquina", "Turno", ...candidate.form.fields.map(f => f.label), ...extraLabels, "Rev."];
    return <div className="rounded-2xl border bg-white p-6 shadow-sm" aria-live="polite" data-history={title}>
        <div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-black">{title}</h2><p className="mt-1 text-sm text-slate-700">{candidate.historyNote}</p></div><Button variant="ghost" size="sm" onClick={refresh}>Actualizar</Button></div>
        {resource.status === "error" ? <p className="mt-4 text-sm text-amber-900">{resource.kind === "invalid" ? "El backend no habilita este formulario para tu sesión." : failureMessage(resource.kind)}</p>
            : resource.status !== "ready" ? <p className="mt-4 text-sm text-slate-600">Consultando registros centrales…</p>
            : resource.data.length === 0 ? <p className="mt-4 text-sm text-slate-600">Todavía no hay registros centrales de este formulario.</p>
            : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[1100px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600">{headers.map(h => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
                <tbody>{resource.data.map(c => <tr key={c.id} className="border-b last:border-0" data-capture={c.id}>
                    {bobbinLevel ? <><td className="px-2 py-2">{c.operating_date}</td><td className="px-2 py-2 font-bold">{c.bobbin?.code ?? "—"}</td><td className="px-2 py-2">{c.work_order?.number ?? "—"}</td><td className="px-2 py-2">{c.line ? `${c.line.line_code} / ${c.line.pv_reference}` : "—"}</td><td className="px-2 py-2">{c.machine.code}</td><td className="px-2 py-2">{c.shift.name}</td><td className="px-2 py-2">{c.captured_at}</td></>
                        : machineLevel ? <><td className="px-2 py-2">{c.operating_date}</td><td className="px-2 py-2">{c.machine.code}</td><td className="px-2 py-2">{c.shift.name}</td><td className="px-2 py-2">{c.captured_at}</td><td className="px-2 py-2">{c.recorded_by?.display_name ?? "—"}</td></>
                        : <><td className="px-2 py-2">{c.operating_date}</td><td className="px-2 py-2">{c.work_order?.number ?? "—"}</td><td className="px-2 py-2">{c.line ? `${c.line.line_code} / ${c.line.pv_reference}` : "—"}</td><td className="px-2 py-2">{c.machine.code}</td><td className="px-2 py-2">{c.shift.name}</td></>}
                    {[...candidate.form.fields, ...extra].map(f => <td key={f.key} className="px-2 py-2">{c.values[f.key] ?? ""}</td>)}<td className="px-2 py-2">{c.revision}</td></tr>)}</tbody></table></div>}
    </div>;
}
