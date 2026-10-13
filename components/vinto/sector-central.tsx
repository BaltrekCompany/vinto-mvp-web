"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BobbinasProgramming } from "@/components/vinto/bobinas-programming";
import { P110History, P116History, P129History } from "@/components/vinto/central-form-history";
import { CentralStatus } from "@/components/vinto/central-status";
import { ContextBanner, type ExecState } from "@/components/vinto/context-banner";
import { Panel } from "@/components/vinto/panels";
import { CONVERSION_DISABLED_MESSAGE, CONVERSION_DISABLED_TITLE, DISABLED_MESSAGE, DISABLED_TITLE, articlesOf, offeredForms, sectorView, type FormScreen, type SectorAvailability } from "@/lib/vinto/availability";
import { listCapturesOf } from "@/lib/vinto/captures-api";
import { ASSIGNMENT_LABELS, CONTEXT_MESSAGES, WORK_ORDER_LABELS, contextFromActive, failureMessage, type CaptureContext } from "@/lib/vinto/orders";
import { P1_10_CODE, parseP110List } from "@/lib/vinto/p1-10";
import { P1_16_CODE, parseP116List } from "@/lib/vinto/p1-16";
import { P1_29_CODE, parseP129List } from "@/lib/vinto/p1-29";
import { useActiveAssignment, useAssignments, useAvailability, useResource, useWorkOrders } from "@/lib/vinto/use-central";

// Shell CENTRAL por sector (M4-A Rebobinado, M6-A Conversión): Jefatura crea/publica OT, Supervisión activa asignaciones, Operación abre los formularios que el backend publica para la máquina y Seguimiento
// muestra los registros centrales, TODO contra las APIs centrales. La disponibilidad (sector operativo, concesión, máquinas y formularios vinculados) la verifica el backend (GET /api/production/machines);
// sin ella la navegación se muestra como no habilitada. Nunca usa OT, asignaciones ni registros de localStorage o de demostración como respaldo, y no escribe nada en el navegador. Los formularios
// siguen siendo CANDIDATOS. Lo único que cambia entre sectores es la configuración de SECTORS: ni el motor ni las reglas de acceso se duplican.

export type SectorModule = "programacion" | "ejecucion" | "seguimiento";
export type RebobinadoModule = SectorModule;
export type CentralSector = "REBOBINADO" | "CONVERSION";

// `attr` conserva el atributo de datos propio de cada frente (data-rebobinado ya lo usan las pruebas E2E de M4-A).
const SECTORS: Record<CentralSector, { label: string; attr: "data-rebobinado" | "data-conversion"; disabledTitle: string; disabledMessage: string }> = {
    REBOBINADO: { label: "Rebobinado", attr: "data-rebobinado", disabledTitle: DISABLED_TITLE, disabledMessage: DISABLED_MESSAGE },
    CONVERSION: { label: "Conversión", attr: "data-conversion", disabledTitle: CONVERSION_DISABLED_TITLE, disabledMessage: CONVERSION_DISABLED_MESSAGE },
};
const tag = (sector: CentralSector, value: string) => ({ [SECTORS[sector].attr]: value });

export type SectorCentralProps = {
    module: SectorModule;
    canManageOrders: boolean;
    canManageAssignments: boolean;
    canCapture: boolean;
    canReadOrders: boolean;
    canReadAssignments: boolean;
    onOpenForm: (screen: FormScreen, context: CaptureContext) => void;
    refreshKey: number; // cambia tras un envío para refrescar el historial
    onSessionLost: () => void;
};
type Props = SectorCentralProps & { code: CentralSector };
type Inner = Props & { sector: SectorAvailability };

export function SectorCentral(props: Props) {
    const { module, canManageOrders, onSessionLost, code } = props;
    const config = SECTORS[code];
    const availability = useAvailability(canManageOrders && module === "programacion", true, onSessionLost); // la programación pide además los artículos de cada máquina
    if (availability.view.status !== "ready") return <CentralStatus state={availability.view} onRetry={availability.refresh} title={`No se pudo consultar la disponibilidad de ${config.label}`}/>;
    const view = sectorView(availability.view.data, code);
    if (view.kind === "disabled") return <div role="status" {...tag(code, "disabled")}><Panel title={config.disabledTitle} note={config.disabledMessage}><p className="text-sm text-slate-700">Habilitar {config.label} requiere datos maestros aprobados y un cambio de configuración revisado en el backend; no se puede activar desde esta pantalla.</p></Panel></div>;
    if (module === "programacion") return <Programming {...props} sector={view.sector}/>;
    if (module === "ejecucion") return <Execution {...props} sector={view.sector}/>;
    return <Tracking {...props} sector={view.sector}/>;
}

function Programming({ code, sector, canManageOrders, canManageAssignments, canReadOrders, onSessionLost }: Inner) {
    const workOrders = useWorkOrders(canReadOrders, onSessionLost);
    const machines = sector.machines.map(m => m.code);
    return <div {...tag(code, "programacion")}><BobbinasProgramming machines={machines} sectorLabel={SECTORS[code].label} catalog={machine => articlesOf(sector.machines.find(m => m.code === machine)).map(a => ({ code: a.code, name: a.description }))}
        workOrders={workOrders.view} onChanged={workOrders.refresh} onSessionLost={onSessionLost} canManageOrders={canManageOrders} canManageAssignments={canManageAssignments}/></div>;
}

function Execution({ code, sector, canCapture, canReadAssignments, onOpenForm, onSessionLost }: Inner) {
    const [machineCode, setMachineCode] = useState(sector.machines[0]?.code ?? "");
    const machine = sector.machines.find(m => m.code === machineCode) ?? sector.machines[0];
    const active = useActiveAssignment(machine.code, canReadAssignments, onSessionLost);
    let state: ExecState;
    if (!canReadAssignments) state = { kind: "error", message: "Acceso no permitido.", retry: active.refresh };
    else if (active.view.status === "ready") state = { kind: "check", check: contextFromActive(active.view.data) };
    else if (active.view.status === "error") state = { kind: "error", message: active.view.kind === "forbidden" ? "Acceso no permitido." : failureMessage(active.view.kind), retry: active.refresh };
    else state = { kind: "loading" };
    const select = (screen: FormScreen | null) => {
        if (!canCapture) return void toast.error("Tu perfil no tiene permiso para capturar en este frente");
        if (!screen) return void toast.error("Este formulario aún no tiene pantalla central");
        if (state.kind !== "check") return void toast.error("Aún se está consultando la asignación activa");
        if (!state.check.ok) return void toast.error(CONTEXT_MESSAGES[state.check.reason]);
        onOpenForm(screen, state.check.context);
    };
    const forms = offeredForms(machine);
    return <div {...tag(code, "ejecucion")}><Panel title="Punto de captura" note="La máquina y sus formularios los publica el backend; la OT y el producto llegan desde Supervisión (asignación central).">
        <div className="flex flex-wrap gap-2">{sector.machines.map(m => <Button key={m.code} size="sm" variant={machine.code === m.code ? "default" : "outline"} className={machine.code === m.code ? "bg-[#146b4f]" : ""} onClick={() => setMachineCode(m.code)}>{m.code}</Button>)}</div></Panel>
        <ContextBanner state={state} machine={machine.code}/>
        {!canCapture && <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">Tu perfil puede consultar este frente, pero no capturar en él.</div>}
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{forms.length === 0
            ? <p className="rounded-2xl border bg-white p-5 text-sm text-slate-700 md:col-span-2 xl:col-span-3">El backend no publica formularios centrales para esta máquina.</p>
            : forms.map(({ form, screen }) => <button key={form.code} data-form={form.code} disabled={screen === null} onClick={() => select(screen)} className="rounded-2xl border bg-white p-5 text-left shadow-sm hover:border-emerald-400 disabled:opacity-60">
                <Badge variant="outline" className="border-amber-300 text-amber-900">Ficha candidata</Badge><h3 className="mt-4 font-black">{form.name.replace(/^Formulario sintético /, "")}</h3><p className="mt-2 text-sm text-slate-700">{form.code} · v{form.version_number}</p>
                <p className="mt-4 border-t pt-3 text-xs font-semibold text-emerald-800">{screen ? "Abrir captura central" : "Sin pantalla central"}</p></button>)}</div></div>;
}

function Tracking({ code, sector, canReadOrders, canReadAssignments, canCapture, refreshKey, onSessionLost }: Inner) {
    const label = SECTORS[code].label;
    const workOrders = useWorkOrders(canReadOrders, onSessionLost);
    const assignments = useAssignments(canReadAssignments, onSessionLost);
    const machines = new Set(sector.machines.map(m => m.code));
    const offered = new Set(sector.machines.flatMap(m => m.forms.map(f => f.code)));
    // Un historial por formulario que el backend publica en ESTE sector: los demás no se consultan (el recurso queda deshabilitado).
    const p110 = useResource(`captures-p110:${refreshKey}`, canCapture && offered.has(P1_10_CODE), signal => listCapturesOf(parseP110List, signal, 50, P1_10_CODE), onSessionLost);
    const p116 = useResource(`captures-p116:${refreshKey}`, canCapture && offered.has(P1_16_CODE), signal => listCapturesOf(parseP116List, signal, 50, P1_16_CODE), onSessionLost);
    const p129 = useResource(`captures-p129:${refreshKey}`, canCapture && offered.has(P1_29_CODE), signal => listCapturesOf(parseP129List, signal, 50, P1_29_CODE), onSessionLost);
    const refresh = () => { workOrders.refresh(); assignments.refresh(); p110.refresh(); p116.refresh(); p129.refresh(); };
    if (workOrders.view.status !== "ready" || assignments.view.status !== "ready") return <div {...tag(code, "seguimiento")}><CentralStatus state={workOrders.view.status !== "ready" ? workOrders.view : assignments.view} onRetry={refresh}/></div>;
    const orders = workOrders.view.data.filter(o => machines.has(o.machine.code)), asg = assignments.view.data.filter(a => machines.has(a.machine.code));
    return <div className="space-y-5" {...tag(code, "seguimiento")}>
        <Panel title={`Órdenes de trabajo de ${label}`} note="Datos centrales (PostgreSQL); sin OT locales ni de demostración.">
            {orders.length === 0 ? <p className="text-sm text-slate-600">Sin OT de {label}.</p>
                : <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600"><th className="px-2 py-2">OT</th><th className="px-2 py-2">Máquina</th><th className="px-2 py-2">Estado</th><th className="px-2 py-2">Líneas</th></tr></thead>
                    <tbody>{orders.map(o => <tr key={o.id} className="border-b last:border-0"><td className="px-2 py-2">{o.number}</td><td className="px-2 py-2">{o.machine.code}</td><td className="px-2 py-2">{WORK_ORDER_LABELS[o.status]}</td><td className="px-2 py-2">{o.baseline.lines.length}</td></tr>)}</tbody></table></div>}
        </Panel>
        <Panel title={`Asignaciones de ${label}`} note="Máquina, turno y fecha operativa los resuelve el backend.">
            {asg.length === 0 ? <p className="text-sm text-slate-600">Sin asignaciones.</p>
                : <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-600"><th className="px-2 py-2">OT / línea</th><th className="px-2 py-2">Máquina</th><th className="px-2 py-2">Turno</th><th className="px-2 py-2">Fecha operativa</th><th className="px-2 py-2">Estado</th></tr></thead>
                    <tbody>{asg.map(a => <tr key={a.id} className="border-b last:border-0"><td className="px-2 py-2">{a.work_order.number} · {a.line.line_code}</td><td className="px-2 py-2">{a.machine.code}</td><td className="px-2 py-2">{a.shift.name}</td><td className="px-2 py-2">{a.operating_date}</td><td className="px-2 py-2">{ASSIGNMENT_LABELS[a.status]}</td></tr>)}</tbody></table></div>}
        </Panel>
        {canCapture && offered.has(P1_10_CODE) && <P110History resource={p110.view} refresh={p110.refresh}/>}
        {canCapture && offered.has(P1_16_CODE) && <P116History resource={p116.view} refresh={p116.refresh}/>}
        {canCapture && offered.has(P1_29_CODE) && <P129History resource={p129.view} refresh={p129.refresh}/>}
    </div>;
}
