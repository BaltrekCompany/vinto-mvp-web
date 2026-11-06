"use client";

import { isSelectable, unselectableReason, type ActiveLineItem, type ActiveLines } from "@/lib/vinto/active-lines";
import { programmedQuantityText, captureContextOf } from "@/lib/vinto/orders";
import { executionStatus, isStartedAssignment, MACHINE_EXECUTION_LABELS, type MachineExecution } from "@/lib/vinto/machine-execution";

type Props = { machine: string; lines: ActiveLines; selectedId: string | null; onChoose: (assignmentId: string) => void; onRefresh: () => void; refreshing?: boolean; execution?: MachineExecution | null; verified?: boolean };

function Option({ item, machine, selected, onChoose, execution, verified }: { item: ActiveLineItem; machine: string; selected: boolean; onChoose: (id: string) => void; execution: MachineExecution | null; verified: boolean }) {
    const a = item.assignment, c = captureContextOf(a), programmed = programmedQuantityText(c), why = unselectableReason(item);
    const status = execution ? executionStatus(execution, a.id) : null;
    const enabled = verified && isSelectable(item) && execution !== null && isStartedAssignment(execution, a.id);
    return <li>
        <label data-line={a.line.line_code} className={`flex gap-3 rounded-xl border p-3 ${enabled ? "cursor-pointer" : "cursor-not-allowed opacity-70"} ${selected ? "border-emerald-500 bg-emerald-50" : "bg-white"}`}>
            <input type="radio" name={`line-${machine}`} className="mt-1 h-5 w-5 shrink-0" value={a.id} checked={selected} disabled={!enabled} onChange={() => onChoose(a.id)}/>
            <span className="min-w-0 text-sm">
                <b className="block">{`${a.work_order.number} · ${a.line.line_code} · ${a.line.article.description}`}</b>
                <span className="block text-slate-700">{`${a.line.article.code} · PV ${a.line.pv_reference} · ${a.machine.code}`}</span>
                <span className="block text-slate-700">{`${a.shift.name} · ${a.operating_date}${programmed ? ` · Programado: ${programmed}` : ""}`}</span>
                {status && <span className={`mt-1 block font-bold ${status === "in_production" ? "text-emerald-800" : "text-amber-900"}`}>{MACHINE_EXECUTION_LABELS[status]}</span>}
                {!verified && <span className="mt-1 block font-bold text-amber-900">Verificando ejecución con el servidor…</span>}
                {why && <span className="mt-1 block font-bold text-amber-900">{why}</span>}
                {verified && execution?.line_execution === true && status === null && <span className="mt-1 block font-bold text-amber-900">Ejecución no verificada. Solicita revisión.</span>}
            </span>
        </label>
    </li>;
}

// Varias líneas activas en la misma máquina: el operario elige UNA, de forma explícita (nunca se preselecciona). Solo ofrece lo que el servidor devolvió para esta sesión y máquina.
export function LineSelector({ machine, lines, selectedId, onChoose, onRefresh, refreshing = false, execution = null, verified = false }: Props) {
    return <fieldset data-line-selector="" className="mt-5 rounded-2xl border border-amber-300 bg-amber-50 p-4">
        <legend className="px-1 text-base font-black">{execution?.line_execution ? `Líneas habilitadas en ${machine}` : `Líneas activas en ${machine}`}</legend>
        <p className="mb-3 text-sm" role={selectedId ? undefined : "status"}>{execution?.line_execution ? "Solo puedes elegir la línea que Supervisión haya iniciado; las demás permanecen visibles en espera." : selectedId ? "Línea elegida. Puedes cambiarla antes de capturar." : "Elige la línea que vas a capturar. No se selecciona ninguna automáticamente."}</p>
        <ul className="grid gap-2">{lines.items.map((item) => <Option key={item.assignment.id} machine={machine} item={item} selected={item.assignment.id === selectedId} onChoose={onChoose} execution={execution} verified={verified}/>)}</ul>
        <button type="button" className="mt-3 min-h-11 rounded-md border bg-white px-3 text-sm font-bold disabled:opacity-60" onClick={onRefresh} disabled={refreshing}>Actualizar líneas</button>
    </fieldset>;
}
