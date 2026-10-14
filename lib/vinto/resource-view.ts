// Estado de un recurso central y su DERIVACIÓN (pura): extraído de useResource para poder probar sin renderizar React que un resultado guardado con una clave NUNCA se presenta bajo otra. Las claves de los
// recursos que dependen de la sesión incluyen el identificador del usuario (sessionScope), de modo que al iniciar sesión otra cuenta en el mismo navegador la vista anterior deja de existir de inmediato,
// antes de recibir ningún resultado HTTP nuevo. Sin red ni DOM.
import type { FailureKind } from "./orders.ts";

export type Resource<T> =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; data: T; refreshing: boolean }
    | { status: "error"; kind: FailureKind; refreshing: boolean };

export type Stored<T> = { key: string; attempt: number; result: { ok: true; data: T } | { ok: false; kind: FailureKind } };

// idle (deshabilitado) | loading (sin resultado guardado PARA ESTA CLAVE) | ready / error (con `refreshing` mientras se recarga el mismo recurso).
export function deriveView<T>(key: string, enabled: boolean, attempt: number, stored: Stored<T> | null): Resource<T> {
    if (!enabled) return { status: "idle" };
    if (!stored || stored.key !== key) return { status: "loading" };
    if (stored.result.ok) return { status: "ready", data: stored.result.data, refreshing: stored.attempt !== attempt };
    return { status: "error", kind: stored.result.kind, refreshing: stored.attempt !== attempt };
}

// Identificador de sesión para las claves: el usuario autenticado; sin sesión, un valor fijo que nunca coincide con el de un usuario.
export const sessionScope = (user: { id: string } | null | undefined): string => (user ? `user:${user.id}` : "anonymous");

export const availabilityKey = (withArticles: boolean, scope?: string): string => `availability:${withArticles ? "articles" : "base"}${scope ? `:${scope}` : ""}`;
export const candidateHistoryKey = (screen: string, scope: string, refresh: number): string => `captures-${screen}:${scope}:${refresh}`;
