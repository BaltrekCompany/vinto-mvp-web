"use client";

import { LogOut, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";
import { canAdminister } from "@/lib/vinto/admin";
import { profileLabel, type AuthUser } from "@/lib/vinto/auth";
import { accessGateCopy } from "@/lib/vinto/access-copy";
import type { AccessState } from "@/lib/vinto/eligibility";

// MF-13-02: pantalla que sustituye al área operativa cuando NO hay un frente que mostrar: accesos en verificación, sin confirmar (503 / sin conexión) o sin accesos asignados.
// Conserva la cabecera (cerrar sesión) y el enlace a Administración para quien tiene user.manage (decisión por permiso, no por nombre de perfil). No explica motivos internos de autorización.
export function AccessGate({ state, user, onRetry, onLogout }: { state: AccessState; user: AuthUser; onRetry: () => void; onLogout: () => void }) {
    const copy = accessGateCopy(state), administrative = canAdminister(user);
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950" data-section="access-gate" data-state={state.status === "ready" ? "none" : state.status}><header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4"><Brand /><div className="flex items-center gap-3"><span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{user.profiles.map(profileLabel).join(" · ") || "Sin perfil activo"}</span></span>{administrative && <a href="/admin" className="rounded-md px-2 py-1 text-sm font-semibold text-[#146b4f] hover:bg-emerald-50">Administración</a>}<Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={onLogout}><LogOut className="h-4 w-4"/></Button></div></div></header>
        <section className="mx-auto max-w-3xl p-4 md:p-8" role="status"><Badge className="bg-[#146b4f]">Accesos</Badge><h1 className="mt-3 text-3xl font-black">{copy.title}</h1><p className="mt-2 text-slate-700">{copy.message}</p>
            {copy.retry && <Button className="mt-5 bg-[#146b4f]" onClick={onRetry}>Reintentar</Button>}
            {administrative && <a href="/admin" className="mt-5 inline-flex h-12 items-center gap-2 rounded-md border border-[#146b4f] px-5 text-sm font-semibold text-[#146b4f] hover:bg-emerald-50"><Users className="h-4 w-4" aria-hidden/>Administración de usuarios</a>}</section></main>;
}
