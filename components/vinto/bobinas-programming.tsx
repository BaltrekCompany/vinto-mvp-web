"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { ActivateAllDialog } from "@/components/vinto/activate-all-dialog";
import { LineExecutionPanel } from "@/components/vinto/line-execution-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CentralStatus } from "@/components/vinto/central-status";
import { OrderDraftEditor, type CatalogItem, type MachineOption } from "@/components/vinto/order-draft-editor";
import { Panel } from "@/components/vinto/panels";
import { activateAssignment } from "@/lib/vinto/assignments-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { PRODUCTS_BY_MACHINE } from "@/lib/vinto/catalogs";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import { emptyRow, normalizeForMode, summarize, summaryText, validateRows, type DraftRow, type RowError } from "@/lib/vinto/order-draft";
import { WORK_ORDER_LABELS, failureMessage, type FailureKind, type LineDraft, type WorkOrder } from "@/lib/vinto/orders";
import type { Resource } from "@/lib/vinto/use-central";
import { NO_CAPABILITIES, massActivationOffered, multiMachineOffered, lineExecutionOffered, type CapabilityStatus, type WorkOrderCapabilities } from "@/lib/vinto/work-order-capabilities";
import { addWorkOrderLine, createWorkOrderWithLines, publishWorkOrder } from "@/lib/vinto/work-orders-api";

// TEMPORAL (solo cuando el llamador no entrega `creation`): lista estática de Bobinas. NO es fuente de autorización: el backend valida máquina, artículo y relación artículo-máquina y,
// si rechaza, se muestra el error y NO se crea nada. La pantalla de Bobinas ya entrega el catálogo que el backend publica para la sesión (bobinas-programming-source.tsx).
const catalogOf = (machine: string) => (PRODUCTS_BY_MACHINE as unknown as Record<string, readonly { code: string; name: string; unit: string }[]>)[machine] ?? [];

export type Creation = { machines: readonly MachineOption[]; catalog: (machine: string) => readonly CatalogItem[] } | "loading" | "unavailable";

type Props = {
    machines: readonly string[];
    catalog?: (machine: string) => readonly CatalogItem[]; // por defecto la lista estática temporal de Bobinas; Rebobinado pasa los artículos que verifica el backend
    creation?: Creation; // máquinas y productos que el BACKEND ofrece a la sesión para crear (puede incluir varios sectores autorizados)
    capabilities?: WorkOrderCapabilities; // lo que el SERVIDOR confirmó; por defecto la creación multimáquina está apagada
    capabilityStatus?: CapabilityStatus; // estado de esa consulta: solo cambia el aviso; nunca habilita nada
    scope?: string; // sessionScope(user): el diálogo de activación masiva y su plan pertenecen a ESTA sesión
    onCapabilitiesStale?: () => void; // el servidor respondió MULTI_MACHINE_DISABLED: volver a pedir las capacidades
    initialRows?: DraftRow[]; // solo para renderizar un borrador conocido (pruebas)
    sectorLabel?: string;
    workOrders: Resource<WorkOrder[]>;
    onChanged: () => void;
    onSessionLost: () => void;
    canManageOrders: boolean;
    canManageAssignments: boolean;
};

// Aviso cuando la creación multimáquina no se ofrece. Solo informa: loading/error/«no habilitado» producen el mismo flujo tradicional.
function capabilityNote(status: CapabilityStatus): string {
    if (status === "loading") return "Confirmando con el servidor si admite OT con líneas en varias máquinas…";
    if (status === "error") return "No se pudo confirmar si el servidor admite OT con líneas en varias máquinas; se usa el flujo de una sola máquina.";
    return "Las OT con líneas en varias máquinas no están habilitadas por el servidor.";
}

const machinesOf = (order: WorkOrder) => [...new Set(order.baseline.lines.map(line => line.machine.code))];

// Programación de OT contra las APIs centrales. Sin estado local de OT/asignaciones persistidas, sin optimismo: cada mutación espera la respuesta del backend (que es la autoridad de número,
// line_code, estado y fechas) y después se reconcilia con GET. El ÚNICO estado local es el borrador de una OT nueva (filas aún no enviadas) y el de «añadir línea» de un borrador.
export function BobbinasProgramming({ machines, catalog: catalogOfMachine = catalogOf, creation, capabilities = NO_CAPABILITIES, capabilityStatus = "ready", scope = "", onCapabilitiesStale, initialRows, sectorLabel = "Bobinas", workOrders, onChanged, onSessionLost, canManageOrders, canManageAssignments }: Props) {
    const options = creation === undefined ? { machines: machines.map(code => ({ code, name: code })), catalog: catalogOfMachine } : creation;
    const optionMachines = typeof options === "string" ? [] : options.machines;
    const optionCatalog = typeof options === "string" ? () => [] : options.catalog;
    const multi = multiMachineOffered(capabilities, canManageOrders, optionMachines.length);
    const executionEnabled = lineExecutionOffered(capabilities, canManageAssignments);
    const keyCounter = useRef(1);
    const nextKey = () => `r${++keyCounter.current}`;
    const [storedRows, setRows] = useState<DraftRow[]>(() => initialRows ?? [emptyRow("r1", optionMachines[0]?.code ?? "")]);
    const rows = normalizeForMode(storedRows, multi, optionCatalog); // si el servidor deja de confirmar la multimáquina, el borrador vuelve a una sola máquina
    const [errors, setErrors] = useState<RowError[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [confirming, setConfirming] = useState<WorkOrder | null>(null);
    // Activación masiva (PR7): el diálogo guarda el plan (y su hash) solo en memoria, ligado a la sesión y a la OT. `blockedBy` recuerda la respuesta de capacidades que el servidor desmintió con
    // MULTI_MACHINE_DISABLED: se vuelve a habilitar únicamente si una nueva consulta al servidor confirma `true` (objeto distinto).
    const [massOrder, setMassOrder] = useState<{ scope: string; id: string; number: string } | null>(null);
    const invoker = useRef<HTMLElement | null>(null); // PR-A (DEF-1): botón que abrió el diálogo; el foco vuelve a él (o a su tarjeta / al panel si ya no sirve)
    const panel = useRef<HTMLDivElement | null>(null);
    const [blockedBy, setBlockedBy] = useState<WorkOrderCapabilities | null>(null);
    const [executionRevision, setExecutionRevision] = useState(0);
    const [guard] = useState(createMutationGuard);
    useEffect(() => () => guard.reset(), [guard]); // al desmontar (o perder la sesión) las respuestas tardías se descartan

    // Una sola escritura a la vez (doble envío): la segunda no sale. Una respuesta tardía (pantalla ya desmontada) no toca el borrador ni muestra avisos (runGuarded, probado en scripts/pr6-order-draft.test.mjs).
    function run<T>(key: string, action: () => Promise<ApiResult<T>>, onOk: (data: T) => void) {
        void runGuarded(guard, action, {
            onStart: () => setBusy(key),
            onOk: data => { onOk(data); onChanged(); },
            onSession: onSessionLost,
            onFailure: kind => { // el borrador NO se descarta: Jefatura puede corregir y reintentar
                toast.error(failureMessage(kind as FailureKind));
                if (kind === "conflict" || kind === "not_found") onChanged(); // el estado cambió: reconciliar
            },
            onSettled: () => setBusy(null),
        });
    }

    function create() {
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        const checked = validateRows(rows, { multi, machines: optionMachines.map(m => m.code), catalog: optionCatalog });
        if (!checked.ok) { setErrors(checked.errors); return void toast.error(checked.message); }
        setErrors([]);
        // UNA sola solicitud con todas las líneas; la máquina principal de la OT es la de la primera fila. El número de OT y los line_code los devuelve el servidor.
        run("create", () => createWorkOrderWithLines(checked.machineCode, checked.lines), (order) => { toast.success(`OT ${order.number} creada`); setRows([emptyRow(nextKey(), optionMachines[0]?.code ?? "")]); });
    }
    function addLine(order: WorkOrder, draft: LineDraft) {
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        run(`add:${order.id}`, () => addWorkOrderLine(order.id, draft), () => { toast.success("Línea añadida a la misma OT"); });
    }
    function publish(order: WorkOrder) {
        setConfirming(null);
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        run(`publish:${order.id}`, () => publishWorkOrder(order.id), (published) => { toast.success(`OT ${published.number}: línea base publicada`); });
    }
    function activate(order: WorkOrder, lineId: string) {
        if (!canManageAssignments) return void toast.error("Tu perfil no puede asignar OT");
        run(`activate:${lineId}`, () => activateAssignment(order.id, lineId), (activation) => {
            setExecutionRevision(n => n + 1);
            toast.success("OT, línea y producto enviados al punto de captura");
            if (activation.finished_assignment_id) toast.info(`La asignación anterior de ${activation.assignment.machine.code} fue finalizada.`);
            else if (activation.already_active) toast.info("La línea ya estaba activa para este turno.");
        });
    }

    if (workOrders.status !== "ready") return <CentralStatus state={workOrders} onRetry={onChanged}/>;
    const orders = workOrders.data.filter(order => machines.includes(order.machine.code)); // solo las OT de las máquinas de este sector (el backend puede devolver otras si el usuario tiene varios sectores)
    const locked = busy !== null;
    return <div ref={panel} tabIndex={-1} className="space-y-5 outline-none">
        {canManageOrders ? <Panel title="Programa base de Jefatura" note={multi ? "Una OT puede contener productos de varios PV y de varias máquinas. Supervisión opera una copia sin sobrescribir la línea base." : "Una OT puede contener productos de varios PV. Supervisión opera una copia sin sobrescribir la línea base."}>
            {typeof options === "string"
                ? <p role="status" className="text-sm text-slate-700">{options === "loading" ? "Consultando las máquinas y productos habilitados…" : "No se pudo consultar el catálogo de máquinas y productos; la creación de OT no está disponible por ahora."}</p>
                : <>
                    <OrderDraftEditor rows={rows} onRows={setRows} machines={options.machines} catalog={options.catalog} multi={multi} disabled={locked} errors={errors} nextKey={nextKey}/>
                    <div className="mt-5 flex flex-wrap items-center gap-4">
                        <Button className="bg-[#146b4f]" disabled={locked} onClick={create}>{busy === "create" ? "Creando…" : multi ? "Crear OT con estas líneas" : rows.length > 1 ? "Crear OT con estas líneas" : "Crear OT inicial"}</Button>
                        <p data-create-summary="" className="text-sm text-slate-700">Se enviará una sola OT: {summaryText(summarize(rows))}. El número y los códigos de línea los asigna el servidor.</p>
                    </div>
                    {!multi && <p data-multi-off="" data-capability={capabilityStatus} className="mt-3 text-xs text-slate-600">OT de una sola máquina. {capabilityNote(capabilityStatus)}</p>}
                </>}
        </Panel> : <Panel title="Programa base" note="Tu perfil puede consultar las OT; su creación y publicación corresponden a Jefatura."><p className="text-sm text-slate-700">Solo lectura.</p></Panel>}
        {orders.length === 0 && <Panel title="Sin órdenes de trabajo" note={`Todavía no hay OT de ${sectorLabel} en el servidor.`}><p className="text-sm text-slate-700">Jefatura puede crear la primera.</p></Panel>}
        {orders.map(order => {
            const orderMachines = machinesOf(order);
            return <div key={order.id} data-work-order={order.number} tabIndex={-1} className="overflow-hidden rounded-2xl border bg-white shadow-sm outline-none"><div className="flex flex-wrap justify-between gap-3 border-b p-5"><div><h3 className="font-black">{order.number} · {order.machine.code}</h3><p className="text-sm text-slate-600">Base v{order.baseline.version_number} · {order.baseline.lines.length} producto(s) · {new Set(order.baseline.lines.map(l => l.pv_reference)).size} PV · máquina(s): {orderMachines.join(", ")}</p>{orderMachines.length > 1 && <p className="text-xs text-slate-500">Máquina principal de la OT: {order.machine.code}</p>}</div><div className="flex flex-wrap items-center gap-2"><Badge>{WORK_ORDER_LABELS[order.status]}</Badge>{canManageAssignments && blockedBy !== capabilities && massActivationOffered(capabilities, canManageAssignments, order.status) && <Button size="sm" className="bg-[#146b4f]" disabled={locked} onClick={event => { invoker.current = event.currentTarget; setMassOrder({ scope, id: order.id, number: order.number }); }}>{executionEnabled ? "Habilitar todas las líneas" : "Activar todas las líneas"}</Button>}{canManageOrders && order.status === "draft" && <Button size="sm" variant="outline" disabled={locked} onClick={() => setConfirming(order)}>{busy === `publish:${order.id}` ? "Publicando…" : "Publicar base"}</Button>}</div></div>
                <div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">Línea</th><th className="p-3">Máquina</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Cantidad</th><th className="p-3">Entrega</th><th className="p-3">Gestión</th></tr></thead><tbody>{order.baseline.lines.map(l => <tr key={l.id} className="border-t"><td className="p-3 font-bold">{l.line_code}</td><td className="p-3" data-line-machine="">{l.machine.code}</td><td className="p-3">{l.pv_reference}</td><td className="p-3"><b>{l.article.code}</b><br />{l.article.description}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{l.due_date}</td><td className="p-3">{canManageAssignments ? <Button size="sm" className="bg-[#146b4f]" disabled={locked || (order.status !== "published" && order.status !== "in_progress")} onClick={() => activate(order, l.id)}>{busy === `activate:${l.id}` ? "Habilitando…" : executionEnabled ? "Habilitar" : "Activar"}</Button> : <span className="text-slate-500">—</span>}</td></tr>)}</tbody></table></div>
                {executionEnabled && (order.status === "published" || order.status === "in_progress") &&
                    <LineExecutionPanel key={scope + ":" + order.id} order={order} scope={scope} refreshRevision={executionRevision}
                        lockedExternal={locked} onChanged={onChanged} onSessionLost={onSessionLost}/>}
                {canManageOrders && order.status === "draft" && typeof options !== "string" && <AddLine order={order} options={options} multi={multi} disabled={locked} busy={busy === `add:${order.id}`} nextKey={nextKey} onAdd={draft => addLine(order, draft)}/>}
            </div>;
        })}
        {massOrder && massOrder.scope === scope && <ActivateAllDialog key={`${massOrder.scope}:${massOrder.id}`} lineExecutionEnabled={executionEnabled} orderId={massOrder.id} orderNumber={massOrder.number} onClose={() => setMassOrder(null)} returnFocusTargets={() => [invoker.current, invoker.current?.closest<HTMLElement>("[data-work-order]"), panel.current]} onSessionLost={onSessionLost} onApplied={() => { setExecutionRevision(n => n + 1); onChanged(); }}
            onDisabled={() => { setBlockedBy(capabilities); onCapabilitiesStale?.(); }}/>}
        <AlertDialog open={confirming !== null} onOpenChange={open => { if (!open) setConfirming(null); }}>
            <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Publicar la línea base de {confirming?.number}</AlertDialogTitle>
                <AlertDialogDescription>{confirming ? `La OT tiene ${confirming.baseline.lines.length} línea(s) en ${machinesOf(confirming).length} máquina(s): ${machinesOf(confirming).join(", ")}. ` : ""}Una vez publicada, la línea base es inmutable: no se podrán modificar ni retirar sus líneas. Supervisión operará una copia.</AlertDialogDescription></AlertDialogHeader>
                <AlertDialogFooter><AlertDialogCancel>Cancelar</AlertDialogCancel><AlertDialogAction onClick={() => confirming && publish(confirming)}>Publicar base</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
        </AlertDialog>
    </div>;
}


// «Añadir línea» a un borrador YA persistido: una fila, con el mismo contrato (POST /api/work-orders/{id}/lines). Una OT tradicional solo ofrece su máquina y NO envía machine_code.
function AddLine({ order, options, multi, disabled, busy, nextKey, onAdd }: { order: WorkOrder; options: { machines: readonly MachineOption[]; catalog: (machine: string) => readonly CatalogItem[] }; multi: boolean; disabled: boolean; busy: boolean; nextKey: () => string; onAdd: (draft: LineDraft) => void }) {
    const machines = multi ? options.machines : options.machines.filter(m => m.code === order.machine.code);
    const [row, setRow] = useState<DraftRow>(() => emptyRow(nextKey(), order.machine.code));
    const [errors, setErrors] = useState<RowError[]>([]);
    function submit() {
        const checked = validateRows([row], { multi, machines: machines.map(m => m.code), catalog: options.catalog });
        if (!checked.ok) { setErrors(checked.errors); return void toast.error(checked.message); }
        setErrors([]);
        onAdd(checked.lines[0]);
        setRow(emptyRow(nextKey(), order.machine.code));
    }
    return <details className="border-t p-4"><summary className="cursor-pointer text-sm font-bold">Añadir una línea a este borrador</summary>
        <div className="mt-3 space-y-3"><OrderDraftEditor rows={[row]} onRows={next => setRow(next[0])} machines={machines} catalog={options.catalog} multi={multi} disabled={disabled} errors={errors} nextKey={nextKey} fixedRows/>
            <Button size="sm" variant="outline" disabled={disabled} onClick={submit}>{busy ? "Añadiendo…" : "Añadir línea"}</Button></div></details>;
}
