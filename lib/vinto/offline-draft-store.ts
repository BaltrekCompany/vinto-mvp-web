/**
 * OFF-04.1 (LABORATORY ONLY): encrypted local Quality drafts.
 *
 * Reuses, unchanged in shape, the existing `drafts` store of `vinto-offline-v1` and the local vault
 * (AES-256-GCM, AAD bound to owner, browser, draft, context, form and version). Values are only ever
 * persisted inside the sealed envelope. This module never opens the send queue store, never queues, never
 * calls a network API and never turns a read-only package into a capture permission.
 */
import {
    getSealedDraft, listSealedDrafts, saveSealedDraftRevision, OfflineStoreError, type OfflineDraft, type RevisionedDraft,
} from "./offline-store.ts";
import { openLocalDraft, sealLocalDraft, VaultError, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { VerifiedQualityDefinition } from "./offline-quality-verify.ts";
import type { VerifiedLocalScope } from "./offline-scope-store.ts";
import {
    buildDraftPayload, contextIdFor, draftMatchesDefinition, evaluateDraft, isLabEligible, parseDraftPayload,
    DraftSchemaError, type DraftPayload, type FieldIssue,
} from "./offline-draft-schema.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type DraftErrorReason =
    | "invalid" | "ineligible" | "conflict" | "quota" | "storage" | "corrupt" | "locked"
    | "not_found" | "stale_definition" | "no_grant";
export class DraftError extends Error {
    readonly reason: DraftErrorReason;
    readonly issues: readonly FieldIssue[];
    constructor(reason: DraftErrorReason, issues: readonly FieldIssue[] = []) {
        super("OFFLINE_DRAFT_" + reason.toUpperCase());
        this.name = "DraftError";
        this.reason = reason;
        this.issues = issues;
    }
}

export type DraftSaveResult = Readonly<{ revision: number; savedAt: string; complete: boolean; missingRequired: readonly FieldIssue[] }>;
export type LoadedDraft = Readonly<{ payload: DraftPayload; revision: number }>;
export type DraftSummary = Readonly<
    | { id: string; corrupt: false; formCode: string; formVersion: number; machineCode: string; revision: number; updatedLocal: string }
    | { id: string; corrupt: true; reason: "corrupt" | "locked" }
>;

const bindingOf = (identity: OfflineVaultIdentity, record: Pick<OfflineDraft, "id" | "contextId" | "formCode" | "formVersion">) =>
    ({ ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: record.id,
       contextId: record.contextId, formCode: record.formCode, formVersion: record.formVersion });

function mapStoreError(error: unknown): DraftError {
    if (error instanceof DraftError) return error;
    if (error instanceof OfflineStoreError) {
        if (error.reason === "conflict" || error.reason === "owner_mismatch") return new DraftError("conflict");
        if (error.reason === "quota") return new DraftError("quota");
        if (error.reason === "invalid") return new DraftError("invalid");
        if (error.reason === "already_queued") return new DraftError("invalid");
    }
    return new DraftError("storage");
}

/** Grant check against the signed scope: the pair must be a Quality machine entry at the same version. */
function assertGranted(scope: VerifiedLocalScope, pkg: VerifiedQualityDefinition): void {
    const p = pkg.envelope.payload;
    const grant = scope.envelope.payload.form_scopes.filter(x => x.machine_code === p.machine_code &&
        x.form_code === p.form_code && x.operation === "quality_machine_capture");
    if (grant.length !== 1 || grant[0].form_version !== p.form_version || grant[0].grant_id !== p.grant_id ||
        scope.envelope.payload.snapshot_id !== p.scope_snapshot_id) throw new DraftError("no_grant");
}

/**
 * Create (expectedRevision=null) or update a draft. Resolves ONLY after the IndexedDB transaction
 * committed. Required fields missing keep it `draft`/incomplete; invalid types/options never save.
 */
export async function saveQualityDraft(
    key: CryptoKey, identity: OfflineVaultIdentity,
    context: Readonly<{ scope: VerifiedLocalScope; pkg: VerifiedQualityDefinition }>,
    input: Readonly<{ id: string; values: Readonly<Record<string, unknown>>; expectedRevision: number | null }>,
    now: () => Date = () => new Date()
): Promise<DraftSaveResult> {
    if (!UUID.test(identity.ownerId) || !UUID.test(identity.deviceKey) || !UUID.test(input.id)) throw new DraftError("invalid");
    const pkg = context.pkg.envelope.payload;
    if (!isLabEligible(pkg.definition)) throw new DraftError("ineligible");
    if (pkg.subject_user_id.toLowerCase() !== identity.ownerId.toLowerCase() ||
        pkg.device_key.toLowerCase() !== identity.deviceKey.toLowerCase()) throw new DraftError("invalid");
    assertGranted(context.scope, context.pkg);
    const evaluation = evaluateDraft(pkg.definition, input.values);
    if (evaluation.typeIssues.length > 0) throw new DraftError("invalid", evaluation.typeIssues);

    let createdLocal = now().toISOString();
    if (input.expectedRevision !== null) {
        const previous = await loadQualityDraft(key, identity, input.id);
        if (previous.revision !== input.expectedRevision) throw new DraftError("conflict");
        if (!draftMatchesDefinition(previous.payload, pkg)) throw new DraftError("stale_definition");
        createdLocal = previous.payload.created_local;
    }
    const revision = (input.expectedRevision ?? 0) + 1;
    const updatedLocal = now().toISOString();
    const contextId = await contextIdFor(pkg.scope_snapshot_id, pkg.machine_code, pkg.form_code);
    const payload = buildDraftPayload({ pkg, ownerId: identity.ownerId, deviceKey: identity.deviceKey },
        input.id, evaluation.clean, revision, createdLocal, updatedLocal);
    const record: RevisionedDraft = {
        id: input.id.toLowerCase(), ownerId: identity.ownerId.toLowerCase(), deviceKey: identity.deviceKey.toLowerCase(),
        formCode: pkg.form_code, formVersion: pkg.form_version, contextId, savedAt: updatedLocal, revision,
        sealed: await sealLocalDraft(key, bindingOf(identity, { id: input.id.toLowerCase(), contextId,
            formCode: pkg.form_code, formVersion: pkg.form_version }), payload).catch(() => { throw new DraftError("storage"); }),
    };
    try { await saveSealedDraftRevision(record, input.expectedRevision); }
    catch (error) { throw mapStoreError(error); }
    return { revision, savedAt: updatedLocal, complete: evaluation.missingRequired.length === 0,
             missingRequired: evaluation.missingRequired };
}

/** Decrypt and strictly validate one draft; any inconsistency is `corrupt`, a wrong key is `locked`. */
export async function loadQualityDraft(key: CryptoKey, identity: OfflineVaultIdentity, id: string): Promise<LoadedDraft> {
    let record: (OfflineDraft & { revision?: unknown }) | null;
    try { record = await getSealedDraft(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase(), id.toLowerCase()); }
    catch (error) { throw error instanceof OfflineStoreError && error.reason === "invalid" ? new DraftError("invalid") : new DraftError("storage"); }
    if (!record) throw new DraftError("not_found");
    if (!Number.isSafeInteger(record.revision) || (record.revision as number) < 1) throw new DraftError("corrupt");
    let body: Record<string, unknown>;
    try { body = await openLocalDraft(key, bindingOf(identity, record), record.sealed); }
    catch (error) { throw error instanceof VaultError && error.reason === "unlock_failed" ? new DraftError("locked") : new DraftError("corrupt"); }
    let payload: DraftPayload;
    try { payload = parseDraftPayload(body); }
    catch (error) { throw error instanceof DraftSchemaError ? new DraftError("corrupt") : new DraftError("storage"); }
    const expectedContext = await contextIdFor(payload.scope_snapshot_id, payload.machine_code, payload.form_code);
    if (payload.draft_id !== record.id || payload.author_user_id !== record.ownerId || payload.device_key !== record.deviceKey ||
        payload.form_code !== record.formCode || payload.form_version !== record.formVersion ||
        payload.revision !== record.revision || expectedContext !== record.contextId) throw new DraftError("corrupt");
    return { payload, revision: payload.revision };
}

/** Drafts of THIS owner+browser only. A damaged draft is listed as corrupt, never hidden, never fatal. */
export async function listQualityDrafts(key: CryptoKey, identity: OfflineVaultIdentity): Promise<DraftSummary[]> {
    let records: OfflineDraft[];
    try { records = await listSealedDrafts(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase()); }
    catch { throw new DraftError("storage"); }
    const out: DraftSummary[] = [];
    for (const record of records) {
        try {
            const { payload, revision } = await loadQualityDraft(key, identity, record.id);
            out.push({ id: record.id, corrupt: false, formCode: payload.form_code, formVersion: payload.form_version,
                machineCode: payload.machine_code, revision, updatedLocal: payload.updated_local });
        } catch (error) {
            out.push({ id: record.id, corrupt: true, reason: error instanceof DraftError && error.reason === "locked" ? "locked" : "corrupt" });
        }
    }
    return out.sort((a, b) => a.id.localeCompare(b.id));
}
