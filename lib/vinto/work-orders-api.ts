import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { addLinePayload, createWorkOrderLinesPayload, createWorkOrderPayload, parseWorkOrder, parseWorkOrderList, type LineDraft, type WorkOrder } from "@/lib/vinto/orders";

// OT base de Bobinas. Solo se envían los campos del contrato; el backend genera número, line_code, unidad y descripción.

export function listWorkOrders(signal?: AbortSignal): Promise<ApiResult<WorkOrder[]>> {
    return requestJson("/api/work-orders", { signal }, parseWorkOrderList);
}

export function createWorkOrder(machineCode: string, line: LineDraft, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson("/api/work-orders", { method: "POST", body: createWorkOrderPayload(machineCode, line), signal }, parseWorkOrder);
}

// MF-13-03B PR6: una OT con VARIAS líneas en UNA sola solicitud (POST /api/work-orders). Las líneas con `machineCode` solo se aceptan si el servidor tiene habilitada la
// compuerta multimáquina; este cliente nunca la enciende ni la consulta (ver docs/MF-13-03B-PR6-ui-ot-multimaquina.md).
export function createWorkOrderWithLines(machineCode: string, lines: LineDraft[], signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson("/api/work-orders", { method: "POST", body: createWorkOrderLinesPayload(machineCode, lines), signal }, parseWorkOrder);
}

export function addWorkOrderLine(workOrderId: string, line: LineDraft, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/lines`, { method: "POST", body: addLinePayload(line), signal }, parseWorkOrder);
}

export function publishWorkOrder(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/publish`, { method: "POST", signal }, parseWorkOrder);
}
