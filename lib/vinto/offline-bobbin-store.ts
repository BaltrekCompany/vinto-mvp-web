/**
 * OFF-04.6 (LABORATORY): encrypted local store of BOBBIN CONTEXTS prepared online.
 *
 * A by-bobbin Quality draft belongs to one physical bobbin. The bobbin's historical context (code, machine, work order, line, PV, article, shift, operating date and the server's
 * digest) is read ONLINE with the signed scope (`/api/offline/bobbin-context`), sealed with the local vault and kept here so the user can pick it offline. It is a convenience
 * and a display aid: the authority stays with the server, which recomputes the context from its own database when the capture reconnects.
 *
 * Own database on purpose: the package store is swept by the scope renewal (OFF-03C.4) and must never see records of another kind.
 */
import { openLocalDraft, sealLocalDraft, VaultError, type OfflineVaultIdentity } from "./offline-vault.ts";
import { parseBobbinContext, DraftSchemaError, type BobbinContext } from "./offline-draft-schema.ts";
import type { SealedValues } from "./offline-store";

export const BOBBIN_DB_NAME = "vinto-off046-bobbin-contexts-v1";
const STORE = "contexts";
const OWNER_INDEX = "ownerDevice";
const VAULT_FORM = "VINTO-BOBBIN-CONTEXT";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Row = { id: string; ownerId: string; deviceKey: string; snapshotId: string; machineCode: string; bobbinId: string; sealed: SealedValues };
export class BobbinStoreError extends Error {
    readonly reason: "invalid" | "unavailable" | "storage" | "locked";
    constructor(reason: BobbinStoreError["reason"]) { super("OFFLINE_BOBBIN_STORE_" + reason.toUpperCase()); this.name = "BobbinStoreError"; this.reason = reason; }
}

function openDb(): Promise<IDBDatabase> {
    if (typeof indexedDB === "undefined") return Promise.reject(new BobbinStoreError("unavailable"));
    return new Promise((resolve, reject) => {
        let request: IDBOpenDBRequest;
        try { request = indexedDB.open(BOBBIN_DB_NAME, 1); } catch { reject(new BobbinStoreError("unavailable")); return; }
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" }).createIndex(OWNER_INDEX, ["ownerId", "deviceKey"]);
        };
        request.onerror = () => reject(new BobbinStoreError("unavailable"));
        request.onblocked = () => reject(new BobbinStoreError("unavailable"));
        request.onsuccess = () => { const db = request.result; db.onversionchange = () => db.close(); resolve(db); };
    });
}

const binding = (identity: OfflineVaultIdentity, row: Pick<Row, "bobbinId" | "snapshotId">) =>
    ({ ownerId: identity.ownerId, deviceKey: identity.deviceKey, id: row.bobbinId, contextId: row.snapshotId, formCode: VAULT_FORM, formVersion: 1 });
const rowId = (identity: OfflineVaultIdentity, snapshotId: string, bobbinId: string) =>
    [identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase(), snapshotId.toLowerCase(), bobbinId.toLowerCase()].join(":");

/** Store (or replace, idempotently) one bobbin context under the signed-scope snapshot it was prepared with. */
export async function storeBobbinContext(key: CryptoKey, identity: OfflineVaultIdentity, snapshotId: string, context: unknown): Promise<BobbinContext> {
    if (!UUID.test(identity.ownerId) || !UUID.test(identity.deviceKey) || !UUID.test(snapshotId)) throw new BobbinStoreError("invalid");
    let ctx: BobbinContext;
    try { ctx = parseBobbinContext(context); } catch { throw new BobbinStoreError("invalid"); }
    const row: Row = { id: rowId(identity, snapshotId, ctx.bobbin_id), ownerId: identity.ownerId.toLowerCase(), deviceKey: identity.deviceKey.toLowerCase(), snapshotId: snapshotId.toLowerCase(),
        machineCode: ctx.machine_code, bobbinId: ctx.bobbin_id.toLowerCase(), sealed: await sealLocalDraft(key, binding(identity, { bobbinId: ctx.bobbin_id, snapshotId }), ctx).catch(() => { throw new BobbinStoreError("storage"); }) };
    const db = await openDb();
    try {
        await new Promise<void>((resolve, reject) => {
            const tx = db.transaction(STORE, "readwrite");
            tx.objectStore(STORE).put(row);
            tx.oncomplete = () => resolve();
            tx.onerror = tx.onabort = () => reject(new BobbinStoreError("storage"));
        });
    } finally { db.close(); }
    return ctx;
}

/** The contexts prepared for this snapshot and machine (decrypted and strictly parsed). A damaged row is counted, never hidden and never fatal. */
export async function listBobbinContexts(key: CryptoKey, identity: OfflineVaultIdentity, snapshotId: string, machineCode: string): Promise<{ contexts: BobbinContext[]; damaged: number }> {
    const db = await openDb();
    let rows: Row[];
    try {
        rows = await new Promise<Row[]>((resolve, reject) => {
            const r = db.transaction(STORE, "readonly").objectStore(STORE).index(OWNER_INDEX).getAll([identity.ownerId.toLowerCase(), identity.deviceKey.toLowerCase()]);
            r.onsuccess = () => resolve(r.result as Row[]);
            r.onerror = () => reject(new BobbinStoreError("storage"));
        });
    } finally { db.close(); }
    const contexts: BobbinContext[] = [];
    let damaged = 0;
    for (const row of rows.filter(r => r.snapshotId === snapshotId.toLowerCase() && r.machineCode === machineCode).sort((a, b) => a.bobbinId.localeCompare(b.bobbinId))) {
        try {
            const ctx = parseBobbinContext(await openLocalDraft(key, binding(identity, row), row.sealed));
            if (ctx.bobbin_id.toLowerCase() !== row.bobbinId || ctx.machine_code !== row.machineCode) { damaged += 1; continue; }
            contexts.push(ctx);
        } catch (error) {
            if (error instanceof VaultError && error.reason === "unlock_failed") throw new BobbinStoreError("locked");
            if (!(error instanceof DraftSchemaError || error instanceof VaultError)) throw error;
            damaged += 1;
        }
    }
    return { contexts, damaged };
}
