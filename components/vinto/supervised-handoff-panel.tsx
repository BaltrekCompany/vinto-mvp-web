"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { HandoffPublishForm } from "@/components/vinto/handoff-publish-form";
import type { CatalogItem } from "@/components/vinto/order-draft-editor";
import { listAssignments } from "@/lib/vinto/assignments-api";
import { getWorkOrderExecution } from "@/lib/vinto/line-execution-api";
import { cancelHandoff, getHandoffCapability, listOpenHandoffs, publishHandoff, reassignHandoff, reserveHandoff } from "@/lib/vinto/handoff-api";
import type { OpenHandoff } from "@/lib/vinto/handoff";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import type { LineDraft, WorkOrder } from "@/lib/vinto/orders";
import { useResource } from "@/lib/vinto/use-central";
import type { ApiResult } from "@/lib/vinto/central-http";

type Props = {
    orders: WorkOrder[];
    scope: string;
    canManageOrders: boolean;
    canManageAssignments: boolean;
    catalog: (machine: string) => readonly CatalogItem[];
    catalogReady: boolean;
    lockedExternal: boolean;
    onChanged: () => void;
    onSessionLost: () => void;
};
type Verified = {
    workOrderId: string; lineCode: string; machine: string;
    assignmentId: string; version: number; quantity: number;
};

function CancelForm({ item, busy, onCancel }: {
    item: OpenHandoff; busy: boolean; onCancel: (reason: string) => void;
}) {
    const [reason, setReason] = useState("");
    const [confirm, setConfirm] = useState(false);
    return <div className="mt-2 flex flex-col gap-2">
        <label htmlFor={"d2-cancel-reason-" + item.handoff_id} className="text-xs font-semibold">Motivo para cancelar la reserva (10-300 caracteres)</label>
        <Input id={"d2-cancel-reason-" + item.handoff_id} value={reason}
            disabled={busy} maxLength={300} autoComplete="off"
            placeholder="Motivo obligatorio" onChange={e => setReason(e.target.value)}/>
        <div><Button variant="outline" size="sm" disabled={busy || reason.trim().length < 10}
            onClick={() => setConfirm(true)}>Revisar cancelacion</Button></div>
        <AlertDialog open={confirm} onOpenChange={open => { if (!open && !busy) setConfirm(false); }}>
            <AlertDialogContent><AlertDialogHeader>
                <AlertDialogTitle>Cancelar la reserva de {item.work_order_number}</AlertDialogTitle>
                <AlertDialogDescription>
                    Se liberara {item.line_code} en {item.machine_code} y se conservara la auditoria.
                    No cancela la orden de trabajo.
                </AlertDialogDescription>
            </AlertDialogHeader><AlertDialogFooter>
                <AlertDialogCancel disabled={busy}>Volver</AlertDialogCancel>
                <AlertDialogAction disabled={busy} onClick={() => {
                    setConfirm(false);
                    onCancel(reason.trim());
                }}>Confirmar cancelacion</AlertDialogAction>
            </AlertDialogFooter></AlertDialogContent>
        </AlertDialog>
    </div>;
}

function ReassignAction({ item, busy, onReassign }: {
    item: OpenHandoff; busy: boolean; onReassign: () => void;
}) {
    const [confirm, setConfirm] = useState(false);
    return <>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirm(true)}>
            Revisar reasignacion a v{item.published_version}
        </Button>
        <AlertDialog open={confirm} onOpenChange={open => { if (!open && !busy) setConfirm(false); }}>
            <AlertDialogContent>
                <AlertDialogHeader><AlertDialogTitle>Reasignar {item.line_code}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {item.work_order_number} · {item.machine_code}: finalizar la asignacion anterior
                        y crear una nueva para v{item.published_version}. El operador aun tendra que
                        confirmar la lectura antes de que E1 permita iniciar.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter><AlertDialogCancel disabled={busy}>Volver</AlertDialogCancel>
                    <AlertDialogAction disabled={busy} onClick={() => {
                        setConfirm(false); onReassign();
                    }}>Confirmar reasignacion</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    </>;
}

// B3: entrada unica para Jefatura y Supervision. La lista de reservas activas
// viene del servidor: no depende de guardar un handoff_id en localStorage.
export function SupervisedHandoffPanel({
    orders, scope, canManageOrders, canManageAssignments, catalog,
    catalogReady, lockedExternal, onChanged, onSessionLost,
}: Props) {
    const capability = useResource<boolean>(
        "e2d2-capability:" + scope, true,
        signal => getHandoffCapability(signal), onSessionLost, true);
    const inbox = useResource<OpenHandoff[]>(
        "e2d2-open-handoffs:" + scope, true,
        signal => listOpenHandoffs(signal), onSessionLost, true);
    const [guard] = useState(createMutationGuard);
    const seq = useRef(0);
    const [busy, setBusy] = useState<string | null>(null);
    const [verifying, setVerifying] = useState(false);
    const [orderId, setOrderId] = useState("");
    const [lineCode, setLineCode] = useState("");
    const [verified, setVerified] = useState<Verified | null>(null);
    const [reserveReason, setReserveReason] = useState("");
    const [reserveConfirm, setReserveConfirm] = useState(false);
    useEffect(() => () => { guard.reset(); seq.current += 1; }, [guard, scope]);

    const capReady = capability.view.status === "ready";
    const enabled = capReady && capability.view.data === true;
    const listReady = inbox.view.status === "ready" && !inbox.view.refreshing;
    const active = listReady ? inbox.view.data : [];
    const pendingOrders = orders.filter(order => order.status === "in_progress");
    const selectedOrder = pendingOrders.find(order => order.id === orderId);
    const selectedLine = (selectedOrder?.programming?.lines ?? selectedOrder?.baseline.lines ?? [])
        .find(line => line.line_code === lineCode);
    const blocked = lockedExternal || busy !== null || verifying;
    const selectionMatches = verified !== null &&
        verified.workOrderId === orderId && verified.lineCode === lineCode &&
        selectedLine?.machine.code === verified.machine &&
        (selectedOrder?.programming?.version_number ?? 2) === verified.version;
    const reservationReady = enabled && listReady && !blocked && selectionMatches &&
        reserveReason.trim().length >= 10 && reserveReason.trim().length <= 300 &&
        !active.some(item => item.work_order_id === orderId);

    function clearSelection() {
        seq.current += 1;
        setVerified(null);
        setReserveReason("");
        setReserveConfirm(false);
    }
    function mutate<T>(key: string, action: () => Promise<ApiResult<T>>, message: string) {
        void runGuarded(guard, action, {
            onStart: () => setBusy(key),
            onOk: () => {
                toast.success(message);
                clearSelection();
                inbox.refresh();
                onChanged();
            },
            onSession: onSessionLost,
            onFailure: (kind, failure) => {
                toast.error(
                    failure.code === "WORK_ORDER_HANDOFF_PENDING"
                        ? "Existe otro relevo abierto. Actualiza los datos."
                        : "La operacion no se pudo confirmar. Consulta los relevos antes de repetir."
                );
                clearSelection();
                inbox.refresh(); onChanged();
                if (kind === "session") onSessionLost();
            },
            onSettled: () => setBusy(null),
        });
    }
    async function verifySelection() {
        if (!enabled || !listReady || blocked || !selectedOrder || !selectedLine ||
            active.some(item => item.work_order_id === selectedOrder.id)) return;
        const ticket = ++seq.current;
        setVerified(null);
        setVerifying(true);
        try {
            const [execution, assignments] = await Promise.all([
                getWorkOrderExecution(selectedOrder.id), listAssignments(),
            ]);
            if (ticket !== seq.current) return;
            if ((!execution.ok && execution.kind === "session") ||
                (!assignments.ok && assignments.kind === "session")) {
                onSessionLost(); return;
            }
            if (!execution.ok || !assignments.ok) {
                toast.error("No se pudo verificar el estado actual de la linea.");
                return;
            }
            const line = execution.data.lines.find(row =>
                row.line_code === selectedLine.line_code &&
                row.machine_code === selectedLine.machine.code &&
                row.status === "enabled" && row.current_assignment_id !== null);
            const assignment = line ? assignments.data.find(row =>
                row.id === line.current_assignment_id && row.status === "active" &&
                row.work_order.id === selectedOrder.id &&
                row.line.line_code === selectedLine.line_code &&
                row.machine.code === selectedLine.machine.code) : null;
            const expected = selectedOrder.programming?.version_number ?? 2;
            if (!line || !assignment || assignment.operational.version_number !== expected) {
                toast.error("Linea no elegible: revisa turno, asignacion, version o E1.");
                return;
            }
            setVerified({
                workOrderId: selectedOrder.id, lineCode: line.line_code,
                machine: line.machine_code, assignmentId: assignment.id,
                version: expected, quantity: selectedLine.quantity,
            });
        } finally {
            if (ticket === seq.current) setVerifying(false);
        }
    }
    // Hay que consultar la capacidad nuevamente tras activaciones de flags;
    // nunca inferir que D2 esta ON de una configuracion del navegador.
    return <section data-e2d2-b3="" className="rounded-2xl border border-slate-300 bg-white p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-black">Relevos supervisados · E2-D2</h2>
                <p className="text-sm text-slate-700">Reprogramacion de lineas habilitadas que todavia no han iniciado produccion.</p></div>
            <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="outline" disabled={blocked}
                    onClick={() => { capability.refresh(); inbox.refresh(); onChanged(); clearSelection(); }}>
                    Actualizar relevos
                </Button>
            </div>
        </div>
        {(!capReady || inbox.view.status !== "ready") && <p role="status" className="mt-3 text-sm text-amber-900">
            {capability.view.status === "error" || inbox.view.status === "error"
                ? "No se pudo comprobar D2. Las acciones de creacion y publicacion estan bloqueadas."
                : "Verificando capacidad y relevos existentes con el servidor..."}
        </p>}
        {capReady && !enabled && <p className="mt-3 text-sm text-slate-700">
            E2-D2 esta desactivado en el servidor. No se pueden iniciar nuevas reservas ni publicar nuevas versiones.
            Las operaciones de recuperacion existentes siguen protegidas por la API.
        </p>}
        {inbox.view.status === "ready" && <>
            <h3 className="mt-4 text-sm font-bold">Relevos abiertos ({inbox.view.data.length})</h3>
            {inbox.view.data.length === 0
                ? <p className="mt-1 text-sm text-slate-600">No hay relevos pendientes.</p>
                : <div className="mt-2 space-y-3">
                    {inbox.view.data.map(item => {
                        const order = orders.find(o => o.id === item.work_order_id);
                        return <article key={item.handoff_id} data-d2-handoff={item.handoff_id}
                            className="rounded-xl border bg-slate-50 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div className="text-sm font-bold">{item.work_order_number} · {item.line_code} · {item.machine_code}</div>
                                <span className="text-xs font-semibold text-amber-800">{item.status === "pending" ? "Reservado · pendiente de Jefatura" : item.status === "published" ? "Publicado · reasignacion pendiente" : "Reasignado · esperando acuse de Operacion"}</span>
                            </div>
                            <p className="mt-1 text-xs text-slate-700">Version original v{item.expected_version} · motivo: {item.reason}</p>
                            {canManageOrders && item.status === "pending" &&
                                (enabled && catalogReady && order ?
                                    <HandoffPublishForm key={item.handoff_id} order={order}
                                        handoff={item} catalog={catalog} busy={blocked || !listReady}
                                        onPublish={(expected, replacement, reason) =>
                                            mutate("publish:" + item.handoff_id,
                                                () => publishHandoff(item.handoff_id, expected, replacement, reason),
                                                "Version nueva publicada; Supervisión debe reasignar.")}/> :
                                    <p className="mt-2 text-xs text-amber-900">
                                        La publicacion requiere D2 ON, catalogo disponible y OT vigente.
                                    </p>)}
                            {canManageAssignments && item.status === "pending" &&
                                <CancelForm key={item.handoff_id} item={item} busy={blocked || !listReady}
                                    onCancel={reason => mutate("cancel:" + item.handoff_id,
                                        () => cancelHandoff(item.handoff_id, reason),
                                        "Reserva cancelada y auditada.")}/>}
                            {canManageAssignments && item.status === "published" &&
                                <div className="mt-2">
                                    <ReassignAction item={item} busy={blocked || !listReady}
                                        onReassign={() => mutate("reassign:" + item.handoff_id,
                                            () => reassignHandoff(item.handoff_id),
                                            "Nueva asignacion creada. Operacion debe acusar la version.")}/>
                                </div>}
                            {item.status === "reassigned" && <p className="mt-2 text-sm text-slate-700">
                                Operacion debe entrar en Ejecucion, consultar el aviso de version y confirmar la lectura exacta.
                                Hasta ese acuse el backend bloquea el inicio E1.
                            </p>}
                        </article>;
                    })}
                </div>}
        </>}
        {canManageAssignments && enabled && listReady && <div className="mt-5 border-t pt-4" data-d2-reservation="">
            <h3 className="font-semibold">Nueva reserva · Supervision</h3>
            <p className="mt-1 text-xs text-slate-600">Primero consulta la asignacion y estado E1 reales. No se permite reprogramar una linea iniciada o con capturas.</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <label className="text-sm font-semibold">Orden de trabajo
                    <select className="mt-1 h-9 w-full rounded-md border bg-white px-2" value={orderId}
                        disabled={blocked} onChange={event => {
                            setOrderId(event.target.value); setLineCode(""); clearSelection();
                        }}>
                        <option value="">Selecciona una OT</option>
                        {pendingOrders.filter(o => !active.some(h => h.work_order_id === o.id))
                            .map(o => <option key={o.id} value={o.id}>{o.number} · {o.machine.code}</option>)}
                    </select>
                </label>
                <label className="text-sm font-semibold">Linea
                    <select className="mt-1 h-9 w-full rounded-md border bg-white px-2"
                        value={lineCode} disabled={blocked || !selectedOrder}
                        onChange={event => { setLineCode(event.target.value); clearSelection(); }}>
                        <option value="">Selecciona una linea</option>
                        {(selectedOrder?.programming?.lines ?? selectedOrder?.baseline.lines ?? [])
                            .map(l => <option key={l.id} value={l.line_code}>{l.line_code} · {l.machine.code} · {l.article.code}</option>)}
                    </select>
                </label>
            </div>
            <Button type="button" variant="outline" className="mt-3" size="sm"
                disabled={blocked || !selectedOrder || !selectedLine}
                onClick={() => void verifySelection()}>
                {verifying ? "Verificando..." : "Verificar elegibilidad actual"}
            </Button>
            {selectionMatches && <div className="mt-3 space-y-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                <p className="text-sm font-semibold">Elegible: {selectedOrder?.number} · {verified?.lineCode} · {verified?.machine} · v{verified?.version} · {verified?.quantity} KG</p>
                <label htmlFor="d2-reservation-reason" className="block text-sm font-semibold">Motivo de reserva (10-300 caracteres)</label>
                <Input id="d2-reservation-reason" autoComplete="off" maxLength={300}
                    value={reserveReason} disabled={blocked}
                    onChange={event => setReserveReason(event.target.value)}
                    placeholder="Ej.: Ajustar cantidad antes de iniciar la produccion"/>
                <Button size="sm" disabled={!reservationReady}
                    onClick={() => setReserveConfirm(true)}>Revisar reserva</Button>
            </div>}
            <AlertDialog open={reserveConfirm} onOpenChange={open => { if (!open && !blocked) setReserveConfirm(false); }}>
                <AlertDialogContent>
                    <AlertDialogHeader><AlertDialogTitle>Reservar linea antes de iniciar E1</AlertDialogTitle>
                        <AlertDialogDescription>
                            {selectedOrder?.number} · {verified?.lineCode} · {verified?.machine} · v{verified?.version}.
                            La reserva bloqueara el inicio de la linea hasta completar publicacion, reasignacion y acuse.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter><AlertDialogCancel disabled={blocked}>Volver</AlertDialogCancel>
                        <AlertDialogAction disabled={!reservationReady} onClick={() => {
                            if (!verified) return;
                            setReserveConfirm(false);
                            mutate("reserve", () => reserveHandoff(
                                verified.workOrderId, verified.lineCode, verified.assignmentId,
                                verified.version, reserveReason),
                            "Reserva creada. Jefatura puede publicar la nueva version.");
                        }}>Confirmar reserva</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>}
    </section>;
}
