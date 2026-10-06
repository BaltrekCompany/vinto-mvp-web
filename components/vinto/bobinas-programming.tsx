"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CentralStatus } from "@/components/vinto/central-status";
import { Panel, Select, Text } from "@/components/vinto/panels";
import { activateAssignment } from "@/lib/vinto/assignments-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { PRODUCTS_BY_MACHINE } from "@/lib/vinto/catalogs";
import { WORK_ORDER_LABELS, failureMessage, parseLineDraft, type WorkOrder } from "@/lib/vinto/orders";
import type { Resource } from "@/lib/vinto/use-central";
import { addWorkOrderLine, createWorkOrder, publishWorkOrder } from "@/lib/vinto/work-orders-api";

// TEMPORAL: el selector de productos sigue leyendo PRODUCTS_BY_MACHINE (aún no existe un endpoint de catálogo central) y solo
// se envía article_code. El backend valida máquina y artículo; si rechaza, se muestra el error y NO se crea nada.
// Debe migrar al catálogo central.
const catalogOf = (machine: string) => (PRODUCTS_BY_MACHINE as unknown as Record<string, readonly { code: string; name: string; unit: string }[]>)[machine] ?? [];

type Props = {
    machines: readonly string[];
    workOrders: Resource<WorkOrder[]>;
    onChanged: () => void;
    onSessionLost: () => void;
    canManageOrders: boolean;
    canManageAssignments: boolean;
};

// Programación de Bobinas contra las APIs centrales. Sin estado local de OT/asignaciones, sin optimismo: cada mutación
// espera la respuesta del backend (que es la autoridad de número, line_code, estado y fechas) y después se reconcilia con GET.
export function BobbinasProgramming({ machines, workOrders, onChanged, onSessionLost, canManageOrders, canManageAssignments }: Props) {
    const [machine, setMachine] = useState(machines[0] ?? ""), [pv, setPv] = useState(""), [code, setCode] = useState(""), [qty, setQty] = useState(""), [date, setDate] = useState("");
    const [busy, setBusy] = useState<string | null>(null);
    const catalog = catalogOf(machine);

    // Un solo request de escritura a la vez: evita dobles envíos y carreras entre botones.
    async function run<T>(key: string, action: () => Promise<ApiResult<T>>, onOk: (data: T) => void) {
        if (busy) return;
        setBusy(key);
        try {
            const result = await action();
            if (result.ok) { onOk(result.data); onChanged(); return; }
            if (result.kind === "session") { onSessionLost(); return; }
            toast.error(failureMessage(result.kind));
            if (result.kind === "conflict" || result.kind === "not_found") onChanged(); // el estado cambió: reconciliar
        } finally { setBusy(null); }
    }

    function draftOrComplain() {
        const draft = parseLineDraft({ pv, code, qty, date });
        if (!draft) toast.error("Completa PV, producto, cantidad y fecha");
        return draft;
    }
    function resetForm() { setPv(""); setCode(""); setQty(""); setDate(""); }

    function create() {
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        const draft = draftOrComplain();
        if (!draft) return;
        void run("create", () => createWorkOrder(machine, draft), (order) => { toast.success(`OT ${order.number} creada`); resetForm(); });
    }
    function addLine(order: WorkOrder) {
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        const draft = draftOrComplain();
        if (!draft) return;
        void run(`add:${order.id}`, () => addWorkOrderLine(order.id, draft), () => { toast.success("Línea añadida a la misma OT"); resetForm(); });
    }
    function publish(order: WorkOrder) {
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        void run(`publish:${order.id}`, () => publishWorkOrder(order.id), (published) => { toast.success(`OT ${published.number}: línea base publicada`); });
    }
    function activate(order: WorkOrder, lineId: string) {
        if (!canManageAssignments) return void toast.error("Tu perfil no puede asignar OT");
        void run(`activate:${lineId}`, () => activateAssignment(order.id, lineId), (activation) => {
            toast.success("OT, línea y producto enviados al punto de captura");
            if (activation.finished_assignment_id) toast.info(`La asignación anterior de ${activation.assignment.machine.code} fue finalizada.`);
            else if (activation.already_active) toast.info("La línea ya estaba activa para este turno.");
        });
    }

    if (workOrders.status !== "ready") return <CentralStatus state={workOrders} onRetry={onChanged}/>;
    const locked = busy !== null;
    return <div className="space-y-5">
        {canManageOrders ? <Panel title="Programa base de Jefatura" note="Una OT puede contener productos de varios PV. Supervisión opera una copia sin sobrescribir la línea base.">
            <div className="grid gap-4 md:grid-cols-5"><Select label="Máquina" value={machine} set={v => { setMachine(v); setCode(""); }} options={[...machines]} disabled={locked}/><Text label="PV" value={pv} set={setPv} disabled={locked}/><Select label="Producto" value={code} set={setCode} options={catalog.map(p => p.code)} disabled={locked} render={v => { const p = catalog.find(x => x.code === v); return p ? `${p.code} · ${p.name}` : v; }}/><Text label="Cantidad" value={qty} set={setQty} type="number" disabled={locked}/><Text label="Entrega" value={date} set={setDate} type="date" disabled={locked}/></div>
            <Button className="mt-5 bg-[#146b4f]" disabled={locked} onClick={create}>{busy === "create" ? "Creando…" : "Crear OT inicial"}</Button>
        </Panel> : <Panel title="Programa base" note="Tu perfil puede consultar las OT; su creación y publicación corresponden a Jefatura."><p className="text-sm text-slate-700">Solo lectura.</p></Panel>}
        {workOrders.data.length === 0 && <Panel title="Sin órdenes de trabajo" note="Todavía no hay OT de Bobinas en el servidor."><p className="text-sm text-slate-700">Jefatura puede crear la primera.</p></Panel>}
        {workOrders.data.map(order => <div key={order.id} className="overflow-hidden rounded-2xl border bg-white shadow-sm"><div className="flex flex-wrap justify-between gap-3 border-b p-5"><div><h3 className="font-black">{order.number} · {order.machine.code}</h3><p className="text-sm text-slate-600">Base v{order.baseline.version_number} · {order.baseline.lines.length} producto(s) · {new Set(order.baseline.lines.map(l => l.pv_reference)).size} PV</p></div><div className="flex gap-2"><Badge>{WORK_ORDER_LABELS[order.status]}</Badge>{canManageOrders && order.status === "draft" && <Button size="sm" variant="outline" disabled={locked} onClick={() => publish(order)}>{busy === `publish:${order.id}` ? "Publicando…" : "Publicar base"}</Button>}{canManageOrders && order.status === "draft" && <Button size="sm" variant="outline" disabled={locked} onClick={() => addLine(order)}>{busy === `add:${order.id}` ? "Añadiendo…" : "Añadir línea actual"}</Button>}</div></div>
            <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">Línea</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Cantidad</th><th className="p-3">Entrega</th><th className="p-3">Gestión</th></tr></thead><tbody>{order.baseline.lines.map(l => <tr key={l.id} className="border-t"><td className="p-3 font-bold">{l.line_code}</td><td className="p-3">{l.pv_reference}</td><td className="p-3"><b>{l.article.code}</b><br />{l.article.description}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{l.due_date}</td><td className="p-3">{canManageAssignments ? <Button size="sm" className="bg-[#146b4f]" disabled={locked || (order.status !== "published" && order.status !== "in_progress")} onClick={() => activate(order, l.id)}>{busy === `activate:${l.id}` ? "Activando…" : "Activar"}</Button> : <span className="text-slate-500">—</span>}</td></tr>)}</tbody></table></div></div>)}
    </div>;
}
