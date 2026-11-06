// E1-06: Operating screen requires an explicit logical execution to write F3/F6.
// Pure, server-authoritative projection. 'active' shift assignment != production.
import type { OperationSelection } from "./active-lines.ts";

export type MachineAssignmentExecutionStatus =
    "planned" | "enabled" | "in_production" | "finished" | "requires_review";
export type MachineExecution = {
    line_execution: boolean;
    assignments: { assignment_id: string; status: MachineAssignmentExecutionStatus }[];
};

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => value !== null && typeof value === "object" && !Array.isArray(value);
const isStr = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const STATES: readonly string[] = ["planned", "enabled", "in_production", "finished", "requires_review"];

export function parseMachineExecution(value: unknown): MachineExecution | null {
    if (!isRec(value) || typeof value.line_execution !== "boolean" || !Array.isArray(value.assignments)) return null;
    const assignments: MachineExecution["assignments"] = [];
    const seen = new Set<string>();
    if (!value.line_execution && value.assignments.length > 0) return null;
    for (const raw of value.assignments) {
        if (!isRec(raw) || !isStr(raw.assignment_id) || !isStr(raw.status) || !STATES.includes(raw.status) || seen.has(raw.assignment_id))
            return null;
        seen.add(raw.assignment_id);
        assignments.push({ assignment_id: raw.assignment_id, status: raw.status as MachineAssignmentExecutionStatus });
    }
    return { line_execution: value.line_execution, assignments };
}

// The projection is per machine and per session. No optimistic read and no
// fallback when the new API is down. The backend independently rechecks every
// capture, so a read racing a supervisor finish cannot allow a late write.
export function isStartedAssignment(snapshot: MachineExecution, assignmentId: string): boolean {
    if (!snapshot.line_execution) return true; // historical flow when server flag OFF
    return snapshot.assignments.some(x => x.assignment_id === assignmentId && x.status === "in_production");
}

export function executionStatus(snapshot: MachineExecution, assignmentId: string): MachineAssignmentExecutionStatus | null {
    if (!snapshot.line_execution) return null;
    return snapshot.assignments.find(x => x.assignment_id === assignmentId)?.status ?? null;
}

export function operationDisplay(snapshot: MachineExecution): "legacy" | "managed" {
    return snapshot.line_execution ? "managed" : "legacy";
}

export function selectedContextAllowed(snapshot: MachineExecution, selection: OperationSelection, assignmentId: string | null): boolean {
    if (!snapshot.line_execution) return true;
    if (!assignmentId) return false;
    if (selection.kind === "single") {
        return selection.active.stale === false && selection.active.assignment?.id === assignmentId
            && isStartedAssignment(snapshot, assignmentId);
    }
    return selection.lines.items.some(item => item.assignment.id === assignmentId && item.stale === false)
        && isStartedAssignment(snapshot, assignmentId);
}

export const MACHINE_EXECUTION_LABELS: Record<MachineAssignmentExecutionStatus, string> = {
    planned: "Programada", enabled: "Habilitada · pendiente de inicio",
    in_production: "En producción", finished: "Finalizada",
    requires_review: "Requiere revisión de Supervisión",
};

export function operationBlockedMessage(snapshot: MachineExecution, assignmentId: string | null): string {
    if (!snapshot.line_execution) return "";
    if (assignmentId === null) return "Selecciona la línea que Supervisión haya iniciado para esta máquina.";
    const status = executionStatus(snapshot, assignmentId);
    if (status === "in_production") return "";
    if (status === "enabled" || status === "planned") return "Esta línea aún no ha sido iniciada por Supervisión.";
    if (status === "finished") return "Esta línea ya terminó. Solicita a Supervisión que inicie la siguiente.";
    return "No se pudo verificar que la línea esté en producción. Solicita revisión de Supervisión.";
}
