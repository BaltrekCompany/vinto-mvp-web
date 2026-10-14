// VINTO-P1-04 «Registro de consumo de fibra» (Bobinas MP1 / MP3): contrato técnico CANDIDATO construido desde la DEFINICIÓN original (form_4_registro_de_consumo_de_fibra, 17 campos: 9 manuales, 6 automáticos
// y 2 calculados), NO desde la pantalla legacy. Los nueve campos manuales conservan clave, orden, etiqueta, tipo y obligatoriedad de la definición: los dos «recorte PH» y «materia prima PH» son decimales y el
// resto texto; `observaciones` es opcional.
//
// DIFERENCIA CON EL LEGACY: la pantalla heredada (componente Fiber) registra hora de consumo, material, origen, presentación, cantidad de UM, peso unitario real y un subtotal calculado. Ese modelo NO coincide con
// los nueve campos de la definición: aquí no se copia, no se convierte su subtotal en `total_kg` ni se asume que material u origen equivalgan a fibra corta o larga. Los registros legacy existentes ni se leen
// ni se borran ni se migran.
//
// BRECHAS (no se resuelven ni se simulan): `hora_inicio` y `hora_fin` figuran como automáticos en la definición, pero NO existe una fuente confirmada: la asignación central aporta fecha operativa, turno y
// máquina, y la sesión aporta el usuario, no el intervalo de consumo. No se generan horas ficticias ni se sustituyen por la hora de envío. `total_kg` y `total_final` son calculados sin fórmula aprobada: no se
// calculan, no se persisten ni se muestran como oficiales, y el backend sigue rechazando cualquier campo calculado enviado. Habilitado solo en entornos de prueba.
import { defineCandidateForm, type CandidateAttempt, type CandidateCapture, type FieldSpec } from "./candidate-form.ts";

export const P1_04_CODE = "VINTO-P1-04";
export const P104_FIELDS: readonly FieldSpec[] = [
    { key: "fibra_corta_detalle", label: "Fibra corta - detalle", kind: "text", required: true },
    { key: "fibra_larga_detalle", label: "Fibra larga - detalle", kind: "text", required: true },
    { key: "recorte_ph", label: "Recorte PH", kind: "decimal", required: true },
    { key: "recorte_servilleta", label: "Recorte servilleta", kind: "text", required: true },
    { key: "recorte_toalla", label: "Recorte toalla", kind: "text", required: true },
    { key: "materia_prima_ph", label: "Materia prima PH", kind: "decimal", required: true },
    { key: "materia_prima_servilleta", label: "Materia prima servilleta", kind: "text", required: true },
    { key: "materia_prima_toalla", label: "Materia prima toalla", kind: "text", required: true },
    { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
];
export const P104 = defineCandidateForm(P1_04_CODE, P104_FIELDS);
export const P104_AUTOMATIC = ["Fecha", "Turno", "Máquina", "Operador (usuario autenticado, informativo)"] as const; // automáticos con representación en el contexto central
export const P104_UNRESOLVED_AUTOMATIC = ["Hora inicio", "Hora fin"] as const; // automáticos de la definición SIN fuente confirmada: no se generan
export const P104_CALCULATED = ["Total kg", "Total final"] as const; // calculados de la definición, sin fórmula aprobada: no se calculan ni se muestran
export const P104_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Hora inicio y hora fin", pending: "La definición las declara automáticas, pero no hay fuente confirmada: no se generan ni se sustituyen por la hora de envío. Decisión de VINTO." },
    { label: "Total kg y total final", pending: "Calculados en la definición, sin fórmula aprobada: no se calculan, no se guardan ni se muestran como oficiales; el backend rechaza el envío de campos calculados." },
    { label: "Detalle de fibra y materiales", pending: "Fibra corta/larga y recortes/materia prima de servilleta y toalla son texto libre: sin catálogo, unidad, rango ni criterio de consumo. PH, decimal sin unidad aprobada." },
    { label: "Pantalla legacy", pending: "El modelo heredado (hora, material, origen, presentación, cantidad y subtotal) no equivale a esta definición y no se migra; sus registros locales se conservan." },
];
export type P104Capture = CandidateCapture;
export type P104Attempt = CandidateAttempt;
