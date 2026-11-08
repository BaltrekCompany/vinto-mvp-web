import { requestJson, type ApiResult } from "@/lib/vinto/central-http";

// E2-C1: on-screen notices derived from the exact assigned published revision.
// No local persistence, polling, production blocking or client-selected actor.
export type RevisionNotice = {
    assignment_id: string;
    version_number: number;
    work_order_number: string;
    line_code: string;
    machine_code: string;
    reason: string;
    revised_at: string;
    acknowledged_at: string | null;
    pv_reference: string;
    article_code: string;
    quantity: string; // decimal exact from PostgreSQL, never rounded
    due_date: string;
};
export type RevisionReceipt = {
    assignment_id: string;
    version_number: number;
    acknowledged_at: string;
};
const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);
const str = (v: unknown): v is string => typeof v === "string";
const uuid = (v: unknown): v is string =>
    str(v) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const version = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 2;
export function parseRevisionNotice(value: unknown): RevisionNotice | null {
    if (!isRecord(value) || !uuid(value.assignment_id) || !version(value.version_number)
        || !str(value.work_order_number) || !str(value.line_code) || !str(value.machine_code)
        || !str(value.reason) || !str(value.revised_at)
        || !(value.acknowledged_at === null || str(value.acknowledged_at))
        || !str(value.pv_reference) || !str(value.article_code)
        || !str(value.quantity) || !str(value.due_date)) return null;
    return value as RevisionNotice;
}
export function parseRevisionNotices(value: unknown): RevisionNotice[] | null {
    if (!Array.isArray(value)) return null;
    const items = value.map(parseRevisionNotice);
    return items.every(v => v !== null) ? items as RevisionNotice[] : null;
}
export function parseRevisionReceipt(value: unknown): RevisionReceipt | null {
    if (!isRecord(value) || !uuid(value.assignment_id)
        || !version(value.version_number) || !str(value.acknowledged_at)) return null;
    return value as RevisionReceipt;
}

export function listRevisionNotices(signal?: AbortSignal): Promise<ApiResult<RevisionNotice[]>> {
    return requestJson("/api/assignments/revision-notices", { signal }, parseRevisionNotices);
}

export function acknowledgeRevision(assignmentId: string, expectedVersion: number,
                                    signal?: AbortSignal): Promise<ApiResult<RevisionReceipt>> {
    return requestJson(`/api/assignments/${encodeURIComponent(assignmentId)}/acknowledge-revision`,
        { method: "POST", body: { expected_version: expectedVersion }, signal }, parseRevisionReceipt);
}
