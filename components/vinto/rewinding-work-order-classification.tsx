"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { CentralStatus } from "@/components/vinto/central-status";
import { Panel } from "@/components/vinto/panels";
import { failureMessage } from "@/lib/vinto/orders";
import { useResource } from "@/lib/vinto/use-central";
import {
    classifyRewindingWorkOrder,
    getRewindingWorkOrderClassification,
    listRewindingWorkOrdersForClassification,
} from "@/lib/vinto/rewinding-export-api";
import type { RewindingWorkOrderClassification } from "@/lib/vinto/rewinding-export";

type Props = {
    scope: string;
    onSessionLost: () => void;
};

export function RewindingWorkOrderClassificationPanel({ scope, onSessionLost }: Props) {
    const workOrders = useResource(
        "rewinding-export-classification-candidates:" + scope,
        true,
        signal => listRewindingWorkOrdersForClassification(signal),
        onSessionLost,
    );
    const [workOrderId, setWorkOrderId] = useState("");
    const current = useResource(
        "rewinding-export-work-order-classification:" + scope + ":" + workOrderId,
        workOrderId !== "",
        signal => getRewindingWorkOrderClassification(workOrderId, signal),
        onSessionLost,
    );
    const [classification, setClassification] = useState<RewindingWorkOrderClassification | "">("");
    const [reason, setReason] = useState("");
    const [confirmed, setConfirmed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    const selected = workOrders.view.status === "ready"
        ? workOrders.view.data.find(order => order.id === workOrderId) ?? null
        : null;
    const currentRecord = current.view.status === "ready" ? current.view.data : null;
    const sameClassification = Boolean(currentRecord?.classification && currentRecord.classification === classification);
    const canSubmit = Boolean(workOrderId && classification && current.view.status === "ready"
        && reason.trim().length >= 10 && reason.trim().length <= 300 && confirmed && !sameClassification && !busy);

    async function submit() {
        if (!canSubmit || !classification) return;
        setBusy(true);
        setError("");
        setNotice("");
        try {
            const result = await classifyRewindingWorkOrder(workOrderId, { classification, reason: reason.trim() });
            if (!result.ok) {
                if (result.kind === "session") onSessionLost();
                setError(result.kind === "forbidden"
                    ? "Tu usuario no tiene permiso para clasificar OTs."
                    : result.kind === "conflict"
                        ? "No se pudo cambiar la clasificación: verifica si existen reportes generados u observados que deban anularse primero."
                        : failureMessage(result.kind));
                return;
            }
            setNotice("Nueva decisión registrada. Secuencia " + result.data.sequence_no + "; la decisión anterior permanece en el historial.");
            setReason("");
            setConfirmed(false);
            setClassification("");
            current.refresh();
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="mt-6" data-rewinding-export="work-order-classification">
            <Panel title="Clasificación de órdenes para RBE"
                note="Solo Jefatura puede registrar decisiones. Una OT sin clasificación production_confirmed permanece desconocida y no aparece en los selectores del reporte.">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                    <div>
                        <Label htmlFor="rbe-classification-ot">Orden de trabajo</Label>
                        <select id="rbe-classification-ot" className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm"
                            value={workOrderId} disabled={busy || workOrders.view.status !== "ready"}
                            onChange={event => {
                                setWorkOrderId(event.target.value);
                                setClassification("");
                                setReason("");
                                setConfirmed(false);
                                setError("");
                                setNotice("");
                            }}>
                            <option value="">Seleccionar OT…</option>
                            {workOrders.view.status === "ready" ? workOrders.view.data.map(order => (
                                <option key={order.id} value={order.id}>{order.number} · {order.machine_code} · {order.status}</option>
                            )) : null}
                        </select>
                        {workOrders.view.status === "loading" || workOrders.view.status === "idle"
                            ? <p className="mt-2 text-sm text-slate-600" role="status">Consultando OTs de Rebobinado, incluidas las cerradas…</p>
                            : null}
                        {workOrders.view.status === "error"
                            ? <div className="mt-2"><CentralStatus state={workOrders.view} onRetry={workOrders.refresh} title="No se pudieron consultar las OTs"/></div>
                            : null}
                        {workOrders.view.status === "ready" && workOrders.view.data.length === 0
                            ? <p className="mt-2 text-sm text-slate-600">No hay OTs disponibles para clasificar en el alcance REBOBINADO.</p>
                            : null}
                        {selected ? <p className="mt-2 text-xs text-slate-600">OT {selected.number} · {selected.machine_code}. El estado {selected.status} no se usa para inferir si es QA; las OTs cerradas también se pueden clasificar.</p> : null}
                    </div>
                    <div className="rounded-xl border bg-slate-50 p-4">
                        <h3 className="font-semibold">Última decisión registrada</h3>
                        {!workOrderId ? <p className="mt-2 text-sm text-slate-600">Selecciona una OT para consultar su clasificación.</p> : null}
                        {workOrderId && (current.view.status === "loading" || current.view.status === "idle")
                            ? <p className="mt-2 text-sm text-slate-600" role="status">Consultando clasificación…</p>
                            : null}
                        {current.view.status === "error"
                            ? <div className="mt-2"><CentralStatus state={current.view} onRetry={current.refresh} title="No se pudo consultar la clasificación"/></div>
                            : null}
                        {currentRecord ? (
                            currentRecord.classification === null ? (
                                <div className="mt-2"><Badge variant="outline" className="border-amber-300 text-amber-900">Desconocida</Badge><p className="mt-1 text-sm text-slate-700">La OT queda excluida hasta que Jefatura confirme su clasificación.</p></div>
                            ) : (
                                <div className="mt-2 space-y-1">
                                    <Badge className={currentRecord.classification === "production_confirmed" ? "bg-emerald-700" : "bg-slate-700"}>
                                        {currentRecord.classification === "production_confirmed" ? "Producción confirmada" : "QA"}
                                    </Badge>
                                    <p className="text-xs text-slate-700">Secuencia {currentRecord.sequence_no} · {currentRecord.recorded_by?.display_name} · {currentRecord.recorded_at ? new Date(currentRecord.recorded_at).toLocaleString("es-PE", { timeZone: "America/Lima" }) : ""}</p>
                                    <p className="text-sm text-slate-700">{currentRecord.reason}</p>
                                </div>
                            )
                        ) : null}
                    </div>
                </div>

                {workOrderId && current.view.status === "ready" ? (
                    <div className="mt-5 border-t pt-4">
                        <h3 className="font-semibold">Registrar una nueva decisión</h3>
                        <p className="mt-1 text-xs text-slate-600">La decisión es append-only: no borra ni modifica la anterior. Para marcar una OT como QA, primero deben anularse sus reportes RBE generados u observados.</p>
                        <div className="mt-3 grid gap-4 md:grid-cols-2">
                            <div>
                                <Label htmlFor="rbe-classification-value">Clasificación *</Label>
                                <select id="rbe-classification-value" className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm"
                                    value={classification} disabled={busy}
                                    onChange={event => { setClassification(event.target.value as RewindingWorkOrderClassification | ""); setConfirmed(false); }}>
                                    <option value="">Seleccionar…</option>
                                    <option value="production_confirmed">Producción confirmada</option>
                                    <option value="qa">QA / datos de prueba</option>
                                </select>
                            </div>
                            <div>
                                <Label htmlFor="rbe-classification-reason">Motivo (10–300 caracteres) *</Label>
                                <textarea id="rbe-classification-reason" rows={3} maxLength={300} value={reason} disabled={busy}
                                    onChange={event => setReason(event.target.value)}
                                    className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"/>
                                <p className="mt-1 text-xs text-slate-500">{reason.trim().length}/300</p>
                            </div>
                        </div>
                        {classification ? (
                            <label className="mt-3 flex items-start gap-2 text-sm text-slate-800">
                                <input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-1"/>
                                <span>{classification === "production_confirmed"
                                    ? "Confirmo que he verificado la OT y que corresponde a producción real, no a datos QA."
                                    : "Confirmo que he verificado que esta OT contiene datos QA/de prueba y debe excluirse de RBE."}</span>
                            </label>
                        ) : null}
                        {sameClassification ? <p className="mt-2 text-xs text-slate-600">La OT ya tiene esta clasificación. No se registrará una decisión duplicada.</p> : null}
                        <Button type="button" className="mt-4 bg-[#146b4f]" disabled={!canSubmit} onClick={() => void submit()}>
                            {busy ? "Registrando…" : "Registrar clasificación"}
                        </Button>
                    </div>
                ) : null}
                {error ? <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p> : null}
                {notice ? <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" role="status" aria-live="polite">{notice}</p> : null}
            </Panel>
        </div>
    );
}
