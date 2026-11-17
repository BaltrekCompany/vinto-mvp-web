/**
 * OFF-02: IndexedDB structural foundation. It MUST NOT receive unencrypted production data.
 * Only opaque AES-GCM envelopes may be persisted. Key enrolment/decryption is OFF-03.
 * No automatic network access or permission decision belongs here.
 */
export const OFFLINE_DB_NAME = "vinto-offline-v1";
export const OFFLINE_DB_VERSION = 1;
export const OFFLINE_OWNER_INDEX = "ownerDevice";

export type SealedValues = Readonly<{
    format: "aes-gcm-v1";
    iv: string;         // base64url, 96-bit nonce, generated uniquely for each encryption
    ciphertext: string; // base64url, authenticated encryption output
}>;

export type OfflineDraft = Readonly<{
    id: string;
    ownerId: string;
    deviceKey: string;
    formCode: string;
    formVersion: number;
    contextId: string;
    savedAt: string;
    sealed: SealedValues;
}>;

export type OfflineOutbox = OfflineDraft & Readonly<{
    status: "queued";
    queuedAt: string;
}>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const B64URL = /^[A-Za-z0-9_-]+$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

export class OfflineStoreError extends Error {
    readonly reason: "unavailable" | "invalid" | "owner_mismatch" | "not_found" | "already_queued" | "storage_failed";
    constructor(reason: OfflineStoreError["reason"]) {
        super(`OFFLINE_STORE_${reason.toUpperCase()}`);
        this.reason = reason;
        this.name = "OfflineStoreError";
    }
}

function isDraft(value: unknown): value is OfflineDraft {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const x = value as Record<string, unknown>;
    if (![x.id, x.ownerId, x.deviceKey, x.contextId].every((v) => typeof v === "string" && UUID.test(v))) return false;
    if (typeof x.formCode !== "string" || !/^VINTO-[A-Z0-9-]{2,40}$/.test(x.formCode)) return false;
    if (typeof x.formVersion !== "number" || !Number.isSafeInteger(x.formVersion) || x.formVersion < 1) return false;
    if (typeof x.savedAt !== "string" || !ISO.test(x.savedAt)) return false;
    if (!x.sealed || typeof x.sealed !== "object" || Array.isArray(x.sealed)) return false;
    const sealed = x.sealed as Record<string, unknown>;
    return sealed.format === "aes-gcm-v1" && typeof sealed.iv === "string" && sealed.iv.length === 16
        && B64URL.test(sealed.iv) && typeof sealed.ciphertext === "string"
        && sealed.ciphertext.length >= 22 && B64URL.test(sealed.ciphertext);
}

function keyOk(ownerId: string, deviceKey: string, id?: string): boolean {
    return UUID.test(ownerId) && UUID.test(deviceKey) && (id === undefined || UUID.test(id));
}

function openDatabase(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new OfflineStoreError("unavailable"));
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION); }
        catch { reject(new OfflineStoreError("unavailable")); return; }
        request.onupgradeneeded = () => {
            const db = request.result;
            for (const name of ["drafts", "outbox"]) {
                if (db.objectStoreNames.contains(name)) continue;
                const store = db.createObjectStore(name, { keyPath: "id" });
                store.createIndex(OFFLINE_OWNER_INDEX, ["ownerId", "deviceKey"], { unique: false });
            }
        };
        request.onsuccess = () => {
            const db = request.result;
            db.onversionchange = () => db.close();
            resolve(db);
        };
        request.onerror = () => reject(new OfflineStoreError("storage_failed"));
        request.onblocked = () => reject(new OfflineStoreError("storage_failed"));
    });
}

async function withDb<T>(run: (db: IDBDatabase) => Promise<T>): Promise<T> {
    const db = await openDatabase();
    try { return await run(db); }
    finally { db.close(); }
}

function failed(): OfflineStoreError { return new OfflineStoreError("storage_failed"); }

export async function saveSealedDraft(draft: OfflineDraft): Promise<void> {
    if (!isDraft(draft)) throw new OfflineStoreError("invalid");
    return withDb((db) => new Promise((resolve, reject) => {
        const tx = db.transaction(["drafts", "outbox"], "readwrite");
        const drafts = tx.objectStore("drafts"), outbox = tx.objectStore("outbox");
        let reason: OfflineStoreError | null = null;
        const prior = drafts.get(draft.id);
        prior.onsuccess = () => {
            const existing = prior.result as OfflineDraft | undefined;
            if (existing && (existing.ownerId !== draft.ownerId || existing.deviceKey !== draft.deviceKey ||
                existing.contextId !== draft.contextId || existing.formCode !== draft.formCode ||
                existing.formVersion !== draft.formVersion)) {
                reason = new OfflineStoreError("owner_mismatch"); tx.abort(); return;
            }
            const queued = outbox.get(draft.id);
            queued.onsuccess = () => {
                if (queued.result !== undefined) {
                    reason = new OfflineStoreError("already_queued"); tx.abort(); return;
                }
                drafts.put(draft);
            };
        };
        tx.oncomplete = () => resolve();
        tx.onabort = () => reject(reason ?? failed());
        tx.onerror = () => reject(reason ?? failed());
    }));
}

export async function getSealedDraft(ownerId: string, deviceKey: string, id: string): Promise<OfflineDraft | null> {
    if (!keyOk(ownerId, deviceKey, id)) throw new OfflineStoreError("invalid");
    return withDb((db) => new Promise((resolve, reject) => {
        const tx = db.transaction("drafts", "readonly");
        const request = tx.objectStore("drafts").get(id);
        request.onsuccess = () => {
            const item = request.result as OfflineDraft | undefined;
            resolve(item && isDraft(item) && item.ownerId === ownerId && item.deviceKey === deviceKey ? item : null);
        };
        request.onerror = () => reject(failed());
        tx.onabort = () => reject(failed());
    }));
}

export async function listSealedDrafts(ownerId: string, deviceKey: string): Promise<OfflineDraft[]> {
    if (!keyOk(ownerId, deviceKey)) throw new OfflineStoreError("invalid");
    return withDb((db) => new Promise((resolve, reject) => {
        const tx = db.transaction("drafts", "readonly");
        const request = tx.objectStore("drafts").index(OFFLINE_OWNER_INDEX).getAll([ownerId, deviceKey]);
        request.onsuccess = () => {
            const values = request.result as unknown[];
            if (!values.every((item) => isDraft(item) && item.ownerId === ownerId && item.deviceKey === deviceKey)) {
                reject(new OfflineStoreError("invalid")); return;
            }
            resolve(values as OfflineDraft[]);
        };
        request.onerror = () => reject(failed());
        tx.onabort = () => reject(failed());
    }));
}

export async function queueSealedDraft(ownerId: string, deviceKey: string, id: string, queuedAt: string): Promise<void> {
    if (!keyOk(ownerId, deviceKey, id) || !ISO.test(queuedAt)) throw new OfflineStoreError("invalid");
    return withDb((db) => new Promise((resolve, reject) => {
        const tx = db.transaction(["drafts", "outbox"], "readwrite");
        let reason: OfflineStoreError | null = null;
        const drafts = tx.objectStore("drafts"), outbox = tx.objectStore("outbox");
        const read = drafts.get(id);
        read.onsuccess = () => {
            const item = read.result as OfflineDraft | undefined;
            if (!item) { reason = new OfflineStoreError("not_found"); tx.abort(); return; }
            if (!isDraft(item)) { reason = new OfflineStoreError("invalid"); tx.abort(); return; }
            if (item.ownerId !== ownerId || item.deviceKey !== deviceKey) { reason = new OfflineStoreError("owner_mismatch"); tx.abort(); return; }
            outbox.add({ ...item, status: "queued", queuedAt } satisfies OfflineOutbox);
            drafts.delete(id);
        };
        tx.oncomplete = () => resolve();
        tx.onabort = () => reject(reason ?? failed());
        tx.onerror = () => reject(reason ?? failed());
    }));
}

export async function listQueuedForOwner(ownerId: string, deviceKey: string): Promise<OfflineOutbox[]> {
    if (!keyOk(ownerId, deviceKey)) throw new OfflineStoreError("invalid");
    return withDb((db) => new Promise((resolve, reject) => {
        const tx = db.transaction("outbox", "readonly");
        const request = tx.objectStore("outbox").index(OFFLINE_OWNER_INDEX).getAll([ownerId, deviceKey]);
        request.onsuccess = () => {
            const values = request.result as unknown[];
            if (!values.every((item) => isDraft(item) && (item as OfflineOutbox).status === "queued"
                && (item as OfflineOutbox).ownerId === ownerId && (item as OfflineOutbox).deviceKey === deviceKey)) {
                reject(new OfflineStoreError("invalid")); return;
            }
            resolve(values as OfflineOutbox[]);
        };
        request.onerror = () => reject(failed());
        tx.onabort = () => reject(failed());
    }));
}

// Probe storage quota without claiming persistence was granted; may be undefined on older browsers.
export async function offlineStorageStatus(): Promise<{ supported: boolean; persisted: boolean | null; estimatedBytes: number | null }> {
    if (typeof indexedDB === "undefined" || typeof navigator === "undefined" || !navigator.storage) {
        return { supported: false, persisted: null, estimatedBytes: null };
    }
    let persisted: boolean | null = null, estimatedBytes: number | null = null;
    try { persisted = typeof navigator.storage.persisted === "function" ? await navigator.storage.persisted() : null; } catch { /* optional */ }
    try { estimatedBytes = typeof navigator.storage.estimate === "function" ? (await navigator.storage.estimate()).quota ?? null : null; } catch { /* optional */ }
    return { supported: true, persisted, estimatedBytes };
}

export async function requestOfflinePersistence(): Promise<boolean> {
    if (typeof navigator === "undefined" || typeof navigator.storage?.persist !== "function") return false;
    try { return await navigator.storage.persist(); }
    catch { return false; }
}
