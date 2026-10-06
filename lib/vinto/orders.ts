// Órdenes de trabajo y asignaciones CENTRALES (Bobinas): tipos de las respuestas del backend, validación de su forma,
// reglas de contexto de captura, mapeos visuales y constructores de payloads. Todo es PURO (sin red, sin DOM, sin
// imports) para poder probarlo con Node. El backend es la autoridad: aquí no se genera número, línea, unidad, turno
// ni fecha, y las etiquetas visuales nunca se envían en una petición.

export type WorkOrderStatus = "draft" | "published" | "in_progress" | "closed";
export type AssignmentStatus = "active" | "finished";

export type WorkOrderLine = {
    id: string;
    line_code: string;
    pv_reference: string;
    article: { code: string; description: string };
    quantity: number;
    unit: string;
    due_date: string;
};

export type WorkOrder = {
    id: string;
    number: string;
    status: WorkOrderStatus;
    machine: { code: string; name: string };
    baseline: { id: string; version_number: number; published_at: string | null; lines: WorkOrderLine[] };
};

export type Assignment = {
    id: string;
    status: AssignmentStatus;
    operating_date: string;
    created_at: string;
    finished_at: string | null;
    machine: { code: string; name: string };
    shift: { code: string; name: string };
    work_order: { id: string; number: string };
    operational: { version_number: number };
    line: WorkOrderLine;
    assigned_by: { id: string; display_name: string };
};

export type ActiveAssignment = {
    assignment: Assignment | null;
    current_shift: { code: string; name: string; operating_date: string } | null;
    stale: boolean | null;
};

export type Activation = {
    created: boolean;
    already_active: boolean;
    finished_assignment_id: string | null;
    assignment: Assignment;
};

// ---- validación de forma -------------------------------------------------------------------------------------------

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isNullableStr = (value: unknown): value is string | null => value === null || isStr(value);
const WORK_ORDER_STATUSES: readonly string[] = ["draft", "published", "in_progress", "closed"];
const ASSIGNMENT_STATUSES: readonly string[] = ["active", "finished"];

function pair(value: unknown, second: string): { code: string; name: string } | null {
    if (!isRec(value) || !isStr(value.code) || typeof value[second] !== "string") return null;
    return { code: value.code, name: value[second] as string };
}

export function parseLine(value: unknown): WorkOrderLine | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.line_code) || !isStr(value.pv_reference) || !isStr(value.unit) || !isStr(value.due_date)) return null;
    if (typeof value.quantity !== "number" || !Number.isFinite(value.quantity) || value.quantity <= 0) return null;
    const article = value.article;
    if (!isRec(article) || !isStr(article.code) || typeof article.description !== "string") return null;
    return { id: value.id, line_code: value.line_code, pv_reference: value.pv_reference, article: { code: article.code, description: article.description },
        quantity: value.quantity, unit: value.unit, due_date: value.due_date };
}

export function parseWorkOrder(value: unknown): WorkOrder | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.number) || !isStr(value.status) || !WORK_ORDER_STATUSES.includes(value.status)) return null;
    const machine = isRec(value.machine) ? pair(value.machine, "name") : null;
    const baseline = value.baseline;
    if (!machine || !isRec(baseline) || !isStr(baseline.id) || typeof baseline.version_number !== "number" || !isNullableStr(baseline.published_at)) return null;
    if (!Array.isArray(baseline.lines)) return null;
    const lines = baseline.lines.map(parseLine);
    if (lines.some((line) => line === null)) return null;
    return { id: value.id, number: value.number, status: value.status as WorkOrderStatus, machine,
        baseline: { id: baseline.id, version_number: baseline.version_number, published_at: baseline.published_at, lines: lines as WorkOrderLine[] } };
}

export function parseWorkOrderList(value: unknown): WorkOrder[] | null {
    if (!Array.isArray(value)) return null;
    const parsed = value.map(parseWorkOrder);
    return parsed.some((item) => item === null) ? null : (parsed as WorkOrder[]);
}

export function parseAssignment(value: unknown): Assignment | null {
    if (!isRec(value) || !isStr(value.id) || !isStr(value.status) || !ASSIGNMENT_STATUSES.includes(value.status)) return null;
    if (!isStr(value.operating_date) || !isStr(value.created_at) || !isNullableStr(value.finished_at)) return null;
    const machine = isRec(value.machine) ? pair(value.machine, "name") : null;
    const shift = isRec(value.shift) ? pair(value.shift, "name") : null;
    const order = value.work_order, operational = value.operational, user = value.assigned_by;
    if (!machine || !shift || !isRec(order) || !isStr(order.id) || !isStr(order.number)) return null;
    if (!isRec(operational) || typeof operational.version_number !== "number") return null;
    if (!isRec(user) || !isStr(user.id) || typeof user.display_name !== "string") return null;
    const line = parseLine(value.line);
    if (!line) return null;
    return { id: value.id, status: value.status as AssignmentStatus, operating_date: value.operating_date, created_at: value.created_at, finished_at: value.finished_at,
        machine, shift, work_order: { id: order.id, number: order.number }, operational: { version_number: operational.version_number }, line,
        assigned_by: { id: user.id, display_name: user.display_name } };
}

export function parseAssignmentList(value: unknown): Assignment[] | null {
    if (!Array.isArray(value)) return null;
    const parsed = value.map(parseAssignment);
    return parsed.some((item) => item === null) ? null : (parsed as Assignment[]);
}

export function parseActive(value: unknown): ActiveAssignment | null {
    if (!isRec(value) || !("assignment" in value) || !("current_shift" in value) || !("stale" in value)) return null;
    const assignment = value.assignment === null ? null : parseAssignment(value.assignment);
    if (value.assignment !== null && assignment === null) return null;
    let currentShift: ActiveAssignment["current_shift"] = null;
    if (value.current_shift !== null) {
        const shift = isRec(value.current_shift) ? pair(value.current_shift, "name") : null;
        if (!shift || !isRec(value.current_shift) || !isStr(value.current_shift.operating_date)) return null;
        currentShift = { ...shift, operating_date: value.current_shift.operating_date as string };
    }
    if (value.stale !== null && typeof value.stale !== "boolean") return null;
    return { assignment, current_shift: currentShift, stale: value.stale };
}

export function parseActivation(value: unknown): Activation | null {
    if (!isRec(value) || typeof value.created !== "boolean" || typeof value.already_active !== "boolean" || !isNullableStr(value.finished_assignment_id)) return null;
    const assignment = parseAssignment(value.assignment);
    return assignment ? { created: value.created, already_active: value.already_active, finished_assignment_id: value.finished_assignment_id, assignment } : null;
}

// ---- errores HTTP -> categoría y mensaje ------------------------------------------------------------------------------

export type FailureKind = "session" | "forbidden" | "not_found" | "conflict" | "invalid" | "unavailable";

export function failureKindFromStatus(status: number): FailureKind {
    if (status === 401) return "session";
    if (status === 403) return "forbidden";
    if (status === 404) return "not_found";
    if (status === 409) return "conflict";
    if (status === 422) return "invalid";
    return "unavailable"; // 0 (red), 5xx y cualquier otro: nunca se asume nada sobre el estado central
}

export const FAILURE_MESSAGES: Record<FailureKind, string> = {
    session: "La sesión ya no es válida.",
    forbidden: "No tienes permisos para esta acción.",
    not_found: "El registro ya no existe.",
    conflict: "El estado cambió. Actualiza y vuelve a intentar.",
    invalid: "Los datos enviados no son válidos.",
    unavailable: "El servidor no está disponible.",
};

export function failureMessage(kind: FailureKind): string {
    return FAILURE_MESSAGES[kind];
}

export const LOAD_ERROR_TITLE = "No se pudieron cargar las órdenes de trabajo";

// ---- etiquetas visuales (solo presentación) ----------------------------------------------------------------------------

export type OtLabel = "Borrador" | "Publicada" | "En ejecución" | "Cerrada";
export const WORK_ORDER_LABELS: Record<WorkOrderStatus, OtLabel> = { draft: "Borrador", published: "Publicada", in_progress: "En ejecución", closed: "Cerrada" };
export const ASSIGNMENT_LABELS: Record<AssignmentStatus, "Activa" | "Finalizada"> = { active: "Activa", finished: "Finalizada" };

// ---- payloads (solo los campos que el backend acepta; nunca número, line_code, unidad, descripción, ids de versión,
// máquina de la asignación, turno ni fecha operativa) ------------------------------------------------------------------

export type LineDraft = { pvReference: string; articleCode: string; quantity: number; dueDate: string };

export function lineBody(line: LineDraft) {
    return { pv_reference: line.pvReference.trim(), article_code: line.articleCode, quantity: line.quantity, due_date: line.dueDate };
}

export function createWorkOrderPayload(machineCode: string, line: LineDraft) {
    return { machine_code: machineCode, lines: [lineBody(line)] };
}

export const addLinePayload = lineBody;

export function activatePayload(workOrderId: string, baselineLineId: string) {
    return { work_order_id: workOrderId, baseline_line_id: baselineLineId };
}

// Valida el formulario antes de llamar al backend: PV, producto, cantidad > 0 y fecha.
export function parseLineDraft(input: { pv: string; code: string; qty: string; date: string }): LineDraft | null {
    const quantity = Number(input.qty);
    if (!input.pv.trim() || !input.code || !input.date || input.qty.trim() === "" || !Number.isFinite(quantity) || quantity <= 0) return null;
    return { pvReference: input.pv, articleCode: input.code, quantity, dueDate: input.date };
}

// ---- contexto de captura -----------------------------------------------------------------------------------------------

export type CaptureContext = {
    assignmentId: string;
    workOrderId: string;
    otId: string; // número de OT real (OT-AAAA-NNNN)
    lineId: string; // line_code real (L1, L2, ...)
    pv: string;
    productCode: string;
    productName: string;
    machine: string;
    shift: string;
    date: string;
};

export type ContextCheck =
    | { ok: true; context: CaptureContext }
    | { ok: false; reason: "none" | "stale" | "unresolvable"; assignment: Assignment | null };

export const CONTEXT_MESSAGES = {
    none: "Se requiere una asignación activa y vigente.",
    stale: "La asignación activa corresponde a otro turno o fecha operativa. Supervisión debe reactivarla.",
    unresolvable: "No se pudo resolver el turno vigente, por lo que no se permite capturar.",
} as const;

export function captureContextOf(assignment: Assignment): CaptureContext {
    return { assignmentId: assignment.id, workOrderId: assignment.work_order.id, otId: assignment.work_order.number, lineId: assignment.line.line_code,
        pv: assignment.line.pv_reference, productCode: assignment.line.article.code, productName: assignment.line.article.description,
        machine: assignment.machine.code, shift: assignment.shift.name, date: assignment.operating_date };
}

// Producción: SOLO una asignación vigente (stale === false) da contexto. Sin asignación, vencida o con turno no resoluble: no hay captura.
export function contextFromActive(active: ActiveAssignment | null): ContextCheck {
    if (!active || active.assignment === null) return { ok: false, reason: "none", assignment: null };
    if (active.stale === true) return { ok: false, reason: "stale", assignment: active.assignment };
    if (active.stale === null) return { ok: false, reason: "unresolvable", assignment: active.assignment };
    return { ok: true, context: captureContextOf(active.assignment) };
}

// ALCANCE: la asignación central (GET /api/assignments/active) es autoridad ÚNICAMENTE para la ejecución de PRODUCCIÓN de
// Bobinas. Calidad no la consulta ni depende de ella (ni para bloquearse ni para desbloquearse): su contexto llegará con el
// bloque de genealogía/liberación (producción -> captura/bobina -> bobina pendiente -> Calidad), no desde la asignación activa.
export function usesCentralAssignment(front: string, module: string): boolean {
    return front === "Bobinas" && module === "ejecucion";
}

// ---- adaptadores a la forma visual existente (Seguimiento) ---------------------------------------------------------------

export type DisplayOt = {
    id: string; sector: "Bobinas"; machine: string; status: OtLabel; baseline: number;
    lines: { id: string; pv: string; productCode: string; productName: string; quantity: number; unit: string; dueDate: string }[];
};
export type DisplayAssignment = { id: string; ot: string; line: string; machine: string; shift: string; date: string; status: "Activa" | "Finalizada"; by: string };

export function toDisplayOt(order: WorkOrder): DisplayOt {
    return { id: order.number, sector: "Bobinas", machine: order.machine.code, status: WORK_ORDER_LABELS[order.status], baseline: order.baseline.version_number,
        lines: order.baseline.lines.map((line) => ({ id: line.line_code, pv: line.pv_reference, productCode: line.article.code, productName: line.article.description,
            quantity: line.quantity, unit: line.unit, dueDate: line.due_date })) };
}

export function toDisplayAssignment(assignment: Assignment): DisplayAssignment {
    return { id: assignment.id, ot: assignment.work_order.number, line: assignment.line.line_code, machine: assignment.machine.code, shift: assignment.shift.name,
        date: assignment.operating_date, status: ASSIGNMENT_LABELS[assignment.status], by: assignment.assigned_by.display_name };
}
