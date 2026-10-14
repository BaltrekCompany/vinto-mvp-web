// VINTO-P1-31 «Consumo de químicos» (Bobinas MP1 / MP3): contrato técnico CANDIDATO. Los nueve campos manuales son exactamente los de la definición legacy (form_31_consumo_de_quimicos, 12 campos: 9 manuales
// y 3 automáticos), con sus tipos: los dos caudales son decimales y los consumos, texto. Fecha y responsables (MP1 y MP3) son automáticos: los resuelve el backend y no se digitan.
//
// PENDIENTE DE VINTO (no se inventa ni se calcula): catálogo de insumos y secciones (código, sección e insumo son TEXTO LIBRE), fórmula de conversión de caudal a consumo, densidades, unidades, rangos,
// tolerancias, reglas de inventario y la relación entre los consumos por máquina y el total. Ningún consumo se calcula: lo que se digita se guarda tal cual. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type CandidateAttempt, type CandidateCapture, type FieldSpec } from "./candidate-form.ts";

export const P1_31_CODE = "VINTO-P1-31";
export const P131_FIELDS: readonly FieldSpec[] = [
    { key: "codigo_de_insumo", label: "Código de insumo", kind: "text", required: true },
    { key: "seccion", label: "Sección", kind: "text", required: true },
    { key: "insumo_quimico", label: "Insumo químico", kind: "text", required: true },
    { key: "caudal_mp1_ml_min", label: "Caudal MP1", kind: "decimal", required: true, suffix: "ml/min" },
    { key: "caudal_mp3_ml_min", label: "Caudal MP3", kind: "decimal", required: true, suffix: "ml/min" },
    { key: "consumo_dia_mp1_kg", label: "Consumo día MP1", kind: "text", required: true, suffix: "kg" },
    { key: "consumo_dia_mp3_kg", label: "Consumo día MP3", kind: "text", required: true, suffix: "kg" },
    { key: "consumo_total_kg", label: "Consumo total", kind: "text", required: true, suffix: "kg" },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P131 = defineCandidateForm(P1_31_CODE, P131_FIELDS);
export const P131_AUTOMATIC = ["Fecha", "Responsable MP1", "Responsable MP3"] as const; // campos automáticos de la definición legacy
export const P131_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Catálogo de insumos", pending: "Código de insumo, sección e insumo son texto libre: no existe catálogo oficial." },
    { label: "Consumos", pending: "Se digitan y se guardan tal cual (texto): no se calculan desde los caudales ni se suman al total; sin fórmula, densidad ni unidad aprobadas." },
    { label: "Caudales", pending: "Solo se exige un número decimal: sin unidad oficial, rango ni tolerancia." },
    { label: "Responsables", pending: "Son el usuario autenticado, solo informativo: no son una firma ni se asume quién es el responsable de cada máquina." },
];
export type P131Capture = CandidateCapture;
export type P131Attempt = CandidateAttempt;
