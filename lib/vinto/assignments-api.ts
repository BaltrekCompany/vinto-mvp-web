import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { activatePayload, parseActivation, parseActive, parseAssignment, parseAssignmentList, type Activation, type ActiveAssignment, type Assignment } from "@/lib/vinto/orders";

// Asignaciones de Bobinas. Activar envía solo la OT y la línea BASE: la máquina, el turno, la fecha y la línea operativa los resuelve el backend.

export function listAssignments(signal?: AbortSignal): Promise<ApiResult<Assignment[]>> {
    return requestJson("/api/assignments", { signal }, parseAssignmentList);
}

export function getActiveAssignment(machineCode: string, signal?: AbortSignal): Promise<ApiResult<ActiveAssignment>> {
    return requestJson(`/api/assignments/active?machine_code=${encodeURIComponent(machineCode)}`, { signal }, parseActive);
}

export function activateAssignment(workOrderId: string, baselineLineId: string, signal?: AbortSignal): Promise<ApiResult<Activation>> {
    return requestJson("/api/assignments/activate", { method: "POST", body: activatePayload(workOrderId, baselineLineId), signal }, parseActivation);
}

export function finishAssignment(assignmentId: string, signal?: AbortSignal): Promise<ApiResult<Assignment>> {
    return requestJson(`/api/assignments/${encodeURIComponent(assignmentId)}/finish`, { method: "POST", signal }, parseAssignment);
}
