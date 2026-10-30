// VINTO-P1-04 «Registro de consumo de fibra» (Bobinas MP1 / MP3). MF-12B (versión 2, MD_Ejec 17): vuelve al modelo del MVP anterior (componente `Fiber` de app/page.tsx antes de INT-02A): UNA CAPTURA POR CONSUMO con hora de
// consumo, material, origen (según el material), presentación (según el material), cantidad de UM y peso unitario real. El subtotal (cantidad × peso unitario, kg) se MUESTRA en pantalla y en el historial con dos decimales
// (aritmética exacta, sin coma flotante) pero NO es un campo: no se envía, no se guarda y no forma parte del contrato del backend; tampoco mueve inventario ni se relaciona con bobinas, genealogía o consumos efectivos.
//
// Catálogos EXACTAMENTE como en el MVP anterior (textos literales: son los valores que se guardan, sin claves técnicas):
//   Material: Fibra larga · Fibra corta · Recorte.   Origen: Fibra larga → Laja, Susano, Dorado; Fibra corta → Laja, Cóndor; Recorte → Sauce Rancho, Máquina.
//   Presentación: Caja, Fardo (Recorte solo Fardo).
// La relación Material–Origen y Material–Presentación se aplica en la pantalla y, en el backend, solo para esta versión (backend/app/dependent_options.py). Sin rangos ni límites industriales.
//
// Las capturas de la versión 1 (los nueve campos de la definición original: fibra corta/larga en detalle, recortes y materia prima por tipo) no se modifican: se leen y se muestran como «versión anterior».
import { defineCandidateForm, type CandidateAttempt, type CandidateCapture, type FieldSpec } from "./candidate-form.ts";
import { productTwoDecimals } from "./exact-decimal.ts";

export const P1_04_CODE = "VINTO-P1-04";
export const P104_V2 = 2; // primera versión con un registro por consumo
export const P104_MATERIALS = ["Fibra larga", "Fibra corta", "Recorte"] as const;
export const P104_ORIGINS_BY_MATERIAL: Readonly<Record<string, readonly string[]>> = { "Fibra larga": ["Laja", "Susano", "Dorado"], "Fibra corta": ["Laja", "Cóndor"], Recorte: ["Sauce Rancho", "Máquina"] };
export const P104_PRESENTATIONS_BY_MATERIAL: Readonly<Record<string, readonly string[]>> = { "Fibra larga": ["Caja", "Fardo"], "Fibra corta": ["Caja", "Fardo"], Recorte: ["Fardo"] };
export const P104_ORIGINS = ["Laja", "Susano", "Dorado", "Cóndor", "Sauce Rancho", "Máquina"] as const; // lista completa (la que publica el seed), en el orden del MVP anterior
export const P104_PRESENTATIONS = ["Caja", "Fardo"] as const;
export const P104_FIELDS: readonly FieldSpec[] = [
    { key: "hora_consumo", label: "Hora de consumo", kind: "time", required: true, sinceVersion: P104_V2 },
    { key: "material", label: "Material", kind: "select", required: true, options: P104_MATERIALS, sinceVersion: P104_V2 },
    { key: "origen", label: "Origen", kind: "select", required: true, options: P104_ORIGINS, dependsOn: { field: "material", allowed: P104_ORIGINS_BY_MATERIAL }, sinceVersion: P104_V2 },
    { key: "presentacion", label: "Presentación", kind: "select", required: true, options: P104_PRESENTATIONS, dependsOn: { field: "material", allowed: P104_PRESENTATIONS_BY_MATERIAL }, sinceVersion: P104_V2 },
    { key: "cantidad_um", label: "Cantidad de UM", kind: "integer", required: true, sinceVersion: P104_V2 },
    { key: "peso_unitario_real", label: "Peso unitario real", kind: "decimal", required: true, suffix: "kg", sinceVersion: P104_V2 },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
// Campos de la versión 1 (retirados): solo lectura para el historial, nunca se digitan ni se envían.
export const P104_LEGACY_FIELDS: readonly FieldSpec[] = [
    { key: "fibra_corta_detalle", label: "Fibra corta - detalle", kind: "text", required: false },
    { key: "fibra_larga_detalle", label: "Fibra larga - detalle", kind: "text", required: false },
    { key: "recorte_ph", label: "Recorte PH", kind: "decimal", required: false },
    { key: "recorte_servilleta", label: "Recorte servilleta", kind: "text", required: false },
    { key: "recorte_toalla", label: "Recorte toalla", kind: "text", required: false },
    { key: "materia_prima_ph", label: "Materia prima PH", kind: "decimal", required: false },
    { key: "materia_prima_servilleta", label: "Materia prima servilleta", kind: "text", required: false },
    { key: "materia_prima_toalla", label: "Materia prima toalla", kind: "text", required: false },
];
export const P104 = defineCandidateForm(P1_04_CODE, P104_FIELDS, { legacy: P104_LEGACY_FIELDS });
// Subtotal (kg) = Cantidad de UM × Peso unitario real: solo visual, con dos decimales; vacío si falta alguno de los dos valores o no es válido.
export const P104_DERIVED = [{
    key: "subtotal_kg", label: "Subtotal", suffix: "kg",
    compute: (values: Readonly<Record<string, string | undefined>>): string | null => {
        const quantity = (values.cantidad_um ?? "").trim(), weight = (values.peso_unitario_real ?? "").trim();
        return quantity && weight ? productTwoDecimals(quantity, weight) : null;
    },
}] as const;
export const P104_AUTOMATIC = ["Fecha", "Turno", "Máquina", "Operador (usuario autenticado, informativo)"] as const; // automáticos con representación en el contexto central
export const P104_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Un registro por consumo", pending: "Cada captura es UN consumo; para registrar otro se envía otra captura. No es un consumo efectivo de inventario ni se relaciona con bobinas, genealogía u órdenes de materiales." },
    { label: "Subtotal", pending: "El subtotal (cantidad × peso unitario, kg) se calcula en pantalla con dos decimales y NO se guarda como campo." },
    { label: "Catálogos y reglas", pending: "Material, origen y presentación son los del MVP anterior (textos literales); el origen y la presentación dependen del material. Sin rangos ni límites de peso aprobados." },
];
export type P104Capture = CandidateCapture;
export type P104Attempt = CandidateAttempt;
