/** OFF-04.8F — coalesced, owner-scoped local draft autosave.
 *
 * Does not queue, transmit, freeze, authorize or approve. The caller's
 * persist() MUST use the encrypted IndexedDB writer with expectedRevision CAS.
 * flush() is a durable barrier: it drains even changes made during an
 * in-flight write, so Save Capture never freezes stale values. Conflict and
 * storage failures are fail-closed; neither may silently become successful.
 */
export type DraftSaveSnapshot = Readonly<{
  draftId: string;
  ownerId: string;
  revision: number | null;
  values: Readonly<Record<string, string | boolean>>;
}>;
export type DraftAutosaveDeps = Readonly<{
  unlocked: () => boolean;
  current: () => DraftSaveSnapshot | null;
  persist: (snapshot: DraftSaveSnapshot) => Promise<{ revision: number }>;
  setTimer: (callback: () => void, milliseconds: number) => unknown;
  clearTimer: (timer: unknown) => void;
  onFailure?: (reason: "locked" | "conflict" | "storage") => void;
  onSaved?: (revision: number) => void;
}>;

export type DraftFlushResult = Readonly<{ ok: true; revision: number | null } | { ok: false; reason: "locked" | "conflict" | "storage" }>;

export function createDraftAutosave(deps: DraftAutosaveDeps, delayMs = 650) {
  if (!Number.isFinite(delayMs) || delayMs < 0) throw new TypeError("invalid autosave delay");
  let timer: unknown = null;
  let dirty = false;
  let changes = 0;
  let stopped = false;
  let blocked: "conflict" | "storage" | null = null;
  let inflight: Promise<void> | null = null;
  let lastRevision: number | null = null;

  const cancel = () => {
    if (timer !== null) deps.clearTimer(timer);
    timer = null;
  };
  const drain = async (): Promise<DraftFlushResult> => {
    cancel();
    if (blocked) return { ok: false, reason: blocked };
    if (stopped) return { ok: false, reason: "storage" };
    if (!deps.unlocked()) {
      deps.onFailure?.("locked");
      return { ok: false, reason: "locked" };
    }

    // New changes can arrive while a write is in progress: keep draining
    // until the revision corresponding to the LATEST input is durable.
    while (dirty || inflight !== null) {
      if (blocked) return { ok: false, reason: blocked };
      if (stopped || !deps.unlocked()) return { ok: false, reason: "locked" };
      if (inflight !== null) {
        await inflight;
        continue;
      }
      const snapshot = deps.current();
      if (!snapshot) return { ok: false, reason: "storage" };
      const revisionAtStart = changes;
      dirty = false;
      inflight = (async () => {
        try {
          const result = await deps.persist(snapshot);
          if (!Number.isSafeInteger(result.revision) || result.revision < 1) throw Error("storage");
          lastRevision = result.revision;
          deps.onSaved?.(result.revision);
        } catch (error) {
          dirty = true;
          blocked = error instanceof Error && error.message === "conflict" ? "conflict" : "storage";
          deps.onFailure?.(blocked);
        }
      })();
      await inflight;
      inflight = null;
      if (revisionAtStart !== changes) dirty = true;
    }
    if (blocked) return { ok: false, reason: blocked };
    return { ok: true, revision: lastRevision };
  };
  const schedule = () => {
    if (stopped || blocked || !dirty || timer !== null) return;
    timer = deps.setTimer(() => {
      timer = null;
      void drain();
    }, delayMs);
  };
  return {
    changed() {
      if (stopped || blocked) return;
      changes += 1;
      dirty = true;
      schedule();
    },
    /** Used by Save Capture: waits for the newest editor state to persist. */
    flush: drain,
    /** Called only after the user resolves a conflict or unlocks their vault. */
    retry() {
      if (stopped) return;
      blocked = null;
      schedule();
    },
    stop() {
      stopped = true;
      cancel();
      // Caller must await flush before planned navigation / editing switch.
    },
    get hasUnsavedChanges() { return dirty || inflight !== null; },
  };
}
