// Captura CENTRAL de VINTO-P1-10 «Registro de fardos» (Rebobinado), M2-B2: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el
// núcleo común (capture-core.ts) y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-10» (una respuesta de F6 nunca pasa por P1-10).
//
// Todo es PURO (sin red, sin DOM). QUÉ NO HACE (decisiones pendientes de VINTO, docs/M2-B-P1-10-contrato.md): no genera ni valida el número de fardo (formato,
// correlativo, unicidad), no convierte el peso en número (es TEXTO, tal como está declarado: sin decimales, rango, unidad ni coma/punto), no valida el código de
// producto contra la línea, no envía fecha/máquina/responsable/firma (el servidor deriva el contexto; responsable y firma siguen pendientes). Solo exige lo
// estructural: texto, obligatorio no vacío y el límite técnico del backend.
//
// P1-10 NO está habilitado en la política de captura central del backend ni Rebobinado es un sector operativo: este cliente solo funciona contra un backend de
// prueba que lo habilite explícitamente.

import {
    freezeAttempt, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf, isRec,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export const P1_10_CODE = "VINTO-P1-10";
export const MAX_TEXT_LENGTH = 10_000; // mismo límite técnico del backend, no una regla funcional

// ---- campos contextuales: origen propuesto y decisión pendiente (NO son reglas confirmadas) ---------------------------------------------

export const CONTEXT_NOTES: Readonly<Record<string, { origin: string; pending: string }>> = {
    fecha: { origin: "Se toma del contexto de la asignación (no se digita).", pending: "Por confirmar: fecha operativa o fecha calendario de la captura." },
    maquina: { origin: "Se toma de la máquina de la asignación (no se elige).", pending: "Por confirmar: qué máquinas pueden usar P1-10 (la definición dice «todas las rebobinadoras» pero lista solo COPASA)." },
    responsable: { origin: "Sin regla definida.", pending: "Por confirmar: no se asume que el responsable sea el operador que captura." },
    firma: { origin: "Sin mecanismo definido.", pending: "Por definir: no existe firma digital en el sistema y no se simula una." },
};

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------

export type P110Values = { codigo_numero_de_producto: string; numero_de_fardo: string; peso_fardo: string; observaciones?: string };
export type P110Capture = CaptureOf<P110Values>;
export type P110Submission = SubmissionOf<P110Capture>;

const nonEmpty = (value: unknown): value is string => typeof value === "string" && value !== "";

// Parser ESTRICTO: los tres obligatorios son texto no vacío (el backend guarda el texto recortado), `observaciones` es texto opcional; los demás valores se ignoran.
function parseValues(value: unknown): P110Values | null {
    if (!isRec(value)) return null;
    const { codigo_numero_de_producto: code, numero_de_fardo: bale, peso_fardo: weight, observaciones: notes } = value;
    if (!nonEmpty(code) || !nonEmpty(bale) || !nonEmpty(weight)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: P110Values = { codigo_numero_de_producto: code, numero_de_fardo: bale, peso_fardo: weight };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

export const parseP110Capture = (value: unknown): P110Capture | null => parseCaptureOf(value, parseValues, P1_10_CODE);
export const parseP110Submission = (value: unknown): P110Submission | null => parseSubmissionOf(value, parseP110Capture);
export const parseP110List = (value: unknown): P110Capture[] | null => parseCaptureListOf(value, parseP110Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------

export type P110Draft = { codigo_numero_de_producto: string; numero_de_fardo: string; peso_fardo: string; observaciones: string };
export const EMPTY_P110_DRAFT: P110Draft = { codigo_numero_de_producto: "", numero_de_fardo: "", peso_fardo: "", observaciones: "" };

export const P110_LABELS = { codigo_numero_de_producto: "Código / número de producto", numero_de_fardo: "Número de fardo", peso_fardo: "Peso fardo", observaciones: "Observaciones" } as const;

export type P110DraftCheck = { ok: true; values: P110Values } | { ok: false; errors: string[] };

export function normalizeP110Draft(draft: P110Draft): P110DraftCheck {
    const errors: string[] = [];
    const clean = (key: keyof P110Draft) => draft[key].trim();
    for (const key of ["codigo_numero_de_producto", "numero_de_fardo", "peso_fardo"] as const) {
        const text = clean(key);
        if (!text) errors.push(`${P110_LABELS[key]}: es obligatorio.`);
        else if (text.length > MAX_TEXT_LENGTH) errors.push(`${P110_LABELS[key]}: supera ${MAX_TEXT_LENGTH} caracteres.`);
    }
    if (clean("observaciones").length > MAX_TEXT_LENGTH) errors.push(`${P110_LABELS.observaciones}: supera ${MAX_TEXT_LENGTH} caracteres.`);
    if (errors.length) return { ok: false, errors };
    const values: P110Values = { codigo_numero_de_producto: clean("codigo_numero_de_producto"), numero_de_fardo: clean("numero_de_fardo"), peso_fardo: clean("peso_fardo") };
    const notes = clean("observaciones");
    if (notes) values.observaciones = notes;
    return { ok: true, values };
}

export type P110Payload = { capture_id: string; form_code: typeof P1_10_CODE; assignment_id: string; device_key: string; values: P110Values };

export function buildP110Payload(captureId: string, assignmentId: string, deviceKey: string, values: P110Values): P110Payload {
    return { capture_id: captureId, form_code: P1_10_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

export type P110Attempt = PendingAttemptOf<P110Payload, P110Draft>;

export function createP110Attempt(draft: P110Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P110Attempt } | { ok: false; errors: string[] } {
    const check = normalizeP110Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP110Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------

export type P110SubmitDeps = SubmitDepsOf<P110Payload, P110Submission, P110Capture>;
export type P110SubmitOutcome = SubmitOutcomeOf<P110Capture>;

export const submitP110Attempt = (attempt: P110Attempt, deps: P110SubmitDeps): Promise<P110SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP110 = (captureId: string, deps: P110SubmitDeps): Promise<P110SubmitOutcome> => reconcileOf(captureId, deps);
