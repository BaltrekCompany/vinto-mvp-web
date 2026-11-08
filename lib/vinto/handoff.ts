// E2-D2-B3: contratos de lectura del backend. Puro, sin red ni estado local.
// Un JSON incompleto o inesperado no habilita acciones; la API sigue siendo autoridad.
export type HandoffState = "pending" | "published" | "reassigned";
export type OpenHandoff = {
    handoff_id: string;
    work_order_id: string;
    work_order_number: string;
    line_code: string;
    machine_code: string;
    status: HandoffState;
    expected_version: number;
    published_version: number | null;
    prior_assignment_id: string;
    replacement_assignment_id: string | null;
    reason: string;
    created_at: string;
};
export type ReservedHandoff = {
    handoff_id: string; work_order_id: string; line_code: string;
    status: "pending" | "cancelled";
};
export type PublishedHandoff = {
    handoff_id: string; work_order_id: string; line_code: string;
    status: "published"; version_number: number;
};
export type ReassignedHandoff = {
    handoff_id: string; work_order_id: string; status: "reassigned";
    version_number: number; previous_assignment_id: string;
    replacement_assignment_id: string;
};
type Rec = Record<string, unknown>;
const rec = (value: unknown): value is Rec =>
    typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const uuid = (value: unknown): value is string =>
    str(value) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const nullableUuid = (value: unknown): value is string | null => value === null || uuid(value);
const number = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 2;
const nullableNumber = (value: unknown): value is number | null => value === null || number(value);
const states: readonly string[] = ["pending", "published", "reassigned"];

export function parseHandoffCapability(value: unknown): boolean | null {
    return rec(value) && typeof value.enabled === "boolean" ? value.enabled : null;
}
export function parseOpenHandoffs(value: unknown): OpenHandoff[] | null {
    if (!Array.isArray(value) || value.length > 100) return null;
    const seen = new Set<string>();
    for (const item of value) {
        if (!rec(item) || !uuid(item.handoff_id) || seen.has(item.handoff_id)
            || !uuid(item.work_order_id) || !str(item.work_order_number)
            || !str(item.line_code) || !str(item.machine_code)
            || !str(item.status) || !states.includes(item.status)
            || !number(item.expected_version) || !nullableNumber(item.published_version)
            || !uuid(item.prior_assignment_id) || !nullableUuid(item.replacement_assignment_id)
            || !str(item.reason) || !str(item.created_at)) return null;
        if ((item.status === "pending" && (item.published_version !== null || item.replacement_assignment_id !== null))
            || (item.status === "published" && (item.published_version === null || item.replacement_assignment_id !== null))
            || (item.status === "reassigned" && (item.published_version === null || item.replacement_assignment_id === null)))
            return null;
        seen.add(item.handoff_id);
    }
    return value as OpenHandoff[];
}
export function parseReservedHandoff(value: unknown): ReservedHandoff | null {
    return rec(value) && uuid(value.handoff_id) && uuid(value.work_order_id)
        && str(value.line_code) && (value.status === "pending" || value.status === "cancelled")
        ? value as ReservedHandoff : null;
}
export function parsePublishedHandoff(value: unknown): PublishedHandoff | null {
    return rec(value) && uuid(value.handoff_id) && uuid(value.work_order_id)
        && str(value.line_code) && value.status === "published" && number(value.version_number)
        ? value as PublishedHandoff : null;
}
export function parseReassignedHandoff(value: unknown): ReassignedHandoff | null {
    return rec(value) && uuid(value.handoff_id) && uuid(value.work_order_id)
        && value.status === "reassigned" && number(value.version_number)
        && uuid(value.previous_assignment_id) && uuid(value.replacement_assignment_id)
        && value.previous_assignment_id !== value.replacement_assignment_id
        ? value as ReassignedHandoff : null;
}
