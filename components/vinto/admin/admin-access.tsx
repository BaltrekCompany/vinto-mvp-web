"use client";

import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";

// Sesión válida pero sin el permiso `user.manage` (la decisión sale de /api/auth/me; el backend la vuelve a exigir en cada endpoint).
export function AdminDenied({ onBack, onLogout }: { onBack: () => void; onLogout: () => void }) {
    return <main className="grid min-h-screen place-items-center bg-[#123f32] p-5"><div role="alert" className="w-full max-w-md rounded-3xl bg-white p-8"><Brand /><h1 className="mt-7 text-2xl font-black">Acceso no autorizado</h1>
        <p className="mt-2 text-sm text-slate-700">Tu usuario no tiene permiso para administrar usuarios y sectores.</p>
        <Button className="mt-5 h-12 w-full bg-[#146b4f]" onClick={onBack}>Volver al inicio</Button><Button variant="outline" className="mt-3 h-12 w-full" onClick={onLogout}>Cerrar sesión</Button></div></main>;
}
