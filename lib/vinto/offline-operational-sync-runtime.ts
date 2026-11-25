/** OFF-04.8K — opt-in automatic OPERATIONAL Quality sync wiring.
 *
 * This is NOT mounted in app/main, any PWA page or the synthetic QA pilot.
 * It connects the atomic operational IndexedDB store to the existing
 * idempotent engine, requiring an OPERATIONAL ACK (not merely a receipt).
 * All transport, original-author online session, timers and window events
 * must come from the authenticated application. There is no direct fetch here.
 */
import { createAutoSyncScheduler } from "./offline-auto-sync.ts";
import { syncNow, type SyncOptions, type SessionInfo } from "./offline-sync-engine.ts";
import { openLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { OperationalLocalStore } from "./offline-operational-local-store.ts";
import type { SyncRecord, SyncRunResult, SyncTransport } from "./offline-sync-types.ts";

export type OperationalSyncRuntimeDeps = Readonly<{
  store: OperationalLocalStore;
  identity: OfflineVaultIdentity;
  /** Null means the original owner's encrypted vault is locked. */
  unlockedKey: () => CryptoKey | null;
  online: () => boolean;
  /** Must query the live server session, not a cached principal or client claim. */
  onlineSession: () => Promise<SessionInfo>;
  transport: SyncTransport;
  tabId: string;
  subscribe: (event: "online" | "focus" | "visible", listener: () => void) => () => void;
  setTimer: (callback: () => void, ms: number) => unknown;
  clearTimer: (timer: unknown) => void;
  onError?: (reason: "preparation_failed" | "sync_failed") => void;
  /** v6.1 (Issue #249): called after EVERY completed pass (automatic or manual) so the UI can redraw the queue. Purely presentational: it never receives the key or a payload,
   * cannot change the outcome, and an exception inside it is swallowed. */
  onRunComplete?: (result: SyncRunResult) => void;
  options?: Partial<Omit<SyncOptions, "requireOperationalAck">>;
}>;

export class OperationalSyncIntegrityError extends Error {
  readonly reason:"owner" | "scope" | "missing_pending" | "mismatch" | "payload";
  constructor(reason:OperationalSyncIntegrityError["reason"]) {
    super("OFF048_OPERATIONAL_SYNC_" + reason.toUpperCase());
    this.reason=reason;
  }
}

const eq = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
export async function openVerifiedOperationalPayload(
  store: OperationalLocalStore, identity: OfflineVaultIdentity, key: CryptoKey, record: SyncRecord,
): Promise<unknown> {
  if (!eq(record.ownerId, identity.ownerId) || !eq(record.deviceKey, identity.deviceKey))
    throw new OperationalSyncIntegrityError("owner");
  if (!record.scopeSnapshotId || !record.machineCode)
    throw new OperationalSyncIntegrityError("scope");
  // Only records created by the atomic confirmation may be uploaded. Never
  // send an orphan queue row or a row copied from the synthetic QA laboratory.
  const matching = (await store.listPending(identity.ownerId, identity.deviceKey))
    .filter(p => p.capture_id === record.capture_id);
  if (matching.length !== 1) throw new OperationalSyncIntegrityError("missing_pending");
  const pending = matching[0];
  if (pending.synthetic !== false ||
      pending.payloadSha256 !== record.payloadSha256 ||
      pending.sealed.iv !== record.sealed.iv ||
      pending.sealed.ciphertext !== record.sealed.ciphertext ||
      !eq(pending.ownerId, record.ownerId) || !eq(pending.deviceKey, record.deviceKey))
    throw new OperationalSyncIntegrityError("mismatch");

  const opened = await openLocalDraft(key, {
    ownerId: identity.ownerId, deviceKey: identity.deviceKey,
    id: record.capture_id, contextId: record.scopeSnapshotId,
    formCode: record.formCode, formVersion: record.formVersion,
  }, record.sealed);
  if (opened.synthetic !== false || !opened.payload || typeof opened.payload !== "object" ||
      Array.isArray(opened.payload))
    throw new OperationalSyncIntegrityError("payload");
  // The sync engine separately checks canonical payloadHash against its
  // immutable queue record before any request reaches the transport.
  return opened;
}

export function createOperationalSyncRuntime(deps: OperationalSyncRuntimeDeps) {
  const syncOnce = async (): Promise<SyncRunResult> => {
    if (!deps.online()) throw Error("offline");
    const key = deps.unlockedKey();
    if (!key) throw Error("vault_locked");
    // Hold the key used for this pass; locking the UI must not make the engine
    // misclassify a pending as permanently corrupt midway through a pass.
    const result = await syncNow({
      store: deps.store.sync,
      transport: deps.transport,
      identity: deps.identity,
      tabId: deps.tabId,
      session: deps.onlineSession,
      openPayload: (rec) => openVerifiedOperationalPayload(deps.store, deps.identity, key, rec),
      options: { ...deps.options, requireOperationalAck: true },
    });
    try { deps.onRunComplete?.(result); } catch { /* presentation only */ }
    return result;
  };
  const scheduler = createAutoSyncScheduler({
    online: deps.online,
    unlocked: () => deps.unlockedKey() !== null,
    // The operational store has already persisted the immutable pending and
    // queue in ONE transaction. Do not bridge or re-create any queue record.
    prepareQueue: async () => {},
    sync: syncOnce,
    subscribe: deps.subscribe,
    setTimer: deps.setTimer,
    clearTimer: deps.clearTimer,
    onError: deps.onError,
  });
  return { start: scheduler.start, stop: scheduler.stop,
    notifyReady: scheduler.notifyReady, syncOnce };
}
