import { apiBaseUrl } from "@/lib/vinto/api";
import { failureKindFromStatus, type FailureKind } from "@/lib/vinto/orders";

// Cliente HTTP común de las APIs centrales. Cookie de sesión HttpOnly: credentials "include", sin tokens ni cabeceras
// Authorization. Nunca se devuelve el cuerpo crudo de un error (podría tener detalles internos): solo una categoría.

export type ApiFailure = { ok: false; kind: FailureKind; status: number };
export type ApiResult<T> = { ok: true; data: T; status: number } | ApiFailure;

type Init = { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal };

export async function requestJson<T>(path: string, init: Init, parse: (payload: unknown) => T | null): Promise<ApiResult<T>> {
    let response: Response;
    try {
        response = await fetch(`${apiBaseUrl()}${path}`, {
            method: init.method ?? "GET",
            signal: init.signal,
            cache: "no-store",
            credentials: "include",
            headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
            body: init.body === undefined ? undefined : JSON.stringify(init.body),
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        return { ok: false, kind: "unavailable", status: 0 };
    }
    if (!response.ok) return { ok: false, kind: failureKindFromStatus(response.status), status: response.status };
    let payload: unknown = null;
    try { payload = await response.json(); } catch { /* cuerpo vacío o inválido: lo decide parse */ }
    const data = parse(payload);
    return data === null ? { ok: false, kind: "unavailable", status: response.status } : { ok: true, data, status: response.status };
}
