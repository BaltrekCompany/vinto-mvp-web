"use client";

import { Button } from "@/components/ui/button";
import { CONTEXT_MESSAGES, type ContextCheck } from "@/lib/vinto/orders";

export type ExecState =
    | { kind: "loading" }
    | { kind: "error"; message: string; retry: () => void }
    | { kind: "check"; check: ContextCheck };

const OK = "border-emerald-300 bg-emerald-50";
const WARN = "border-amber-300 bg-amber-50";

// Estado del punto de captura: verde solo con una asignación vigente. Una asignación vencida (stale), sin turno resoluble o
// inexistente nunca da contexto de captura.
export function ContextBanner({ state, machine }: { state: ExecState; machine: string }) {
    if (state.kind === "loading") {
        return <div role="status" className={`mt-5 rounded-2xl border p-5 ${WARN}`}><p className="font-black">Consultando la asignación activa de {machine}…</p></div>;
    }
    if (state.kind === "error") {
        return <div role="alert" className={`mt-5 rounded-2xl border p-5 ${WARN}`}><p className="font-black">No se pudo consultar la asignación activa</p><p className="mt-1 text-sm">{state.message}</p><Button size="sm" className="mt-3 bg-[#146b4f]" onClick={state.retry}>Reintentar</Button></div>;
    }
    const { check } = state;
    if (check.ok) {
        const c = check.context;
        return <div className={`mt-5 rounded-2xl border p-5 ${OK}`}><p className="font-black">{`${c.otId} · ${c.lineId} · ${c.productName}`}</p><p className="mt-1 text-sm">{`${c.pv} · ${c.machine} · ${c.shift} · ${c.date}`}</p></div>;
    }
    const assignment = check.assignment;
    return <div role="alert" className={`mt-5 rounded-2xl border p-5 ${WARN}`}>
        <p className="font-black">{assignment ? `${assignment.work_order.number} · ${assignment.line.line_code} · ${assignment.line.article.description}` : "Sin asignación activa"}</p>
        <p className="mt-1 text-sm">{CONTEXT_MESSAGES[check.reason]}{check.reason === "none" ? " Supervisión debe activar una línea de OT." : ""}</p>
    </div>;
}
