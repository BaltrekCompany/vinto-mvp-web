"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { CentralStatus } from "@/components/vinto/central-status";
import { Panel } from "@/components/vinto/panels";
import {
    annulRewindingExport,
    downloadRewindingExportPdf,
    getRewindingExportReport,
    listRewindingExportHistory,
    REWINDING_EXPORT_HISTORY_PAGE_SIZE,
    saveRewindingExportPdf,
} from "@/lib/vinto/rewinding-export-api";
import { REWINDING_EXPORT_STATUS } from "@/lib/vinto/rewinding-export";
import { failureMessage, type FailureKind } from "@/lib/vinto/orders";
import { requestRevalidation } from "@/lib/vinto/revalidation";
import { useResource } from "@/lib/vinto/use-central";

type Props = {
    scope: string;
    own?: boolean;
    canAnnul?: boolean;
    refreshKey?: number;
    onSessionLost: () => void;
};

const localDate = (value: string) => new Date(value).toLocaleString("es-BO", { timeZone: "America/La_Paz" });

export function RewindingExportHistory({ scope, own = false, canAnnul = false, refreshKey = 0, onSessionLost }: Props) {
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState("");
    const [confirming, setConfirming] = useState(false);
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState(false);
    const [feedback, setFeedback] = useState<{ error: boolean; message: string } | null>(null);
    const action = useRef<AbortController | null>(null);
    useEffect(() => () => action.current?.abort(), []);
    const history = useResource(`rbe-history:${scope}:${refreshKey}:${offset}`, true,
        signal => listRewindingExportHistory(offset, signal), onSessionLost, true);
    const detail = useResource(`rbe-detail:${scope}:${selected}`, Boolean(selected),
        signal => getRewindingExportReport(selected, signal), onSessionLost, true);

    function fail(kind: FailureKind) {
        if (kind === "session") onSessionLost();
        setFeedback({ error: true, message: failureMessage(kind) });
    }

    async function runAction(operation: (signal: AbortSignal) => Promise<void>) {
        if (action.current) return;
        const controller = new AbortController();
        action.current = controller;
        setBusy(true);
        setFeedback(null);
        try {
            await operation(controller.signal);
        } catch {
            if (!controller.signal.aborted) fail("unavailable");
        } finally {
            action.current = null;
            if (!controller.signal.aborted) setBusy(false);
        }
    }

    async function download(reportId: string) {
        await runAction(async signal => {
            const result = await downloadRewindingExportPdf(reportId, signal);
            if (signal.aborted) return;
            if (!result.ok) return fail(result.kind);
            saveRewindingExportPdf(reportId, result.data);
        });
    }

    async function annul() {
        const clean = reason.trim();
        if (!canAnnul || !confirming || clean.length < 10 || clean.length > 300) return;
        await runAction(async signal => {
            const result = await annulRewindingExport(selected, clean, signal);
            if (signal.aborted) return;
            history.refresh();
            detail.refresh();
            requestRevalidation();
            if (!result.ok) return fail(result.kind);
            setConfirming(false);
            setReason("");
            setFeedback({ error: false, message: `Reporte anulado. Crías liberadas: ${result.data.released_reservations}.` });
        });
    }

    const report = detail.view.status === "ready" ? detail.view.data : null;
    return <Panel title={own ? "Mis reportes de exportación" : "Historial de reportes de exportación"} note="Consulta el estado de cada reporte y su documento original.">
        <div className="space-y-3" data-rewinding-export="history">
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { history.refresh(); detail.refresh(); }}>Actualizar historial</Button>
            {history.view.status !== "ready" ? <CentralStatus state={history.view} onRetry={history.refresh}/> :
                <>
                    {history.view.data.length === 0 ? <p className="text-sm text-slate-600">No hay reportes en esta página.</p> :
                        <ul className="divide-y">
                            {history.view.data.map(item => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                                <div className="text-sm">
                                    <p className="font-semibold">{item.pv_reference} · {item.article_code_snapshot} · {REWINDING_EXPORT_STATUS[item.status]}</p>
                                    <p className="text-xs text-slate-600">{localDate(item.generated_at)} · {item.machine_code} · Camión {item.truck_number} · Orden {item.order_number}</p>
                                </div>
                                <div className="flex gap-2">
                                    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => {
                                        setSelected(item.id);
                                        setFeedback(null);
                                        setConfirming(false);
                                        setReason("");
                                    }}>Ver detalle</Button>
                                    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void download(item.id)}>Descargar PDF original</Button>
                                </div>
                            </li>)}
                        </ul>}
                    {offset > 0 || history.view.data.length === REWINDING_EXPORT_HISTORY_PAGE_SIZE ? <div className="flex gap-2">
                        <Button type="button" variant="outline" size="sm" disabled={busy || offset === 0} onClick={() => setOffset(offset - REWINDING_EXPORT_HISTORY_PAGE_SIZE)}>Anterior</Button>
                        <Button type="button" variant="outline" size="sm" disabled={busy || history.view.data.length < REWINDING_EXPORT_HISTORY_PAGE_SIZE} onClick={() => setOffset(offset + REWINDING_EXPORT_HISTORY_PAGE_SIZE)}>Siguiente</Button>
                    </div> : null}
                </>}
            {selected && !report ? <CentralStatus state={detail.view} onRetry={detail.refresh}/> : null}
            {report ? <section className="space-y-2 rounded-xl border p-4" aria-label="Detalle del reporte">
                <div className="flex items-center justify-between gap-2">
                    <h3 className="font-semibold">{report.order_number} · {REWINDING_EXPORT_STATUS[report.status]}</h3>
                    <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => {
                        setSelected("");
                        setConfirming(false);
                        setReason("");
                    }}>Cerrar detalle</Button>
                </div>
                <p className="text-sm">{report.pv_reference} · {report.article_code_snapshot}{report.articleDescription && ` · ${report.articleDescription}`} · {report.machine_code}</p>
                <p className="text-sm">Destino {report.destination} · Camión {report.truck_number} · {localDate(report.generated_at)}</p>
                {report.format && <p className="text-sm">Formato {report.format}</p>}
                {report.observations && <p className="whitespace-pre-wrap text-sm">{report.observations}</p>}
                {report.annulled_reason && <p className="text-sm">Motivo de anulación: {report.annulled_reason}</p>}
                <ul className="max-h-60 divide-y overflow-auto text-sm">
                    {report.packages.map(item => <li key={item.number} className="space-y-1 py-2">
                        <p className="font-semibold">Paquete {item.number} · Madre {item.mother}</p>
                        <p>{item.lines.map(line => `Cría ${line.slot} (N.º ${line.position}, ${line.weight} kg)`).join(" · ")}</p>
                        <p>{[
                            item.diameter && `Diámetro ${item.diameter}`, item.cuts && `Cortes ${item.cuts}`,
                            item.tubete && `Tubete ${item.tubete}`, item.helper && `Ayudante ${item.helper}`,
                            item.operator && `Operador ${item.operator}`,
                        ].filter(Boolean).join(" · ")}</p>
                    </li>)}
                </ul>
                {report.warnings.length > 0 && <ul aria-label="Advertencias de origen" className="list-disc pl-5 text-sm text-amber-900">
                    {report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
                </ul>}
                {canAnnul && report.status !== "annulled" && !confirming ? <Button type="button" variant="destructive" size="sm" onClick={() => setConfirming(true)}>Anular reporte</Button> : null}
                {canAnnul && report.status !== "annulled" && confirming ? <div className="space-y-2 rounded-lg border border-red-200 p-3" role="alertdialog" aria-label="Confirmar anulación de reporte">
                    <p className="text-sm">La anulación libera las reservas y conserva el PDF original.</p>
                    <Label htmlFor="rbe-annul-reason">Motivo de anulación (10 a 300 caracteres)</Label>
                    <textarea id="rbe-annul-reason" className="block w-full rounded-md border p-2 text-sm" value={reason} disabled={busy}
                        maxLength={300} onChange={event => setReason(event.target.value)}/>
                    <div className="flex gap-2">
                        <Button type="button" variant="destructive" size="sm" disabled={busy || reason.trim().length < 10} onClick={() => void annul()}>Confirmar anulación</Button>
                        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setConfirming(false); setReason(""); }}>Cancelar</Button>
                    </div>
                </div> : null}
            </section> : null}
            {feedback && <p className={feedback.error ? "text-sm text-red-800" : "text-sm text-emerald-800"} role={feedback.error ? "alert" : "status"}>{feedback.message}</p>}
        </div>
    </Panel>;
}
