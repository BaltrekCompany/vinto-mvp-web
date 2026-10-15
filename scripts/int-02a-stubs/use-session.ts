// Sustituto de prueba de lib/vinto/use-session.ts (INT-02A): la sesión la fija el escenario (globalThis.__INT02A.session). Solo para scripts/int-02a-central-only.test.mjs.
export function useSession() {
    const g = globalThis as unknown as { __INT02A: { session: unknown } };
    return { view: g.__INT02A.session as never, retry: () => undefined, setSession: () => undefined };
}
