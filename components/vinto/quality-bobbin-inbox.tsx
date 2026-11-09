"use client";

import { Button } from "@/components/ui/button";
import { QualityBobbinDecision } from "@/components/vinto/quality-bobbin-decision";
import { CentralStatus } from "@/components/vinto/central-status";
import { grammageLabel, qualityStatusLabel, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import { QUALITY_BOBBIN_CANDIDATES } from "@/lib/vinto/quality-bobbin-candidates";
import type { QualityBobbinScreen } from "@/lib/vinto/quality-offers";
import type { Resource } from "@/lib/vinto/use-central";

// Inbox central: mantiene GET /api/quality/bobbins como unica fuente. Las decisiones
// siguen aisladas en QualityBobbinDecision (una bobina y un POST por decision).
// Layout compacto y adaptable: sin tabla de 16 columnas ni desplazamiento horizontal.
// Los controles de captura e historial siguen disponibles en el desplegable nativo.
type Props = {
    resource: Resource<QualityBobbinInboxItem[]>;
    refresh: () => void;
    onRegisterHumidity: (item: QualityBobbinInboxItem) => void;
    onRegisterProperties: (item: QualityBobbinInboxItem) => void;
    onViewHistory: (item: QualityBobbinInboxItem) => void;
    candidateOffers?: (machineCode: string) => QualityBobbinScreen[];
    onRegisterCandidate?: (screen: QualityBobbinScreen, item: QualityBobbinInboxItem) => void;
    actionOffers?: (machineCode: string) => { humidity: boolean; physical: boolean };
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
    return <div className="min-w-0">
        <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">{label}</dt>
        <dd className="mt-0.5 break-words text-sm text-slate-950">{children}</dd>
    </div>;
}

export function QualityBobbinInbox({ resource, refresh, onRegisterHumidity, onRegisterProperties, onViewHistory, candidateOffers, onRegisterCandidate, actionOffers }: Props) {
    if (resource.status !== "ready") return <CentralStatus state={resource} onRetry={refresh} title="No se pudo cargar el inbox de Calidad"/>;
    const items = resource.data;
    return <section className="min-w-0 max-w-full rounded-2xl border bg-white p-4 shadow-sm md:p-6" aria-live="polite">
        <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 className="text-xl font-black">Bobinas pendientes de Calidad</h2>
                <p className="mt-1 text-sm text-slate-700">Bobinas producidas pendientes de evaluación. El listado no depende de la asignación actualmente activa.</p>
            </div>
            <div className="flex items-center gap-3">
                <span className="text-sm font-bold">Pendientes: {items.length}</span>
                <Button variant="outline" size="sm" disabled={resource.refreshing} onClick={refresh}>{resource.refreshing ? "Actualizando…" : "Actualizar"}</Button>
            </div>
        </div>
        {items.length === 0 ? <p className="mt-4 text-sm text-slate-600">No hay bobinas pendientes de Calidad.</p>
        : <div className="mt-4 space-y-3">
            {items.map(i => <article key={i.bobbin.id} aria-label={"Bobina " + i.bobbin.code + " de " + i.bobbin.machine.code} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/60 p-3 md:p-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <h3 className="text-lg font-black">Bobina {i.bobbin.code}</h3>
                        <span className="text-sm font-bold text-slate-700">Máquina {i.bobbin.machine.code}</span>
                        <span className="text-xs text-slate-600">Gestión {i.bobbin.management_start_year}</span>
                    </div>
                    <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-950">Estado: {qualityStatusLabel(i.quality.status)}</span>
                </div>
                <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,310px)]">
                    <div className="min-w-0">
                        <dl className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-3">
                            <Field label="OT">{i.production.work_order.number}</Field>
                            <Field label="Línea / PV">{i.production.line.line_code} / {i.production.line.pv_reference}</Field>
                            <Field label="Fecha operativa">{i.production.operating_date}</Field>
                            <Field label="Artículo"><span className="font-semibold">{i.production.line.article.code}</span><span className="block text-slate-700">{i.production.line.article.description}</span></Field>
                            <Field label="Peso (kg)">{i.bobbin.weight_kg}</Field>
                            <Field label="Gramaje">{grammageLabel(i.bobbin.grammage_g_m2)}</Field>
                        </dl>
                        <details className="mt-3 rounded-lg border border-slate-200 bg-white">
                            <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-[#146b4f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">Ver más datos de producción</summary>
                            <dl className="grid grid-cols-2 gap-3 border-t p-3 sm:grid-cols-3">
                                <Field label="Turno">{i.production.shift.name}</Field>
                                <Field label="Hora inicio">{i.bobbin.start_time}</Field>
                                <Field label="Hora fin">{i.bobbin.end_time}</Field>
                                <Field label="Diámetro (mm)">{i.bobbin.diameter_mm}</Field>
                                <Field label="Cortes">{i.bobbin.number_of_cuts}</Field>
                                <Field label="Observaciones">{i.bobbin.notes ?? "—"}</Field>
                            </dl>
                        </details>
                    </div>
                    <div className="min-w-0 space-y-3 lg:border-l lg:border-slate-200 lg:pl-4">
                        <QualityBobbinDecision item={i} refresh={refresh}/>
                        <details className="rounded-lg border border-slate-200 bg-white">
                            <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-[#146b4f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">Controles e historial</summary>
                            <div className="flex flex-col gap-2 border-t p-3">
                                {(actionOffers?.(i.bobbin.machine.code).humidity ?? true) && <Button size="sm" variant="outline" className="h-auto min-h-8 whitespace-normal text-left" aria-label={`Registrar humedad de la bobina ${i.bobbin.code} (${i.bobbin.machine.code} · ${i.production.work_order.number})`} onClick={() => onRegisterHumidity(i)}>Registrar humedad</Button>}
                                {(actionOffers?.(i.bobbin.machine.code).physical ?? true) && <Button size="sm" variant="outline" className="h-auto min-h-8 whitespace-normal text-left" aria-label={`Registrar propiedades físicas de la bobina ${i.bobbin.code} (${i.bobbin.machine.code} · ${i.production.work_order.number})`} onClick={() => onRegisterProperties(i)}>Registrar propiedades</Button>}
                                {(candidateOffers?.(i.bobbin.machine.code) ?? []).map(screen => <Button key={screen} size="sm" variant="outline" className="h-auto min-h-8 whitespace-normal border-amber-300 text-amber-950" data-form={QUALITY_BOBBIN_CANDIDATES[screen].code}
                                    aria-label={`${QUALITY_BOBBIN_CANDIDATES[screen].actionLabel ?? `Registrar ${QUALITY_BOBBIN_CANDIDATES[screen].title} (candidato)`} de la bobina ${i.bobbin.code} (${i.bobbin.machine.code} · ${i.production.work_order.number})`} onClick={() => onRegisterCandidate?.(screen, i)}>{QUALITY_BOBBIN_CANDIDATES[screen].actionLabel ?? `${QUALITY_BOBBIN_CANDIDATES[screen].title} (candidato)`}</Button>)}
                                <Button size="sm" variant="outline" aria-label={`Ver controles de la bobina ${i.bobbin.code} (${i.bobbin.machine.code} · ${i.production.work_order.number})`} onClick={() => onViewHistory(i)}>Ver controles</Button>
                            </div>
                        </details>
                    </div>
                </div>
            </article>)}
        </div>}
    </section>;
}
