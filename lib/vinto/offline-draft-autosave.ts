/** OFF-04.8G — encrypted local-draft autosave, NOT submission.
 *
 * The operational caller must bind persist() to a revision-CAS encrypted
 * IndexedDB write and may only expose this session's owner-scoped draft.
 * Save Capture must lock the editor BEFORE calling flush(), then freeze the
 * returned durable revision in the same vault. Never queue on autosave.
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
export type DraftFlushResult = Readonly<
  { ok: true; revision: number | null } |
  { ok: false; reason: "locked" | "conflict" | "storage" }
>;
export const DEFAULT_AUTOSAVE_DELAY_MS = 1500;

export function createDraftAutosave(deps: DraftAutosaveDeps, delayMs = DEFAULT_AUTOSAVE_DELAY_MS) {
  if (!Number.isFinite(delayMs) || delayMs < 0) throw new TypeError("invalid autosave delay");
  let timer: unknown = null;
  let dirty = false;
  let stopped = false;
  let blocked: "conflict" | "storage" | null = null;
  let draining: Promise<DraftFlushResult> | null = null;
  let lastRevision: number | null = null;

  const cancel = () => {
    if (timer !== null) deps.clearTimer(timer);
    timer = null;
  };
  const notify = (reason: "locked" | "conflict" | "storage"): DraftFlushResult => {
    deps.onFailure?.(reason);
    return { ok: false, reason };
  };
  const drainOnce = async (): Promise<DraftFlushResult> => {
    if (stopped) return notify("storage");
    if (blocked) return { ok: false, reason: blocked };
    if (!deps.unlocked()) return notify("locked");
    while (dirty) {
      if (stopped) return notify("storage");
      if (blocked) return { ok: false, reason: blocked };
      if (!deps.unlocked()) return notify("locked");
      const snapshot = deps.current();
      if (!snapshot) return notify("storage");
      dirty = false;
      try {
        const result = await deps.persist(snapshot);
        if (!Number.isSafeInteger(result.revision) || result.revision < 1) throw Error("storage");
        lastRevision = result.revision;
        deps.onSaved?.(result.revision);
        // If changed() was called while persist() awaited, dirty is set again
        // and the next loop persists the LATEST snapshot with the new CAS revision.
      } catch (error) {
        dirty = true;
        blocked = error instanceof Error &&
          (error.message === "conflict" ||
           (typeof (error as {reason?:unknown}).reason === "string" &&
            (error as {reason:string}).reason === "conflict"))
          ? "conflict" : "storage";
        return notify(blocked);
      }
    }
    // Opening an existing clean draft and pressing Save Capture must not lose
    // its durable revision just because no new edits were made in this session.
    const current = deps.current();
    return { ok: true, revision: lastRevision ?? current?.revision ?? null };
  };
  const schedule = () => {
    if (stopped || blocked || !dirty || timer !== null || draining !== null) return;
    timer = deps.setTimer(() => {
      timer = null;
      void flush();
    }, delayMs);
  };
  const flush = (): Promise<DraftFlushResult> => {
    cancel();
    // All simultaneous callers share one drain operation and cannot issue
    // competing writes against the same revision.
    if (draining !== null) return draining;
    const promise = drainOnce();
    draining = promise;
    void promise.finally(() => {
      if (draining === promise) draining = null;
      schedule();
    });
    return promise;
  };
  return {
    changed() {
      if (stopped || blocked) return;
      dirty = true;
      schedule();
    },
    flush,
    retry() {
      if (stopped) return;
      blocked = null;
      schedule();
    },
    stop() {
      stopped = true;
      cancel();
      // In-flight CAS may finish; the owner-scoped record is never sent here.
    },
    get hasUnsavedChanges() { return dirty || draining !== null; },
  };
}
