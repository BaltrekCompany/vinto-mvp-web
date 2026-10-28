// Captura CENTRAL CANDIDATA de VINTO-P1-16 «Registro de control de merma» (Conversión), M6-A: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-16».
//
// CLOUD-DEP G.12-C4-FINAL25: el contrato REAL usado por el backend (seed_data, política, UI) es `P116_FIELDS` + `defineCandidateForm`, más abajo en este archivo -- los 8 campos MANUALES
// exactos de la definición legacy (form_16_registro_de_control_de_merma, 14 campos: 5 automáticos, 8 manuales, 1 calculado). Todo lo de ARRIBA de esta nota (hipótesis `WasteCapture`: una
// pesada con tipo/origen/peso) es la HIPÓTESIS DE PRUEBA original y ya NO se usa desde app/page.tsx: queda como código muerto, sin eliminar.
//
// QUÉ NO HACE el contrato real (decisiones pendientes de VINTO, docs/M6-A-conversion-central-p116.md): no calcula total_merma_kg (calculado, sin fórmula aprobada). Solo exige lo
// estructural que la propia definición declara (texto; el correlativo es texto digitado, no generado).
//
// Todo es PURO (sin red, sin DOM).

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type Option, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";
import { defineCandidateForm, type FieldSpec } from "./candidate-form.ts";

export const P1_16_CODE = "VINTO-P1-16";

// Opciones tal como las ofrece la pantalla legacy (WasteCapture). Los valores son las claves que el formulario candidato publica como opciones del campo.
export const TIPO_MERMA_OPTIONS: readonly Option[] = [
    { value: "hoja_doble", label: "Hoja doble" }, { value: "hoja_simple", label: "Hoja simple" }, { value: "servilleta", label: "Servilleta" },
    { value: "toalla", label: "Toalla" }, { value: "carton", label: "Cartón" }, { value: "plastico", label: "Plástico" },
];
export const ORIGEN_MERMA_OPTIONS: readonly Option[] = [{ value: "logs", label: "Logs" }, { value: "cola", label: "Cola" }, { value: "maquina", label: "Máquina" }];

// ---- decisiones pendientes de VINTO (NO son reglas confirmadas) --------------------------------------------------------------------------

export const PENDING_NOTES: readonly { key: string; label: string; pending: string }[] = [
    { key: "correlativo", label: "Número correlativo", pending: "La definición legacy lo declara; no se genera ni se valida ninguno." },
    { key: "totales", label: "Total de merma (kg)", pending: "La definición legacy lo calcula; aquí no hay totales ni fórmulas: cada captura es una pesada." },
    { key: "firma", label: "Firma / grupo", pending: "Sin mecanismo de firma ni concepto de grupo en el modelo central; no se simulan." },
    { key: "peso", label: "Peso real", pending: "Unidad, rango y decimales sin confirmar; solo se exige un decimal válido." },
];

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------------

export type P116Values = { tipo_merma: string; origen_merma: string; peso_merma_kg: string };
export type P116Capture = CaptureOf<P116Values>;
export type P116Submission = SubmissionOf<P116Capture>;

const isOption = (options: readonly Option[], value: unknown): value is string => typeof value === "string" && options.some((o) => o.value === value);
const isDecimalText = (value: unknown): value is string => typeof value === "string" && value.length <= MAX_DECIMAL_CHARS && DECIMAL.test(value);

// Parser ESTRICTO: tipo y origen deben ser opciones conocidas y el peso un decimal en texto (el backend devuelve los decimales como texto); lo demás se ignora.
function parseValues(value: unknown): P116Values | null {
    if (!isRec(value)) return null;
    const { tipo_merma: tipo, origen_merma: origen, peso_merma_kg: peso } = value;
    if (!isOption(TIPO_MERMA_OPTIONS, tipo) || !isOption(ORIGEN_MERMA_OPTIONS, origen) || !isDecimalText(peso)) return null;
    return { tipo_merma: tipo, origen_merma: origen, peso_merma_kg: peso };
}

export const parseP116Capture = (value: unknown): P116Capture | null => parseCaptureOf(value, parseValues, P1_16_CODE);
export const parseP116Submission = (value: unknown): P116Submission | null => parseSubmissionOf(value, parseP116Capture);
export const parseP116List = (value: unknown): P116Capture[] | null => parseCaptureListOf(value, parseP116Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------------

export type P116Draft = { tipo_merma: string; origen_merma: string; peso_merma_kg: string };
export const EMPTY_P116_DRAFT: P116Draft = { tipo_merma: "", origen_merma: "", peso_merma_kg: "" };
export const P116_LABELS = { tipo_merma: "Tipo de merma", origen_merma: "Origen de la merma", peso_merma_kg: "Peso real" } as const;

export type P116DraftCheck = { ok: true; values: P116Values } | { ok: false; errors: string[] };

export function normalizeP116Draft(draft: P116Draft): P116DraftCheck {
    const errors: string[] = [];
    if (!isOption(TIPO_MERMA_OPTIONS, draft.tipo_merma)) errors.push(`${P116_LABELS.tipo_merma}: selecciona una opción.`);
    if (!isOption(ORIGEN_MERMA_OPTIONS, draft.origen_merma)) errors.push(`${P116_LABELS.origen_merma}: selecciona una opción.`);
    // El peso se escribe con coma o punto; el backend solo acepta el punto. Es la ÚNICA normalización (sin redondeo ni conversión de unidad).
    const weight = draft.peso_merma_kg.trim().replace(",", ".");
    if (!weight) errors.push(`${P116_LABELS.peso_merma_kg}: es obligatorio.`);
    else if (!isDecimalText(weight)) errors.push(`${P116_LABELS.peso_merma_kg}: debe ser un número decimal (por ejemplo 12.5).`);
    if (errors.length) return { ok: false, errors };
    return { ok: true, values: { tipo_merma: draft.tipo_merma, origen_merma: draft.origen_merma, peso_merma_kg: weight } };
}

export type P116Payload = { capture_id: string; form_code: typeof P1_16_CODE; assignment_id: string; device_key: string; values: P116Values };

export function buildP116Payload(captureId: string, assignmentId: string, deviceKey: string, values: P116Values): P116Payload {
    return { capture_id: captureId, form_code: P1_16_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

export type P116Attempt = PendingAttemptOf<P116Payload, P116Draft>;

export function createP116Attempt(draft: P116Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P116Attempt } | { ok: false; errors: string[] } {
    const check = normalizeP116Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP116Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------------

export type P116SubmitDeps = SubmitDepsOf<P116Payload, P116Submission, P116Capture>;
export type P116SubmitOutcome = SubmitOutcomeOf<P116Capture>;

export const submitP116Attempt = (attempt: P116Attempt, deps: P116SubmitDeps): Promise<P116SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP116 = (captureId: string, deps: P116SubmitDeps): Promise<P116SubmitOutcome> => reconcileOf(captureId, deps);

// ---- CLOUD-DEP G.12-C4-FINAL25: contrato REAL (8 campos manuales de la definición legacy, en su orden) -----------------------------------
// Fuente única: form-definitions.ts / form_16_registro_de_control_de_merma. Automáticos excluidos (fecha, turno, grupo, operador, maquina);
// calculado excluido (total_merma_kg): sin fórmula aprobada, no se calcula ni se acepta del cliente.
export const P116_FIELDS: readonly FieldSpec[] = [
    { key: "hora_inicio", label: "Hora inicio", kind: "time", required: true, sinceVersion: 2 }, // MF-11 (MD_Ejec 48): horas GENERALES del registro
    { key: "hora_fin", label: "Hora fin", kind: "time", required: true, sinceVersion: 2 },
    { key: "numero_correlativo", label: "Número correlativo", kind: "text", required: true },
    { key: "hoja_doble_kg", label: "Hoja doble kg", kind: "text", required: true },
    { key: "servilleta_kg", label: "Servilleta kg", kind: "text", required: true },
    { key: "toalla_kg", label: "Toalla kg", kind: "text", required: true },
    { key: "carton_kg", label: "Cartón kg", kind: "text", required: true },
    { key: "hoja_simple_kg", label: "Hoja simple kg", kind: "text", required: true },
    { key: "plastico_kg", label: "Plástico kg", kind: "text", required: true },
    { key: "observacion", label: "Observación", kind: "textarea", required: false },
];
export const P116 = defineCandidateForm(P1_16_CODE, P116_FIELDS);

export const P116_AUTOMATIC = ["Fecha", "Turno", "Grupo", "Operador", "Máquina"] as const;
export const P116_PENDING: readonly { label: string; pending: string }[] = [
    { label: "Horas de inicio y fin", pending: "Se digitan (HH:MM, hora local de planta) y son obligatorias desde la versión 2; no son la hora de registro del sistema, no se calcula la duración ni se valida el orden, y no se asume otra fecha si cruzan la medianoche." },
    { label: "Merma total", pending: "total_merma_kg es un campo calculado de la definición legacy, sin fórmula aprobada: no se calcula ni se acepta del cliente." },
];
