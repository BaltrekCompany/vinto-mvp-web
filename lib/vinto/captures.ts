// Captura CENTRAL F6 (VINTO-P1-06 · Registro de control de fardos): tipos de las respuestas del backend, validación de su forma,
// opciones (option_key + etiqueta), normalización del borrador, payload exacto, intento pendiente y flujo de envío con
// reconciliación. Todo es PURO (sin red, sin DOM, sin imports en tiempo de ejecución) para probarlo con Node: la red entra por
// funciones inyectadas. El backend es la autoridad: aquí no se envía ni se calcula máquina, turno, fecha operativa, OT, PV,
// producto, línea, versión del formulario, revisión, estado ni usuario.

export const F6_FORM_ID = "form_6_registro_de_control_de_fardos";
export const F6_FORM_CODE = "VINTO-P1-06";

export type Option = { value: string; label: string };
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
export const optionLabel = (options: readonly Option[], value: string) => options.find((o) => o.value === value)?.label ?? value;

// ---- identificadores -----------------------------------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isUuidV4 = (value: unknown): value is string => typeof value === "string" && UUID_V4.test(value);
export const newCaptureId = (): string => crypto.randomUUID();

// ---- respuestas ----------------------------------------------------------------------------------------------------------

export type CentralCapture = {
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
    values: { cantidad_fardos: number; punto_merma: string; tipo_producto: string; peso_kg: string; observaciones?: string };
};

export type CaptureSubmission = { created: boolean; already_submitted: boolean; capture: CentralCapture };

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const DECIMAL = /^-?\d+(\.\d+)?$/;

function pair(value: unknown): { code: string; name: string } | null {
    return isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
}

function parseValues(value: unknown): CentralCapture["values"] | null {
    if (!isRec(value)) return null;
    const { cantidad_fardos: qty, punto_merma: point, tipo_producto: kind, peso_kg: weight, observaciones: notes } = value;
    if (typeof qty !== "number" || !Number.isSafeInteger(qty) || !isStr(point) || !isStr(kind)) return null;
    // Los decimales llegan como texto; un número JSON finito también se acepta y se normaliza a texto.
    const kg = typeof weight === "number" && Number.isFinite(weight) ? String(weight) : weight;
    if (typeof kg !== "string" || !DECIMAL.test(kg)) return null;
    if (notes !== undefined && typeof notes !== "string") return null;
    const clean: CentralCapture["values"] = { cantidad_fardos: qty, punto_merma: point, tipo_producto: kind, peso_kg: kg };
    if (notes !== undefined) clean.observaciones = notes;
    return clean;
}

// Construye un objeto LIMPIO: los campos desconocidos del backend se ignoran.
export function parseCapture(value: unknown): CentralCapture | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.status) || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision)) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, machine = pair(value.machine), shift = pair(value.shift), assignment = value.assignment, order = value.work_order, line = value.line;
    if (!isRec(form) || !isStr(form.code) || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (!isRec(assignment) || !isStr(assignment.id) || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parseValues(value.values);
    if (!values) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, machine, shift, operating_date: value.operating_date,
        assignment: { id: assignment.id }, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        values,
    };
}

export function parseSubmission(value: unknown): CaptureSubmission | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_submitted !== "boolean") return null;
    const capture = parseCapture(value.capture);
    return capture ? { created: value.created, already_submitted: value.already_submitted, capture } : null;
}

export function parseCaptureList(value: unknown): CentralCapture[] | null {
    if (!Array.isArray(value)) return null;
    const parsed = value.map(parseCapture);
    return parsed.some((item) => item === null) ? null : (parsed as CentralCapture[]);
}

// ---- borrador, normalización y payload ------------------------------------------------------------------------------------

export type F6Draft = { cantidad_fardos: string; punto_merma: string; tipo_producto: string; peso_kg: string; observaciones: string };
export const EMPTY_DRAFT: F6Draft = { cantidad_fardos: "", punto_merma: "", tipo_producto: "", peso_kg: "", observaciones: "" };

export type F6Values = { cantidad_fardos: number; punto_merma: string; tipo_producto: string; peso_kg: string; observaciones?: string };
export type CapturePayload = { capture_id: string; form_code: typeof F6_FORM_CODE; assignment_id: string; device_key: string; values: F6Values };

export const MAX_DECIMAL_CHARS = 40; // mismo límite técnico del backend

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

// ---- errores y mensajes ---------------------------------------------------------------------------------------------------

export const SUBMIT_MESSAGES = {
    created: "Registro enviado correctamente.",
    already: "El registro ya había sido recibido.",
    offline: "Se requiere conexión para enviar este registro.",
    forbidden: "No tienes permisos para enviar este registro.",
    notFound: "La asignación o contexto ya no existe.",
    stale: "La asignación ya no corresponde al turno o fecha actual. Solicita a Supervisión que la reactive.",
    notActive: "La asignación ya no está activa.",
    idempotency: "No se puede reutilizar este identificador para datos distintos.",
    invalid: "Revisa los campos obligatorios y sus valores.",
    conflict: "El servidor no pudo aceptar el registro. Actualiza y vuelve a intentar.",
    uncertain: "No se pudo confirmar el envío.",
    notSaved: "El registro no se guardó. Puedes reintentar el envío.",
} as const;

export type RejectReason = "forbidden" | "not_found" | "stale" | "not_active" | "idempotency" | "invalid" | "conflict";

export function rejectionFor(status: number, code?: string): { reason: RejectReason; message: string } | null {
    if (status === 403) return { reason: "forbidden", message: SUBMIT_MESSAGES.forbidden };
    if (status === 404) return { reason: "not_found", message: SUBMIT_MESSAGES.notFound };
    if (status === 422) return { reason: "invalid", message: SUBMIT_MESSAGES.invalid };
    if (status === 409) {
        if (code === "ASSIGNMENT_STALE") return { reason: "stale", message: SUBMIT_MESSAGES.stale };
        if (code === "ASSIGNMENT_NOT_ACTIVE") return { reason: "not_active", message: SUBMIT_MESSAGES.notActive };
        if (code === "CAPTURE_IDEMPOTENCY_CONFLICT") return { reason: "idempotency", message: SUBMIT_MESSAGES.idempotency };
        return { reason: "conflict", message: SUBMIT_MESSAGES.conflict };
    }
    return null;
}

// ---- flujo de envío con reconciliación ------------------------------------------------------------------------------------

export type ApiLike<T> = { ok: true; data: T; status: number } | { ok: false; kind: string; status: number; code?: string };
export type SubmitDeps = {
    post: (payload: CapturePayload) => Promise<ApiLike<CaptureSubmission>>;
    get: (captureId: string) => Promise<ApiLike<CentralCapture>>;
};

export type SubmitOutcome =
    | { kind: "submitted"; created: boolean; alreadySubmitted: boolean; reconciled: boolean; capture: CentralCapture }
    | { kind: "session" }
    | { kind: "rejected"; reason: RejectReason; message: string } // respuesta definitiva del backend: el intento termina
    | { kind: "not_saved"; message: string } // GET 404 tras un POST incierto: se puede reintentar el MISMO POST
    | { kind: "uncertain"; message: string }; // no se pudo confirmar: se conserva el intento

export const submitMessage = (outcome: Extract<SubmitOutcome, { kind: "submitted" }>) =>
    outcome.alreadySubmitted && !outcome.created ? SUBMIT_MESSAGES.already : SUBMIT_MESSAGES.created;

// POST con el payload del intento. Si la respuesta es incierta (red, 5xx, cuerpo ilegible) NO se asume que no se guardó:
// se consulta GET /api/captures/{capture_id}: 200 -> éxito; 404 -> no existe (reintento con el mismo id); otro -> incierto.
export async function submitAttempt(attempt: PendingAttempt, deps: SubmitDeps): Promise<SubmitOutcome> {
    const posted = await deps.post(attempt.payload);
    if (posted.ok) return { kind: "submitted", created: posted.data.created, alreadySubmitted: posted.data.already_submitted, reconciled: false, capture: posted.data.capture };
    if (posted.status === 401) return { kind: "session" };
    const rejection = rejectionFor(posted.status, posted.code);
    if (rejection) return { kind: "rejected", ...rejection };
    return reconcile(attempt.captureId, deps);
}

export async function reconcile(captureId: string, deps: SubmitDeps): Promise<SubmitOutcome> {
    const found = await deps.get(captureId);
    if (found.ok && found.data.id === captureId) return { kind: "submitted", created: false, alreadySubmitted: false, reconciled: true, capture: found.data };
    if (!found.ok && found.status === 401) return { kind: "session" };
    if (!found.ok && found.status === 404) return { kind: "not_saved", message: SUBMIT_MESSAGES.notSaved };
    return { kind: "uncertain", message: SUBMIT_MESSAGES.uncertain };
}
