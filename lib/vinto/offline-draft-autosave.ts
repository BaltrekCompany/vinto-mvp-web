/** OFF-04.8E: opt-in, coalesced and revision-safe local draft autosave.
 *
 * Keeps the form editable and saves work automatically while the operator types.
 * Does NOT freeze, queue, transmit or authorize a capture. "Guardar captura" must
 * remain a separate explicit action, performed by the operator only once the
 * form is complete. The injected persist function must use the encrypted
 * IndexedDB draft writer with expectedRevision CAS to avoid stale overwrites.
 *
 * Never mounted in the old synthetic QA lab or the operational app yet.
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
export function createDraftAutosave(deps: DraftAutosaveDeps, delayMs = 650) {
  if (!Number.isFinite(delayMs) || delayMs < 0) throw new TypeError("invalid autosave delay");
  let timer: unknown = null;
  let running = false;
  let dirty = false;
  let stopped = false;
  let blocked = false;
  let inflight: Promise<void> | null = null;
  const cancel = () => {
    if (timer !== null) deps.clearTimer(timer);
    timer = null;
  };
  const schedule = () => {
    if (stopped || blocked || !dirty || timer !== null || running) return;
    timer = deps.setTimer(() => {
      timer = null;
      void flush();
    }, delayMs);
  };
  const flush = async (): Promise<void> => {
    cancel();
    if (stopped || blocked || !dirty) return;
    if (running) {
      await inflight;
      return;
    }
    if (!deps.unlocked()) {
      deps.onFailure?.("locked");
      return; // keep dirty, do not save plaintext
    }
    const snapshot = deps.current();
    if (!snapshot) return;
    dirty = false;
    running = true;
    const doSave = async () => {
      try {
        const result = await deps.persist(snapshot);
        // The integration must update the editor's CAS revision; it may not
        // blindly overwrite a newer draft from another tab.
        deps.onSaved?.(result.revision);
      } catch (error) {
        dirty = true;
        blocked = true; // a conflict must be explicitly resolved, not retried forever
        const reason = error instanceof Error && error.message === "conflict" ? "conflict" : "storage";
        deps.onFailure?.(reason);
      } finally {
        running = false;
        inflight = null;
        schedule();
      }
    };
    inflight = doSave();
    await inflight;
  };
  return {
    changed() {
      if (stopped || blocked) return;
      dirty = true;
      schedule();
    },
    flush,
    /** Resume after session unlock, or after user resolves a draft conflict. */
    retry() {
      if (stopped) return;
      blocked = false;
      schedule();
    },
    stop() {
      stopped = true;
      cancel();
      // A caller MUST await flush before navigation when safe to do so;
      // stopping intentionally prevents a late dirty write after owner switch.
    },
    get hasUnsavedChanges() { return dirty; },
  };
}
