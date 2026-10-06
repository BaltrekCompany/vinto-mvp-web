"use client";

import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Piezas visuales compartidas (extraídas de app/page.tsx sin cambios de diseño).
export function Panel({ title, note, children }: { title: string; note: string; children: ReactNode }) {
    return <div className="rounded-2xl border bg-white p-6 shadow-sm"><h2 className="text-xl font-black">{title}</h2><p className="mb-5 mt-1 text-sm text-slate-700">{note}</p>{children}</div>;
}

export function Select({ label, value, set, options, render, disabled }: { label: string; value: string; set: (x: string) => void; options: string[]; render?: (x: string) => string; disabled?: boolean }) {
    return <div><Label>{label}</Label><select disabled={disabled} className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-950" value={value} onChange={e => set(e.target.value)}><option value="">Seleccionar…</option>{options.map(x => <option key={x} value={x}>{render ? render(x) : x}</option>)}</select></div>;
}

export function Text({ label, value, set, type = "text", disabled }: { label: string; value: string; set: (x: string) => void; type?: string; disabled?: boolean }) {
    return <div><Label>{label}</Label><Input disabled={disabled} className="mt-2 text-slate-950" type={type} value={value} onChange={e => set(e.target.value)}/></div>;
}
