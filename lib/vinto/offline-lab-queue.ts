/**
 * OFF-04.2 (LABORATORY ONLY): explicit transition of an encrypted synthetic Quality draft to a SIMULATED local
 * pending (`queued_local_simulation`). It does NOT send, sync, approve or authorise anything.
 *
 * The result lives in an isolated database (see offline-lab-queue-store.ts), never in the application's
 * send queue, and carries a frozen, re-sealed copy of the draft. Pending records are immutable: the only
 * write primitive is "add", the source draft becomes read-only (see saveQualityDraft) and a repeated
 * transition (double click, retry, second tab) is idempotent: it returns the existing pending unchanged.
 */
import { openLocalDraft, sealLocalDraft, VaultError, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { VerifiedQualityDefinition } from "./offline-quality-verify.ts";
import type { VerifiedLocalScope } from "./offline-scope-store.ts";
import {
    contextIdFor, draftMatchesDefinition, evaluateDraft, isLabEligible, parseDraftPayload, DraftSchemaError, type DraftPayload,
} from "./offline-draft-schema.ts";
import { assertGranted, DraftError, loadQualityDraft } from "./offline-draft-store.ts";
import {
    addLabPending, getLabPendingByDraft, listLabPending, LabQueueStoreError, LAB_STATUS, type LabPending,
} from "./offline-lab-queue-store.ts";

export const PENDING_SCHEMA = "vinto.offline.quality-pending-sim.v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const encoder = new TextEncoder();

export type QueueErrorReason =
    | "invalid" | "ineligible" | "no_grant" | "conflict" | "incomplete" | "stale_definition"
    | "locked" | "corrupt" | "not_found" | "quota" | "storage";
export class LabQueueError extends Error {
    readonly reason: QueueErrorReason;
    readonly missing: readonly string[];
    constructor(reason: QueueErrorReason, missing: readonly string[] = []) {
        super("OFFLINE_LAB_QUEUE_" + reason.toUpperCase());
        this.name = "LabQueueError";
        this.reason = reason;
        this.missing = missing;
    }
}

export type PendingPayload = Readonly<{
    schema: typeof PENDING_SCHEMA;
    status: typeof LAB_STATUS;
    synthetic: true;
    sync_state: "NOT_SYNCED";
    capture_id: string;
    source_draft_id: string;
    source_revision: number;
    queued_local: string;
    draft: DraftPayload;
}>;
const PENDING_KEYS = ["schema", "status", "synthetic", "sync_state", "capture_id", "source_draft_id", "source_revision", "queued_local", "draft"];

export type QueueResult = Readonly<{ captureId: string; created: boolean; sourceRevision: number; queuedAt: string }>;
export type PendingSummary = Readonly<
    | { captureId: string; corrupt: false; formCode: string; formVersion: number; machineCode: string; sourceRevision: number; queuedAt: string }
    | { captureId: string; corrupt: true; reason: "corrupt" | "locked" }
>;

/** Stable capture id: one per (owner, browser, draft). Retries and second tabs derive the same value. */
export async function captureIdFor(ownerId: string, deviceKey: string, draftId: string): Promise<string> {
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256",
        encoder.encode(["VINTO:OFF042:CAPTURE:v1", ownerId.toLowerCase(), deviceKey.toLowerCase(), draftId.toLowerCase()].join(":")) as BufferSource));
    const b = digest.slice(0, 16);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const hex = Array.from(b, x => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const bindingOf = (identity: OfflineVaultIdentity, r: Pick<LabPending, "capture_id" | "contextId" | "formCode" | "formVersion">) =>
    ({ ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: r.capture_id,
       contextId: r.contextId, formCode: r.formCode, formVersion: r.formVersion });

function mapDraftError(error: unknown): LabQueueError {
    if (error instanceof LabQueueError) return error;
    if (error instanceof DraftError) {
        if (error.reason === "locked") return new LabQueueError("locked");
        if (error.reason === "not_found") return new LabQueueError("not_found");
        if (error.reason === "corrupt") return new LabQueueError("corrupt");
        if (error.reason === "stale_definition") return new LabQueueError("stale_definition");
        if (error.reason === "no_grant") return new LabQueueError("no_grant");
        if (error.reason === "ineligible") return new LabQueueError("ineligible");
        if (error.reason === "invalid") return new LabQueueError("invalid");
    }
    return new LabQueueError("storage");
}

function mapStoreError(error: unknown): LabQueueError {
    if (error instanceof LabQueueStoreError) {
        if (error.reason === "quota") return new LabQueueError("quota");
        if (error.reason === "invalid") return new LabQueueError("invalid");
    }
    return new LabQueueError("storage");
}

/**
 * draft → queued_local_simulation. `expectedRevision` is the draft revision the user is looking at; a
 * different stored revision is a conflict. Only a COMPLETE, valid draft of an eligible synthetic definition
 * can transition. Resolves after the single IndexedDB transaction committed.
 */
export async function queueLabDraft(
    key: CryptoKey, identity: OfflineVaultIdentity,
    context: Readonly<{ scope: VerifiedLocalScope; pkg: VerifiedQualityDefinition }>,
    input: Readonly<{ id: string; expectedRevision: number }>,
    now: () => Date = () => new Date()
): Promise<QueueResult> {
    if (!UUID.test(identity.ownerId) || !UUID.test(identity.deviceKey) || !UUID.test(input.id) ||
        !Number.isSafeInteger(input.expectedRevision) || input.expectedRevision < 1) throw new LabQueueError("invalid");
    const owner = identity.ownerId.toLowerCase(), device = identity.deviceKey.toLowerCase(), draftId = input.id.toLowerCase();
    const pkg = context.pkg.envelope.payload;
    if (!isLabEligible(pkg.definition)) throw new LabQueueError("ineligible");
    if (pkg.subject_user_id.toLowerCase() !== owner || pkg.device_key.toLowerCase() !== device) throw new LabQueueError("invalid");
    try { assertGranted(context.scope, context.pkg); } catch (error) { throw mapDraftError(error); }

    // Idempotency: an existing pending for this draft is returned unchanged (never overwritten).
    let existing: LabPending | null;
    try { existing = await getLabPendingByDraft(owner, device, draftId); } catch { throw new LabQueueError("storage"); }
    if (existing) {
        if (existing.sourceRevision !== input.expectedRevision) throw new LabQueueError("conflict");
        return { captureId: existing.capture_id, created: false, sourceRevision: existing.sourceRevision, queuedAt: existing.queuedAt };
    }

    let loaded;
    try { loaded = await loadQualityDraft(key, identity, draftId); } catch (error) { throw mapDraftError(error); }
    if (loaded.revision !== input.expectedRevision) throw new LabQueueError("conflict");
    if (!draftMatchesDefinition(loaded.payload, pkg)) throw new LabQueueError("stale_definition");
    const evaluation = evaluateDraft(pkg.definition, loaded.payload.values);
    if (evaluation.typeIssues.length > 0) throw new LabQueueError("corrupt");
    if (evaluation.missingRequired.length > 0) throw new LabQueueError("incomplete", evaluation.missingRequired.map(i => i.key));

    const captureId = await captureIdFor(owner, device, draftId);
    const contextId = await contextIdFor(loaded.payload.scope_snapshot_id, loaded.payload.machine_code, loaded.payload.form_code);
    const queuedAt = now().toISOString();
    const payload: PendingPayload = {
        schema: PENDING_SCHEMA, status: LAB_STATUS, synthetic: true, sync_state: "NOT_SYNCED", capture_id: captureId,
        source_draft_id: draftId, source_revision: loaded.revision, queued_local: queuedAt, draft: loaded.payload,
    };
    let sealed;
    try {
        sealed = await sealLocalDraft(key, bindingOf(identity, { capture_id: captureId, contextId, formCode: loaded.payload.form_code,
            formVersion: loaded.payload.form_version }), payload);
    } catch { throw new LabQueueError("storage"); }
    const record: LabPending = {
        capture_id: captureId, draftId, ownerId: owner, deviceKey: device, formCode: loaded.payload.form_code,
        formVersion: loaded.payload.form_version, contextId, sourceRevision: loaded.revision, queuedAt,
        status: LAB_STATUS, lab: true, syncState: "NOT_SYNCED", sealed,
    };
    try { await addLabPending(record); }
    catch (error) {
        if (error instanceof LabQueueStoreError && error.reason === "duplicate") {
            // A concurrent tab/click won the race: report that pending, never a second one.
            let winner: LabPending | null = null;
            try { winner = await getLabPendingByDraft(owner, device, draftId); } catch { /* fall through */ }
            if (winner && winner.sourceRevision === loaded.revision) {
                return { captureId: winner.capture_id, created: false, sourceRevision: winner.sourceRevision, queuedAt: winner.queuedAt };
            }
            throw new LabQueueError("conflict");
        }
        throw mapStoreError(error);
    }
    return { captureId, created: true, sourceRevision: loaded.revision, queuedAt };
}

function parsePending(body: Record<string, unknown>): PendingPayload {
    if (Object.keys(body).sort().join("|") !== [...PENDING_KEYS].sort().join("|")) throw new DraftSchemaError("invalid");
    if (body.schema !== PENDING_SCHEMA || body.status !== LAB_STATUS || body.synthetic !== true || body.sync_state !== "NOT_SYNCED" ||
        typeof body.capture_id !== "string" || !UUID.test(body.capture_id) || typeof body.source_draft_id !== "string" ||
        !UUID.test(body.source_draft_id) || !Number.isSafeInteger(body.source_revision) || (body.source_revision as number) < 1 ||
        typeof body.queued_local !== "string" || !Number.isFinite(Date.parse(body.queued_local))) throw new DraftSchemaError("invalid");
    parseDraftPayload(body.draft);
    return body as unknown as PendingPayload;
}

/** Decrypt and strictly validate one pending. A wrong key is `locked`; anything inconsistent is `corrupt`. */
export async function loadLabPending(key: CryptoKey, identity: OfflineVaultIdentity, record: LabPending): Promise<PendingPayload> {
    let body: Record<string, unknown>;
    try { body = await openLocalDraft(key, bindingOf(identity, record), record.sealed); }
    catch (error) { throw error instanceof VaultError && error.reason === "unlock_failed" ? new LabQueueError("locked") : new LabQueueError("corrupt"); }
    let payload: PendingPayload;
    try { payload = parsePending(body); } catch { throw new LabQueueError("corrupt"); }
    const d = payload.draft;
    const expectedCapture = await captureIdFor(record.ownerId, record.deviceKey, record.draftId);
    const expectedContext = await contextIdFor(d.scope_snapshot_id, d.machine_code, d.form_code);
    if (payload.capture_id !== record.capture_id || expectedCapture !== record.capture_id || payload.source_draft_id !== record.draftId ||
        d.draft_id !== record.draftId || d.author_user_id !== record.ownerId || d.device_key !== record.deviceKey ||
        d.form_code !== record.formCode || d.form_version !== record.formVersion || d.revision !== record.sourceRevision ||
        payload.source_revision !== record.sourceRevision || payload.queued_local !== record.queuedAt ||
        expectedContext !== record.contextId) throw new LabQueueError("corrupt");
    return payload;
}

/** Pendings of THIS owner+browser. Damaged ones are listed as such; none is ever modified or removed. */
export async function listLabPendingSummaries(
    key: CryptoKey, identity: OfflineVaultIdentity
): Promise<{ items: PendingSummary[]; malformed: number }> {
    let listed;
    try { listed = await listLabPending(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase()); }
    catch { throw new LabQueueError("storage"); }
    const items: PendingSummary[] = [];
    for (const record of listed.records) {
        try {
            const p = await loadLabPending(key, identity, record);
            items.push({ captureId: record.capture_id, corrupt: false, formCode: p.draft.form_code, formVersion: p.draft.form_version,
                machineCode: p.draft.machine_code, sourceRevision: p.source_revision, queuedAt: p.queued_local });
        } catch (error) {
            items.push({ captureId: record.capture_id, corrupt: true, reason: error instanceof LabQueueError && error.reason === "locked" ? "locked" : "corrupt" });
        }
    }
    return { items: items.sort((a, b) => a.captureId.localeCompare(b.captureId)), malformed: listed.malformed };
}

/** Which of this identity's draft ids are already pending (used to mark them read-only in the UI). */
export async function pendingDraftIds(identity: OfflineVaultIdentity): Promise<Set<string>> {
    const listed = await listLabPending(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase());
    return new Set(listed.records.map(r => r.draftId));
}
