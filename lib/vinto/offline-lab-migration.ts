/**
 * OFF-04.2-R2 (LABORATORY ONLY): NON-DESTRUCTIVE migration of the synthetic laboratory data that earlier
 * increments kept in two other places (drafts in the application's `drafts` store, simulated pendings in
 * the former laboratory queue database) into the consolidated laboratory database.
 *
 * Phases: PREPARE (read-only; decrypt and verify every row) → VERIFY (consistency of the plan) → COMMIT (one
 * add-only IndexedDB transaction, marker included) → VERIFY-COMMITTED (re-read both sides: the laboratory has the
 * rows and the legacy sources are byte-identical to what was read). Legacy data is NEVER written, changed or
 * deleted. Sealed blobs are copied verbatim (their AAD does not depend on the database). A failure at any point
 * leaves the laboratory untouched; the whole procedure can simply be run again.
 */
import { listSealedDrafts, type OfflineDraft } from "./offline-store.ts";
import { openLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import { contextIdFor, parseDraftPayload, DraftSchemaError } from "./offline-draft-schema.ts";
import { loadLabPending, LabQueueError } from "./offline-lab-queue.ts";
import {
    commitMigrationBatch, getLabDraft, getLabPending, isLabPending, readMeta, LabDbError,
    type LabDraftRow, type LabPending, type QuarantineRow,
} from "./offline-lab-db.ts";

export const LEGACY_QUEUE_DB = "vinto-off04lab-queue-v1";
const encoder = new TextEncoder();

export type MigrationReason = "locked" | "storage" | "inconsistent" | "lab_lost" | "quota" | "verification_failed";
export class LabMigrationError extends Error {
    readonly reason: MigrationReason;
    constructor(reason: MigrationReason) {
        super("OFFLINE_LAB_MIGRATION_" + reason.toUpperCase());
        this.name = "LabMigrationError";
        this.reason = reason;
    }
}

type LegacyData = Readonly<{ drafts: (OfflineDraft & { revision?: unknown })[]; pendings: unknown[] }>;
export type MigrationPlan = Readonly<{
    alreadyMigrated: boolean; metaKey: string; drafts: LabDraftRow[]; pendings: LabPending[]; quarantine: QuarantineRow[];
    divergent: string[]; legacyFingerprint: string;
}>;
export type MigrationReport = Readonly<{
    alreadyMigrated: boolean; migratedDrafts: number; migratedPendings: number; quarantined: number; divergent: number; skippedIdentical: number;
}>;

async function sha256(text: string): Promise<string> {
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text) as BufferSource));
    return Array.from(d, b => b.toString(16).padStart(2, "0")).join("");
}

/** Open the former queue database WITHOUT creating it (an absent database aborts its own creation). */
function readLegacyQueue(owner: string, device: string): Promise<unknown[]> {
    if (typeof indexedDB === "undefined") return Promise.resolve([]);
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(LEGACY_QUEUE_DB); } catch { resolve([]); return; }
        request.onupgradeneeded = () => { try { request.transaction?.abort(); } catch { /* nothing to create */ } };
        request.onerror = () => {
            if (request.error === null || request.error.name === "AbortError") resolve([]);   // the absent database aborted its own creation
            else reject(new LabMigrationError("storage"));
        };
        request.onsuccess = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("lab_pending")) { db.close(); resolve([]); return; }
            const tx = db.transaction("lab_pending", "readonly");
            const r = tx.objectStore("lab_pending").getAll();
            r.onsuccess = () => {
                db.close();
                resolve((r.result as Record<string, unknown>[]).filter(x => x && x.ownerId === owner && x.deviceKey === device));
            };
            r.onerror = () => { db.close(); reject(new LabMigrationError("storage")); };
        };
    });
}

async function readLegacy(owner: string, device: string): Promise<LegacyData> {
    let drafts: (OfflineDraft & { revision?: unknown })[];
    try { drafts = await listSealedDrafts(owner, device) as (OfflineDraft & { revision?: unknown })[]; }
    catch { throw new LabMigrationError("storage"); }
    return { drafts: [...drafts].sort((a, b) => a.id.localeCompare(b.id)), pendings: [...(await readLegacyQueue(owner, device))]
        .sort((a, b) => String((a as { capture_id?: string }).capture_id).localeCompare(String((b as { capture_id?: string }).capture_id))) };
}
const fingerprintOf = (l: LegacyData) => sha256(JSON.stringify([l.drafts, l.pendings]));

const evidence = (source: string, id: string, reason: string, owner: string, device: string, raw: unknown): QuarantineRow =>
    ({ id: source + "-" + id, source, reason, at: new Date().toISOString(), ownerId: owner, deviceKey: device, raw: JSON.stringify(raw) });

async function verifyLegacyDraft(key: CryptoKey, identity: OfflineVaultIdentity, row: OfflineDraft & { revision?: unknown }): Promise<LabDraftRow | string> {
    if (!Number.isSafeInteger(row.revision) || (row.revision as number) < 1) return "no_revision";
    let body: Record<string, unknown>;
    try {
        body = await openLocalDraft(key, { ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: row.id, contextId: row.contextId,
            formCode: row.formCode, formVersion: row.formVersion }, row.sealed);
    } catch { return "undecryptable"; }
    let payload;
    try { payload = parseDraftPayload(body); } catch (error) { if (error instanceof DraftSchemaError) return "not_a_lab_draft"; return "not_a_lab_draft"; }
    const ctx = await contextIdFor(payload.scope_snapshot_id, payload.machine_code, payload.form_code);
    if (payload.draft_id !== row.id || payload.author_user_id !== row.ownerId || payload.device_key !== row.deviceKey ||
        payload.form_code !== row.formCode || payload.form_version !== row.formVersion || payload.revision !== row.revision || ctx !== row.contextId) return "inconsistent";
    return { id: row.id, ownerId: row.ownerId, deviceKey: row.deviceKey, formCode: row.formCode, formVersion: row.formVersion,
        contextId: row.contextId, savedAt: row.savedAt, revision: row.revision as number, sealed: row.sealed };
}

/**
 * PREPARE: read-only. The vault cannot tell a wrong key from damaged data (same AEAD failure). Unless the caller
 * proved the key (`keyVerified`, e.g. the signed scope was just decrypted with it), a run where NOTHING decrypts is
 * treated as a wrong key and aborts, so a typo can never classify healthy data as damaged.
 */
export async function prepareLegacyMigration(key: CryptoKey, identity: OfflineVaultIdentity, keyVerified = false): Promise<MigrationPlan> {
    const owner = identity.ownerId.toLowerCase(), device = identity.deviceKey.toLowerCase();
    const metaKey = `migration:${owner}:${device}`;
    let done: unknown;
    try { done = await readMeta(metaKey); } catch (error) { throw error instanceof LabDbError && (error.reason === "lab_lost" || error.reason === "lab_mismatch") ? new LabMigrationError("lab_lost") : new LabMigrationError("storage"); }
    const legacy = await readLegacy(owner, device);
    const legacyFingerprint = await fingerprintOf(legacy);
    if (done !== undefined) return { alreadyMigrated: true, metaKey, drafts: [], pendings: [], quarantine: [], divergent: [], legacyFingerprint };
    const drafts: LabDraftRow[] = [], pendings: LabPending[] = [], quarantine: QuarantineRow[] = [];
    let decrypted = 0, undecryptable = 0;
    for (const row of legacy.drafts) {
        const verified = await verifyLegacyDraft(key, identity, row);
        if (verified === "undecryptable") undecryptable += 1; else decrypted += 1;
        if (typeof verified === "string") quarantine.push(evidence("legacy_draft", row.id, verified, owner, device, row)); else drafts.push(verified);
    }
    for (const raw of legacy.pendings) {
        const id = String((raw as { capture_id?: unknown }).capture_id);
        if (!isLabPending(raw)) { quarantine.push(evidence("legacy_pending", id, "malformed", owner, device, raw)); continue; }
        try { await loadLabPending(key, identity, raw); pendings.push(raw); decrypted += 1; }
        catch (error) {
            if (error instanceof LabQueueError && error.reason === "locked") undecryptable += 1; else decrypted += 1;
            quarantine.push(evidence("legacy_pending", id, "unverifiable", owner, device, raw));
        }
    }
    if (!keyVerified && decrypted === 0 && undecryptable > 0) throw new LabMigrationError("locked");
    const byDraft = new Map(drafts.map(d => [d.id, d]));
    const divergent = pendings.filter(p => { const d = byDraft.get(p.draftId); return !!d && d.revision > p.sourceRevision; }).map(p => p.capture_id);
    return { alreadyMigrated: false, metaKey, drafts, pendings, quarantine, divergent, legacyFingerprint };
}

/** VERIFY: internal consistency of the plan before anything is written. */
export function verifyMigrationPlan(plan: MigrationPlan): void {
    const ids = plan.drafts.map(d => d.id), caps = plan.pendings.map(p => p.capture_id), drafts = plan.pendings.map(p => p.draftId);
    if (new Set(ids).size !== ids.length || new Set(caps).size !== caps.length || new Set(drafts).size !== drafts.length) throw new LabMigrationError("inconsistent");
    const byDraft = new Map(plan.drafts.map(d => [d.id, d]));
    for (const p of plan.pendings) {
        const d = byDraft.get(p.draftId);
        if (d && (d.ownerId !== p.ownerId || d.deviceKey !== p.deviceKey || d.revision < p.sourceRevision)) throw new LabMigrationError("inconsistent");
    }
}

/** COMMIT: one add-only transaction including the marker. */
export async function commitLegacyMigration(plan: MigrationPlan): Promise<MigrationReport> {
    if (plan.alreadyMigrated) return { alreadyMigrated: true, migratedDrafts: 0, migratedPendings: 0, quarantined: 0, divergent: 0, skippedIdentical: 0 };
    const fp = async (c: string) => sha256(c);
    const metaValue = { at: new Date().toISOString(), legacyFingerprint: plan.legacyFingerprint,
        drafts: await Promise.all(plan.drafts.map(async d => ({ id: d.id, revision: d.revision, fp: await fp(d.sealed.ciphertext) }))),
        pendings: await Promise.all(plan.pendings.map(async p => ({ capture_id: p.capture_id, fp: await fp(p.sealed.ciphertext) }))),
        quarantined: plan.quarantine.length, divergent: plan.divergent };
    let outcome;
    try { outcome = await commitMigrationBatch({ metaKey: plan.metaKey, metaValue, drafts: plan.drafts, pendings: plan.pendings, quarantine: plan.quarantine }); }
    catch (error) {
        if (error instanceof LabDbError) throw new LabMigrationError(error.reason === "quota" ? "quota" : error.reason === "lab_lost" || error.reason === "lab_mismatch" ? "lab_lost" : "storage");
        throw new LabMigrationError("storage");
    }
    if (outcome === "already_migrated") return { alreadyMigrated: true, migratedDrafts: 0, migratedPendings: 0, quarantined: 0, divergent: 0, skippedIdentical: 0 };
    return { alreadyMigrated: false, migratedDrafts: outcome.addedDrafts, migratedPendings: outcome.addedPendings, quarantined: plan.quarantine.length + outcome.conflicts,
        divergent: plan.divergent.length, skippedIdentical: outcome.skippedIdentical };
}

/** VERIFY-COMMITTED: the laboratory holds exactly the verified blobs AND the legacy sources did not change. */
export async function verifyCommittedMigration(plan: MigrationPlan, identity: OfflineVaultIdentity): Promise<void> {
    if (plan.alreadyMigrated) return;
    const owner = identity.ownerId.toLowerCase(), device = identity.deviceKey.toLowerCase();
    try {
        for (const d of plan.drafts) {
            const row = await getLabDraft(owner, device, d.id);
            if (!row || row.sealed.ciphertext !== d.sealed.ciphertext || row.revision !== d.revision) throw new LabMigrationError("verification_failed");
        }
        for (const p of plan.pendings) {
            const row = await getLabPending(owner, device, p.capture_id);
            if (!row || row.sealed.ciphertext !== p.sealed.ciphertext) throw new LabMigrationError("verification_failed");
        }
    } catch (error) { throw error instanceof LabMigrationError ? error : new LabMigrationError("storage"); }
    if (await fingerprintOf(await readLegacy(owner, device)) !== plan.legacyFingerprint) throw new LabMigrationError("verification_failed");
}

/** Convenience: prepare → verify → commit → verify-committed. Never touches legacy data. */
export async function runLegacyMigration(key: CryptoKey, identity: OfflineVaultIdentity, keyVerified = false): Promise<MigrationReport> {
    const plan = await prepareLegacyMigration(key, identity, keyVerified);
    if (plan.alreadyMigrated) return commitLegacyMigration(plan);
    verifyMigrationPlan(plan);
    const report = await commitLegacyMigration(plan);
    await verifyCommittedMigration(plan, identity);
    return report;
}
