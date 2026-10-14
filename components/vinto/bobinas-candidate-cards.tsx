"use client";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/vinto/panels";
import { BOBINAS_CANDIDATES } from "@/lib/vinto/bobinas-candidates";
import type { Availability } from "@/lib/vinto/availability";
import { candidateScreensFor, publishedCandidateScreens, type BobinasCandidateScreen } from "@/lib/vinto/bobinas-offers";
import type { Resource } from "@/lib/vinto/use-central";

// Fichas CANDIDATAS centrales de Bobinas (P1-05 y P1-31): se ofrecen SOLO si el backend las publica para la máquina elegida (GET /api/production/machines, formulario vinculado y habilitado por la política)
// y la sesión puede capturar. Con la configuración real el backend no las publica y este panel no se muestra. Nunca se usa localStorage ni una lista estática como respaldo.
// Con la disponibilidad aún sin cargar (o con error) no se ofrece nada: la decisión es de lib/vinto/bobinas-offers.ts.
export const offeredCandidates = (availability: Resource<Availability>, machineCode: string): BobinasCandidateScreen[] => availability.status === "ready" ? candidateScreensFor(availability.data, machineCode) : [];
export const publishedCandidates = (availability: Resource<Availability>): BobinasCandidateScreen[] => availability.status === "ready" ? publishedCandidateScreens(availability.data) : [];

export function BobinasCandidateCards({ offered, canCapture, onOpen }: { offered: BobinasCandidateScreen[]; canCapture: boolean; onOpen: (screen: BobinasCandidateScreen) => void }) {
    if (offered.length === 0) return null;
    return <div className="mt-5" data-section="candidate-forms"><Panel title="Fichas candidatas centrales" note="El backend publica estos formularios para la máquina. Son candidatos técnicos, no fichas homologadas.">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{offered.map(screen => { const c = BOBINAS_CANDIDATES[screen];
            return <button key={screen} data-form={c.code} disabled={!canCapture} onClick={() => onOpen(screen)} className="rounded-2xl border bg-white p-5 text-left shadow-sm hover:border-emerald-400 disabled:opacity-60">
                <Badge variant="outline" className="border-amber-300 text-amber-900">Ficha candidata</Badge><h3 className="mt-4 font-black">{c.title}</h3><p className="mt-2 text-sm text-slate-700">{c.code}</p>
                <p className="mt-4 border-t pt-3 text-xs font-semibold text-emerald-800">{canCapture ? "Abrir captura central" : "Tu perfil no puede capturar"}</p></button>; })}</div></Panel></div>;
}
