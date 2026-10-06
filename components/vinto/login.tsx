"use client";

import { useRef, useState, type FormEvent } from "react";
import { LockKeyhole } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Brand } from "@/components/vinto/brand";
import { login } from "@/lib/vinto/auth-api";
import { LOGIN_MESSAGES, type AuthUser } from "@/lib/vinto/auth";

// Usuario + contraseña contra POST /api/auth/login. La contraseña vive solo en el estado de este componente:
// no se guarda en localStorage/sessionStorage, no se registra y se limpia al terminar la petición.
export function Login({ notice, onAuthenticated }: { notice?: string; onAuthenticated: (user: AuthUser) => void }) {
    const [username, setUsername] = useState(""), [password, setPassword] = useState(""), [pending, setPending] = useState(false), [error, setError] = useState("");
    const inFlight = useRef(false);
    async function submit(event: FormEvent) {
        event.preventDefault();
        if (inFlight.current) return; // evita el doble envío
        if (!username.trim() || !password) { setError("Ingresa usuario y contraseña"); return; }
        inFlight.current = true;
        setPending(true);
        setError("");
        const result = await login(username.trim(), password);
        setPassword(""); // nunca se conserva la contraseña
        inFlight.current = false;
        setPending(false);
        if (result.status === "ok") onAuthenticated(result.user);
        else setError(LOGIN_MESSAGES[result.status]);
    }
    return <main className="grid min-h-screen place-items-center bg-[#123f32] p-5"><form onSubmit={submit} className="w-full max-w-md rounded-3xl bg-white p-8"><Brand /><Badge className="mt-7 bg-amber-100 text-amber-950">MVP To-Be actualizado</Badge><h1 className="mt-4 text-3xl font-black">Ingreso</h1>
        {notice && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">{notice}</p>}
        <Label htmlFor="vinto-username" className="mt-6 block">Usuario</Label><Input id="vinto-username" className="mt-2 h-12 text-slate-950" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={e => setUsername(e.target.value)} disabled={pending}/>
        <Label htmlFor="vinto-password" className="mt-5 block">Contraseña</Label><div className="relative mt-2"><LockKeyhole className="absolute left-3 top-3 h-5 w-5 text-slate-600"/><Input id="vinto-password" type="password" autoComplete="current-password" className="h-12 pl-11 text-slate-950" value={password} onChange={e => setPassword(e.target.value)} disabled={pending}/></div>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-900">{error}</p>}
        <Button type="submit" className="mt-5 h-12 w-full bg-[#146b4f]" disabled={pending}>{pending ? "Ingresando…" : "Ingresar"}</Button></form></main>;
}
