/**
 * OFF-04.3 CI-only browser harness (bundled by scripts/off-03c4-build-harness.mjs, served from loopback).
 * Synthetic data and the in-memory FAKE server only. Not part of the app, never cached by the Service Worker.
 */
import { createLocalVault, unlockLocalVault, type OfflineVaultIdentity } from "../lib/vinto/offline-vault.ts";
import { readLocalProfile, storeLocalProfile } from "../lib/vinto/offline-profile-store.ts";
import { FakeSyncServer, type Fault } from "../lib/vinto/offline-sync-fake-server.ts";
import { syncNow } from "../lib/vinto/offline-sync-engine.ts";
import { createSyncCapture, openSyncPayload } from "../lib/vinto/offline-sync-capture.ts";
import { createIdbSyncStore, SYNC_LAB_DB } from "../lib/vinto/offline-sync-store.ts";
import { runSyncScenarios } from "./off-04-sync-scenarios.ts";

type Json = Record<string, unknown>;
let key: CryptoKey | null = null;
let identity: OfflineVaultIdentity | null = null;
const attempts: string[] = [];
const blocked = (name: string) => () => { attempts.push(name); throw new Error("network blocked by harness"); };
(globalThis as { fetch: unknown }).fetch = blocked("fetch");
(globalThis as { XMLHttpRequest: unknown }).XMLHttpRequest = function () { attempts.push("xhr"); throw new Error("blocked"); };
(navigator as { sendBeacon: unknown }).sendBeacon = () => { attempts.push("beacon"); return false; };
(globalThis as { WebSocket: unknown }).WebSocket = function () { attempts.push("websocket"); throw new Error("blocked"); };

const store = createIdbSyncStore();
let server = new FakeSyncServer({ sessionUser: null });
let sessionUser: string | null = null;
const originalPut = IDBObjectStore.prototype.put;
const wrap = async (fn: () => Promise<Json>): Promise<Json> => { try { return { ok: true, ...(await fn()) }; } catch (e) { return { ok: false, reason: String((e as Error)?.message ?? e) }; } };

async function rawRows(): Promise<Json[]> {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open(SYNC_LAB_DB, 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("o")); });
    try { return await new Promise<Json[]>((resolve, reject) => { const g = db.transaction("sync_queue").objectStore("sync_queue").getAll(); g.onsuccess = () => resolve(g.result as Json[]); g.onerror = () => reject(new Error("g")); }); }
    finally { db.close(); }
}

const H = {
    async enrol(id: OfflineVaultIdentity, passphrase: string): Promise<void> { const { record } = await createLocalVault(id, passphrase); await storeLocalProfile(record); },
    async unlock(passphrase: string): Promise<boolean> {
        const record = await readLocalProfile();
        if (!record) return false;
        try { key = await unlockLocalVault(record, passphrase); identity = { ownerId: record.ownerId, deviceKey: record.deviceKey }; sessionUser = record.ownerId; return true; }
        catch { key = null; return false; }
    },
    /** All engine scenarios against the REAL IndexedDB store in this browser. */
    runScenarios: () => runSyncScenarios({
        makeStore: () => createIdbSyncStore(),
        tamperHash: async (id: string) => {
            const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open(SYNC_LAB_DB, 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("o")); });
            try {
                await new Promise<void>((resolve, reject) => {
                    const tx = db.transaction("sync_queue", "readwrite"); const st = tx.objectStore("sync_queue"); const g = st.get(id);
                    g.onsuccess = () => { const row = g.result; row.payloadSha256 = "0".repeat(64); st.put(row); };
                    tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("t"));
                });
            } finally { db.close(); }
        },
        tamperCiphertext: async (id: string) => {
            const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open(SYNC_LAB_DB, 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("o")); });
            try {
                await new Promise<void>((resolve, reject) => {
                    const tx = db.transaction("sync_queue", "readwrite"); const st = tx.objectStore("sync_queue"); const g = st.get(id);
                    g.onsuccess = () => { const row = g.result; row.sealed.ciphertext = (row.sealed.ciphertext[0] === "A" ? "B" : "A") + row.sealed.ciphertext.slice(1); st.put(row); };
                    tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("t"));
                });
            } finally { db.close(); }
        },
    }),
    newServer: (faults: Fault[] = [], context = "ctx-1", delayMs = 0) => { server = new FakeSyncServer({ sessionUser, currentContext: context, delayMs }); server.script(...faults); },
    setSession: (user: string | null) => { sessionUser = user; server.sessionUser = user; },
    addMany: (n: number, from = 1) => wrap(async () => {
        const ids: string[] = [];
        for (let i = 0; i < n; i++) ids.push((await createSyncCapture(key!, identity!, store, { payload: { numero_de_cuba: "C-" + (from + i) + "-SINT" }, contextVersion: "ctx-1", seq: Date.now() * 1000 + from + i })).capture_id);
        return { ids };
    }),
    sync: (tab: string, timeoutMs = 3000) => wrap(async () => {
        const r = await syncNow({ store, transport: server.transport(), session: async () => sessionUser ? { userId: sessionUser } : null,
            openPayload: openSyncPayload(key!, identity!), identity: identity!, tabId: tab, options: { timeoutMs, baseDelayMs: 300, maxDelayMs: 2000, leaseMs: 30000, maxAttempts: 6 } });
        return { result: r as unknown as Json, accepted: [...server.accepted.keys()], sends: server.sendCount };
    }),
    startSync: (tab: string) => { (window as unknown as { __s: Promise<Json> }).__s = H.sync(tab); },
    list: () => wrap(async () => ({ rows: (await store.list(identity!.ownerId.toLowerCase(), identity!.deviceKey.toLowerCase())).map(r => ({ id: r.capture_id, state: r.state, attempts: r.attempts, uncertain: r.uncertain, hasLease: !!r.lease, serverRef: r.serverRef })) })),
    raw: async () => (await rawRows()) as unknown as Json[],
    /** claim the same record from this tab; used to race two real tabs on one IndexedDB */
    claimRace: (id: string, tab: string) => wrap(async () => ({ won: !!(await store.claim(id, tab, Date.now(), 30000)) })),
    failPutOn(n: number, name = "DataError"): void {
        let count = 0;
        IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore["put"]>) {
            count += 1; if (count === n) throw new DOMException("injected", name);
            return originalPut.apply(this, args);
        };
    },
    clearFaults(): void { IDBObjectStore.prototype.put = originalPut; },
    networkAttempts: () => attempts.slice(),
    serverSends: () => server.sendCount,
    serverAccepted: () => server.accepted.size,
};
Object.assign(globalThis, { H });
