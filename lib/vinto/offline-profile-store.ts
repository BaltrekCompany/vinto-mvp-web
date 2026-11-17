/**
 * VINTO OFF-03A -- local-only profile record.
 *
 * This store contains only the wrapped AES key and minimal owner/device IDs.
 * Never stores an auth cookie, password, plaintext draft, or server grant.
 * First registration must be explicitly authorized ONLINE by OFF-03B.
 */
import { isOfflineVaultRecord, type OfflineVaultRecord, VaultError } from "./offline-vault";

export const PROFILE_DB_NAME = "vinto-off03a-profiles-v1";
const PROFILE_DB_VERSION = 1;
const STORE_NAME = "profiles";

function openProfileDb(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new VaultError("unavailable"));
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(PROFILE_DB_NAME, PROFILE_DB_VERSION); }
        catch { reject(new VaultError("unavailable")); return; }
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: "profileId" });
        };
        request.onerror = () => reject(new VaultError("unavailable"));
        request.onblocked = () => reject(new VaultError("unavailable"));
        request.onsuccess = () => {
            const db = request.result;
            db.onversionchange = () => db.close();
            resolve(db);
        };
    });
}

function key(record: { ownerId: string; deviceKey: string }): string {
    return `${record.ownerId.toLowerCase()}:${record.deviceKey.toLowerCase()}`;
}

export async function storeLocalProfile(record: OfflineVaultRecord): Promise<void> {
    if (!isOfflineVaultRecord(record)) throw new VaultError("invalid");
    const db = await openProfileDb();
    try {
        return await new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, "readwrite");
            const bucket = tx.objectStore(STORE_NAME);
            let rejected: VaultError | undefined;
            // MVP policy: ONE operator per browser. No silent overwrite/rotation.
            const count = bucket.count();
            count.onsuccess = () => {
                if (count.result !== 0) {
                    rejected = new VaultError("invalid"); tx.abort(); return;
                }
                bucket.add({ profileId: key(record), ...record });
            };
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(rejected ?? new VaultError("unavailable"));
            tx.onabort = () => reject(rejected ?? new VaultError("unavailable"));
        });
    } finally { db.close(); }
}

/** Offline boot: exactly one enrolled profile per browser; otherwise fail closed. */
export async function readLocalProfile(): Promise<OfflineVaultRecord | null> {
    const db = await openProfileDb();
    try {
        return await new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, "readonly");
            const request = tx.objectStore(STORE_NAME).getAll();
            let records: unknown[] = [];
            request.onsuccess = () => { records = request.result; };
            tx.oncomplete = () => {
                if (records.length === 0) { resolve(null); return; }
                if (records.length !== 1) { reject(new VaultError("corrupt")); return; }
                const candidate = records[0];
                if (typeof candidate !== "object" || candidate === null
                    || !isOfflineVaultRecord(candidate)
                    || !("profileId" in candidate)
                    || candidate.profileId !== key(candidate)) {
                    reject(new VaultError("corrupt")); return;
                }
                resolve(candidate);
            };
            tx.onerror = () => reject(new VaultError("unavailable"));
            tx.onabort = () => reject(new VaultError("unavailable"));
        });
    } finally { db.close(); }
}
