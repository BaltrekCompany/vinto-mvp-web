"use client";

import { LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";
import { profileLabel, type AuthUser } from "@/lib/vinto/auth";

// Vista segura para usuarios sin rol operativo (por ejemplo DATA_BALTREK): sin acciones de planta.
export function TechnicalView({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
    const administrative = user.profiles.includes("DATA_BALTREK");
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4"><Brand /><div className="flex items-center gap-3"><span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{user.profiles.map(profileLabel).join(" · ") || "Sin perfil activo"}</span></span><Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={onLogout}><LogOut className="h-4 w-4"/></Button></div></div></header>
        <section className="mx-auto max-w-3xl p-4 md:p-8"><Badge className="bg-[#146b4f]">MVP To-Be actualizado</Badge><h1 className="mt-3 text-3xl font-black">{administrative ? "Administración técnica" : "Sin perfil operativo"}</h1>
            <p className="mt-2 text-slate-700">{administrative ? "Los módulos administrativos se incorporarán en una siguiente etapa." : "Tu usuario no tiene un perfil operativo activo. Contacta con Data Baltrek."}</p></section></main>;
}
