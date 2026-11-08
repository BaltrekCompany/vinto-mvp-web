import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { lineBody, type LineDraft } from "@/lib/vinto/orders";
import {
    parseHandoffCapability, parseOpenHandoffs, parseReservedHandoff,
    parsePublishedHandoff, parseReassignedHandoff,
    type OpenHandoff, type ReservedHandoff, type PublishedHandoff, type ReassignedHandoff,
} from "@/lib/vinto/handoff";

// Las APIs solo reciben identificadores verificados por el servidor y los cuatro
// campos de programación. No se mandan roles, actores, estado ni máquinas.
export const getHandoffCapability = (signal?: AbortSignal): Promise<ApiResult<boolean>> =>
    requestJson("/api/work-orders/handoff-capabilities", { signal }, parseHandoffCapability);

export const listOpenHandoffs = (signal?: AbortSignal): Promise<ApiResult<OpenHandoff[]>> =>
    requestJson("/api/work-orders/handoffs", { signal }, parseOpenHandoffs);

export const reserveHandoff = (
    workOrderId: string, lineCode: string, assignmentId: string,
    expectedVersion: number, reason: string,
): Promise<ApiResult<ReservedHandoff>> =>
    requestJson(`/api/work-orders/${encodeURIComponent(workOrderId)}/lines/${encodeURIComponent(lineCode)}/reserve-handoff`,
        { method: "POST", body: {
            assignment_id: assignmentId, expected_version: expectedVersion, reason: reason.trim(),
        } }, parseReservedHandoff);

export const cancelHandoff = (handoffId: string, reason: string): Promise<ApiResult<ReservedHandoff>> =>
    requestJson(`/api/work-orders/handoffs/${encodeURIComponent(handoffId)}/cancel`,
        { method: "POST", body: { reason: reason.trim() } }, parseReservedHandoff);

export const publishHandoff = (
    handoffId: string, expected: LineDraft, replacement: LineDraft, reason: string,
): Promise<ApiResult<PublishedHandoff>> =>
    requestJson(`/api/work-orders/handoffs/${encodeURIComponent(handoffId)}/publish`,
        { method: "POST", body: {
            expected: lineBody(expected), replacement: lineBody(replacement), reason: reason.trim(),
        } }, parsePublishedHandoff);

export const reassignHandoff = (handoffId: string): Promise<ApiResult<ReassignedHandoff>> =>
    requestJson(`/api/work-orders/handoffs/${encodeURIComponent(handoffId)}/reassign`,
        { method: "POST" }, parseReassignedHandoff);
