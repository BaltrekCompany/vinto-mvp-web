"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CandidateHistory } from "@/components/vinto/candidate-history";
import { CentralStatus } from "@/components/vinto/central-status";
import { Panel } from "@/components/vinto/panels";
import { getQualityMachineForms } from "@/lib/vinto/candidate-form-api";
import type { CandidateCapture } from "@/lib/vinto/candidate-form";
import { qualityMachines, qualityScreensFor, type QualityCandidateScreen } from "@/lib/vinto/quality-offers";
import { QUALITY_CANDIDATES } from "@/lib/vinto/quality-candidates";
import { candidateHistoryKey } from "@/lib/vinto/resource-view";
import { useResource } from "@/lib/vinto/use-central";

// Controles de Calidad POR MÁQUINA (DEV-Q1, candidatos P1-22 y P1-26): sin bobina, asignación ni OT. La disponibilidad (qué formularios publica el backend para cada máquina) viene de
// GET /api/quality/machine-forms; con la política real el backend no publica ninguno y este panel no ofrece nada. Los recursos llevan el identificador de sesión en la clave (nunca se ve la vista de otra
// cuenta). Nunca se usa localStorage ni listas estáticas; un control registrado no libera, aprueba ni rechaza ninguna bobina.
type Props = {
    scope: string; // sessionScope(user)
    canCapture: boolean; // quality.capture
    mode: "execution" | "tracking"; // Ejecución: tarjetas + historial; Seguimiento: solo historial
    refreshKey: number; // cambia tras un envío para recargar el historial
    onOpen: (screen: QualityCandidateScreen, machine: { code: string; name: string }) => void;
    onSessionLost: () => void;
};

export function QualityMachineControls({ scope, canCapture, mode, refreshKey, onOpen, onSessionLost }: Props) {
    const forms = useResource(`quality-machine-forms:${scope}`, canCapture, signal => getQualityMachineForms(signal), onSessionLost);
    const [chosen, setChosen] = useState<string | null>(null);
    const machines = forms.view.status === "ready" ? qualityMachines(forms.view.data) : [];
    const machine = machines.find(m => m.code === chosen) ?? machines[0];
    const offered = forms.view.status === "ready" && machine ? qualityScreensFor(forms.view.data, machine.code) : [];
    const code = machine?.code ?? "";
    const history = {
        p122: useResource<CandidateCapture[]>(candidateHistoryKey(`p122-${code}`, scope, refreshKey), canCapture && offered.includes("p122"), signal => QUALITY_CANDIDATES.p122.machineApi.list(code, signal), onSessionLost),
        p126: useResource<CandidateCapture[]>(candidateHistoryKey(`p126-${code}`, scope, refreshKey), canCapture && offered.includes("p126"), signal => QUALITY_CANDIDATES.p126.machineApi.list(code, signal), onSessionLost),
    };
    if (!canCapture) return null;
    if (forms.view.status === "error") return <div className="mt-5" data-section="quality-machine-controls"><CentralStatus state={forms.view} onRetry={forms.refresh} title="No se pudo consultar los controles por máquina"/></div>;
    if (!machine || offered.length === 0) return null; // el backend no publica controles por máquina para esta sesión: no se muestra nada
    return <div className="mt-5 space-y-5" data-section="quality-machine-controls">
        <Panel title="Controles de Calidad por máquina (candidatos)" note="El backend publica estos controles para la máquina. Son candidatos técnicos, sin bobina ni OT, y no liberan ni rechazan nada.">
            <div className="flex flex-wrap gap-2">{machines.map(m => <Button key={m.code} size="sm" variant={machine.code === m.code ? "default" : "outline"} className={machine.code === m.code ? "bg-[#146b4f]" : ""} onClick={() => setChosen(m.code)}>{m.code}</Button>)}</div>
            {mode === "execution" && <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{offered.map(screen => { const c = QUALITY_CANDIDATES[screen];
                return <button key={screen} data-form={c.code} onClick={() => onOpen(screen, { code: machine.code, name: machine.name })} className="rounded-2xl border bg-white p-5 text-left shadow-sm hover:border-emerald-400">
                    <Badge variant="outline" className="border-amber-300 text-amber-900">Control candidato</Badge><h3 className="mt-4 font-black">{c.title}</h3><p className="mt-2 text-sm text-slate-700">{c.code} · {machine.code}</p>
                    <p className="mt-4 border-t pt-3 text-xs font-semibold text-emerald-800">Abrir captura central</p></button>; })}</div>}
        </Panel>
        {offered.map(screen => <CandidateHistory key={screen} candidate={QUALITY_CANDIDATES[screen]} resource={history[screen].view} refresh={history[screen].refresh}/>)}
    </div>;
}
