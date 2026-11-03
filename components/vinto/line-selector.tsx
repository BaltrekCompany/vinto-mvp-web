"use client";

import { isSelectable, unselectableReason, type ActiveLineItem, type ActiveLines } from "@/lib/vinto/active-lines";
import { programmedQuantityText, captureContextOf } from "@/lib/vinto/orders";

type Props = { machine: string; lines: ActiveLines; selectedId: string | null; onChoose: (assignmentId: string) => void; onRefresh: () => void; refreshing?: boolean };

function Option({ item, machine, selected, onChoose }: { item: ActiveLineItem; machine: string; selected: boolean; onChoose: (id: string) => void }) {
    const a = item.assignment, c = captureContextOf(a), programmed = programmedQuantityText(c), why = unselectableReason(item), enabled = isSelectable(item);
    return <li>
        <label data-line={a.line.line_code} className={`flex gap-3 rounded-xl border p-3 ${enabled ? "cursor-pointer" : "cursor-not-allowed opacity-70"} ${selected ? "border-emerald-500 bg-emerald-50" : "bg-white"}`}>
            <input type="radio" name={`line-${machine}`} className="mt-1 h-5 w-5 shrink-0" value={a.id} checked={selected} disabled={!enabled} onChange={() => onChoose(a.id)}/>
            <span className="min-w-0 text-sm">
                <b className="block">{`${a.work_order.number} · ${a.line.line_code} · ${a.line.article.description}`}</b>
                <span className="block text-slate-700">{`${a.line.article.code} · PV ${a.line.pv_reference} · ${a.machine.code}`}</span>
                <span className="block text-slate-700">{`${a.shift.name} · ${a.operating_date}${programmed ? ` · Programado: ${programmed}` : ""}`}</span>
                {why && <span className="mt-1 block font-bold text-amber-900">{why}</span>}
            </span>
        </label>
    </li>;
}

// Varias líneas activas en la misma máquina: el operario elige UNA, de forma explícita (nunca se preselecciona). Solo ofrece lo que el servidor devolvió para esta sesión y máquina.
export function LineSelector({ machine, lines, selectedId, onChoose, onRefresh, refreshing = false }: Props) {
    return <fieldset data-line-selector="" className="mt-5 rounded-2xl border border-amber-300 bg-amber-50 p-4">
        <legend className="px-1 text-base font-black">{`Líneas activas en ${machine}`}</legend>
        <p className="mb-3 text-sm" role={selectedId ? undefined : "status"}>{selectedId ? "Línea elegida. Puedes cambiarla antes de capturar." : "Elige la línea que vas a capturar. No se selecciona ninguna automáticamente."}</p>
        <ul className="grid gap-2">{lines.items.map((item) => <Option key={item.assignment.id} machine={machine} item={item} selected={item.assignment.id === selectedId} onChoose={onChoose}/>)}</ul>
        <button type="button" className="mt-3 min-h-11 rounded-md border bg-white px-3 text-sm font-bold disabled:opacity-60" onClick={onRefresh} disabled={refreshing}>Actualizar líneas</button>
    </fieldset>;
}
