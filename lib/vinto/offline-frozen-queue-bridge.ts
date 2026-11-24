/** OFF-04.8F — isolated operational frozen-pending -> send queue recovery.
 *
 * Intended as AutoSyncDeps.prepareQueue. It NEVER turns a synthetic lab
 * pending into an industrial capture, NEVER changes its original author or
 * capture_id, and NEVER deletes/rebinds a frozen source. The producer and
 * queue operations are injected by the future operational PWA implementation.
 */
export type OperationalPendingRef = Readonly<{
  captureId: string;
  ownerId: string;
  deviceKey: string;
  synthetic: false;
}>;
export type FrozenBridgeDeps = Readonly<{
  unlockedIdentity: () => Readonly<{ownerId: string; deviceKey: string}> | null;
  /** Must list only owner-scoped encrypted and authenticated pending headers. */
  list: (identity: Readonly<{ownerId: string; deviceKey: string}>) => Promise<readonly OperationalPendingRef[]>;
  /** Must validate AAD, hash and frozen snapshot before idempotent enqueue. */
  enqueue: (pending: OperationalPendingRef) => Promise<void>;
  onQuarantine?: (captureId: string, reason: "identity_mismatch" | "invalid_kind" | "storage") => void;
}>;
export type FrozenBridgeResult = Readonly<{queuedOrExisting: number; quarantined: number; deferred: boolean}>;

export async function bridgeOperationalPendings(deps: FrozenBridgeDeps): Promise<FrozenBridgeResult> {
  const identity = deps.unlockedIdentity();
  if (!identity) return {queuedOrExisting:0, quarantined:0, deferred:true};
  const same = (a:string,b:string) => a.toLowerCase() === b.toLowerCase();
  // listing failure aborts. The records remain untouched and auto-sync retries.
  const list = await deps.list(identity);
  let queuedOrExisting = 0, quarantined = 0;
  const seen = new Set<string>();
  for (const candidate of list) {
    const captureId = candidate.captureId.toLowerCase();
    if (seen.has(captureId)) continue;
    seen.add(captureId);
    if (!same(candidate.ownerId, identity.ownerId) || !same(candidate.deviceKey, identity.deviceKey)) {
      quarantined++;
      deps.onQuarantine?.(captureId, "identity_mismatch");
      continue;
    }
    if (candidate.synthetic !== false) {
      quarantined++;
      deps.onQuarantine?.(captureId, "invalid_kind");
      continue;
    }
    // A different unlocked account must not be able to continue this batch.
    const current = deps.unlockedIdentity();
    if (!current || !same(current.ownerId, identity.ownerId) || !same(current.deviceKey, identity.deviceKey)) {
      return {queuedOrExisting, quarantined, deferred:true};
    }
    try {
      await deps.enqueue(candidate);
      queuedOrExisting++;
    } catch {
      quarantined++;
      deps.onQuarantine?.(captureId, "storage");
      // Each record remains locally frozen and recoverable: do not block others.
    }
  }
  return {queuedOrExisting, quarantined, deferred:false};
}
