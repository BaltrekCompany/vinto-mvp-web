/**
 * OFF-04.3 (LABORATORY ONLY): in-memory FAKE central server. It stands in for FastAPI so the engine can be proven
 * end to end without touching any real API. It registers every LOGICAL capture exactly once (by `capture_id`), even
 * when it receives many attempts, and can be scripted to lose responses, time out, fail with 5xx/401/403, ask for
 * review, add warnings or report a changed industrial context. No network access, no persistence outside memory.
 */
import { SyncTransportError, type LookupReply, type SyncReply, type SyncRequest, type SyncTransport } from "./offline-sync-types.ts";

export type Fault =
    | { type: "network_before" }                      // request never reaches the server
    | { type: "lose_response" }                       // server persists, the response is lost
    | { type: "timeout_after_persist" }               // server persists, the client times out
    | { type: "timeout_before" }                      // request never reaches the server; client times out
    | { type: "status"; status: number }              // answered without persisting (401, 403, 429, 500, 503, 400...)
    | { type: "status_after_persist"; status: number }// persisted, but the answer is a 5xx
    | { type: "review" }                              // accepted for central review (202)
    | { type: "warning"; warnings: string[] }         // accepted with an advisory (201 + warnings)
    | { type: "lookup_network" };                     // the next reconciliation lookup fails

export type Accepted = {
    capture_id: string; server_id: string; payload_sha256: string; author_user_id: string;
    outcome: "accepted" | "accepted_warning" | "review"; warnings: string[]; receivedAt: number;
};
export type LogEntry = { n: number; kind: "send" | "lookup"; capture_id: string; result: string };

export type FakeServerOptions = {
    sessionUser?: string | null;                    // null/undefined = no valid session (401)
    currentContext?: string;                         // requests prepared under another context are 409 context_changed
    now?: () => number;
    delayMs?: number;                                // artificial latency (honours AbortSignal)
};

export class FakeSyncServer {
    readonly accepted = new Map<string, Accepted>();
    readonly log: LogEntry[] = [];
    sessionUser: string | null;
    currentContext: string;
    delayMs: number;
    private faults: Fault[] = [];
    private counter = 0;
    private readonly now: () => number;

    constructor(options: FakeServerOptions = {}) {
        this.sessionUser = options.sessionUser ?? null;
        this.currentContext = options.currentContext ?? "ctx-1";
        this.now = options.now ?? (() => Date.now());
        this.delayMs = options.delayMs ?? 0;
    }

    /** Queue faults, consumed one per request (send or lookup) in order. */
    script(...faults: Fault[]): this { this.faults.push(...faults); return this; }
    clearFaults(): void { this.faults = []; }
    get sendCount(): number { return this.log.filter(l => l.kind === "send").length; }
    sendsFor(captureId: string): number { return this.log.filter(l => l.kind === "send" && l.capture_id === captureId).length; }

    private record(kind: LogEntry["kind"], capture_id: string, result: string): void { this.log.push({ n: this.log.length + 1, kind, capture_id, result }); }

    private async wait(signal: AbortSignal): Promise<void> {
        if (this.delayMs <= 0) { if (signal.aborted) throw new SyncTransportError("timeout"); return; }
        await new Promise<void>((resolve, reject) => {
            const t = setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, this.delayMs);
            const onAbort = () => { clearTimeout(t); reject(new SyncTransportError("timeout")); };
            if (signal.aborted) { onAbort(); return; }
            signal.addEventListener("abort", onAbort, { once: true });
        });
    }

    private persist(req: SyncRequest, outcome: Accepted["outcome"], warnings: string[]): Accepted {
        const existing = this.accepted.get(req.capture_id);
        if (existing) return existing;
        this.counter += 1;
        const row: Accepted = { capture_id: req.capture_id, server_id: "srv-" + String(this.counter).padStart(4, "0"), payload_sha256: req.payload_sha256,
            author_user_id: req.author_user_id, outcome, warnings, receivedAt: this.now() };
        this.accepted.set(req.capture_id, row);
        return row;
    }

    async handleSend(req: SyncRequest, signal: AbortSignal): Promise<SyncReply> {
        await this.wait(signal);
        const fault = this.faults.shift();
        if (fault?.type === "network_before") { this.record("send", req.capture_id, "network_before"); throw new SyncTransportError("network"); }
        if (fault?.type === "timeout_before") { this.record("send", req.capture_id, "timeout_before"); throw new SyncTransportError("timeout"); }
        if (fault?.type === "status") { this.record("send", req.capture_id, "status " + fault.status); return { status: fault.status, body: { outcome: "error", reason: "scripted_" + fault.status } }; }
        // normal request handling
        if (this.sessionUser === null) { this.record("send", req.capture_id, "401"); return { status: 401, body: { outcome: "error", reason: "unauthenticated" } }; }
        if (req.author_user_id.toLowerCase() !== this.sessionUser.toLowerCase()) { this.record("send", req.capture_id, "403 author"); return { status: 403, body: { outcome: "error", reason: "author_mismatch" } }; }
        if (req.context_version !== this.currentContext) { this.record("send", req.capture_id, "409 context_changed"); return { status: 409, body: { outcome: "conflict", reason: "context_changed" } }; }
        const existing = this.accepted.get(req.capture_id);
        if (existing && existing.payload_sha256 !== req.payload_sha256) { this.record("send", req.capture_id, "409 payload_mismatch"); return { status: 409, body: { outcome: "conflict", reason: "payload_mismatch" } }; }
        let reply: SyncReply;
        if (existing) {
            reply = existing.outcome === "review" ? { status: 202, body: { outcome: "review", server_id: existing.server_id, reason: "central_review" } }
                : { status: 200, body: { outcome: "duplicate", server_id: existing.server_id, warnings: existing.warnings } };
            this.record("send", req.capture_id, "duplicate");
        } else if (fault?.type === "review") {
            const row = this.persist(req, "review", []);
            reply = { status: 202, body: { outcome: "review", server_id: row.server_id, reason: "central_review" } };
            this.record("send", req.capture_id, "review");
        } else {
            const warnings = fault?.type === "warning" ? fault.warnings : [];
            const row = this.persist(req, warnings.length > 0 ? "accepted_warning" : "accepted", warnings);
            reply = { status: 201, body: { outcome: "created", server_id: row.server_id, warnings } };
            this.record("send", req.capture_id, "created");
        }
        if (fault?.type === "lose_response") throw new SyncTransportError("network");
        if (fault?.type === "timeout_after_persist") throw new SyncTransportError("timeout");
        if (fault?.type === "status_after_persist") return { status: fault.status, body: { outcome: "error", reason: "scripted_" + fault.status } };
        return reply;
    }

    async handleLookup(captureId: string, signal: AbortSignal): Promise<LookupReply> {
        await this.wait(signal);
        const fault = this.faults[0]?.type === "lookup_network" ? this.faults.shift() : undefined;
        if (fault) { this.record("lookup", captureId, "network"); throw new SyncTransportError("network"); }
        const row = this.accepted.get(captureId);
        this.record("lookup", captureId, row ? "found" : "not_found");
        if (!row) return { found: false };
        return { found: true, outcome: row.outcome, server_id: row.server_id, warnings: row.warnings };
    }

    transport(): SyncTransport {
        return { send: (req, o) => this.handleSend(req, o.signal), lookup: (id, o) => this.handleLookup(id, o.signal) };
    }
}
