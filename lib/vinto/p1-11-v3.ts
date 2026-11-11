// CV-P111-v3: tres posiciones visibles, la primera obligatoria.
// Valores del consumo se derivan solo en pantalla, sin movimientos de inventario.
import { freezeAttempt, newCaptureId, type PendingAttemptOf } from "./capture-core.ts";
import { buildGroupedValues, buildGroups, emptyRow, newRowKey, type GroupDrafts, type GroupSpec, type RowDraft, type RowError } from "./capture-groups.ts";
import { RECIPES_BY_PRODUCT } from "./recipes.ts";

export const P111_V3_GROUPS: readonly GroupSpec[] = [{
    code: "bobinas", label: "Bobinas e insumos consumidos", repeatable: true, minRows: 1, maxRows: 3,
    fields: [
        { key: "posicion", label: "Posición", kind: "choice", required: true, options: [
            { value: "superior", label: "Superior" }, { value: "inferior", label: "Inferior" }, { value: "no_aplica", label: "No aplica" },
        ] },
        { key: "tipo_material", label: "Tipo según receta", kind: "text", required: true },
        { key: "numero_bobina", label: "N.º bobina", kind: "text", required: true },
        { key: "saldo_inicial_kg", label: "Saldo inicial", kind: "decimal", required: true, unit: "kg" },
        { key: "ingreso_kg", label: "Ingreso", kind: "decimal", required: true, unit: "kg" },
        { key: "saldo_final_kg", label: "Saldo final", kind: "decimal", required: true, unit: "kg" },
    ],
}];
export const P111_V3_SLOTS = 3;
export type P111V3Draft = { observaciones: string; groups: GroupDrafts };
export type P111V3Payload = { capture_id: string; form_code: "VINTO-P1-11"; assignment_id: string; device_key: string; values: Record<string, unknown> };
export type P111V3Attempt = PendingAttemptOf<P111V3Payload, P111V3Draft>;

export function materialOptionsFor(productCode: string) {
    return RECIPES_BY_PRODUCT[productCode] ?? [];
}

export function emptyP111V3Draft(makeKey: () => string = newRowKey): P111V3Draft {
    return { observaciones: "", groups: { bobinas: Array.from({ length: P111_V3_SLOTS }, () => emptyRow(P111_V3_GROUPS[0], makeKey)) } };
}

export function isBlankOptionalRow(row: RowDraft): boolean {
    return P111_V3_GROUPS[0].fields.every(field => !(row.cells[field.key] ?? "").trim());
}

export function normalizeP111V3Draft(draft: P111V3Draft, productCode: string):
    { ok: true; values: Record<string, unknown> } | { ok: false; errors: RowError[] } {
    const all = draft.groups.bobinas ?? [];
    const errors: RowError[] = [];
    if (all.length !== P111_V3_SLOTS) errors.push({ group: "bobinas", row: null, message: "Se esperan exactamente tres posiciones visibles." });
    const filledIndices = all.map((row, i) => i).filter(i => i === 0 || !isBlankOptionalRow(all[i]));
    const filled = filledIndices.map(i => all[i]);
    const allowed = new Set(materialOptionsFor(productCode).map(item => item.code));
    if (!allowed.size) errors.push({ group: "bobinas", row: null, message: "No hay receta registrada para el producto de la OT. No se puede enviar." });
    const built = buildGroups(P111_V3_GROUPS, { bobinas: filled });
    if (!built.ok) errors.push(...built.errors.map(error => ({ ...error,
        row: error.row === null ? null : filledIndices[error.row - 1] + 1,
    })));
    all.forEach((row, index) => {
        if (index !== 0 && isBlankOptionalRow(row)) return;
        const material = (row.cells.tipo_material ?? "").trim();
        if (material && !allowed.has(material)) errors.push({
            group: "bobinas", row: index + 1, field: "tipo_material", message: "El material no pertenece a la receta del producto de la OT.",
        });
    });
    const notes = draft.observaciones.trim();
    if (notes.length > 10000) errors.push({ group: "", row: null, field: "observaciones", message: "Las observaciones superan 10000 caracteres." });
    if (errors.length || !built.ok) return { ok: false, errors };
    return { ok: true, values: buildGroupedValues(notes ? { observaciones: notes } : {}, built.groups) };
}

export function createP111V3Attempt(draft: P111V3Draft, assignmentId: string, deviceKey: string, productCode: string, makeId: () => string = newCaptureId):
    { ok: true; attempt: P111V3Attempt } | { ok: false; errors: RowError[] } {
    const checked = normalizeP111V3Draft(draft, productCode);
    if (!checked.ok) return checked;
    return { ok: true, attempt: freezeAttempt({
        capture_id: makeId(), form_code: "VINTO-P1-11", assignment_id: assignmentId, device_key: deviceKey, values: checked.values,
    }, draft) };
}

// Vista derivada; los números originales se envían como texto normalizado sin redondeo.
export function calculatedConsumption(row: Readonly<Partial<Record<"saldo_inicial_kg" | "ingreso_kg" | "saldo_final_kg", string>>>): string {
    const get = (key: string) => {
        const raw = (row[key] ?? "").trim().replace(",", ".");
        return /^-?\d+(\.\d+)?$/.test(raw) ? Number(raw) : NaN;
    };
    const init = get("saldo_inicial_kg"), incoming = get("ingreso_kg"), end = get("saldo_final_kg");
    if ([init, incoming, end].some(n => !Number.isFinite(n))) return "0.00 kg";
    const value = init + incoming - end;
    return Number.isFinite(value) ? value.toFixed(2) + " kg" : "—";
}
