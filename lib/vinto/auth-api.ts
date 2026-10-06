import { apiBaseUrl } from "@/lib/vinto/api";
import { interpretLogin, interpretLogout, interpretSession, type LoginResult, type SessionResult } from "@/lib/vinto/auth";

// Cliente de los endpoints de autenticación. La cookie de sesión es HttpOnly: el navegador la envía y la recibe
// gracias a credentials: "include"; este código nunca la lee ni la escribe. Toda la interpretación de respuestas
// vive en lib/vinto/auth.ts (puro y probado).

const ROUTES = { login: "/api/auth/login", me: "/api/auth/me", logout: "/api/auth/logout" } as const;

async function readJson(response: Response): Promise<unknown> {
    try { return await response.json(); } catch { return null; }
}

function isAbort(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
}

export async function getCurrentUser(signal?: AbortSignal): Promise<SessionResult> {
    try {
        const response = await fetch(`${apiBaseUrl()}${ROUTES.me}`, { signal, cache: "no-store", credentials: "include" });
        return interpretSession(response.status, await readJson(response));
    } catch (error) {
        if (isAbort(error)) throw error; // el llamador cancela y descarta el resultado
        return { status: "unavailable" }; // red caída: nunca equivale a "sesión cerrada"
    }
}

export async function login(username: string, password: string, signal?: AbortSignal): Promise<LoginResult> {
    try {
        const response = await fetch(`${apiBaseUrl()}${ROUTES.login}`, {
            method: "POST",
            signal,
            cache: "no-store",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        return interpretLogin(response.status, await readJson(response));
    } catch (error) {
        if (isAbort(error)) throw error;
        return { status: "unavailable" };
    }
}

// confirmed=false cuando el backend no pudo confirmar la revocación central (503 o red caída): el backend igualmente
// intenta borrar la cookie local, y el llamador cierra la sesión en la UI de todas formas.
export async function logout(signal?: AbortSignal): Promise<{ confirmed: boolean }> {
    try {
        const response = await fetch(`${apiBaseUrl()}${ROUTES.logout}`, { method: "POST", signal, cache: "no-store", credentials: "include" });
        return interpretLogout(response.status);
    } catch (error) {
        if (isAbort(error)) throw error;
        return { confirmed: false };
    }
}
