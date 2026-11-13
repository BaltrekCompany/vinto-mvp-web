"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { CaptureNotice, CaptureShell, ContextStrip, SubmitBar, contextItems } from "@/components/vinto/capture-kit";
import { SUBMIT_MESSAGES, submitAttemptOf, submitMessage, type SubmitDepsOf } from "@/lib/vinto/capture-core";
import { errorsFor, setCell, type RowError } from "@/lib/vinto/capture-groups";
import { getDeviceKey } from "@/lib/vinto/device";
import { getP111, submitP111 } from "@/lib/vinto/p1-11-api";
import type { P111Capture, P111Submission } from "@/lib/vinto/p1-11";
import { calculatedConsumption, createP111V3Attempt, emptyP111V3Draft, materialOptionsFor, P111_V4_GROUPS, type P111V3Attempt, type P111V3Draft, type P111V3Payload } from "@/lib/vinto/p1-11-v3";
import type { CaptureContext } from "@/lib/vinto/orders";
import { beginSessionOperation } from "@/lib/vinto/session-epoch";

type Props = {
    context: CaptureContext;
    online: boolean;
    attempt: P111V3Attempt | null;
    setAttempt: (attempt: P111V3Attempt | null) => void;
    back: () => void;
    onSubmitted?: (capture: P111Capture) => void;
    onAssignmentChanged: () => void;
    onSessionLost: () => void;
    user?: { display_name: string } | null;
    api?: SubmitDepsOf<P111V3Payload, P111Submission, P111Capture>;
};
type ReadBack = "reading" | "ok" | "mismatch" | "error";
const REAL_API: SubmitDepsOf<P111V3Payload, P111Submission, P111Capture> = {
    post: submitP111, get: id => getP111(id),
};
const ROW_FIELDS = [
    { key: "numero_bobina", label: "N.º bobina" },
    { key: "saldo_inicial_kg", label: "Saldo inicial" },
    { key: "ingreso_kg", label: "Ingreso" },
    { key: "saldo_final_kg", label: "Saldo final" },
] as const;
const positions = P111_V4_GROUPS[0].fields[0].options ?? [];

export function P111RecipeCaptureForm({ context, online, attempt, setAttempt, back, onSubmitted,
    onAssignmentChanged, onSessionLost, user, api = REAL_API }: Props) {
    const [draft, setDraft] = useState<P111V3Draft>(() => attempt ? structuredClone(attempt.draft) as P111V3Draft : emptyP111V3Draft());
    const [errors, setErrors] = useState<RowError[]>([]);
    const [sending, setSending] = useState(false);
    const [notice, setNotice] = useState<string | null>(attempt ? SUBMIT_MESSAGES.uncertain : null);
    const [saved, setSaved] = useState<{ capture: P111Capture; message: string; readBack: ReadBack } | null>(null);
    const busy = useRef(false);
    const locked = sending || attempt !== null || saved !== null;
    const rows = draft.groups.bobinas ?? [];
    const materials = materialOptionsFor(context.productCode);
    const updateCell = (rowKey: string, key: string, value: string) =>
        setDraft(old => ({ ...old, groups: { ...old.groups,
            bobinas: setCell(old.groups.bobinas ?? [], rowKey, key, value) } }));
    const displayContext = contextItems(context).map(item =>
        item.label === "Producto" ? { ...item, value: context.productCode + " · " + context.productName } : item);

    async function send() {
        const live = beginSessionOperation();
        if (busy.current || saved) return;
        if (!online) { setNotice(SUBMIT_MESSAGES.offline); return; }
        let current = attempt;
        if (!current) {
            const created = createP111V3Attempt(draft, context.assignmentId, getDeviceKey(), context.productCode);
            if (!created.ok) {
                setErrors(created.errors);
                setNotice([SUBMIT_MESSAGES.invalid, ...created.errors.filter(e => !e.group).map(e => e.message)].join(" "));
                return;
            }
            setErrors([]);
            current = created.attempt;
            setAttempt(current);
        }
        busy.current = true; setSending(true); setNotice(null);
        try {
            const outcome = await submitAttemptOf(current, api);
            if (!live()) return;
            if (outcome.kind === "submitted") {
                setAttempt(null);
                const message = submitMessage(outcome);
                toast.success(message);
                setSaved({ capture: outcome.capture, message, readBack: "reading" });
                onSubmitted?.(outcome.capture);
                const checked = await api.get(outcome.capture.id);
                if (!live()) return;
                setSaved(old => old && { ...old, readBack: !checked.ok ? "error"
                    : JSON.stringify(checked.data.values) === JSON.stringify(outcome.capture.values) ? "ok" : "mismatch" });
                return;
            }
            if (outcome.kind === "session") { setAttempt(null); onSessionLost(); return; }
            if (outcome.kind === "rejected") {
                setAttempt(null);
                if (outcome.reason === "stale" || outcome.reason === "not_active" || outcome.reason === "line_not_producing") {
                    toast.error(outcome.message); onAssignmentChanged(); return;
                }
                setNotice(outcome.message); return;
            }
            setNotice(outcome.message); // intento y payload quedan congelados
        } finally {
            busy.current = false; setSending(false);
        }
    }

    return <CaptureShell kicker="1. Consumo de bobinas" title="Consumo de bobinas" onBack={back} wide>
        <ContextStrip items={displayContext}/>
        {user && <p className="border-b bg-slate-50 px-5 py-2 text-xs text-slate-600">
            Operador autenticado: {user.display_name}. El usuario se registra mediante la sesión del servidor.
        </p>}
        <section className="border-b px-5 py-6" data-p111-v3="consumo-bobinas">
            <h2 className="text-lg font-black">Bobinas e insumos consumidos</h2>
            <p className="mt-1 text-sm text-slate-700">El consumo físico se calcula: saldo inicial + ingreso − saldo final. La merma se registra por separado.</p>
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-950">
                La posición 1 es obligatoria. Las posiciones 2 y 3 son opcionales. Los tres saldos son opcionales en todas las posiciones; si están vacíos, cuentan como 0 solo para el consumo calculado.
            </p>
            {materials.length === 0 && <p role="alert" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                El producto {context.productCode} no tiene materiales asociados en el catálogo. Se bloquea el registro; no se muestran materiales de otros productos.
            </p>}
            {errorsFor(errors, "bobinas", null).map(error => <p role="alert" key={error} className="mt-2 text-sm text-red-700">{error}</p>)}
            <div className="mt-4 space-y-4">
                {rows.map((row, i) => <div key={row.rowKey} className="overflow-x-auto rounded-xl border border-slate-300 bg-white p-4" data-p111-row={i + 1}>
                    <div className="mb-3 flex items-center gap-2 text-sm">
                        <span className="rounded bg-emerald-100 px-3 py-1 font-black text-emerald-950">Posición {i + 1}</span>
                        <span className="rounded bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{i === 0 ? "Obligatoria" : "Opcional"}</span>
                    </div>
                    <div className="grid min-w-[1210px] grid-cols-[150px_minmax(240px,2fr)_140px_130px_130px_130px_140px] items-end gap-3">
                        <label className="block text-xs font-semibold text-slate-900">Posición {i === 0 ? "*" : ""}
                            <select data-field="posicion" value={row.cells.posicion ?? ""} disabled={locked}
                                onChange={e => updateCell(row.rowKey, "posicion", e.target.value)}
                                className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                                <option value="">Seleccionar…</option>{positions.map(option =>
                                    <option key={option.value} value={option.value}>{option.label}</option>)}
                            </select>
                        </label>
                        <label className="block text-xs font-semibold text-slate-900">Tipo según receta {i === 0 ? "*" : ""}
                            <span className="ml-1 font-normal text-slate-500">(producto {context.productCode})</span>
                            <select data-field="tipo_material" value={row.cells.tipo_material ?? ""} disabled={locked || materials.length === 0}
                                onChange={e => updateCell(row.rowKey, "tipo_material", e.target.value)}
                                className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                                <option value="">Seleccionar…</option>{materials.map(item =>
                                    <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}
                            </select>
                        </label>
                        {ROW_FIELDS.map(field => <label key={field.key} className="block text-xs font-semibold text-slate-900">
                            {field.label} {i === 0 && field.key === "numero_bobina" ? "*" : ""}
                            <span className="relative mt-2 block">
                                <input data-field={field.key} type="text" inputMode={field.key === "numero_bobina" ? "text" : "decimal"}
                                    value={row.cells[field.key] ?? ""} disabled={locked}
                                    onChange={e => updateCell(row.rowKey, field.key, e.target.value)}
                                    className="h-10 w-full rounded-md border border-slate-300 bg-white px-2 pr-7 text-sm text-slate-950"/>
                                {field.key !== "numero_bobina" && <span className="pointer-events-none absolute right-2 top-3 text-xs text-slate-500">kg</span>}
                            </span>
                        </label>)}
                        <div className="text-xs font-semibold text-slate-900">Consumo calculado
                            <output data-consumo={i + 1} className="mt-2 flex h-10 items-center rounded-md border border-blue-200 bg-blue-50 px-3 text-base font-black text-slate-950">
                                {calculatedConsumption(row.cells)}
                            </output>
                        </div>
                    </div>
                    {errorsFor(errors, "bobinas", i + 1).length > 0 && <div role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-800">
                        {errorsFor(errors, "bobinas", i + 1).map(message => <p key={message}>{message}</p>)}
                    </div>}
                </div>)}
            </div>
            <label className="mt-5 block max-w-2xl text-sm font-semibold text-slate-900">Observaciones (opcional)
                <textarea value={draft.observaciones} disabled={locked} onChange={e => setDraft(old => ({ ...old, observaciones: e.target.value }))}
                    className="mt-2 min-h-16 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm font-normal text-slate-950"/>
            </label>
        </section>
        <CaptureNotice text={notice}/>
        {saved && <div role="status" className="border-b border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
            <p className="font-black">{saved.message}</p>
            <p>Captura {saved.capture.id} · {saved.capture.values._groups.bobinas.length} material(es) registrado(s).</p>
            <p data-readback={saved.readBack}>{saved.readBack === "reading" ? "Verificando captura..." :
                saved.readBack === "ok" ? "Registro verificado mediante lectura posterior." :
                saved.readBack === "mismatch" ? "La lectura posterior no coincide. Revisar." : "Lectura posterior no disponible."}</p>
        </div>}
        {!saved && <SubmitBar onSend={send} sending={sending} retry={attempt !== null}/>}
    </CaptureShell>;
}
