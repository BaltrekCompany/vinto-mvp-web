// CV-P113-01: contrato productivo v3. El historial v1/v2 se mantiene en legacy.
import { defineCandidateForm, type CandidateDraft, type FieldSpec } from "./candidate-form.ts";
import { materialOptionsFor } from "./p1-11-v3.ts";
import { P113_FIELDS, P1_13_CODE } from "./p1-13.ts";
import { calculatedConsumption } from "./p1-11-v3.ts";
export { calculatedConsumption, materialOptionsFor };

export const P113_V3_FIELDS: readonly FieldSpec[] = [
    { key: "tipo_bobina", label: "Tipo de bobina", kind: "text", required: true, sinceVersion: 3 },
    { key: "numero_bobina", label: "N.º bobina", kind: "text", required: true, sinceVersion: 3 },
    { key: "saldo_inicial_kg", label: "Saldo inicial", kind: "decimal", required: true, sinceVersion: 3 },
    { key: "ingreso_kg", label: "Ingreso", kind: "decimal", required: true, sinceVersion: 3 },
    { key: "saldo_final_kg", label: "Saldo final", kind: "decimal", required: true, sinceVersion: 3 },
    { key: "cantidad_jabas", label: "Cantidad de jabas", kind: "integer", required: true, sinceVersion: 3 },
    { key: "hora_inicio", label: "Hora inicio pallet", kind: "time", required: true, sinceVersion: 2 },
    { key: "hora_fin", label: "Hora fin pallet", kind: "time", required: true, sinceVersion: 2 },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false, sinceVersion: 3 },
];
export const P113_LEGACY_FIELDS: readonly FieldSpec[] =
    P113_FIELDS.filter(field => !P113_V3_FIELDS.some(current => current.key === field.key));
const base = defineCandidateForm(P1_13_CODE, P113_V3_FIELDS, { legacy: P113_LEGACY_FIELDS });
export const P113_V3 = {
    ...base,
    createAttempt: (...args: Parameters<typeof base.createAttempt>): ReturnType<typeof base.createAttempt> => {
        const quantity = (args[0].cantidad_jabas ?? "").trim();
        if (!/^\d{1,9}$/.test(quantity) || Number(quantity) < 1) {
            return { ok: false, errors: ["Cantidad de jabas: debe ser un entero positivo."] };
        }
        return base.createAttempt(...args);
    },
};
export function checkP113Recipe(draft: CandidateDraft, productCode: string): string | null {
    const materials = materialOptionsFor(productCode);
    if (materials.length === 0) return "El producto de la OT no tiene receta. No se puede registrar.";
    if (!materials.some(item => item.code === (draft.tipo_bobina ?? "").trim()))
        return "Tipo de bobina: selecciona un material de la receta del producto de la OT.";
    return null;
}
