"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CaptureCountError, getCaptureCount, type CaptureCountFailure, type CaptureFront } from "@/lib/vinto/api";
import { captureCountView } from "@/lib/vinto/capture-count-view";

// Cada resultado queda ligado a (usuario, frente, intento): si cambia el usuario, el frente o se reintenta, el resultado anterior deja de
// aplicar y se muestra "cargando". Así nunca se muestra el conteo de otra sesión u otro frente.
type CountState = { owner: string; front: CaptureFront; attempt: number } & ({ status: "failed"; kind: CaptureCountFailure } | { status: "ready"; count: number });

export function CaptureCount({ front, localCount, userKey, onSessionLost }: { front: CaptureFront; localCount: number; userKey: string; onSessionLost: () => void }) {
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<CountState | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        const timer = window.setTimeout(() => controller.abort(), 5000);
        getCaptureCount(front, controller.signal)
            .then(result => { if (active) setState({ owner: userKey, front, attempt, status: "ready", count: result.count }); })
            .catch(error => {
                if (!active) return; // petición obsoleta (cambio de frente, usuario o desmontaje): se descarta
                const kind: CaptureCountFailure = error instanceof CaptureCountError ? error.kind : "unavailable";
                if (kind === "session") onSessionLost(); // 401: vuelve al Login por el mecanismo de autenticación existente
                else setState({ owner: userKey, front, attempt, status: "failed", kind });
            })
            .finally(() => window.clearTimeout(timer));
        return () => { active = false; window.clearTimeout(timer); controller.abort(); };
        // onSessionLost cambia en cada render del padre; el efecto solo depende de la identidad de la consulta.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [front, attempt, userKey]);
    const current = state && state.owner === userKey && state.front === front && state.attempt === attempt ? state : { owner: userKey, front, attempt, status: "loading" as const };
    const view = captureCountView(current, front, localCount);
    return <div className="rounded-2xl border bg-white p-5" aria-live="polite">
        <p className="text-sm text-slate-700">{view.label}</p>
        <p className="mt-2 text-3xl font-black">{view.value}</p>
        <p className="mt-2 text-xs text-slate-600">{view.note}</p>
        {view.canRetry && <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAttempt(n => n + 1)}>
            {current.status === "ready" ? "Actualizar" : "Reintentar"}
        </Button>}
    </div>;
}
