// MF-13-02 · Revalidación de accesos. PURO: sin red ni DOM (los eventos del navegador los conecta use-access.ts).
// Un permiso o una concesión pueden revocarse mientras hay una pantalla abierta. Los recursos de disponibilidad se suscriben aquí y se recargan cuando:
//   · la pestaña vuelve a estar visible, o vuelve la conexión (use-access.ts);
//   · el backend rechaza una captura con 403 o 404 (capture-core.ts), que son las señales de que el acceso cambió.
// Ninguna recarga toca borradores ni intentos pendientes: solo vuelven a pedirse las listas de disponibilidad.
const listeners = new Set<() => void>();
let lastRun = 0;
export const REVALIDATION_MIN_INTERVAL_MS = 1000;

export function subscribeRevalidation(listener: () => void): () => void {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
}

// Limita ráfagas (p. ej. visibilitychange + online casi simultáneos). `now` se inyecta solo en pruebas.
export function requestRevalidation(now: number = Date.now()): boolean {
    if (now - lastRun < REVALIDATION_MIN_INTERVAL_MS) return false;
    lastRun = now;
    for (const listener of [...listeners]) listener();
    return true;
}

export const resetRevalidationForTests = (): void => { listeners.clear(); lastRun = 0; };
