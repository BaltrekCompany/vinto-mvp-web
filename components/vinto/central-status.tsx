"use client";

import { Button } from "@/components/ui/button";
import { LOAD_ERROR_TITLE, failureMessage } from "@/lib/vinto/orders";
import type { Resource } from "@/lib/vinto/use-central";

// Panel seguro mientras se cargan datos centrales o cuando falla la carga. Nunca se muestran datos demo ni locales.
export function CentralStatus({ state, onRetry, title = LOAD_ERROR_TITLE }: { state: Resource<unknown>; onRetry: () => void; title?: string }) {
    if (state.status === "idle" || state.status === "loading") {
        return <div role="status" aria-live="polite" className="rounded-2xl border bg-white p-6 text-sm font-semibold text-slate-700">Cargando datos centrales…</div>;
    }
    if (state.status === "error") {
        const message = state.kind === "forbidden" ? "Acceso no permitido." : failureMessage(state.kind);
        return <div role="alert" className="rounded-2xl border border-amber-300 bg-amber-50 p-6"><p className="font-black text-amber-950">{title}</p><p className="mt-1 text-sm text-amber-950">{message}</p><Button className="mt-4 bg-[#146b4f]" disabled={state.refreshing} onClick={onRetry}>{state.refreshing ? "Reintentando…" : "Reintentar"}</Button></div>;
    }
    return null;
}
