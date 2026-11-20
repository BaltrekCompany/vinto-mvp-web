/**
 * OFF-04.1/04.2-R2 (LABORATORY ONLY): encrypted local Quality drafts.
 *
 * Drafts live in the consolidated laboratory database (offline-lab-db.ts), together with the simulated pendings,
 * so a save and the draft→pending transition are serialised by IndexedDB itself. The local vault is reused
 * (AES-256-GCM, AAD bound to owner, browser, draft, context, form and version). Values are only ever
 * persisted inside the sealed envelope. This module never opens the application's send queue, never queues, never
 * calls a network API and never turns a read-only package into a capture permission.
 */
import { getLabDraft, listLabDrafts, saveLabDraftRevision, LabDbError, type LabDraftRow } from "./offline-lab-db.ts";
import { openLocalDraft, sealLocalDraft, VaultError, type OfflineVaultIdentity } from "./offline-vault.ts";
import { QUALITY_OPERATIONS, type VerifiedQualityDefinition } from "./offline-quality-verify.ts";
import type { VerifiedLocalScope } from "./offline-scope-store.ts";
import {
    buildDraftPayload, contextIdFor, draftContextKey, draftMatchesDefinition, evaluateDraft, isLabEligible, parseBobbinContext, parseDraftPayload,
    DraftSchemaError, type BobbinContext, type DraftPayload, type FieldIssue,
} from "./offline-draft-schema.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type DraftErrorReason =
    | "invalid" | "ineligible" | "conflict" | "quota" | "storage" | "corrupt" | "locked"
    | "not_found" | "stale_definition" | "no_grant" | "pending_local" | "quarantined" | "lab_lost"
    | "bobbin_required" | "bobbin_not_allowed" | "bobbin_changed";
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
export type LoadedDraft = Readonly<{ payload: DraftPayload; revision: number; frozenBy: string | null; sealedFingerprint: string }>;
export type DraftSummary = Readonly<
    | { id: string; corrupt: false; frozen: boolean; formCode: string; formVersion: number; machineCode: string; revision: number; updatedLocal: string }
    | { id: string; corrupt: true; reason: "corrupt" | "locked" }
>;

const bindingOf = (identity: OfflineVaultIdentity, record: Pick<LabDraftRow, "id" | "contextId" | "formCode" | "formVersion">) =>
    ({ ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: record.id,
       contextId: record.contextId, formCode: record.formCode, formVersion: record.formVersion });

export function mapLabDbError(error: unknown): DraftError {
    if (error instanceof DraftError) return error;
    if (error instanceof LabDbError) {
        switch (error.reason) {
            case "conflict": case "owner_mismatch": case "duplicate": return new DraftError("conflict");
            case "quota": return new DraftError("quota");
            case "invalid": return new DraftError("invalid");
            case "pending_local": return new DraftError("pending_local");
            case "quarantined": return new DraftError("quarantined");
            case "lab_lost": case "lab_mismatch": return new DraftError("lab_lost");
            case "not_found": return new DraftError("not_found");
            default: return new DraftError("storage");
        }
    }
    return new DraftError("storage");
}

/** Grant check against the signed scope: the pair must be a Quality entry (by machine OR by bobbin) at the same version. Returns the operation the grant was issued for. */
export function assertGranted(scope: VerifiedLocalScope, pkg: VerifiedQualityDefinition): string {
    const p = pkg.envelope.payload;
    const grant = scope.envelope.payload.form_scopes.filter(x => x.machine_code === p.machine_code &&
        x.form_code === p.form_code && QUALITY_OPERATIONS.has(x.operation));
    if (grant.length !== 1 || grant[0].form_version !== p.form_version || grant[0].grant_id !== p.grant_id ||
        scope.envelope.payload.snapshot_id !== p.scope_snapshot_id) throw new DraftError("no_grant");
    return grant[0].operation;
}

/**
 * Create (expectedRevision=null) or update a draft. Resolves ONLY after the IndexedDB transaction
 * committed. Required fields missing keep it `draft`/incomplete; invalid types/options never save.
 */
export async function saveQualityDraft(
    key: CryptoKey, identity: OfflineVaultIdentity,
    context: Readonly<{ scope: VerifiedLocalScope; pkg: VerifiedQualityDefinition }>,
    input: Readonly<{ id: string; values: Readonly<Record<string, unknown>>; expectedRevision: number | null; bobbin?: BobbinContext | null }>,
    now: () => Date = () => new Date()
): Promise<DraftSaveResult> {
    if (!UUID.test(identity.ownerId) || !UUID.test(identity.deviceKey) || !UUID.test(input.id)) throw new DraftError("invalid");
    const pkg = context.pkg.envelope.payload;
    if (!isLabEligible(pkg.definition)) throw new DraftError("ineligible");
    if (pkg.subject_user_id.toLowerCase() !== identity.ownerId.toLowerCase() ||
        pkg.device_key.toLowerCase() !== identity.deviceKey.toLowerCase()) throw new DraftError("invalid");
    const operation = assertGranted(context.scope, context.pkg);
    // OFF-04.6: a draft of a by-bobbin form belongs to ONE physical bobbin (prepared online, same machine); a machine form never carries one.
    let bobbin: BobbinContext | undefined;
    if (operation === "quality_bobbin_capture") {
        if (!input.bobbin) throw new DraftError("bobbin_required");
        try { bobbin = parseBobbinContext(input.bobbin); } catch { throw new DraftError("invalid"); }
        if (bobbin.machine_code !== pkg.machine_code) throw new DraftError("invalid");
    } else if (input.bobbin) throw new DraftError("bobbin_not_allowed");
    // A draft that is (or may be) frozen is refused INSIDE the save transaction (see saveLabDraftRevision).
    const evaluation = evaluateDraft(pkg.definition, input.values);
    if (evaluation.typeIssues.length > 0) throw new DraftError("invalid", evaluation.typeIssues);

    let createdLocal = now().toISOString();
    if (input.expectedRevision !== null) {
        const previous = await loadQualityDraft(key, identity, input.id);
        if (previous.revision !== input.expectedRevision) throw new DraftError("conflict");
        if (!draftMatchesDefinition(previous.payload, pkg)) throw new DraftError("stale_definition");
        if ((previous.payload.bobbin_context?.bobbin_id ?? null) !== (bobbin?.bobbin_id.toLowerCase() ?? null) ||
            (previous.payload.bobbin_context?.context_digest ?? null) !== (bobbin?.context_digest ?? null)) throw new DraftError("bobbin_changed");   // the association never changes
        createdLocal = previous.payload.created_local;
    }
    const revision = (input.expectedRevision ?? 0) + 1;
    const updatedLocal = now().toISOString();
    const contextId = await contextIdFor(pkg.scope_snapshot_id, pkg.machine_code, draftContextKey(pkg.form_code, bobbin));
    const payload = buildDraftPayload({ pkg, ownerId: identity.ownerId, deviceKey: identity.deviceKey },
        input.id, evaluation.clean, revision, createdLocal, updatedLocal, bobbin);
    const record: LabDraftRow = {
        id: input.id.toLowerCase(), ownerId: identity.ownerId.toLowerCase(), deviceKey: identity.deviceKey.toLowerCase(),
        formCode: pkg.form_code, formVersion: pkg.form_version, contextId, savedAt: updatedLocal, revision,
        sealed: await sealLocalDraft(key, bindingOf(identity, { id: input.id.toLowerCase(), contextId,
            formCode: pkg.form_code, formVersion: pkg.form_version }), payload).catch(() => { throw new DraftError("storage"); }),
    };
    try { await saveLabDraftRevision(record, input.expectedRevision); }
    catch (error) { throw mapLabDbError(error); }
    return { revision, savedAt: updatedLocal, complete: evaluation.missingRequired.length === 0,
             missingRequired: evaluation.missingRequired };
}

/** Decrypt and strictly validate one draft; any inconsistency is `corrupt`, a wrong key is `locked`. */
export async function loadQualityDraft(key: CryptoKey, identity: OfflineVaultIdentity, id: string): Promise<LoadedDraft> {
    let record: LabDraftRow | null;
    try { record = await getLabDraft(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase(), id.toLowerCase()); }
    catch (error) {
        if (error instanceof LabDbError && error.reason === "invalid") {
            // a malformed row is damaged evidence, not an input error
            throw new DraftError(/^[0-9a-f-]{36}$/i.test(id) ? "corrupt" : "invalid");
        }
        throw mapLabDbError(error);
    }
    if (!record) throw new DraftError("not_found");
    let body: Record<string, unknown>;
    try { body = await openLocalDraft(key, bindingOf(identity, record), record.sealed); }
    catch (error) { throw error instanceof VaultError && error.reason === "unlock_failed" ? new DraftError("locked") : new DraftError("corrupt"); }
    let payload: DraftPayload;
    try { payload = parseDraftPayload(body); }
    catch (error) { throw error instanceof DraftSchemaError ? new DraftError("corrupt") : new DraftError("storage"); }
    const expectedContext = await contextIdFor(payload.scope_snapshot_id, payload.machine_code, draftContextKey(payload.form_code, payload.bobbin_context));
    if (payload.draft_id !== record.id || payload.author_user_id !== record.ownerId || payload.device_key !== record.deviceKey ||
        payload.form_code !== record.formCode || payload.form_version !== record.formVersion ||
        payload.revision !== record.revision || expectedContext !== record.contextId) throw new DraftError("corrupt");
    return { payload, revision: payload.revision, frozenBy: record.frozenBy ?? null, sealedFingerprint: record.sealed.ciphertext };
}

/** Drafts of THIS owner+browser only. A damaged draft is listed as corrupt, never hidden, never fatal. */
export async function listQualityDrafts(key: CryptoKey, identity: OfflineVaultIdentity): Promise<DraftSummary[]> {
    let records: LabDraftRow[];
    try { records = await listLabDrafts(identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase()); }
    catch (error) { throw mapLabDbError(error); }
    const out: DraftSummary[] = [];
    for (const record of records) {
        try {
            const { payload, revision, frozenBy } = await loadQualityDraft(key, identity, record.id);
            out.push({ id: record.id, corrupt: false, frozen: frozenBy !== null, formCode: payload.form_code, formVersion: payload.form_version,
                machineCode: payload.machine_code, revision, updatedLocal: payload.updated_local });
        } catch (error) {
            out.push({ id: record.id, corrupt: true, reason: error instanceof DraftError && error.reason === "locked" ? "locked" : "corrupt" });
        }
    }
    return out.sort((a, b) => a.id.localeCompare(b.id));
}
