"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getCurrentUser } from "@/lib/vinto/auth-api";
import { DEVICE_KEY_STORAGE, getDeviceKey } from "@/lib/vinto/device";
import { createLocalVault, unlockLocalVault, VaultError } from "@/lib/vinto/offline-vault";
import { readLocalProfile, storeLocalProfile } from "@/lib/vinto/offline-profile-store";
import { issueOnlineReadinessScope } from "@/lib/vinto/offline-scope-api";
import { storeOfflineScope, readOfflineScope } from "@/lib/vinto/offline-scope-store";
import { fetchOnlineQualityPackage } from "@/lib/vinto/offline-quality-api";
import { storeQualityPackage } from "@/lib/vinto/offline-quality-store";
import { offlineStorageStatus, requestOfflinePersistence } from "@/lib/vinto/offline-store";
import type { AuthUser } from "@/lib/vinto/auth";

type PageState = "checking" | "blocked" | "create" | "scope" | "package" | "working";
const eligible = (u: AuthUser) => !u.must_change &&
    (u.permissions.includes("quality.capture") || u.permissions.includes("production.capture"));
const MACHINE = /^[A-Za-z0-9_.-]{1,48}$/;
function parseMachines(raw: string): string[] {
    const codes = raw.split(",").map(s => s.trim()).filter(Boolean);
    if (!codes.length || codes.length > 25 || new Set(codes).size !== codes.length ||
        !codes.every(c => MACHINE.test(c))) throw new Error("invalid-machines");
    return codes;
}

export default function OfflinePreparationPage() {
    const [state, setState] = useState<PageState>("checking");
    const [user, setUser] = useState<AuthUser | null>(null);
    const [secret, setSecret] = useState("");
    const [confirm, setConfirm] = useState("");
    const [machines, setMachines] = useState("");
    const [packageMachine, setPackageMachine] = useState("");
    const [packageForm, setPackageForm] = useState("");
    const [message, setMessage] = useState("Validando sesión online...");
    useEffect(() => {
        let active = true;
        void (async () => {
            try {
                const auth = await getCurrentUser();
                if (!active) return;
                if (auth.status !== "authenticated" || !eligible(auth.user) || !window.isSecureContext) {
                    setMessage("Debe ingresar online desde un navegador seguro con permisos de captura vigentes.");
                    setState("blocked"); return;
                }
                const existing = await readLocalProfile();
                if (!active) return;
                if (existing && existing.ownerId !== auth.user.id.toLowerCase()) {
                    setMessage("Este navegador ya pertenece a otro operario. Utilice su propio navegador.");
                    setState("blocked"); return;
                }
                const storage = await offlineStorageStatus();
                if (!active) return;
                if (!storage.supported) {
                    setMessage("No está disponible el almacenamiento persistente necesario.");
                    setState("blocked"); return;
                }
                setUser(auth.user);
                if (existing) {
                    setMessage("Perfil local preparado. Solicite un alcance firmado SOLO de lectura con su sesión online.");
                    setState("scope");
                } else {
                    setMessage("Preparación de prueba: crea una clave local protegida. No habilita capturas offline.");
                    setState("create");
                }
            } catch {
                if (active) { setMessage("No se pudo comprobar identidad o almacenamiento."); setState("blocked"); }
            }
        })();
        return () => { active = false; };
    }, []);

    async function verifySession(): Promise<AuthUser> {
        if (!user) throw new Error("no-user");
        const auth = await getCurrentUser();
        if (auth.status !== "authenticated" || auth.user.id !== user.id || !eligible(auth.user))
            throw new Error("session-changed");
        return auth.user;
    }
    async function prepareProfile() {
        if (state !== "create" || !user) return;
        if (secret !== confirm) { setMessage("Las frases locales no coinciden."); return; }
        setState("working");
        try {
            const active = await verifySession();
            const deviceKey = getDeviceKey();
            if (localStorage.getItem(DEVICE_KEY_STORAGE) !== deviceKey) throw new Error("device-not-persistent");
            const { record } = await createLocalVault({ ownerId: active.id, deviceKey }, secret);
            await storeLocalProfile(record);
            const persisted = await requestOfflinePersistence();
            setMessage(persisted
                ? "Perfil preparado. Para solicitar el alcance firmado, ingrese su frase local y las máquinas autorizadas."
                : "Perfil preparado, pero el navegador no garantizó persistencia. Requiere QA de equipo.");
            setState("scope");
        } catch (error) {
            setMessage(error instanceof VaultError && error.reason === "weak_passphrase"
                ? "Frase local débil. Use al menos 16 caracteres variados, distintos de su contraseña VINTO."
                : "No se pudo preparar el perfil. Compruebe sesión, navegador y almacenamiento.");
            setState("blocked");
        } finally { setSecret(""); setConfirm(""); }
    }
    async function prepareScope() {
        if (state !== "scope" || !user) return;
        setState("working");
        try {
            const machineCodes = parseMachines(machines);
            const active = await verifySession();
            const existing = await readLocalProfile();
            const deviceKey = getDeviceKey();
            if (!existing || existing.ownerId !== active.id.toLowerCase() ||
                existing.deviceKey !== deviceKey.toLowerCase() ||
                localStorage.getItem(DEVICE_KEY_STORAGE) !== deviceKey) throw new Error("profile-mismatch");
            const contentKey = await unlockLocalVault(existing, secret);
            // The initial key pin comes ONLY from this online authenticated API
            // response over HTTPS (loopback in CI), never from offline storage.
            const envelope = await issueOnlineReadinessScope(deviceKey, machineCodes);
            await storeOfflineScope(contentKey, { ownerId: active.id, deviceKey },
                envelope, envelope.public_key_b64url);
            setMessage("Alcance firmado verificado y guardado cifrado. Consulte los formularios disponibles al desconectarse. Capturas y sincronización siguen deshabilitadas.");
            setState("package");
        } catch {
            setMessage("No se guardó un alcance nuevo. Verifique permisos efectivos, conexión segura, frase y máquinas.");
            setState("scope");
        } finally { setSecret(""); setConfirm(""); }
    }

    async function preparePackage() {
        if (state !== "package" || !user) return;
        setState("working");
        try {
            const active = await verifySession();
            const deviceKey = getDeviceKey();
            const existing = await readLocalProfile();
            if (!existing || existing.ownerId !== active.id.toLowerCase() ||
                existing.deviceKey !== deviceKey.toLowerCase() ||
                localStorage.getItem(DEVICE_KEY_STORAGE) !== deviceKey) throw new Error("identity");
            const machine = packageMachine.trim();
            const form = packageForm.trim().toUpperCase();
            if (!MACHINE.test(machine) || !/^VINTO-P1-(18|22|26|27)$/.test(form)) throw new Error("unsupported");
            const contentKey = await unlockLocalVault(existing, secret);
            const identity = {ownerId: active.id, deviceKey};
            const scope = await readOfflineScope(contentKey, identity);
            if (!scope || !scope.envelope.payload.form_scopes.some(item =>
                item.machine_code === machine && item.form_code === form &&
                item.operation === "quality_machine_capture")) throw new Error("scope");
            const definition = await fetchOnlineQualityPackage(
                deviceKey, machine, form, scope.envelope);
            await storeQualityPackage(contentKey, identity, definition);
            setMessage("Definición completa de Calidad firmada y guardada cifrada. Puede consultarla sin Internet en modo lectura. Capturas deshabilitadas.");
        } catch {
            setMessage("No se guardó el formulario. Compruebe sesión, alcance firmado, máquina, versión vigente, contraseña local y conexión segura.");
        } finally { setSecret(""); setState("package"); }
    }

    return (
        <main className="mx-auto max-w-xl p-6 space-y-5">
            <h1 className="text-2xl font-semibold">VINTO · Preparación offline (ensayo)</h1>
            <p className="text-sm text-amber-700">Solo consulta de alcance firmado. No permite registrar Calidad, Producción ni sincronizar.</p>
            <p role="status" aria-live="polite">{message}</p>
            {state === "create" && (
                <form className="space-y-4" onSubmit={e => {e.preventDefault();void prepareProfile();}}>
                    <label className="block">Frase offline nueva, distinta de la contraseña corporativa
                        <input type="password" autoComplete="new-password" minLength={16} maxLength={256} required
                            value={secret} onChange={e => setSecret(e.target.value)} className="block w-full border rounded p-2 mt-2" />
                    </label>
                    <label className="block">Confirmar frase offline
                        <input type="password" autoComplete="new-password" minLength={16} maxLength={256} required
                            value={confirm} onChange={e => setConfirm(e.target.value)} className="block w-full border rounded p-2 mt-2" />
                    </label>
                    <button type="submit" className="px-4 py-2 rounded bg-emerald-800 text-white">Preparar perfil local</button>
                </form>
            )}
            {state === "scope" && (
                <form className="space-y-4" onSubmit={e => {e.preventDefault();void prepareScope();}}>
                    <label className="block">Máquinas a consultar (códigos separados por coma)
                        <input value={machines} onChange={e => setMachines(e.target.value)}
                            placeholder="MP1, MP3" required className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <label className="block">Frase del perfil local
                        <input type="password" autoComplete="off" required value={secret}
                            onChange={e => setSecret(e.target.value)} className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <button type="submit" className="px-4 py-2 rounded bg-emerald-800 text-white">Guardar alcance firmado cifrado</button>
                    <button type="button" className="block text-sm underline text-emerald-800"
                        onClick={() => {setSecret("");setState("package");setMessage("Continuando con alcance firmado existente. La frase local será necesaria para verificarlo.");}}>
                        Ya tengo un alcance firmado: preparar formulario de Calidad
                    </button>
                </form>
            )}
            {state === "package" && (
                <form className="space-y-4" onSubmit={e=>{e.preventDefault();void preparePackage();}}>
                    <p className="text-sm">Solo formularios de Calidad por máquina P1-18/22/26/27. No habilita captura.</p>
                    <label className="block">Máquina vinculada al alcance firmado
                        <input value={packageMachine} onChange={e=>setPackageMachine(e.target.value)}
                            placeholder="MP1" required className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <label className="block">Código del formulario de Calidad
                        <input value={packageForm} onChange={e=>setPackageForm(e.target.value)}
                            placeholder="VINTO-P1-22" required className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <label className="block">Frase del perfil local
                        <input type="password" autoComplete="off" required value={secret}
                            onChange={e=>setSecret(e.target.value)} className="block w-full border rounded p-2 mt-2"/>
                    </label>
                    <button type="submit" className="px-4 py-2 rounded bg-emerald-800 text-white">
                        Guardar formulario firmado cifrado
                    </button>
                </form>
            )}
            <Link className="underline text-emerald-800" href="/">Volver a VINTO</Link>
        </main>
    );
}
