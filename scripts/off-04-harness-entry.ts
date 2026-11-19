/**
 * OFF-04.1 CI-only browser harness (bundled by scripts/off-03c4-build-harness.mjs, served from loopback).
 * Synthetic data only. Not part of the app, never cached by the Service Worker.
 */
import { createLocalVault, unlockLocalVault, type OfflineVaultIdentity } from "../lib/vinto/offline-vault.ts";
import { openProfileDb, readLocalProfile, storeLocalProfile } from "../lib/vinto/offline-profile-store.ts";
import { readOfflineScope, storeOfflineScope, type VerifiedLocalScope } from "../lib/vinto/offline-scope-store.ts";
import { readQualityPackage, storeQualityPackage } from "../lib/vinto/offline-quality-store.ts";
import { renewOfflineBundle } from "../lib/vinto/offline-renewal.ts";
import type { VerifiedQualityDefinition } from "../lib/vinto/offline-quality-verify.ts";
import type { SignedOfflineScope } from "../lib/vinto/offline-scope-verify.ts";
import { DraftError, listQualityDrafts, loadQualityDraft, saveQualityDraft } from "../lib/vinto/offline-draft-store.ts";

type Json = Record<string, unknown>;
let key: CryptoKey | null = null;
let identity: OfflineVaultIdentity | null = null;
const MACHINE = "MP1", FORM = "VINTO-P1-26";
const attempts: string[] = [];

// Any attempt to reach a network API from the page is recorded (and made to fail).
const blocked = (name: string) => () => { attempts.push(name); throw new Error("network blocked by harness"); };
(globalThis as { fetch: unknown }).fetch = blocked("fetch");
(globalThis as { XMLHttpRequest: unknown }).XMLHttpRequest = function () { attempts.push("xhr"); throw new Error("blocked"); };
(navigator as { sendBeacon: unknown }).sendBeacon = () => { attempts.push("beacon"); return false; };
(globalThis as { WebSocket: unknown }).WebSocket = function () { attempts.push("websocket"); throw new Error("blocked"); };

async function context(): Promise<{ scope: VerifiedLocalScope; pkg: VerifiedQualityDefinition }> {
    const scope = await readOfflineScope(key!, identity!);
    if (!scope) throw new Error("no-scope");
    const pkg = await readQualityPackage(key!, identity!, scope, MACHINE, FORM);
    if (!pkg) throw new Error("no-package");
    return { scope, pkg };
}
async function dump(name: string): Promise<unknown[]> {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const r = indexedDB.open("vinto-offline-v1", 1);
        r.onupgradeneeded = () => { for (const n of ["drafts", "outbox"]) if (!r.result.objectStoreNames.contains(n)) r.result.createObjectStore(n, { keyPath: "id" }); };
        r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("open"));
    });
    try {
        return await new Promise<unknown[]>((resolve, reject) => {
            const q = db.transaction(name, "readonly").objectStore(name).getAll();
            q.onsuccess = () => resolve(q.result as unknown[]); q.onerror = () => reject(new Error("dump"));
        });
    } finally { db.close(); }
}
const wrap = async (fn: () => Promise<Json>): Promise<Json> => {
    try { return { ok: true, ...(await fn()) }; }
    catch (error) {
        if (error instanceof DraftError) return { ok: false, reason: error.reason, issues: error.issues.map(i => i.key + ":" + i.code) };
        return { ok: false, reason: "unexpected:" + String(error) };
    }
};

const originalPut = IDBObjectStore.prototype.put;
const originalEncrypt = crypto.subtle.encrypt.bind(crypto.subtle);

const H = {
    async enrol(id: OfflineVaultIdentity, passphrase: string): Promise<void> {
        const { record } = await createLocalVault(id, passphrase);
        await storeLocalProfile(record);
    },
    async unlock(passphrase: string): Promise<boolean> {
        const record = await readLocalProfile();
        if (!record) return false;
        try { key = await unlockLocalVault(record, passphrase); identity = { ownerId: record.ownerId, deviceKey: record.deviceKey }; return true; }
        catch { key = null; return false; }
    },
    useForeignKey: () => crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]).then(k => { key = k as CryptoKey; }),
    async seed(scope: SignedOfflineScope, pkg: unknown): Promise<void> {
        await storeOfflineScope(key!, identity!, scope, scope.public_key_b64url);
        await storeQualityPackage(key!, identity!, pkg);
    },
    async seedNonLab(scope: SignedOfflineScope, pkg: unknown): Promise<Json> {
        await H.seed(scope, pkg);
        const scopeNow = await readOfflineScope(key!, identity!);
        const p = await readQualityPackage(key!, identity!, scopeNow!, "MP1", "VINTO-P1-18");
        return wrap(() => saveQualityDraft(key!, identity!, { scope: scopeNow!, pkg: p! },
            { id: crypto.randomUUID(), values: {}, expectedRevision: null }).then(r => ({ ...r })));
    },
    async renewTo(scope: SignedOfflineScope, pkg: unknown): Promise<Json> {
        try {
            const r = await renewOfflineBundle(key!, identity!, {
                fetchScope: async () => scope, fetchPackage: async () => pkg }, {});
            return { ok: true, snapshotId: r.snapshotId };
        } catch (e) { return { ok: false, reason: String((e as { reason?: string }).reason ?? e) }; }
    },
    save: (id: string, values: Record<string, unknown>, expectedRevision: number | null, asIdentity?: OfflineVaultIdentity) =>
        wrap(async () => {
            const c = await context();
            const r = await saveQualityDraft(key!, asIdentity ?? identity!, c, { id, values, expectedRevision });
            return { ...r };
        }),
    load: (id: string, asIdentity?: OfflineVaultIdentity) =>
        wrap(async () => { const d = await loadQualityDraft(key!, asIdentity ?? identity!, id); return { revision: d.revision, values: d.payload.values as unknown as Json, payload: d.payload as unknown as Json }; }),
    list: (asIdentity?: OfflineVaultIdentity) =>
        wrap(async () => ({ items: (await listQualityDrafts(key!, asIdentity ?? identity!)) as unknown as Json[] })),
    rawDrafts: async () => JSON.stringify(await dump("drafts")),
    rawOutboxCount: async () => (await dump("outbox")).length,
    async tamper(id: string, kind: "ciphertext" | "outer_revision" | "outer_version" | "drop_revision"): Promise<void> {
        const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open("vinto-offline-v1", 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("o")); });
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = db.transaction("drafts", "readwrite"); const store = tx.objectStore("drafts"); const g = store.get(id);
                g.onsuccess = () => {
                    const row = g.result as { sealed: { ciphertext: string }; revision?: number; formVersion: number };
                    if (kind === "ciphertext") row.sealed.ciphertext = (row.sealed.ciphertext[0] === "A" ? "B" : "A") + row.sealed.ciphertext.slice(1);
                    if (kind === "outer_revision") row.revision = (row.revision ?? 1) + 5;
                    if (kind === "outer_version") row.formVersion += 1;
                    if (kind === "drop_revision") delete row.revision;
                    store.put(row);
                };
                tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("t"));
            });
        } finally { db.close(); }
    },
    /** Deterministic race: ANOTHER writer commits between this save's read and its transaction. */
    async raceSave(id: string, valuesB: Record<string, unknown>, expected: number | null, valuesA: Record<string, unknown>): Promise<Json> {
        let fired = false;
        (crypto.subtle as { encrypt: unknown }).encrypt = async (...args: Parameters<SubtleCrypto["encrypt"]>) => {
            if (!fired) { fired = true; await H.save(id, valuesA, expected); }
            return originalEncrypt(...args);
        };
        try { return await H.save(id, valuesB, expected); }
        finally { (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt; }
    },
    networkAttempts: () => attempts.slice(),
    failPutOn(n: number, name = "DataError"): void {
        let count = 0;
        IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore["put"]>) {
            count += 1; if (count === n) throw new DOMException("injected", name);
            return originalPut.apply(this, args);
        };
    },
    failEncryptOn(n: number): void {
        let count = 0;
        (crypto.subtle as { encrypt: unknown }).encrypt = (...args: Parameters<SubtleCrypto["encrypt"]>) => {
            count += 1; return count === n ? Promise.reject(new DOMException("injected", "OperationError")) : originalEncrypt(...args);
        };
    },
    clearFaults(): void { IDBObjectStore.prototype.put = originalPut; (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt; },
    profileDbOpen: () => openProfileDb().then(db => { db.close(); return true; }),
};
Object.assign(globalThis, { H });
