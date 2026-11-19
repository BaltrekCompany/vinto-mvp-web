/**
 * OFF-04.2-R2 (LABORATORY ONLY): the ONE consolidated IndexedDB of the synthetic laboratory.
 *
 * Synthetic drafts, simulated pendings and quarantine evidence live together here, so the draft→pending
 * transition and every draft save are single, serialisable IndexedDB transactions (no cross-database race).
 * It is isolated from the application's offline database and its send queue: a different database name,
 * different stores and a different status vocabulary. It never imports the application's offline store,
 * never calls a network API and never grants capture permission.
 *
 * Safety properties enforced here:
 *  - saves and the transition run in ONE transaction over `lab_drafts` + `lab_pending` (revision + ciphertext CAS);
 *  - a draft is FROZEN by a marker on its own row (`frozenBy`) in the same transaction that adds the pending, so
 *    tampering with either the pending or the marker never unblocks the draft silently;
 *  - pendings are immutable: the only write primitive on `lab_pending` is `add`;
 *  - loss/replacement of this database is detected through an epoch kept OUTSIDE it (fail closed, `lab_lost`).
 */
export const LAB_DB = "vinto-off04lab-v2";
export const LAB_EPOCH_KEY = "vinto-off04lab-epoch";
export const LAB_STATUS = "queued_local_simulation";
const S_DRAFTS = "lab_drafts", S_PENDING = "lab_pending", S_QUARANTINE = "lab_quarantine", S_META = "lab_meta";
const OWNER_INDEX = "ownerDevice", DRAFT_INDEX = "sourceDraft";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const B64URL = /^[A-Za-z0-9_-]+$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

export type Sealed = Readonly<{ format: "aes-gcm-v1"; iv: string; ciphertext: string }>;
export type LabDraftRow = Readonly<{
    id: string; ownerId: string; deviceKey: string; formCode: string; formVersion: number; contextId: string;
    savedAt: string; revision: number; sealed: Sealed; frozenBy?: string;
}>;
export type LabPending = Readonly<{
    capture_id: string; draftId: string; ownerId: string; deviceKey: string; formCode: string; formVersion: number;
    contextId: string; sourceRevision: number; queuedAt: string; status: typeof LAB_STATUS; lab: true;
    syncState: "NOT_SYNCED"; sealed: Sealed;
}>;
export type QuarantineRow = Readonly<{ id: string; source: string; reason: string; at: string; ownerId: string; deviceKey: string; raw: string }>;

export type LabDbReason =
    | "unavailable" | "storage" | "quota" | "conflict" | "pending_local" | "quarantined" | "not_found"
    | "owner_mismatch" | "invalid" | "lab_lost" | "lab_mismatch" | "duplicate";
export class LabDbError extends Error {
    readonly reason: LabDbReason;
    constructor(reason: LabDbReason) {
        super("OFFLINE_LAB_DB_" + reason.toUpperCase());
        this.name = "LabDbError";
        this.reason = reason;
    }
}

const isSealed = (s: unknown): s is Sealed => {
    const x = s as Record<string, unknown> | null;
    return !!x && typeof x === "object" && x.format === "aes-gcm-v1" && typeof x.iv === "string" && x.iv.length === 16 &&
        B64URL.test(x.iv) && typeof x.ciphertext === "string" && x.ciphertext.length >= 22 && B64URL.test(x.ciphertext);
};
const idsOk = (...v: unknown[]) => v.every(x => typeof x === "string" && UUID.test(x));

export function isLabDraftRow(value: unknown): value is LabDraftRow {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const x = value as Record<string, unknown>;
    const keys = Object.keys(x).sort().join("|");
    const base = ["contextId", "deviceKey", "formCode", "formVersion", "id", "ownerId", "revision", "savedAt", "sealed"];
    if (keys !== base.join("|") && keys !== [...base, "frozenBy"].sort().join("|")) return false;
    return idsOk(x.id, x.ownerId, x.deviceKey, x.contextId) && (x.frozenBy === undefined || idsOk(x.frozenBy)) &&
        typeof x.formCode === "string" && /^VINTO-[A-Z0-9-]{2,40}$/.test(x.formCode) &&
        Number.isSafeInteger(x.formVersion) && (x.formVersion as number) >= 1 && Number.isSafeInteger(x.revision) && (x.revision as number) >= 1 &&
        typeof x.savedAt === "string" && ISO.test(x.savedAt) && isSealed(x.sealed);
}

const PENDING_KEYS = ["capture_id", "draftId", "ownerId", "deviceKey", "formCode", "formVersion", "contextId", "sourceRevision",
    "queuedAt", "status", "lab", "syncState", "sealed"].sort().join("|");
export function isLabPending(value: unknown): value is LabPending {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const x = value as Record<string, unknown>;
    return Object.keys(x).sort().join("|") === PENDING_KEYS && idsOk(x.capture_id, x.draftId, x.ownerId, x.deviceKey, x.contextId) &&
        typeof x.formCode === "string" && /^VINTO-[A-Z0-9-]{2,40}$/.test(x.formCode) &&
        Number.isSafeInteger(x.formVersion) && (x.formVersion as number) >= 1 &&
        Number.isSafeInteger(x.sourceRevision) && (x.sourceRevision as number) >= 1 &&
        typeof x.queuedAt === "string" && ISO.test(x.queuedAt) && x.status === LAB_STATUS && x.lab === true &&
        x.syncState === "NOT_SYNCED" && isSealed(x.sealed);
}

// ---- epoch kept OUTSIDE the database: detects loss/replacement of ONLY this database ----
function readEpoch(): string | null {
    try { return localStorage.getItem(LAB_EPOCH_KEY); } catch { throw new LabDbError("unavailable"); }
}
function writeEpoch(value: string): void {
    try { localStorage.setItem(LAB_EPOCH_KEY, value); } catch { throw new LabDbError("unavailable"); }
}

const nameReason = (name: string | undefined): LabDbReason =>
    name === "QuotaExceededError" ? "quota" : name === "ConstraintError" ? "duplicate" : "storage";

function openLab(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new LabDbError("unavailable"));
    let epoch: string | null;
    try { epoch = readEpoch(); } catch (error) { return Promise.reject(error); }
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(LAB_DB, 1); } catch { reject(new LabDbError("unavailable")); return; }
        let refused: LabDbError | null = null;
        request.onupgradeneeded = (event) => {
            const db = request.result, tx = request.transaction as IDBTransaction;
            if ((event as IDBVersionChangeEvent).oldVersion !== 0) return;
            // A brand-new database while an epoch exists means the previous one was LOST: do NOT recreate it.
            if (epoch !== null) { refused = new LabDbError("lab_lost"); try { tx.abort(); } catch { /* done */ } return; }
            const drafts = db.createObjectStore(S_DRAFTS, { keyPath: "id" });
            drafts.createIndex(OWNER_INDEX, ["ownerId", "deviceKey"], { unique: false });
            const pending = db.createObjectStore(S_PENDING, { keyPath: "capture_id" });
            pending.createIndex(OWNER_INDEX, ["ownerId", "deviceKey"], { unique: false });
            pending.createIndex(DRAFT_INDEX, ["ownerId", "deviceKey", "draftId"], { unique: true });
            db.createObjectStore(S_QUARANTINE, { keyPath: "id" });
            const meta = db.createObjectStore(S_META, { keyPath: "key" });
            meta.put({ key: "instance", value: crypto.randomUUID() });
        };
        request.onerror = () => reject(refused ?? new LabDbError("storage"));
        request.onblocked = () => reject(new LabDbError("storage"));
        request.onsuccess = () => {
            const db = request.result;
            db.onversionchange = () => db.close();
            let get: IDBRequest;
            try { get = db.transaction(S_META, "readonly").objectStore(S_META).get("instance"); }
            catch { db.close(); reject(new LabDbError("lab_mismatch")); return; }
            get.onsuccess = () => {
                const instance = (get.result as { value?: unknown } | undefined)?.value;
                if (typeof instance !== "string" || !UUID.test(instance)) { db.close(); reject(new LabDbError("lab_mismatch")); return; }
                if (epoch !== null && epoch !== instance) { db.close(); reject(new LabDbError("lab_mismatch")); return; }
                if (epoch === null) { try { writeEpoch(instance); } catch (error) { db.close(); reject(error); return; } }
                resolve(db);
            };
            get.onerror = () => { db.close(); reject(new LabDbError("storage")); };
        };
    });
}

async function withLab<T>(run: (db: IDBDatabase) => Promise<T>): Promise<T> {
    const db = await openLab();
    try { return await run(db); } finally { db.close(); }
}

/** Run one readwrite transaction; resolves only after `oncomplete`. `body` may call `stop(reason)` to abort. */
function writeTx<T>(db: IDBDatabase, stores: string[], body: (tx: IDBTransaction, stop: (r: LabDbReason) => void, done: (v: T) => void) => void): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        let tx: IDBTransaction;
        try { tx = db.transaction(stores, "readwrite"); } catch { reject(new LabDbError("storage")); return; }
        let reason: LabDbError | null = null, value: T | undefined, finished = false;
        const stop = (r: LabDbReason) => { if (!reason) reason = new LabDbError(r); try { tx.abort(); } catch { /* done */ } };
        tx.oncomplete = () => { finished = true; resolve(value as T); };
        tx.onabort = () => { if (!finished) reject(reason ?? new LabDbError(nameReason(tx.error?.name))); };
        tx.onerror = () => { if (!reason) reason = new LabDbError(nameReason(tx.error?.name)); };
        try { body(tx, stop, v => { value = v; }); } catch (error) { stop(nameReason((error as DOMException)?.name)); }
    });
}

const reqOk = <T>(r: IDBRequest<T>, then: (v: T) => void, stop: (r: LabDbReason) => void) => {
    r.onsuccess = () => { try { then(r.result); } catch (error) { stop(nameReason((error as DOMException)?.name)); } };
    r.onerror = () => stop(nameReason(r.error?.name));
};

/** Attach handlers to TWO already-issued requests immediately (a handler attached later would miss its event). */
function pair(a: IDBRequest | null, b: IDBRequest, then: (a: unknown, b: unknown) => void, stop: (r: LabDbReason) => void): void {
    let ra: unknown, rb: unknown, pending = a ? 2 : 1;
    const arrive = () => { pending -= 1; if (pending === 0) { try { then(ra, rb); } catch (error) { stop(nameReason((error as DOMException)?.name)); } } };
    if (a) { a.onsuccess = () => { ra = a.result; arrive(); }; a.onerror = () => stop(nameReason(a.error?.name)); }
    b.onsuccess = () => { rb = b.result; arrive(); };
    b.onerror = () => stop(nameReason(b.error?.name));
}

// ---- drafts ----
export async function getLabDraft(ownerId: string, deviceKey: string, id: string): Promise<LabDraftRow | null> {
    if (!idsOk(ownerId, deviceKey, id)) throw new LabDbError("invalid");
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_DRAFTS, "readonly");
        const r = tx.objectStore(S_DRAFTS).get(id);
        r.onsuccess = () => {
            const row = r.result as unknown;
            if (row === undefined) { resolve(null); return; }
            if (!isLabDraftRow(row)) { reject(new LabDbError("invalid")); return; }
            resolve(row.ownerId === ownerId && row.deviceKey === deviceKey ? row : null);
        };
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

export async function listLabDrafts(ownerId: string, deviceKey: string): Promise<LabDraftRow[]> {
    if (!idsOk(ownerId, deviceKey)) throw new LabDbError("invalid");
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_DRAFTS, "readonly");
        const r = tx.objectStore(S_DRAFTS).index(OWNER_INDEX).getAll([ownerId, deviceKey]);
        r.onsuccess = () => {
            const rows = r.result as unknown[];
            if (!rows.every(x => isLabDraftRow(x) && x.ownerId === ownerId && x.deviceKey === deviceKey)) { reject(new LabDbError("invalid")); return; }
            resolve(rows as LabDraftRow[]);
        };
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

/** Why a draft is frozen: a valid pending for it, or damaged evidence (never an unlock). */
function frozenReason(draft: LabDraftRow | undefined, pendingByKey: unknown, pendingByDraft: unknown): LabDbReason | null {
    const valid = (p: unknown, d: LabDraftRow | undefined) => isLabPending(p) && (!d || (p.draftId === d.id && p.ownerId === d.ownerId && p.deviceKey === d.deviceKey));
    if (draft?.frozenBy !== undefined) return valid(pendingByKey, draft) && (pendingByKey as LabPending).capture_id === draft.frozenBy ? "pending_local" : "quarantined";
    if (pendingByDraft !== undefined) return isLabPending(pendingByDraft) ? "pending_local" : "quarantined";
    return null;
}

/**
 * Compare-and-swap save of ONE draft, in ONE transaction over drafts+pendings. A frozen draft (marker or any
 * pending bound to it) is refused. `expectedRevision` null = brand new draft.
 */
export async function saveLabDraftRevision(draft: LabDraftRow, expectedRevision: number | null): Promise<void> {
    if (!isLabDraftRow(draft) || draft.frozenBy !== undefined ||
        (expectedRevision !== null && (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1)) ||
        draft.revision !== (expectedRevision === null ? 1 : expectedRevision + 1)) throw new LabDbError("invalid");
    return withLab(db => writeTx<void>(db, [S_DRAFTS, S_PENDING], (tx, stop) => {
        const drafts = tx.objectStore(S_DRAFTS), pending = tx.objectStore(S_PENDING);
        reqOk(drafts.get(draft.id), (raw) => {
            const existing = raw as LabDraftRow | undefined;
            if (existing !== undefined && !isLabDraftRow(existing)) { stop("invalid"); return; }
            if (existing && (existing.ownerId !== draft.ownerId || existing.deviceKey !== draft.deviceKey || existing.contextId !== draft.contextId ||
                existing.formCode !== draft.formCode || existing.formVersion !== draft.formVersion)) { stop("owner_mismatch"); return; }
            const byKey = existing?.frozenBy !== undefined ? pending.get(existing.frozenBy) : null;
            const byDraft = pending.index(DRAFT_INDEX).get([draft.ownerId, draft.deviceKey, draft.id]);
            const proceed = (k: unknown, d: unknown) => {
                const why = frozenReason(existing, k, d);
                if (why) { stop(why); return; }
                if (existing ? existing.revision !== expectedRevision : expectedRevision !== null) { stop("conflict"); return; }
                drafts.put(draft);
            };
            pair(byKey, byDraft, (k, d) => proceed(k, d), stop);
        }, stop);
    }));
}

// ---- pendings ----
export async function getLabPending(ownerId: string, deviceKey: string, captureId: string): Promise<LabPending | null> {
    if (!idsOk(ownerId, deviceKey, captureId)) throw new LabDbError("invalid");
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_PENDING, "readonly");
        const r = tx.objectStore(S_PENDING).get(captureId);
        r.onsuccess = () => {
            const row = r.result as unknown;
            if (row === undefined) { resolve(null); return; }
            if (!isLabPending(row)) { reject(new LabDbError("quarantined")); return; }
            resolve(row.ownerId === ownerId && row.deviceKey === deviceKey ? row : null);
        };
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

export type TransitionInput = Readonly<{ ownerId: string; deviceKey: string; draftId: string; expectedRevision: number; expectedCiphertext: string; record: LabPending }>;
export type TransitionResult = Readonly<{ created: boolean; pending: LabPending }>;

/**
 * draft → pending in ONE transaction: verifies the draft is still exactly the (revision, ciphertext) that was
 * sealed, not frozen and has no pending; adds the immutable pending and marks the draft frozen. Repeating it is
 * idempotent (returns the existing pending); any divergence is `conflict`; damaged evidence is `quarantined`.
 */
export async function transitionLabDraft(input: TransitionInput): Promise<TransitionResult> {
    const rec = input.record;
    if (!isLabPending(rec) || rec.draftId !== input.draftId || rec.ownerId !== input.ownerId || rec.deviceKey !== input.deviceKey ||
        rec.sourceRevision !== input.expectedRevision) throw new LabDbError("invalid");
    return withLab(db => writeTx<TransitionResult>(db, [S_DRAFTS, S_PENDING], (tx, stop, done) => {
        const drafts = tx.objectStore(S_DRAFTS), pending = tx.objectStore(S_PENDING);
        reqOk(drafts.get(input.draftId), (raw) => {
            if (raw === undefined) { stop("not_found"); return; }
            if (!isLabDraftRow(raw)) { stop("invalid"); return; }
            const draft = raw;
            if (draft.ownerId !== input.ownerId || draft.deviceKey !== input.deviceKey) { stop("owner_mismatch"); return; }
            const byKey = draft.frozenBy !== undefined ? pending.get(draft.frozenBy) : null;
            const byDraft = pending.index(DRAFT_INDEX).get([input.ownerId, input.deviceKey, input.draftId]);
            const proceed = (k: unknown, d: unknown) => {
                const why = frozenReason(draft, k, d);
                if (why === "quarantined") { stop("quarantined"); return; }
                if (why === "pending_local") {                       // idempotent repeat of the SAME transition
                    const existing = (draft.frozenBy !== undefined ? k : d) as LabPending;
                    if (existing.sourceRevision !== input.expectedRevision) { stop("conflict"); return; }
                    done({ created: false, pending: existing });
                    return;
                }
                if (draft.revision !== input.expectedRevision || draft.sealed.ciphertext !== input.expectedCiphertext) { stop("conflict"); return; }
                const addRequest = pending.add(rec);
                addRequest.onerror = () => stop(nameReason(addRequest.error?.name));
                drafts.put({ ...draft, frozenBy: rec.capture_id });
                done({ created: true, pending: rec });
            };
            pair(byKey, byDraft, (k, d) => proceed(k, d), stop);
        }, stop);
    }));
}

/** All pending rows split into valid and malformed (malformed ones are evidence: reported, never removed). */
export async function readAllPending(): Promise<{ valid: LabPending[]; malformed: { captureId: string }[] }> {
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_PENDING, "readonly");
        const r = tx.objectStore(S_PENDING).getAll();
        r.onsuccess = () => {
            const rows = r.result as Record<string, unknown>[];
            resolve({ valid: rows.filter(isLabPending) as LabPending[],
                malformed: rows.filter(x => !isLabPending(x)).map(x => ({ captureId: typeof x?.capture_id === "string" ? x.capture_id : "?" })) });
        };
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

export async function readQuarantine(): Promise<QuarantineRow[]> {
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_QUARANTINE, "readonly");
        const r = tx.objectStore(S_QUARANTINE).getAll();
        r.onsuccess = () => resolve(r.result as QuarantineRow[]);
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

export async function readMeta(key: string): Promise<unknown> {
    return withLab(db => new Promise((resolve, reject) => {
        const tx = db.transaction(S_META, "readonly");
        const r = tx.objectStore(S_META).get(key);
        r.onsuccess = () => resolve((r.result as { value?: unknown } | undefined)?.value);
        r.onerror = () => reject(new LabDbError("storage"));
        tx.onabort = () => reject(new LabDbError("storage"));
    }));
}

export type MigrationBatch = Readonly<{
    metaKey: string; metaValue: unknown; drafts: readonly LabDraftRow[]; pendings: readonly LabPending[]; quarantine: readonly QuarantineRow[];
}>;
export type MigrationOutcome = Readonly<{ addedDrafts: number; addedPendings: number; skippedIdentical: number; conflicts: number }>;

/**
 * Commit a verified legacy batch in ONE transaction. Add-only: an existing row is never overwritten; an
 * identical one is skipped, a different one is recorded as quarantine evidence. The marker is written in the
 * same transaction, so the batch is all-or-nothing and a second run is a no-op.
 */
export async function commitMigrationBatch(batch: MigrationBatch): Promise<MigrationOutcome | "already_migrated"> {
    return withLab(db => writeTx<MigrationOutcome | "already_migrated">(db, [S_DRAFTS, S_PENDING, S_QUARANTINE, S_META], (tx, stop, done) => {
        const drafts = tx.objectStore(S_DRAFTS), pending = tx.objectStore(S_PENDING), quarantine = tx.objectStore(S_QUARANTINE), meta = tx.objectStore(S_META);
        let outcome = { addedDrafts: 0, addedPendings: 0, skippedIdentical: 0, conflicts: 0 };
        const evidence = (row: QuarantineRow) => {
            const q = quarantine.add(row);
            q.onerror = (e) => { e.preventDefault(); e.stopPropagation(); };   // an identical evidence id already exists
        };
        reqOk(meta.get(batch.metaKey), (existing) => {
            if (existing !== undefined) { done("already_migrated"); return; }
            const pendingById = new Map(batch.pendings.map(p => [p.capture_id, p]));
            let waiting = batch.drafts.length + batch.pendings.length;
            const finish = () => {
                waiting -= 1;
                if (waiting > 0) return;
                for (const q of batch.quarantine) evidence(q);
                const put = meta.add({ key: batch.metaKey, value: batch.metaValue });
                put.onerror = () => stop(nameReason(put.error?.name));
                done(outcome);
            };
            if (waiting === 0) { waiting = 1; finish(); return; }
            for (const d of batch.drafts) {
                reqOk(drafts.get(d.id), (cur) => {
                    const row: LabDraftRow = d.frozenBy === undefined && [...pendingById.values()].some(p => p.draftId === d.id)
                        ? { ...d, frozenBy: [...pendingById.values()].find(p => p.draftId === d.id)!.capture_id } : d;
                    if (cur === undefined) {
                        const a = drafts.add(row); a.onerror = () => stop(nameReason(a.error?.name)); outcome = { ...outcome, addedDrafts: outcome.addedDrafts + 1 };
                    } else if ((cur as LabDraftRow).sealed?.ciphertext === d.sealed.ciphertext) {
                        outcome = { ...outcome, skippedIdentical: outcome.skippedIdentical + 1 };
                    } else {
                        evidence({ id: "conflict-draft-" + d.id, source: "legacy_draft", reason: "migration_conflict", at: new Date().toISOString(),
                            ownerId: d.ownerId, deviceKey: d.deviceKey, raw: JSON.stringify(d) });
                        outcome = { ...outcome, conflicts: outcome.conflicts + 1 };
                    }
                    finish();
                }, stop);
            }
            for (const p of batch.pendings) {
                reqOk(pending.get(p.capture_id), (cur) => {
                    if (cur === undefined) {
                        const a = pending.add(p); a.onerror = () => stop(nameReason(a.error?.name)); outcome = { ...outcome, addedPendings: outcome.addedPendings + 1 };
                    } else if ((cur as LabPending).sealed?.ciphertext === p.sealed.ciphertext) {
                        outcome = { ...outcome, skippedIdentical: outcome.skippedIdentical + 1 };
                    } else {
                        evidence({ id: "conflict-pending-" + p.capture_id, source: "legacy_pending", reason: "migration_conflict", at: new Date().toISOString(),
                            ownerId: p.ownerId, deviceKey: p.deviceKey, raw: JSON.stringify(p) });
                        outcome = { ...outcome, conflicts: outcome.conflicts + 1 };
                    }
                    finish();
                }, stop);
            }
        }, stop);
    }));
}
