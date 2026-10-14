import type { ReactNode } from "react";
import { Panel } from "@/components/vinto/panels";

// Estados «todavía no disponible» de Seguimiento: sustituyen a los datos de ejemplo. No muestran cifras (ni cero) porque la fuente central no existe.
export function PendingMetric({ label, note }: { label: string; note: string }) {
    return <div className="rounded-2xl border border-dashed bg-white p-5" aria-live="polite">
        <p className="text-sm text-slate-700">{label}</p>
        <p className="mt-2 text-xl font-black text-slate-700">Funcionalidad pendiente</p>
        <p className="mt-2 text-xs text-slate-600">{note}</p>
    </div>;
}

export function PendingNotice({ children }: { children: ReactNode }) {
    return <p className="rounded-lg border border-dashed bg-slate-50 p-3 text-sm text-slate-700">{children}</p>;
}

export function QualityTrackingPending() {
    return <Panel title="Seguimiento de Calidad" note="Resumen central todavía no disponible.">
        <PendingNotice>El resumen de Seguimiento de Calidad todavía no está disponible: no existe una fuente central de estados de liberación. El estado de cada bobina se consulta en la bandeja y el historial de Ejecución. Registrar humedad o propiedades físicas no libera ni rechaza una bobina.</PendingNotice>
    </Panel>;
}
