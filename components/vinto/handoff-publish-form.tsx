"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { OrderDraftEditor, type CatalogItem } from "@/components/vinto/order-draft-editor";
import { validateRows, type DraftRow, type RowError } from "@/lib/vinto/order-draft";
import type { OpenHandoff } from "@/lib/vinto/handoff";
import type { LineDraft, WorkOrder } from "@/lib/vinto/orders";

// Jefatura: edita un borrador LOCAL de la nueva version; publica con el
// snapshot esperado por el servidor (CAS). Nunca toca la baseline o asignacion.
export function HandoffPublishForm({ handoff, order, catalog, busy, onPublish }: {
    handoff: OpenHandoff;
    order: WorkOrder;
    catalog: (machine: string) => readonly CatalogItem[];
    busy: boolean;
    onPublish: (expected: LineDraft, replacement: LineDraft, reason: string) => void;
}) {
    const latest = order.programming ?? order.baseline;
    const line = latest.lines.find(item => item.line_code === handoff.line_code && item.machine.code === handoff.machine_code);
    const [row, setRow] = useState<DraftRow>(() => ({
        key: handoff.handoff_id, machine: handoff.machine_code,
        pv: line?.pv_reference ?? "", code: line?.article.code ?? "",
        qty: line ? String(line.quantity) : "", date: line?.due_date ?? "",
    }));
    const [reason, setReason] = useState("");
    const [errors, setErrors] = useState<RowError[]>([]);
    const [confirmation, setConfirmation] = useState<LineDraft | null>(null);
    // La version v2 inicial no aparece como `programming` en el GET
    // historico hasta que haya reprogramaciones; en ese caso baseline=v1.
    const versionOk = latest.version_number === handoff.expected_version ||
        (!order.programming && handoff.expected_version === 2 && order.baseline.version_number === 1);
    if (!line || !versionOk || order.status !== "in_progress") {
        return <p role="alert" className="text-sm text-red-800">
            La OT o su version operativa cambio. Actualiza antes de publicar.
        </p>;
    }
    const original: LineDraft = {
        pvReference: line.pv_reference,
        articleCode: line.article.code,
        quantity: line.quantity,
        dueDate: line.due_date,
    };
    const changed = row.pv.trim() !== original.pvReference ||
        row.code !== original.articleCode ||
        Number(row.qty) !== original.quantity ||
        row.date !== original.dueDate;

    function prepare() {
        const checked = validateRows([row], {
            multi: false, machines: [line!.machine.code], catalog,
        });
        if (!checked.ok) { setErrors(checked.errors); return; }
        if (!changed || reason.trim().length < 10 || reason.trim().length > 300) return;
        setErrors([]);
        setConfirmation(checked.lines[0]);
    }

    return <div className="mt-3 space-y-3 rounded-lg border bg-slate-50 p-3" data-d2-publish-form={handoff.handoff_id}>
        <p className="text-sm font-bold">Jefatura: publicar version v{handoff.expected_version + 1}</p>
        <p className="text-xs text-slate-700">Antes: {line.article.code} · {line.quantity} {line.unit} · PV {line.pv_reference} · entrega {line.due_date}. La maquina no se puede cambiar.</p>
        <OrderDraftEditor rows={[row]} onRows={next => setRow(next[0])}
            machines={[line.machine]} catalog={catalog} multi={false} lockMachine fixedRows
            disabled={busy} errors={errors} nextKey={() => handoff.handoff_id}/>
        <label htmlFor={"d2-publish-reason-" + handoff.handoff_id} className="block text-sm font-semibold">Motivo obligatorio (10-300 caracteres)</label>
        <Input id={"d2-publish-reason-" + handoff.handoff_id} value={reason}
            onChange={event => setReason(event.target.value)} maxLength={300}
            disabled={busy} autoComplete="off" placeholder="Motivo de la reprogramacion"/>
        <Button type="button" variant="outline"
            disabled={busy || !changed || reason.trim().length < 10}
            onClick={prepare}>Revisar nueva version</Button>
        <AlertDialog open={confirmation !== null} onOpenChange={open => { if (!open && !busy) setConfirmation(null); }}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Publicar nueva version v{handoff.expected_version + 1}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {order.number} · {handoff.line_code} · {handoff.machine_code}.
                        Cantidad {original.quantity} a {confirmation?.quantity}; producto {original.articleCode} a {confirmation?.articleCode}.
                        La asignacion anterior no se sustituye hasta que Supervision confirme la reasignacion.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={busy}>Cancelar</AlertDialogCancel>
                    <AlertDialogAction disabled={busy || confirmation === null}
                        onClick={() => {
                            if (!confirmation) return;
                            const next = confirmation;
                            setConfirmation(null);
                            onPublish(original, next, reason.trim());
                        }}>Confirmar publicacion</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    </div>;
}
