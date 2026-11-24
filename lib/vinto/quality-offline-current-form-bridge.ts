/**
 * Safe adapter between the EXISTING declarative Quality forms and the
 * OFF-04.8 operational capture bindings. No network or storage side effects.
 *
 * This is NOT a grant to capture offline. The caller must obtain and verify a
 * signed CAPTURE authority, the original session and a current form package;
 * the server validates all of those again before operational registration.
 */
import type { CandidateForm, CandidateDraft } from "./candidate-form";
import { resolveQualityOfflineTarget, type QualityOfflineTarget } from "./quality-offline-target";

export type CurrentQualityOfflineInput = Readonly<{
  form: CandidateForm;
  draft: CandidateDraft;
  machineCode: string;
  bobbinId?: string;
  bobbinContextDigest?: string;
  formVersion: number;
  scopeSnapshotId: string;
  contextVersion: string;
}>;

export type PreparedQualityOfflineInput = Readonly<{
  target: QualityOfflineTarget;
  formVersion: number;
  scopeSnapshotId: string;
  contextVersion: string;
  values: Readonly<Record<string, string>>;
  bobbin?: Readonly<{bobbin_id: string; context_digest: string}>;
}>;

export function prepareCurrentQualityOfflineInput(input: CurrentQualityOfflineInput):
  {ok: true; value: PreparedQualityOfflineInput} | {ok: false; reason: string} {
  const target = resolveQualityOfflineTarget(input.form.code, {
    machineCode: input.machineCode, bobbinId: input.bobbinId,
  });
  if (!target || target.kind !== input.form.context) return {ok: false, reason: "context_invalid"};
  if (!Number.isSafeInteger(input.formVersion) || input.formVersion < 1 ||
      !input.scopeSnapshotId.trim() || !input.contextVersion.trim())
    return {ok: false, reason: "authority_context_missing"};

  if (target.kind === "bobbin" && !input.bobbinContextDigest?.trim())
    return {ok: false, reason: "bobbin_context_missing"};
  if (target.kind === "machine" && input.bobbinContextDigest)
    return {ok: false, reason: "unexpected_bobbin_context"};

  // Reuse the exact field validation of the existing online form.
  const check = input.form.normalizeDraft(input.draft);
  if (!check.ok) return {ok: false, reason: "invalid_fields"};
  return {ok: true, value: {
    target, formVersion: input.formVersion, scopeSnapshotId: input.scopeSnapshotId,
    contextVersion: input.contextVersion, values: check.values,
    ...(target.kind === "bobbin" ? {bobbin: {
      bobbin_id: target.bobbinId, context_digest: input.bobbinContextDigest!,
    }} : {}),
  }};
}
