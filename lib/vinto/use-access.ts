// MF-13-02 · Hook de acceso de la sesión: pide al backend la disponibilidad elegible (producción y, con quality.capture, los dos listados de Calidad), deriva los frentes visibles y la
// revalida al volver a la pestaña y al recuperar la conexión. Un error de conexión / 503 deja el estado SIN CONFIRMAR: nunca se conservan accesos como confirmados.
import { useEffect } from "react";
import type { Availability } from "@/lib/vinto/availability";
import { getQualityBobbinForms, getQualityMachineForms } from "@/lib/vinto/candidate-form-api";
import { deriveAccess, type AccessState } from "@/lib/vinto/eligibility";
import { requestRevalidation } from "@/lib/vinto/revalidation";
import type { Resource } from "@/lib/vinto/resource-view";
import { useAvailability, useResource } from "@/lib/vinto/use-central";

export type Access = { state: AccessState; production: Resource<Availability>; qualityBobbin: Resource<Availability>; qualityMachine: Resource<Availability>; retry: () => void };

export function useAccess(input: { enabled: boolean; canManage: boolean; canQuality: boolean; scope: string; onUnauthorized: () => void }): Access {
    const { enabled, canManage, canQuality, scope, onUnauthorized } = input;
    const production = useAvailability(false, enabled, onUnauthorized, scope);
    const qualityBobbin = useResource<Availability>(`quality-bobbin-forms:${scope}`, enabled && canQuality, (signal) => getQualityBobbinForms(signal), onUnauthorized, true);
    const qualityMachine = useResource<Availability>(`quality-machine-forms:${scope}`, enabled && canQuality, (signal) => getQualityMachineForms(signal), onUnauthorized, true);
    useEffect(() => {
        if (!enabled) return;
        const onVisible = () => { if (document.visibilityState === "visible") requestRevalidation(); };
        const onOnline = () => { requestRevalidation(); };
        document.addEventListener("visibilitychange", onVisible);
        addEventListener("online", onOnline);
        return () => { document.removeEventListener("visibilitychange", onVisible); removeEventListener("online", onOnline); };
    }, [enabled]);
    const view = (r: Resource<Availability>) => (r.status === "ready" ? { status: "ready" as const, data: r.data } : r.status === "error" ? { status: "error" as const, kind: r.kind } : { status: r.status });
    const state = deriveAccess({ canManage, canQuality, production: view(production.view), qualityBobbin: view(qualityBobbin.view), qualityMachine: view(qualityMachine.view) });
    return { state, production: production.view, qualityBobbin: qualityBobbin.view, qualityMachine: qualityMachine.view, retry: () => { production.refresh(); qualityBobbin.refresh(); qualityMachine.refresh(); } };
}
