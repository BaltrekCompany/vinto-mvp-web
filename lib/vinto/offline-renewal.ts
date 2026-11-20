/**
 * OFF-03C.4: atomic, all-or-nothing renewal of the signed scope AND its encrypted
 * Quality packages, for ONE owner in ONE browser. Read-only definitions only:
 * this module never enables capture, approval, release or synchronisation.
 *
 * Why it exists: a package is bound to the exact signed-scope snapshot it was issued
 * under. Replacing the scope first orphans every package; storing a package first is
 * impossible because it must match the scope already saved. So the pair has to be
 * replaced in ONE IndexedDB transaction, after everything was fetched, verified and
 * encrypted in memory. Nothing is written before that single commit.
 *
 * A valid signature proves the integrity of a HISTORICAL snapshot. It never proves
 * that the grant is still in force; only an online answer can, and a known revocation
 * is recorded in a sealed marker so the offline screen stops presenting the old
 * set as available.
 */
import { openProfileDb, PACKAGE_STORE_NAME, readLocalProfile, SCOPE_STORE_NAME } from "./offline-profile-store.ts";
import { openLocalDraft, sealLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { SealedValues } from "./offline-store";
import {
    compareScopeFreshness, verifyOfflineScope, ScopeError, type SignedOfflineScope,
} from "./offline-scope-verify.ts";
import {
    readOfflineScope, readRawScope, sealScopeRecord, validStoredScope, type StoredScope,
    type VerifiedLocalScope,
} from "./offline-scope-store.ts";
import { verifyQualityPackage, QualityPackageError, type VerifiedQualityDefinition } from "./offline-quality-verify.ts";
import {
    clearUnrecordedRevocation, noteUnrecordedRevocation, unrecordedRevocationAt,
} from "./offline-revocation-fallback.ts";
import {
    assertPackageProgression, readQualityPackage, readRawPackage, sealPackageRecord,
    validPackageRecord, type StoredPackage,
} from "./offline-quality-store.ts";

export const RENEWAL_MARKER_FORM = "VINTO-OFFLINE-RENEWAL";
const MARKER_SCHEMA = "vinto.offline.renewal-marker.v1";
const QUALITY_FORMS = /^VINTO-P1-(18|19|20|21|22|24|25|26|27|28)$/;      // OFF-04.6: the ten Quality forms (by machine and by bobbin)
const QUALITY_OPS = new Set(["quality_machine_capture", "quality_bobbin_capture"]);
const MACHINE = /^[A-Za-z0-9_.-]{1,48}$/;
const MAX_RENEWED_PACKAGES = 24;
export const DISCARD_CONFIRMATION = "DISCARD_SUPERSEDED_PACKAGES" as const;

export type RenewalPair = Readonly<{ machine_code: string; form_code: string }>;
export type RenewalReason =
    | "network" | "auth" | "revoked" | "revoked_unrecorded" | "server_unavailable" | "invalid" | "rollback"
    | "identity_mismatch" | "pin_mismatch" | "incompatible" | "needs_recovery" | "conflict"
    | "storage" | "commit_failed" | "no_local_scope";

export class RenewalError extends Error {
    readonly reason: RenewalReason;
    /** "prepare": nothing was written. "commit": the single transaction was rolled back. */
    readonly stage: "prepare" | "commit";
    constructor(reason: RenewalReason, stage: "prepare" | "commit" = "prepare") {
        super("OFFLINE_RENEWAL_" + reason.toUpperCase());
        this.name = "RenewalError";
        this.reason = reason;
        this.stage = stage;
    }
}

/** Network access is injected: the caller binds the device key and the HTTPS clients. */
export type RenewalDeps = Readonly<{
    fetchScope: (machineCodes: string[]) => Promise<unknown>;
    fetchPackage: (machineCode: string, formCode: string, scope: SignedOfflineScope) => Promise<unknown>;
}>;
export type RenewalOptions = Readonly<{
    /** Explicit recovery: allow replacing unreadable (corrupt) local data. Never automatic. */
    allowReplaceUnreadable?: boolean;
    /** Machines to request when the previous scope cannot be read. */
    machineCodes?: string[];
    /** Packages never stored before that should be added by this renewal. */
    extraPairs?: RenewalPair[];
    now?: () => Date;
}>;
export type RenewalResult = Readonly<{
    outcome: "renewed";
    snapshotId: string;
    renewedPackages: RenewalPair[];
    removedPairs: RenewalPair[];
    reduced: boolean;
}>;
export type RenewalStatusName = "renewed_online" | "revocation_known" | "legacy_unverified" | "unreadable";
/**
 * `durable` is false when the status comes from the fail-closed fallback (a refusal observed
 * online that could not be sealed into IndexedDB), true when it comes from the sealed marker.
 */
export type RenewalStatus = Readonly<{ status: RenewalStatusName; recordedAt: string | null; durable: boolean }>;

const pairKey = (p: RenewalPair): string => p.machine_code + "|" + p.form_code;

/** Pure: which packages are carried into the new set and which fall out of it. */
export function planRenewalPairs(
    existing: readonly RenewalPair[], extra: readonly RenewalPair[], next: SignedOfflineScope
): { renew: RenewalPair[]; removed: RenewalPair[]; missingExtra: RenewalPair[] } {
    const granted = new Set(next.payload.form_scopes
        .filter(x => QUALITY_OPS.has(x.operation) && QUALITY_FORMS.test(x.form_code))
        .map(x => x.machine_code + "|" + x.form_code));
    const renew = new Map<string, RenewalPair>(), removed: RenewalPair[] = [], missingExtra: RenewalPair[] = [];
    for (const p of existing) {
        if (granted.has(pairKey(p))) renew.set(pairKey(p), { machine_code: p.machine_code, form_code: p.form_code });
        else removed.push({ machine_code: p.machine_code, form_code: p.form_code });
    }
    for (const p of extra) {
        if (granted.has(pairKey(p))) renew.set(pairKey(p), { machine_code: p.machine_code, form_code: p.form_code });
        else missingExtra.push({ machine_code: p.machine_code, form_code: p.form_code });
    }
    const sorted = [...renew.values()].sort((a, b) => pairKey(a).localeCompare(pairKey(b)));
    return { renew: sorted, removed, missingExtra };
}

// ---------------------------------------------------------------------------
// Sealed renewal marker (last online verification outcome). Never lists permissions.
// ---------------------------------------------------------------------------
type MarkerContent = {
    schema: typeof MARKER_SCHEMA; status: "renewed_online" | "revocation_known";
    snapshotId: string; issuedAt: string | null; recordedAt: string;
};
function markerBinding(identity: OfflineVaultIdentity, snapshotId: string) {
    return { ...identity, id: snapshotId, contextId: snapshotId, formCode: RENEWAL_MARKER_FORM, formVersion: 1 };
}
async function sealMarker(key: CryptoKey, identity: OfflineVaultIdentity, content: MarkerContent) {
    return sealLocalDraft(key, markerBinding(identity, content.snapshotId), content);
}

/** Opaque identity of a sealed marker (iv + ciphertext only); never the plaintext content. */
function markerFingerprint(sealed: SealedValues | undefined): string {
    return sealed === undefined ? "none" : sealed.format + "." + sealed.iv + "." + sealed.ciphertext;
}

/** Read the last online-verification outcome. Fail closed on any inconsistency. */
export async function readRenewalStatus(key: CryptoKey, identity: OfflineVaultIdentity): Promise<RenewalStatus | null> {
    const raw = await readRawScope(identity);
    if (!raw) return null;
    let sealedStatus: RenewalStatus;
    if (raw.renewal === undefined) sealedStatus = { status: "legacy_unverified", recordedAt: null, durable: true };
    else {
        try {
            const body = await openLocalDraft(key, markerBinding(identity, raw.snapshotId), raw.renewal);
            sealedStatus = (body.schema !== MARKER_SCHEMA || body.snapshotId !== raw.snapshotId ||
                (body.status !== "renewed_online" && body.status !== "revocation_known") ||
                typeof body.recordedAt !== "string" || !Number.isFinite(Date.parse(body.recordedAt)))
                ? { status: "unreadable", recordedAt: null, durable: true }
                : { status: body.status, recordedAt: body.recordedAt, durable: true };
        } catch { sealedStatus = { status: "unreadable", recordedAt: null, durable: true }; }
    }
    // A refusal observed online but never sealed still closes the set, unless a verified
    // renewal that STARTED AFTER that refusal has since been committed.
    const fallbackAt = unrecordedRevocationAt(raw.profileId);
    if (fallbackAt !== null && sealedStatus.status !== "revocation_known" && sealedStatus.status !== "unreadable") {
        const renewedAt = sealedStatus.status === "renewed_online" && sealedStatus.recordedAt
            ? Date.parse(sealedStatus.recordedAt) : -Infinity;
        if (renewedAt < fallbackAt) {
            return { status: "revocation_known", recordedAt: new Date(fallbackAt).toISOString(), durable: false };
        }
    }
    return sealedStatus;
}

/**
 * Seal a refusal into the scope record. THROWS if it could not be confirmed written.
 * If another tab changed the record meanwhile the refusal is re-applied to the CURRENT
 * snapshot (a 403 means the user has no effective grants regardless of snapshot): when the
 * order of the two operations cannot be proven, the safe outcome is the closed one.
 */
async function recordRevocationKnown(key: CryptoKey, identity: OfflineVaultIdentity, observedAt: Date): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt++) {
        const current = await readRawScope(identity);
        if (!current) throw new RenewalError("no_local_scope", "commit");
        const sealed = await sealMarker(key, identity, {
            schema: MARKER_SCHEMA, status: "revocation_known", snapshotId: current.snapshotId,
            issuedAt: null, recordedAt: observedAt.toISOString(),
        });
        const db = await openProfileDb();
        try {
            const done = await new Promise<boolean>((resolve, reject) => {
                const tx = db.transaction(SCOPE_STORE_NAME, "readwrite");
                const store = tx.objectStore(SCOPE_STORE_NAME);
                let changed = false;
                const get = store.get(current.profileId);
                get.onsuccess = () => {
                    const row = get.result as StoredScope | undefined;
                    if (!row || !validStoredScope(row, identity) || row.snapshotId !== current.snapshotId ||
                        markerFingerprint(row.renewal) !== markerFingerprint(current.renewal)) {
                        changed = true; return;                      // someone else wrote: re-read and retry
                    }
                    store.put({ ...row, schemaVersion: 2 as const, renewal: sealed });
                };
                tx.oncomplete = () => resolve(!changed);
                tx.onabort = () => reject(new RenewalError("commit_failed", "commit"));
                tx.onerror = () => reject(new RenewalError("commit_failed", "commit"));
            });
            if (done) return;
        } finally { db.close(); }
    }
    throw new RenewalError("conflict", "commit");
}

/** Turn an online HTTP 403 into the right error, never claiming persistence that was not confirmed. */
async function refuse(key: CryptoKey, identity: OfflineVaultIdentity, profileId: string, observedAt: Date): Promise<RenewalError> {
    try {
        await recordRevocationKnown(key, identity, observedAt);
        clearUnrecordedRevocation(profileId, observedAt.getTime());
        return new RenewalError("revoked");
    } catch {
        // Keep the set closed in this context (and across restarts when the browser's key-value storage accepts writes).
        noteUnrecordedRevocation(profileId, observedAt.getTime());
        return new RenewalError("revoked_unrecorded");
    }
}

function statusOf(error: unknown): number | undefined {
    const s = (error as { status?: unknown } | null)?.status;
    return typeof s === "number" ? s : undefined;
}
function classifyFetch(error: unknown): RenewalReason {
    const status = statusOf(error);
    if (status === 403) return "revoked";
    if (status === 401) return "auth";
    if (status !== undefined) return "server_unavailable";
    return "network";
}

type Existing = Readonly<{ pair: RenewalPair; raw: StoredPackage; verified: VerifiedQualityDefinition | null }>;

async function enumerateExisting(
    key: CryptoKey, identity: OfflineVaultIdentity, previous: VerifiedLocalScope
): Promise<Existing[]> {
    const out: Existing[] = [];
    const seen = new Set<string>();
    for (const item of previous.envelope.payload.form_scopes) {
        if (!QUALITY_OPS.has(item.operation) || !QUALITY_FORMS.test(item.form_code)) continue;
        const pair = { machine_code: item.machine_code, form_code: item.form_code };
        if (seen.has(pairKey(pair))) continue;
        seen.add(pairKey(pair));
        let raw: StoredPackage | null;
        try { raw = await readRawPackage(identity, pair.machine_code, pair.form_code); }
        catch { throw new RenewalError("needs_recovery"); }   // malformed record under this key
        if (!raw) continue;
        let verified: VerifiedQualityDefinition | null = null;
        try { verified = await readQualityPackage(key, identity, previous, pair.machine_code, pair.form_code); }
        catch { verified = null; }
        out.push({ pair, raw, verified });
    }
    return out;
}

function mapScopeError(error: unknown): RenewalError {
    if (error instanceof ScopeError) {
        if (error.reason === "identity_mismatch") return new RenewalError("identity_mismatch");
        if (error.reason === "pin_mismatch") return new RenewalError("pin_mismatch");
    }
    return new RenewalError("invalid");
}
function mapPackageError(error: unknown): RenewalError {
    if (error instanceof QualityPackageError) {
        if (error.reason === "scope") return new RenewalError("incompatible");
        if (error.reason === "pin") return new RenewalError("pin_mismatch");
    }
    return new RenewalError("invalid");
}

type CommitPlan = Readonly<{
    profileId: string; identity: OfflineVaultIdentity; expectedScopeSnapshotId: string;
    /** Fingerprint of the sealed renewal marker observed when preparing (R2). */
    expectedRenewalFingerprint: string;
    scopeRecord: StoredScope; packageRecords: StoredPackage[]; expectedPackageIds: ReadonlyMap<string, string | null>;
}>;

/** ONE readwrite transaction. Either every record is replaced or none is. */
async function commit(plan: CommitPlan): Promise<void> {
    const db = await openProfileDb();
    try {
        await new Promise<void>((resolve, reject) => {
            const tx = db.transaction(["profiles", SCOPE_STORE_NAME, PACKAGE_STORE_NAME], "readwrite");
            let failure: RenewalError | undefined;
            const stop = (reason: RenewalReason) => {
                if (!failure) { failure = new RenewalError(reason, "commit"); try { tx.abort(); } catch { /* already finished */ } }
            };
            let pending = 2 + plan.packageRecords.length;
            const done = () => {
                pending -= 1;
                if (pending !== 0 || failure) return;
                const scopes = tx.objectStore(SCOPE_STORE_NAME), packages = tx.objectStore(PACKAGE_STORE_NAME);
                scopes.put(plan.scopeRecord);
                for (const record of plan.packageRecords) packages.put(record);
            };
            const profile = tx.objectStore("profiles").get(plan.profileId);
            profile.onsuccess = () => {
                const p = profile.result as { ownerId?: string; deviceKey?: string } | undefined;
                if (!p || p.ownerId !== plan.identity.ownerId.toLowerCase() ||
                    p.deviceKey !== plan.identity.deviceKey.toLowerCase()) { stop("identity_mismatch"); return; }
                done();
            };
            const scope = tx.objectStore(SCOPE_STORE_NAME).get(plan.profileId);
            scope.onsuccess = () => {
                const s = scope.result as StoredScope | undefined;
                // Compare-and-swap: another tab/renewal changed the scope since we prepared.
                // A different snapshot, or ANY change of the renewal marker (for example a revocation
                // recorded by another tab), means what we prepared is stale: abort, never overwrite.
                if (!s || !validStoredScope(s, plan.identity) || s.snapshotId !== plan.expectedScopeSnapshotId ||
                    markerFingerprint(s.renewal) !== plan.expectedRenewalFingerprint) {
                    stop("conflict"); return;
                }
                done();
            };
            for (const record of plan.packageRecords) {
                const prior = tx.objectStore(PACKAGE_STORE_NAME).get(record.packageKey);
                prior.onsuccess = () => {
                    const r = prior.result as StoredPackage | undefined;
                    const expected = plan.expectedPackageIds.get(record.packageKey) ?? null;
                    if (r !== undefined && !validPackageRecord(r, plan.identity, record.packageKey)) { stop("conflict"); return; }
                    if ((r?.packageId ?? null) !== expected) { stop("conflict"); return; }
                    done();
                };
            }
            tx.oncomplete = () => resolve();
            tx.onabort = () => reject(failure ?? new RenewalError("commit_failed", "commit"));
            tx.onerror = () => { if (!failure) failure = new RenewalError("commit_failed", "commit"); };
        });
    } finally { db.close(); }
}

/**
 * Renew the signed scope and every stored Quality package as ONE coherent set.
 * Preconditions: an online authenticated session (enforced by the injected fetchers)
 * and an unlocked vault key. On ANY failure nothing is replaced and the previous
 * encrypted set stays exactly as it was.
 */
export async function renewOfflineBundle(
    key: CryptoKey, identity: OfflineVaultIdentity, deps: RenewalDeps, options: RenewalOptions = {}
): Promise<RenewalResult> {
    const now = options.now ?? (() => new Date());
    // ---------------- PREPARE: no IndexedDB writes in this section ----------------
    const profile = await readLocalProfile().catch(() => { throw new RenewalError("storage"); });
    if (!profile || profile.ownerId !== identity.ownerId.toLowerCase() ||
        profile.deviceKey !== identity.deviceKey.toLowerCase()) throw new RenewalError("identity_mismatch");
    let rawScope: StoredScope | null;
    try { rawScope = await readRawScope(identity); } catch { throw new RenewalError("needs_recovery"); }
    if (!rawScope) throw new RenewalError("no_local_scope");
    const observedFingerprint = markerFingerprint(rawScope.renewal);

    let previous: VerifiedLocalScope | null = null;
    try { previous = await readOfflineScope(key, identity); } catch { previous = null; }

    const machines = options.machineCodes ??
        (previous ? [...new Set(previous.envelope.payload.form_scopes.map(x => x.machine_code))] : []);
    if (machines.length === 0 || machines.length > 25 || !machines.every(m => MACHINE.test(m))) {
        throw new RenewalError(previous ? "invalid" : "needs_recovery");
    }

    const scopeObservedAt = now();            // moment the online answer is about (orders revocation vs renewal)
    let envelope: unknown;
    try { envelope = await deps.fetchScope(machines); }
    catch (error) {
        const reason = classifyFetch(error);
        if (reason === "revoked") throw await refuse(key, identity, rawScope.profileId, scopeObservedAt);
        throw new RenewalError(reason);
    }

    const trusted = previous?.trustedPublicKey ?? (options.allowReplaceUnreadable === true &&
        typeof (envelope as { public_key_b64url?: unknown } | null)?.public_key_b64url === "string"
        ? (envelope as { public_key_b64url: string }).public_key_b64url : null);
    if (!trusted) throw new RenewalError("needs_recovery");
    let next: SignedOfflineScope;
    try { next = await verifyOfflineScope(envelope, trusted, identity); }
    catch (error) { throw mapScopeError(error); }

    if (previous) {
        const order = compareScopeFreshness(next, previous.envelope);
        if (order !== "newer" && order !== "identical") throw new RenewalError("rollback");
    }

    const existing = previous ? await enumerateExisting(key, identity, previous) : [];
    if (existing.some(e => e.verified === null) && options.allowReplaceUnreadable !== true) {
        throw new RenewalError("needs_recovery");
    }
    const extra = options.extraPairs ?? [];
    if (!extra.every(p => MACHINE.test(p.machine_code) && QUALITY_FORMS.test(p.form_code))) throw new RenewalError("invalid");
    const plan = planRenewalPairs(existing.map(e => e.pair), extra, next);
    if (plan.missingExtra.length > 0 || plan.renew.length > MAX_RENEWED_PACKAGES) throw new RenewalError("incompatible");

    const verifiedNew: VerifiedQualityDefinition[] = [];
    for (const pair of plan.renew) {
        const packageObservedAt = now();
        let packageEnvelope: unknown;
        try { packageEnvelope = await deps.fetchPackage(pair.machine_code, pair.form_code, next); }
        catch (error) {
            const reason = classifyFetch(error);
            if (reason === "revoked") throw await refuse(key, identity, rawScope.profileId, packageObservedAt);
            throw new RenewalError(reason);
        }
        let verified: VerifiedQualityDefinition;
        try { verified = await verifyQualityPackage(packageEnvelope, { envelope: next, trustedPublicKey: trusted }, identity); }
        catch (error) { throw mapPackageError(error); }
        const p = verified.envelope.payload;
        if (p.machine_code !== pair.machine_code || p.form_code !== pair.form_code) throw new RenewalError("invalid");
        const old = existing.find(e => pairKey(e.pair) === pairKey(pair))?.verified;
        if (old) {
            try { assertPackageProgression(old.envelope.payload, p); }
            catch { throw new RenewalError("rollback"); }
        }
        verifiedNew.push(verified);
    }

    // Encrypt EVERYTHING before touching storage; a failure here still leaves the old set intact.
    let scopeRecord: StoredScope, packageRecords: StoredPackage[];
    try {
        const base = await sealScopeRecord(key, identity, next, trusted);
        const marker = await sealMarker(key, identity, {
            schema: MARKER_SCHEMA, status: "renewed_online", snapshotId: next.payload.snapshot_id,
            issuedAt: next.payload.issued_at, recordedAt: scopeObservedAt.toISOString(),
        });
        scopeRecord = { ...base, schemaVersion: 2, renewal: marker };
        packageRecords = [];
        for (const verified of verifiedNew) packageRecords.push(await sealPackageRecord(key, identity, verified));
    } catch { throw new RenewalError("storage"); }

    const expected = new Map<string, string | null>();
    for (const record of packageRecords) expected.set(record.packageKey, null);
    for (const e of existing) expected.set(e.raw.packageKey, e.raw.packageId);

    // ---------------- COMMIT: a single IndexedDB transaction ----------------
    await commit({
        profileId: rawScope.profileId, identity, expectedScopeSnapshotId: rawScope.snapshotId,
        expectedRenewalFingerprint: observedFingerprint,
        scopeRecord, packageRecords, expectedPackageIds: expected,
    });
    // A refusal observed BEFORE this renewal's online answer is now superseded by it.
    clearUnrecordedRevocation(rawScope.profileId, scopeObservedAt.getTime());
    return {
        outcome: "renewed", snapshotId: next.payload.snapshot_id,
        renewedPackages: plan.renew, removedPairs: plan.removed,
        reduced: plan.removed.length > 0 || next.payload.form_scopes.length <
            (previous?.envelope.payload.form_scopes.length ?? 0),
    };
}

// ---------------------------------------------------------------------------
// Explicit recovery policy: nothing here runs automatically.
// ---------------------------------------------------------------------------
async function withSupersededScan<T>(
    identity: OfflineVaultIdentity, write: boolean,
    run: (stale: StoredPackage[], packages: IDBObjectStore) => T
): Promise<T> {
    const db = await openProfileDb();
    try {
        return await new Promise<T>((resolve, reject) => {
            const tx = db.transaction([SCOPE_STORE_NAME, PACKAGE_STORE_NAME], write ? "readwrite" : "readonly");
            let result: T | undefined;
            const scope = tx.objectStore(SCOPE_STORE_NAME).get(
                identity.ownerId.toLowerCase() + ":" + identity.deviceKey.toLowerCase());
            scope.onsuccess = () => {
                const s = scope.result as StoredScope | undefined;
                if (!s || !validStoredScope(s, identity)) { tx.abort(); return; }
                const all = tx.objectStore(PACKAGE_STORE_NAME).getAll();
                all.onsuccess = () => {
                    const stale = (all.result as unknown[]).filter((r): r is StoredPackage =>
                        typeof r === "object" && r !== null &&
                        (r as StoredPackage).ownerId === identity.ownerId.toLowerCase() &&
                        (r as StoredPackage).deviceKey === identity.deviceKey.toLowerCase() &&
                        (r as StoredPackage).scopeSnapshotId !== s.snapshotId);
                    result = run(stale, tx.objectStore(PACKAGE_STORE_NAME));
                };
            };
            tx.oncomplete = () => resolve(result as T);
            tx.onabort = () => reject(new RenewalError("storage"));
            tx.onerror = () => reject(new RenewalError("storage"));
        });
    } finally { db.close(); }
}

/** Encrypted packages that belong to an older snapshot and therefore cannot be read. */
export function countSupersededPackages(identity: OfflineVaultIdentity): Promise<number> {
    return withSupersededScan(identity, false, stale => stale.length);
}

/**
 * Operator-confirmed cleanup of packages bound to a superseded snapshot. Never called
 * by renewal or boot. Requires the exact confirmation token; the current set is untouched.
 */
export function discardSupersededPackages(identity: OfflineVaultIdentity, confirmation: string): Promise<number> {
    if (confirmation !== DISCARD_CONFIRMATION) return Promise.reject(new RenewalError("invalid"));
    return withSupersededScan(identity, true, (stale, packages) => {
        for (const record of stale) packages.delete(record.packageKey);
        return stale.length;
    });
}
