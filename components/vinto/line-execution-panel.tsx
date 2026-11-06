"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getWorkOrderExecution, startWorkOrderLine, finishWorkOrderLine } from "@/lib/vinto/line-execution-api";
import { actionForLine, EXECUTION_LABELS, safeExecutionMessage, type ExecutionLine, type ExecutionMutation, type WorkOrderExecution } from "@/lib/vinto/line-execution";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import { failureMessage, type FailureKind, type WorkOrder } from "@/lib/vinto/orders";
import { useResource } from "@/lib/vinto/use-central";
import type { ApiResult } from "@/lib/vinto/central-http";

type Props = {
    order: WorkOrder;
    scope: string;
    refreshRevision: number;
    lockedExternal: boolean;
    onChanged: () => void;
    onSessionLost: () => void;
};

// This component is mounted only for Supervisión when the server explicitly
// confirms line_execution=true. No local flag or optimistic state can start a line.
export function LineExecutionPanel({ order, scope, refreshRevision, lockedExternal, onChanged, onSessionLost }: Props) {
    const [guard] = useState(createMutationGuard);
    const [busy, setBusy] = useState<string | null>(null);
    const [confirm, setConfirm] = useState<ExecutionLine | null>(null);
    const resource = useResource<WorkOrderExecution>(
        "supervision-line-execution:" + scope + ":" + order.id, true,
        signal => getWorkOrderExecution(order.id, signal), onSessionLost);
    useEffect(() => () => guard.reset(), [guard, scope]);
    useEffect(() => { if (refreshRevision > 0) resource.refresh(); }, [refreshRevision, resource.refresh]);

    function perform(key: string, action: () => Promise<ApiResult<ExecutionMutation>>, success: string) {
        void runGuarded(guard, action, {
            onStart: () => setBusy(key),
            onOk: () => {
                toast.success(success);
                resource.refresh();
                onChanged(); // OT status and assignment panels remain server-authoritative
            },
            onSession: onSessionLost,
            onFailure: (kind, failure) => {
                toast.error(safeExecutionMessage(failure.code, failureMessage(kind as FailureKind)));
                resource.refresh(); // a 409 or lost assignment requires new server state
            },
            onSettled: () => setBusy(null),
        });
    }

    const view = resource.view;
    const data = view.status === "ready" && view.data.work_order_id === order.id ? view.data : null;
    const loading = view.status === "loading" || (view.status === "ready" && view.refreshing);
    const blocked = busy !== null || lockedExternal || loading;
    return <section data-line-execution="" aria-label={"Ejecución de líneas de " + order.number} className="border-t bg-slate-50 p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
                <h4 className="font-bold text-slate-900">Ejecución por línea · Supervisión</h4>
                <p className="text-xs text-slate-600">Habilitar no inicia la producción. Solo una línea puede producir por máquina.</p>
            </div>
            <Button size="sm" variant="outline" disabled={blocked} onClick={resource.refresh}>Actualizar estados</Button>
        </div>
        {view.status === "loading" && <p role="status" className="text-sm text-slate-600">Consultando estados de ejecución…</p>}
        {view.status === "error" && <div role="alert" className="space-y-2 rounded-md border border-red-200 bg-white p-3 text-sm text-red-800">
            <p>No se pudo consultar el estado de ejecución. No se habilitan acciones sin confirmación del servidor.</p>
            <Button size="sm" variant="outline" onClick={resource.refresh}>Reintentar</Button>
        </div>}
        {data && <div className="overflow-x-auto rounded-lg border bg-white">
            <table className="w-full min-w-[740px] text-sm">
                <thead className="bg-slate-100 text-left"><tr>
                    <th className="p-3">Línea</th><th className="p-3">Máquina</th><th className="p-3">Producto · PV</th><th className="p-3">Estado</th><th className="p-3">Acción</th>
                </tr></thead>
                <tbody>{data.lines.map(line => {
                    const baseline = order.baseline.lines.find(item => item.id === line.baseline_line_id && item.line_code === line.line_code && item.machine.code === line.machine_code);
                    // If data from the API and the immutable baseline disagree,
                    // do not offer a mutation against a guessed product/line.
                    const action = baseline ? actionForLine(line, order.status, data.lines) : { canStart: false, canFinish: false, reason: "Los datos de la línea no coinciden con su programación." };
                    const key = line.baseline_line_id;
                    return <tr key={key} className="border-t align-top" data-execution-line={line.line_code}>
                        <td className="p-3 font-semibold">{line.line_code}</td>
                        <td className="p-3">{line.machine_code}</td>
                        <td className="p-3">{baseline ? <><b>{baseline.article.code}</b><br />{baseline.pv_reference}</> : <span className="text-red-700">Requiere revisión</span>}</td>
                        <td className="p-3"><Badge variant="outline">{EXECUTION_LABELS[line.status]}</Badge></td>
                        <td className="p-3">
                            <div className="flex flex-col items-start gap-1">
                                {action.canStart && <Button size="sm" disabled={blocked}
                                    onClick={() => line.current_assignment_id && perform(
                                        "start:" + key,
                                        () => startWorkOrderLine(order.id, line.line_code, line.current_assignment_id as string),
                                        "Línea " + line.line_code + " iniciada en " + line.machine_code)}>
                                    {busy === "start:" + key ? "Iniciando…" : "Iniciar línea"}
                                </Button>}
                                {action.canFinish && <Button size="sm" variant="outline" disabled={blocked} onClick={() => setConfirm(line)}>
                                    Finalizar línea
                                </Button>}
                                {action.reason && <span className="max-w-[280px] text-xs text-slate-600">{action.reason}</span>}
                            </div>
                        </td>
                    </tr>;
                })}</tbody>
            </table>
        </div>}
        <AlertDialog open={confirm !== null} onOpenChange={open => { if (!open && busy === null) setConfirm(null); }}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Finalizar {confirm?.line_code} de {order.number}</AlertDialogTitle>
                    <AlertDialogDescription>
                        La máquina {confirm?.machine_code} dejará de producir esta línea. Se impedirán nuevas capturas.
                        Se conservará lo producido, aunque sea menor que lo programado. No se solicita motivo obligatorio y la OT no se cierra automáticamente.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={busy !== null}>Cancelar</AlertDialogCancel>
                    <AlertDialogAction disabled={busy !== null || lockedExternal} onClick={() => {
                        if (!confirm) return;
                        const line = confirm;
                        setConfirm(null);
                        perform("finish:" + line.baseline_line_id,
                            () => finishWorkOrderLine(order.id, line.line_code),
                            "Línea " + line.line_code + " finalizada; OT pendiente de cierre manual.");
                    }}>Confirmar finalización</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    </section>;
}
