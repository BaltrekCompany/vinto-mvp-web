// Captura CENTRAL F6 (VINTO-P1-06 · Registro de control de fardos): valores, opciones (option_key + etiqueta), normalización del borrador,
// payload exacto e intento pendiente DE F6. Lo común a cualquier formulario de producción (envelope de la respuesta, identificadores, mensajes,
// rechazos y flujo de envío con reconciliación) vive en capture-core.ts y se re-exporta aquí con los mismos nombres. Todo es PURO (sin red, sin DOM)
// para probarlo con Node: la red entra por funciones inyectadas. El backend es la autoridad: aquí no se envía ni se calcula máquina, turno, fecha
// operativa, OT, PV, producto, línea, versión del formulario, revisión, estado ni usuario.

import {
    DECIMAL, MAX_DECIMAL_CHARS, isRec, isStr, newCaptureId, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, submitAttemptOf,
    type CaptureOf, type Option, type SubmissionOf, type SubmitDepsOf, type SubmitOutcomeOf,
} from "./capture-core.ts";

export { MAX_DECIMAL_CHARS, SUBMIT_MESSAGES, isUuidV4, newCaptureId, optionLabel, rejectionFor, submitMessage, type ApiLike, type Option, type RejectReason } from "./capture-core.ts";

export const F6_FORM_ID = "form_6_registro_de_control_de_fardos";
export const F6_FORM_CODE = "VINTO-P1-06";

export const PUNTO_MERMA_OPTIONS: readonly Option[] = [
    { value: "bobina_rechazada", label: "Bobina rechazada" },
    { value: "recorte_maquina", label: "Recorte de máquina" },
];
export const TIPO_PRODUCTO_OPTIONS: readonly Option[] = [
    { value: "servilleta", label: "Servilleta" },
    { value: "hoja_doble", label: "Hoja doble" },
    { value: "hoja_simple", label: "Hoja simple" },
];

export const isF6 = (formId: string) => formId === F6_FORM_ID;

// ---- respuestas ----------------------------------------------------------------------------------------------------------

export type F6Values = { cantidad_fardos: number; punto_merma: string; tipo_producto: string; peso_kg: string; observaciones?: string };
export type CentralCapture = CaptureOf<F6Values>;
export type CaptureSubmission = SubmissionOf<CentralCapture>;

// Parser ESTRICTO de los valores F6 (cantidad entera, opciones, peso decimal como texto, observaciones opcional). Si no cumple, se rechaza toda la captura.
function parseValues(value: unknown): F6Values | null {
    if (!isRec(value)) return null;
    const { cantidad_fardos: qty, punto_merma: point, tipo_producto: kind, peso_kg: weight, observaciones: notes } = value;
    if (typeof qty !== "number" || !Number.isSafeInteger(qty) || !isStr(point) || !isStr(kind)) return null;
    // Los decimales llegan como texto; un número JSON finito también se acepta y se normaliza a texto.
    const kg = typeof weight === "number" && Number.isFinite(weight) ? String(weight) : weight;
    if (typeof kg !== "string" || !DECIMAL.test(kg)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: F6Values = { cantidad_fardos: qty, punto_merma: point, tipo_producto: kind, peso_kg: kg };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

// Construye un objeto LIMPIO: los campos desconocidos del backend se ignoran.
export const parseCapture = (value: unknown): CentralCapture | null => parseCaptureOf(value, parseValues);
export const parseSubmission = (value: unknown): CaptureSubmission | null => parseSubmissionOf(value, parseCapture);
export const parseCaptureList = (value: unknown): CentralCapture[] | null => parseCaptureListOf(value, parseCapture);

// ---- borrador, normalización y payload ------------------------------------------------------------------------------------

export type F6Draft = { cantidad_fardos: string; punto_merma: string; tipo_producto: string; peso_kg: string; observaciones: string };
export const EMPTY_DRAFT: F6Draft = { cantidad_fardos: "", punto_merma: "", tipo_producto: "", peso_kg: "", observaciones: "" };

export type CapturePayload = { capture_id: string; form_code: typeof F6_FORM_CODE; assignment_id: string; device_key: string; values: F6Values };

export type DraftCheck = { ok: true; values: F6Values } | { ok: false; errors: string[] };

// Sin límites funcionales inventados (el backend admite 0). El peso viaja como texto decimal limpio: nunca pasa por float.
export function normalizeDraft(draft: F6Draft): DraftCheck {
    const errors: string[] = [];
    const qtyText = draft.cantidad_fardos.trim(), qty = /^-?\d+$/.test(qtyText) ? Number(qtyText) : NaN;
    if (!Number.isSafeInteger(qty)) errors.push("Cantidad de fardos: ingresa un número entero.");
    if (!PUNTO_MERMA_OPTIONS.some((o) => o.value === draft.punto_merma)) errors.push("Punto de merma: selecciona una opción.");
    if (!TIPO_PRODUCTO_OPTIONS.some((o) => o.value === draft.tipo_producto)) errors.push("Tipo de producto: selecciona una opción.");
    let weight = draft.peso_kg.trim();
    if (/^-?\d+,\d+$/.test(weight)) weight = weight.replace(",", "."); // coma decimal habitual; se envía con punto
    if (!DECIMAL.test(weight) || weight.length > MAX_DECIMAL_CHARS) errors.push("Peso real total: ingresa un número decimal.");
    if (errors.length) return { ok: false, errors };
    const values: F6Values = { cantidad_fardos: qty, punto_merma: draft.punto_merma, tipo_producto: draft.tipo_producto, peso_kg: weight };
    const notes = draft.observaciones.trim();
    if (notes) values.observaciones = notes;
    return { ok: true, values };
}

export function buildPayload(captureId: string, assignmentId: string, deviceKey: string, values: F6Values): CapturePayload {
    return { capture_id: captureId, form_code: F6_FORM_CODE, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

// ---- intento pendiente ----------------------------------------------------------------------------------------------------
// Un UUIDv4 por intento LÓGICO de envío. Mientras no se sepa con certeza si el servidor guardó, capture_id, assignment_id,
// device_key y values se conservan EXACTAMENTE (el payload es inmutable) y los campos del formulario quedan bloqueados.

export type PendingAttempt = { readonly captureId: string; readonly payload: Readonly<CapturePayload>; readonly draft: Readonly<F6Draft> };

export function createAttempt(draft: F6Draft, assignmentId: string, deviceKey: string, makeId: () => string = newCaptureId): { ok: true; attempt: PendingAttempt } | { ok: false; errors: string[] } {
    const check = normalizeDraft(draft);
    if (!check.ok) return check;
    const captureId = makeId();
    return { ok: true, attempt: Object.freeze({ captureId, payload: Object.freeze(buildPayload(captureId, assignmentId, deviceKey, check.values)), draft: Object.freeze({ ...draft }) }) };
}

// ---- flujo de envío con reconciliación (el flujo común está en capture-core.ts) ------------------------------------------------------

export type SubmitDeps = SubmitDepsOf<CapturePayload, CaptureSubmission, CentralCapture>;
export type SubmitOutcome = SubmitOutcomeOf<CentralCapture>;

export const submitAttempt = (attempt: PendingAttempt, deps: SubmitDeps): Promise<SubmitOutcome> => submitAttemptOf(attempt, deps);
export const reconcile = (captureId: string, deps: SubmitDeps): Promise<SubmitOutcome> => reconcileOf(captureId, deps);
