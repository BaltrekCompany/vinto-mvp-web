import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { confirmPayload, parseConfirmation, parsePreview, previewPayload, statusMatchesOutcome, type ActivateAllResponse } from "@/lib/vinto/activate-all";
import { parseCapabilitiesResponse, type WorkOrderCapabilities } from "@/lib/vinto/work-order-capabilities";
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

// MF-13-03B PR6.1: capacidades de OT que el servidor confirma a la sesión (solo lectura). Una respuesta que no sea exactamente el contrato es un fallo («unavailable»): la capacidad queda apagada.
export function getWorkOrderCapabilities(signal?: AbortSignal): Promise<ApiResult<WorkOrderCapabilities>> {
    return requestJson("/api/work-orders/capabilities", { signal }, parseCapabilitiesResponse);
}

// MF-13-03B PR7: activación masiva de TODAS las líneas de una OT (PR4). Siempre UNA solicitud POST, nunca una por línea. Vista previa: cuerpo exacto {"dry_run": true} (solo lectura).
export function previewActivateAll(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<ActivateAllResponse>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/activate-all`, { method: "POST", body: previewPayload(), signal }, parsePreview);
}

// Confirmación: cuerpo exacto {"dry_run": false, "plan_hash": <hash del servidor, sin modificar>}. Un hash con forma inválida no sale del navegador. La respuesta debe ser coherente con el estado HTTP
// (201 = applied, 200 = already_in_effect) y repetir el mismo hash; si no, es un fallo («unavailable») y la interfaz NO reintenta: el servidor pudo haber aplicado la transacción.
export async function confirmActivateAll(workOrderId: string, planHash: string, signal?: AbortSignal): Promise<ApiResult<ActivateAllResponse>> {
    const body = confirmPayload(planHash);
    if (!body) return { ok: false, kind: "invalid", status: 0 };
    const result = await requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/activate-all`, { method: "POST", body, signal }, parseConfirmation(planHash));
    if (result.ok && !statusMatchesOutcome(result.status, result.data.outcome)) return { ok: false, kind: "unavailable", status: result.status };
    return result;
}
