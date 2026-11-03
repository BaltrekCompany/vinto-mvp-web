// MF-13-03B PR6: borrador LOCAL de una OT con varias líneas (antes de enviarla). PURO: sin red, sin DOM. Nada de esto se persiste ni se envía hasta que Jefatura confirma;
// el número de OT, el line_code y todo identificador son del servidor. Las máquinas y los productos que se ofrecen salen del catálogo que el BACKEND entrega a la sesión
// (GET /api/production/machines?articles=true); la validación local solo evita viajes inútiles, la autoridad (máquina existente/activa/en alcance, artículo permitido para esa
// máquina, cantidad, fechas, 200 líneas) sigue siendo el backend y su rechazo no deja ninguna OT parcial.

import { MAX_ORDER_LINES, type LineDraft } from "./orders.ts";

export type DraftRow = { key: string; machine: string; pv: string; code: string; qty: string; date: string };
export type DraftField = "pv" | "code" | "qty" | "date";
export type CatalogOf = (machine: string) => readonly { code: string }[];

export const emptyRow = (key: string, machine = ""): DraftRow => ({ key, machine, pv: "", code: "", qty: "", date: "" });

// Una fila nueva hereda la máquina de la última (multimáquina) o la de la primera (una sola máquina). Nunca supera el máximo del backend.
export function addRow(rows: readonly DraftRow[], key: string, multi: boolean): DraftRow[] {
    if (rows.length >= MAX_ORDER_LINES) return [...rows];
    const source = multi ? rows[rows.length - 1] : rows[0];
    return [...rows, emptyRow(key, source?.machine ?? "")];
}

// Retirar una fila SOLO afecta al borrador local. Siempre queda al menos una fila.
export function removeRow(rows: readonly DraftRow[], key: string): DraftRow[] {
    if (rows.length <= 1) return [...rows];
    return rows.filter((row) => row.key !== key);
}

// Cambiar la máquina de una fila invalida el producto elegido si ya no pertenece a esa máquina.
export function setMachine(rows: readonly DraftRow[], key: string, machine: string, catalog: CatalogOf, multi: boolean): DraftRow[] {
    const valid = (row: DraftRow, target: string) => (catalog(target).some((item) => item.code === row.code) ? row.code : "");
    if (!multi) return rows.map((row) => ({ ...row, machine, code: valid(row, machine) })); // una sola máquina: todas las filas la comparten
    return rows.map((row) => (row.key === key ? { ...row, machine, code: valid(row, machine) } : row));
}

export function setField(rows: readonly DraftRow[], key: string, field: DraftField, value: string): DraftRow[] {
    return rows.map((row) => (row.key === key ? { ...row, [field]: value } : row));
}

// Si la modalidad pasa a «una sola máquina» (p. ej. el servidor dejó de confirmar la multimáquina), todas las filas toman la máquina de la primera y se invalida el producto que ya no corresponde.
// Cuando `multi` es verdadero devuelve las mismas filas.
export function normalizeForMode(rows: readonly DraftRow[], multi: boolean, catalog: CatalogOf): DraftRow[] {
    if (multi || rows.length === 0) return [...rows];
    const machine = rows[0].machine;
    if (rows.every((row) => row.machine === machine)) return [...rows];
    return rows.map((row) => ({ ...row, machine, code: catalog(machine).some((item) => item.code === row.code) ? row.code : "" }));
}

export type RowError = { key: string; field: "machine" | DraftField; message: string };
export type DraftValidation = { ok: true; machineCode: string; lines: LineDraft[] } | { ok: false; errors: RowError[]; message: string };

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const QUANTITY = /^\d{1,12}(\.\d{1,3})?$/; // hasta 15 dígitos y 3 decimales, como Decimal(15, 3) del backend
export const PV_MAX = 100; // LineIn.pv_reference max_length

export function isRealDate(value: string): boolean {
    if (!DATE.test(value)) return false;
    const [year, month, day] = value.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function validateRows(rows: readonly DraftRow[], options: { multi: boolean; machines: readonly string[]; catalog: CatalogOf }): DraftValidation {
    if (rows.length === 0) return { ok: false, errors: [], message: "Agrega al menos una línea" };
    if (rows.length > MAX_ORDER_LINES) return { ok: false, errors: [], message: `Una OT admite hasta ${MAX_ORDER_LINES} líneas` };
    const errors: RowError[] = [];
    const fail = (row: DraftRow, field: RowError["field"], message: string) => errors.push({ key: row.key, field, message });
    const header = rows[0].machine;
    for (const row of rows) {
        if (!row.machine || !options.machines.includes(row.machine)) fail(row, "machine", "Selecciona una máquina");
        else if (!options.multi && row.machine !== header) fail(row, "machine", "Todas las líneas deben ser de la misma máquina");
        const pv = row.pv.trim();
        if (!pv) fail(row, "pv", "Falta el PV");
        else if (pv.length > PV_MAX) fail(row, "pv", `El PV admite hasta ${PV_MAX} caracteres`);
        if (!row.code || !options.catalog(row.machine).some((item) => item.code === row.code)) fail(row, "code", "Selecciona un producto de esa máquina");
        const qty = row.qty.trim();
        if (!QUANTITY.test(qty) || Number(qty) <= 0) fail(row, "qty", "Cantidad mayor que 0, con hasta 3 decimales");
        if (!isRealDate(row.date)) fail(row, "date", "Fecha de entrega inválida");
    }
    if (errors.length > 0) return { ok: false, errors, message: `Revisa ${new Set(errors.map((error) => error.key)).size} línea(s) del borrador` };
    const lines = rows.map((row): LineDraft => ({ pvReference: row.pv, articleCode: row.code, quantity: Number(row.qty.trim()), dueDate: row.date,
        ...(options.multi ? { machineCode: row.machine } : {}) })); // una sola máquina: payload histórico, sin machine_code por línea
    return { ok: true, machineCode: header, lines };
}

export type DraftSummary = { lines: number; machines: string[]; products: string[]; perMachine: Record<string, number> };

// Resumen previo al envío: solo cuenta lo que Jefatura ya eligió (filas incompletas no inventan máquinas ni productos).
export function summarize(rows: readonly DraftRow[]): DraftSummary {
    const machines: string[] = [], products: string[] = [], perMachine: Record<string, number> = {};
    for (const row of rows) {
        if (row.machine) { if (!machines.includes(row.machine)) machines.push(row.machine); perMachine[row.machine] = (perMachine[row.machine] ?? 0) + 1; }
        if (row.code && !products.includes(row.code)) products.push(row.code);
    }
    return { lines: rows.length, machines, products, perMachine };
}

export function summaryText(summary: DraftSummary): string {
    const machines = summary.machines.length === 0 ? "sin máquina" : `${summary.machines.length} máquina(s): ${summary.machines.join(", ")}`;
    return `${summary.lines} línea(s) · ${machines} · ${summary.products.length} producto(s)`;
}
