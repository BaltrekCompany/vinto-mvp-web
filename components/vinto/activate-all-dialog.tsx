"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ActivateAllResponse, PlanLine } from "@/lib/vinto/activate-all";
import {
    NOTHING_TO_DO, PROBLEM_MESSAGES, canConfirmPlan, canRetryPreview, classifyFailure, conflictMessage, flowReducer, groupLines, isActionable, previewHeadline, reasonLabel, resultMessage, startPreviewing,
    type FlowState,
} from "@/lib/vinto/activate-all-flow";
import { pickReturnTarget, type FocusTarget } from "@/lib/vinto/focus-return";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import type { Assignment } from "@/lib/vinto/orders";
import { confirmActivateAll, previewActivateAll } from "@/lib/vinto/work-orders-api";

type Row = { key: string; line: string; machine: string; product: string; pv: string; when: string; note?: string };
const whenOf = (shift: string | null, date: string | null) => (shift && date ? `${shift} · ${date}` : "—");
const rowOfLine = (line: PlanLine, note?: string): Row => ({ key: line.baseline_line_id, line: line.line_code, machine: line.machine.code, product: `${line.article.code} · ${line.article.description}`, pv: line.pv_reference,
    when: whenOf(line.shift?.name ?? null, line.operating_date), note });
const rowOfAssignment = (a: Assignment): Row => ({ key: a.id, line: a.line.line_code, machine: a.machine.code, product: `${a.line.article.code} · ${a.line.article.description}`, pv: a.line.pv_reference, when: whenOf(a.shift.name, a.operating_date) });

// Tabla compacta de tres columnas (línea y máquina / producto y PV / turno y fecha): cabe en móvil sin desplazamiento horizontal que oculte lo importante.
function Section({ id, title, rows, withNote }: { id: string; title: string; rows: Row[]; withNote?: boolean }) {
    if (rows.length === 0) return null;
    return <section data-section={id} aria-labelledby={`aa-${id}`} className="space-y-2">
        <h3 id={`aa-${id}`} className="text-sm font-black">{title} ({rows.length})</h3>
        <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm"><caption className="sr-only">{title}</caption>
            <thead className="bg-muted text-left text-foreground"><tr><th scope="col" className="p-2">Línea y máquina</th><th scope="col" className="p-2">Producto y PV</th><th scope="col" className="p-2">Turno y fecha</th>{withNote && <th scope="col" className="p-2">Motivo</th>}</tr></thead>
            <tbody>{rows.map(row => <tr key={row.key} className="border-t align-top"><td className="p-2"><b>{row.line}</b> · {row.machine}</td><td className="p-2">{row.product}<br /><span className="text-muted-foreground">PV {row.pv}</span></td><td className="p-2">{row.when}</td>{withNote && <td className="p-2">{row.note}</td>}</tr>)}</tbody></table></div>
    </section>;
}

type PanelProps = { state: FlowState; onConfirm: () => void; onRefresh: () => void; onClose: () => void; lineExecutionEnabled?: boolean };

// Contenido del diálogo (presentacional). Nada de «activación realizada» hasta que el servidor confirme el éxito (fase `done`).
export function ActivateAllPanel({ state, onConfirm, onRefresh, onClose, lineExecutionEnabled = false }: PanelProps) {
    return <div data-activate-all="" data-phase={state.phase} className="space-y-4">
        <div aria-live="polite" role="status" className="text-sm text-muted-foreground">
            {state.phase === "previewing" && "Consultando la vista previa (solo lectura)…"}
            {state.phase === "confirming" && "Enviando la confirmación al servidor…"}
        </div>
        {(state.phase === "preview" || state.phase === "confirming") && <PlanView plan={state.plan} lineExecutionEnabled={lineExecutionEnabled}/>}
        {state.phase === "done" && <DoneView result={state.result} lineExecutionEnabled={lineExecutionEnabled}/>}
        {state.phase === "problem" && <div role="alert" data-problem={state.problem} className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-700 dark:bg-red-950 dark:text-red-100">{PROBLEM_MESSAGES[state.problem]}</div>}
        <DialogFooter className="gap-2">
            {/* Orden del DOM = orden de tabulación: «Cerrar» primero (el foco inicial nunca cae sobre la confirmación); en escritorio la acción principal queda a la derecha y en móvil (columna invertida) arriba. */}
            <Button type="button" variant="outline" disabled={state.phase === "confirming"} onClick={onClose}>Cerrar</Button>
            {state.phase === "preview" && <Button type="button" variant="outline" onClick={onRefresh}>Actualizar vista previa</Button>}
            {state.phase === "problem" && canRetryPreview(state.problem) && <Button type="button" variant="outline" onClick={onRefresh}>{state.problem === "uncertain" ? "Consultar la situación (solo lectura)" : "Consultar de nuevo la vista previa"}</Button>}
            {(state.phase === "preview" || state.phase === "confirming") && <Button type="button" className="bg-[#146b4f] text-white hover:bg-[#0f5a41]" disabled={state.phase === "confirming" || !canConfirmPlan(state.plan)} onClick={onConfirm}>
                {state.phase === "confirming" ? (lineExecutionEnabled ? "Habilitando…" : "Activando…") : (lineExecutionEnabled ? "Confirmar habilitación de " : "Confirmar activación de ") + state.plan.summary.activate + " línea(s)"}</Button>}
        </DialogFooter>
    </div>;
}

function PlanView({ plan, lineExecutionEnabled = false }: { plan: ActivateAllResponse; lineExecutionEnabled?: boolean }) {
    const groups = groupLines(plan);
    return <div className="space-y-4">
        <p data-headline="" className="rounded-lg bg-muted p-3 text-sm font-bold text-foreground">{previewHeadline(plan)}</p>
        {plan.conflicts.length > 0 && <div role="alert" data-section="conflicts" className="space-y-1 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-700 dark:bg-red-950 dark:text-red-100"><h3 className="font-black">Conflictos con otras OT ({plan.conflicts.length}) — la activación está bloqueada</h3>
            <ul className="list-disc pl-5">{[...new Set(plan.conflicts.map(conflictMessage))].map(message => <li key={message}>{message}</li>)}</ul></div>}
        <Section id="activate" title={lineExecutionEnabled ? "Líneas por habilitar" : "Líneas por activar"} rows={groups.toActivate.map(line => rowOfLine(line))}/>
        <Section id="already_active" title={lineExecutionEnabled ? "Líneas ya habilitadas en el turno vigente" : "Líneas ya activas en el turno vigente"} rows={groups.alreadyActive.map(line => rowOfLine(line))}/>
        <Section id="blocked" title="Líneas bloqueadas" rows={groups.blocked.map(line => rowOfLine(line, reasonLabel(line.reason)))} withNote/>
        {plan.expired.length > 0 && <section data-section="expired" aria-labelledby="aa-expired" className="space-y-2"><h3 id="aa-expired" className="text-sm font-black">Asignaciones vencidas de esta OT que se finalizarán ({plan.expired.length})</h3>
            <ul className="list-disc pl-5 text-sm">{plan.expired.map(item => <li key={item.assignment_id}>{item.line_code} · {item.machine.code}</li>)}</ul></section>}
        {plan.can_confirm && !isActionable(plan) && <p data-nothing="" className="text-sm text-muted-foreground">{NOTHING_TO_DO}</p>}
        <p className="text-xs text-muted-foreground">Esta vista previa es informativa: no modifica asignaciones. Los turnos y fechas los resuelve el servidor al confirmar.</p>
    </div>;
}

function DoneView({ result, lineExecutionEnabled = false }: { result: ActivateAllResponse; lineExecutionEnabled?: boolean }) {
    return <div data-section="result" className="space-y-4">
        <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm font-bold text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100">{resultMessage(result)}</p>
        <Section id="activated" title={lineExecutionEnabled ? "Líneas habilitadas" : "Líneas activadas"} rows={result.activated.map(rowOfAssignment)}/>
        <Section id="already_active_result" title={lineExecutionEnabled ? "Líneas previamente habilitadas" : "Líneas que ya estaban activas"} rows={result.already_active.map(rowOfAssignment)}/>
        <Section id="finished" title="Asignaciones vencidas finalizadas" rows={result.finished.map(rowOfAssignment)}/>
    </div>;
}

type Props = {
    orderId: string;
    orderNumber: string;
    lineExecutionEnabled?: boolean;
    onClose: () => void;
    onSessionLost: () => void;
    onApplied: () => void; // el servidor confirmó (applied / already_in_effect): reconciliar las listas con GET
    onDisabled: () => void; // 422 MULTI_MACHINE_DISABLED: deshabilitar la activación masiva y volver a pedir las capacidades
    // PR-A (DEF-1): destinos del foco al cerrar, por orden de preferencia (invocador, su tarjeta, el panel). Se evalúan AL CERRAR: el invocador pudo desaparecer o quedar deshabilitado.
    returnFocusTargets?: () => ReadonlyArray<FocusTarget | null | undefined>;
};

// Diálogo con estado: vista previa de solo lectura al abrir -> confirmación con el MISMO hash. Una sola escritura a la vez (mutation-guard); al desmontar (cierre, otra OT o cambio de sesión)
// se descartan el plan, su hash y cualquier respuesta tardía. El hash no se escribe en ningún almacenamiento.
export function ActivateAllDialog({ orderId, orderNumber, lineExecutionEnabled = false, onClose, onSessionLost, onApplied, onDisabled, returnFocusTargets }: Props) {
    const [state, dispatch] = useReducer(flowReducer, orderId, startPreviewing);
    const [guard] = useState(createMutationGuard);
    const latest = useRef({ onSessionLost, onApplied, onDisabled });
    useEffect(() => { latest.current = { onSessionLost, onApplied, onDisabled }; });

    function preview(initial: boolean) {
        void runGuarded(guard, () => previewActivateAll(orderId), {
            onStart: () => { if (!initial) dispatch({ type: "preview_start", orderId }); },
            onOk: plan => dispatch({ type: "preview_ok", orderId, plan }),
            onSession: () => latest.current.onSessionLost(),
            onFailure: (_kind, failure) => { if (classifyFailure("preview", failure) === "disabled") latest.current.onDisabled(); dispatch({ type: "preview_failed", orderId, failure }); },
            onSettled: () => undefined,
        });
    }
    useEffect(() => { preview(true); return () => guard.reset(); }, [guard, orderId]); // eslint-disable-line react-hooks/exhaustive-deps -- `preview` solo usa `orderId`, `guard` y refs estables

    function confirm() {
        if (state.phase !== "preview" || !canConfirmPlan(state.plan) || guard.busy()) return; // sin vista previa vigente, o ya hay una escritura en curso (doble clic)
        const hash = state.plan.plan_hash; // el hash del servidor, sin tocar
        dispatch({ type: "confirm_start", orderId });
        void runGuarded(guard, () => confirmActivateAll(orderId, hash), {
            onStart: () => undefined,
            onOk: result => { dispatch({ type: "confirm_ok", orderId, result }); latest.current.onApplied(); },
            onSession: () => latest.current.onSessionLost(),
            onFailure: (_kind, failure) => { if (classifyFailure("confirm", failure) === "disabled") latest.current.onDisabled(); dispatch({ type: "confirm_failed", orderId, failure }); }, // sin reintento automático
            onSettled: () => undefined,
        });
    }
    function refresh() { if (!guard.busy()) preview(false); }

    return <Dialog open onOpenChange={open => { if (!open && state.phase !== "confirming") onClose(); }}>
        <DialogContent showCloseButton={state.phase !== "confirming"} className="max-h-[90vh] overflow-y-auto sm:max-w-3xl" onInteractOutside={event => { if (state.phase === "confirming") event.preventDefault(); }} onEscapeKeyDown={event => { if (state.phase === "confirming") event.preventDefault(); }}
            onCloseAutoFocus={event => { // Radix cancela la restauración por defecto y enfoca su DialogTrigger, que aquí no existe (se abre por estado): se devuelve el foco explícitamente.
                const target = pickReturnTarget(returnFocusTargets?.() ?? []);
                if (target) { event.preventDefault(); target.focus(); }
            }}>
            <DialogHeader><DialogTitle>{lineExecutionEnabled ? "Habilitar" : "Activar"} todas las líneas de {orderNumber} <Badge className="ml-2 align-middle">Vista previa</Badge></DialogTitle>
                <DialogDescription>{lineExecutionEnabled ? "Se habilitan las líneas de la OT para este turno. Supervisión deberá iniciar expresamente cada línea antes de que Operación pueda capturar; nunca se inicia producción múltiple en una máquina." : "Se activan, en una sola operación, todas las líneas de la OT en sus máquinas. Activar deja la línea disponible para que Operación la seleccione; no es producción simultánea."}</DialogDescription></DialogHeader>
            <ActivateAllPanel state={state} onConfirm={confirm} onRefresh={refresh} onClose={onClose} lineExecutionEnabled={lineExecutionEnabled}/>
        </DialogContent>
    </Dialog>;
}
