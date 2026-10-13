"use client";

import { useState } from "react";
import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CaptureSection, CaptureShell, ContextValue, TextAreaField, TextField } from "@/components/vinto/capture-kit";
import { DEMO_CONTEXT, DEMO_DISCLAIMER, DEMO_DRAFT, PENDING_RULES, previewSpec } from "@/lib/vinto/p1-10-preview";

// VISTA PREVIA de VINTO-P1-10 (Registro de fardos · Rebobinado). Solo presentación: NO importa ningún cliente de red ni de almacenamiento, no tiene
// botón de envío activo y los valores que se escriban viven únicamente en este componente (se pierden al salir). No está enlazada desde la aplicación.
// Las reglas sin confirmar se muestran como pendientes; no se inventa correlativo, formato, unicidad, tipo del peso, firma ni responsable.

export function P110Preview({ onBack }: { onBack: () => void }) {
    const spec = previewSpec();
    const [draft, setDraft] = useState<Record<string, string>>({ ...DEMO_DRAFT });
    const set = (key: string) => (value: string) => setDraft(old => ({ ...old, [key]: value }));
    return <CaptureShell kicker="Vista previa · Rebobinado" title={spec.name} onBack={onBack}>
        <div role="note" data-preview-banner className="border-b border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-black">VISTA PREVIA — NO REGISTRA CAPTURAS</p>
            <p className="mt-1">{DEMO_DISCLAIMER}. Este formulario ({spec.code}) no está habilitado para operación: Rebobinado no es un sector operativo y el formulario no está en la captura central. Nada de lo escrito aquí se envía ni se guarda.</p>
        </div>
        <div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-4" data-section="contextual">
            {spec.contextual.map(field => <div key={field.key}>
                <ContextValue label={`${field.label} · automático`} value={DEMO_CONTEXT[field.key] ?? "—"}/>
                <p className="mt-1 text-xs text-slate-700">{field.origin}</p>
                <p className="mt-1 text-xs font-semibold text-amber-900">{field.pending}</p>
            </div>)}
        </div>
        <CaptureSection title="Campos de captura manual" hint="Los cuatro campos que digitaría el operador según la definición actual. Los valores mostrados son de ejemplo.">
            {spec.manual.map(field => field.declaredType === "textarea"
                ? <TextAreaField key={field.key} label={field.label} required={field.required} value={draft[field.key] ?? ""} onChange={set(field.key)}/>
                : <TextField key={field.key} label={field.label} required={field.required} suffix={field.unit ?? undefined} inputMode={field.key === "peso_fardo" ? "decimal" : "text"}
                    hint={field.key === "numero_de_fardo" ? "Sin correlativo, formato ni unicidad confirmados." : field.key === "peso_fardo" ? "Tipo declarado: texto. Formato y decimales por confirmar." : undefined}
                    value={draft[field.key] ?? ""} onChange={set(field.key)}/>)}
        </CaptureSection>
        <div className="border-b p-6" data-section="pending"><h2 className="font-black">Reglas pendientes de confirmar</h2>
            <p className="mb-3 text-sm text-slate-700">Ninguna de estas reglas está implementada ni asumida en esta vista.</p>
            <ul className="space-y-2 text-sm">{PENDING_RULES.map(rule => <li key={rule.id} className="rounded-xl border border-amber-200 bg-amber-50 p-3"><span className="font-bold">{rule.title}: </span>{rule.detail}</li>)}</ul></div>
        <div className="flex flex-wrap items-center justify-end gap-3 border-t p-5">
            <p className="text-sm text-slate-700">Máquinas según la definición: {spec.machineLabel} (lista actual: {spec.allowedMachineIds.join(", ")}).</p>
            <Button disabled aria-disabled="true" data-testid="preview-submit" className="bg-slate-400"><Lock className="mr-2 h-4 w-4"/>Envío no habilitado (vista previa)</Button>
        </div>
    </CaptureShell>;
}
