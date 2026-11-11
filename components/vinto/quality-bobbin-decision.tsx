"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import { REJECTION_CLASSES, REJECTION_TYPES, submitQualityDecision } from "@/lib/vinto/quality-decision-api";

type Props = { item: QualityBobbinInboxItem; refresh: () => void };

export function QualityBobbinDecision({ item, refresh }: Props) {
    const [open, setOpen] = useState(false);
    const dialogRef = useRef<HTMLElement>(null);
    const [review, setReview] = useState(false);
    const [rejectionType, setRejectionType] = useState("");
    const [classification, setClassification] = useState("");
    const [detail, setDetail] = useState("");
    const [correctiveAction, setCorrectiveAction] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [done, setDone] = useState(false);

    const canReject = rejectionType !== "" && classification !== "" && detail.trim() !== "" && correctiveAction.trim() !== "" &&
        detail.length <= 4000 && correctiveAction.length <= 4000;
    const typeLabel = REJECTION_TYPES.find(x => x.value === rejectionType)?.label ?? "Sin seleccionar";
    const classLabel = REJECTION_CLASSES.find(x => x.value === classification)?.label ?? "Sin seleccionar";
    const child = item.bobbin.rewinding;
    const isChild = Boolean(child);
    const actionable = item.quality.status === "pending";

    // Sólo crías P1-07: modal con foco encerrado y Escape para cancelar.
    // F3 conserva su presentación anterior y sus propios controles.
    useEffect(() => {
        if (!open || !isChild) return;
        const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const focusable = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]), select:not([disabled]), textarea:not([disabled])'
        ) ?? []);
        focusable()[0]?.focus();
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape" && !busy) {
                event.preventDefault();
                setOpen(false);
                setReview(false);
            }
            if (event.key !== "Tab") return;
            const nodes = focusable();
            if (nodes.length === 0) { event.preventDefault(); return; }
            const first = nodes[0], last = nodes[nodes.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => { window.removeEventListener("keydown", onKey); previous?.focus(); };
    }, [open, isChild, busy]);
    const subject = child ? `cría ${child.child_position} de la madre ${child.mother_label}` : `bobina ${item.bobbin.code}`;

    async function submit(action: "release" | "reject") {
        if (!actionable || busy || done || (action === "reject" && (!canReject || !review))) return;
        // La identidad/idempotencia y el control transaccional siguen en el backend.
        // Cada decision confirmada conserva exactamente el contrato de PR #159.
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
                    "No se pudo confirmar el registro. Actualiza la bandeja y comprueba el estado antes de repetir.");
                return;
            }
            setDone(true);
            setReview(false);
            setOpen(false);
            refresh();
        } catch {
            setError("No se pudo confirmar el registro. Actualiza la bandeja y comprueba el estado antes de repetir.");
        } finally {
            setBusy(false);
        }
    }

    return <div className="min-w-0 space-y-2" data-quality-decision={item.bobbin.id}>
        <div className="grid grid-cols-2 gap-2">
            <Button size="sm" className="bg-[#146b4f]" disabled={!actionable || busy || done}
                aria-label={`Liberar ${subject}`}
                onClick={() => {
                    if (window.confirm(`¿Liberar definitivamente ${subject} de ${item.bobbin.machine.code} (OT ${item.production.work_order.number}, línea ${item.production.line.line_code})? Esta decisión quedará registrada y no se puede deshacer desde esta pantalla.`))
                        void submit("release");
                }}>
                Liberar
            </Button>
            <Button size="sm" variant="outline" disabled={!actionable || busy || done} aria-expanded={open}
                aria-label={`Rechazar ${subject}`}
                onClick={() => { setOpen(v => !v); setReview(false); setError(""); }}>
                Rechazar
            </Button>
        </div>
        {open && <div className={isChild ? "fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6" : ""}>
            {isChild && <button type="button" className="absolute inset-0 bg-slate-950/50" aria-label="Cerrar rechazo sin guardar" disabled={busy} onClick={() => { setOpen(false); setReview(false); }}/>}
            <section ref={dialogRef} role={isChild ? "dialog" : undefined} aria-modal={isChild ? true : undefined}
                className={isChild ? "relative z-10 max-h-[90vh] w-full max-w-xl space-y-3 overflow-y-auto rounded-xl border border-rose-200 bg-white p-4 text-sm shadow-xl sm:p-6" : "min-w-0 space-y-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm"} aria-label={`Rechazo de ${subject}`}>
            <h4 className="font-bold">Rechazar {subject} — {item.bobbin.machine.code}</h4>
            {child && <p className="rounded-md border border-rose-200 bg-white p-2 text-xs text-slate-900">
                Madre declarada: <strong>{child.mother_label}</strong> · Cría <strong>{child.child_position}</strong> ·
                Peso <strong>{item.bobbin.weight_kg} kg</strong> · OT <strong>{item.production.work_order.number}</strong> ·
                Línea/PV <strong>{item.production.line.line_code} / {item.production.line.pv_reference}</strong>
            </p>}
            {!review ? <>
                <p className="text-xs text-rose-900">Completa los cuatro campos. La clasificación debe corresponder al detalle registrado.</p>
                <label className="block font-medium">Tipo
                    <select className="mt-1 w-full rounded border border-slate-300 bg-white p-2" value={rejectionType} onChange={e => setRejectionType(e.target.value)} disabled={busy}>
                        <option value="">Seleccionar</option>
                        {REJECTION_TYPES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
                    </select>
                </label>
                <label className="block font-medium">Clasificación
                    <select className="mt-1 w-full rounded border border-slate-300 bg-white p-2" value={classification} onChange={e => setClassification(e.target.value)} disabled={busy}>
                        <option value="">Seleccionar</option>
                        {REJECTION_CLASSES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
                    </select>
                </label>
                <label className="block font-medium">Detalle
                    <textarea className="mt-1 w-full rounded border border-slate-300 bg-white p-2" rows={3} maxLength={4000} value={detail} onChange={e => setDetail(e.target.value)} disabled={busy}/>
                </label>
                <label className="block font-medium">Acción correctiva
                    <textarea className="mt-1 w-full rounded border border-slate-300 bg-white p-2" rows={3} maxLength={4000} value={correctiveAction} onChange={e => setCorrectiveAction(e.target.value)} disabled={busy}/>
                </label>
                <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={busy || done || !canReject} onClick={() => { setError(""); setReview(true); }}>Revisar rechazo</Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setOpen(false); setReview(false); }}>Cancelar</Button>
                </div>
            </> : <>
                <div className="rounded-lg border border-rose-300 bg-white p-3" role="region" aria-label="Revisión previa al rechazo">
                    <p className="font-bold text-rose-950">Revisa antes de confirmar</p>
                    <p className="mt-1 text-xs text-rose-900">La decisión será definitiva en esta pantalla. Verifica que la clasificación coincida con el detalle.</p>
                    <dl className="mt-3 space-y-2">
                        <div><dt className="text-xs font-semibold text-slate-600">{child ? "Cría / madre / máquina / OT" : "Bobina / máquina / OT"}</dt>
                            <dd className="break-words">{subject} / {item.bobbin.machine.code} / {item.production.work_order.number}</dd></div>
                        <div><dt className="text-xs font-semibold text-slate-600">Tipo</dt><dd>{typeLabel}</dd></div>
                        <div><dt className="text-xs font-semibold text-slate-600">Clasificación</dt><dd className="font-semibold">{classLabel}</dd></div>
                        <div><dt className="text-xs font-semibold text-slate-600">Detalle</dt><dd className="whitespace-pre-wrap break-words">{detail.trim()}</dd></div>
                        <div><dt className="text-xs font-semibold text-slate-600">Acción correctiva</dt><dd className="whitespace-pre-wrap break-words">{correctiveAction.trim()}</dd></div>
                    </dl>
                </div>
                <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="destructive" className="h-auto min-h-8 whitespace-normal" disabled={busy || done || !canReject} onClick={() => void submit("reject")}>
                        {busy ? "Guardando…" : "Confirmar rechazo definitivo"}
                    </Button>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => { setReview(false); setError(""); }}>Volver a editar</Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setOpen(false); setReview(false); }}>Cancelar</Button>
                </div>
            </>}
            {isChild && error && <p role="alert" className="rounded-md bg-red-50 p-2 text-xs font-medium text-red-800">{error} <button type="button" className="underline" onClick={refresh}>Actualizar</button></p>}
        </section></div>}
        {!isChild && error && <p role="alert" className="text-xs font-medium text-red-800">{error} <button type="button" className="underline" onClick={refresh}>Actualizar</button></p>}
        {done && <p role="status" className="text-xs font-medium text-green-800">Decisión guardada</p>}
    </div>;
}
