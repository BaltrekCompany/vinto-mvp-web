/**
 * Port for the existing P1-19 and P1-20 screens. It reuses their exact
 * online field validators; no alternate schema or calculated values are sent.
 * The caller must supply a verified offline CAPTURE authority separately.
 */
import { normalizeHumidityDraft, Q19_FORM_CODE, type HumidityDraft } from "./quality-captures";
import { normalizePhysicalDraft, Q20_FORM_CODE, type PhysicalDraft } from "./quality-physical";
import { resolveQualityOfflineTarget } from "./quality-offline-target";

export type LegacyQualityOfflineForm =
  | { formCode: typeof Q19_FORM_CODE; draft: HumidityDraft }
  | { formCode: typeof Q20_FORM_CODE; draft: PhysicalDraft };

export type LegacyQualityOfflineContext = Readonly<{
  machineCode: string;
  bobbinId: string;
  formVersion: number;
  scopeSnapshotId: string;
  contextVersion: string;
  bobbinContextDigest: string;
}>;

export type LegacyQualityOfflinePayload = Readonly<{
  target: { formCode: string; kind: "bobbin"; machineCode: string; bobbinId: string };
  formVersion: number;
  scopeSnapshotId: string;
  contextVersion: string;
  bobbin: { bobbin_id: string; context_digest: string };
  values: Readonly<Record<string, string>>;
}>;

export function prepareLegacyQualityOfflineCapture(
  form: LegacyQualityOfflineForm, context: LegacyQualityOfflineContext,
): {ok: true; value: LegacyQualityOfflinePayload} | {ok: false; reason: string} {
  const target = resolveQualityOfflineTarget(form.formCode, context);
  if (!target || target.kind !== "bobbin") return {ok: false, reason: "context_invalid"};
  if (!Number.isSafeInteger(context.formVersion) || context.formVersion < 1 ||
    !context.scopeSnapshotId.trim() || !context.contextVersion.trim() ||
    !context.bobbinContextDigest.trim())
    return {ok: false, reason: "authority_context_missing"};
  const check = form.formCode === Q19_FORM_CODE
    ? normalizeHumidityDraft(form.draft)
    : normalizePhysicalDraft(form.draft);
  if (!check.ok) return {ok: false, reason: "invalid_fields"};
  return {ok: true, value: {
    target, formVersion: context.formVersion,
    scopeSnapshotId: context.scopeSnapshotId,
    contextVersion: context.contextVersion,
    bobbin: {bobbin_id: target.bobbinId, context_digest: context.bobbinContextDigest},
    values: check.values,
  }};
}
