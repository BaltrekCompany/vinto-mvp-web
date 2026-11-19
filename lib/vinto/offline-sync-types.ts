/**
 * OFF-04.3 (LABORATORY ONLY): contracts of the offline synchronisation engine.
 *
 * The engine talks to a SyncTransport. In this increment the ONLY transport is an in-memory fake server
 * (offline-sync-fake-server.ts): there is no network access, no real API call and no production endpoint.
 * A future FastAPI transport must implement the same interface (see docs/OFF-04-3-motor-sincronizacion-laboratorio.md).
 * The engine is fully separate from the application's send queue and from the synthetic lab queue.
 */
export type SyncState =
    | "queued" | "syncing" | "retry_wait" | "synced" | "synced_warning" | "requires_review" | "conflict";
export const TERMINAL_STATES: readonly SyncState[] = ["synced", "synced_warning", "requires_review", "conflict"];
export const DONE_STATES: readonly SyncState[] = ["synced", "synced_warning"];

export type SyncSealed = Readonly<{ format: "aes-gcm-v1"; iv: string; ciphertext: string }>;
export type SyncLease = Readonly<{ owner: string; until: number }>;

export type SyncRecord = Readonly<{
    capture_id: string;           // stable, never regenerated: the idempotency key
    ownerId: string;              // ORIGINAL author: only this user's session may send it
    deviceKey: string;
    seq: number;                  // local order
    dependsOn: string | null;     // capture_id that must be synced first
    formCode: string;
    formVersion: number;
    contextVersion: string;       // industrial context the capture was prepared under
    machineCode?: string;         // OFF-04.4: references sent to a central receiver (optional: the fake server ignores them)
    scopeSnapshotId?: string;
    payloadSha256: string;        // integrity of the frozen payload
    state: SyncState;
    attempts: number;
    nextAttemptAt: number | null;
    uncertain: boolean;           // a send may have reached the server without a definite answer
    lease: SyncLease | null;
    version: number;              // compare-and-swap counter
    lastError: string | null;
    serverRef: string | null;
    warnings: readonly string[];
    createdAt: string;
    updatedAt: string;
    sealed: SyncSealed;
}>;

/** What goes on the wire (the future FastAPI body). `capture_id` doubles as the idempotency key. */
export type SyncRequest = Readonly<{
    capture_id: string;
    author_user_id: string;
    device_key: string;
    form_code: string;
    form_version: number;
    context_version: string;
    machine_code?: string;
    scope_snapshot_id?: string;
    payload_sha256: string;
    payload: unknown;
}>;

export type SyncReply = Readonly<{
    status: number;
    body: Readonly<{ outcome?: "created" | "duplicate" | "review" | "conflict" | "error"; server_id?: string; warnings?: readonly string[]; reason?: string }>;
}>;
export type LookupReply = Readonly<
    | { found: false }
    | { found: true; outcome: "accepted" | "accepted_warning" | "review" | "conflict"; server_id: string; warnings?: readonly string[]; reason?: string }
>;

export class SyncTransportError extends Error {
    readonly kind: "network" | "timeout";
    constructor(kind: "network" | "timeout") {
        super("SYNC_TRANSPORT_" + kind.toUpperCase());
        this.name = "SyncTransportError";
        this.kind = kind;
    }
}

export interface SyncTransport {
    /** POST: must be idempotent by `capture_id`. Throws SyncTransportError on network failure/timeout. */
    send(request: SyncRequest, options: { signal: AbortSignal }): Promise<SyncReply>;
    /** GET reconciliation by `capture_id` (used before ever repeating an uncertain send). */
    lookup(captureId: string, options: { signal: AbortSignal }): Promise<LookupReply>;
}

export type ClaimResult = Readonly<{ record: SyncRecord; recovered: boolean }> | null;
export type FinalizePatch = Readonly<Partial<Pick<SyncRecord, "state" | "nextAttemptAt" | "uncertain" | "lastError" | "serverRef" | "warnings" | "attempts">>>;

/** Persistent queue contract. Every method is atomic; `claim`/`finalize` are compare-and-swap on lease+state. */
export interface SyncQueueStore {
    enqueue(record: SyncRecord): Promise<{ created: boolean; record: SyncRecord }>;
    get(captureId: string): Promise<SyncRecord | null>;
    list(ownerId: string, deviceKey: string): Promise<SyncRecord[]>;
    /** Atomically take the record for sending if it is eligible at `now`; null when not eligible / lost the race. */
    claim(captureId: string, tabId: string, now: number, leaseMs: number): Promise<ClaimResult>;
    /** Apply a result ONLY if `tabId` still holds the lease on a `syncing` record. Returns false when the lease was lost. */
    finalize(captureId: string, tabId: string, patch: FinalizePatch, now: number): Promise<boolean>;
}

export type SyncPause = "session_invalid" | "different_user" | "auth_required" | "busy";
export type SyncOutcome = Readonly<{ capture_id: string; from: SyncState; to: SyncState; detail: string }>;
export type SyncCounts = Readonly<Record<SyncState, number>>;
export type SyncRunResult = Readonly<{
    paused: SyncPause | null;
    stopped: "network" | "timeout" | "server_error" | null;
    sent: number;
    reconciled: number;
    skipped: Readonly<{ waiting: number; blocked: number; busy: number }>;
    outcomes: readonly SyncOutcome[];
    counts: SyncCounts;
}>;
