/** VINTO OFF-04.8G — headless editor wiring, no synthetic or production route mounted.
 *
 * This is a UI boundary around the reviewed encrypted autosave and Save
 * Capture services. No API, scope issuer or sender is enabled by importing it.
 * The future PWA must inject a CURRENT-owner CAS writer and immutable
 * transition backed by IndexedDB (not the synthetic QA laboratory store).
 */
import { createDraftAutosave, DEFAULT_AUTOSAVE_DELAY_MS, type DraftSaveSnapshot } from "./offline-draft-autosave.ts";
import { createCaptureConfirmer, type CaptureConfirmResult } from "./offline-confirm-capture.ts";

export type EditorWorkflowDeps = Readonly<{
  unlocked: () => boolean;
  current: () => DraftSaveSnapshot | null;
  persistDraft: (snapshot: DraftSaveSnapshot) => Promise<{ revision: number }>;
  freezeDraft: (revision: number) => Promise<{ captureId: string; created: boolean }>;
  enqueueFrozen: (captureId: string) => Promise<void>;
  notifySync: () => void;
  /** Prevent field edits / screen changes during the final save-and-freeze. */
  setEditorLocked: (locked: boolean) => void;
  setTimer: (callback: () => void, ms: number) => unknown;
  clearTimer: (timer: unknown) => void;
  onDraftSaved?: (revision: number) => void;
  onDraftError?: (reason: "locked" | "conflict" | "storage") => void;
  onCaptureBlocked?: (reason: Exclude<CaptureConfirmResult, {status:"queued"}>["reason"]) => void;
}>;

export function createOfflineCaptureEditorWorkflow(deps: EditorWorkflowDeps) {
  let stopped = false;
  let confirming = false;
  const autosave = createDraftAutosave({
    unlocked: deps.unlocked,
    current: deps.current,
    persist: deps.persistDraft,
    setTimer: deps.setTimer,
    clearTimer: deps.clearTimer,
    onFailure: deps.onDraftError,
    onSaved: deps.onDraftSaved,
  }, DEFAULT_AUTOSAVE_DELAY_MS);

  const confirmer = createCaptureConfirmer({
    flushDraft: autosave.flush,
    freeze: deps.freezeDraft,
    enqueueFrozen: deps.enqueueFrozen,
    notifySync: deps.notifySync,
    onBlocked: deps.onCaptureBlocked,
  });
  return {
    onFieldEdited() {
      if (stopped || confirming) return;
      autosave.changed();
    },
    /**
     * Called only by the operator pressing "Guardar captura". Lock the editor
     * synchronously before yielding to async storage, so late input cannot
     * mutate the revision being frozen.
     */
    async onGuardarCaptura(): Promise<CaptureConfirmResult> {
      if (stopped) return {status:"blocked",reason:"storage"};
      if (confirming) return {status:"blocked",reason:"conflict"};
      confirming = true;
      deps.setEditorLocked(true);
      try {
        const result = await confirmer.confirm();
        if (result.status === "queued") {
          // A confirmed capture is immutable; never unlock this editor.
          autosave.stop();
          stopped = true;
        }
        return result;
      } finally {
        confirming = false;
        if (!stopped) deps.setEditorLocked(false);
      }
    },
    /** Call this before switching forms or signing out. The caller may block navigation on failure. */
    flushDraft: autosave.flush,
    retryAfterUnlockOrConflict: autosave.retry,
    stop() { stopped = true; autosave.stop(); },
    get hasUnsavedChanges() { return autosave.hasUnsavedChanges; },
  };
}
