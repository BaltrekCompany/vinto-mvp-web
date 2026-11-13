"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { ActivateAllDialog } from "@/components/vinto/activate-all-dialog";
import { LineExecutionPanel } from "@/components/vinto/line-execution-panel";
import { SupervisedHandoffPanel } from "@/components/vinto/supervised-handoff-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CentralStatus } from "@/components/vinto/central-status";
import { OrderDraftEditor, type CatalogItem, type MachineOption } from "@/components/vinto/order-draft-editor";
import { Panel } from "@/components/vinto/panels";
import { activateAssignment } from "@/lib/vinto/assignments-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import { PRODUCTS_BY_MACHINE } from "@/lib/vinto/catalogs";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import { emptyRow, normalizeForMode, summarize, summaryText, validateRows, type DraftRow, type RowError } from "@/lib/vinto/order-draft";
import { WORK_ORDER_LABELS, failureMessage, type FailureKind, type LineDraft, type WorkOrder, type WorkOrderLine } from "@/lib/vinto/orders";
import { useResource, type Resource } from "@/lib/vinto/use-central";
import { NO_CAPABILITIES, massActivationOffered, multiMachineOffered, type CapabilityStatus, type WorkOrderCapabilities } from "@/lib/vinto/work-order-capabilities";
import { addWorkOrderLine, archiveWorkOrder, createWorkOrderWithLines, editDraftWorkOrderLine, listArchivedWorkOrders, listWorkOrderRevisions, reprogramPublishedLine, publishWorkOrder, restoreWorkOrder } from "@/lib/vinto/work-orders-api";

// TEMPORAL (solo cuando el llamador no entrega `creation`): lista estática de Bobinas. NO es fuente de autorización: el backend valida máquina, artículo y relación artículo-máquina y,
// si rechaza, se muestra el error y NO se crea nada. La pantalla de Bobinas ya entrega el catálogo que el backend publica para la sesión (bobinas-programming-source.tsx).
const catalogOf = (machine: string) => (PRODUCTS_BY_MACHINE as unknown as Record<string, readonly { code: string; name: string; unit: string }[]>)[machine] ?? [];

export type Creation = { machines: readonly MachineOption[]; catalog: (machine: string) => readonly CatalogItem[] } | "loading" | "unavailable";

type Props = {
    machines: readonly string[];
    catalog?: (machine: string) => readonly CatalogItem[]; // por defecto la lista estática temporal de Bobinas; Rebobinado pasa los artículos que verifica el backend
    creation?: Creation; // máquinas y productos que el BACKEND ofrece a la sesión para crear (puede incluir varios sectores autorizados)
    capabilities?: WorkOrderCapabilities; // lo que el SERVIDOR confirmó; por defecto la creación multimáquina está apagada
    executionEnabled?: boolean; // confirmación separada del servidor para el flujo inicio/finalización
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
export function BobbinasProgramming({ machines, catalog: catalogOfMachine = catalogOf, creation, capabilities = NO_CAPABILITIES, executionEnabled = false, capabilityStatus = "ready", scope = "", onCapabilitiesStale, initialRows, sectorLabel = "Bobinas", workOrders, onChanged, onSessionLost, canManageOrders, canManageAssignments }: Props) {
    const options = creation === undefined ? { machines: machines.map(code => ({ code, name: code })), catalog: catalogOfMachine } : creation;
    const optionMachines = typeof options === "string" ? [] : options.machines;
    const optionCatalog = typeof options === "string" ? () => [] : options.catalog;
    const multi = multiMachineOffered(capabilities, canManageOrders, optionMachines.length);
    const keyCounter = useRef(1);
    const nextKey = () => `r${++keyCounter.current}`;
    const [storedRows, setRows] = useState<DraftRow[]>(() => initialRows ?? [emptyRow("r1", optionMachines[0]?.code ?? "")]);
    const rows = normalizeForMode(storedRows, multi, optionCatalog); // si el servidor deja de confirmar la multimáquina, el borrador vuelve a una sola máquina
    const [errors, setErrors] = useState<RowError[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [confirming, setConfirming] = useState<WorkOrder | null>(null);
    const [archiveCandidate, setArchiveCandidate] = useState<WorkOrder | null>(null);
    const [archiveReason, setArchiveReason] = useState("");
    const [showArchived, setShowArchived] = useState(false);
    // The historical resource belongs to the session scope and is loaded only
    // after Jefatura asks for it. Never put archived OT into browser storage.
    const archivedOrders = useResource<WorkOrder[]>(
        "work-order-history:" + scope, canManageOrders && showArchived,
        signal => listArchivedWorkOrders(signal), onSessionLost);
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
    function editLine(order: WorkOrder, line: WorkOrderLine, replacement: LineDraft, reason: string) {
        if (!canManageOrders || order.status !== "draft") return void toast.error("Solo Jefatura puede editar líneas en borrador");
        const expected: LineDraft = {
            pvReference: line.pv_reference, articleCode: line.article.code,
            quantity: line.quantity, dueDate: line.due_date,
        };
        run(`edit:${line.id}`, () => editDraftWorkOrderLine(order.id, line.line_code, expected, replacement, reason),
            () => toast.success(`OT ${order.number}: línea ${line.line_code} actualizada`));
    }
    function reprogramLine(order: WorkOrder, line: WorkOrderLine, replacement: LineDraft, reason: string) {
        if (!canManageOrders || order.status !== "published")
            return void toast.error("Solo Jefatura puede reprogramar una OT publicada");
        const expectedVersion = order.programming?.version_number ?? order.baseline.version_number;
        const expected: LineDraft = {
            pvReference: line.pv_reference, articleCode: line.article.code,
            quantity: line.quantity, dueDate: line.due_date,
        };
        run(`reprogram:${line.line_code}`, () =>
            reprogramPublishedLine(order.id, line.line_code, expectedVersion, expected, replacement, reason),
            (updated) => toast.success(`OT ${updated.number}: programación v${updated.programming?.version_number ?? "?"} publicada`));
    }
    function publish(order: WorkOrder) {
        setConfirming(null);
        if (!canManageOrders) return void toast.error("Tu perfil no puede crear ni modificar OT");
        run(`publish:${order.id}`, () => publishWorkOrder(order.id), (published) => { toast.success(`OT ${published.number}: línea base publicada`); });
    }
    function archive(order: WorkOrder) {
        if (!canManageOrders) return void toast.error("Solo Jefatura puede archivar");
        const reason = archiveReason.trim();
        if (reason.length < 10 || reason.length > 300) return void toast.error("Escribe un motivo de 10 a 300 caracteres");
        setArchiveCandidate(null);
        run(`archive:${order.id}`, () => archiveWorkOrder(order.id, reason), (archived) => {
            toast.success(`OT ${archived.number} archivada; historial conservado`);
            archivedOrders.refresh();
            setArchiveReason("");
        });
    }
    function restore(order: WorkOrder) {
        if (!canManageOrders) return void toast.error("Solo Jefatura puede restaurar");
        run(`restore:${order.id}`, () => restoreWorkOrder(order.id), (restored) => {
            toast.success(`OT ${restored.number} visible nuevamente`);
            archivedOrders.refresh();
        });
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
        {canManageOrders && <Panel title="Archivo de órdenes de trabajo"
            note="Las OT archivadas dejan de aparecer en Programación. Las capturas, Calidad y la auditoría permanecen intactas. No se archivan órdenes en ejecución ni con asignaciones.">
            <Button size="sm" variant="outline" disabled={locked} onClick={() => setShowArchived(value => !value)}
                data-archive-toggle="">{showArchived ? "Ocultar historial" : "Ver OT archivadas"}</Button>
            {showArchived && <div className="mt-4" data-archive-history="">
                {archivedOrders.view.status !== "ready"
                    ? <CentralStatus state={archivedOrders.view} onRetry={archivedOrders.refresh}/>
                    : archivedOrders.view.data.filter(o => machines.includes(o.machine.code)).length === 0
                        ? <p className="text-sm text-slate-600">No hay OT archivadas para este frente.</p>
                        : <div className="space-y-2">{archivedOrders.view.data
                            .filter(o => machines.includes(o.machine.code)).map(o =>
                                <div key={o.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                                    <div><b>{o.number}</b> · {o.machine.code} · {WORK_ORDER_LABELS[o.status]}
                                        <p className="text-xs text-slate-600">{o.status === "in_progress" ? "Retirada de QA · historial inmutable" : "Histórico de solo lectura"} · {o.baseline.lines.length} línea(s)</p></div>
                                    {o.status !== "in_progress" && <Button size="sm" variant="outline" disabled={locked}
                                        onClick={() => restore(o)}>{busy === `restore:${o.id}` ? "Restaurando…" : "Restaurar"}</Button>}
                                </div>)}</div>}
            </div>}
        </Panel>}
        {(canManageOrders || canManageAssignments) && <SupervisedHandoffPanel
            key={"e2d2:" + scope} orders={orders} scope={scope}
            canManageOrders={canManageOrders} canManageAssignments={canManageAssignments}
            catalog={optionCatalog} catalogReady={typeof options !== "string"}
            lockedExternal={locked} onChanged={onChanged} onSessionLost={onSessionLost}/>}
        {orders.length === 0 && <Panel title="Sin órdenes de trabajo" note={`Todavía no hay OT de ${sectorLabel} en el servidor.`}><p className="text-sm text-slate-700">Jefatura puede crear la primera.</p></Panel>}
        {orders.map(order => {
            const orderMachines = machinesOf(order);
            return <div key={order.id} data-work-order={order.number} tabIndex={-1} className="overflow-hidden rounded-2xl border bg-white shadow-sm outline-none"><div className="flex flex-wrap justify-between gap-3 border-b p-5"><div><h3 className="font-black">{order.number}</h3><p className="text-sm text-slate-600">Base v{order.baseline.version_number}{order.programming ? ` · Programación vigente v${order.programming.version_number}` : ""} · {order.baseline.lines.length} producto(s) · {new Set(order.baseline.lines.map(l => l.pv_reference)).size} PV · máquina(s): {orderMachines.join(", ")}</p>{orderMachines.length > 1 && <p className="text-xs text-slate-500">Máquina principal de la OT: {order.machine.code}</p>}</div><div className="flex flex-wrap items-center gap-2"><Badge>{WORK_ORDER_LABELS[order.status]}</Badge>{canManageAssignments && blockedBy !== capabilities && massActivationOffered(capabilities, canManageAssignments, order.status) && <Button size="sm" className="bg-[#146b4f]" disabled={locked} onClick={event => { invoker.current = event.currentTarget; setMassOrder({ scope, id: order.id, number: order.number }); }}>{executionEnabled ? "Habilitar todas las líneas" : "Activar todas las líneas"}</Button>}{canManageOrders && order.status === "draft" && <Button size="sm" variant="outline" disabled={locked} onClick={() => setConfirming(order)}>{busy === `publish:${order.id}` ? "Publicando…" : "Publicar base"}</Button>}{canManageOrders && (order.status === "draft" || order.status === "published") &&
                    <Button size="sm" variant="outline" disabled={locked}
                        onClick={() => { setArchiveCandidate(order); setArchiveReason(""); }}>
                        Archivar OT
                    </Button>}</div></div>
                <div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">Línea</th><th className="p-3">Máquina</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Cantidad</th><th className="p-3">Entrega</th><th className="p-3">Gestión</th></tr></thead><tbody>{order.baseline.lines.map(base => { const l = order.programming?.lines.find(line => line.line_code === base.line_code) ?? base; return <tr key={base.id} className="border-t"><td className="p-3 font-bold">{l.line_code}</td><td className="p-3" data-line-machine="">{l.machine.code}</td><td className="p-3">{l.pv_reference}</td><td className="p-3"><b>{l.article.code}</b><br />{l.article.description}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{l.due_date}</td><td className="p-3">{canManageAssignments ? <Button size="sm" className="bg-[#146b4f]" disabled={locked || (order.status !== "published" && order.status !== "in_progress")} onClick={() => activate(order, base.id)}>{busy === `activate:${l.id}` ? "Habilitando…" : executionEnabled ? "Habilitar" : "Activar"}</Button> : <span className="text-slate-500">—</span>}</td></tr>; })}</tbody></table></div>
                {executionEnabled && (order.status === "published" || order.status === "in_progress") &&
                    <LineExecutionPanel key={scope + ":" + order.id} order={order} scope={scope} refreshRevision={executionRevision}
                        lockedExternal={locked} onChanged={onChanged} onSessionLost={onSessionLost}/>}
                {canManageOrders && order.status === "published" && typeof options !== "string" && <>
                    <p className="border-t px-4 pt-3 text-sm text-slate-600">Reprogramación controlada: conserva la base original y crea una nueva versión. Solo disponible antes de la primera asignación; con una línea habilitada, en ejecución o finalizada, el servidor rechaza el cambio.</p>
                    {(order.programming?.lines ?? order.baseline.lines).map(line => <EditDraftLine
                        key={`revision:${line.id}:${line.quantity}:${line.pv_reference}`}
                        line={line} options={options} disabled={locked} reprogram
                        onSave={(replacement, reason) => reprogramLine(order, line, replacement, reason)}/>)}
                    <RevisionHistory key={`history:${scope}:${order.id}:${order.programming?.version_number ?? 1}`} order={order} onSessionLost={onSessionLost}/>
                </>}
                {canManageOrders && order.status === "draft" && typeof options !== "string" && <>
                    {order.baseline.lines.map(line => <EditDraftLine
                        key={`${line.id}:${line.pv_reference}:${line.article.code}:${line.quantity}:${line.due_date}`}
                        line={line} options={options} disabled={locked}
                        onSave={(replacement, reason) => editLine(order, line, replacement, reason)}/>)}
                    <AddLine order={order} options={options} multi={multi} disabled={locked} busy={busy === `add:${order.id}`} nextKey={nextKey} onAdd={draft => addLine(order, draft)}/>
                </>}
            </div>;
        })}
        {massOrder && massOrder.scope === scope && <ActivateAllDialog key={`${massOrder.scope}:${massOrder.id}`} lineExecutionEnabled={executionEnabled} orderId={massOrder.id} orderNumber={massOrder.number} onClose={() => setMassOrder(null)} returnFocusTargets={() => [invoker.current, invoker.current?.closest<HTMLElement>("[data-work-order]"), panel.current]} onSessionLost={onSessionLost} onApplied={() => { setExecutionRevision(n => n + 1); onChanged(); }}
            onDisabled={() => { setBlockedBy(capabilities); onCapabilitiesStale?.(); }}/>}
        <AlertDialog open={archiveCandidate !== null} onOpenChange={open => { if (!open) setArchiveCandidate(null); }}>
            <AlertDialogContent><AlertDialogHeader>
                <AlertDialogTitle>Archivar {archiveCandidate?.number}</AlertDialogTitle>
                <AlertDialogDescription>La OT saldrá de la lista operativa, sin borrar líneas, capturas ni auditoría.
                    La OT conserva su estado original y se puede restaurar desde el historial.
                    Solo se aceptan órdenes en borrador o publicadas sin asignaciones.</AlertDialogDescription>
            </AlertDialogHeader>
            <label className="block text-sm font-semibold" htmlFor="work-order-archive-reason">Motivo de archivado (10–300 caracteres)</label>
            <Input id="work-order-archive-reason" autoComplete="off" maxLength={300}
                value={archiveReason} onChange={event => setArchiveReason(event.target.value)}
                placeholder="Ej.: Escenario ficticio de prueba validado" />
            <AlertDialogFooter><AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction disabled={locked || archiveReason.trim().length < 10 || archiveReason.trim().length > 300}
                    onClick={() => archiveCandidate && archive(archiveCandidate)}>Archivar sin borrar</AlertDialogAction>
            </AlertDialogFooter></AlertDialogContent>
        </AlertDialog>
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

// E2-A: editar una línea persistida SOLO antes de publicar; no cambia máquina ni identidad.
function EditDraftLine({ line, options, disabled, onSave, reprogram = false }: {
    line: WorkOrderLine;
    options: { machines: readonly MachineOption[]; catalog: (machine: string) => readonly CatalogItem[] };
    disabled: boolean;
    onSave: (replacement: LineDraft, reason: string) => void;
    reprogram?: boolean;
}) {
    const machine = line.machine.code;
    const [row, setRow] = useState<DraftRow>(() => ({
        key: line.id, machine, pv: line.pv_reference, code: line.article.code,
        qty: String(line.quantity), date: line.due_date,
    }));
    const [reason, setReason] = useState("");
    const [errors, setErrors] = useState<RowError[]>([]);
    const changed = row.pv.trim() !== line.pv_reference || row.code !== line.article.code
        || Number(row.qty) !== line.quantity || row.date !== line.due_date;
    function save() {
        const checked = validateRows([row], {
            multi: false, machines: [machine], catalog: options.catalog,
        });
        if (!checked.ok) { setErrors(checked.errors); return void toast.error(checked.message); }
        if (!changed) return void toast.error("No hay cambios para guardar");
        if (reason.trim().length < 10 || reason.trim().length > 300)
            return void toast.error("Indica un motivo de 10 a 300 caracteres");
        setErrors([]);
        onSave(checked.lines[0], reason.trim());
    }
    return <details className="border-t p-4" data-edit-draft-line={reprogram ? undefined : line.line_code} data-reprogram-line={reprogram ? line.line_code : undefined}>
        <summary className="cursor-pointer text-sm font-bold">{reprogram ? "Reprogramar" : "Editar"} {line.line_code} · {machine} {reprogram ? "(versión controlada)" : "(solo borrador)"}</summary>
        <div className="mt-3 space-y-3">
            <OrderDraftEditor rows={[row]} onRows={next => setRow(next[0])} machines={[line.machine]}
                catalog={options.catalog} multi={false} lockMachine fixedRows disabled={disabled}
                errors={errors} nextKey={() => line.id}/>
            <label className="block text-sm font-semibold" htmlFor={`draft-edit-reason-${line.id}`}>Motivo de la corrección (obligatorio)</label>
            <Input id={`draft-edit-reason-${line.id}`} value={reason} maxLength={300} disabled={disabled}
                placeholder="Ej.: Ajuste de cantidad solicitado por Jefatura"
                onChange={event => setReason(event.target.value)}/>
            <Button type="button" size="sm" variant="outline" disabled={disabled || !changed || reason.trim().length < 10}
                onClick={save}>{reprogram ? "Publicar nueva versión de" : "Guardar cambios de"} {line.line_code}</Button>
            <p className="text-xs text-slate-600">{reprogram ? "Se conservarán la base original y todas las versiones anteriores. No disponible si existe cualquier asignación." : "La máquina, el código de línea y la OT no cambian. Una OT publicada no admite esta operación."}</p>
        </div>
    </details>;
}

// Historial de correcciones consultado bajo demanda. No se mezcla con la baseline.
function RevisionHistory({ order, onSessionLost }: { order: WorkOrder; onSessionLost: () => void }) {
    const [history, setHistory] = useState<Awaited<ReturnType<typeof listWorkOrderRevisions>> | null>(null);
    const [loading, setLoading] = useState(false);
    async function load() {
        if (loading) return;
        setLoading(true);
        try {
            const response = await listWorkOrderRevisions(order.id);
            if (!response.ok && response.kind === "session") onSessionLost();
            setHistory(response);
        } catch { setHistory({ ok: false, kind: "unavailable", status: 0 }); }
        finally { setLoading(false); }
    }
    return <div className="border-t p-4 space-y-2">
        <Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load()}>
            {loading ? "Consultando historial..." : "Consultar historial de versiones"}</Button>
        {history && !history.ok && <p role="alert" className="text-sm text-red-700">No se pudo consultar el historial. Vuelve a intentar.</p>}
        {history?.ok && (history.data.length === 0 ?
            <p className="text-sm text-slate-600">Sin reprogramaciones registradas.</p> :
            <div className="space-y-2">{history.data.map(r => <div key={r.version_number} className="rounded-md border p-3 text-sm">
                <b>v{r.previous_version} → v{r.version_number} · {r.line_code}</b>
                <p>{r.reason} · {r.changed_by_name} · {new Date(r.changed_at).toLocaleString("es-PE")}</p>
                <p>PV: {r.before.pv_reference} → {r.after.pv_reference} · Producto: {r.before.article_code} → {r.after.article_code}</p>
                <p>Cantidad: {r.before.quantity} → {r.after.quantity} · Entrega: {r.before.due_date} → {r.after.due_date}</p>
            </div>)}</div>)}
    </div>;
}
