// Sustituto de prueba de lib/vinto/use-central.ts (INT-02A): devuelve la vista que fija el escenario para cada clave y REGISTRA cada clave pedida (para comprobar que todas llevan la sesión). Sin red.
type Hook = { key: string; enabled: boolean };
type Scenario = { resource: (key: string, enabled: boolean) => unknown; hooks: Hook[] };
const scenario = () => (globalThis as unknown as { __INT02A: Scenario }).__INT02A;
export type { Resource } from "../../lib/vinto/resource-view.ts";

// (los argumentos `load` y `onUnauthorized` del hook real se ignoran a propósito: la vista la fija el escenario)
export function useResource(key: string, enabled: boolean, ...ignored: unknown[]) {
    void ignored;
    const s = scenario();
    s.hooks.push({ key, enabled });
    return { view: s.resource(key, enabled) as never, refresh: () => undefined };
}
export const useWorkOrders = (enabled: boolean, onUnauthorized: unknown, scope: string) => useResource(`work-orders:${scope}`, enabled, null, onUnauthorized);
export const useAssignments = (enabled: boolean, onUnauthorized: unknown, scope: string) => useResource(`assignments:${scope}`, enabled, null, onUnauthorized);
export const useActiveAssignment = (machineCode: string, enabled: boolean, onUnauthorized: unknown, scope: string) => useResource(`active:${scope}:${machineCode}`, enabled, null, onUnauthorized);
export const useAvailability = (withArticles: boolean, enabled: boolean, onUnauthorized: unknown, scope: string) => useResource(`availability:${withArticles ? "articles" : "base"}:${scope}`, enabled, null, onUnauthorized);
