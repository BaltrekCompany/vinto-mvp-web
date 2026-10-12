export type CaptureFront = "Bobinas" | "Rebobinado" | "Conversión" | "Calidad";
export type CaptureCountResponse = { front: CaptureFront; count: number; source: "database" };

// Base única de la API (también la usa lib/vinto/auth-api.ts).
export function apiBaseUrl(): string {
    return (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

// Por qué falló el contador central: sesión vencida (401), sin permiso (403) o no disponible (red, 5xx, cuerpo inválido).
export type CaptureCountFailure = "session" | "forbidden" | "unavailable";
export class CaptureCountError extends Error {
    kind: CaptureCountFailure; // campo explícito: la sintaxis de propiedades de parámetro no se puede ejecutar con type stripping
    constructor(kind: CaptureCountFailure) { super("Consulta central no disponible"); this.kind = kind; }
}

// GET /api/captures/count exige sesión: la cookie HttpOnly viaja con credentials "include" (nunca se lee ni se copia en JavaScript).
// El backend limita el conteo a los sectores concedidos a la sesión; el cliente no envía sectores.
export async function getCaptureCount(front: CaptureFront, signal: AbortSignal): Promise<CaptureCountResponse> {
    const url = new URL(`${apiBaseUrl()}/api/captures/count`);
    url.searchParams.set("front", front);
    let response: Response;
    try {
        response = await fetch(url, { signal, cache: "no-store", credentials: "include" });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        throw new CaptureCountError("unavailable");
    }
    if (response.status === 401) throw new CaptureCountError("session");
    if (response.status === 403) throw new CaptureCountError("forbidden");
    if (!response.ok) throw new CaptureCountError("unavailable");
    let payload: unknown;
    try { payload = await response.json(); } catch { throw new CaptureCountError("unavailable"); }
    if (typeof payload !== "object" || payload === null ||
        !("front" in payload) || payload.front !== front ||
        !("source" in payload) || payload.source !== "database" ||
        !("count" in payload) || typeof payload.count !== "number" ||
        !Number.isSafeInteger(payload.count) || payload.count < 0) {
        throw new CaptureCountError("unavailable");
    }
    return { front, count: payload.count, source: "database" };
}
