/** FOFF-02: read-only projection from effective backend eligibility.
 * This is NOT an offline authorization or a persisted grant.
 * Missing eligible=true means no offer, including old/incomplete responses.
 */
import type { Availability } from "./availability.ts";
import { onlyEligible } from "./eligibility.ts";

export const OFFLINE_PRODUCTION_FRONTS = [
  { sector: "CONVERSION", label: "Conversión" },
  { sector: "REBOBINADO", label: "Rebobinado" },
  { sector: "BOBINAS", label: "Bobinas" },
] as const;

export type OfflineProductionForm = Readonly<{ code: string; name: string; version: number }>;
export type OfflineProductionMachine = Readonly<{ code: string; name: string; forms: readonly OfflineProductionForm[] }>;
export type OfflineProductionFront = Readonly<{ code: string; label: string; machines: readonly OfflineProductionMachine[] }>;

export function authorizedOfflineProductionNavigation(availability: Availability): OfflineProductionFront[] {
  const eligible = onlyEligible(availability);
  return OFFLINE_PRODUCTION_FRONTS.flatMap(({ sector, label }) => {
    const source = eligible.sectors.find((item) => item.code === sector);
    if (!source) return [];
    const machines = source.machines.flatMap((machine) => {
      const all = [...machine.forms, ...(machine.bobbin_forms ?? [])];
      const forms = all
        .filter((form) => form.eligible === true && Number.isSafeInteger(form.version_number) && form.version_number > 0)
        .map((form) => ({ code: form.code, name: form.name, version: form.version_number }));
      return forms.length ? [{ code: machine.code, name: machine.name, forms }] : [];
    });
    return machines.length ? [{ code: sector, label, machines }] : [];
  });
}
