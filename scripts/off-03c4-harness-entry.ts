/**
 * OFF-03C.4 CI-only browser harness. It is bundled by scripts/off-03c4-build-harness.mjs
 * into a throwaway script that Playwright serves from loopback; it is NOT part of the app,
 * is never cached by the Service Worker and contains only synthetic-data helpers.
 */
import { createLocalVault, unlockLocalVault, type OfflineVaultIdentity } from "../lib/vinto/offline-vault.ts";
import { openProfileDb, PACKAGE_STORE_NAME, readLocalProfile, SCOPE_STORE_NAME, storeLocalProfile } from "../lib/vinto/offline-profile-store.ts";
import { readOfflineScope, storeOfflineScope } from "../lib/vinto/offline-scope-store.ts";
import { readQualityPackage, storeQualityPackage } from "../lib/vinto/offline-quality-store.ts";
import {
    countSupersededPackages, discardSupersededPackages, readRenewalStatus, renewOfflineBundle,
    RenewalError, type RenewalOptions,
} from "../lib/vinto/offline-renewal.ts";
import type { SignedOfflineScope } from "../lib/vinto/offline-scope-verify.ts";

type Json = Record<string, unknown>;
type FetchSpec = {
    envelope?: unknown; status?: number; network?: boolean; hang?: boolean;
    /** Deterministic interleaving: run ANOTHER complete renewal (a second tab) before this answer returns. */
    interleave?: Plan;
};
type Plan = { scope: FetchSpec; packages: Record<string, FetchSpec> };

let key: CryptoKey | null = null;
let identity: OfflineVaultIdentity | null = null;

const sleepForever = (): Promise<never> => new Promise<never>(() => { /* interrupted renewal */ });
async function outcome(spec: FetchSpec | undefined): Promise<unknown> {
    if (!spec) throw Object.assign(new Error("no-fixture"));
    if (spec.interleave) await runRenew(spec.interleave, {});
    if (spec.hang) return sleepForever();
    if (spec.network) return Promise.reject(new TypeError("network"));
    if (spec.status !== undefined) return Promise.reject(Object.assign(new Error("http"), { status: spec.status }));
    return Promise.resolve(spec.envelope);
}

async function dumpStore(name: string): Promise<unknown[]> {
    const db = await openProfileDb();
    try {
        return await new Promise<unknown[]>((resolve, reject) => {
            const request = db.transaction(name, "readonly").objectStore(name).getAll();
            request.onsuccess = () => resolve(request.result as unknown[]);
            request.onerror = () => reject(new Error("dump"));
        });
    } finally { db.close(); }
}

async function runRenew(plan: Plan, options: Partial<{ allowReplaceUnreadable: boolean; asIdentity: OfflineVaultIdentity }>): Promise<Json> {
    const who = options.asIdentity ?? identity!;
    const opts: RenewalOptions = { allowReplaceUnreadable: options.allowReplaceUnreadable === true };
    try {
        const result = await renewOfflineBundle(key!, who, {
            fetchScope: () => outcome(plan.scope),
            fetchPackage: (machine, form) => outcome(plan.packages[machine + "|" + form]),
        }, opts);
        return { ok: true, ...result } as Json;
    } catch (error) {
        if (error instanceof RenewalError) return { ok: false, reason: error.reason, stage: error.stage };
        return { ok: false, reason: "unexpected:" + String(error) };
    }
}

const originalPut = IDBObjectStore.prototype.put;
const originalSetItem = Storage.prototype.setItem;
const originalTransaction = IDBDatabase.prototype.transaction;
const originalEncrypt = crypto.subtle.encrypt.bind(crypto.subtle);

const H = {
    async enrol(id: OfflineVaultIdentity, passphrase: string): Promise<void> {
        const { record } = await createLocalVault(id, passphrase);
        await storeLocalProfile(record);
        identity = id;
    },
    async unlock(passphrase: string): Promise<boolean> {
        const record = await readLocalProfile();
        if (!record) return false;
        try { key = await unlockLocalVault(record, passphrase); identity = { ownerId: record.ownerId, deviceKey: record.deviceKey }; return true; }
        catch { key = null; return false; }
    },
    useForeignKey(): Promise<void> {
        return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"])
            .then(k => { key = k as CryptoKey; });
    },
    async seed(scope: SignedOfflineScope, packages: unknown[]): Promise<void> {
        await storeOfflineScope(key!, identity!, scope, scope.public_key_b64url);
        for (const p of packages) await storeQualityPackage(key!, identity!, p);
    },
    renew(plan: Plan, options: Partial<{ allowReplaceUnreadable: boolean; asIdentity: OfflineVaultIdentity }> = {}): Promise<Json> {
        return runRenew(plan, options);
    },
    async view(): Promise<Json> {
        let scopeInfo: Json | null = null;
        const packages: Json[] = [];
        let error: string | null = null;
        try {
            const scope = await readOfflineScope(key!, identity!);
            if (scope) {
                scopeInfo = { snapshotId: scope.envelope.payload.snapshot_id, issuedAt: scope.envelope.payload.issued_at,
                    pairs: scope.envelope.payload.form_scopes.map(x => x.machine_code + "|" + x.form_code + "|v" + x.form_version) };
                for (const item of scope.envelope.payload.form_scopes) {
                    try {
                        const p = await readQualityPackage(key!, identity!, scope, item.machine_code, item.form_code);
                        if (p) packages.push({ pair: item.machine_code + "|" + item.form_code,
                            version: p.envelope.payload.form_version,
                            label: p.envelope.payload.definition.fields[0].label,
                            snapshot: p.envelope.payload.scope_snapshot_id });
                    } catch { packages.push({ pair: item.machine_code + "|" + item.form_code, unreadable: true }); }
                }
            }
        } catch (e) { error = String(e); }
        const status = await readRenewalStatus(key!, identity!).catch(() => null);
        return { scope: scopeInfo, packages, status: status?.status ?? null,
            durable: (status as unknown as { durable?: boolean } | null)?.durable ?? null, error };
    },
    async rawSnapshot(): Promise<string> {
        return JSON.stringify({ scopes: await dumpStore(SCOPE_STORE_NAME), packages: await dumpStore(PACKAGE_STORE_NAME) });
    },
    async rawCounts(): Promise<Json> {
        return { scopes: (await dumpStore(SCOPE_STORE_NAME)).length, packages: (await dumpStore(PACKAGE_STORE_NAME)).length };
    },
    superseded: () => countSupersededPackages(identity!),
    discard: (token: string) => discardSupersededPackages(identity!, token).then(n => ({ ok: true, n }), (e: unknown) => ({ ok: false, reason: (e as RenewalError).reason })),
    async corruptFirstPackage(): Promise<void> {
        const db = await openProfileDb();
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = db.transaction(PACKAGE_STORE_NAME, "readwrite");
                const store = tx.objectStore(PACKAGE_STORE_NAME);
                const all = store.getAll();
                all.onsuccess = () => {
                    const row = (all.result as { sealed: { ciphertext: string } }[])[0];
                    const text = row.sealed.ciphertext;
                    row.sealed.ciphertext = (text[0] === "A" ? "B" : "A") + text.slice(1);
                    store.put(row);
                };
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(new Error("corrupt"));
            });
        } finally { db.close(); }
    },
    /** Fault injection (testing only). */
    failPutOn(n: number, errorName = "DataError"): void {
        let count = 0;
        IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore["put"]>) {
            count += 1;
            if (count === n) throw new DOMException("injected", errorName);
            return originalPut.apply(this, args);
        };
    },
    spinAfterFirstPut(ms: number): void {
        let count = 0;
        IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore["put"]>) {
            const request = originalPut.apply(this, args);
            count += 1;
            if (count === 1) { const end = Date.now() + ms; while (Date.now() < end) { /* hold the transaction open */ } }
            return request;
        };
    },
    failEncryptOn(n: number): void {
        let count = 0;
        (crypto.subtle as { encrypt: unknown }).encrypt = (...args: Parameters<SubtleCrypto["encrypt"]>) => {
            count += 1;
            return count === n ? Promise.reject(new DOMException("injected", "OperationError")) : originalEncrypt(...args);
        };
    },
    /** Any write that is split across a SECOND readwrite transaction would break here. */
    failSecondWriteTransaction(): void {
        let writes = 0;
        IDBDatabase.prototype.transaction = function (this: IDBDatabase, ...args: Parameters<IDBDatabase["transaction"]>) {
            const tx = originalTransaction.apply(this, args);
            if (args[1] === "readwrite") {
                writes += 1;
                if (writes === 2) queueMicrotask(() => { try { tx.abort(); } catch { /* already finished */ } });
            }
            return tx;
        } as typeof IDBDatabase.prototype.transaction;
    },
    blockLocalStorage(): void {
        Storage.prototype.setItem = function () { throw new DOMException("injected", "QuotaExceededError"); };
    },
    localFlags(): string[] {
        return Object.keys(localStorage).filter(k => k.startsWith("vinto:off03c4:revoked:"));
    },
    clearFaults(): void {
        Storage.prototype.setItem = originalSetItem;
        IDBDatabase.prototype.transaction = originalTransaction;
        IDBObjectStore.prototype.put = originalPut;
        (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt;
    },
};
Object.assign(globalThis, { H });
