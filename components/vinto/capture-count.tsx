"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { getCaptureCount, type CaptureFront } from "@/lib/vinto/api";

type CountState = { front: CaptureFront; attempt: number; status: "unavailable" } |
    { front: CaptureFront; attempt: number; status: "ready"; count: number };

export function CaptureCount({ front, localCount }: { front: CaptureFront; localCount: number }) {
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<CountState | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        const timer = window.setTimeout(() => controller.abort(), 5000);
        getCaptureCount(front, controller.signal)
            .then(result => { if (active) setState({ front, attempt, status: "ready", count: result.count }); })
            .catch(() => { if (active) setState({ front, attempt, status: "unavailable" }); })
            .finally(() => window.clearTimeout(timer));
        return () => { active = false; window.clearTimeout(timer); controller.abort(); };
    }, [front, attempt]);
    const current = state && state.front === front && state.attempt === attempt ? state : { front, attempt, status: "loading" as const };
    return <div className="rounded-2xl border bg-white p-5" aria-live="polite">
        <p className="text-sm text-slate-700">{current.status === "ready" ? "Registros centrales" : "Registros locales"}</p>
        <p className="mt-2 text-3xl font-black">{current.status === "ready" ? current.count : localCount}</p>
        <p className="mt-2 text-xs text-slate-600">
            {current.status === "ready" ? `En este navegador: ${localCount}. Sin sincronización automática.` :
                current.status === "loading" ? "Consultando registros centrales…" : "Consulta central no disponible"}
        </p>
        {current.status !== "loading" && <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAttempt(n => n + 1)}>
            {current.status === "ready" ? "Actualizar" : "Reintentar"}
        </Button>}
    </div>;
}
