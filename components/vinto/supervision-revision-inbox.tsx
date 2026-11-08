"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
    acknowledgeSupervisionRevision, listSupervisionNotices,
    type SupervisionRevisionNotice, type SupervisionRevisionFields,
} from "@/lib/vinto/supervision-revision-api";
import { createMutationGuard, runGuarded } from "@/lib/vinto/mutation-guard";
import { useResource } from "@/lib/vinto/use-central";

const line = (f: SupervisionRevisionFields) =>
    `PV ${f.pv_reference} · Artículo ${f.article_code} · Cantidad ${f.quantity} · Entrega ${f.due_date}`;

// Only managers with assignment.manage mount this component; API enforces it
// independently. No browser storage/polling or capture/activation blocking.
export function SupervisionRevisionInbox({ scope, onSessionLost }: {
    scope: string; onSessionLost: () => void;
}) {
    const { view, refresh } = useResource<SupervisionRevisionNotice[]>(
        `e2c2-supervision-revisions:${scope}`, true,
        signal => listSupervisionNotices(signal), onSessionLost, true);
    const [busy, setBusy] = useState<string | null>(null);
    const guard = useRef(createMutationGuard());
    useEffect(() => {
        const current = guard.current;
        return () => current.reset();
    }, [scope]);

    function acknowledge(notice: SupervisionRevisionNotice) {
        if (busy || notice.acknowledged_at || view.status !== "ready" || view.refreshing) return;
        void runGuarded(guard.current,
            () => acknowledgeSupervisionRevision(notice.work_order_id, notice.version_number),
            {
                onStart: () => setBusy(notice.work_order_id),
                onOk: () => { toast.success("Supervisión confirmó la lectura de la versión"); refresh(); },
                onSession: onSessionLost,
                onFailure: () => {
                    toast.error("No se confirmó la versión. Actualiza los avisos y revisa si cambió la programación.");
                    refresh();
                },
                onSettled: () => setBusy(null),
            });
    }

    return <section data-e2c2-supervision-inbox="" aria-label="Avisos de reprogramación para Supervisión"
        className="mb-5 rounded-2xl border border-amber-300 bg-amber-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
                <h2 className="font-black text-amber-950">Supervisión · Reprogramaciones por revisar</h2>
                <p className="text-sm text-amber-950">
                    Consulta los cambios publicados por Jefatura antes de habilitar líneas.
                    Esta confirmación registra lectura, no autoriza cambios en producción ni bloquea la asignación.
                </p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={refresh}
                disabled={busy !== null || view.status === "loading" || (view.status === "ready" && view.refreshing)}>
                Actualizar avisos
            </Button>
        </div>
        {view.status === "loading" && <p className="mt-3 text-sm" role="status">Consultando reprogramaciones…</p>}
        {view.status === "error" && <p className="mt-3 text-sm font-semibold text-red-800" role="alert">
            No se pudo verificar el historial vigente. Actualiza los avisos; no se asumen como revisados.
        </p>}
        {view.status === "ready" && (view.data.length === 0
            ? <p className="mt-3 text-sm">No hay reprogramaciones publicadas vigentes dentro de tus sectores.</p>
            : <div className="mt-3 grid gap-3">
                <p className="text-sm font-semibold text-amber-950">
                    Pendientes para tu usuario: {view.data.filter(n => n.acknowledged_at === null).length}
                </p>
                {view.data.map(n => <article key={`${n.work_order_id}:${n.version_number}`}
                    data-supervision-revision={n.work_order_id}
                    className="rounded-xl border border-amber-200 bg-white p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <strong>{n.work_order_number} · {n.line_code} · {n.machine_code} · versión {n.version_number}</strong>
                        <span className={n.acknowledged_at ? "font-medium text-emerald-800" : "font-medium text-amber-900"}>
                            {n.acknowledged_at ? "Lectura confirmada" : "Pendiente de lectura"}
                        </span>
                    </div>
                    <p className="mt-2">Motivo: {n.reason}</p>
                    <p className="mt-1 text-slate-600">Registrado por {n.changed_by ?? "Usuario no disponible"} · {new Date(n.revised_at).toLocaleString("es-PE")}</p>
                    <div className="mt-2 grid gap-2 rounded-lg bg-slate-50 p-3">
                        <p><b>Antes:</b> {line(n.before)}</p>
                        <p><b>Ahora:</b> {line(n.after)}</p>
                    </div>
                    {n.acknowledged_at
                        ? <p className="mt-2 font-medium text-emerald-800">
                            Confirmación registrada: {new Date(n.acknowledged_at).toLocaleString("es-PE")}
                          </p>
                        : <Button type="button" className="mt-3 bg-[#146b4f]" size="sm"
                            disabled={busy !== null || view.refreshing}
                            onClick={() => acknowledge(n)}>
                            {busy === n.work_order_id ? "Registrando…" : "He revisado esta versión"}
                          </Button>}
                </article>)}
              </div>)}
    </section>;
}
