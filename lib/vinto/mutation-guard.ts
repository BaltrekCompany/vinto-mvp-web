// MF-13-03B PR6: una sola escritura a la vez y descarte de respuestas tardías. PURO.
//
// `begin()` devuelve un token o `null` si ya hay una escritura en curso (doble envío: la segunda no sale). `isCurrent(token)` es verdadero solo mientras no se haya llamado a
// `reset()` (desmontaje de la pantalla o cambio de sesión): una respuesta que llega después NO debe tocar el borrador, ni mostrar avisos, ni refrescar datos de otra cuenta.

export type MutationToken = { readonly id: number; readonly epoch: number };

export function createMutationGuard() {
    let counter = 0, epoch = 0, active: MutationToken | null = null;
    return {
        begin(): MutationToken | null {
            if (active) return null;
            active = { id: ++counter, epoch };
            return active;
        },
        end(token: MutationToken): void {
            if (active && active.id === token.id) active = null;
        },
        isCurrent(token: MutationToken): boolean {
            return token.epoch === epoch;
        },
        busy(): boolean {
            return active !== null;
        },
        reset(): void {
            epoch += 1;
            active = null;
        },
    };
}

export type GuardedResult<T> = { ok: true; data: T } | { ok: false; kind: string };
export type GuardedHandlers<T> = {
    onStart: () => void; // la escritura salió (p. ej. marcar «ocupado»)
    onOk: (data: T) => void; // respuesta vigente y correcta
    onSession: () => void; // 401: se vuelve al inicio de sesión
    onFailure: (kind: string) => void; // cualquier otro fallo: el borrador NO se descarta
    onSettled: () => void; // fin de una escritura VIGENTE (no se llama para una respuesta tardía)
};
export type GuardedOutcome = "skipped" | "stale" | "ok" | "session" | "failure";

// Orquesta UNA escritura: la segunda mientras hay una en curso no sale («skipped»); una respuesta posterior a `reset()` se descarta en silencio («stale»: ni borrador, ni avisos, ni refresco).
export async function runGuarded<T>(guard: ReturnType<typeof createMutationGuard>, action: () => Promise<GuardedResult<T>>, handlers: GuardedHandlers<T>): Promise<GuardedOutcome> {
    const token = guard.begin();
    if (!token) return "skipped";
    handlers.onStart();
    try {
        const result = await action();
        if (!guard.isCurrent(token)) return "stale";
        if (result.ok) { handlers.onOk(result.data); return "ok"; }
        if (result.kind === "session") { handlers.onSession(); return "session"; }
        handlers.onFailure(result.kind);
        return "failure";
    } catch {
        if (!guard.isCurrent(token)) return "stale";
        handlers.onFailure("unavailable");
        return "failure";
    } finally {
        guard.end(token);
        if (guard.isCurrent(token)) handlers.onSettled();
    }
}
