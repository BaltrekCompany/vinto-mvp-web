/**
 * Opt-in composition for a previously enrolled Quality device.
 *
 * The caller supplies an already unlocked vault key and a trusted public-key
 * pin from authenticated enrolment. No UI, network, credentials, migrations or
 * production routes are created here. Any invalid CAPTURE scope fails closed.
 */
import { verifyCaptureBeforeEditor, type OperationalCaptureGateDeps } from "./offline-operational-capture-gate";
import { createOperationalLocalStore, type OperationalLocalStore } from "./offline-operational-local-store";
import { createOperationalCaptureBindings, type OperationalFormContext } from "./offline-operational-capture-bindings";
import { createQualityOfflineDraftLifecycle } from "./quality-offline-draft-lifecycle";
import type { OfflineVaultIdentity } from "./offline-vault";

export type PreparedQualityDeviceDeps = Readonly<{
  identity: OfflineVaultIdentity;
  key: CryptoKey;
  context: OperationalFormContext;
  captureAuthority: OperationalCaptureGateDeps;
  /** The same exact field rules as the current online Quality form. */
  validateComplete: (values: Readonly<Record<string,string|boolean>>) => void;
  store?: OperationalLocalStore;
}>;

export async function prepareQualityDevice(deps: PreparedQualityDeviceDeps) {
  const {identity, context, captureAuthority} = deps;
  const target = captureAuthority.target;
  if (captureAuthority.identity.ownerId.toLowerCase() !== identity.ownerId.toLowerCase() ||
      captureAuthority.identity.deviceKey.toLowerCase() !== identity.deviceKey.toLowerCase() ||
      target.scopeSnapshotId !== context.scopeSnapshotId ||
      target.machineCode !== context.machineCode ||
      target.formCode !== context.formCode ||
      target.formVersion !== context.formVersion)
    throw new Error("offline_quality_preparation_mismatch");

  // The verifier only accepts the separately signed CAPTURE authority, never
  // readiness-only envelopes. It also requires the trusted pinned signing key.
  const verified = await verifyCaptureBeforeEditor(captureAuthority);
  const store = deps.store ?? createOperationalLocalStore();
  const bindings = createOperationalCaptureBindings({
    key: deps.key, identity, context, store,
    assertCaptureScope: verified.assertCaptureScope,
    validateComplete: deps.validateComplete,
  });
  const draft = createQualityOfflineDraftLifecycle({
    bindings, draftId: context.draftId, identity,
    assertPreparedCaptureScope: verified.assertCaptureScope,
  });
  return { draft, bindings, store };
}
