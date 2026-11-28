import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import {
    parseRewindingExportChildList,
    parseRewindingExportDraft,
    parseRewindingExportDraftSummaryList,
    parseRewindingExportMotherList,
    parseRewindingExportPreview,
    parseRewindingExportProductList,
    parseRewindingExportPvList,
    parseRewindingWorkOrderClassification,
    parseRewindingWorkOrderOptionList,
    type RewindingExportChild,
    type RewindingExportDraft,
    type RewindingExportDraftSummary,
    type RewindingExportMother,
    type RewindingExportPackagePayload,
    type RewindingExportPreview,
    type RewindingExportProduct,
    type RewindingExportPv,
    type RewindingWorkOrderClassification,
    type RewindingWorkOrderClassificationRecord,
    type RewindingWorkOrderOption,
} from "@/lib/vinto/rewinding-export";

const ROOT = "/api/reports/rewinding-export";

export function listRewindingExportPvs(signal?: AbortSignal): Promise<ApiResult<RewindingExportPv[]>> {
    return requestJson(ROOT + "/pvs", { signal }, parseRewindingExportPvList);
}
export function listRewindingExportProducts(pvReference: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportProduct[]>> {
    const query = new URLSearchParams({ pv_reference: pvReference });
    return requestJson(ROOT + "/products?" + query.toString(), { signal }, parseRewindingExportProductList);
}
export function listRewindingExportMothers(pvReference: string, articleId: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportMother[]>> {
    const query = new URLSearchParams({ pv_reference: pvReference, article_id: articleId });
    return requestJson(ROOT + "/mothers?" + query.toString(), { signal }, parseRewindingExportMotherList);
}
export function listRewindingExportChildren(motherCaptureId: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportChild[]>> {
    return requestJson(ROOT + "/mothers/" + encodeURIComponent(motherCaptureId) + "/children", { signal }, parseRewindingExportChildList);
}
export function listRewindingExportDrafts(signal?: AbortSignal): Promise<ApiResult<RewindingExportDraftSummary[]>> {
    return requestJson(ROOT + "/drafts", { signal }, parseRewindingExportDraftSummaryList);
}
export function getRewindingExportDraft(reportId: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId), { signal }, parseRewindingExportDraft);
}
export function createRewindingExportDraft(payload: {
    pv_reference: string;
    article_id: string;
    truck_number: string;
    order_number: string;
    observations: string;
}, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts", { method: "POST", body: payload, signal }, parseRewindingExportDraft);
}
export function updateRewindingExportDraft(reportId: string, payload: {
    truck_number: string;
    order_number: string;
    observations: string;
}, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId), { method: "PATCH", body: payload, signal }, parseRewindingExportDraft);
}
export function addRewindingExportPackage(reportId: string, payload: RewindingExportPackagePayload, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId) + "/packages", { method: "POST", body: payload, signal }, parseRewindingExportDraft);
}
export function updateRewindingExportPackage(reportId: string, packageId: string, payload: RewindingExportPackagePayload, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId) + "/packages/" + encodeURIComponent(packageId), { method: "PATCH", body: payload, signal }, parseRewindingExportDraft);
}
export function removeRewindingExportPackage(reportId: string, packageId: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportDraft>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId) + "/packages/" + encodeURIComponent(packageId) + "/remove", { method: "POST", body: {}, signal }, parseRewindingExportDraft);
}
export function previewRewindingExportDraft(reportId: string, signal?: AbortSignal): Promise<ApiResult<RewindingExportPreview>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId) + "/preview", { method: "POST", body: {}, signal }, parseRewindingExportPreview);
}
export function discardRewindingExportDraft(reportId: string, signal?: AbortSignal): Promise<ApiResult<boolean>> {
    return requestJson(ROOT + "/drafts/" + encodeURIComponent(reportId) + "/discard", { method: "POST", body: {}, signal }, payload => {
        if (typeof payload !== "object" || payload === null || !("discarded" in payload) || (payload as { discarded: unknown }).discarded !== true) return null;
        return true;
    });
}
export function listRewindingWorkOrdersForClassification(signal?: AbortSignal): Promise<ApiResult<RewindingWorkOrderOption[]>> {
    return requestJson(ROOT + "/work-orders", { signal }, parseRewindingWorkOrderOptionList);
}
export function getRewindingWorkOrderClassification(workOrderId: string, signal?: AbortSignal): Promise<ApiResult<RewindingWorkOrderClassificationRecord>> {
    return requestJson(ROOT + "/work-orders/" + encodeURIComponent(workOrderId) + "/classification", { signal }, parseRewindingWorkOrderClassification);
}
export function classifyRewindingWorkOrder(workOrderId: string, payload: {
    classification: RewindingWorkOrderClassification;
    reason: string;
}, signal?: AbortSignal): Promise<ApiResult<RewindingWorkOrderClassificationRecord>> {
    return requestJson(ROOT + "/work-orders/" + encodeURIComponent(workOrderId) + "/classification", { method: "POST", body: payload, signal }, parseRewindingWorkOrderClassification);
}
