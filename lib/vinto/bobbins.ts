// Producción de bobinas CENTRAL F3 (VINTO-P1-03 · Registro de producción de bobinas): tipos de la respuesta del backend
// (Bobbin + Capture), validación defensiva de su forma, normalización del borrador, payload exacto, intento pendiente y flujo
// de envío. Todo es PURO (sin red, sin DOM, sin imports en tiempo de ejecución) para probarlo con Node: la red entra por una
// función inyectada. El backend es la autoridad: aquí no se envía ni se calcula fecha, turno, máquina, operador, código de
// bobina, producto, descripción, gramaje, OT/PV/línea, gestión ni correlativo. Solo viajan assignment_id y los 6 valores manuales.
//
// A diferencia de F6, un POST incierto NO se reconcilia con un GET: el cliente no conoce bobbin_id antes de la primera respuesta.
// La reconciliación es repetir el MISMO POST (mismo capture_id y payload), seguro por la idempotencia del backend.

import type { CaptureContext } from "./orders.ts"; // solo tipo: se borra al compilar, el módulo sigue sin dependencias en tiempo de ejecución

export const F3_FORM_ID = "form_3_registro_de_produccion_de_bobinas";
export const F3_FORM_CODE = "VINTO-P1-03";
export const isF3 = (formId: string) => formId === F3_FORM_ID;

// ---- identificadores -----------------------------------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isUuidV4 = (value: unknown): value is string => typeof value === "string" && UUID_V4.test(value);
export const newBobbinCaptureId = (): string => crypto.randomUUID();

// ---- respuesta -----------------------------------------------------------------------------------------------------------

export type CentralBobbin = {
    id: string;
    code: string;
    capture_id: string;
    machine: { code: string; name: string };
    management_start_year: number;
    sequence_number: number;
    start_time: string;
    end_time: string;
    diameter_mm: string;
    weight_kg: string;
    grammage_g_m2: string | null;
    number_of_cuts: string;
    notes: string | null;
    article: { code: string; description: string };
    quality_status: QualityStatus;
    created_at: string;
};

// Estados de vinto_txn.quality_release (CHECK de 0001): ningún otro valor es posible.
export const QUALITY_STATUSES = ["pending", "released", "rejected"] as const;
export type QualityStatus = (typeof QUALITY_STATUSES)[number];
const isQualityStatus = (value: unknown): value is QualityStatus => typeof value === "string" && (QUALITY_STATUSES as readonly string[]).includes(value);

// Una captura F3 devuelta por POST/retry solo puede estar enviada o cerrada (nunca borrador ni bloqueada).
export const F3_CAPTURE_STATUSES = ["submitted", "closed"] as const;

export type BobbinCapture = {
    id: string;
    status: string;
    revision: number;
    captured_at: string;
    submitted_at: string | null;
    form: { code: string; version_number: number; name: string };
    machine: { code: string; name: string };
    shift: { code: string; name: string };
    operating_date: string;
    assignment: { id: string };
    work_order: { id: string; number: string };
    line: { id: string; line_code: string; pv_reference: string; article: { code: string; description: string } };
    values: BobbinCaptureValues;
};

export type BobbinCaptureValues = { hora_inicio: string; hora_fin: string; diametro: string; peso_kg: string; numero_de_cortes: string; observaciones?: string };

export type BobbinSubmission = { created: boolean; already_submitted: boolean; bobbin: CentralBobbin; capture: BobbinCapture };

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isInt = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value);
const DECIMAL = /^-?\d+(\.\d+)?$/;
const isNegative = (decimal: string) => decimal.startsWith("-") && !/^-0+(\.0+)?$/.test(decimal); // sin pasar por float; -0 no es negativo

// El backend entrega decimales como texto; un número JSON finito también se acepta y se normaliza a texto.
function decimalText(value: unknown): string | null {
    const text = typeof value === "number" && Number.isFinite(value) ? String(value) : value;
    return typeof text === "string" && DECIMAL.test(text) ? text : null;
}

function pair(value: unknown): { code: string; name: string } | null {
    return isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
}

// Construye un objeto LIMPIO: los campos desconocidos del backend se ignoran.
export function parseBobbin(value: unknown): CentralBobbin | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.code) || !isStr(value.capture_id)) return null;
    const machine = pair(value.machine), article = value.article;
    if (!machine || !isRec(article) || !isStr(article.code) || typeof article.description !== "string") return null;
    // Invariantes ya existentes en backend/DB (CHECK de 0004: sequence_number > 0, management_start_year > 0, code = sequence_number::text).
    if (!isInt(value.management_start_year) || value.management_start_year <= 0 || !isInt(value.sequence_number) || value.sequence_number <= 0) return null;
    if (value.code !== String(value.sequence_number)) return null;
    if (!isStr(value.start_time) || !isStr(value.end_time) || !isStr(value.number_of_cuts) || !isQualityStatus(value.quality_status) || !isStr(value.created_at)) return null;
    const diameter = decimalText(value.diameter_mm), weight = decimalText(value.weight_kg); // diámetro: decimal válido, SIN rango funcional
    if (diameter === null || weight === null || isNegative(weight)) return null; // weight_kg >= 0 viene de 0001
    const grammage = value.grammage_g_m2 === null ? null : decimalText(value.grammage_g_m2); // null = el producto no tiene gramaje (válido)
    if (value.grammage_g_m2 !== null && grammage === null) return null;
    if (!(value.notes === null || typeof value.notes === "string")) return null;
    return {
        id: value.id, code: value.code, capture_id: value.capture_id, machine, management_start_year: value.management_start_year,
        sequence_number: value.sequence_number, start_time: value.start_time, end_time: value.end_time, diameter_mm: diameter, weight_kg: weight,
        grammage_g_m2: grammage, number_of_cuts: value.number_of_cuts, notes: value.notes, article: { code: article.code, description: article.description },
        quality_status: value.quality_status, created_at: value.created_at,
    };
}

function parseCaptureValues(value: unknown): BobbinCaptureValues | null {
    if (!isRec(value)) return null;
    const { hora_inicio: start, hora_fin: end, numero_de_cortes: cuts, observaciones: notes } = value;
    const diameter = decimalText(value.diametro), weight = decimalText(value.peso_kg);
    if (!isStr(start) || !isStr(end) || !isStr(cuts) || diameter === null || weight === null) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: BobbinCaptureValues = { hora_inicio: start, hora_fin: end, diametro: diameter, peso_kg: weight, numero_de_cortes: cuts };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

export function parseBobbinCapture(value: unknown): BobbinCapture | null {
    if (!isRec(value) || !isStr(value.id) || !(F3_CAPTURE_STATUSES as readonly unknown[]).includes(value.status) || !isInt(value.revision) || value.revision <= 0) return null;
    const status = value.status as string;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, machine = pair(value.machine), shift = pair(value.shift), assignment = value.assignment, order = value.work_order, line = value.line;
    if (!isRec(form) || form.code !== F3_FORM_CODE || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(assignment) || !isStr(assignment.id) || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parseCaptureValues(value.values);
    if (!values) return null;
    return {
        id: value.id, status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, machine, shift, operating_date: value.operating_date,
        assignment: { id: assignment.id }, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        values,
    };
}

export function parseBobbinSubmission(value: unknown): BobbinSubmission | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_submitted !== "boolean") return null;
    const bobbin = parseBobbin(value.bobbin), capture = parseBobbinCapture(value.capture);
    if (!bobbin || !capture || bobbin.capture_id !== capture.id) return null;
    return { created: value.created, already_submitted: value.already_submitted, bobbin, capture };
}

// ---- borrador, normalización y payload ------------------------------------------------------------------------------------

export type BobbinDraft = { hora_inicio: string; hora_fin: string; diametro: string; peso_kg: string; numero_de_cortes: string; observaciones: string };
export const EMPTY_BOBBIN_DRAFT: BobbinDraft = { hora_inicio: "", hora_fin: "", diametro: "", peso_kg: "", numero_de_cortes: "", observaciones: "" };

export type BobbinValues = { hora_inicio: string; hora_fin: string; diametro: string; peso_kg: string; numero_de_cortes: string; observaciones?: string };
export type BobbinPayload = { capture_id: string; assignment_id: string; device_key: string; values: BobbinValues };

export const MAX_DECIMAL_CHARS = 40; // límites técnicos equivalentes a los del backend, no funcionales
export const MAX_TEXT_CHARS = 10_000;
const TIME = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/;
const ZERO = /^-0+(\.0+)?$/;

export type BobbinDraftCheck = { ok: true; values: BobbinValues } | { ok: false; errors: string[] };

function decimalField(raw: string): string | null {
    let text = raw.trim();
    if (/^-?\d+,\d+$/.test(text)) text = text.replace(",", "."); // coma decimal habitual; se envía con punto
    return DECIMAL.test(text) && text.length <= MAX_DECIMAL_CHARS ? text : null;
}

// Reglas SOLO de UX y coherentes con el backend. Sin comparar horas (puede cruzar medianoche), sin rango para el diámetro y sin
// máximos inventados. El peso no puede ser negativo porque vinto_txn.bobbin.weight_kg ya tenía CHECK (weight_kg >= 0) desde 0001.
// Los decimales viajan como texto limpio: nunca pasan por float. numero_de_cortes es TEXTO (nunca Number/parseInt).
export function normalizeBobbinDraft(draft: BobbinDraft): BobbinDraftCheck {
    const errors: string[] = [];
    const start = draft.hora_inicio.trim(), end = draft.hora_fin.trim();
    if (!TIME.test(start)) errors.push("Hora inicio: ingresa una hora válida.");
    if (!TIME.test(end)) errors.push("Hora fin: ingresa una hora válida.");
    const diameter = decimalField(draft.diametro);
    if (diameter === null) errors.push("Diámetro: ingresa un número decimal.");
    const weight = decimalField(draft.peso_kg);
    if (weight === null) errors.push("Peso: ingresa un número decimal.");
    else if (weight.startsWith("-") && !ZERO.test(weight)) errors.push("Peso: no puede ser negativo.");
    const cuts = draft.numero_de_cortes.trim();
    if (!cuts) errors.push("Número de cortes: obligatorio.");
    else if (cuts.length > MAX_TEXT_CHARS) errors.push("Número de cortes: demasiado largo.");
    const notes = draft.observaciones.trim();
    if (notes.length > MAX_TEXT_CHARS) errors.push("Observaciones: demasiado largas.");
    if (errors.length) return { ok: false, errors };
    const values: BobbinValues = { hora_inicio: start, hora_fin: end, diametro: diameter as string, peso_kg: weight as string, numero_de_cortes: cuts };
    if (notes) values.observaciones = notes; // vacío = se omite del payload
    return { ok: true, values };
}

export function buildBobbinPayload(captureId: string, assignmentId: string, deviceKey: string, values: BobbinValues): BobbinPayload {
    return { capture_id: captureId, assignment_id: assignmentId, device_key: deviceKey, values: { ...values } };
}

// ---- intento pendiente ----------------------------------------------------------------------------------------------------
// Un UUIDv4 por intento LÓGICO. Mientras no se sepa con certeza si el servidor guardó, capture_id, assignment_id, device_key y
// values se conservan EXACTAMENTE (el payload es inmutable) y los campos quedan bloqueados. No se persiste (sin localStorage).

// El intento también congela el CONTEXTO VISUAL (snapshot del CaptureContext) de la asignación a la que pertenece su assignment_id:
// reabrirlo muestra SIEMPRE la OT/línea/máquina originales, aunque el selector ya apunte a otra máquina.
export type BobbinAttemptContext = Readonly<CaptureContext>;
export type PendingBobbinAttempt = {
    readonly captureId: string;
    readonly payload: Readonly<BobbinPayload>;
    readonly draft: Readonly<BobbinDraft>;
    readonly context: BobbinAttemptContext;
};

// Contexto que se muestra y desde el que se envía: el del intento pendiente si existe; si no, el actual. Nunca se mezclan.
export const contextToShow = (attempt: PendingBobbinAttempt | null, current: CaptureContext | null): BobbinAttemptContext | null => (attempt ? attempt.context : current);

export const pendingNotice = (attempt: PendingBobbinAttempt): string =>
    `Existe un envío pendiente: se reintentará la bobina de ${attempt.context.machine} · ${attempt.context.otId} · ${attempt.context.lineId} / ${attempt.context.pv} (${attempt.context.shift} · ${attempt.context.date}).`;

export function createBobbinAttempt(draft: BobbinDraft, context: CaptureContext, deviceKey: string, makeId: () => string = newBobbinCaptureId):
    { ok: true; attempt: PendingBobbinAttempt } | { ok: false; errors: string[] } {
    const check = normalizeBobbinDraft(draft);
    if (!check.ok) return check;
    const captureId = makeId();
    // Congelado explícito de cada nivel: intento, payload, values y borrador (Object.freeze es superficial).
    const built = buildBobbinPayload(captureId, context.assignmentId, deviceKey, check.values);
    const values: Readonly<BobbinValues> = Object.freeze({ ...built.values });
    const payload: Readonly<BobbinPayload> = Object.freeze({ capture_id: built.capture_id, assignment_id: built.assignment_id, device_key: built.device_key, values });
    const frozenDraft: Readonly<BobbinDraft> = Object.freeze({ ...draft });
    const frozenContext: BobbinAttemptContext = Object.freeze({ ...context });
    return { ok: true, attempt: Object.freeze({ captureId, payload, draft: frozenDraft, context: frozenContext }) };
}

// ---- errores y mensajes ---------------------------------------------------------------------------------------------------

export const BOBBIN_MESSAGES = {
    offline: "Se requiere conexión para registrar la bobina.",
    forbidden: "No tienes permisos para registrar bobinas.",
    notFound: "La asignación o contexto ya no existe.",
    stale: "La asignación ya no corresponde al turno o fecha actual. Solicita a Supervisión que la reactive.",
    notActive: "La asignación ya no está activa.",
    idempotency: "No se puede reutilizar este identificador para datos distintos.",
    invalid: "Revisa los campos obligatorios y sus valores.",
    conflict: "El servidor no pudo aceptar el registro. Actualiza y vuelve a intentar.",
    uncertain: "No se pudo confirmar el registro de la bobina. Reintenta el envío: se reenvía exactamente el mismo registro y no se duplicará.",
} as const;

export type BobbinRejectReason = "forbidden" | "not_found" | "stale" | "not_active" | "idempotency" | "invalid" | "conflict";

export function bobbinRejectionFor(status: number, code?: string): { reason: BobbinRejectReason; message: string } | null {
    if (status === 403) return { reason: "forbidden", message: BOBBIN_MESSAGES.forbidden };
    if (status === 404) return { reason: "not_found", message: BOBBIN_MESSAGES.notFound };
    if (status === 422) return { reason: "invalid", message: BOBBIN_MESSAGES.invalid };
    if (status === 409) {
        if (code === "ASSIGNMENT_STALE") return { reason: "stale", message: BOBBIN_MESSAGES.stale };
        if (code === "ASSIGNMENT_NOT_ACTIVE") return { reason: "not_active", message: BOBBIN_MESSAGES.notActive };
        if (code === "CAPTURE_IDEMPOTENCY_CONFLICT") return { reason: "idempotency", message: BOBBIN_MESSAGES.idempotency };
        return { reason: "conflict", message: BOBBIN_MESSAGES.conflict };
    }
    return null;
}

const quality = (status: QualityStatus) => (status === "pending" ? "Calidad pendiente" : status === "released" ? "Calidad liberada" : "Calidad rechazada");

// "Bobina 2 registrada · gramaje 15.5 · Calidad pendiente". Gramaje null: redacción neutra (no es un error).
export function bobbinSuccessMessage(bobbin: CentralBobbin, alreadySubmitted = false): string {
    const grammage = bobbin.grammage_g_m2 === null ? "sin gramaje en el maestro" : `gramaje ${bobbin.grammage_g_m2}`;
    return `Bobina ${bobbin.code} ${alreadySubmitted ? "ya había sido registrada" : "registrada"} · ${grammage} · ${quality(bobbin.quality_status)}`;
}

// ---- flujo de envío -------------------------------------------------------------------------------------------------------

export type BobbinApiLike = { ok: true; data: BobbinSubmission; status: number } | { ok: false; kind: string; status: number; code?: string };
export type BobbinSubmitDeps = { post: (payload: BobbinPayload) => Promise<BobbinApiLike> };

export type BobbinSubmitOutcome =
    | { kind: "submitted"; created: boolean; alreadySubmitted: boolean; submission: BobbinSubmission; message: string }
    | { kind: "session" }
    | { kind: "rejected"; reason: BobbinRejectReason; message: string } // respuesta definitiva: el intento termina
    | { kind: "uncertain"; message: string }; // red / 5xx / cuerpo ilegible: se conserva EL MISMO intento (mismo capture_id)

// 200 con already_submitted es éxito (reintento idempotente). Ante lo incierto no se genera otro capture_id ni se consulta otro endpoint.
export async function submitBobbinAttempt(attempt: PendingBobbinAttempt, deps: BobbinSubmitDeps): Promise<BobbinSubmitOutcome> {
    const posted = await deps.post(attempt.payload);
    if (posted.ok) {
        const { created, already_submitted: alreadySubmitted, bobbin } = posted.data;
        return { kind: "submitted", created, alreadySubmitted, submission: posted.data, message: bobbinSuccessMessage(bobbin, alreadySubmitted && !created) };
    }
    if (posted.status === 401) return { kind: "session" };
    const rejection = bobbinRejectionFor(posted.status, posted.code);
    if (rejection) return { kind: "rejected", ...rejection };
    return { kind: "uncertain", message: BOBBIN_MESSAGES.uncertain };
}
