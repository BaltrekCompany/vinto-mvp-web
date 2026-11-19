/**
 * OFF-04.2 (LABORATORY ONLY): raw storage of SIMULATED local pending captures.
 *
 * STRUCTURAL ISOLATION from any future synchronisation engine:
 *  - a DIFFERENT IndexedDB database (`vinto-off04lab-queue-v1`), so code that opens the application's own
 *    offline database (the one a real sender would read) cannot even see these records;
 *  - a different object store, record type and status vocabulary (`queued_local_simulation`, never the real
 *    pending status), plus an explicit `lab` marker and `syncState: "NOT_SYNCED"`;
 *  - IMMUTABLE by construction: this module only ever ADDS records. There is no update, delete or clear.
 * It never touches the application's offline database, never calls a network API and never grants capture permission.
 */
export const LAB_QUEUE_DB = "vinto-off04lab-queue-v1";
export const LAB_QUEUE_STORE = "lab_pending";
export const LAB_STATUS = "queued_local_simulation";
const OWNER_INDEX = "ownerDevice";
const DRAFT_INDEX = "sourceDraft";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const B64URL = /^[A-Za-z0-9_-]+$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

export type LabPending = Readonly<{
    capture_id: string;
    draftId: string;
    ownerId: string;
    deviceKey: string;
    formCode: string;
    formVersion: number;
    contextId: string;
    sourceRevision: number;
    queuedAt: string;
    status: typeof LAB_STATUS;
    lab: true;
    syncState: "NOT_SYNCED";
    sealed: Readonly<{ format: "aes-gcm-v1"; iv: string; ciphertext: string }>;
}>;

export type LabQueueReason = "invalid" | "duplicate" | "quota" | "storage" | "unavailable";
export class LabQueueStoreError extends Error {
    readonly reason: LabQueueReason;
    constructor(reason: LabQueueReason) {
        super("OFFLINE_LAB_QUEUE_" + reason.toUpperCase());
        this.name = "LabQueueStoreError";
        this.reason = reason;
    }
}

const KEYS = ["capture_id", "draftId", "ownerId", "deviceKey", "formCode", "formVersion", "contextId", "sourceRevision",
    "queuedAt", "status", "lab", "syncState", "sealed"].sort().join("|");

export function isLabPending(value: unknown): value is LabPending {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const x = value as Record<string, unknown>;
    if (Object.keys(x).sort().join("|") !== KEYS) return false;
    if (![x.capture_id, x.draftId, x.ownerId, x.deviceKey, x.contextId].every(v => typeof v === "string" && UUID.test(v))) return false;
    if (typeof x.formCode !== "string" || !/^VINTO-[A-Z0-9-]{2,40}$/.test(x.formCode)) return false;
    if (!Number.isSafeInteger(x.formVersion) || (x.formVersion as number) < 1) return false;
    if (!Number.isSafeInteger(x.sourceRevision) || (x.sourceRevision as number) < 1) return false;
    if (typeof x.queuedAt !== "string" || !ISO.test(x.queuedAt)) return false;
    if (x.status !== LAB_STATUS || x.lab !== true || x.syncState !== "NOT_SYNCED") return false;
    const s = x.sealed as Record<string, unknown> | null;
    return !!s && typeof s === "object" && s.format === "aes-gcm-v1" && typeof s.iv === "string" && s.iv.length === 16 &&
        B64URL.test(s.iv) && typeof s.ciphertext === "string" && s.ciphertext.length >= 22 && B64URL.test(s.ciphertext);
}

function openDatabase(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new LabQueueStoreError("unavailable"));
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(LAB_QUEUE_DB, 1); } catch { reject(new LabQueueStoreError("unavailable")); return; }
        request.onupgradeneeded = () => {
            const db = request.result;
            if (db.objectStoreNames.contains(LAB_QUEUE_STORE)) return;
            const store = db.createObjectStore(LAB_QUEUE_STORE, { keyPath: "capture_id" });
            store.createIndex(OWNER_INDEX, ["ownerId", "deviceKey"], { unique: false });
            store.createIndex(DRAFT_INDEX, ["ownerId", "deviceKey", "draftId"], { unique: true });   // one pending per draft
        };
        request.onsuccess = () => { const db = request.result; db.onversionchange = () => db.close(); resolve(db); };
        request.onerror = () => reject(new LabQueueStoreError("storage"));
        request.onblocked = () => reject(new LabQueueStoreError("storage"));
    });
}

async function withDb<T>(run: (db: IDBDatabase) => Promise<T>): Promise<T> {
    const db = await openDatabase();
    try { return await run(db); } finally { db.close(); }
}

const reasonOf = (name: string | undefined): LabQueueReason =>
    name === "QuotaExceededError" ? "quota" : name === "ConstraintError" ? "duplicate" : "storage";

/**
 * Add ONE pending record in a single transaction. Resolves only after `oncomplete`; any failure
 * (duplicate capture id, duplicate draft, quota, injected fault) aborts and leaves the store untouched.
 */
export async function addLabPending(record: LabPending): Promise<void> {
    if (!isLabPending(record)) throw new LabQueueStoreError("invalid");
    return withDb(db => new Promise<void>((resolve, reject) => {
        let reason: LabQueueStoreError | null = null;
        let tx: IDBTransaction;
        try { tx = db.transaction(LAB_QUEUE_STORE, "readwrite"); } catch { reject(new LabQueueStoreError("storage")); return; }
        const fail = (name: string | undefined) => { reason = new LabQueueStoreError(reasonOf(name)); try { tx.abort(); } catch { /* done */ } };
        try {
            const request = tx.objectStore(LAB_QUEUE_STORE).add(record);
            request.onerror = () => { reason = new LabQueueStoreError(reasonOf(request.error?.name)); };
        } catch (error) { fail((error as DOMException)?.name); }
        tx.oncomplete = () => resolve();
        tx.onabort = () => reject(reason ?? new LabQueueStoreError(reasonOf(tx.error?.name)));
        tx.onerror = () => { if (!reason) reason = new LabQueueStoreError(reasonOf(tx.error?.name)); };
    }));
}

export async function getLabPendingByDraft(ownerId: string, deviceKey: string, draftId: string): Promise<LabPending | null> {
    if (![ownerId, deviceKey, draftId].every(v => UUID.test(v))) throw new LabQueueStoreError("invalid");
    return withDb(db => new Promise<LabPending | null>((resolve, reject) => {
        const tx = db.transaction(LAB_QUEUE_STORE, "readonly");
        const request = tx.objectStore(LAB_QUEUE_STORE).index(DRAFT_INDEX).get([ownerId, deviceKey, draftId]);
        request.onsuccess = () => {
            const row = request.result as unknown;
            if (row === undefined) { resolve(null); return; }
            if (!isLabPending(row)) { reject(new LabQueueStoreError("invalid")); return; }
            resolve(row);
        };
        request.onerror = () => reject(new LabQueueStoreError("storage"));
        tx.onabort = () => reject(new LabQueueStoreError("storage"));
    }));
}

export async function getLabPending(ownerId: string, deviceKey: string, captureId: string): Promise<LabPending | null> {
    if (![ownerId, deviceKey, captureId].every(v => UUID.test(v))) throw new LabQueueStoreError("invalid");
    return withDb(db => new Promise<LabPending | null>((resolve, reject) => {
        const tx = db.transaction(LAB_QUEUE_STORE, "readonly");
        const request = tx.objectStore(LAB_QUEUE_STORE).get(captureId);
        request.onsuccess = () => {
            const row = request.result as unknown;
            if (row === undefined) { resolve(null); return; }
            if (!isLabPending(row)) { reject(new LabQueueStoreError("invalid")); return; }
            resolve(row.ownerId === ownerId && row.deviceKey === deviceKey ? row : null);
        };
        request.onerror = () => reject(new LabQueueStoreError("storage"));
        tx.onabort = () => reject(new LabQueueStoreError("storage"));
    }));
}

/** Pending records of THIS owner+browser. Malformed rows are counted, never hidden and never altered. */
export async function listLabPending(ownerId: string, deviceKey: string): Promise<{ records: LabPending[]; malformed: number }> {
    if (![ownerId, deviceKey].every(v => UUID.test(v))) throw new LabQueueStoreError("invalid");
    return withDb(db => new Promise((resolve, reject) => {
        const tx = db.transaction(LAB_QUEUE_STORE, "readonly");
        const request = tx.objectStore(LAB_QUEUE_STORE).index(OWNER_INDEX).getAll([ownerId, deviceKey]);
        request.onsuccess = () => {
            const rows = request.result as unknown[];
            const records = rows.filter(isLabPending);
            resolve({ records, malformed: rows.length - records.length });
        };
        request.onerror = () => reject(new LabQueueStoreError("storage"));
        tx.onabort = () => reject(new LabQueueStoreError("storage"));
    }));
}
