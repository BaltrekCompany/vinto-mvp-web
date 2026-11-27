"use client";

/** FOFF-02: navigation ONLY; capturing offline remains disabled until FOFF-03/04/05.
 * Availability and eligibility are read from authenticated backend data, never
 * from static lists or persisted UI permissions.
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Availability } from "@/lib/vinto/availability";
import { authorizedOfflineProductionNavigation } from "@/lib/vinto/foff-navigation";

export function FoffModuleSelector({ availability, onExit }: {
  availability: Availability;
  onExit: () => void;
}) {
  const fronts = authorizedOfflineProductionNavigation(availability);
  const [frontCode, setFrontCode] = useState<string | null>(null);
  const [machineCode, setMachineCode] = useState<string | null>(null);
  const front = fronts.find((f) => f.code === frontCode) ?? fronts[0];
  const machine = front?.machines.find((m) => m.code === machineCode) ?? front?.machines[0];

  return <main className="mx-auto max-w-4xl space-y-5 p-4 md:p-8" data-foff="selector">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold">Front operativo · Offline</h1>
        <p className="text-sm text-slate-600">Módulos y fichas publicados para tu cuenta y máquina.</p>
      </div>
      <Button variant="outline" onClick={onExit}>Volver a VINTO</Button>
    </div>
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950" role="status">
      FOFF-02: selector en preparación. Los formularios de producción todavía no admiten captura sin internet.
      Conéctate y utiliza las pantallas originales hasta que cada módulo sea habilitado y probado.
    </div>
    {fronts.length === 0 ? <p role="status">No hay formularios de producción autorizados disponibles.</p> : <>
      <section aria-label="Módulos autorizados" className="space-y-2">
        <h2 className="font-semibold">1. Selecciona el módulo</h2>
        <div className="flex flex-wrap gap-2">
          {fronts.map((item) => <Button key={item.code} variant={item.code === front?.code ? "default" : "outline"} onClick={() => { setFrontCode(item.code); setMachineCode(null); }}>{item.label}</Button>)}
        </div>
      </section>
      <section aria-label="Máquinas autorizadas" className="space-y-2">
        <h2 className="font-semibold">2. Selecciona la máquina</h2>
        <div className="flex flex-wrap gap-2">
          {front?.machines.map((item) => <Button key={item.code} variant={item.code === machine?.code ? "default" : "outline"} onClick={() => setMachineCode(item.code)}>{item.name}</Button>)}
        </div>
      </section>
      <section aria-label="Formularios publicados" className="space-y-2">
        <h2 className="font-semibold">3. Formularios habilitados</h2>
        <ul className="grid gap-2 md:grid-cols-2">
          {machine?.forms.map((item) => <li key={item.code} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="font-semibold">{item.name}</div>
            <div className="text-sm text-slate-600">{item.code} · versión {item.version}</div>
            <p className="mt-2 text-xs text-amber-800">Captura offline pendiente de implementación</p>
          </li>)}
        </ul>
      </section>
    </>}
  </main>;
}
