"use client";

import type { ReactNode } from "react";
import { ArrowLeft, Send } from "lucide-react";
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
export function TextField({ label, value, onChange, disabled, required, hint, inputMode, suffix }: FieldBase & { inputMode?: "text" | "numeric" | "decimal"; suffix?: string }) {
    const input = <Input disabled={disabled} className="mt-2 text-slate-950" type="text" inputMode={inputMode} value={value} onChange={e => onChange(e.target.value)}/>;
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
