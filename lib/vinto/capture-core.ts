// Núcleo COMÚN de las capturas centrales de producción (M2-B1): lo que no depende del formulario. Extraído de captures.ts (F6) sin cambiar su
// comportamiento; F6 y los formularios siguientes lo especializan con su propio parser de `values`, su borrador y su payload.
// Todo es PURO (sin red, sin DOM, sin imports en tiempo de ejecución) para probarlo con Node. Lo que SÍ es específico de cada formulario (valores,
// validaciones, opciones, código) NO está aquí: el envelope solo acepta lo que el backend garantiza para cualquier captura central.

export type Option = { value: string; label: string };
export const optionLabel = (options: readonly Option[], value: string) => options.find((o) => o.value === value)?.label ?? value;

// ---- identificadores -----------------------------------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const isUuidV4 = (value: unknown): value is string => typeof value === "string" && UUID_V4.test(value);
export const newCaptureId = (): string => crypto.randomUUID();

// ---- respuestas: envelope común --------------------------------------------------------------------------------------------

export type CaptureEnvelope = {
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
};
export type CaptureOf<V> = CaptureEnvelope & { values: V };
export type SubmissionOf<C> = { created: boolean; already_submitted: boolean; capture: C };

export type Rec = Record<string, unknown>;
export const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
export const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
export const DECIMAL = /^-?\d+(\.\d+)?$/;
export const MAX_DECIMAL_CHARS = 40; // mismo límite técnico del backend

function pair(value: unknown): { code: string; name: string } | null {
    return isRec(value) && isStr(value.code) && typeof value.name === "string" ? { code: value.code, name: value.name } : null;
}

// Construye un objeto LIMPIO (los campos desconocidos del backend se ignoran). `parseValues` es el parser ESTRICTO del formulario: si devuelve null,
// toda la captura se rechaza. Con `expectedFormCode` se rechaza además una captura de OTRO formulario (un parser nuevo debería indicarlo siempre).
export function parseCaptureOf<V>(value: unknown, parseValues: (values: unknown, version?: number) => V | null, expectedFormCode?: string): CaptureOf<V> | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.status) || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision)) return null;
    if (!isStr(value.captured_at) || !(value.submitted_at === null || isStr(value.submitted_at)) || !isStr(value.operating_date)) return null;
    const form = value.form, machine = pair(value.machine), shift = pair(value.shift), assignment = value.assignment, order = value.work_order, line = value.line;
    if (!isRec(form) || !isStr(form.code) || typeof form.version_number !== "number" || typeof form.name !== "string" || !machine || !shift) return null;
    if (expectedFormCode !== undefined && form.code !== expectedFormCode) return null;
    if (!isRec(assignment) || !isStr(assignment.id) || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(line) || !isStr(line.id) || !isStr(line.line_code) || !isStr(line.pv_reference) || !isRec(line.article) || !isStr(line.article.code) || typeof line.article.description !== "string") return null;
    const values = parseValues(value.values, form.version_number as number); // MF-10: cada captura se interpreta con la definición de SU versión
    if (values === null) return null;
    return {
        id: value.id, status: value.status, revision: value.revision, captured_at: value.captured_at, submitted_at: value.submitted_at,
        form: { code: form.code, version_number: form.version_number, name: form.name }, machine, shift, operating_date: value.operating_date,
        assignment: { id: assignment.id }, work_order: { id: order.id, number: order.number },
        line: { id: line.id, line_code: line.line_code, pv_reference: line.pv_reference, article: { code: line.article.code, description: line.article.description } },
        values,
    };
}

export function parseSubmissionOf<C>(value: unknown, parseOne: (capture: unknown) => C | null): SubmissionOf<C> | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_submitted !== "boolean") return null;
    const capture = parseOne(value.capture);
    return capture ? { created: value.created, already_submitted: value.already_submitted, capture } : null;
}

export function parseCaptureListOf<C>(value: unknown, parseOne: (capture: unknown) => C | null): C[] | null {
    if (!Array.isArray(value)) return null;
    const parsed = value.map(parseOne);
    return parsed.some((item) => item === null) ? null : (parsed as C[]);
}

// ---- intento pendiente (genérico) --------------------------------------------------------------------------------------------
// Un UUIDv4 por intento LÓGICO de envío. Mientras no se sepa con certeza si el servidor guardó, capture_id, assignment_id, device_key y values se
// conservan EXACTAMENTE (el payload es inmutable, también `values`) y los campos del formulario quedan bloqueados.
export type PendingAttemptOf<P extends { capture_id: string }, D> = { readonly captureId: string; readonly payload: Readonly<P>; readonly draft: Readonly<D> };

// Copia PROFUNDA y congelada: ni el payload ni el borrador comparten referencias con el estado de la pantalla (p. ej. las listas de filas de un grupo repetible), de modo que
// agregar, eliminar o editar filas después NO modifica un intento pendiente.
function deepFreeze<T>(value: T): T {
    if (typeof value === "object" && value !== null) for (const inner of Object.values(value)) deepFreeze(inner);
    return Object.freeze(value);
}

export function freezeAttempt<P extends { capture_id: string; values: object }, D extends object>(payload: P, draft: D): PendingAttemptOf<P, D> {
    return deepFreeze({ captureId: payload.capture_id, payload: structuredClone(payload) as Readonly<P>, draft: structuredClone(draft) as Readonly<D> });
}

// ---- rutas de lectura (sin red) ----------------------------------------------------------------------------------------------

// `form_code` es opcional: sin él el backend devuelve el comportamiento histórico (F6). Con él, el backend exige que el formulario esté habilitado (422 si no).
export function capturesListPath(limit = 50, formCode?: string): string {
    return `/api/captures?limit=${limit}${formCode === undefined ? "" : `&form_code=${encodeURIComponent(formCode)}`}`;
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

// ---- flujo de envío con reconciliación (independiente del formulario) -----------------------------------------------------------

export type ApiLike<T> = { ok: true; data: T; status: number } | { ok: false; kind: string; status: number; code?: string };
export type SubmitDepsOf<P, S, C> = {
    post: (payload: P) => Promise<ApiLike<S>>;
    get: (captureId: string) => Promise<ApiLike<C>>;
};

export type SubmitOutcomeOf<C> =
    | { kind: "submitted"; created: boolean; alreadySubmitted: boolean; reconciled: boolean; capture: C }
    | { kind: "session" }
    | { kind: "rejected"; reason: RejectReason; message: string } // respuesta definitiva del backend: el intento termina
    | { kind: "not_saved"; message: string } // GET 404 tras un POST incierto: se puede reintentar el MISMO POST
    | { kind: "uncertain"; message: string }; // no se pudo confirmar: se conserva el intento

export const submitMessage = (outcome: { created: boolean; alreadySubmitted: boolean }) =>
    outcome.alreadySubmitted && !outcome.created ? SUBMIT_MESSAGES.already : SUBMIT_MESSAGES.created;

// POST con el payload del intento. Si la respuesta es incierta (red, 5xx, cuerpo ilegible) NO se asume que no se guardó:
// se consulta GET /api/captures/{capture_id}: 200 -> éxito; 404 -> no existe (reintento con el mismo id); otro -> incierto.
export async function submitAttemptOf<P, S extends SubmissionOf<C>, C extends { id: string }>(
    attempt: { readonly captureId: string; readonly payload: Readonly<P> }, deps: SubmitDepsOf<P, S, C>,
): Promise<SubmitOutcomeOf<C>> {
    const posted = await deps.post(attempt.payload);
    if (posted.ok) return { kind: "submitted", created: posted.data.created, alreadySubmitted: posted.data.already_submitted, reconciled: false, capture: posted.data.capture };
    if (posted.status === 401) return { kind: "session" };
    const rejection = rejectionFor(posted.status, posted.code);
    if (rejection) return { kind: "rejected", ...rejection };
    return reconcileOf(attempt.captureId, deps);
}

export async function reconcileOf<P, S, C extends { id: string }>(captureId: string, deps: SubmitDepsOf<P, S, C>): Promise<SubmitOutcomeOf<C>> {
    const found = await deps.get(captureId);
    if (found.ok && found.data.id === captureId) return { kind: "submitted", created: false, alreadySubmitted: false, reconciled: true, capture: found.data };
    if (!found.ok && found.status === 401) return { kind: "session" };
    if (!found.ok && found.status === 404) return { kind: "not_saved", message: SUBMIT_MESSAGES.notSaved };
    return { kind: "uncertain", message: SUBMIT_MESSAGES.uncertain };
}
