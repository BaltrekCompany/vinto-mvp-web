"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { acknowledgeRevision, listRevisionNotices, type RevisionNotice } from "@/lib/vinto/revision-notices-api";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import { useResource } from "@/lib/vinto/use-central";

// E2-C1: operator read receipt for an already-assigned revised OT.
// Visible in all three production sectors, never in Calidad. No browser storage.
export function RevisionNoticeInbox({ scope, onSessionLost }: { scope: string; onSessionLost: () => void }) {
    const { view, refresh } = useResource<RevisionNotice[]>(
        `e2c1-revision-notices:${scope}`, true,
        signal => listRevisionNotices(signal), onSessionLost, true);
    const [busy, setBusy] = useState<string | null>(null);
    const guard = useRef(createMutationGuard());

    // Discard late responses on logout, unmount and account switch.
    useEffect(() => {
        const current = guard.current;
        return () => current.reset();
    }, [scope]);

    function acknowledge(notice: RevisionNotice) {
        if (busy || notice.acknowledged_at !== null || view.status !== "ready" || view.refreshing)
            return;
        void runGuarded(guard.current,
            () => acknowledgeRevision(notice.assignment_id, notice.version_number),
            {
                onStart: () => setBusy(notice.assignment_id),
                onOk: () => { toast.success("Lectura registrada para la versión asignada"); refresh(); },
                onSession: onSessionLost,
                onFailure: () => { toast.error("No se pudo registrar la lectura. Actualiza los avisos y reintenta."); refresh(); },
                onSettled: () => setBusy(null),
            });
    }

    return <section data-e2c1-revision-inbox="" className="mb-5 rounded-2xl border border-sky-200 bg-sky-50 p-4" aria-label="Avisos de cambios de programación">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-black text-sky-950">Cambios de programación asignada</h2>
                <p className="text-sm text-sky-900">Avisos dentro de VINTO sobre una versión modificada antes de su asignación. Confirma únicamente lo que hayas leído.</p></div>
            <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={view.status === "loading" || (view.status === "ready" && view.refreshing) || busy !== null}>Actualizar avisos</Button>
        </div>
        {view.status === "loading" && <p className="mt-3 text-sm" role="status">Consultando avisos vigentes…</p>}
        {view.status === "error" && <p className="mt-3 text-sm font-semibold text-red-800" role="alert">No fue posible verificar los avisos. Usa «Actualizar avisos». No se asume que estén leídos.</p>}
        {view.status === "ready" && <>
            {view.data.length === 0
                ? <p className="mt-3 text-sm text-sky-900">No tienes avisos de versiones reprogramadas en tus asignaciones activas.</p>
                : <div className="mt-3 grid gap-3">
                    <p className="text-sm font-semibold text-sky-950">Pendientes: {view.data.filter(n => n.acknowledged_at === null).length}</p>
                    {view.data.map(item => <div key={`${item.assignment_id}:${item.version_number}`} data-notice-assignment={item.assignment_id}
                        className="rounded-xl border border-sky-300 bg-white p-3 text-sm">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="font-bold">{item.work_order_number} · {item.line_code} · {item.machine_code} · versión {item.version_number}</div>
                            <span className={item.acknowledged_at ? "text-emerald-800" : "text-amber-900"}>
                                {item.acknowledged_at ? "Lectura confirmada" : "Lectura pendiente"}
                            </span>
                        </div>
                        <p className="mt-2">Motivo registrado: {item.reason}</p>
                        <p className="mt-1 text-slate-700">Programación asignada: PV {item.pv_reference} · Artículo {item.article_code} · Cantidad {item.quantity} · Entrega {item.due_date}</p>
                        <p className="mt-1 text-slate-600">Publicada: {new Date(item.revised_at).toLocaleString("es-PE")}</p>
                        {item.acknowledged_at
                            ? <p className="mt-1 text-emerald-800">Confirmada: {new Date(item.acknowledged_at).toLocaleString("es-PE")}</p>
                            : <Button size="sm" className="mt-3 bg-[#146b4f]" disabled={busy !== null || view.refreshing}
                                onClick={() => acknowledge(item)}>{busy === item.assignment_id ? "Registrando…" : "He leído esta programación"}</Button>}
                    </div>)}
                </div>}
        </>}
    </section>;
}
