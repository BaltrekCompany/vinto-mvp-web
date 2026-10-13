// Grupos repetibles de las capturas centrales (M3-A), parte CLIENTE y PURA (sin red, sin DOM): especificación tipada de grupos, borradores por fila, operaciones de filas
// inmutables, validación/normalización por fila y parser estricto de la respuesta. El contrato con el backend es: `values` conserva los campos simples y lleva los grupos
// en la propiedad reservada `_groups` = { código_de_grupo: [ {clave: valor}, ... ] } con las filas EN ORDEN (la posición es el orden; no hay ids ni row_number del cliente).
//
// Reglas de seguridad: lo que se envía sale de la ESPECIFICACIÓN del formulario (claves y tipos conocidos), nunca de campos arbitrarios; las claves internas de la fila
// (`rowKey`, solo para React) no viajan; los límites (mínimo/máximo/repetible) son los de la definición, no se inventa ninguno. El backend revalida todo.

import { DECIMAL, MAX_DECIMAL_CHARS, isRec, isStr, type Option, type Rec } from "./capture-core.ts";

export const GROUPS_KEY = "_groups";

export type GroupFieldKind = "text" | "textarea" | "integer" | "decimal" | "choice";
export type GroupFieldSpec = { key: string; label: string; kind: GroupFieldKind; required: boolean; options?: readonly Option[]; unit?: string };
export type GroupSpec = { code: string; label: string; repeatable: boolean; minRows: number; maxRows: number | null; fields: readonly GroupFieldSpec[] };

// Borrador de una fila: `rowKey` es SOLO una clave local para la lista de React (nunca se envía); `cells` guarda el texto tecleado por campo.
export type RowDraft = { readonly rowKey: string; readonly cells: Readonly<Record<string, string>> };
export type GroupDrafts = Readonly<Record<string, readonly RowDraft[]>>;
export type RowError = { group: string; row: number | null; field?: string; message: string }; // row es 1-based; null = error del grupo

let counter = 0;
export const newRowKey = (): string => `row-${++counter}`;

// ---- operaciones de filas (inmutables: devuelven listas nuevas y no tocan ningún intento ya creado) ---------------------------------------------

export function emptyRow(spec: GroupSpec, makeKey: () => string = newRowKey): RowDraft {
    return { rowKey: makeKey(), cells: Object.fromEntries(spec.fields.map((f) => [f.key, ""])) };
}

const limit = (spec: GroupSpec) => (spec.repeatable ? spec.maxRows : Math.min(1, spec.maxRows ?? 1));
export const canAddRow = (spec: GroupSpec, rows: readonly RowDraft[]): boolean => { const max = limit(spec); return max === null || rows.length < max; };
export const canRemoveRow = (spec: GroupSpec, rows: readonly RowDraft[]): boolean => rows.length > spec.minRows;

export function addRow(spec: GroupSpec, rows: readonly RowDraft[], makeKey: () => string = newRowKey): readonly RowDraft[] {
    return canAddRow(spec, rows) ? [...rows, emptyRow(spec, makeKey)] : rows;
}
export function removeRow(spec: GroupSpec, rows: readonly RowDraft[], rowKey: string): readonly RowDraft[] {
    return canRemoveRow(spec, rows) ? rows.filter((r) => r.rowKey !== rowKey) : rows;
}
export function setCell(rows: readonly RowDraft[], rowKey: string, field: string, value: string): readonly RowDraft[] {
    return rows.map((r) => (r.rowKey === rowKey ? { rowKey: r.rowKey, cells: { ...r.cells, [field]: value } } : r));
}
// Estado inicial: tantas filas vacías como el mínimo declarado.
export const initialRows = (spec: GroupSpec, makeKey: () => string = newRowKey): readonly RowDraft[] => Array.from({ length: spec.minRows }, () => emptyRow(spec, makeKey));
export const initialDrafts = (specs: readonly GroupSpec[], makeKey: () => string = newRowKey): GroupDrafts => Object.fromEntries(specs.map((s) => [s.code, initialRows(s, makeKey)]));

// ---- validación y normalización por fila --------------------------------------------------------------------------------------------------------

function normalizeCell(field: GroupFieldSpec, raw: string): { value: unknown } | { error: string } | null {
    const text = raw.trim();
    if (!text) return null;
    if (field.kind === "text" || field.kind === "textarea") return { value: text };
    if (field.kind === "choice") return field.options?.some((o) => o.value === text) ? { value: text } : { error: "selecciona una opción válida." };
    if (field.kind === "integer") { const n = /^-?\d+$/.test(text) ? Number(text) : NaN; return Number.isSafeInteger(n) ? { value: n } : { error: "ingresa un número entero." }; }
    const decimal = /^-?\d+,\d+$/.test(text) ? text.replace(",", ".") : text; // coma decimal habitual; se envía con punto y como TEXTO (nunca pasa por float)
    return DECIMAL.test(decimal) && decimal.length <= MAX_DECIMAL_CHARS ? { value: decimal } : { error: "ingresa un número decimal." };
}

export function validateGroup(spec: GroupSpec, rows: readonly RowDraft[]): { ok: true; rows: Record<string, unknown>[] } | { ok: false; errors: RowError[] } {
    const errors: RowError[] = [];
    const max = limit(spec);
    if (rows.length < spec.minRows) errors.push({ group: spec.code, row: null, message: `${spec.label}: se requieren al menos ${spec.minRows} filas.` });
    if (max !== null && rows.length > max) errors.push({ group: spec.code, row: null, message: `${spec.label}: máximo ${max} filas.` });
    const clean: Record<string, unknown>[] = [];
    rows.forEach((row, index) => {
        const out: Record<string, unknown> = {};
        for (const field of spec.fields) {
            const cell = normalizeCell(field, row.cells[field.key] ?? "");
            if (cell === null) { if (field.required) errors.push({ group: spec.code, row: index + 1, field: field.key, message: `${field.label}: es obligatorio.` }); }
            else if ("error" in cell) errors.push({ group: spec.code, row: index + 1, field: field.key, message: `${field.label}: ${cell.error}` });
            else out[field.key] = cell.value;
        }
        if (Object.keys(out).length === 0 && !errors.some((e) => e.group === spec.code && e.row === index + 1)) errors.push({ group: spec.code, row: index + 1, message: "La fila no tiene valores." });
        clean.push(out);
    });
    return errors.length ? { ok: false, errors } : { ok: true, rows: clean };
}

// Todos los grupos de la especificación -> { código: filas } listo para `values._groups` (las filas conservan su orden).
export function buildGroups(specs: readonly GroupSpec[], drafts: GroupDrafts): { ok: true; groups: Record<string, Record<string, unknown>[]> } | { ok: false; errors: RowError[] } {
    const errors: RowError[] = [];
    const groups: Record<string, Record<string, unknown>[]> = {};
    for (const spec of specs) {
        const result = validateGroup(spec, drafts[spec.code] ?? []);
        if (result.ok) groups[spec.code] = result.rows; else errors.push(...result.errors);
    }
    return errors.length ? { ok: false, errors } : { ok: true, groups };
}

export const buildGroupedValues = (simple: Record<string, unknown>, groups: Record<string, Record<string, unknown>[]>): Record<string, unknown> => ({ ...simple, [GROUPS_KEY]: groups });

export function errorsFor(errors: readonly RowError[], group: string, row: number | null): string[] {
    return errors.filter((e) => e.group === group && e.row === row).map((e) => e.message);
}

// ---- lectura: parser ESTRICTO de `_groups` en la respuesta ------------------------------------------------------------------------------------------

function parseCellValue(field: GroupFieldSpec, value: unknown): unknown | undefined {
    if (field.kind === "integer") return typeof value === "number" && Number.isSafeInteger(value) ? value : undefined;
    if (field.kind === "decimal") { const text = typeof value === "number" && Number.isFinite(value) ? String(value) : value; return typeof text === "string" && DECIMAL.test(text) ? text : undefined; }
    if (field.kind === "choice") return typeof value === "string" && field.options?.some((o) => o.value === value) ? value : undefined;
    return isStr(value) ? value : undefined;
}

// Devuelve { código: [fila, ...] } con TODOS los grupos declarados (lista vacía si no hay filas) o null si algo no cumple la especificación:
// grupo desconocido/ausente, fila que no es objeto, clave desconocida, tipo incorrecto, obligatorio ausente o fila sin valores.
export function parseGroups(specs: readonly GroupSpec[], value: unknown): Record<string, Rec[]> | null {
    if (!isRec(value)) return null;
    if (Object.keys(value).some((code) => !specs.some((s) => s.code === code))) return null;
    const out: Record<string, Rec[]> = {};
    for (const spec of specs) {
        const rows = value[spec.code];
        if (!Array.isArray(rows)) return null;
        const clean: Rec[] = [];
        for (const row of rows) {
            if (!isRec(row) || Object.keys(row).some((k) => !spec.fields.some((f) => f.key === k))) return null;
            const out2: Rec = {};
            for (const field of spec.fields) {
                if (row[field.key] === undefined) { if (field.required) return null; continue; }
                const parsed = parseCellValue(field, row[field.key]);
                if (parsed === undefined) return null;
                out2[field.key] = parsed;
            }
            if (Object.keys(out2).length === 0) return null;
            clean.push(out2);
        }
        out[spec.code] = clean;
    }
    return out;
}

// Parser de `values` de un formulario agrupado: el de los campos simples + `_groups` según la especificación. Si cualquiera falla, se rechaza toda la captura.
export function groupedValuesParser<S extends Rec>(parseSimple: (simple: unknown) => S | null, specs: readonly GroupSpec[]) {
    return (value: unknown): (S & { _groups: Record<string, Rec[]> }) | null => {
        if (!isRec(value)) return null;
        const { [GROUPS_KEY]: rawGroups, ...rest } = value;
        const simple = parseSimple(rest);
        const groups = parseGroups(specs, rawGroups);
        return simple && groups ? { ...simple, _groups: groups } : null;
    };
}
