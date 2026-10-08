// Captura CENTRAL de Calidad · VINTO-P1-19 "Control de humedad" ligada a una Bobina física. PURO (sin red, sin DOM, sin imports en
// tiempo de ejecución) para probarlo con Node: la red entra por funciones inyectadas. El backend es la autoridad: aquí solo viajan
// capture_id, form_code, device_key y los DATOS FUENTE manuales (seis pesos y observaciones). La humedad por posición y el promedio
// se calculan SOLO para mostrarlos (misma fórmula que ya usaba app/page.tsx) y NUNCA se envían ni se guardan. La Bobina va en la ruta;
// máquina, turno, fecha, OT, PV y artículo los deriva el backend de la F3 de origen. No libera ni rechaza nada.

import type { QualityBobbinInboxItem } from "./quality-bobbins.ts"; // solo tipo: se borra al compilar

export const Q19_FORM_ID = "form_19_control_de_humedad";
export const Q19_FORM_CODE = "VINTO-P1-19";
export const isQ19 = (formId: string) => formId === Q19_FORM_ID;

// ---- identificadores -----------------------------------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isUuidV4 = (value: unknown): value is string => typeof value === "string" && UUID_V4.test(value);
export const newQualityCaptureId = (): string => crypto.randomUUID();

// ---- campos --------------------------------------------------------------------------------------------------------------

export const POSITIONS = ["comando", "medio", "transversal"] as const;
export type Position = (typeof POSITIONS)[number];
export const POSITION_LABELS: Record<Position, string> = { comando: "Comando", medio: "Medio", transversal: "Transversal" };

export type WeightKey = "peso_humedo_comando" | "peso_seco_comando" | "peso_humedo_medio" | "peso_seco_medio" | "peso_humedo_transversal" | "peso_seco_transversal";
export const WEIGHT_KEYS: readonly WeightKey[] = POSITIONS.flatMap((p) => [`peso_humedo_${p}`, `peso_seco_${p}`] as const);
export const WEIGHT_LABELS: Record<WeightKey, string> = {
    peso_humedo_comando: "Peso húmedo · Comando", peso_seco_comando: "Peso seco · Comando",
    peso_humedo_medio: "Peso húmedo · Medio", peso_seco_medio: "Peso seco · Medio",
    peso_humedo_transversal: "Peso húmedo · Transversal", peso_seco_transversal: "Peso seco · Transversal",
};

export type HumidityDraft = Record<WeightKey, string> & { observaciones: string };
export const EMPTY_HUMIDITY_DRAFT: HumidityDraft = {
    peso_humedo_comando: "", peso_seco_comando: "", peso_humedo_medio: "", peso_seco_medio: "", peso_humedo_transversal: "", peso_seco_transversal: "", observaciones: "",
};

export type HumidityValues = Record<WeightKey, string> & { observaciones?: string };
export type HumidityPayload = { capture_id: string; form_code: typeof Q19_FORM_CODE; device_key: string; values: HumidityValues };

export const MAX_DECIMAL_CHARS = 40; // límites técnicos equivalentes a los del backend, no funcionales
export const MAX_TEXT_CHARS = 10_000;
const DECIMAL = /^-?\d+(\.\d+)?$/;

export type HumidityDraftCheck = { ok: true; values: HumidityValues } | { ok: false; errors: string[] };

// Coma decimal -> punto. Sin rangos ni máximos funcionales: solo "es un decimal" y el límite técnico de longitud. Texto, nunca float.
export function decimalText(raw: string): string | null {
    let text = raw.trim();
    if (/^-?\d+,\d+$/.test(text)) text = text.replace(",", ".");
    return DECIMAL.test(text) && text.length <= MAX_DECIMAL_CHARS ? text : null;
}

export function normalizeHumidityDraft(draft: HumidityDraft): HumidityDraftCheck {
    const errors: string[] = [];
    const values: Partial<HumidityValues> = {};
    for (const key of WEIGHT_KEYS) {
        const text = decimalText(draft[key]);
        if (text === null) errors.push(`${WEIGHT_LABELS[key]}: ingresa un número decimal.`);
        else values[key] = text;
    }
    const notes = draft.observaciones.trim();
    if (notes.length > MAX_TEXT_CHARS) errors.push("Observaciones: demasiado largas.");
    if (errors.length) return { ok: false, errors };
    if (notes) values.observaciones = notes; // vacío = se omite del payload
    return { ok: true, values: values as HumidityValues };
}

// ---- cálculo de presentación (la fórmula YA EXISTENTE de app/page.tsx; NO se envía) ---------------------------------------------

export type HumidityResult = { comando: number; medio: number; transversal: number; promedio: number };

// humedad = ((húmedo - seco) / húmedo) * 100, 2 decimales; húmedo <= 0 o no numérico -> 0. Promedio = media de las tres humedades ya
// redondeadas, 2 decimales. Solo para mostrar: los datos fuente son los pesos, que quedan en PostgreSQL.
export function computeHumidity(draft: Pick<HumidityDraft, WeightKey>): HumidityResult {
    const num = (raw: string) => Number(raw.trim().replace(/^(-?\d+),(\d+)$/, "$1.$2"));
    const humidity = (position: Position) => {
        const wet = num(draft[`peso_humedo_${position}`]), dry = num(draft[`peso_seco_${position}`]);
        return wet > 0 ? Number((((wet - dry) / wet) * 100).toFixed(2)) : 0;
    };
    const comando = humidity("comando"), medio = humidity("medio"), transversal = humidity("transversal");
    return { comando, medio, transversal, promedio: Number(((comando + medio + transversal) / 3).toFixed(2)) };
}
export const formatHumidity = (value: number): string => value.toFixed(2);

export function buildHumidityPayload(captureId: string, deviceKey: string, values: HumidityValues): HumidityPayload {
    return { capture_id: captureId, form_code: Q19_FORM_CODE, device_key: deviceKey, values: { ...values } };
}

// ---- intento pendiente ----------------------------------------------------------------------------------------------------
// Un UUIDv4 por intento LÓGICO. Congela capture_id, bobbin_id, device_key y values, y el SNAPSHOT visual de la Bobina: reabrirlo muestra
// SIEMPRE esa misma Bobina. No se persiste (sin localStorage; la única persistencia es la clave técnica del dispositivo).

export type PendingHumidityAttempt = {
    readonly captureId: string;
    readonly bobbinId: string;
    readonly payload: Readonly<HumidityPayload>;
    readonly draft: Readonly<HumidityDraft>;
    readonly bobbin: Readonly<QualityBobbinInboxItem>;
};

export function createHumidityAttempt(draft: HumidityDraft, bobbin: QualityBobbinInboxItem, deviceKey: string, makeId: () => string = newQualityCaptureId):
    { ok: true; attempt: PendingHumidityAttempt } | { ok: false; errors: string[] } {
    const check = normalizeHumidityDraft(draft);
    if (!check.ok) return check;
    const captureId = makeId();
    const built = buildHumidityPayload(captureId, deviceKey, check.values);
    const values: Readonly<HumidityValues> = Object.freeze({ ...built.values });
    const payload: Readonly<HumidityPayload> = Object.freeze({ capture_id: built.capture_id, form_code: built.form_code, device_key: built.device_key, values });
    const snapshot = deepFreeze(structuredClone(bobbin)); // el inbox puede cambiar después: el intento conserva SU Bobina, congelada en todos sus niveles
    return { ok: true, attempt: Object.freeze({ captureId, bobbinId: bobbin.bobbin.id, payload, draft: Object.freeze({ ...draft }), bobbin: snapshot }) };
}

// Congela recursivamente un DTO de datos planos (objetos y arrays; los primitivos ya son inmutables). Puro: devuelve el mismo objeto.
export function deepFreeze<T>(value: T): T {
    if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
        for (const child of Object.values(value)) deepFreeze(child);
        Object.freeze(value);
    }
    return value;
}

// ¿Esta captura del servidor ES el intento? Mismo id, misma Bobina, mismo formulario y los MISMOS datos fuente, comparados como texto exacto
// contra los valores congelados del intento (sin floats ni re-normalización). Las observaciones deben tener la misma presencia y el mismo texto.
export function captureMatchesHumidityAttempt(capture: QualityCapture, attempt: PendingHumidityAttempt): boolean {
    if (capture.id !== attempt.captureId || capture.bobbin.id !== attempt.bobbinId || capture.form.code !== Q19_FORM_CODE) return false;
    const sent = attempt.payload.values, stored = capture.values;
    if (WEIGHT_KEYS.some((key) => stored[key] !== sent[key])) return false;
    const sentHas = Object.prototype.hasOwnProperty.call(sent, "observaciones"), storedHas = Object.prototype.hasOwnProperty.call(stored, "observaciones");
    return sentHas === storedHas && (!sentHas || stored.observaciones === sent.observaciones);
}

// Bobina que se muestra: la del intento pendiente si existe; si no, la seleccionada. Nunca se mezclan.
export const bobbinToShow = (attempt: PendingHumidityAttempt | null, selected: QualityBobbinInboxItem | null): Readonly<QualityBobbinInboxItem> | null => (attempt ? attempt.bobbin : selected);

export const pendingNotice = (attempt: PendingHumidityAttempt): string =>
    `Existe un envío pendiente: se reintentará el control de humedad de la bobina ${attempt.bobbin.bobbin.code} (${attempt.bobbin.bobbin.machine.code} · ${attempt.bobbin.production.work_order.number}).`;

// ---- respuesta ------------------------------------------------------------------------------------------------------------

export type QualityCapture = {
    id: string;
    status: string;
    revision: number;
    captured_at: string;
    submitted_at: string | null;
    form: { code: string; version_number: number; name: string };
    bobbin: { id: string; code: string };
    machine: { code: string; name: string };
    shift: { code: string; name: string };
    operating_date: string;
    work_order: { id: string; number: string };
    line: { id: string; line_code: string; pv_reference: string; article: { code: string; description: string } };
    values: HumidityValues;
};
export type QualityCaptureSubmission = { created: boolean; already_submitted: boolean; capture: QualityCapture };

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const pair = (value: unknown): { code: string; name: string } | null =>
    isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
// Los decimales llegan SOLO como texto ("101.000" se conserva exacto). Un número JSON se rechaza: String(101.0) perdería la escala.
const decimalOf = (value: unknown): string | null => (typeof value === "string" && DECIMAL.test(value) ? value : null);

function parseValues(value: unknown): HumidityValues | null {
    if (!isRec(value)) return null;
    const clean: Partial<HumidityValues> = {};
    for (const key of WEIGHT_KEYS) {
        const text = decimalOf(value[key]);
        if (text === null) return null;
        clean[key] = text;
    }
    if (value.observaciones !== undefined) {
        if (typeof value.observaciones !== "string") return null;
        clean.observaciones = value.observaciones;
    }
    return clean as HumidityValues;
}

export function parseQualityCapture(value: unknown): QualityCapture | null {
    if (!isRec(value) || !isStr(value.id) || !(value.status === "submitted" || value.status === "closed")) return null;
    if (typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision <= 0) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, bobbin = value.bobbin, machine = pair(value.machine), shift = pair(value.shift), order = value.work_order, line = value.line;
    if (!isRec(form) || form.code !== Q19_FORM_CODE || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(bobbin) || !isStr(bobbin.id) || !isStr(bobbin.code)) return null;
    if (!isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parseValues(value.values);
    if (!values) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, bobbin: { id: bobbin.id, code: bobbin.code }, machine, shift,
        operating_date: value.operating_date, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        values,
    };
}

export function parseQualityCaptureSubmission(value: unknown): QualityCaptureSubmission | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_submitted !== "boolean") return null;
    const capture = parseQualityCapture(value.capture);
    return capture ? { created: value.created, already_submitted: value.already_submitted, capture } : null;
}

// ---- mensajes y errores ---------------------------------------------------------------------------------------------------

export const HUMIDITY_MESSAGES = {
    offline: "Se requiere conexión para registrar el control de humedad.",
    forbidden: "No tienes permisos para registrar controles de Calidad.",
    notFound: "La bobina ya no existe.",
    formUnavailable: "El formulario Control de humedad no está disponible para esta máquina.",
    idempotency: "No se puede reutilizar este identificador para datos distintos.",
    invalid: "Revisa los campos obligatorios y sus valores.",
    conflict: "El servidor no pudo aceptar el registro. Actualiza y vuelve a intentar.",
    uncertain: "No se pudo confirmar el registro. Reintenta el envío: se reenvía exactamente el mismo control y no se duplicará.",
    notSaved: "El registro no se guardó. Puedes reintentar el envío.",
} as const;

export type HumidityRejectReason = "forbidden" | "not_found" | "form_unavailable" | "idempotency" | "invalid" | "conflict";

// No existe "asignación stale" para Calidad: una asignación terminada de la Bobina no es un error.
export function humidityRejectionFor(status: number, code?: string): { reason: HumidityRejectReason; message: string } | null {
    if (status === 403) return { reason: "forbidden", message: HUMIDITY_MESSAGES.forbidden };
    if (status === 404) return { reason: "not_found", message: HUMIDITY_MESSAGES.notFound };
    if (status === 422) return { reason: "invalid", message: HUMIDITY_MESSAGES.invalid };
    if (status === 409) {
        if (code === "CAPTURE_IDEMPOTENCY_CONFLICT") return { reason: "idempotency", message: HUMIDITY_MESSAGES.idempotency };
        if (code === "FORM_NOT_AVAILABLE") return { reason: "form_unavailable", message: HUMIDITY_MESSAGES.formUnavailable };
        return { reason: "conflict", message: HUMIDITY_MESSAGES.conflict };
    }
    return null;
}

export const humiditySuccessMessage = (capture: QualityCapture, alreadySubmitted = false): string =>
    `Control de humedad ${alreadySubmitted ? "ya registrado" : "registrado"} para la bobina ${capture.bobbin.code} · Calidad sigue pendiente`;

// ---- flujo de envío con reconciliación -------------------------------------------------------------------------------------

export type QualityApiLike<T> = { ok: true; data: T; status: number } | { ok: false; kind: string; status: number; code?: string };
export type HumiditySubmitDeps = {
    post: (bobbinId: string, payload: HumidityPayload) => Promise<QualityApiLike<QualityCaptureSubmission>>;
    get: (captureId: string) => Promise<QualityApiLike<QualityCapture>>;
};

export type HumiditySubmitOutcome =
    | { kind: "submitted"; created: boolean; alreadySubmitted: boolean; reconciled: boolean; capture: QualityCapture; message: string }
    | { kind: "session" }
    | { kind: "rejected"; reason: HumidityRejectReason; message: string } // respuesta definitiva: el intento termina
    | { kind: "not_saved"; message: string } // GET 404 tras un POST incierto: se puede reintentar el MISMO POST
    | { kind: "uncertain"; message: string }; // no se pudo confirmar: se conserva el intento

// POST con el payload del intento. Un 2xx solo es éxito si la captura devuelta ES el intento (captureMatchesHumidityAttempt); si no, se
// reconcilia por GET. Si la respuesta es incierta (red, 5xx, cuerpo ilegible) NO se asume que no se guardó: se consulta
// GET /api/quality/captures/{capture_id} (el id se conoce antes de enviar): la misma captura del intento -> éxito; 404 -> no existe
// (reintento con el mismo id); otro -> incierto. Nunca se genera otro capture_id.
export async function submitHumidityAttempt(attempt: PendingHumidityAttempt, deps: HumiditySubmitDeps): Promise<HumiditySubmitOutcome> {
    const posted = await deps.post(attempt.bobbinId, attempt.payload);
    if (posted.ok) {
        const { created, already_submitted: alreadySubmitted, capture } = posted.data;
        if (captureMatchesHumidityAttempt(capture, attempt)) {
            return { kind: "submitted", created, alreadySubmitted, reconciled: false, capture, message: humiditySuccessMessage(capture, alreadySubmitted && !created) };
        }
        // 2xx que no demuestra identidad: el servidor SÍ respondió con una captura, así que un GET 404 no prueba que no se guardó.
        // Solo el GET exacto da éxito; 404 (y cualquier otra cosa) deja el MISMO intento como incierto. 401 sigue siendo sesión perdida.
        const outcome = await reconcileHumidity(attempt, deps);
        return outcome.kind === "not_saved" ? { kind: "uncertain", message: HUMIDITY_MESSAGES.uncertain } : outcome;
    }
    if (posted.status === 401) return { kind: "session" };
    const rejection = humidityRejectionFor(posted.status, posted.code);
    if (rejection) return { kind: "rejected", ...rejection };
    return reconcileHumidity(attempt, deps);
}

export async function reconcileHumidity(attempt: PendingHumidityAttempt, deps: HumiditySubmitDeps): Promise<HumiditySubmitOutcome> {
    const found = await deps.get(attempt.captureId);
    if (found.ok && captureMatchesHumidityAttempt(found.data, attempt)) {
        return { kind: "submitted", created: false, alreadySubmitted: false, reconciled: true, capture: found.data, message: humiditySuccessMessage(found.data, true) };
    }
    if (!found.ok && found.status === 401) return { kind: "session" };
    if (!found.ok && found.status === 404) return { kind: "not_saved", message: HUMIDITY_MESSAGES.notSaved };
    return { kind: "uncertain", message: HUMIDITY_MESSAGES.uncertain };
}
