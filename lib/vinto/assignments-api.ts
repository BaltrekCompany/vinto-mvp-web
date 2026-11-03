import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseActiveLines, selectionFromLines, type ActiveLines, type OperationSelection } from "@/lib/vinto/active-lines";
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

// MF-13-03B PR8: todas las líneas activas de la máquina (sin elegir ninguna). Solo se llama cuando `/active` responde MULTIPLE_ACTIVE_ASSIGNMENTS.
export function getActiveLines(machineCode: string, signal?: AbortSignal): Promise<ApiResult<ActiveLines>> {
    return requestJson(`/api/assignments/active-lines?machine_code=${encodeURIComponent(machineCode)}`, { signal }, parseActiveLines);
}

// Lectura de Ejecución: el contrato histórico (`/active`, una sola solicitud) y, SOLO si el servidor informa varias líneas activas, `/active-lines`.
// Una falla distinta de MULTIPLE_ACTIVE_ASSIGNMENTS se devuelve tal cual (nunca se "adivina" una línea).
export async function getOperationSelection(machineCode: string, signal?: AbortSignal): Promise<ApiResult<OperationSelection>> {
    const single = await getActiveAssignment(machineCode, signal);
    if (single.ok) return { ok: true, status: single.status, data: { kind: "single", active: single.data } };
    if (single.kind !== "conflict" || single.code !== "MULTIPLE_ACTIVE_ASSIGNMENTS") return single;
    const lines = await getActiveLines(machineCode, signal);
    return lines.ok ? { ok: true, status: lines.status, data: selectionFromLines(lines.data) } : lines;
}
