"use client";

import { useCallback, useEffect, useState } from "react";
import { getCurrentUser } from "@/lib/vinto/auth-api";
import type { AuthView, SessionResult } from "@/lib/vinto/auth";

type Stored = { attempt: number; session: SessionResult };

// Estado de autenticación: checking | anonymous | authenticated | unavailable. La autoridad es GET /api/auth/me:
// no se guarda nada en localStorage/sessionStorage. "checking" se deriva (no hay setState síncrono en el efecto):
// mientras el resultado guardado no corresponda al intento actual, la vista es "checking".
export function useSession() {
    const [attempt, setAttempt] = useState(0);
    const [stored, setStored] = useState<Stored | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        getCurrentUser(controller.signal)
            .then((session) => setStored({ attempt, session }))
            .catch(() => { if (!controller.signal.aborted) setStored({ attempt, session: { status: "unavailable" } }); });
        return () => controller.abort();
    }, [attempt]);
    const view: AuthView = stored && stored.attempt === attempt ? stored.session : { status: "checking" };
    const retry = useCallback(() => setAttempt((n) => n + 1), []);
    const setSession = useCallback((session: SessionResult) => setStored({ attempt, session }), [attempt]);
    return { view, retry, setSession };
}
