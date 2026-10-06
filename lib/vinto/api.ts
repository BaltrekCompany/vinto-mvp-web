export type CaptureFront = "Bobinas" | "Rebobinado" | "Conversión" | "Calidad";
export type CaptureCountResponse = { front: CaptureFront; count: number; source: "database" };

// Base única de la API (también la usa lib/vinto/auth-api.ts).
export function apiBaseUrl(): string {
    return (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export async function getCaptureCount(front: CaptureFront, signal: AbortSignal): Promise<CaptureCountResponse> {
    const url = new URL(`${apiBaseUrl()}/api/captures/count`);
    url.searchParams.set("front", front);
    const response = await fetch(url, { signal, cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new Error("Consulta central no disponible");
    const payload: unknown = await response.json();
    if (typeof payload !== "object" || payload === null ||
        !("front" in payload) || payload.front !== front ||
        !("source" in payload) || payload.source !== "database" ||
        !("count" in payload) || typeof payload.count !== "number" ||
        !Number.isSafeInteger(payload.count) || payload.count < 0) {
        throw new Error("Respuesta de contador inválida");
    }
    return { front, count: payload.count, source: "database" };
}
