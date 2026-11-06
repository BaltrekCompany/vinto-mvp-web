// E1-05: server-authoritative logical line execution for Supervisión.
// Pure module: no frontend state, network or client-side authorization.
export type ExecutionStatus = "planned" | "enabled" | "in_production" | "finished" | "requires_review";

export type ExecutionLine = {
    baseline_line_id: string;
    line_code: string;
    machine_code: string;
    status: ExecutionStatus;
    current_assignment_id: string | null;
    started_at: string | null;
    started_by: string | null;
    finished_at: string | null;
    finished_by: string | null;
};

export type WorkOrderExecution = { work_order_id: string; lines: ExecutionLine[] };

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => v !== null && typeof v === "object" && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const nullable = (v: unknown): v is string | null => v === null || isStr(v);
const STATUSES: readonly string[] = ["planned", "enabled", "in_production", "finished", "requires_review"];
export const EXECUTION_LABELS: Record<ExecutionStatus, string> = {
    planned: "Programada",
    enabled: "Habilitada",
    in_production: "En producción",
    finished: "Finalizada",
    requires_review: "Requiere revisión",
};

export function parseWorkOrderExecution(value: unknown): WorkOrderExecution | null {
    if (!isRec(value) || !isStr(value.work_order_id) || !Array.isArray(value.lines)) return null;
    const lines: ExecutionLine[] = [];
    const seen = new Set<string>();
    for (const raw of value.lines) {
        if (!isRec(raw) || !isStr(raw.baseline_line_id) || !isStr(raw.line_code)
            || !isStr(raw.machine_code) || !isStr(raw.status) || !STATUSES.includes(raw.status)
            || !nullable(raw.current_assignment_id) || !nullable(raw.started_at)
            || !nullable(raw.started_by) || !nullable(raw.finished_at) || !nullable(raw.finished_by)) return null;
        if (seen.has(raw.baseline_line_id) || seen.has(raw.line_code)) return null;
        seen.add(raw.baseline_line_id); seen.add(raw.line_code);
        lines.push({
            baseline_line_id: raw.baseline_line_id, line_code: raw.line_code,
            machine_code: raw.machine_code, status: raw.status as ExecutionStatus,
            current_assignment_id: raw.current_assignment_id,
            started_at: raw.started_at, started_by: raw.started_by,
            finished_at: raw.finished_at, finished_by: raw.finished_by,
        });
    }
    return { work_order_id: value.work_order_id, lines };
}

export type LineActionView = {
    canStart: boolean;
    canFinish: boolean;
    reason: string | null;
};

export function actionForLine(line: ExecutionLine, orderStatus: string, lines: readonly ExecutionLine[]): LineActionView {
    if (orderStatus !== "in_progress") return { canStart: false, canFinish: false, reason: "La OT no está en ejecución." };
    if (line.status === "finished") return { canStart: false, canFinish: false, reason: "La línea ya fue finalizada." };
    if (line.status === "requires_review") return { canStart: false, canFinish: false, reason: "Asignación heredada: requiere revisión de Supervisión." };
    if (line.status === "planned") return { canStart: false, canFinish: false, reason: "Primero habilita la línea en el turno correspondiente." };
    if (line.status === "in_production") return { canStart: false, canFinish: true, reason: null };
    const occupied = lines.find(item => item.machine_code === line.machine_code
        && item.baseline_line_id !== line.baseline_line_id && item.status === "in_production");
    if (occupied) return { canStart: false, canFinish: false, reason: occupied.line_code + " está en producción en " + line.machine_code + "." };
    if (!line.current_assignment_id) return { canStart: false, canFinish: false, reason: "No existe una asignación vigente para este turno; Supervisión debe habilitarla." };
    return { canStart: true, canFinish: false, reason: null };
}

export function safeExecutionMessage(code: string | undefined, fallback: string): string {
    if (code === "LINE_MACHINE_IN_PRODUCTION") return "La máquina ya tiene una línea en producción. Actualiza los estados.";
    if (code === "LINE_ASSIGNMENT_INVALID") return "La asignación ya no corresponde al turno vigente. Actualiza y habilita la línea.";
    if (code === "LINE_EXECUTION_NOT_READY" || code === "LINE_NOT_IN_PRODUCTION")
        return "Esta línea requiere habilitación o revisión de Supervisión.";
    if (code === "LINE_EXECUTION_DISABLED") return "El control de ejecución no está habilitado en el servidor.";
    if (code === "LINE_EXECUTION_CONFLICT") return "El estado de la línea cambió. Actualiza antes de repetir.";
    if (code === "WORK_ORDER_CLOSE_PENDING_LINES") return "No se puede cerrar la OT: todavía hay líneas pendientes o asignaciones activas. Actualiza los estados.";
    if (code === "WORK_ORDER_CLOSE_INVALID_STATE") return "La OT no está en ejecución o ya cambió de estado. Actualiza los datos.";
    return fallback;
}

export type ExecutionMutation = Omit<ExecutionLine, "current_assignment_id"> & { work_order_id: string };

export function parseExecutionMutation(raw: unknown): ExecutionMutation | null {
    if (!isRec(raw) || !isStr(raw.work_order_id)) return null;
    const data = {
        work_order_id: raw.work_order_id,
        lines: [{
            baseline_line_id: raw.baseline_line_id, line_code: raw.line_code,
            machine_code: raw.machine_code, status: raw.status,
            current_assignment_id: null,
            started_at: raw.started_at, started_by: raw.started_by,
            finished_at: raw.finished_at, finished_by: raw.finished_by,
        }],
    };
    const parsed = parseWorkOrderExecution(data);
    if (!parsed || parsed.lines.length !== 1) return null;
    const line = parsed.lines[0];
    return {
        baseline_line_id: line.baseline_line_id, line_code: line.line_code,
        machine_code: line.machine_code, status: line.status,
        started_at: line.started_at, started_by: line.started_by,
        finished_at: line.finished_at, finished_by: line.finished_by,
        work_order_id: parsed.work_order_id,
    };
}

export function parseExecutionCapability(raw: unknown): boolean | null {
    if (!isRec(raw) || typeof raw.line_execution !== "boolean") return null;
    return raw.line_execution;
}

// E1-07: full immutable baseline must match the Supervisor projection. UI
// readiness is a hint only; POST /close rechecks every row transactionally.
export type CloseReadiness = { total: number; finished: number; canClose: boolean; pending: string[] };

export function closeReadiness(
    order: { id: string; status: string; baseline: { lines: { id: string; line_code: string; machine: { code: string } }[] } },
    execution: WorkOrderExecution | null,
): CloseReadiness {
    const baseline = order.baseline.lines;
    if (!execution || execution.work_order_id !== order.id || baseline.length === 0)
        return { total: baseline.length, finished: 0, canClose: false, pending: baseline.map(x => x.line_code) };
    const covered = new Set<string>();
    let finished = 0;
    const pending: string[] = [];
    for (const line of baseline) {
        const state = execution.lines.find(item =>
            item.baseline_line_id === line.id && item.line_code === line.line_code &&
            item.machine_code === line.machine.code);
        if (!state || covered.has(state.baseline_line_id) || state.status !== "finished") {
            pending.push(line.line_code);
        } else {
            finished += 1;
            covered.add(state.baseline_line_id);
        }
    }
    const complete = baseline.length === execution.lines.length && pending.length === 0;
    return { total: baseline.length, finished, pending, canClose: order.status === "in_progress" && complete };
}
