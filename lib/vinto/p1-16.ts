// Captura CENTRAL CANDIDATA de VINTO-P1-16 «Registro de control de merma» (Conversión), M6-A: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-16».
//
// HIPÓTESIS DE PRUEBA, NO una definición aprobada: los tres campos son la interpretación de `WasteCapture` (la pantalla legacy de app/page.tsx): una PESADA por captura con tipo, origen y
// peso real. La definición legacy de P1-16 es otra (columnas de kg por tipo de merma, correlativo, total) y NO se implementa aquí. No se inventa: correlativo, firma, grupo, totales ni
// fórmulas; tampoco unidad, rango ni decimales del peso (solo se exige el formato decimal que el backend ya valida). Las opciones de tipo y origen son las de la pantalla legacy.
//
// Todo es PURO (sin red, sin DOM). P1-16 NO está habilitado en la política de captura central del backend ni Conversión es un sector operativo: este cliente solo funciona contra un backend
// de prueba que lo habilite explícitamente.

import {
    DECIMAL, MAX_DECIMAL_CHARS, freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type Option, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

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
