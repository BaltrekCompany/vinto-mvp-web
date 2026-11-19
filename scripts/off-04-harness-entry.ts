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

import { captureIdFor, LabQueueError, listLabPendingSummaries, loadFrozenForDraft, PENDING_SCHEMA, queueLabDraft } from "../lib/vinto/offline-lab-queue.ts";
import { LabMigrationError, prepareLegacyMigration, runLegacyMigration, verifyMigrationPlan } from "../lib/vinto/offline-lab-migration.ts";
import { listQueuedForOwner, saveSealedDraftRevision } from "../lib/vinto/offline-store.ts";
import { buildDraftPayload, contextIdFor, evaluateDraft } from "../lib/vinto/offline-draft-schema.ts";
import { openLocalDraft, sealLocalDraft } from "../lib/vinto/offline-vault.ts";

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
        r.onupgradeneeded = () => { for (const n of ["drafts", "outbox"]) if (!r.result.objectStoreNames.contains(n)) r.result.createObjectStore(n, { keyPath: "id" }).createIndex("ownerDevice", ["ownerId", "deviceKey"], { unique: false }); };
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
        if (error instanceof LabMigrationError) return { ok: false, reason: error.reason };
        if (error instanceof LabQueueError) return { ok: false, reason: error.reason, missing: [...error.missing] };
        if (error instanceof DraftError) return { ok: false, reason: error.reason, issues: error.issues.map(i => i.key + ":" + i.code) };
        return { ok: false, reason: "unexpected:" + String(error) };
    }
};

const originalPut = IDBObjectStore.prototype.put;
const originalAdd = IDBObjectStore.prototype.add;

/** Opens the laboratory database WITHOUT creating it (an absent database aborts its own creation). */
async function labDb(): Promise<IDBDatabase | null> {
    return new Promise(resolve => {
        const r = indexedDB.open("vinto-off04lab-v2");
        r.onupgradeneeded = () => { try { r.transaction!.abort(); } catch { /* nothing to create */ } };
        r.onsuccess = () => resolve(r.result); r.onerror = () => resolve(null);
    });
}
async function labRows(store = "lab_pending"): Promise<Json[]> {
    const db = await labDb();
    if (!db) return [];
    try {
        return await new Promise<Json[]>((resolve, reject) => {
            const q = db.transaction(store, "readonly").objectStore(store).getAll();
            q.onsuccess = () => resolve(q.result as Json[]); q.onerror = () => reject(new Error("dump"));
        });
    } finally { db.close(); }
}
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
    rawDrafts: async () => JSON.stringify(await labRows("lab_drafts")),
    rawDraftRows: async () => (await labRows("lab_drafts")) as unknown as Json[],
    legacyDrafts: async () => JSON.stringify(await dump("drafts")),
    rawQuarantine: async () => (await labRows("lab_quarantine")) as unknown as Json[],
    labMeta: async () => (await labRows("lab_meta")) as unknown as Json[],
    labEpoch: () => localStorage.getItem("vinto-off04lab-epoch"),
    rawOutboxCount: async () => (await dump("outbox")).length,
    async tamper(id: string, kind: "ciphertext" | "outer_revision" | "outer_version" | "drop_revision" | "unfreeze" | "fake_freeze"): Promise<void> {
        const db = (await labDb())!;
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = db.transaction("lab_drafts", "readwrite"); const store = tx.objectStore("lab_drafts"); const g = store.get(id);
                g.onsuccess = () => {
                    const row = g.result as { sealed: { ciphertext: string }; revision?: number; formVersion: number; frozenBy?: string };
                    if (kind === "ciphertext") row.sealed.ciphertext = (row.sealed.ciphertext[0] === "A" ? "B" : "A") + row.sealed.ciphertext.slice(1);
                    if (kind === "outer_revision") row.revision = (row.revision ?? 1) + 5;
                    if (kind === "outer_version") row.formVersion += 1;
                    if (kind === "drop_revision") delete row.revision;
                    if (kind === "unfreeze") delete row.frozenBy;
                    if (kind === "fake_freeze") row.frozenBy = "99999999-9999-4999-8999-999999999999";
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
    queue: (id: string, expected: number, asIdentity?: OfflineVaultIdentity) =>
        wrap(async () => { const c = await context(); return { ...(await queueLabDraft(key!, asIdentity ?? identity!, c, { id, expectedRevision: expected })) }; }),
    /** N simultaneous transitions of the same draft inside this tab (double click / retries). */
    queueMany: async (id: string, expected: number, n: number): Promise<Json> => {
        const results = await Promise.all(Array.from({ length: n }, () => H.queue(id, expected)));
        return { ok: true, results: results as unknown as Json[] };
    },
    pendingList: (asIdentity?: OfflineVaultIdentity) =>
        wrap(async () => ({ ...(await listLabPendingSummaries(key!, asIdentity ?? identity!)) as unknown as Json })),
    frozen: (draftId: string) => wrap(async () => ({ payload: (await loadFrozenForDraft(key!, identity!, draftId)) as unknown as Json })),
    pendingLoad: (draftId: string) => wrap(async () => {
        const rows = (await labRows("lab_pending")).filter(r => r.draftId === draftId);
        if (rows.length === 0) return { found: false };
        const p = await loadFrozenForDraft(key!, identity!, draftId);
        return { found: true, record: rows[0], payload: p as unknown as Json };
    }),
    rawPending: async () => JSON.stringify(await labRows()),
    rawPendingRows: async () => (await labRows()) as unknown as Json[],
    realOutbox: async () => (await dump("outbox")).length + (await listQueuedForOwner(identity!.ownerId.toLowerCase(), identity!.deviceKey.toLowerCase())).length,
    /** Raw attempts to break the immutability/uniqueness contract (what a buggy or hostile writer could do). */
    async rawAddPending(row: Json): Promise<Json> {
        const db = (await labDb())!;
        try {
            return await new Promise<Json>(resolve => {
                const tx = db.transaction("lab_pending", "readwrite");
                try { tx.objectStore("lab_pending").add(row); } catch (e) { resolve({ ok: false, reason: (e as DOMException).name }); return; }
                tx.oncomplete = () => resolve({ ok: true }); tx.onabort = () => resolve({ ok: false, reason: tx.error?.name ?? "abort" });
            });
        } finally { db.close(); }
    },
    async tamperPending(captureId: string, kind: "ciphertext" | "status" | "revision" | "draft_id" | "delete_marker"): Promise<void> {
        const db = (await labDb())!;
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = db.transaction("lab_pending", "readwrite"); const store = tx.objectStore("lab_pending"); const g = store.get(captureId);
                g.onsuccess = () => {
                    const row = g.result as Record<string, unknown> & { sealed: { ciphertext: string } };
                    if (kind === "ciphertext") row.sealed.ciphertext = (row.sealed.ciphertext[0] === "A" ? "B" : "A") + row.sealed.ciphertext.slice(1);
                    if (kind === "status") row.status = "queued";
                    if (kind === "revision") row.sourceRevision = (row.sourceRevision as number) + 1;
                    if (kind === "draft_id") row.draftId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
                    store.put(row);
                };
                tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("t"));
            });
        } finally { db.close(); }
    },
    failAddOn(n: number, name = "DataError", after = false): void {
        let count = 0;
        IDBObjectStore.prototype.add = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore["add"]>) {
            count += 1;
            if (count !== n) return originalAdd.apply(this, args);
            if (after) { const r = originalAdd.apply(this, args); throw new DOMException("injected-after", name) ; void r; }
            throw new DOMException("injected", name);
        };
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
    clearFaults(): void { IDBObjectStore.prototype.put = originalPut; IDBObjectStore.prototype.add = originalAdd; (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt; },
    profileDbOpen: () => openProfileDb().then(db => { db.close(); return true; }),
};
/** OFF-04.2-R2 helpers: deterministic races between a draft save and the pending transition. */
async function hookOnce(fn: () => Promise<unknown>, run: () => Promise<Json>): Promise<Json> {
    let fired = false;
    (crypto.subtle as { encrypt: unknown }).encrypt = async (...args: Parameters<SubtleCrypto["encrypt"]>) => {
        if (!fired) { fired = true; (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt; await fn(); }
        return originalEncrypt(...args);
    };
    try { return await run(); } finally { (crypto.subtle as { encrypt: unknown }).encrypt = originalEncrypt; }
}
const LEGACY_QUEUE = "vinto-off04lab-queue-v1";
async function legacyQueueDb(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const r = indexedDB.open(LEGACY_QUEUE, 1);
        r.onupgradeneeded = () => {
            const st = r.result.createObjectStore("lab_pending", { keyPath: "capture_id" });
            st.createIndex("ownerDevice", ["ownerId", "deviceKey"], { unique: false });
            st.createIndex("sourceDraft", ["ownerId", "deviceKey", "draftId"], { unique: true });
        };
        r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("legacy queue db"));
    });
}
Object.assign(H, {
    /** ANOTHER writer saves revision N+1 while the queue transition is sealing revision N. */
    queueVsSave: (id: string, exp: number, v: Record<string, unknown>) => hookOnce(() => H.save(id, v, exp), () => H.queue(id, exp)),
    /** ANOTHER tab queues revision N while a save of N+1 is sealing (it already read the draft). */
    saveVsQueue: (id: string, exp: number, v: Record<string, unknown>) => hookOnce(() => H.queue(id, exp), () => H.save(id, v, exp)),
    /** Simulates losing ONLY the laboratory database (partial cleanup / restore). */
    async dropLabDb(): Promise<void> {
        for (const name of ["vinto-off04lab-v2", LEGACY_QUEUE]) {
            await new Promise<void>(r => { const q = indexedDB.deleteDatabase(name); q.onsuccess = q.onerror = q.onblocked = () => r(); });
        }
    },
    async dropOnlyV2(): Promise<void> {
        await new Promise<void>(r => { const q = indexedDB.deleteDatabase("vinto-off04lab-v2"); q.onsuccess = q.onerror = q.onblocked = () => r(); });
    },
    labExists: async () => (await indexedDB.databases()).some(d => d.name === "vinto-off04lab-v2"),
    clearLabEpoch: () => { localStorage.removeItem("vinto-off04lab-epoch"); },
    /** Legacy (pre-R2) data, written exactly as OFF-04.1/04.2 did: drafts in the application's drafts store. */
    legacySave: (id: string, values: Record<string, unknown>, expected: number | null) => wrap(async () => {
        const c = await context(); const pkg = c.pkg.envelope.payload;
        const ev = evaluateDraft(pkg.definition, values);
        const revision = (expected ?? 0) + 1, now = new Date().toISOString();
        const contextId = await contextIdFor(pkg.scope_snapshot_id, pkg.machine_code, pkg.form_code);
        const payload = buildDraftPayload({ pkg, ownerId: identity!.ownerId, deviceKey: identity!.deviceKey }, id, ev.clean, revision, now, now);
        const sealed = await sealLocalDraft(key!, { ownerId: identity!.ownerId, deviceKey: identity!.deviceKey, id: id.toLowerCase(), contextId,
            formCode: pkg.form_code, formVersion: pkg.form_version }, payload);
        await saveSealedDraftRevision({ id: id.toLowerCase(), ownerId: identity!.ownerId.toLowerCase(), deviceKey: identity!.deviceKey.toLowerCase(),
            formCode: pkg.form_code, formVersion: pkg.form_version, contextId, savedAt: now, revision, sealed }, expected);
        return { revision };
    }),
    /** Legacy pending in the former queue database (frozen copy of the CURRENT legacy draft). */
    legacyQueue: (id: string) => wrap(async () => {
        const row = (await dump("drafts") as Record<string, unknown>[]).find(r => r.id === id.toLowerCase()) as Record<string, unknown> & { sealed: never };
        const binding = { ownerId: identity!.ownerId, deviceKey: identity!.deviceKey, id: row.id as string, contextId: row.contextId as string,
            formCode: row.formCode as string, formVersion: row.formVersion as number };
        const draft = await openLocalDraft(key!, binding, row.sealed) as Record<string, unknown>;
        const captureId = await captureIdFor(identity!.ownerId, identity!.deviceKey, id);
        const queuedAt = new Date().toISOString();
        const payload = { schema: PENDING_SCHEMA, status: "queued_local_simulation", synthetic: true, sync_state: "NOT_SYNCED", capture_id: captureId,
            source_draft_id: id.toLowerCase(), source_revision: draft.revision, queued_local: queuedAt, draft };
        const sealed = await sealLocalDraft(key!, { ...binding, id: captureId }, payload);
        const record = { capture_id: captureId, draftId: id.toLowerCase(), ownerId: identity!.ownerId.toLowerCase(), deviceKey: identity!.deviceKey.toLowerCase(),
            formCode: row.formCode, formVersion: row.formVersion, contextId: row.contextId, sourceRevision: draft.revision, queuedAt,
            status: "queued_local_simulation", lab: true, syncState: "NOT_SYNCED", sealed };
        const db = await legacyQueueDb();
        try { await new Promise<void>((resolve, reject) => { const tx = db.transaction("lab_pending", "readwrite"); tx.objectStore("lab_pending").add(record); tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("lq")); }); }
        finally { db.close(); }
        return { captureId };
    }),
    async legacyTamper(id: string): Promise<void> {
        const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open("vinto-offline-v1", 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(new Error("o")); });
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = db.transaction("drafts", "readwrite"); const st = tx.objectStore("drafts"); const g = st.get(id.toLowerCase());
                g.onsuccess = () => { const row = g.result; row.sealed.ciphertext = (row.sealed.ciphertext[0] === "A" ? "B" : "A") + row.sealed.ciphertext.slice(1); st.put(row); };
                tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error("t"));
            });
        } finally { db.close(); }
    },
    legacyRaw: async () => {
        const q = await new Promise<unknown[]>(resolve => {
            const r = indexedDB.open(LEGACY_QUEUE);
            r.onupgradeneeded = () => { try { r.transaction!.abort(); } catch { /* absent */ } };
            r.onerror = () => resolve([]);
            r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.contains("lab_pending")) { db.close(); resolve([]); return; }
                const g = db.transaction("lab_pending").objectStore("lab_pending").getAll(); g.onsuccess = () => { db.close(); resolve(g.result as unknown[]); }; };
        });
        return JSON.stringify([await dump("drafts"), q]);
    },
    migrate: (verified = false) => wrap(async () => ({ ...(await runLegacyMigration(key!, identity!, verified)) as unknown as Json })),
    migratePlan: (verified = false) => wrap(async () => {
        const plan = await prepareLegacyMigration(key!, identity!, verified);
        if (!plan.alreadyMigrated) verifyMigrationPlan(plan);
        return { alreadyMigrated: plan.alreadyMigrated, drafts: plan.drafts.length, pendings: plan.pendings.length, quarantine: plan.quarantine.length, divergent: plan.divergent.length };
    }),
});
Object.assign(globalThis, { H });
