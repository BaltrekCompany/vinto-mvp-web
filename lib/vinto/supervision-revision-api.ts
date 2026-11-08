import { requestJson, type ApiResult } from "@/lib/vinto/central-http";

// E2-C2: the server derives principal, sector scope, and latest published version.
// Browser never supplies the acknowledgement actor or overrides before/after.
export type SupervisionRevisionFields = {
    pv_reference: string;
    article_code: string;
    quantity: string;
    due_date: string;
};
export type SupervisionRevisionNotice = {
    work_order_id: string;
    work_order_number: string;
    status: "published" | "in_progress";
    version_number: number;
    line_code: string;
    reason: string;
    revised_at: string;
    changed_by: string | null;
    machine_code: string;
    before: SupervisionRevisionFields;
    after: SupervisionRevisionFields;
    acknowledged_at: string | null;
};
export type SupervisionRevisionAck = {
    work_order_id: string;
    version_number: number;
    acknowledged_at: string;
};
const record = (v: unknown): v is Record<string, unknown> =>
    typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string";
const id = (v: unknown): v is string =>
    text(v) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const version = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 2;
const fields = (v: unknown): v is SupervisionRevisionFields =>
    record(v) && text(v.pv_reference) && text(v.article_code)
    && text(v.quantity) && text(v.due_date);

export function parseSupervisionNotice(v: unknown): SupervisionRevisionNotice | null {
    if (!record(v) || !id(v.work_order_id) || !text(v.work_order_number)
        || (v.status !== "published" && v.status !== "in_progress")
        || !version(v.version_number) || !text(v.line_code) || !text(v.reason)
        || !text(v.revised_at) || !(v.changed_by === null || text(v.changed_by))
        || !text(v.machine_code) || !fields(v.before) || !fields(v.after)
        || !(v.acknowledged_at === null || text(v.acknowledged_at))) return null;
    return v as SupervisionRevisionNotice;
}
export function parseSupervisionNotices(v: unknown): SupervisionRevisionNotice[] | null {
    if (!Array.isArray(v)) return null;
    const list = v.map(parseSupervisionNotice);
    return list.every(item => item !== null) ? list as SupervisionRevisionNotice[] : null;
}
export function parseSupervisionAck(v: unknown): SupervisionRevisionAck | null {
    if (!record(v) || !id(v.work_order_id) || !version(v.version_number)
        || !text(v.acknowledged_at)) return null;
    return v as SupervisionRevisionAck;
}

export function listSupervisionNotices(signal?: AbortSignal): Promise<ApiResult<SupervisionRevisionNotice[]>> {
    return requestJson("/api/work-orders/supervision-revision-notices", { signal }, parseSupervisionNotices);
}

export function acknowledgeSupervisionRevision(workOrderId: string, expectedVersion: number,
                                               signal?: AbortSignal): Promise<ApiResult<SupervisionRevisionAck>> {
    return requestJson(
        `/api/work-orders/${encodeURIComponent(workOrderId)}/acknowledge-supervision-revision`,
        { method: "POST", body: { expected_version: expectedVersion }, signal }, parseSupervisionAck);
}
