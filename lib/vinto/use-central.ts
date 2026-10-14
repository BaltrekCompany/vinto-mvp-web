"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getActiveAssignment, listAssignments } from "@/lib/vinto/assignments-api";
import type { Availability } from "@/lib/vinto/availability";
import { getProductionAvailability } from "@/lib/vinto/production-api";
import type { ApiResult } from "@/lib/vinto/central-http";
import type { ActiveAssignment, Assignment, WorkOrder } from "@/lib/vinto/orders";
import { availabilityKey, deriveView, type Resource, type Stored } from "@/lib/vinto/resource-view";
import { listWorkOrders } from "@/lib/vinto/work-orders-api";

export type { Resource } from "@/lib/vinto/resource-view";

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
    const view: Resource<T> = deriveView(key, enabled, attempt, stored);
    const refresh = useCallback(() => setAttempt((n) => n + 1), []);
    return { view, refresh };
}

export const useWorkOrders = (enabled: boolean, onUnauthorized: () => void) =>
    useResource<WorkOrder[]>("work-orders", enabled, (signal) => listWorkOrders(signal), onUnauthorized);

export const useAssignments = (enabled: boolean, onUnauthorized: () => void) =>
    useResource<Assignment[]>("assignments", enabled, (signal) => listAssignments(signal), onUnauthorized);

export const useActiveAssignment = (machineCode: string, enabled: boolean, onUnauthorized: () => void) =>
    useResource<ActiveAssignment>(`active:${machineCode}`, enabled, (signal) => getActiveAssignment(machineCode, signal), onUnauthorized);

// Máquinas y formularios centrales operables por la sesión (solo lectura, verificado por el backend). Con `withArticles` incluye los artículos de cada máquina.
// `scope` (opcional) liga el resultado a la sesión: al cambiar de usuario en el mismo navegador la vista anterior no se reutiliza. Sin `scope` la clave es la de siempre (otros llamadores no cambian).
export const useAvailability = (withArticles: boolean, enabled: boolean, onUnauthorized: () => void, scope?: string) =>
    useResource<Availability>(availabilityKey(withArticles, scope), enabled, (signal) => getProductionAvailability(signal, withArticles), onUnauthorized);
