/**
 * OFF-04.3 scenario suite for the synchronisation engine, written ONCE and run against BOTH queue stores:
 * the in-memory store (Node) and the IndexedDB store (real Chrome, via the browser harness). Synthetic data only;
 * the "server" is the in-memory FakeSyncServer; any fetch/XHR attempt is recorded and must be zero.
 */
import { createLocalVault, type OfflineVaultIdentity } from "../lib/vinto/offline-vault.ts";
import { FakeSyncServer } from "../lib/vinto/offline-sync-fake-server.ts";
import { backoffDelay, DEFAULT_SYNC_OPTIONS, syncNow, type SyncDeps } from "../lib/vinto/offline-sync-engine.ts";
import { createSyncCapture, openSyncPayload } from "../lib/vinto/offline-sync-capture.ts";
import type { SyncQueueStore, SyncRecord, SyncRunResult, SyncState, SyncTransport } from "../lib/vinto/offline-sync-types.ts";

export type SuiteEnv = Readonly<{
    makeStore: () => SyncQueueStore;
    /** corrupt the sealed payload of a stored record (raw write, bypassing the engine) */
    tamperCiphertext: (id: string) => Promise<void>;
    /** change the stored integrity hash of a record (raw write): the payload still decrypts but no longer matches */
    tamperHash: (id: string) => Promise<void>;
}>;
export type ScenarioResult = { name: string; ok: boolean; detail?: string };

const OWNER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const check = (cond: unknown, msg: string): void => { if (!cond) throw new Error("ASSERT: " + msg); };
const eq = (a: unknown, b: unknown, msg: string): void => check(JSON.stringify(a) === JSON.stringify(b), msg + " (got " + JSON.stringify(a) + ", expected " + JSON.stringify(b) + ")");
const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

type Ctx = {
    store: SyncQueueStore; server: FakeSyncServer; identity: OfflineVaultIdentity; key: CryptoKey; clock: { t: number };
    deps: (tab: string, extra?: Partial<SyncDeps>) => SyncDeps; add: (n: number, extra?: { dependsOn?: string | null; contextVersion?: string }) => Promise<SyncRecord>;
    run: (tab?: string, extra?: Partial<SyncDeps>) => Promise<SyncRunResult>; state: (r: SyncRecord) => Promise<SyncState>; rec: (r: SyncRecord) => Promise<SyncRecord>;
    sessionUser: { v: string | null };
};

export async function runSyncScenarios(env: SuiteEnv): Promise<ScenarioResult[]> {
    const fetchCalls: string[] = [];
    const realFetch = (globalThis as { fetch?: unknown }).fetch;
    (globalThis as { fetch: unknown }).fetch = (...a: unknown[]) => { fetchCalls.push(String(a[0])); throw new Error("fetch blocked in sync lab"); };
    const { key } = await createLocalVault({ ownerId: OWNER, deviceKey: "99999999-9999-4999-8999-999999999999" }, "VINTO OFF043 synthetic secret 7741!!");
    let seqCounter = 0;
    const make = async (): Promise<Ctx> => {
        const identity: OfflineVaultIdentity = { ownerId: OWNER, deviceKey: crypto.randomUUID() };
        const store = env.makeStore();
        const clock = { t: 1_700_000_000_000 };
        const sessionUser: { v: string | null } = { v: OWNER };
        const server = new FakeSyncServer({ sessionUser: OWNER, currentContext: "ctx-1", now: () => clock.t });
        const deps = (tab: string, extra: Partial<SyncDeps> = {}): SyncDeps => ({
            store, transport: server.transport(), session: async () => sessionUser.v ? { userId: sessionUser.v } : null, openPayload: openSyncPayload(key, identity),
            identity, tabId: tab + "-" + crypto.randomUUID().slice(0, 6), now: () => clock.t, rand: () => 1,
            options: { leaseMs: 30_000, timeoutMs: 400, maxAttempts: 4, baseDelayMs: 1000, maxDelayMs: 60_000 }, ...extra,
        });
        const add = (n: number, extra: { dependsOn?: string | null; contextVersion?: string } = {}) => createSyncCapture(key, identity, store,
            { payload: { numero_de_cuba: "C-" + n + "-SINT", masa_g: String(100 + n) }, contextVersion: extra.contextVersion ?? "ctx-1", dependsOn: extra.dependsOn ?? null, seq: ++seqCounter }, () => clock.t);
        return { store, server, identity, key, clock, deps, add, sessionUser,
            run: (tab = "A", extra = {}) => syncNow(deps(tab, extra)),
            state: async (r) => (await store.get(r.capture_id))!.state, rec: async (r) => (await store.get(r.capture_id))! };
    };

    const scenarios: [string, (c: Ctx) => Promise<void>][] = [
        ["success_counters_and_results", async (c) => {
            const [a, b, d] = [await c.add(1), await c.add(2), await c.add(3)];
            const r = await c.run();
            eq([r.paused, r.stopped, r.sent], [null, null, 3], "run summary");
            eq(r.counts.synced, 3, "counters"); eq(r.outcomes.map(o => o.to), ["synced", "synced", "synced"], "outcomes");
            check(c.server.accepted.size === 3 && c.server.sendCount === 3, "server registered each capture once");
            for (const x of [a, b, d]) { const s = await c.rec(x); check(s.serverRef && s.state === "synced" && s.attempts === 1 && s.lease === null, "record result persisted"); }
            const again = await c.run("A2");
            eq([again.sent, c.server.sendCount, again.counts.synced], [0, 3, 3], "terminal records are never sent again nor deleted");
        }],
        ["idempotent_enqueue_and_stable_capture_id", async (c) => {
            const a = await c.add(1);
            const same = await createSyncCapture(c.key, c.identity, c.store, { captureId: a.capture_id, payload: { numero_de_cuba: "C-1-SINT", masa_g: "101" }, contextVersion: "ctx-1", seq: 99 });
            eq(same.capture_id, a.capture_id, "same id"); eq((await c.store.list(c.identity.ownerId, c.identity.deviceKey)).length, 1, "no duplicate row");
            let rejected = false;
            try { await createSyncCapture(c.key, c.identity, c.store, { captureId: a.capture_id, payload: { numero_de_cuba: "OTRO" }, contextVersion: "ctx-1", seq: 100 }); } catch { rejected = true; }
            check(rejected, "same capture_id with another payload is refused locally");
            await c.run(); await c.run("B");
            eq((await c.rec(a)).capture_id, a.capture_id, "capture_id never regenerated");
            eq([c.server.sendsFor(a.capture_id)], [1], "sent once");
        }],
        ["lost_response_after_persistence_is_reconciled_not_resent", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "lose_response" });
            const r1 = await c.run();
            eq([r1.stopped, await c.state(a)], ["network", "retry_wait"], "response lost => retry_wait");
            const s1 = await c.rec(a);
            check(s1.uncertain && (s1.nextAttemptAt ?? 0) > c.clock.t, "marked uncertain with backoff");
            const early = await c.run("B"); eq([early.sent, early.skipped.waiting], [0, 1], "not retried before its time");
            c.clock.t += 2000;
            const r2 = await c.run("C");
            eq([r2.sent, r2.reconciled, await c.state(a)], [0, 1, "synced"], "reconciled by lookup, not resent");
            eq([c.server.accepted.size, c.server.sendCount], [1, 1], "server has ONE capture, ONE send");
        }],
        ["same_capture_id_repeated_registers_once", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "timeout_after_persist" });
            await c.run(); c.clock.t += 2000; await c.run("B");
            const req = { capture_id: a.capture_id, author_user_id: OWNER, device_key: c.identity.deviceKey, form_code: a.formCode, form_version: 1, context_version: "ctx-1", payload_sha256: a.payloadSha256, payload: {} };
            const dup = await c.server.handleSend(req, new AbortController().signal);
            eq([dup.status, dup.body.outcome], [200, "duplicate"], "duplicate answered idempotently");
            eq(c.server.accepted.size, 1, "still one logical capture");
            const bad = await c.server.handleSend({ ...req, payload_sha256: "0".repeat(64) }, new AbortController().signal);
            eq([bad.status, bad.body.reason], [409, "payload_mismatch"], "same id, other payload is a conflict");
        }],
        ["two_tabs_send_each_capture_once", async (c) => {
            for (let i = 1; i <= 4; i++) await c.add(i);
            c.server.delayMs = 8;
            const [ra, rb] = await Promise.all([c.run("A"), c.run("B")]);
            eq([c.server.accepted.size, c.server.sendCount], [4, 4], "4 captures, 4 sends in total across both tabs");
            eq(ra.sent + rb.sent, 4, "sends split between tabs, never doubled");
            eq((await c.store.list(c.identity.ownerId, c.identity.deviceKey)).every(r => r.state === "synced"), true, "all synced");
        }],
        ["interruption_during_sync_recovers_without_duplicate_after_persist", async (c) => {
            const a = await c.add(1);
            const base = c.server.transport();
            const hang: SyncTransport = { lookup: base.lookup, send: async (req, o) => { await c.server.handleSend(req, o.signal); return new Promise(() => { /* the tab died before the answer */ }); } };
            const first = c.run("A", { transport: hang, options: { ...c.deps("x").options, timeoutMs: 300 } });
            for (let i = 0; i < 200 && (await c.state(a)) !== "syncing"; i++) await sleep(5);
            eq(await c.state(a), "syncing", "record is syncing (tab A)");
            const blocked = await c.run("B"); eq([blocked.sent, blocked.skipped.busy], [0, 1], "live lease: another tab does not touch it");
            c.clock.t += 31_000;                                                // the lease expired: tab A is gone
            const rec = await c.run("B2");
            eq([await c.state(a), rec.reconciled, rec.sent], ["synced", 1, 0], "recovered by reconciliation, not resent");
            await first;                                                        // the dead tab finally times out: its late result must not corrupt anything
            eq([await c.state(a), c.server.accepted.size, c.server.sendCount], ["synced", 1, 1], "no corruption, ONE capture, ONE send");
        }],
        ["interruption_before_persistence_resends_once", async (c) => {
            const a = await c.add(1);
            const base = c.server.transport();
            const hang: SyncTransport = { lookup: base.lookup, send: () => new Promise(() => { /* died before reaching the server */ }) };
            const first = c.run("A", { transport: hang, options: { ...c.deps("x").options, timeoutMs: 300 } });
            for (let i = 0; i < 200 && (await c.state(a)) !== "syncing"; i++) await sleep(5);
            c.clock.t += 31_000;
            const rec = await c.run("B");
            eq([await c.state(a), rec.reconciled, rec.sent, c.server.accepted.size], ["synced", 1, 1, 1], "lookup found nothing, so it was sent exactly once");
            await first;
            eq([await c.state(a), c.server.sendCount], ["synced", 1], "late timeout of the dead tab changed nothing");
        }],
        ["expired_session_pauses_without_changing_anything", async (c) => {
            const a = await c.add(1);
            c.sessionUser.v = null;
            const r = await c.run();
            eq([r.paused, r.sent, await c.state(a), (await c.rec(a)).attempts], ["session_invalid", 0, "queued", 0], "paused, untouched");
            c.sessionUser.v = OWNER;
            eq((await c.run("B")).counts.synced, 1, "resumes after the author logs in again");
        }],
        ["different_author_session_pauses_and_never_reassigns", async (c) => {
            const a = await c.add(1);
            c.sessionUser.v = OTHER;
            const r = await c.run();
            eq([r.paused, r.sent, await c.state(a), (await c.rec(a)).ownerId], ["different_user", 0, "queued", OWNER], "paused; the record keeps its original author");
            eq(c.server.sendCount, 0, "nothing reached the server");
        }],
        ["server_401_pauses_and_keeps_the_record_queued", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "status", status: 401 });
            const r = await c.run();
            eq([r.paused, await c.state(a), (await c.rec(a)).attempts], ["auth_required", "queued", 0], "401 => auth_required, attempt not consumed");
            eq((await c.run("B")).counts.synced, 1, "syncs after re-authentication");
        }],
        ["server_403_requires_review_and_is_not_retried", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "status", status: 403 });
            await c.run();
            const s = await c.rec(a);
            eq([s.state, s.lastError], ["requires_review", "forbidden"], "403 => requires_review");
            check((await c.run("B")).sent === 0 && c.server.sendCount === 1, "never retried automatically");
        }],
        ["transient_5xx_uses_backoff_then_succeeds", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "status", status: 503 }, { type: "status", status: 500 });
            const r1 = await c.run(); const s1 = await c.rec(a);
            eq([r1.stopped, s1.state, s1.nextAttemptAt], ["server_error", "retry_wait", c.clock.t + 1000], "first backoff = base");
            c.clock.t += 1000; await c.run("B"); const s2 = await c.rec(a);
            eq([s2.state, s2.nextAttemptAt], ["retry_wait", c.clock.t + 2000], "second backoff doubles");
            c.clock.t += 2000; await c.run("C");
            eq([await c.state(a), c.server.accepted.size], ["synced", 1], "succeeds when the server recovers");
        }],
        ["5xx_after_persistence_is_reconciled", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "status_after_persist", status: 500 });
            await c.run(); c.clock.t += 5000; const r = await c.run("B");
            eq([await c.state(a), r.reconciled, c.server.sendCount, c.server.accepted.size], ["synced", 1, 1, 1], "persisted-then-500 is reconciled, not duplicated");
        }],
        ["intermittent_network_retries_then_gives_up_for_review_keeping_the_payload", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "network_before" }, { type: "timeout_before" }, { type: "network_before" }, { type: "network_before" });
            for (let i = 0; i < 4; i++) { await c.run("T" + i); c.clock.t += 120_000; }
            const s = await c.rec(a);
            eq([s.state, s.lastError, s.attempts], ["requires_review", "network", 4], "retries exhausted => requires_review");
            check(!!(await openSyncPayload(c.key, c.identity)(s)), "the payload is preserved for review");
            eq(c.server.accepted.size, 0, "nothing was registered");
        }],
        ["dependencies_are_respected_in_order", async (c) => {
            const a = await c.add(1); const b = await c.add(2, { dependsOn: a.capture_id });
            c.server.script({ type: "status", status: 503 });
            const r1 = await c.run();
            eq([await c.state(a), await c.state(b), r1.skipped.blocked], ["retry_wait", "queued", 0], "dependent is not sent while its dependency fails");
            c.clock.t += 5000;
            const r2 = await c.run("B");
            eq([await c.state(a), await c.state(b), r2.sent], ["synced", "synced", 2], "dependency first, then the dependent");
            eq(c.server.log.filter(l => l.kind === "send").map(l => l.capture_id), [a.capture_id, a.capture_id, b.capture_id], "order of sends: the failed attempt, the retry, then the dependent");
        }],
        ["blocked_dependency_keeps_the_dependent_queued", async (c) => {
            const a = await c.add(1); const b = await c.add(2, { dependsOn: a.capture_id });
            c.server.currentContext = "ctx-2";            // a conflicts
            const r = await c.run();
            eq([await c.state(a), await c.state(b), r.skipped.blocked, r.sent], ["conflict", "queued", 1, 1], "a conflicted; b is blocked and untouched");
            const r2 = await c.run("B");
            eq([r2.skipped.blocked, r2.sent, await c.state(b)], [1, 0, "queued"], "b stays blocked, never sent");
        }],
        ["industrial_context_changed_is_a_conflict_and_keeps_evidence", async (c) => {
            const a = await c.add(1);
            c.server.currentContext = "ctx-2";
            await c.run();
            const s = await c.rec(a);
            eq([s.state, s.lastError], ["conflict", "context_changed"], "context changed => conflict");
            check(!!(await openSyncPayload(c.key, c.identity)(s)) && s.contextVersion === "ctx-1", "original context and payload preserved, never migrated");
            check((await c.run("B")).sent === 0, "not retried automatically");
        }],
        ["central_review_response", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "review" });
            await c.run();
            const s = await c.rec(a);
            eq([s.state, !!s.serverRef], ["requires_review", true], "202 => requires_review with server reference");
            check((await c.run("B")).sent === 0 && c.server.accepted.size === 1, "registered once, not resent");
        }],
        ["accepted_with_warning", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "warning", warnings: ["context_changed_after_prepare"] });
            await c.run();
            const s = await c.rec(a);
            eq([s.state, s.warnings], ["synced_warning", ["context_changed_after_prepare"]], "synced_warning keeps the advisory");
        }],
        ["result_not_stored_after_central_persistence_is_recovered_without_duplicate", async (c) => {
            const a = await c.add(1);
            let fired = false;
            const flaky: SyncQueueStore = { ...c.store, finalize: async (...args) => { if (!fired) { fired = true; throw new Error("disk full"); } return c.store.finalize(...args); } };
            let threw = false;
            try { await c.run("A", { store: flaky }); } catch { threw = true; }
            check(threw, "the storage failure is surfaced, not swallowed");
            eq([await c.state(a), c.server.accepted.size], ["syncing", 1], "persisted centrally, still syncing locally");
            c.clock.t += 31_000;
            const r = await c.run("B");
            eq([await c.state(a), r.reconciled, r.sent, c.server.sendCount], ["synced", 1, 0, 1], "recovered by reconciliation: one capture, one send");
        }],
        ["tampered_local_payload_goes_to_review_never_to_the_server", async (c) => {
            const a = await c.add(1);
            await env.tamperCiphertext(a.capture_id);
            await c.run();
            eq([await c.state(a), c.server.sendCount], ["requires_review", 0], "unreadable payload is never sent");
        }],
        ["payload_that_no_longer_matches_its_hash_goes_to_review_never_to_the_server", async (c) => {
            const a = await c.add(1);
            await env.tamperHash(a.capture_id);
            await c.run();
            eq([await c.state(a), (await c.rec(a)).lastError, c.server.sendCount], ["requires_review", "payload_altered", 0], "integrity mismatch is never sent");
        }],
        ["reconcile_failure_keeps_the_record_waiting", async (c) => {
            const a = await c.add(1);
            c.server.script({ type: "lose_response" }, { type: "lookup_network" });
            await c.run(); c.clock.t += 5000;
            const r = await c.run("B");
            eq([r.stopped, await c.state(a), c.server.sendCount], ["network", "retry_wait", 1], "lookup failed: not resent blindly");
            c.clock.t += 120_000; await c.run("C");
            eq([await c.state(a), c.server.sendCount], ["synced", 1], "later reconciled");
        }],
        ["backoff_function_is_exponential_capped_and_jittered", async () => {
            const o = { ...DEFAULT_SYNC_OPTIONS, baseDelayMs: 1000, maxDelayMs: 10_000 };
            eq([1, 2, 3, 4, 5, 6].map(n => backoffDelay(n, o, () => 1)), [1000, 2000, 4000, 8000, 10000, 10000], "exponential and capped");
            eq([backoffDelay(3, o, () => 0), backoffDelay(3, o, () => 1)], [2000, 4000], "jitter 50-100 %");
        }],
    ];

    const results: ScenarioResult[] = [];
    for (const [name, fn] of scenarios) {
        try { await fn(await make()); results.push({ name, ok: true }); }
        catch (error) { results.push({ name, ok: false, detail: String((error as Error)?.message ?? error).slice(0, 400) }); }
    }
    results.push({ name: "no_real_api_or_network_call_was_made", ok: fetchCalls.length === 0, detail: fetchCalls.join(",") });
    (globalThis as { fetch?: unknown }).fetch = realFetch;
    return results;
}
