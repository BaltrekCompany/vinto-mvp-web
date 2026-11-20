/** OFF-04.8F — Save Capture command for the future operational UI.
 *
 * A single operator click waits until the LATEST encrypted draft revision is
 * durable, freezes the exact revision (stable capture_id), puts that immutable
 * pending in the idempotent queue, and wakes auto-sync if online.
 *
 * No separate "prepare", "authorize", "move to queue", or "sync" button. No
 * automatic capture submission from typing/autosave. No production caller yet.
 */
import type { DraftFlushResult } from "./offline-draft-autosave.ts";

export type CaptureConfirmResult =
  | Readonly<{ status: "queued"; captureId: string; created: boolean }>
  | Readonly<{ status: "blocked"; reason: "locked" | "conflict" | "storage" | "incomplete" | "invalid" | "context_changed" }>;

export type CaptureConfirmDeps = Readonly<{
  /** Flushes every outstanding edit, not merely a stale scheduled write. */
  flushDraft: () => Promise<DraftFlushResult>;
  /** Atomic encrypted draft->pending with expected revision CAS. */
  freeze: (expectedRevision: number) => Promise<{ captureId: string; created: boolean }>;
  /** Idempotent pending->sync queue; must keep frozen pending on failure. */
  enqueueFrozen: (captureId: string) => Promise<void>;
  /** Only schedules work: does NOT grant access or bypass active session. */
  notifySync: () => void;
  /** Never log or expose field values. */
  onBlocked?: (reason: Exclude<CaptureConfirmResult, {status: "queued"}>["reason"]) => void;
}>;

export function createCaptureConfirmer(deps: CaptureConfirmDeps) {
  let current: Promise<CaptureConfirmResult> | null = null;
  return {
    confirm(): Promise<CaptureConfirmResult> {
      // A double tap / multiple handlers in the same tab are one operation.
      if (current !== null) return current;
      const execute = async (): Promise<CaptureConfirmResult> => {
        const flush = await deps.flushDraft();
        if (!flush.ok) {
          deps.onBlocked?.(flush.reason);
          return { status: "blocked", reason: flush.reason };
        }
        if (!Number.isSafeInteger(flush.revision) || flush.revision === null || flush.revision < 1) {
          deps.onBlocked?.("incomplete");
          return { status: "blocked", reason: "incomplete" };
        }
        let frozen: { captureId: string; created: boolean };
        try {
          frozen = await deps.freeze(flush.revision);
        } catch (error) {
          const code = error instanceof Error ? error.message : "";
          const reason = (["conflict", "incomplete", "invalid", "context_changed"] as const).find(x => x === code) ?? "storage";
          deps.onBlocked?.(reason);
          return { status: "blocked", reason };
        }
        // The local pending is now immutable. A queue failure must NOT reverse
        // or delete it; the next startup/reconnect can bridge it again.
        try {
          await deps.enqueueFrozen(frozen.captureId);
        } catch {
          deps.onBlocked?.("storage");
          return { status: "blocked", reason: "storage" };
        }
        try {
          deps.notifySync();
        } catch {
          // Wake failure does not invalidate a durable queued record; the next
          // online/focus/startup event retries it.
        }
        return { status: "queued", captureId: frozen.captureId, created: frozen.created };
      };
      current = execute().finally(() => { current = null; });
      return current;
    },
  };
}
