"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureShell, ContextStrip, SubmitBar, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitMessage } from "@/lib/vinto/capture-core";
import { getDeviceKey } from "@/lib/vinto/device";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";
import { candidateApi } from "@/lib/vinto/candidate-form-api";
import type { CandidateAttempt, CandidateCapture, CandidateDraft } from "@/lib/vinto/candidate-form";
import type { CaptureContext } from "@/lib/vinto/orders";
import { getPalletPreview, previewTotalKg, type PalletPreview } from "@/lib/vinto/pallet-preview";
import { P113_V3, calculatedConsumption, checkP113Recipe, materialOptionsFor } from "@/lib/vinto/p1-13-v3";

const api = candidateApi(P113_V3);
type Props = {
    context: CaptureContext; online: boolean;
    attempt: CandidateAttempt | null; setAttempt: (value: CandidateAttempt | null) => void;
    back: () => void; onSubmitted?: (capture: CandidateCapture) => void;
    onAssignmentChanged: () => void; onSessionLost: () => void;
    user?: { display_name: string } | null;
};
type StoredPreview = { assignmentId: string; preview: PalletPreview | null };
type ReadBack = "reading" | "ok" | "mismatch" | "error";
const COIL_FIELDS = [
    { key: "numero_bobina", label: "N.º bobina", inputMode: "text" },
    { key: "saldo_inicial_kg", label: "Saldo inicial", inputMode: "decimal" },
    { key: "ingreso_kg", label: "Ingreso", inputMode: "decimal" },
    { key: "saldo_final_kg", label: "Saldo final", inputMode: "decimal" },
] as const;

export function P113V3CaptureForm({ context, online, attempt, setAttempt, back, onSubmitted,
    onAssignmentChanged, onSessionLost, user }: Props) {
    const [draft, setDraft] = useState<CandidateDraft>(() => attempt ? { ...attempt.draft } : P113_V3.emptyDraft());
    const [palletSource, setPalletSource] = useState<StoredPreview | null>(null);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: CandidateCapture; message: string; readBack: ReadBack } | null>(null);
    const [sending, setSending] = useState(false);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const materials = materialOptionsFor(context.productCode);
    const preview = palletSource?.assignmentId === context.assignmentId &&
        palletSource.preview?.article_code === context.productCode &&
        palletSource.preview?.machine === context.machine ? palletSource.preview : null;
    const loading = palletSource?.assignmentId !== context.assignmentId;
    const nominal = preview?.nominal_weight_kg ?? null;

    useEffect(() => {
        const controller = new AbortController();
        const id = context.assignmentId;
        getPalletPreview(id, controller.signal)
            .then(result => { if (!controller.signal.aborted)
                setPalletSource({ assignmentId: id, preview: result.ok ? result.data : null }); })
            .catch(() => { if (!controller.signal.aborted) setPalletSource({ assignmentId: id, preview: null }); });
        return () => controller.abort();
    }, [context.assignmentId]);

    const set = (key: string) => (value: string) => setDraft(old => ({ ...old, [key]: value }));

    async function submit() {
        const sameSession = beginSessionOperation();
        if (busy.current || saved) return;
        if (!online) return void setNotice(SUBMIT_MESSAGES.offline);
        let current = attempt;
        if (!current) {
            if (!preview?.weight_available || !nominal)
                return void setNotice("No se puede registrar: falta peso nominal autorizado del artículo de la OT.");
            const issue = checkP113Recipe(draft, context.productCode);
            if (issue) return void setNotice(issue);
            const made = P113_V3.createAttempt(draft, context.assignmentId, getDeviceKey());
            if (!made.ok) return void setNotice(made.errors.join(" "));
            current = made.attempt;
            setAttempt(current);
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const result = await P113_V3.submitAttempt(current, { post: api.submit, get: id => api.get(id) });
            if (!sameSession()) return;
            if (result.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(result);
                toast.success(message);
                setSaved({ capture: result.capture, message, readBack: "reading" });
                onSubmitted?.(result.capture);
                const read = await api.get(result.capture.id);
                if (!sameSession()) return;
                setSaved(old => old && { ...old,
                    readBack: !read.ok ? "error" : JSON.stringify(read.data.values) === JSON.stringify(result.capture.values) &&
                        JSON.stringify(read.data.pallet) === JSON.stringify(result.capture.pallet) ? "ok" : "mismatch" });
                return;
            }
            if (result.kind === "session") { setAttempt(null); onSessionLost(); return; }
            if (result.kind === "rejected") {
                setAttempt(null);
                if (result.reason === "stale" || result.reason === "not_active" || result.reason === "line_not_producing") {
                    toast.error(result.message); onAssignmentChanged(); return;
                }
                setNotice(result.message); return;
            }
            setNotice(result.message);
        } finally { busy.current = false; setSending(false); }
    }

    const inputClass = "mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 disabled:bg-slate-100";
    const boxClass = "rounded-xl border border-slate-300 bg-blue-50 p-3";
    return <CaptureShell kicker="2. Servilletas, especiales y sobreempaque" title="Producción diaria de servilletas y especiales" onBack={back} wide>
        <ContextStrip items={contextItems(context).map(item => item.label === "Producto"
            ? { ...item, value: context.productCode + " · " + context.productName } : item)}/>
        {user && <p className="border-b bg-slate-50 px-5 py-2 text-xs text-slate-600">
            Operador autenticado: {user.display_name}. El usuario queda identificado por la sesión.
        </p>}

        <section className="border-b px-5 py-6" data-p113-v3="consumo-bobina">
            <h2 className="text-lg font-black">1. Consumo de bobina</h2>
            <p className="mt-1 text-sm text-slate-600">Una bobina o material declarado por pallet. Consumo = saldo inicial + ingreso − saldo final.</p>
            {materials.length === 0 && <p role="alert" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                El artículo {context.productCode} no tiene receta. Se bloquea el envío; no se utilizará una lista genérica.
            </p>}
            <div className="mt-4 overflow-x-auto">
                <div className="grid min-w-[1060px] grid-cols-[minmax(260px,2.8fr)_140px_125px_125px_125px_145px] items-end gap-3">
                    <label className="text-xs font-semibold">Tipo de bobina *
                        <span className="ml-1 font-normal text-slate-500">(artículo {context.productCode})</span>
                        <select className={inputClass} data-field="tipo_bobina" disabled={locked || materials.length === 0}
                            value={draft.tipo_bobina ?? ""} onChange={e => set("tipo_bobina")(e.target.value)}>
                            <option value="">Seleccionar...</option>
                            {materials.map(item => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}
                        </select>
                    </label>
                    {COIL_FIELDS.map(field => <label key={field.key} className="text-xs font-semibold">{field.label} *
                        <span className="relative block">
                            <input className={inputClass} data-field={field.key} type="text" inputMode={field.inputMode}
                                disabled={locked} value={draft[field.key] ?? ""} onChange={e => set(field.key)(e.target.value)}/>
                            {field.inputMode === "decimal" && <span className="pointer-events-none absolute right-2 top-5 text-xs text-slate-500">kg</span>}
                        </span>
                    </label>)}
                    <div className="text-xs font-semibold">Consumo calculado
                        <output data-p113-consumo className="mt-2 flex h-10 items-center rounded-md border border-blue-200 bg-blue-50 px-3 text-base font-black">
                            {calculatedConsumption(draft)}
                        </output>
                    </div>
                </div>
            </div>
            <label className="mt-4 block max-w-xl text-xs font-semibold">Observaciones (opcional)
                <textarea className="mt-2 min-h-16 w-full rounded-md border border-slate-300 p-3 text-sm font-normal"
                    disabled={locked} value={draft.observaciones ?? ""} onChange={e => set("observaciones")(e.target.value)}/>
            </label>
        </section>

        <section className="border-b px-5 py-6" data-p113-v3="produccion-pallet">
            <h2 className="text-lg font-black">2. Producción por pallet</h2>
            <p className="mt-1 text-sm text-slate-600">Un envío crea un pallet independiente; correlativo por OT y línea, generado en el servidor.</p>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className={boxClass} data-pallet-number><p className="text-xs font-semibold text-blue-900">N.º pallet</p>
                    <p className="mt-1 font-bold">Automático al enviar</p></div>
                <label className="text-xs font-semibold">Cantidad de jabas *
                    <input className={inputClass} data-field="cantidad_jabas" inputMode="numeric" disabled={locked}
                        value={draft.cantidad_jabas ?? ""} onChange={e => set("cantidad_jabas")(e.target.value)}/>
                </label>
                <div className={boxClass} data-pallet-nominal><p className="text-xs font-semibold text-blue-900">Peso nominal por jaba · maestro</p>
                    <p className="mt-1 font-bold">{nominal ? nominal + " kg" : loading ? "Consultando..." : "No disponible"}</p></div>
                <div className={boxClass} data-pallet-total><p className="text-xs font-semibold text-blue-900">Peso total calculado</p>
                    <p className="mt-1 font-bold">{previewTotalKg(nominal, (draft.cantidad_jabas ?? "").trim()) ?? "0.00"} kg</p></div>
                <label className="text-xs font-semibold">Hora inicio pallet *
                    <input className={inputClass} data-field="hora_inicio" type="time" disabled={locked}
                        value={draft.hora_inicio ?? ""} onChange={e => set("hora_inicio")(e.target.value)}/>
                </label>
                <label className="text-xs font-semibold">Hora fin pallet *
                    <input className={inputClass} data-field="hora_fin" type="time" disabled={locked}
                        value={draft.hora_fin ?? ""} onChange={e => set("hora_fin")(e.target.value)}/>
                </label>
            </div>
            {!loading && !nominal && <p role="alert" className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                No hay peso nominal válido para este producto, o no tienes acceso a la consulta. Registro bloqueado.
            </p>}
            <p className="mt-3 text-xs text-slate-500">Los pesos y el correlativo definitivos se verifican y guardan en PostgreSQL al registrar.</p>
        </section>

        <CaptureNotice text={notice}/>
        {saved && <div className="border-b bg-emerald-50 p-4 text-sm text-emerald-950" role="status">
            <p className="font-black">{saved.message}</p>
            <p data-pallet-confirmed>{saved.capture.pallet ? "Pallet N.º " + saved.capture.pallet.number + " · " +
                saved.capture.pallet.quantity_jabas + " jabas · " + saved.capture.pallet.nominal_weight_kg + " kg/jaba · total " +
                saved.capture.pallet.total_weight_kg + " kg" : "No se recibió el pallet: revisar el registro."}</p>
            <p>Captura {saved.capture.id}</p>
            <p data-readback={saved.readBack}>{saved.readBack === "ok" ? "Registro verificado mediante lectura posterior." :
                saved.readBack === "reading" ? "Consultando captura..." : "Lectura posterior no confirmada; revisar."}</p>
        </div>}
        {!saved && <SubmitBar onSend={submit} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
