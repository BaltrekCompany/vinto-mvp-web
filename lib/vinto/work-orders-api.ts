import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { confirmPayload, parseConfirmation, parsePreview, previewPayload, statusMatchesOutcome, type ActivateAllResponse } from "@/lib/vinto/activate-all";
import { parseCapabilitiesResponse, type WorkOrderCapabilities } from "@/lib/vinto/work-order-capabilities";
import { addLinePayload, createWorkOrderLinesPayload, createWorkOrderPayload, parseWorkOrder, parseWorkOrderList, type LineDraft, type WorkOrder } from "@/lib/vinto/orders";

// OT base de Bobinas. Solo se envían los campos del contrato; el backend genera número, line_code, unidad y descripción.

export function listWorkOrders(signal?: AbortSignal): Promise<ApiResult<WorkOrder[]>> {
    return requestJson("/api/work-orders", { signal }, parseWorkOrderList);
}

// E1-09 archival: manager-only endpoint. The regular list hides archived OT.
// No direct mutation of status, assignments, captures or audit records.
export function listArchivedWorkOrders(signal?: AbortSignal): Promise<ApiResult<WorkOrder[]>> {
    return requestJson("/api/work-orders?archived=true", { signal }, parseWorkOrderList);
}

export function archiveWorkOrder(workOrderId: string, reason: string, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/archive`,
        { method: "POST", body: { reason: reason.trim() }, signal }, parseWorkOrder);
}

export function restoreWorkOrder(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/restore`,
        { method: "POST", signal }, parseWorkOrder);
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

// E2-A: edición de los cuatro datos programados de una línea guardada, SOLO en borrador.
 // expected hace la escritura condicional: un cambio concurrente devuelve 409, nunca sobrescribe en silencio.
export function editDraftWorkOrderLine(workOrderId: string, lineCode: string, expected: LineDraft,
                                       replacement: LineDraft, reason: string, signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/lines/${encodeURIComponent(lineCode)}/edit-draft`,
        { method: "POST", body: { expected: lineBodyNoMachine(expected), replacement: lineBodyNoMachine(replacement), reason: reason.trim() }, signal }, parseWorkOrder);
}

function lineBodyNoMachine(line: LineDraft) {
    return { pv_reference: line.pvReference.trim(), article_code: line.articleCode, quantity: line.quantity, due_date: line.dueDate };
}

// E2-B: versioned revision of a published OT BEFORE its first assignment.
// The server retains every previous snapshot. Machine and baseline identifiers
// never appear in this payload. Any historic assignment returns 409.
export function reprogramPublishedLine(workOrderId: string, lineCode: string, expectedVersion: number,
                                       expected: LineDraft, replacement: LineDraft, reason: string,
                                       signal?: AbortSignal): Promise<ApiResult<WorkOrder>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/lines/${encodeURIComponent(lineCode)}/reprogram`,
        { method: "POST", body: { expected_version: expectedVersion, expected: lineBodyNoMachine(expected),
            replacement: lineBodyNoMachine(replacement), reason: reason.trim() }, signal }, parseWorkOrder);
}

export type RevisionFields = { pv_reference: string; article_code: string; quantity: number; due_date: string };
export type WorkOrderRevision = {
    version_number: number; previous_version: number; line_code: string;
    reason: string; changed_at: string; changed_by_id: string; changed_by_name: string;
    before: RevisionFields; after: RevisionFields;
};
function isRevisionFields(value: unknown): value is RevisionFields {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const v = value as Record<string, unknown>;
    return typeof v.pv_reference === "string" && typeof v.article_code === "string"
        && typeof v.quantity === "number" && Number.isFinite(v.quantity) && v.quantity > 0
        && typeof v.due_date === "string";
}
function parseRevisions(value: unknown): WorkOrderRevision[] | null {
    if (!Array.isArray(value)) return null;
    if (!value.every(item => {
        if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
        const r = item as Record<string, unknown>;
        return Number.isInteger(r.version_number) && Number.isInteger(r.previous_version)
            && typeof r.line_code === "string" && typeof r.reason === "string"
            && typeof r.changed_at === "string" && typeof r.changed_by_id === "string"
            && typeof r.changed_by_name === "string"
            && isRevisionFields(r.before) && isRevisionFields(r.after);
    })) return null;
    return value as WorkOrderRevision[];
}
export function listWorkOrderRevisions(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<WorkOrderRevision[]>> {
    return requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/revisions`, { signal }, parseRevisions);
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
