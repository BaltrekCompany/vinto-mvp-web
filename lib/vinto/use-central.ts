"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getActiveAssignment, listAssignments } from "@/lib/vinto/assignments-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import type { ActiveAssignment, Assignment, FailureKind, WorkOrder } from "@/lib/vinto/orders";
import { listWorkOrders } from "@/lib/vinto/work-orders-api";

export type Resource<T> =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; data: T; refreshing: boolean }
    | { status: "error"; kind: FailureKind; refreshing: boolean };

type Stored<T> = { key: string; attempt: number; result: { ok: true; data: T } | { ok: false; kind: FailureKind } };

// Recurso central con estados idle | loading | ready | error. La carga ocurre solo al habilitarse, al cambiar la clave o al
// llamar a refresh() (después de una mutación o desde "Reintentar"): no hay polling. Nunca se cae a datos locales ni a demo.
// "loading" y "refreshing" se derivan (sin setState síncrono en el efecto); un 401 se informa a onUnauthorized.
export function useResource<T>(key: string, enabled: boolean, load: (signal: AbortSignal) => Promise<ApiResult<T>>, onUnauthorized: () => void) {
    const [attempt, setAttempt] = useState(0);
    const [stored, setStored] = useState<Stored<T> | null>(null);
    const latest = useRef({ load, onUnauthorized });
    useEffect(() => { latest.current = { load, onUnauthorized }; });
    useEffect(() => {
        if (!enabled) return;
        const controller = new AbortController();
        latest.current.load(controller.signal)
            .then((result) => {
                if (controller.signal.aborted) return;
                if (!result.ok && result.kind === "session") latest.current.onUnauthorized();
                setStored({ key, attempt, result: result.ok ? { ok: true, data: result.data } : { ok: false, kind: result.kind } });
            })
            .catch(() => { if (!controller.signal.aborted) setStored({ key, attempt, result: { ok: false, kind: "unavailable" } }); });
        return () => controller.abort();
    }, [key, enabled, attempt]);
    let view: Resource<T>;
    if (!enabled) view = { status: "idle" };
    else if (!stored || stored.key !== key) view = { status: "loading" };
    else if (stored.result.ok) view = { status: "ready", data: stored.result.data, refreshing: stored.attempt !== attempt };
    else view = { status: "error", kind: stored.result.kind, refreshing: stored.attempt !== attempt };
    const refresh = useCallback(() => setAttempt((n) => n + 1), []);
    return { view, refresh };
}

export const useWorkOrders = (enabled: boolean, onUnauthorized: () => void) =>
    useResource<WorkOrder[]>("work-orders", enabled, (signal) => listWorkOrders(signal), onUnauthorized);

export const useAssignments = (enabled: boolean, onUnauthorized: () => void) =>
    useResource<Assignment[]>("assignments", enabled, (signal) => listAssignments(signal), onUnauthorized);

export const useActiveAssignment = (machineCode: string, enabled: boolean, onUnauthorized: () => void) =>
    useResource<ActiveAssignment>(`active:${machineCode}`, enabled, (signal) => getActiveAssignment(machineCode, signal), onUnauthorized);
