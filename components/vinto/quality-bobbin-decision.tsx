"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import { REJECTION_CLASSES, REJECTION_TYPES, submitQualityDecision } from "@/lib/vinto/quality-decision-api";

type Props = { item: QualityBobbinInboxItem; refresh: () => void };

export function QualityBobbinDecision({ item, refresh }: Props) {
    const [open, setOpen] = useState(false);
    const [rejectionType, setRejectionType] = useState("");
    const [classification, setClassification] = useState("");
    const [detail, setDetail] = useState("");
    const [correctiveAction, setCorrectiveAction] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [done, setDone] = useState(false);

    const canReject = rejectionType !== "" && classification !== "" && detail.trim() !== "" && correctiveAction.trim() !== "" &&
        detail.length <= 4000 && correctiveAction.length <= 4000;

    async function submit(action: "release" | "reject") {
        if (busy || done || (action === "reject" && !canReject)) return;
        // La clave es nueva por intencion del usuario. No creamos reintentos concurrentes.
        const decision_id = crypto.randomUUID();
        setBusy(true);
        setError("");
        try {
            const body = action === "release"
                ? { decision_id, action }
                : { decision_id, action, rejection_type: rejectionType, classification, detail: detail.trim(), corrective_action: correctiveAction.trim() };
            const result = await submitQualityDecision(item.bobbin.id, body);
            if (!result.ok) {
                setError(result.status === 409 ? "Esta bobina ya fue evaluada. Actualiza la bandeja." :
                    result.status === 403 ? "No tienes permiso para decidir sobre esta bobina." :
                    "No se pudo guardar la decision. Actualiza y vuelve a consultar antes de repetir.");
                return;
            }
            setDone(true);
            setOpen(false);
            refresh();
        } catch {
            setError("No se pudo confirmar la decision. Actualiza la bandeja antes de volver a intentar.");
        } finally { setBusy(false); }
    }

    return <div className="space-y-2" data-quality-decision={item.bobbin.id}>
        <Button size="sm" className="bg-[#146b4f]" disabled={busy || done}
            aria-label={`Liberar bobina ${item.bobbin.code}`}
            onClick={() => { if (window.confirm(`¿Liberar la bobina ${item.bobbin.code} de ${item.bobbin.machine.code}?`)) void submit("release"); }}>
            Liberar
        </Button>
        <Button size="sm" variant="outline" disabled={busy || done}
            aria-label={`Rechazar bobina ${item.bobbin.code}`} onClick={() => { setOpen(v => !v); setError(""); }}>
            Rechazar
        </Button>
        {open && <div className="min-w-[240px] space-y-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm">
            <p className="font-bold">Rechazar bobina {item.bobbin.code} — {item.bobbin.machine.code}</p>
            <label className="block font-medium">Tipo
                <select className="mt-1 w-full rounded border bg-white p-2" value={rejectionType} onChange={e => setRejectionType(e.target.value)} disabled={busy}>
                    <option value="">Seleccionar</option>
                    {REJECTION_TYPES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
                </select>
            </label>
            <label className="block font-medium">Clasificación
                <select className="mt-1 w-full rounded border bg-white p-2" value={classification} onChange={e => setClassification(e.target.value)} disabled={busy}>
                    <option value="">Seleccionar</option>
                    {REJECTION_CLASSES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
                </select>
            </label>
            <label className="block font-medium">Detalle
                <textarea className="mt-1 w-full rounded border bg-white p-2" rows={3} maxLength={4000} value={detail} onChange={e => setDetail(e.target.value)} disabled={busy}/>
            </label>
            <label className="block font-medium">Acción correctiva
                <textarea className="mt-1 w-full rounded border bg-white p-2" rows={3} maxLength={4000} value={correctiveAction} onChange={e => setCorrectiveAction(e.target.value)} disabled={busy}/>
            </label>
            <Button size="sm" disabled={busy || done || !canReject} onClick={() => void submit("reject")}>
                {busy ? "Guardando…" : "Confirmar rechazo"}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Cancelar</Button>
        </div>}
        {error && <p role="alert" className="max-w-[260px] text-xs text-red-800">{error}</p>}
        {done && <p role="status" className="text-xs text-green-800">Decisión guardada</p>}
    </div>;
}
