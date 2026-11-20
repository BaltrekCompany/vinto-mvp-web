/**
 * OFF-04.1 (LABORATORY ONLY): schema, validation and context derivation for local Quality drafts.
 *
 * Pure module: no storage, no network, no DOM. It never creates permission to capture:
 * the Quality definition it reads is a read-only package whose capture-eligibility flag is false and a draft is
 * a SYNTHETIC rehearsal. Validation covers ONLY what the definition states explicitly (required,
 * value type, closed option lists, editable vs calculated). Ranges, units, formulas, cross-field
 * rules and any server-side authority are NOT inferred; they stay pending industrial approval.
 */
import type { QualityDefinition, QualityField, QualityPayload } from "./offline-quality-verify.ts";

export const DRAFT_SCHEMA = "vinto.offline.quality-draft.v1";
export const DRAFT_FORM_CODE_PREFIX = "VINTO-";
export const SYNTHETIC_NAME_PREFIX = "SINTÉTICO";
export const SYNTHETIC_NOTE_PREFIX = "Synthetic QA-only";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DECIMAL = /^-?\d{1,12}(?:[.,]\d{1,6})?$/;
const INTEGER = /^-?\d{1,12}$/;
const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TEXT_MAX = 200;
const TEXTAREA_MAX = 2000;
const MAX_VALUES = 128;
const encoder = new TextEncoder();

export type DraftValue = string | boolean;
export type DraftValues = Readonly<Record<string, DraftValue>>;
export type IssueCode = "required" | "type" | "option" | "unknown" | "calculated" | "too_long";
export type FieldIssue = Readonly<{ key: string; code: IssueCode }>;

/** OFF-04.6: the HISTORICAL context of the physical bobbin a by-bobbin Quality draft belongs to, prepared ONLINE and embedded in the draft (the receiver recomputes it from the database). */
export type BobbinContext = Readonly<{
    bobbin_id: string; bobbin_code: string; machine_code: string; is_mother: boolean; work_order: string; line_code: string; pv_reference: string;
    article_code: string; article_description: string; shift_code: string; operating_date: string; context_digest: string;
}>;
const BOBBIN_KEYS = ["bobbin_id", "bobbin_code", "machine_code", "is_mother", "work_order", "line_code", "pv_reference", "article_code", "article_description",
    "shift_code", "operating_date", "context_digest"];

export function parseBobbinContext(input: unknown): BobbinContext {
    if (!exact(input, BOBBIN_KEYS)) throw new DraftSchemaError("invalid");
    const b = input;
    const text = (k: string, max: number) => typeof b[k] === "string" && (b[k] as string).length >= 1 && (b[k] as string).length <= max;
    if (typeof b.bobbin_id !== "string" || !UUID.test(b.bobbin_id) || !text("bobbin_code", 48) || typeof b.machine_code !== "string" || !/^[A-Za-z0-9_.-]{1,48}$/.test(b.machine_code) ||
        typeof b.is_mother !== "boolean" || !text("work_order", 48) || !text("line_code", 48) || !text("pv_reference", 64) || !text("article_code", 64) || !text("article_description", 200) ||
        !text("shift_code", 16) || typeof b.operating_date !== "string" || !validDate(b.operating_date) || typeof b.context_digest !== "string" || !/^[0-9a-f]{64}$/.test(b.context_digest)) throw new DraftSchemaError("invalid");
    return b as unknown as BobbinContext;
}

/** Key that binds the draft's local-storage context: machine forms use the form code, by-bobbin forms add the bobbin, so two bobbins never share a context. */
export const draftContextKey = (formCode: string, bobbin: BobbinContext | null | undefined): string => bobbin ? formCode + "@b:" + bobbin.bobbin_id.toLowerCase() : formCode;

/** `context_version` of a capture by bobbin: SHA-256 of (domain, signed-scope snapshot, bobbin id, server digest); identical to backend `bobbin_context.context_version`. */
export async function bobbinContextVersion(snapshotId: string, bobbinId: string, digest: string): Promise<string> {
    const bytes = encoder.encode(["vinto-offline-bobbin-context-v1", snapshotId.toLowerCase(), bobbinId.toLowerCase(), digest].join("\0"));
    return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes as BufferSource)), b => b.toString(16).padStart(2, "0")).join("");
}

export type DraftPayload = Readonly<{
    schema: typeof DRAFT_SCHEMA;
    status: "draft";
    synthetic: true;
    draft_id: string;
    author_user_id: string;
    device_key: string;
    machine_code: string;
    form_code: string;
    form_version: number;
    form_checksum: string;
    definition_sha256: string;
    package_id: string;
    scope_snapshot_id: string;
    revision: number;
    created_local: string;
    updated_local: string;
    values: DraftValues;
    bobbin_context?: BobbinContext;      // OFF-04.6: present only for by-bobbin Quality forms
}>;

const PAYLOAD_KEYS_WITH_BOBBIN_SUFFIX = "bobbin_context";
const PAYLOAD_KEYS = ["schema", "status", "synthetic", "draft_id", "author_user_id", "device_key", "machine_code",
    "form_code", "form_version", "form_checksum", "definition_sha256", "package_id", "scope_snapshot_id", "revision",
    "created_local", "updated_local", "values"];

export class DraftSchemaError extends Error {
    readonly reason: "invalid" | "ineligible";
    constructor(reason: "invalid" | "ineligible") {
        super("OFFLINE_DRAFT_SCHEMA_" + reason.toUpperCase());
        this.name = "DraftSchemaError";
        this.reason = reason;
    }
}

/** Only the SYNTHETIC laboratory definitions may be edited; a real published definition never is. */
export function isLabEligible(definition: QualityDefinition): boolean {
    return definition.capture_eligible === false && definition.form_name.startsWith(SYNTHETIC_NAME_PREFIX) &&
        definition.note.startsWith(SYNTHETIC_NOTE_PREFIX);
}

export const isCalculated = (field: QualityField): boolean => field.source === "calculated";
export const editableFields = (definition: QualityDefinition): QualityField[] =>
    definition.fields.filter(f => !isCalculated(f)).sort((a, b) => a.display_order - b.display_order);

function validDate(text: string): boolean {
    const m = DATE.exec(text);
    if (!m) return false;
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    const t = new Date(Date.UTC(y, mo - 1, d));
    return y >= 1900 && y <= 2200 && t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}

function normalise(field: QualityField, raw: unknown): { ok: true; value: DraftValue } | { ok: false; code: IssueCode } {
    if (field.value_type === "boolean") return typeof raw === "boolean" ? { ok: true, value: raw } : { ok: false, code: "type" };
    if (typeof raw !== "string") return { ok: false, code: "type" };
    const text = field.value_type === "textarea" ? raw.replace(/\r\n/g, "\n") : raw.trim();
    if (field.options.length > 0) {
        return field.options.some(o => o.option_key === text) ? { ok: true, value: text } : { ok: false, code: "option" };
    }
    switch (field.value_type) {
        case "text":
            if (/[\u0000-\u001f\u007f]/.test(text)) return { ok: false, code: "type" };
            return text.length > TEXT_MAX ? { ok: false, code: "too_long" } : { ok: true, value: text };
        case "textarea":
            if (/[\u0000-\u0008\u000b-\u001f\u007f]/.test(text)) return { ok: false, code: "type" };
            return text.length > TEXTAREA_MAX ? { ok: false, code: "too_long" } : { ok: true, value: text };
        case "decimal": return DECIMAL.test(text) ? { ok: true, value: text.replace(",", ".") } : { ok: false, code: "type" };
        case "integer": return INTEGER.test(text) ? { ok: true, value: text } : { ok: false, code: "type" };
        case "date": return validDate(text) ? { ok: true, value: text } : { ok: false, code: "type" };
        case "time": return TIME.test(text) ? { ok: true, value: text } : { ok: false, code: "type" };
        default: return { ok: false, code: "type" };
    }
}

export type Evaluation = Readonly<{
    clean: DraftValues;               // normalised, valid values only
    typeIssues: FieldIssue[];         // block saving
    missingRequired: FieldIssue[];    // do NOT block a draft; they keep it "incomplete"
}>;

/** Validate required/type/options against the definition. Calculated and unknown keys are refused. */
export function evaluateDraft(definition: QualityDefinition, values: Readonly<Record<string, unknown>>): Evaluation {
    const typeIssues: FieldIssue[] = [], missing: FieldIssue[] = [], clean: Record<string, DraftValue> = {};
    const byKey = new Map(definition.fields.map(f => [f.key, f]));
    const keys = Object.keys(values);
    if (keys.length > MAX_VALUES) typeIssues.push({ key: "*", code: "too_long" });
    for (const key of keys) {
        const field = byKey.get(key);
        const raw = values[key];
        if (!field) { typeIssues.push({ key, code: "unknown" }); continue; }
        if (isCalculated(field)) {
            if (raw !== undefined && raw !== null && raw !== "") typeIssues.push({ key, code: "calculated" });
            continue;
        }
        if (raw === undefined || raw === null || (typeof raw === "string" && raw.trim() === "")) continue;
        const result = normalise(field, raw);
        if (result.ok) clean[key] = result.value; else typeIssues.push({ key, code: result.code });
    }
    for (const field of editableFields(definition)) {
        if (field.required && !(field.key in clean) && !typeIssues.some(i => i.key === field.key)) {
            missing.push({ key: field.key, code: "required" });
        }
    }
    return { clean, typeIssues, missingRequired: missing };
}

/** Deterministic UUID for the drafting context: machine + form + signed-scope snapshot. */
export async function contextIdFor(snapshotId: string, machineCode: string, formCode: string): Promise<string> {
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256",
        encoder.encode(["VINTO:OFF041:CONTEXT:v1", snapshotId.toLowerCase(), machineCode, formCode].join(":")) as BufferSource));
    const b = digest.slice(0, 16);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const hex = Array.from(b, x => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export type DraftSource = Readonly<{
    pkg: QualityPayload;                  // verified read-only package payload
    ownerId: string;
    deviceKey: string;
}>;

export function buildDraftPayload(
    source: DraftSource, draftId: string, values: DraftValues, revision: number, createdLocal: string, updatedLocal: string, bobbin?: BobbinContext
): DraftPayload {
    const p = source.pkg;
    return {
        schema: DRAFT_SCHEMA, status: "draft", synthetic: true, draft_id: draftId.toLowerCase(),
        author_user_id: source.ownerId.toLowerCase(), device_key: source.deviceKey.toLowerCase(),
        machine_code: p.machine_code, form_code: p.form_code, form_version: p.form_version,
        form_checksum: p.definition.source_definition_checksum, definition_sha256: p.content_sha256,
        package_id: p.package_id, scope_snapshot_id: p.scope_snapshot_id, revision,
        created_local: createdLocal, updated_local: updatedLocal, values, ...(bobbin ? { bobbin_context: bobbin } : {}),
    };
}

function exact(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value) &&
        Object.keys(value).sort().join("|") === [...keys].sort().join("|");
}
const iso = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(v) && Number.isFinite(Date.parse(v));

/** Strict parse of a DECRYPTED payload. Anything unexpected is refused, never coerced. */
export function parseDraftPayload(input: unknown): DraftPayload {
    const hasBobbin = typeof input === "object" && input !== null && !Array.isArray(input) && PAYLOAD_KEYS_WITH_BOBBIN_SUFFIX in (input as object);
    if (!exact(input, hasBobbin ? [...PAYLOAD_KEYS, PAYLOAD_KEYS_WITH_BOBBIN_SUFFIX] : PAYLOAD_KEYS)) throw new DraftSchemaError("invalid");
    const p = input;
    if (hasBobbin) parseBobbinContext(p.bobbin_context);
    if (p.schema !== DRAFT_SCHEMA || p.status !== "draft" || p.synthetic !== true ||
        !["draft_id", "author_user_id", "device_key", "scope_snapshot_id", "package_id"].every(k => typeof p[k] === "string" && UUID.test(p[k] as string)) ||
        typeof p.machine_code !== "string" || !/^[A-Za-z0-9_.-]{1,48}$/.test(p.machine_code) ||
        typeof p.form_code !== "string" || !/^VINTO-[A-Z0-9-]{2,40}$/.test(p.form_code) ||
        !Number.isSafeInteger(p.form_version) || (p.form_version as number) < 1 ||
        !Number.isSafeInteger(p.revision) || (p.revision as number) < 1 ||
        typeof p.form_checksum !== "string" || !/^[0-9a-f]{64}$/.test(p.form_checksum) ||
        typeof p.definition_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(p.definition_sha256) ||
        !iso(p.created_local) || !iso(p.updated_local) ||
        typeof p.values !== "object" || p.values === null || Array.isArray(p.values)) throw new DraftSchemaError("invalid");
    const values = p.values as Record<string, unknown>;
    const keys = Object.keys(values);
    if (keys.length > MAX_VALUES || !keys.every(k => typeof values[k] === "string" || typeof values[k] === "boolean")) {
        throw new DraftSchemaError("invalid");
    }
    return p as unknown as DraftPayload;
}

/** A draft is editable only against the SAME definition it was created from. */
export function draftMatchesDefinition(draft: DraftPayload, pkg: QualityPayload): boolean {
    return draft.machine_code === pkg.machine_code && draft.form_code === pkg.form_code &&
        draft.form_version === pkg.form_version && draft.definition_sha256 === pkg.content_sha256 &&
        draft.form_checksum === pkg.definition.source_definition_checksum;
}

/** Rules the editor deliberately does NOT enforce (recorded for the homologation checklist). */
export const UNCOVERED_RULES = [
    "ranges, units and precision limits per field",
    "calculated formulas (shown read-only; computed only by the backend)",
    "cross-field and option-dependency rules",
    "work-order, assignment and shift context",
    "any central authority over actor, grant and version",
] as const;
