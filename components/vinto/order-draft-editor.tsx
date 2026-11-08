"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { addRow, removeRow, setField, setMachine, summarize, summaryText, type CatalogOf, type DraftField, type DraftRow, type RowError } from "@/lib/vinto/order-draft";
import { MAX_ORDER_LINES } from "@/lib/vinto/orders";

export type MachineOption = { code: string; name: string };
export type CatalogItem = { code: string; name: string };

type Props = {
    rows: DraftRow[];
    onRows: (rows: DraftRow[]) => void;
    machines: readonly MachineOption[];
    catalog: (machine: string) => readonly CatalogItem[];
    multi: boolean; // true = cada fila elige su máquina; false = todas comparten la de la primera fila (OT tradicional)
    disabled: boolean;
    errors: readonly RowError[];
    nextKey: () => string;
    fixedRows?: boolean; // una sola fila sin agregar ni retirar (formulario de «añadir línea»)
    lockMachine?: boolean; // E2-A: edición de línea persistida, máquina inmutable
};

const field = "h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-950";
const invalid = "border-red-500";

// Tabla EDITABLE del borrador local de una OT: máquina, PV, producto, cantidad y entrega por fila. Agregar o retirar filas solo cambia el borrador del navegador: no toca nada persistido.
// Cuando cambia la máquina de una fila se invalida su producto si ya no corresponde. El número de OT y el código de línea NO existen aquí: los asigna el servidor.
export function OrderDraftEditor({ rows, onRows, machines, catalog, multi, disabled, errors, nextKey, fixedRows = false, lockMachine = false }: Props) {
    const catalogOf: CatalogOf = (machine) => catalog(machine);
    const errorOf = (key: string, name: RowError["field"]) => errors.find(error => error.key === key && error.field === name);
    const cell = (row: DraftRow, name: DraftField, label: string, type: string) => {
        const error = errorOf(row.key, name);
        return <td className="p-2 align-top"><Input aria-label={label} aria-invalid={error ? true : undefined} disabled={disabled} type={type} className={`text-slate-950 ${error ? invalid : ""}`} value={row[name]} onChange={e => onRows(setField(rows, row.key, name, e.target.value))}/>{error && <p role="alert" className="mt-1 text-xs text-red-700">{error.message}</p>}</td>;
    };
    const summary = summarize(rows);
    return <div data-order-draft="" className="space-y-3">
        <div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-2">#</th><th className="p-2">Máquina</th><th className="p-2">PV</th><th className="p-2">Producto</th><th className="p-2">Cantidad</th><th className="p-2">Entrega</th>{!fixedRows && <th className="p-2"><span className="sr-only">Acciones</span></th>}</tr></thead>
            <tbody>{rows.map((row, index) => {
                const machineError = errorOf(row.key, "machine"), codeError = errorOf(row.key, "code");
                const shared = !multi && index > 0; // en una OT tradicional la máquina la fija la primera fila
                return <tr key={row.key} data-draft-row="" className="border-t">
                    <td className="p-2 align-top font-bold">{index + 1}</td>
                    <td className="p-2 align-top"><select aria-label={`Máquina de la fila ${index + 1}`} aria-invalid={machineError ? true : undefined} disabled={disabled || shared || lockMachine} className={`${field} ${machineError ? invalid : ""}`} value={row.machine} onChange={e => onRows(setMachine(rows, row.key, e.target.value, catalogOf, multi))}><option value="">Seleccionar…</option>{machines.map(m => <option key={m.code} value={m.code}>{m.code}</option>)}</select>{machineError && <p role="alert" className="mt-1 text-xs text-red-700">{machineError.message}</p>}</td>
                    {cell(row, "pv", `PV de la fila ${index + 1}`, "text")}
                    <td className="p-2 align-top"><select aria-label={`Producto de la fila ${index + 1}`} aria-invalid={codeError ? true : undefined} disabled={disabled || !row.machine} className={`${field} ${codeError ? invalid : ""}`} value={row.code} onChange={e => onRows(setField(rows, row.key, "code", e.target.value))}><option value="">Seleccionar…</option>{catalog(row.machine).map(p => <option key={p.code} value={p.code}>{p.code} · {p.name}</option>)}</select>{codeError && <p role="alert" className="mt-1 text-xs text-red-700">{codeError.message}</p>}</td>
                    {cell(row, "qty", `Cantidad de la fila ${index + 1}`, "number")}
                    {cell(row, "date", `Entrega de la fila ${index + 1}`, "date")}
                    {!fixedRows && <td className="p-2 align-top"><Button type="button" size="sm" variant="outline" aria-label={`Retirar la fila ${index + 1}`} disabled={disabled || rows.length <= 1} onClick={() => onRows(removeRow(rows, row.key))}>Retirar</Button></td>}
                </tr>;
            })}</tbody></table></div>
        {!fixedRows && <div className="flex flex-wrap items-center justify-between gap-3">
            <Button type="button" variant="outline" disabled={disabled || rows.length >= MAX_ORDER_LINES} onClick={() => onRows(addRow(rows, nextKey(), multi))}>Agregar línea</Button>
            <p data-draft-summary="" className="text-sm text-slate-700" role="status">Borrador local: {summaryText(summary)}{rows.length >= MAX_ORDER_LINES ? ` (máximo ${MAX_ORDER_LINES})` : ""}</p>
        </div>}
    </div>;
}
