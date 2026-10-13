// Captura CENTRAL CANDIDATA de VINTO-P1-12 «Producción diaria de papel higiénico» (Conversión), M6-B: valores, borrador, validación ESTRUCTURAL, payload e intento pendiente. Reutiliza el núcleo
// común (capture-core.ts) y aporta su propio parser estricto de `values` con el código esperado «VINTO-P1-12».
//
// HIPÓTESIS DE PRUEBA, NO una definición aprobada: los tres campos son la interpretación de `PalletProduction` (la pantalla legacy de app/page.tsx): UN PALLET por envío, con cantidad de jabas,
// hora de inicio y hora de fin. La definición legacy de P1-12 es otra (37 campos: balances de empaque, subempaque, bolsa, segundas y asas, mermas y total de producción) y NO se implementa aquí.
//
// QUÉ NO HACE (decisiones pendientes de VINTO, docs/M6-B-conversion-p112.md): no calcula ni envía peso nominal ni peso total (el maestro de pesos no está homologado), no genera ni muestra un
// número de pallet (el código `PAL-AAAAMMDD-XXXXXX` del legacy era aleatorio y NO es un correlativo), no impone mínimos ni máximos de jabas, no exige que la hora de fin sea posterior a la de
// inicio (un turno nocturno cruza la medianoche), no valida contra la receta ni el artículo. Solo exige lo estructural: un entero y dos horas HH:MM.
//
// Todo es PURO (sin red, sin DOM). P1-12 NO está habilitado en la política de captura central del backend ni Conversión es un sector operativo: este cliente solo funciona contra un backend de
// prueba que lo habilite explícitamente.

import {
    freezeAttempt, isRec, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type PendingAttemptOf, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export const P1_12_CODE = "VINTO-P1-12";

// ---- decisiones pendientes de VINTO (NO son reglas confirmadas) --------------------------------------------------------------------------

export const PENDING_NOTES: readonly { key: string; label: string; pending: string }[] = [
    { key: "pallet", label: "Número oficial de pallet", pending: "Pendiente de definición: no se genera ni se asume ningún correlativo. La captura se identifica solo con su identificador técnico." },
    { key: "peso", label: "Peso nominal y peso total", pending: "Pendiente: el maestro de pesos nominales no está homologado. No se calcula ni se guarda ningún peso." },
    { key: "balances", label: "Empaque, saldos y mermas", pending: "La definición legacy los declara (37 campos); esta hipótesis solo registra el pallet." },
    { key: "firma", label: "Firma / grupo", pending: "Sin mecanismo de firma ni concepto de grupo en el modelo central; no se simulan." },
];

// ---- valores y respuestas ----------------------------------------------------------------------------------------------------------------

export type P112Values = { cantidad_jabas: number; hora_inicio: string; hora_fin: string };
export type P112Capture = CaptureOf<P112Values>;
export type P112Submission = SubmissionOf<P112Capture>;

const HOUR = /^([01]\d|2[0-3]):[0-5]\d$/; // lo que envía el cliente
const STORED_HOUR = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d(\.\d+)?)?$/; // PostgreSQL devuelve la hora con segundos (HH:MM:SS)
const DIGITS = /^\d+$/;

// Hora tal como se muestra: HH:MM (los segundos que añade PostgreSQL no se muestran).
export const shortHour = (value: string): string => value.slice(0, 5);

// Parser ESTRICTO: la cantidad es un entero JSON y las horas son texto con formato de hora; lo demás se ignora.
function parseValues(value: unknown): P112Values | null {
    if (!isRec(value)) return null;
    const { cantidad_jabas: jabas, hora_inicio: start, hora_fin: end } = value;
    if (typeof jabas !== "number" || !Number.isSafeInteger(jabas)) return null;
    if (typeof start !== "string" || !STORED_HOUR.test(start) || typeof end !== "string" || !STORED_HOUR.test(end)) return null;
    return { cantidad_jabas: jabas, hora_inicio: start, hora_fin: end };
}

export const parseP112Capture = (value: unknown): P112Capture | null => parseCaptureOf(value, parseValues, P1_12_CODE);
export const parseP112Submission = (value: unknown): P112Submission | null => parseSubmissionOf(value, parseP112Capture);
export const parseP112List = (value: unknown): P112Capture[] | null => parseCaptureListOf(value, parseP112Capture);

// ---- borrador, validación estructural y payload ------------------------------------------------------------------------------------------

export type P112Draft = { cantidad_jabas: string; hora_inicio: string; hora_fin: string };
export const EMPTY_P112_DRAFT: P112Draft = { cantidad_jabas: "", hora_inicio: "", hora_fin: "" };
export const P112_LABELS = { cantidad_jabas: "Cantidad de jabas", hora_inicio: "Hora inicio del pallet", hora_fin: "Hora fin del pallet" } as const;

export type P112DraftCheck = { ok: true; values: P112Values } | { ok: false; errors: string[] };

export function normalizeP112Draft(draft: P112Draft): P112DraftCheck {
    const errors: string[] = [];
    const jabas = draft.cantidad_jabas.trim(), start = draft.hora_inicio.trim(), end = draft.hora_fin.trim();
    if (!jabas) errors.push(`${P112_LABELS.cantidad_jabas}: es obligatorio.`);
    else if (!DIGITS.test(jabas) || !Number.isSafeInteger(Number(jabas))) errors.push(`${P112_LABELS.cantidad_jabas}: debe ser un número entero (solo dígitos).`);
    for (const [key, text] of [["hora_inicio", start], ["hora_fin", end]] as const) {
        if (!text) errors.push(`${P112_LABELS[key]}: es obligatorio.`);
        else if (!HOUR.test(text)) errors.push(`${P112_LABELS[key]}: debe tener formato HH:MM.`);
    }
    if (errors.length) return { ok: false, errors };
    return { ok: true, values: { cantidad_jabas: Number(jabas), hora_inicio: start, hora_fin: end } };
}

export type P112Payload = { capture_id: string; form_code: typeof P1_12_CODE; assignment_id: string; device_key: string; values: P112Values };

export function buildP112Payload(captureId: string, assignmentId: string, deviceKey: string, values: P112Values): P112Payload {
    return { capture_id: captureId, form_code: P1_12_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

export type P112Attempt = PendingAttemptOf<P112Payload, P112Draft>;

export function createP112Attempt(draft: P112Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: P112Attempt } | { ok: false; errors: string[] } {
    const check = normalizeP112Draft(draft);
    if (!check.ok) return check;
    return { ok: true, attempt: freezeAttempt(buildP112Payload(makeId(), assignmentId, deviceKey, check.values), draft) };
}

// ---- flujo de envío con reconciliación (el común está en capture-core.ts) ----------------------------------------------------------------------

export type P112SubmitDeps = SubmitDepsOf<P112Payload, P112Submission, P112Capture>;
export type P112SubmitOutcome = SubmitOutcomeOf<P112Capture>;

export const submitP112Attempt = (attempt: P112Attempt, deps: P112SubmitDeps): Promise<P112SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcileP112 = (captureId: string, deps: P112SubmitDeps): Promise<P112SubmitOutcome> => reconcileOf(captureId, deps);
