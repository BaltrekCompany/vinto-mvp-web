// Captura CENTRAL de Calidad · VINTO-P1-20 "Propiedades físicas de bobina" ligada a una Bobina física. PURO (sin red, sin DOM, sin imports
// en tiempo de ejecución) para probarlo con Node: la red entra por funciones inyectadas. Mismo patrón que P1-19 (quality-captures.ts), con
// su PROPIO contrato y parsers estrictos: los de P1-19 no se relajan ni se reutilizan para otro formulario. El backend es la autoridad: solo
// viajan capture_id, form_code, device_key y las ONCE mediciones fuente (+ observaciones). Los promedios se calculan SOLO para mostrarlos y
// nunca se envían ni se guardan. Contexto (máquina, turno, fecha, OT, PV, artículo, gramaje nominal, cortes) lo deriva el backend de la F3.
// Unidades y etiquetas son PROVISIONALES (contrato Q3.2-A): sin mínimos, máximos, tolerancias ni conformidad. No libera ni rechaza nada.

import type { QualityBobbinInboxItem } from "./quality-bobbins.ts"; // solo tipo: se borra al compilar

export const Q20_FORM_ID = "form_20_propiedades_fisicas_de_bobina";
export const Q20_FORM_CODE = "VINTO-P1-20";

// ---- identificadores -----------------------------------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isUuidV4 = (value: unknown): value is string => typeof value === "string" && UUID_V4.test(value);
export const newPhysicalCaptureId = (): string => crypto.randomUUID();

// ---- campos (claves técnicas EXACTAS del bundle; *_centro se muestra como «Comando») ---------------------------------------

export const PHYSICAL_POSITIONS = ["centro", "medio", "extremo"] as const;
export type PhysicalPosition = (typeof PHYSICAL_POSITIONS)[number];
export const PHYSICAL_POSITION_LABELS: Record<PhysicalPosition, string> = { centro: "Comando", medio: "Medio", extremo: "Extremo" };

export type PhysicalKey =
    | "crepado" | "gramaje"
    | "resistencia_longitudinal_centro" | "resistencia_longitudinal_medio" | "resistencia_longitudinal_extremo"
    | "resistencia_transversal_centro" | "resistencia_transversal_medio" | "resistencia_transversal_extremo"
    | "espesor_centro" | "espesor_medio" | "espesor_extremo";
export type PhysicalSeries = "resistencia_longitudinal" | "resistencia_transversal" | "espesor";
export const PHYSICAL_SERIES: readonly PhysicalSeries[] = ["resistencia_longitudinal", "resistencia_transversal", "espesor"];
export const seriesKeys = (series: PhysicalSeries): PhysicalKey[] => PHYSICAL_POSITIONS.map((p) => `${series}_${p}` as PhysicalKey);
// Orden del contrato publicado (display_order 1..11).
export const PHYSICAL_KEYS: readonly PhysicalKey[] = ["crepado", "gramaje", ...PHYSICAL_SERIES.flatMap(seriesKeys)];

export const PHYSICAL_LABELS: Record<PhysicalKey, string> = {
    crepado: "Crepado", gramaje: "Gramaje medido por Calidad",
    resistencia_longitudinal_centro: "Resistencia longitudinal · Comando", resistencia_longitudinal_medio: "Resistencia longitudinal · Medio", resistencia_longitudinal_extremo: "Resistencia longitudinal · Extremo",
    resistencia_transversal_centro: "Resistencia transversal · Comando", resistencia_transversal_medio: "Resistencia transversal · Medio", resistencia_transversal_extremo: "Resistencia transversal · Extremo",
    espesor_centro: "Espesor · Comando", espesor_medio: "Espesor · Medio", espesor_extremo: "Espesor · Extremo",
};
// Unidades VISUALES provisionales (no viajan): g/m² del gramaje medido y mm del espesor. Crepado y resistencias sin unidad (no se inventa).
export const PHYSICAL_UNITS: Partial<Record<PhysicalKey, string>> = { gramaje: "g/m²", espesor_centro: "mm", espesor_medio: "mm", espesor_extremo: "mm" };
export const SERIES_LABELS: Record<PhysicalSeries, string> = { resistencia_longitudinal: "Resistencia longitudinal", resistencia_transversal: "Resistencia transversal", espesor: "Espesor" };
export const PHYSICAL_GROUPS: readonly { title: string; keys: readonly PhysicalKey[] }[] = [
    { title: "Crepado y gramaje medido", keys: ["crepado", "gramaje"] },
    ...PHYSICAL_SERIES.map((series) => ({ title: SERIES_LABELS[series], keys: seriesKeys(series) })),
];

export type PhysicalDraft = Record<PhysicalKey, string> & { observaciones: string };
export const EMPTY_PHYSICAL_DRAFT: PhysicalDraft = {
    crepado: "", gramaje: "", resistencia_longitudinal_centro: "", resistencia_longitudinal_medio: "", resistencia_longitudinal_extremo: "",
    resistencia_transversal_centro: "", resistencia_transversal_medio: "", resistencia_transversal_extremo: "", espesor_centro: "", espesor_medio: "", espesor_extremo: "",
    observaciones: "",
};

export type PhysicalValues = Record<PhysicalKey, string> & { observaciones?: string };
export type PhysicalPayload = { capture_id: string; form_code: typeof Q20_FORM_CODE; device_key: string; values: PhysicalValues };

export const MAX_DECIMAL_CHARS = 40; // límites técnicos equivalentes a los del backend, no funcionales
export const MAX_TEXT_CHARS = 10_000;
const DECIMAL = /^-?\d+(\.\d+)?$/;

export type PhysicalDraftCheck = { ok: true; values: PhysicalValues } | { ok: false; errors: string[] };

// Coma decimal -> punto (resto de dígitos intacto). Sin rangos: solo "es un decimal" y el límite técnico de longitud. Texto, nunca float.
// Misma regla que decimalText() de P1-19 (se comprueba en las pruebas).
export function physicalDecimalText(raw: string): string | null {
    let text = raw.trim();
    if (/^-?\d+,\d+$/.test(text)) text = text.replace(",", ".");
    return DECIMAL.test(text) && text.length <= MAX_DECIMAL_CHARS ? text : null;
}

export function normalizePhysicalDraft(draft: PhysicalDraft): PhysicalDraftCheck {
    const errors: string[] = [];
    const values: Partial<PhysicalValues> = {};
    for (const key of PHYSICAL_KEYS) {
        const text = physicalDecimalText(draft[key]);
        if (text === null) errors.push(`${PHYSICAL_LABELS[key]}: ingresa un número decimal.`);
        else values[key] = text;
    }
    const notes = draft.observaciones.trim();
    if (notes.length > MAX_TEXT_CHARS) errors.push("Observaciones: demasiado largas.");
    if (errors.length) return { ok: false, errors };
    if (notes) values.observaciones = notes; // vacío = se omite del payload
    return { ok: true, values: values as PhysicalValues };
}

// ---- promedios de PRESENTACIÓN (provisionales; NO se envían ni se guardan) -----------------------------------------------------
// Media aritmética de las tres posiciones, con aritmética DECIMAL EXACTA (BigInt sobre los dígitos de texto): sin float, sin NaN/Infinity,
// sin pérdida en valores grandes. Si falta o es inválida una posición: "incomplete" (nunca un 0 ficticio). Representación provisional (no
// aprobada por VINTO): si la media es exacta con la escala de las entradas se muestra tal cual; si no, se muestra con DOS decimales más,
// redondeando la última cifra la mitad lejos de cero, marcada como aproximada ("≈").

export type AverageView = { kind: "exact"; text: string } | { kind: "approx"; text: string } | { kind: "incomplete" };
export const AVERAGE_EXTRA_DIGITS = 2;

const ZERO = BigInt(0), ONE = BigInt(1);
const pow10 = (n: number) => BigInt(`1${"0".repeat(n)}`);
function scaled(text: string, scale: number): bigint {
    const [whole, frac = ""] = text.replace("-", "").split(".");
    const digits = BigInt(whole + frac.padEnd(scale, "0"));
    return text.startsWith("-") ? -digits : digits;
}
function formatScaled(value: bigint, scale: number): string {
    const negative = value < ZERO;
    const digits = (negative ? -value : value).toString().padStart(scale + 1, "0");
    const body = scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
    return negative ? `-${body}` : body;
}

export function averageOf(raws: readonly string[]): AverageView {
    const texts = raws.map(physicalDecimalText);
    if (texts.length === 0 || texts.some((t) => t === null)) return { kind: "incomplete" };
    const valid = texts as string[];
    const scale = Math.max(...valid.map((t) => (t.split(".")[1] ?? "").length));
    const count = BigInt(valid.length);
    const sum = valid.reduce((acc, t) => acc + scaled(t, scale), ZERO);
    if (sum % count === ZERO) return { kind: "exact", text: formatScaled(sum / count, scale) };
    const widened = sum * pow10(AVERAGE_EXTRA_DIGITS);
    let quotient = widened / count; // BigInt trunca hacia cero
    const remainder = widened % count;
    if ((remainder < ZERO ? -remainder : remainder) * BigInt(2) >= count) quotient += widened < ZERO ? -ONE : ONE;
    return { kind: "approx", text: formatScaled(quotient, scale + AVERAGE_EXTRA_DIGITS) };
}

export type PhysicalAverages = Record<PhysicalSeries, AverageView>;
export function physicalAverages(draft: Pick<PhysicalDraft, PhysicalKey>): PhysicalAverages {
    const averages = {} as PhysicalAverages;
    for (const series of PHYSICAL_SERIES) averages[series] = averageOf(seriesKeys(series).map((k) => draft[k]));
    return averages;
}
export const averageLabel = (view: AverageView): string => (view.kind === "incomplete" ? "—" : view.kind === "approx" ? `≈ ${view.text}` : view.text);

export function buildPhysicalPayload(captureId: string, deviceKey: string, values: PhysicalValues): PhysicalPayload {
    return { capture_id: captureId, form_code: Q20_FORM_CODE, device_key: deviceKey, values: { ...values } };
}

// ---- intento pendiente ----------------------------------------------------------------------------------------------------
// Un UUIDv4 por intento LÓGICO. Congela capture_id, bobbin_id, device_key, form_code, values y el SNAPSHOT visual de la Bobina: reabrirlo
// muestra SIEMPRE esa misma Bobina. Vive solo en memoria (sin localStorage; la única persistencia es la clave técnica del dispositivo).

export type PendingPhysicalAttempt = {
    readonly captureId: string;
    readonly bobbinId: string;
    readonly payload: Readonly<PhysicalPayload>;
    readonly draft: Readonly<PhysicalDraft>;
    readonly bobbin: Readonly<QualityBobbinInboxItem>;
};

export function deepFreeze<T>(value: T): T {
    if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
        for (const child of Object.values(value)) deepFreeze(child);
        Object.freeze(value);
    }
    return value;
}

export function createPhysicalAttempt(draft: PhysicalDraft, bobbin: QualityBobbinInboxItem, deviceKey: string, makeId: () => string = newPhysicalCaptureId):
    { ok: true; attempt: PendingPhysicalAttempt } | { ok: false; errors: string[] } {
    const check = normalizePhysicalDraft(draft);
    if (!check.ok) return check;
    const captureId = makeId();
    const payload = deepFreeze(buildPhysicalPayload(captureId, deviceKey, check.values));
    const snapshot = deepFreeze(structuredClone(bobbin)); // el inbox puede cambiar después: el intento conserva SU Bobina
    return { ok: true, attempt: deepFreeze({ captureId, bobbinId: bobbin.bobbin.id, payload, draft: { ...draft }, bobbin: snapshot }) };
}

// Bobina que se muestra: la del intento pendiente si existe; si no, la seleccionada. Nunca se mezclan.
export const physicalBobbinToShow = (attempt: PendingPhysicalAttempt | null, selected: QualityBobbinInboxItem | null): Readonly<QualityBobbinInboxItem> | null => (attempt ? attempt.bobbin : selected);

export const physicalPendingNotice = (attempt: PendingPhysicalAttempt): string =>
    `Existe un envío pendiente: se reintentará el control de propiedades físicas de la bobina ${attempt.bobbin.bobbin.code} (${attempt.bobbin.bobbin.machine.code} · ${attempt.bobbin.production.work_order.number}).`;

// ---- respuesta (parser ESTRICTO P1-20) ----------------------------------------------------------------------------------------

export type PhysicalCapture = {
    id: string;
    status: string;
    revision: number;
    captured_at: string;
    submitted_at: string | null;
    form: { code: typeof Q20_FORM_CODE; version_number: number; name: string };
    bobbin: { id: string; code: string };
    machine: { code: string; name: string };
    shift: { code: string; name: string };
    operating_date: string;
    work_order: { id: string; number: string };
    line: { id: string; line_code: string; pv_reference: string; article: { code: string; description: string } };
    values: PhysicalValues;
};
export type PhysicalCaptureSubmission = { created: boolean; already_submitted: boolean; capture: PhysicalCapture };

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const pair = (value: unknown): { code: string; name: string } | null =>
    isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
// Decimales SOLO como texto ("15.500" se conserva exacto). Un número JSON se rechaza: String(15.5) perdería la escala.
const decimalOf = (value: unknown): string | null => (typeof value === "string" && DECIMAL.test(value) ? value : null);
const ALLOWED_VALUE_KEYS = new Set<string>([...PHYSICAL_KEYS, "observaciones"]);

function parsePhysicalValues(value: unknown): PhysicalValues | null {
    if (!isRec(value) || Object.keys(value).some((k) => !ALLOWED_VALUE_KEYS.has(k))) return null; // ni promedios ni campos ajenos
    const clean: Partial<PhysicalValues> = {};
    for (const key of PHYSICAL_KEYS) {
        const text = decimalOf(value[key]);
        if (text === null) return null;
        clean[key] = text;
    }
    if (value.observaciones !== undefined) {
        if (typeof value.observaciones !== "string") return null;
        clean.observaciones = value.observaciones;
    }
    return clean as PhysicalValues;
}

export function parsePhysicalCapture(value: unknown): PhysicalCapture | null {
    if (!isRec(value) || !isStr(value.id) || !(value.status === "submitted" || value.status === "closed")) return null;
    if (typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision <= 0) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, bobbin = value.bobbin, machine = pair(value.machine), shift = pair(value.shift), order = value.work_order, line = value.line;
    if (!isRec(form) || form.code !== Q20_FORM_CODE || typeof form.version_number !== "number" || !Number.isSafeInteger(form.version_number) || form.version_number <= 0) return null;
    if (typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(bobbin) || !isStr(bobbin.id) || !isStr(bobbin.code)) return null;
    if (!isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parsePhysicalValues(value.values);
    if (!values) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: Q20_FORM_CODE, version_number: form.version_number, name: form.name }, bobbin: { id: bobbin.id, code: bobbin.code }, machine, shift,
        operating_date: value.operating_date, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        values,
    };
}

export function parsePhysicalCaptureSubmission(value: unknown): PhysicalCaptureSubmission | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_submitted !== "boolean") return null;
    const capture = parsePhysicalCapture(value.capture);
    return capture ? { created: value.created, already_submitted: value.already_submitted, capture } : null;
}

// ¿Esta captura del servidor ES el intento? Mismo id, misma Bobina, mismo formulario y los MISMOS datos fuente, como texto exacto contra los
// valores congelados (sin floats ni re-normalización). Observaciones: misma presencia y mismo texto.
export function captureMatchesPhysicalAttempt(capture: PhysicalCapture, attempt: PendingPhysicalAttempt): boolean {
    if (capture.id !== attempt.captureId || capture.bobbin.id !== attempt.bobbinId || capture.form.code !== attempt.payload.form_code) return false;
    const sent = attempt.payload.values, stored = capture.values;
    if (PHYSICAL_KEYS.some((key) => stored[key] !== sent[key])) return false;
    const sentHas = Object.prototype.hasOwnProperty.call(sent, "observaciones"), storedHas = Object.prototype.hasOwnProperty.call(stored, "observaciones");
    return sentHas === storedHas && (!sentHas || stored.observaciones === sent.observaciones);
}

// ---- mensajes y errores ---------------------------------------------------------------------------------------------------

export const PHYSICAL_MESSAGES = {
    offline: "Se requiere conexión para registrar las propiedades físicas.",
    forbidden: "No tienes permisos para registrar controles de Calidad.",
    notFound: "La bobina ya no existe.",
    formUnavailable: "El formulario Propiedades físicas de bobina (VINTO-P1-20) todavía no está publicado en esta base de datos o para esta máquina.",
    idempotency: "El servidor ya tiene otro registro con este identificador. No se reenvió: revisa el historial de controles de la bobina antes de registrar de nuevo.",
    invalid: "El servidor rechazó los valores: revisa los campos obligatorios y su formato.",
    conflict: "El servidor no pudo aceptar el registro. Actualiza y vuelve a intentar.",
    uncertain: "No se pudo confirmar el registro. Reintenta el envío: se reenvía exactamente el mismo control y no se duplicará.",
    notSaved: "El registro no se guardó. Reintenta el envío: se reenvía el mismo control con el mismo identificador.",
} as const;

export type PhysicalRejectReason = "forbidden" | "not_found" | "form_unavailable" | "idempotency" | "invalid" | "conflict";

// Respuestas DEFINITIVAS (el servidor decidió): 403, 404, 409, 422. 401 se trata aparte (sesión). El resto es incierto.
export function physicalRejectionFor(status: number, code?: string): { reason: PhysicalRejectReason; message: string } | null {
    if (status === 403) return { reason: "forbidden", message: PHYSICAL_MESSAGES.forbidden };
    if (status === 404) return { reason: "not_found", message: PHYSICAL_MESSAGES.notFound };
    if (status === 422) return { reason: "invalid", message: PHYSICAL_MESSAGES.invalid };
    if (status === 409) {
        if (code === "CAPTURE_IDEMPOTENCY_CONFLICT") return { reason: "idempotency", message: PHYSICAL_MESSAGES.idempotency };
        if (code === "FORM_NOT_AVAILABLE") return { reason: "form_unavailable", message: PHYSICAL_MESSAGES.formUnavailable };
        return { reason: "conflict", message: PHYSICAL_MESSAGES.conflict };
    }
    return null;
}

export const physicalSuccessMessage = (capture: PhysicalCapture, alreadySubmitted = false): string =>
    `Propiedades físicas ${alreadySubmitted ? "ya registradas" : "registradas"} para la bobina ${capture.bobbin.code} · Calidad sigue pendiente`;

// ---- flujo de envío con reconciliación -------------------------------------------------------------------------------------

export type PhysicalApiLike<T> = { ok: true; data: T; status: number } | { ok: false; kind: string; status: number; code?: string };
export type PhysicalSubmitDeps = {
    post: (bobbinId: string, payload: PhysicalPayload) => Promise<PhysicalApiLike<PhysicalCaptureSubmission>>;
    get: (captureId: string) => Promise<PhysicalApiLike<PhysicalCapture>>;
};

export type PhysicalSubmitOutcome =
    | { kind: "submitted"; created: boolean; alreadySubmitted: boolean; reconciled: boolean; capture: PhysicalCapture; message: string }
    | { kind: "session" }
    | { kind: "rejected"; reason: PhysicalRejectReason; message: string } // respuesta definitiva: el intento termina (nunca se genera otro UUID solo)
    | { kind: "not_saved"; message: string } // GET 404 tras un POST incierto: se reintenta el MISMO POST (mismo UUID)
    | { kind: "uncertain"; message: string }; // no se pudo confirmar: se conserva el intento

// POST con el payload congelado. Un 2xx solo es éxito si la captura devuelta ES el intento; si no, se reconcilia por GET. Si la respuesta es
// incierta (red, tiempo agotado, 5xx, cuerpo ilegible) NO se asume nada: GET /api/quality/captures/{capture_id}. Nunca otro capture_id.
export async function submitPhysicalAttempt(attempt: PendingPhysicalAttempt, deps: PhysicalSubmitDeps): Promise<PhysicalSubmitOutcome> {
    const posted = await deps.post(attempt.bobbinId, attempt.payload);
    if (posted.ok) {
        const { created, already_submitted: alreadySubmitted, capture } = posted.data;
        if (captureMatchesPhysicalAttempt(capture, attempt)) {
            return { kind: "submitted", created, alreadySubmitted, reconciled: false, capture, message: physicalSuccessMessage(capture, alreadySubmitted && !created) };
        }
        // 2xx que no demuestra identidad: el servidor SÍ respondió con una captura, así que un GET 404 no prueba que no se guardó.
        const outcome = await reconcilePhysical(attempt, deps);
        return outcome.kind === "not_saved" ? { kind: "uncertain", message: PHYSICAL_MESSAGES.uncertain } : outcome;
    }
    if (posted.status === 401) return { kind: "session" };
    const rejection = physicalRejectionFor(posted.status, posted.code);
    if (rejection) return { kind: "rejected", ...rejection };
    return reconcilePhysical(attempt, deps);
}

export async function reconcilePhysical(attempt: PendingPhysicalAttempt, deps: PhysicalSubmitDeps): Promise<PhysicalSubmitOutcome> {
    const found = await deps.get(attempt.captureId);
    if (found.ok && captureMatchesPhysicalAttempt(found.data, attempt)) {
        return { kind: "submitted", created: false, alreadySubmitted: false, reconciled: true, capture: found.data, message: physicalSuccessMessage(found.data, true) };
    }
    if (!found.ok && found.status === 401) return { kind: "session" };
    if (!found.ok && found.status === 404) return { kind: "not_saved", message: PHYSICAL_MESSAGES.notSaved };
    return { kind: "uncertain", message: PHYSICAL_MESSAGES.uncertain };
}
