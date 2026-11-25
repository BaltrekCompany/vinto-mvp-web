/**
 * Contract for attaching the offline capture engine to the EXISTING Quality
 * screens. This module has no network, storage, or UI side effects.
 *
 * A form must be offered by the existing server-side availability and current
 * authorization checks before a caller may use this mapping. This is NOT an
 * offline permission grant. A missing machine/bobbin is always rejected.
 */
import { BOBBIN_SCREEN_BY_FORM, QUALITY_SCREEN_BY_FORM } from "./quality-offers";

export type QualityOfflineTarget =
  | { formCode: string; kind: "machine"; machineCode: string }
  | { formCode: string; kind: "bobbin"; machineCode: string; bobbinId: string };

const BOBBIN_LEGACY = new Set(["VINTO-P1-19", "VINTO-P1-20"]);

export function resolveQualityOfflineTarget(
  formCode: string,
  context: { machineCode?: string | null; bobbinId?: string | null },
): QualityOfflineTarget | null {
  const machineCode = context.machineCode?.trim();
  if (!machineCode) return null;

  if (Object.prototype.hasOwnProperty.call(QUALITY_SCREEN_BY_FORM, formCode)) {
    // Machine controls must not silently inherit a bobbin context.
    if (context.bobbinId) return null;
    return { formCode, kind: "machine", machineCode };
  }

  if (Object.prototype.hasOwnProperty.call(BOBBIN_SCREEN_BY_FORM, formCode) ||
      BOBBIN_LEGACY.has(formCode)) {
    const bobbinId = context.bobbinId?.trim();
    if (!bobbinId) return null;
    return { formCode, kind: "bobbin", machineCode, bobbinId };
  }
  return null;
}
