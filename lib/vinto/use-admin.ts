"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { adminApi } from "@/lib/vinto/admin-api";
import {
    CLOSED, createChangeController, deriveResource, loadResource,
    type AdminResource, type AdminResult, type ChangeController, type ChangeState, type ChangeTarget, type SectorChange, type StoredResource,
} from "@/lib/vinto/admin";

// Recurso administrativo con estados idle | loading | ready | error. La clave incluye la sesión (id del usuario) y el usuario seleccionado: al cambiarla se cancela la
// petición anterior (AbortController) y el resultado viejo deja de aplicar (la vista pasa a "loading"), de modo que nunca se muestran datos de otra sesión u otro usuario.
// Un 401 se informa a onUnauthorized. Nunca hay polling, localStorage ni datos de demostración. La lógica vive en lib/vinto/admin.ts (probada con Node).
export function useAdminResource<T>(key: string, enabled: boolean, load: (signal: AbortSignal) => Promise<AdminResult<T>>, onUnauthorized: () => void) {
    const [attempt, setAttempt] = useState(0);
    const [stored, setStored] = useState<StoredResource<T> | null>(null);
    const latest = useRef({ load, onUnauthorized });
    useEffect(() => { latest.current = { load, onUnauthorized }; });
    useEffect(() => {
        if (!enabled) return;
        const controller = new AbortController();
        void loadResource((signal) => latest.current.load(signal), controller.signal, key, attempt, setStored, () => latest.current.onUnauthorized());
        return () => controller.abort();
    }, [key, enabled, attempt]);
    const view: AdminResource<T> = deriveResource(enabled, key, attempt, stored);
    const refresh = useCallback(() => setAttempt((n) => n + 1), []);
    return { view, refresh };
}

// Concesión / revocación: ver createChangeController. Este hook solo espeja su estado en React y lo libera al desmontar.
export function useSectorChange(onSettled: (result: AdminResult<SectorChange>) => void) {
    const [state, setState] = useState<ChangeState>(CLOSED);
    const settled = useRef(onSettled);
    const controller = useRef<ChangeController | null>(null);
    useEffect(() => { settled.current = onSettled; });
    useEffect(() => {
        const created = createChangeController(adminApi, setState, (result) => settled.current(result));
        controller.current = created;
        return () => { created.dispose(); controller.current = null; };
    }, []);
    const open = useCallback((target: ChangeTarget) => controller.current?.open(target), []);
    const close = useCallback(() => controller.current?.close(), []);
    const confirm = useCallback(() => controller.current?.confirm() ?? Promise.resolve(), []);
    return { state, open, close, confirm };
}
