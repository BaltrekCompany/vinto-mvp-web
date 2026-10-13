"use client";

import type { ReactNode } from "react";
import { ArrowLeft, Plus, Send, Trash2 } from "lucide-react";
import { Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Option } from "@/lib/vinto/capture-core";
import type { CaptureContext } from "@/lib/vinto/orders";

// Piezas VISUALES reutilizables de las capturas simples de producción (M2-B1). Son deliberadamente pequeñas y sin lógica de negocio: reciben texto,
// valores y manejadores por props. Las validaciones, el borrador y el envío de cada formulario viven en su propio módulo (F6: lib/vinto/captures.ts).
// Compatibles con móvil: todo en una columna y a dos columnas desde md; sin anchos fijos.

export type ContextItem = { label: string; value: string };

// Contexto de la asignación (solo informativo: el backend vuelve a derivar máquina, turno, fecha, OT, PV y producto).
export const contextItems = (context: CaptureContext): ContextItem[] => [
    { label: "OT", value: context.otId },
    { label: "Línea / PV", value: `${context.lineId} / ${context.pv}` },
    { label: "Producto", value: context.productName },
    { label: "Máquina", value: context.machine },
    { label: "Turno / fecha", value: `${context.shift} · ${context.date}` },
];

// Encabezado + tarjeta de la captura (barra de volver, título y contenido).
export function CaptureShell({ kicker, title, onBack, children }: { kicker: string; title: string; onBack: () => void; children: ReactNode }) {
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/>
        <header className="border-b bg-white p-4"><Button variant="ghost" onClick={onBack}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header>
        <section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
            <div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">{kicker}</p><h1 className="mt-2 text-2xl font-black">{title}</h1></div>
            {children}
        </div></section></main>;
}

export function ContextStrip({ items }: { items: readonly ContextItem[] }) {
    return <div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-5">{items.map(item => <ContextValue key={item.label} label={item.label} value={item.value}/>)}</div>;
}

export function ContextValue({ label, value }: { label: string; value: string }) {
    return <div><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 font-bold">{value}</p></div>;
}

export function CaptureSection({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
    return <div className="border-b p-6"><h2 className="font-black">{title}</h2>{hint && <p className="mb-4 text-sm text-slate-700">{hint}</p>}
        <div className="grid gap-5 md:grid-cols-2">{children}</div></div>;
}

type FieldBase = { label: string; value: string; onChange: (value: string) => void; disabled?: boolean; required?: boolean; hint?: string };
const labelOf = (label: string, required?: boolean) => required ? `${label} *` : label;

// Texto de una línea. `inputMode="decimal"` + `suffix` (p. ej. "kg") sirven para números: el valor sigue siendo TEXTO; interpretarlo es del formulario.
export function TextField({ label, value, onChange, disabled, required, hint, inputMode, suffix, type = "text" }: FieldBase & { inputMode?: "text" | "numeric" | "decimal"; suffix?: string; type?: "text" | "date" | "time" }) {
    const input = <Input disabled={disabled} className="mt-2 text-slate-950" type={type} inputMode={inputMode} value={value} onChange={e => onChange(e.target.value)}/>;
    return <div><Label>{labelOf(label, required)}</Label>
        {suffix ? <div className="relative">{input}<span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">{suffix}</span></div> : input}
        {hint && <p className="mt-1 text-xs text-slate-600">{hint}</p>}</div>;
}

export function TextAreaField({ label, value, onChange, disabled, required, hint, wide = true }: FieldBase & { wide?: boolean }) {
    return <div className={wide ? "md:col-span-2" : undefined}><Label>{labelOf(label, required)}</Label>
        <Textarea disabled={disabled} className="mt-2 text-slate-950" value={value} onChange={e => onChange(e.target.value)}/>{hint && <p className="mt-1 text-xs text-slate-600">{hint}</p>}</div>;
}

export function ChoiceField({ label, value, onChange, options, disabled, required = true }: Omit<FieldBase, "hint"> & { options: readonly Option[] }) {
    return <div><Label>{labelOf(label, required)}</Label><select disabled={disabled} className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-slate-950 disabled:opacity-70" value={value} onChange={e => onChange(e.target.value)}><option value="">Seleccionar…</option>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>;
}

export function CaptureNotice({ text }: { text: string | null }) {
    return text ? <div role="alert" className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{text}</div> : null;
}

export function SubmitBar({ onSend, sending, retry, label = "Enviar registro trazable" }: { onSend: () => void; sending: boolean; retry: boolean; label?: string }) {
    return <div className="flex flex-wrap justify-end gap-2 border-t p-5">
        <Button className="bg-[#146b4f]" disabled={sending} onClick={onSend}><Send className="mr-2 h-4 w-4"/>{sending ? "Enviando…" : retry ? "Reintentar envío" : label}</Button>
    </div>;
}

// ---- grupos repetibles (M3-A) --------------------------------------------------------------------------------------------------------------------
// Piezas VISUALES de un grupo con filas repetibles. Sin lógica: el estado de las filas, los límites (canAdd/canRemove) y la validación viven en lib/vinto/capture-groups.ts;
// aquí solo se dibuja el encabezado, cada fila numerada (el orden visible es el orden que se envía), sus errores y los botones Agregar/Eliminar.

export type GroupRowView = { key: string; errors: readonly string[] };

export function RepeatableGroup({ title, hint, rows, minRows, maxRows, canAdd, canRemove, disabled, groupErrors = [], onAdd, onRemove, renderRow }: {
    title: string; hint?: string; rows: readonly GroupRowView[]; minRows: number; maxRows: number | null; canAdd: boolean; canRemove: boolean; disabled?: boolean;
    groupErrors?: readonly string[]; onAdd: () => void; onRemove: (index: number) => void; renderRow: (index: number) => ReactNode;
}) {
    const limits = maxRows === null ? (minRows > 0 ? `mínimo ${minRows}` : "sin mínimo") : `${minRows > 0 ? `mínimo ${minRows}, ` : ""}máximo ${maxRows}`;
    return <section className="border-b p-6" aria-label={title} data-group={title}>
        <div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-black">{title}</h2>{hint && <p className="text-sm text-slate-700">{hint}</p>}
            <p className="mt-1 text-xs text-slate-600" data-testid="group-count">{rows.length} {rows.length === 1 ? "fila" : "filas"} · {limits}</p></div>
            <Button type="button" variant="outline" size="sm" disabled={disabled || !canAdd} onClick={onAdd}><Plus className="mr-1 h-4 w-4"/>Agregar fila</Button></div>
        {groupErrors.length > 0 && <div role="alert" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{groupErrors.map(message => <p key={message}>{message}</p>)}</div>}
        {rows.length === 0 ? <p className="mt-4 rounded-lg border border-dashed p-3 text-sm text-slate-700">Sin filas.</p>
            : <ol className="mt-4 space-y-4">{rows.map((row, index) => <li key={row.key} className="rounded-xl border bg-slate-50 p-4" data-row={index + 1}>
                <div className="mb-3 flex items-center justify-between gap-2"><p className="text-sm font-black text-[#146b4f]">Fila {index + 1}</p>
                    <Button type="button" variant="ghost" size="sm" aria-label={`Eliminar fila ${index + 1} de ${title}`} disabled={disabled || !canRemove} onClick={() => onRemove(index)}><Trash2 className="mr-1 h-4 w-4"/>Eliminar</Button></div>
                <div className="grid gap-4 md:grid-cols-2">{renderRow(index)}</div>
                {row.errors.length > 0 && <div role="alert" className="mt-3 rounded-lg border border-amber-300 bg-white p-3 text-sm text-amber-950">{row.errors.map(message => <p key={message}>{message}</p>)}</div>}
            </li>)}</ol>}
    </section>;
}
