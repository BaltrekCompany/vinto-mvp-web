/**
 * VINTO Quality: fail-closed queue adapter for the existing ten form screens.
 * No component mounts this automatically: an authenticated, verified
 * preparation flow must inject bindings for the ORIGINAL author and device.
 *
 * Do not create a second local draft from the same snapshot after freezing:
 * callers must prepare a new draftId for each new capture.
 */
import type { PreparedQualityOfflineInput } from "./quality-offline-current-form-bridge";
import type { LegacyQualityOfflinePayload } from "./quality-offline-legacy-bridge";
import { createOperationalCaptureBindings } from "./offline-operational-capture-bindings";
import type { OperationalCaptureBindingsDeps } from "./offline-operational-capture-bindings";

export type QualityOfflinePrepared = PreparedQualityOfflineInput | LegacyQualityOfflinePayload;
export type QualityOfflineQueuePort = (prepared: QualityOfflinePrepared) => Promise<{captureId: string}>;

type BindingPort = ReturnType<typeof createOperationalCaptureBindings>;
export type QualityOfflineQueueDependencies = Readonly<{
  /**
   * Only the verified, capture-capable offline preparation may create this.
   * It MUST enforce authenticated owner/device, signed scope, and persisted
   * draftId for the selected machine, bobbin and form version.
   */
  bindingsFor: (prepared: QualityOfflinePrepared) => Promise<BindingPort>;
  /** Reuse the ORIGINAL form validator. Raw editable values have empty optional
   * fields and cannot be compared directly with the normalized upload values.
   */
  normalizeDraft: (prepared:QualityOfflinePrepared,
    editable:Readonly<Record<string,string|boolean>>)=>Readonly<Record<string,string|boolean>>;
  onQueued?: (captureId: string) => void;
}>;

const sameValues = (
  a: Readonly<Record<string,string|boolean>>,
  b: Readonly<Record<string,string|boolean>>,
):boolean => {
  const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
  return ka.length === kb.length && ka.every((key,i) => key === kb[i] && a[key] === b[key]);
};

export function createQualityOfflineQueuePort(deps: QualityOfflineQueueDependencies): QualityOfflineQueuePort {
  return async (prepared) => {
    // No implicit default context, automatic authorization, or silent fallback.
    if (!prepared || !prepared.target || !prepared.scopeSnapshotId ||
        !prepared.contextVersion || !Number.isSafeInteger(prepared.formVersion) ||
        prepared.formVersion < 1) throw new Error("offline_preparation_missing");
    if (prepared.target.kind === "bobbin" &&
        (!prepared.bobbin || prepared.bobbin.bobbin_id !== prepared.target.bobbinId ||
         !prepared.bobbin.context_digest)) throw new Error("offline_bobbin_context_invalid");
    if (prepared.target.kind === "machine" && prepared.bobbin)
      throw new Error("offline_machine_context_invalid");

    const bindings = await deps.bindingsFor(prepared);
    const prior = await bindings.resume();
    const values = prepared.values;
    let revision:number;
    if (prior) {
      // Never replace a preserved draft or an immutable capture silently.
      const normalised = deps.normalizeDraft(prepared, prior.values);
      if (!sameValues(normalised, values)) throw new Error("offline_draft_conflict");
      revision = prior.revision;
    } else {
      // The verified binding controls stable draftId and original owner.
      // The operation is intentionally single-context; no synthetic fixture.
      throw new Error("offline_draft_not_initialized");
    }

    // freeze performs signed CAPTURE revalidation, validation of full fields,
    // deterministic capture ID and atomic draft+pending+queue confirmation.
    const confirmed = await bindings.freeze(revision);
    if (!confirmed.captureId) throw new Error("offline_capture_unconfirmed");
    try { deps.onQueued?.(confirmed.captureId); } catch { /* notification only */ }
    return {captureId: confirmed.captureId};
  };
}

/**
 * A safe constructor for the verified runtime binding. This does not unlock
 * the vault or grant scope: callers MUST provide the actual vault key,
 * original owner and a signed authority verifier.
 */
export function createVerifiedQualityBindings(deps:OperationalCaptureBindingsDeps) {
  return createOperationalCaptureBindings(deps);
}
