"use client";

// USR-05: interfaz de cuentas (sin lógica de red ni permisos inferidos por perfil).
import { useState, type FormEvent } from "react";
import { AlertTriangle, Pencil, Plus, RefreshCw, RotateCcw, UserRoundX, UserRoundCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AdminNotice } from "@/components/vinto/admin/admin-parts";
import { FAILURE_MESSAGES, userLabel, type AdminResource, type AdminUser } from "@/lib/vinto/admin";
import {
    validateAccountInput, type AccountAction, type AccountInput, type AccountProfile, type AccountState, type AccountTarget,
} from "@/lib/vinto/admin-users";

export function AccountToolbar({ profiles, locked, onCreate, onRetry }: {
    profiles: AdminResource<AccountProfile[]>; locked: boolean; onCreate: () => void; onRetry: () => void;
}) {
    return <section aria-label="Gestión de cuentas" className="rounded-2xl border bg-white p-4 md:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-lg font-black">Gestión de cuentas</h2>
                <p className="mt-1 text-sm text-slate-700">Crea cuentas con un perfil activo. Los sectores y formularios se conceden por separado.</p>
            </div>
            <Button className="bg-[#146b4f]" disabled={locked || profiles.status !== "ready" || profiles.refreshing}
                    onClick={onCreate} aria-label="Crear usuario"><Plus className="mr-2 h-4 w-4"/>Nuevo usuario</Button>
        </div>
        {(profiles.status === "loading" || profiles.status === "idle") && <p role="status" className="mt-2 text-sm text-slate-600">Consultando perfiles disponibles…</p>}
        {profiles.status === "error" && <div className="mt-3"><AdminNotice title="No se pudieron cargar los perfiles"
            text={FAILURE_MESSAGES[profiles.kind]} onRetry={onRetry}/></div>}
        {profiles.status === "ready" && profiles.data.length === 0 && <p role="status" className="mt-2 text-sm text-amber-900">No hay perfiles activos disponibles para crear o editar usuarios.</p>}
    </section>;
}

export function AccountUserActions({ user, locked, currentUserId, onOpen }: {
    user: AdminUser; locked: boolean; currentUserId: string; onOpen: (target: AccountTarget) => void;
}) {
    const editReady = user.profiles.length === 1;
    const target = (action: AccountAction): AccountTarget => ({ action, user });
    return <section aria-label="Acciones de cuenta" className="rounded-2xl border bg-white p-4 md:p-5">
        <h2 className="text-lg font-black">Cuenta de {userLabel(user)}</h2>
        <p className="mt-1 text-sm text-slate-700">Nombre, perfil, contraseña y estado del usuario. Las concesiones existentes no se modifican aquí.</p>
        <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" aria-label="Editar cuenta" disabled={locked || !editReady} onClick={() => onOpen(target("edit"))}>
                <Pencil className="mr-1 h-4 w-4"/>Editar nombre y perfil</Button>
            <Button size="sm" variant="outline" aria-label="Restablecer contraseña" disabled={locked || !user.username} onClick={() => onOpen(target("reset"))}>
                <RotateCcw className="mr-1 h-4 w-4"/>Restablecer contraseña</Button>
            {user.active
                ? <Button size="sm" variant="destructive" aria-label="Desactivar cuenta" disabled={locked || !user.username} onClick={() => onOpen(target("deactivate"))}>
                    <UserRoundX className="mr-1 h-4 w-4"/>Desactivar</Button>
                : <Button size="sm" variant="outline" aria-label="Reactivar cuenta" disabled={locked || !user.username} onClick={() => onOpen(target("reactivate"))}>
                    <UserRoundCheck className="mr-1 h-4 w-4"/>Reactivar</Button>}
        </div>
        {user.id === currentUserId && <p role="note" className="mt-3 text-xs text-amber-950">Esta es tu cuenta. Modificar tu perfil, contraseña o estado puede cerrar tu sesión.</p>}
        {!editReady && <p className="mt-3 text-xs text-amber-950">El usuario no tiene exactamente un perfil vigente; la edición queda bloqueada hasta revisar sus datos.</p>}
    </section>;
}

const TITLES: Record<AccountAction, string> = {
    create: "Crear usuario", edit: "Editar nombre y perfil", reset: "Restablecer contraseña",
    deactivate: "Desactivar cuenta", reactivate: "Reactivar cuenta",
};
const CONFIRM: Record<AccountAction, string> = {
    create: "Crear usuario", edit: "Guardar cambios", reset: "Cambiar contraseña",
    deactivate: "Desactivar usuario", reactivate: "Reactivar usuario",
};

export function AccountForm({ target, profiles, submitting, onConfirm, onClose }: {
    target: AccountTarget; profiles: AccountProfile[]; submitting: boolean; onConfirm: (input: AccountInput) => void; onClose: () => void;
}) {
    const [username, setUsername] = useState("");
    const [name, setName] = useState(target.user?.display_name ?? "");
    const [profile, setProfile] = useState(target.user?.profiles[0] ?? "");
    const [password, setPassword] = useState("");
    const [verifyPassword, setVerifyPassword] = useState("");
    const [reason, setReason] = useState("");
    const [error, setError] = useState<string | null>(null);
    const action = target.action;
    const account = target.user;
    const requiresProfile = action === "create" || action === "edit";
    const needsPassword = action === "create" || action === "reset";
    const changesState = action === "deactivate" || action === "reactivate";
    const ready = !requiresProfile || profiles.length > 0;

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (submitting) return;
        let input: AccountInput;
        if (action === "create") input = { action, username, display_name: name, profile_code: profile, password };
        else if (action === "edit") input = { action, display_name: name, profile_code: profile };
        else if (action === "reset") input = { action, password };
        else input = { action, reason };
        if (needsPassword && password !== verifyPassword) { setError("Las contraseñas no coinciden."); return; }
        const failure = validateAccountInput(target, input, profiles);
        if (failure) { setError(failure); return; }
        setError(null);
        // El payload es transitorio; nunca se añade al estado del controlador ni a un mensaje.
        onConfirm(input);
        setPassword("");
        setVerifyPassword("");
    }

    return <form onSubmit={handleSubmit} className="space-y-4" aria-busy={submitting}>
        <div className="space-y-1"><h3 className="font-semibold">{TITLES[action]}</h3>
            <p className="text-sm text-slate-700">{account ? userLabel(account) : "Se creará una cuenta sin concesiones de sectores ni formularios."}</p></div>
        {action === "create" && <div className="space-y-2"><Label htmlFor="usr05-username">Usuario de acceso</Label>
            <Input id="usr05-username" value={username} maxLength={64} disabled={submitting} onChange={(event) => setUsername(event.target.value)}
                autoComplete="off" spellCheck={false} placeholder="nombre.apellido" required/></div>}
        {(action === "create" || action === "edit") && <>
            <div className="space-y-2"><Label htmlFor="usr05-name">Nombre visible</Label>
                <Input id="usr05-name" value={name} maxLength={200} disabled={submitting}
                    onChange={(event) => setName(event.target.value)} required/></div>
            <div className="space-y-2"><Label htmlFor="usr05-profile">Perfil vigente</Label>
                <select id="usr05-profile" value={profile} disabled={submitting || !ready} required
                        onChange={(event) => setProfile(event.target.value)}
                        className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm">
                    <option value="">Selecciona un perfil…</option>
                    {profiles.map((entry) => <option key={entry.code} value={entry.code}>{entry.name} ({entry.code})</option>)}
                </select>
                <p className="text-xs text-slate-600">El perfil determina permisos. Cambiarlo revoca las sesiones actuales.</p>
            </div>
        </>}
        {needsPassword && <>
            <div className="space-y-2"><Label htmlFor="usr05-password">Contraseña nueva</Label>
                <Input id="usr05-password" type="password" value={password} minLength={12} maxLength={256} disabled={submitting}
                    autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} required/></div>
            <div className="space-y-2"><Label htmlFor="usr05-password-confirm">Repetir contraseña</Label>
                <Input id="usr05-password-confirm" type="password" value={verifyPassword} minLength={12} maxLength={256} disabled={submitting}
                    autoComplete="new-password" onChange={(event) => setVerifyPassword(event.target.value)} required/></div>
            <p className="text-xs text-slate-600">Mínimo 12 caracteres. La contraseña no se mostrará en los resultados ni se guardará en el navegador.</p>
        </>}
        {changesState && <>
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                <AlertTriangle className="mr-1 inline h-4 w-4" aria-hidden/>
                {action === "deactivate"
                    ? "El usuario dejará de poder iniciar sesión y sus sesiones actuales se revocarán. No se borrarán sus registros."
                    : "Se reactivará el acceso, pero todas las sesiones anteriores seguirán invalidadas. Deberá iniciar sesión de nuevo."}
            </div>
            <div className="space-y-2"><Label htmlFor="usr05-reason">Motivo obligatorio</Label>
                <Input id="usr05-reason" value={reason} maxLength={500} disabled={submitting}
                    onChange={(event) => setReason(event.target.value)} required/></div>
        </>}
        {error && <p role="alert" className="text-sm font-semibold text-red-700">{error}</p>}
        <DialogFooter><Button type="button" variant="outline" disabled={submitting} onClick={onClose}>Cancelar</Button>
            <Button type="submit" disabled={submitting || !ready} className={action === "deactivate" ? "bg-red-700 hover:bg-red-800" : "bg-[#146b4f]"}>
                {submitting ? "Aplicando…" : CONFIRM[action]}</Button></DialogFooter>
    </form>;
}

function outcomeMessage(state: Extract<AccountState, { step: "done" }>): string {
    const o = state.outcome;
    if (!o.changed) return "La cuenta ya tenía ese estado o los datos no cambiaron. No se registró una operación nueva.";
    if (o.action === "create") return "Cuenta creada. Asigna sectores y formularios por separado.";
    if (o.action === "edit") return o.sessionsRevoked > 0 ? "Cuenta actualizada; se revocaron las sesiones anteriores por el cambio de perfil." : "Datos de la cuenta actualizados.";
    if (o.action === "reset") return "Contraseña cambiada. Se revocaron las sesiones anteriores.";
    if (o.action === "deactivate") return "Cuenta desactivada. Las sesiones anteriores quedaron revocadas.";
    return "Cuenta reactivada. El usuario deberá iniciar una nueva sesión.";
}

export function AccountDialog({ state, profiles, onConfirm, onClose }: {
    state: AccountState; profiles: AccountProfile[]; onConfirm: (input: AccountInput) => void; onClose: () => void;
}) {
    if (state.step === "closed") return null;
    const pending = state.step === "submitting";
    return <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose(); }}>
        <DialogContent showCloseButton={!pending} className="max-h-[90vh] overflow-y-auto" aria-busy={pending}>
            <DialogHeader><DialogTitle>{TITLES[state.target.action]}</DialogTitle>
                <DialogDescription>Solo un administrador autorizado puede efectuar esta operación. El servidor comprobará los permisos y registrará el cambio.</DialogDescription></DialogHeader>
            {(state.step === "draft" || state.step === "submitting") &&
                <AccountForm key={state.target.action + ":" + (state.target.user?.id ?? "new")}
                    target={state.target} profiles={profiles} submitting={pending} onConfirm={onConfirm} onClose={onClose}/>}
            {state.step === "done" && <div className="space-y-3" role="status">
                <p className="text-sm">{outcomeMessage(state)}</p>
                <p className="text-xs text-slate-600">Usuario: {state.outcome.username || "—"} · Sesiones revocadas: {state.outcome.sessionsRevoked}</p>
                {state.outcome.requestId && <details className="break-all text-xs text-slate-600"><summary>Identificador de auditoría</summary>{state.outcome.requestId}</details>}
                <DialogFooter><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></DialogFooter>
            </div>}
            {state.step === "failed" && <div role="alert" className="space-y-3">
                <p className="text-sm text-red-700">{state.failure.code === "LAST_ADMINISTRATOR"
                    ? "No se puede desactivar ni retirar al último administrador activo."
                    : state.failure.code === "USERNAME_ALREADY_EXISTS"
                        ? "El nombre de usuario ya existe. Indica otro."
                        : FAILURE_MESSAGES[state.failure.kind]}</p>
                {state.failure.kind === "unavailable" && <p className="text-sm text-amber-950">Resultado no confirmado: la operación pudo aplicarse. Relee el estado antes de repetirla.</p>}
                <DialogFooter><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></DialogFooter>
            </div>}
        </DialogContent>
    </Dialog>;
}

export function AccountUncertain({ checking, onRetry }: { checking: boolean; onRetry: () => void }) {
    return <section role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
        <b>Estado de cuenta sin confirmar.</b> La comunicación falló y la operación pudo haberse aplicado.
        No se permiten nuevas operaciones hasta releer el listado del servidor.
        <Button variant="outline" size="sm" disabled={checking} className="ml-3 mt-2"
                onClick={onRetry}><RefreshCw className="mr-1 h-4 w-4"/> {checking ? "Releyendo…" : "Releer estado"}</Button>
    </section>;
}
