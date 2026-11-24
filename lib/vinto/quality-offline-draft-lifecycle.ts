/**
 * Opt-in lifecycle for an existing Quality editor and an already verified
 * operational binding. This never creates authority, unlocks a vault, sends
 * data, or mounts a new UI. The identity and draftId must originate from the
 * trusted preparation, not from form fields or user-controlled browser text.
 */
import { createOperationalCaptureBindings } from "./offline-operational-capture-bindings";
import type { OfflineVaultIdentity } from "./offline-vault";

type Bindings = ReturnType<typeof createOperationalCaptureBindings>;
type Values = Readonly<Record<string, string | boolean>>;
export type QualityOfflineDraftState = Readonly<{
  revision: number; frozen: boolean; values: Values;
}>;
export type QualityOfflineDraftLifecycleDeps = Readonly<{
  bindings: Bindings;
  identity: OfflineVaultIdentity;
  draftId: string;
  /** Independently verified CAPTURE authority for initial preparation. */
  assertPreparedCaptureScope: () => Promise<void>;
}>;

/** Recover rather than overwrite whenever a draft exists. */
export function createQualityOfflineDraftLifecycle(deps: QualityOfflineDraftLifecycleDeps) {
  return {
    async recover(): Promise<QualityOfflineDraftState | null> {
      return deps.bindings.resume();
    },
    /**
     * Save an edit by compare-and-swap. The caller supplies the revision it
     * actually displayed: stale tabs and frozen captures must fail closed.
     * Incomplete measurements may be saved for later completion.
     */
    async save(values: Values, expectedRevision: number): Promise<QualityOfflineDraftState> {
      if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1)
        throw new Error("offline_draft_revision_invalid");
      const current = await deps.bindings.resume();
      if (!current || current.frozen || current.revision !== expectedRevision)
        throw new Error("offline_draft_conflict");
      const result = await deps.bindings.persist({
        draftId: deps.draftId,
        ownerId: deps.identity.ownerId,
        revision: expectedRevision,
        values,
      });
      return { revision: result.revision, frozen: false, values };
    },
    async prepare(initialValues: Values): Promise<QualityOfflineDraftState> {
      const existing = await deps.bindings.resume();
      if (existing) return existing;
      await deps.assertPreparedCaptureScope();
      // Re-read after asynchronous verification, to avoid resetting a draft
      // that was prepared in another tab or is already frozen.
      const concurrent = await deps.bindings.resume();
      if (concurrent) return concurrent;
      const result = await deps.bindings.persist({
        draftId: deps.draftId,
        ownerId: deps.identity.ownerId,
        revision: null,
        values: initialValues,
      });
      return {revision: result.revision, frozen: false, values: initialValues};
    },
  };
}
