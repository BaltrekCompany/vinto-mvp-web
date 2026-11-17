"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getCurrentUser } from "@/lib/vinto/auth-api";
import { DEVICE_KEY_STORAGE, getDeviceKey } from "@/lib/vinto/device";
import { createLocalVault, VaultError } from "@/lib/vinto/offline-vault";
import { readLocalProfile, storeLocalProfile } from "@/lib/vinto/offline-profile-store";
import { offlineStorageStatus, requestOfflinePersistence } from "@/lib/vinto/offline-store";
import type { AuthUser } from "@/lib/vinto/auth";

type PageState = "checking" | "blocked" | "ready" | "enrolled" | "working";
const eligible = (u: AuthUser) => !u.must_change && (u.permissions.includes("quality.capture") || u.permissions.includes("production.capture"));

export default function OfflinePreparationPage() {
    const [state, setState] = useState<PageState>("checking");
    const [user, setUser] = useState<AuthUser | null>(null);
    const [secret, setSecret] = useState("");
    const [confirm, setConfirm] = useState("");
    const [message, setMessage] = useState("Validando sesión online...");
    useEffect(() => {
        let active = true;
        void (async () => {
            try {
                const auth = await getCurrentUser();
                if (!active) return;
                if (auth.status !== "authenticated" || !eligible(auth.user)) {
                    setMessage("Debe ingresar online con un usuario habilitado para capturas. No se permite preparar este perfil sin autorización.");
                    setState("blocked"); return;
                }
                const existing = await readLocalProfile();
                if (!active) return;
                if (existing) {
                    setMessage(existing.ownerId === auth.user.id.toLowerCase()
                        ? "Este navegador ya dispone de un perfil local. No se permite reemplazarlo automáticamente."
                        : "Este navegador pertenece a otro perfil local. Utilice el navegador asignado a su usuario.");
                    setState("blocked"); return;
                }
                const storage = await offlineStorageStatus();
                if (!active) return;
                if (!storage.supported) {
                    setMessage("El almacenamiento local no está disponible; no es seguro preparar el acceso offline.");
                    setState("blocked"); return;
                }
                setUser(auth.user);
                setMessage("Preparación de prueba: crea una clave local protegida. No habilita capturas offline ni permisos centrales.");
                setState("ready");
            } catch {
                if (active) { setMessage("No se pudo comprobar identidad o almacenamiento. No se preparó nada."); setState("blocked"); }
            }
        })();
        return () => { active = false; };
    }, []);

    async function prepare() {
        if (state !== "ready" || !user) return;
        if (secret !== confirm) { setMessage("Las frases locales no coinciden."); return; }
        setState("working");
        try {
            // Recheck against the authority at the exact enrollment operation.
            const auth = await getCurrentUser();
            if (auth.status !== "authenticated" || auth.user.id !== user.id || !eligible(auth.user)) {
                setMessage("Se perdió o cambió la sesión online. No se creó ningún perfil.");
                setState("blocked"); return;
            }
            if (!window.isSecureContext) throw new Error("secure-context");
            const key = getDeviceKey();
            if (localStorage.getItem(DEVICE_KEY_STORAGE) !== key) throw new Error("device-not-persistent");
            const { record } = await createLocalVault({ ownerId: auth.user.id, deviceKey: key }, secret);
            await storeLocalProfile(record);
            const persisted = await requestOfflinePersistence();
            setMessage(persisted
                ? "Perfil local preparado. Al reconectar, la sesión online del autor seguirá siendo obligatoria para sincronizar. Las capturas aún están deshabilitadas."
                : "Perfil preparado, pero el navegador no confirmó almacenamiento persistente. Requiere validación del equipo antes de utilizarse.");
            setState("enrolled");
        } catch (error) {
            setMessage(error instanceof VaultError && error.reason === "weak_passphrase"
                ? "La frase local es demasiado débil. Utilice una frase distinta de su contraseña de VINTO, de al menos 16 caracteres variados."
                : "No fue posible preparar el perfil. Verifique sesión, navegador y almacenamiento.");
            setState("blocked"); // Fail closed rather than assuming partial enrolment did not occur.
        } finally { setSecret(""); setConfirm(""); }
    }

    return (
        <main className="mx-auto max-w-xl p-6 space-y-5">
            <h1 className="text-2xl font-semibold">VINTO · Preparación offline (prueba)</h1>
            <p className="text-sm text-amber-700">Función en desarrollo. No permite registrar producción, calidad ni sincronizar capturas.</p>
            <p role="status" aria-live="polite">{message}</p>
            {state === "ready" && (
                <form className="space-y-4" onSubmit={(e) => {e.preventDefault();void prepare();}}>
                    <label className="block">Frase de acceso offline (no use su contraseña corporativa)
                        <input type="password" autoComplete="new-password" minLength={16} maxLength={256} required
                            value={secret} onChange={(e) => setSecret(e.target.value)} className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <label className="block">Confirmar frase de acceso offline
                        <input type="password" autoComplete="new-password" minLength={16} maxLength={256} required
                            value={confirm} onChange={(e) => setConfirm(e.target.value)} className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <button type="submit" className="px-4 py-2 rounded bg-emerald-800 text-white">Preparar perfil local</button>
                </form>
            )}
            {state === "enrolled" && <p className="text-sm">Puede comprobar la verificación local desde la pantalla de contingencia cuando no tenga Internet. No se han descargado OT ni formularios.</p>}
            <Link className="underline text-emerald-800" href="/">Volver a VINTO</Link>
        </main>
    );
}
