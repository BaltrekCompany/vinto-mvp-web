/**
 * OFF-04.3 (LABORATORY ONLY): IndexedDB persistence of the synchronisation queue.
 *
 * Its own database (`vinto-off043-sync-lab-v1`): separate from the application's offline database and its send queue and
 * from the synthetic lab pending queue. Records are never deleted. `claim`/`finalize` are single transactions
 * (compare-and-swap with a lease), and resolve only after `oncomplete`.
 */
import { applyClaim, applyFinalize } from "./offline-sync-rules.ts";
import type { ClaimResult, FinalizePatch, SyncQueueStore, SyncRecord } from "./offline-sync-types.ts";

export const SYNC_LAB_DB = "vinto-off043-sync-lab-v1";
const STORE = "sync_queue", OWNER_INDEX = "ownerDevice";
export class SyncStoreError extends Error {
    readonly reason: "unavailable" | "invalid" | "storage" | "quota" | "duplicate_conflict";
    constructor(reason: SyncStoreError["reason"]) { super("OFFLINE_SYNC_STORE_" + reason.toUpperCase()); this.name = "SyncStoreError"; this.reason = reason; }
}

export { isSyncRecord } from "./offline-queue-record.ts";
import { isSyncRecord } from "./offline-queue-record.ts";

function open(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new SyncStoreError("unavailable"));
    return new Promise((resolve, reject) => {
        const r = indexedDB.open(SYNC_LAB_DB, 1);
        r.onupgradeneeded = () => {
            if (r.result.objectStoreNames.contains(STORE)) return;
            r.result.createObjectStore(STORE, { keyPath: "capture_id" }).createIndex(OWNER_INDEX, ["ownerId", "deviceKey"], { unique: false });
        };
        r.onsuccess = () => { r.result.onversionchange = () => r.result.close(); resolve(r.result); };
        r.onerror = () => reject(new SyncStoreError("storage")); r.onblocked = () => reject(new SyncStoreError("storage"));
    });
}
async function withDb<T>(run: (db: IDBDatabase) => Promise<T>): Promise<T> {
    const db = await open();
    try { return await run(db); } finally { db.close(); }
}
const reason = (name?: string): SyncStoreError => new SyncStoreError(name === "QuotaExceededError" ? "quota" : "storage");

/** One readwrite transaction on the queue; `body` computes the result from the current row; resolves after commit. */
function tx<T>(db: IDBDatabase, captureId: string, body: (current: unknown, put: (row: SyncRecord) => void) => T): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        let t: IDBTransaction;
        try { t = db.transaction(STORE, "readwrite"); } catch { reject(new SyncStoreError("storage")); return; }
        const store = t.objectStore(STORE);
        let result: T, fail: SyncStoreError | null = null, finished = false;
        const g = store.get(captureId);
        g.onsuccess = () => {
            try { result = body(g.result as unknown, (row) => { const p = store.put(row); p.onerror = () => { fail = reason(p.error?.name); }; }); }
            catch (error) { fail = error instanceof SyncStoreError ? error : reason((error as DOMException)?.name); try { t.abort(); } catch { /* done */ } }
        };
        g.onerror = () => { fail = reason(g.error?.name); };
        t.oncomplete = () => { finished = true; resolve(result); };
        t.onabort = () => { if (!finished) reject(fail ?? reason(t.error?.name)); };
    });
}

export function createIdbSyncStore(): SyncQueueStore {
    return {
        enqueue: (record) => withDb(db => tx(db, record.capture_id, (current, put) => {
            if (!isSyncRecord(record)) throw new SyncStoreError("invalid");
            if (current !== undefined) {
                if (!isSyncRecord(current)) throw new SyncStoreError("invalid");
                if (current.payloadSha256 !== record.payloadSha256 || current.ownerId !== record.ownerId) throw new SyncStoreError("duplicate_conflict");
                return { created: false, record: current };
            }
            put(record);
            return { created: true, record };
        })),
        get: (id) => withDb(db => new Promise<SyncRecord | null>((resolve, reject) => {
            const r = db.transaction(STORE, "readonly").objectStore(STORE).get(id);
            r.onsuccess = () => resolve(r.result === undefined ? null : isSyncRecord(r.result) ? r.result : (() => { reject(new SyncStoreError("invalid")); return null; })());
            r.onerror = () => reject(new SyncStoreError("storage"));
        })),
        list: (ownerId, deviceKey) => withDb(db => new Promise<SyncRecord[]>((resolve, reject) => {
            const r = db.transaction(STORE, "readonly").objectStore(STORE).index(OWNER_INDEX).getAll([ownerId, deviceKey]);
            r.onsuccess = () => {
                const rows = r.result as unknown[];
                if (rows.every(isSyncRecord)) resolve(rows as SyncRecord[]); else reject(new SyncStoreError("invalid"));
            };
            r.onerror = () => reject(new SyncStoreError("storage"));
        })),
        claim: (id, tabId, now, leaseMs): Promise<ClaimResult> => withDb(db => tx(db, id, (current, put) => {
            if (current === undefined) return null;
            if (!isSyncRecord(current)) throw new SyncStoreError("invalid");
            const next = applyClaim(current, tabId, now, leaseMs);
            if (!next) return null;
            put(next.record);
            return next;
        })),
        finalize: (id, tabId, patch: FinalizePatch, now) => withDb(db => tx(db, id, (current, put) => {
            if (current === undefined || !isSyncRecord(current)) return false;
            const next = applyFinalize(current, tabId, patch, now);
            if (!next) return false;
            put(next);
            return true;
        })),
    };
}
