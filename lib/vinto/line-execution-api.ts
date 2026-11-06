import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseWorkOrder, type WorkOrder } from "@/lib/vinto/orders";
import { parseExecutionCapability, parseExecutionMutation, parseWorkOrderExecution, type ExecutionMutation, type WorkOrderExecution } from "@/lib/vinto/line-execution";

// The backend enforces role, sector, shift, assignment and single production
// per machine. The frontend never sends machine/status/actor or writes optimistically.
export function getWorkOrderExecution(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<WorkOrderExecution>> {
    return requestJson("/api/work-orders/" + encodeURIComponent(workOrderId) + "/execution",
        { signal }, parseWorkOrderExecution);
}

export function startWorkOrderLine(workOrderId: string, lineCode: string, assignmentId: string, signal?: AbortSignal): Promise<ApiResult<ExecutionMutation>> {
    return requestJson("/api/work-orders/" + encodeURIComponent(workOrderId) + "/lines/" + encodeURIComponent(lineCode) + "/start",
        { method: "POST", body: { assignment_id: assignmentId }, signal }, parseExecutionMutation);
}

export function finishWorkOrderLine(workOrderId: string, lineCode: string, signal?: AbortSignal): Promise<ApiResult<ExecutionMutation>> {
    return requestJson("/api/work-orders/" + encodeURIComponent(workOrderId) + "/lines/" + encodeURIComponent(lineCode) + "/finish",
        { method: "POST", signal }, parseExecutionMutation);
}

export function getLineExecutionCapability(signal?: AbortSignal): Promise<ApiResult<boolean>> {
    return requestJson("/api/work-orders/execution-capabilities", { signal }, parseExecutionCapability);
}

export function closeWorkOrder(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson("/api/work-orders/" + encodeURIComponent(workOrderId) + "/close",
        { method: "POST", signal }, parseWorkOrder);
}
