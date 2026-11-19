/**
 * OFF-04.3 (LABORATORY ONLY): offline synchronisation engine.
 *
 * Pure orchestration over a SyncQueueStore and a SyncTransport (both injected). It never decides permissions,
 * never touches the application's send queue or the synthetic lab queue, and never calls a network API itself.
 *
 * Guarantees implemented here:
 *  - the same `capture_id` is sent for every attempt (idempotency key); it is never regenerated;
 *  - a record is sent only under the ORIGINAL author's valid session; otherwise the engine PAUSES and changes nothing;
 *  - any send that may have reached the server without a definite answer is reconciled (lookup) BEFORE being repeated;
 *  - a lease (compare-and-swap in the store) lets only one tab send a record; an interrupted `syncing` record is
 *    recovered after the lease expires, never duplicated;
 *  - dependencies are respected; payloads are never deleted; failures are classified, not swallowed.
 */
import {
    DONE_STATES, SyncTransportError, TERMINAL_STATES,
    type LookupReply, type SyncCounts, type SyncOutcome, type SyncQueueStore, type SyncRecord, type SyncReply, type SyncRequest,
    type SyncRunResult, type SyncState, type SyncTransport,
} from "./offline-sync-types.ts";

export type SessionInfo = Readonly<{ userId: string }> | null;
export type SyncOptions = Readonly<{
    leaseMs: number; timeoutMs: number; maxAttempts: number; baseDelayMs: number; maxDelayMs: number;
}>;
export const DEFAULT_SYNC_OPTIONS: SyncOptions = { leaseMs: 30_000, timeoutMs: 15_000, maxAttempts: 6, baseDelayMs: 2_000, maxDelayMs: 300_000 };

export type SyncDeps = Readonly<{
    store: SyncQueueStore;
    transport: SyncTransport;
    /** Current ONLINE session (a future authenticated-user check); null = no valid session. */
    session: () => Promise<SessionInfo>;
    /** Decrypts the frozen payload of a record (vault). */
    openPayload: (record: SyncRecord) => Promise<unknown>;
    identity: Readonly<{ ownerId: string; deviceKey: string }>;
    tabId: string;
    now?: () => number;
    rand?: () => number;
    options?: Partial<SyncOptions>;
}>;

const running = new Set<string>();
const lc = (s: string) => s.toLowerCase();

/** Exponential backoff with deterministic jitter (rand injectable): base·2^(n-1), capped, 50–100 %. */
export function backoffDelay(attempts: number, o: SyncOptions, rand: () => number): number {
    const raw = Math.min(o.maxDelayMs, o.baseDelayMs * 2 ** Math.max(0, attempts - 1));
    return Math.round(raw * (0.5 + rand() / 2));
}

export function countStates(records: readonly SyncRecord[]): SyncCounts {
    const c: Record<SyncState, number> = { queued: 0, syncing: 0, retry_wait: 0, synced: 0, synced_warning: 0, requires_review: 0, conflict: 0 };
    for (const r of records) c[r.state] += 1;
    return c;
}

async function withTimeout<T>(run: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => { ctl.abort(); reject(new SyncTransportError("timeout")); }, ms); });
    try { return await Promise.race([run(ctl.signal), timeout]); } finally { if (timer) clearTimeout(timer); }
}

async function sha256Hex(text: string): Promise<string> {
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text) as BufferSource));
    return Array.from(d, b => b.toString(16).padStart(2, "0")).join("");
}
/** Canonical hash used for `payload_sha256`: stable key order, so the server can compare payloads. */
export async function payloadHash(payload: unknown): Promise<string> {
    const canon = (v: unknown): unknown => Array.isArray(v) ? v.map(canon)
        : v && typeof v === "object" ? Object.fromEntries(Object.keys(v as object).sort().map(k => [k, canon((v as Record<string, unknown>)[k])])) : v;
    return sha256Hex(JSON.stringify(canon(payload)));
}

function applyLookup(found: Extract<LookupReply, { found: true }>): { state: SyncState; reason: string | null } {
    if (found.outcome === "review") return { state: "requires_review", reason: found.reason ?? "central_review" };
    if (found.outcome === "conflict") return { state: "conflict", reason: found.reason ?? "central_conflict" };
    return { state: found.outcome === "accepted_warning" ? "synced_warning" : "synced", reason: null };
}

type Classified =
    | { kind: "done"; state: "synced" | "synced_warning" | "requires_review" | "conflict"; serverRef: string | null; warnings: string[]; detail: string }
    | { kind: "auth" }
    | { kind: "transient"; detail: string; stop: "server_error" };

function classify(reply: SyncReply): Classified {
    const { status, body } = reply;
    if (status === 200 || status === 201) {
        const warnings = [...(body.warnings ?? [])];
        return { kind: "done", state: warnings.length > 0 ? "synced_warning" : "synced", serverRef: body.server_id ?? null, warnings, detail: body.outcome ?? "ok" };
    }
    if (status === 202) return { kind: "done", state: "requires_review", serverRef: body.server_id ?? null, warnings: [], detail: body.reason ?? "central_review" };
    if (status === 401) return { kind: "auth" };
    if (status === 403) return { kind: "done", state: "requires_review", serverRef: null, warnings: [], detail: "forbidden" };
    if (status === 409 || status === 422 || status === 400) return { kind: "done", state: "conflict", serverRef: null, warnings: [], detail: body.reason ?? "rejected_" + status };
    return { kind: "transient", detail: "http_" + status, stop: "server_error" };
}

/**
 * One synchronisation pass ("Sincronizar ahora"). Safe to call concurrently from several tabs: records are
 * claimed with a lease, and the single-flight guard prevents overlapping passes in one tab.
 */
export async function syncNow(deps: SyncDeps): Promise<SyncRunResult> {
    const o: SyncOptions = { ...DEFAULT_SYNC_OPTIONS, ...deps.options };
    const now = deps.now ?? (() => Date.now());
    const rand = deps.rand ?? Math.random;
    const guard = deps.tabId + ":" + lc(deps.identity.ownerId) + ":" + lc(deps.identity.deviceKey);
    const outcomes: SyncOutcome[] = [];
    const skipped = { waiting: 0, blocked: 0, busy: 0 };
    let sent = 0, reconciled = 0;
    let stopped: SyncRunResult["stopped"] = null;
    let paused: SyncRunResult["paused"] = null;
    const finish = async (): Promise<SyncRunResult> => ({
        paused, stopped, sent, reconciled, skipped, outcomes, counts: countStates(await deps.store.list(deps.identity.ownerId, deps.identity.deviceKey)),
    });
    if (running.has(guard)) { paused = "busy"; return finish(); }
    running.add(guard);
    try {
        let session: SessionInfo;
        try { session = await deps.session(); } catch { session = null; }
        if (!session) { paused = "session_invalid"; return await finish(); }
        if (lc(session.userId) !== lc(deps.identity.ownerId)) { paused = "different_user"; return await finish(); }

        const records = [...(await deps.store.list(deps.identity.ownerId, deps.identity.deviceKey))].sort((a, b) => a.seq - b.seq);
        for (const listed of records) {
            if (TERMINAL_STATES.includes(listed.state)) continue;
            const t0 = now();
            if (listed.state === "retry_wait" && (listed.nextAttemptAt ?? 0) > t0) { skipped.waiting += 1; continue; }
            if (listed.state === "syncing" && listed.lease && listed.lease.until > t0) { skipped.busy += 1; continue; }
            if (listed.dependsOn) {
                const dep = await deps.store.get(listed.dependsOn);
                if (!dep || !DONE_STATES.includes(dep.state)) {
                    skipped.blocked += 1;           // waits for (or is blocked by) its dependency; nothing is sent or changed
                    continue;
                }
            }
            // identity of the ORIGINAL author, checked per record again right before sending
            if (lc(listed.ownerId) !== lc(session.userId)) { paused = "different_user"; break; }

            const claim = await deps.store.claim(listed.capture_id, deps.tabId, t0, o.leaseMs);
            if (!claim) { skipped.busy += 1; continue; }
            const rec = claim.record;
            const from: SyncState = listed.state;
            const done = async (to: SyncState, detail: string, patch: Parameters<SyncQueueStore["finalize"]>[2] = {}) => {
                const ok = await deps.store.finalize(rec.capture_id, deps.tabId, { state: to, ...patch }, now());
                outcomes.push({ capture_id: rec.capture_id, from, to: ok ? to : from, detail: ok ? detail : "lease_lost" });
                return ok;
            };
            const retry = async (detail: string, uncertain: boolean) => {
                if (rec.attempts >= o.maxAttempts) { await done("requires_review", "retries_exhausted", { lastError: detail, uncertain }); return; }
                await done("retry_wait", detail, { nextAttemptAt: now() + backoffDelay(rec.attempts, o, rand), uncertain, lastError: detail });
            };

            // 1) reconcile BEFORE repeating anything that may already have reached the server
            if (rec.uncertain || claim.recovered) {
                try {
                    const found = await withTimeout(s => deps.transport.lookup(rec.capture_id, { signal: s }), o.timeoutMs);
                    reconciled += 1;
                    if (found.found) {
                        const r = applyLookup(found);
                        await done(r.state, "reconciled", { serverRef: found.server_id, warnings: found.warnings ?? [], uncertain: false, lastError: r.reason, nextAttemptAt: null });
                        continue;
                    }
                } catch (error) {
                    stopped = error instanceof SyncTransportError && error.kind === "timeout" ? "timeout" : "network";
                    await retry("reconcile_" + stopped, true);
                    break;
                }
            }

            // 2) payload integrity
            let payload: unknown;
            try { payload = await deps.openPayload(rec); }
            catch { await done("requires_review", "payload_unreadable", { lastError: "payload_unreadable" }); continue; }
            const hash = await payloadHash(payload);
            if (hash !== rec.payloadSha256) { await done("requires_review", "payload_altered", { lastError: "payload_altered" }); continue; }

            // 3) send (same capture_id every time)
            const request: SyncRequest = { capture_id: rec.capture_id, author_user_id: rec.ownerId, device_key: rec.deviceKey, form_code: rec.formCode,
                form_version: rec.formVersion, context_version: rec.contextVersion, payload_sha256: rec.payloadSha256, payload,
                ...(rec.machineCode ? { machine_code: rec.machineCode } : {}), ...(rec.scopeSnapshotId ? { scope_snapshot_id: rec.scopeSnapshotId } : {}) };
            let reply: SyncReply;
            try {
                sent += 1;
                reply = await withTimeout(s => deps.transport.send(request, { signal: s }), o.timeoutMs);
            } catch (error) {
                stopped = error instanceof SyncTransportError && error.kind === "timeout" ? "timeout" : "network";
                await retry(stopped, true);                      // the request may have been persisted: reconcile next time
                break;
            }
            const c = classify(reply);
            if (c.kind === "auth") {
                await done("queued", "auth_required", { uncertain: false, nextAttemptAt: null, lastError: "auth_required", attempts: Math.max(0, rec.attempts - 1) });
                paused = "auth_required";
                break;
            }
            if (c.kind === "transient") {
                stopped = c.stop;
                await retry(c.detail, true);
                break;
            }
            await done(c.state, c.detail, { serverRef: c.serverRef, warnings: c.warnings, uncertain: false, nextAttemptAt: null, lastError: c.state === "synced" || c.state === "synced_warning" ? null : c.detail });
        }
        return await finish();
    } finally { running.delete(guard); }
}
