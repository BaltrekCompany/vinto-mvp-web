"use client";

import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";

// Pantallas previas al dashboard: nunca se muestra contenido de planta hasta que /api/auth/me confirma la sesión.
export function AuthChecking({ label = "Validando sesión…" }: { label?: string }) {
    return <main className="grid min-h-screen place-items-center bg-[#123f32] p-5"><div role="status" aria-live="polite" className="w-full max-w-md rounded-3xl bg-white p-8"><Brand /><p className="mt-7 font-semibold text-slate-700">{label}</p></div></main>;
}

// /me falló por red o 503: no se asume ni sesión abierta ni cerrada, y no existe ningún acceso alternativo.
export function AuthUnavailable({ onRetry }: { onRetry: () => void }) {
    return <main className="grid min-h-screen place-items-center bg-[#123f32] p-5"><div role="alert" className="w-full max-w-md rounded-3xl bg-white p-8"><Brand /><h1 className="mt-7 text-2xl font-black">No se pudo validar la sesión</h1><p className="mt-2 text-sm text-slate-700">El servidor de autenticación no está disponible.</p><Button className="mt-5 h-12 w-full bg-[#146b4f]" onClick={onRetry}>Reintentar</Button></div></main>;
}
