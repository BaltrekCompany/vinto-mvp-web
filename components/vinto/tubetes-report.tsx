"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Download, FileSpreadsheet, Printer, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/vinto/panels";
import { getTubetesReport } from "@/lib/vinto/tubetes-report-api";
import { visibleTubetesMachines, type TubetesMachineSelection, type TubetesReport } from "@/lib/vinto/tubetes-report";
import type { ApiFailure } from "@/lib/vinto/central-http";
import { downloadTubetesPdf, openTubetesPdfForPrint } from "@/lib/vinto/tubetes-pdf";
import { downloadTubetesExcel } from "@/lib/vinto/tubetes-excel";

function displayDate(value: string): string {
    const [year, month, day] = value.split("-");
    return day && month && year ? day + "/" + month + "/" + year : value;
}

function generatedLabel(value: string): string {
    return new Intl.DateTimeFormat("es-PE", {
        dateStyle: "short", timeStyle: "short", timeZone: "America/La_Paz",
    }).format(new Date(value));
}

function failureLabel(error: ApiFailure): string {
    if (error.kind === "session") return "Tu sesión venció. Vuelve a iniciar sesión para consultar el reporte.";
    if (error.kind === "forbidden") return "Tu usuario no tiene permiso para consultar este reporte o no tiene concedido el sector Bobinas.";
    return "No fue posible consultar el reporte. Comprueba la conexión e inténtalo nuevamente.";
}

function MachineTable({ report }: { report: TubetesReport["machines"][number] }) {
    return <section className="rounded-xl border bg-white p-4" aria-label={"Usos de tubetes en " + report.machine}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-lg font-black">{report.machine}</h3>
            <Badge variant="outline">{report.usage_total} {report.usage_total === 1 ? "uso" : "usos"}</Badge>
        </div>
        {report.tubetes.length === 0 ? <p className="text-sm text-slate-600">No hay utilizaciones con código registradas para esta máquina.</p>
            : <div className="w-full min-w-0"><table className="w-full table-fixed text-left text-xs sm:text-sm">
                <colgroup><col style={{ width: "22%" }}/><col style={{ width: "15%" }}/><col style={{ width: "63%" }}/></colgroup>
                <thead className="bg-slate-50 text-xs uppercase text-slate-600"><tr>
                    <th className="break-words px-2 py-2">Código</th><th className="break-words px-2 py-2">Usos</th><th className="break-words px-2 py-2">Fechas de utilización</th>
                </tr></thead>
                <tbody>{report.tubetes.map(item => <tr key={item.code} className="border-t align-top">
                    <td className="break-all px-2 py-3 font-bold tabular-nums">{item.code}</td>
                    <td className="px-2 py-3 tabular-nums">{item.usage_count}</td>
                    <td className="px-2 py-3"><div className="flex flex-wrap gap-1.5">{item.dates.map((date, index) => <span key={date + "-" + index} className="whitespace-nowrap rounded-md bg-slate-100 px-2 py-1 text-[11px] tabular-nums">{displayDate(date)}</span>)}</div></td>
                </tr>)}</tbody>
            </table></div>}
        {report.records_without_code > 0 && <p className="mt-3 text-xs text-slate-500">Registros históricos sin código de tubete: {report.records_without_code}. No se contabilizan como uso.</p>}
    </section>;
}

export function TubetesReportEntry({ onSessionLost }: { onSessionLost: () => void }) {
    const onSessionLostRef = useRef(onSessionLost);
    const [opened, setOpened] = useState(false);
    const [refresh, setRefresh] = useState(0);
    const [exportError, setExportError] = useState(false);
    const [machineSelection, setMachineSelection] = useState<TubetesMachineSelection>("all");
    const [result, setResult] = useState<{ status: "loading" } | { status: "ready"; data: TubetesReport } | { status: "error"; error: ApiFailure }>({ status: "loading" });

    useEffect(() => {
        onSessionLostRef.current = onSessionLost;
    }, [onSessionLost]);

    useEffect(() => {
        if (!opened) return;
        const controller = new AbortController();
        void getTubetesReport(controller.signal).then(reply => {
            if (controller.signal.aborted) return;
            if (reply.ok) setResult({ status: "ready", data: reply.data });
            else {
                setResult({ status: "error", error: reply });
                if (reply.kind === "session") onSessionLostRef.current();
            }
        }).catch(error => {
            if (error instanceof DOMException && error.name === "AbortError") return;
            if (!controller.signal.aborted) setResult({ status: "error", error: { ok: false, kind: "unavailable", status: 0 } });
        });
        return () => controller.abort();
    }, [opened, refresh]);

    function openReport() {
        setResult({ status: "loading" });
        setExportError(false);
        setOpened(true);
    }

    function refreshReport() {
        setResult({ status: "loading" });
        setExportError(false);
        setRefresh(value => value + 1);
    }

    function handleDownloadPdf() {
        if (result.status !== "ready") return;
        try {
            downloadTubetesPdf(result.data);
            setExportError(false);
        } catch {
            setExportError(true);
        }
    }

    function handlePrintPdf() {
        if (result.status !== "ready") return;
        try {
            openTubetesPdfForPrint(result.data);
            setExportError(false);
        } catch {
            setExportError(true);
        }
    }

    function handleDownloadExcel() {
        if (result.status !== "ready") return;
        try {
            // La exportación contiene las dos hojas oficiales: MP1 y MP3,
            // independientemente de la máquina seleccionada para la vista.
            downloadTubetesExcel(result.data);
            setExportError(false);
        } catch {
            setExportError(true);
        }
    }

    if (!opened) return <div className="rounded-lg border p-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-semibold">Tubetes utilizados</p><p className="mt-1 text-xs font-normal text-slate-600">Consumo registrado en Producción de Bobinas P1-03 · MP1 y MP3</p></div>
            <Button size="sm" onClick={openReport}>Abrir reporte</Button></div>
    </div>;

    return <div className="space-y-4 rounded-xl border bg-slate-50 p-4" data-testid="tubetes-report">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-black">Tubetes utilizados</h3><p className="text-sm text-slate-600">Fuente: VINTO-P1-03 · Fecha operativa · America/La_Paz</p></div>
            <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={handleDownloadPdf} disabled={result.status !== "ready"}><Download className="h-4 w-4"/>Descargar PDF</Button><Button variant="outline" size="sm" onClick={handleDownloadExcel} disabled={result.status !== "ready"}><FileSpreadsheet className="h-4 w-4"/>Descargar Excel</Button><Button variant="outline" size="sm" onClick={handlePrintPdf} disabled={result.status !== "ready"}><Printer className="h-4 w-4"/>Imprimir</Button><Button variant="outline" size="sm" onClick={refreshReport} disabled={result.status === "loading"}><RefreshCw className="h-4 w-4"/>Actualizar</Button><Button variant="ghost" size="sm" onClick={() => setOpened(false)}><ArrowLeft className="h-4 w-4"/>Volver</Button></div></div>
        {exportError && <p role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">No se pudo generar el archivo. Inténtalo nuevamente.</p>}
        {result.status === "loading" && <p role="status" className="rounded-lg border bg-white p-4 text-sm text-slate-600">Consultando utilizaciones de tubetes…</p>}
        {result.status === "error" && <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{failureLabel(result.error)}<div className="mt-3"><Button size="sm" variant="outline" onClick={refreshReport}>Reintentar</Button></div></div>}
        {result.status === "ready" && <><p className="text-xs text-slate-500">Actualizado: {generatedLabel(result.data.generated_at)} · Las fechas repetidas representan utilizaciones distintas y se conservan.</p>
            <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Seleccionar máquina para visualizar">
                    <span className="mr-1 text-sm font-semibold">Ver:</span>
                    <Button size="sm" variant={machineSelection === "all" ? "default" : "outline"} aria-pressed={machineSelection === "all"} onClick={() => setMachineSelection("all")}>Ambas</Button>
                    <Button size="sm" variant={machineSelection === "MP1" ? "default" : "outline"} aria-pressed={machineSelection === "MP1"} onClick={() => setMachineSelection("MP1")}>MP1</Button>
                    <Button size="sm" variant={machineSelection === "MP3" ? "default" : "outline"} aria-pressed={machineSelection === "MP3"} onClick={() => setMachineSelection("MP3")}>MP3</Button>
                </div>
                <p className="text-xs text-slate-500">La selección cambia solo la vista. El PDF y el Excel incluyen siempre MP1 y MP3.</p>
            </div>
            <div className="flex min-w-0 flex-col gap-4">{visibleTubetesMachines(result.data, machineSelection).map(machine => <MachineTable key={machine.machine} report={machine}/>)}</div></>}
    </div>;
}

export function TubetesReportPanel({ onSessionLost }: { onSessionLost: () => void }) {
    return <Panel title="Reportes" note="Consultas automáticas construidas desde registros centrales; no requieren volver a digitar información.">
        <div className="space-y-2"><TubetesReportEntry onSessionLost={onSessionLost}/>
            <p className="text-xs text-slate-500">Los demás reportes se habilitarán en sus incrementos correspondientes.</p>
        </div>
    </Panel>;
}
