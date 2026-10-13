"use client";

import { useState } from "react";
import { AdminConsole } from "@/components/vinto/admin/admin-console";
import { AdminDenied } from "@/components/vinto/admin/admin-access";
import { AuthChecking, AuthUnavailable } from "@/components/vinto/auth-status";
import { Login } from "@/components/vinto/login";
import { canAdminister } from "@/lib/vinto/admin";
import { logout } from "@/lib/vinto/auth-api";
import { useSession } from "@/lib/vinto/use-session";

// /admin: la sesión (GET /api/auth/me) decide qué se muestra. No se solicita NINGUNA lista administrativa sin el permiso `user.manage`
// (AdminConsole ni siquiera se monta), y el backend lo vuelve a exigir en cada endpoint. No hay datos de demostración ni almacenamiento local.
export default function AdminPage() {
    const { view, retry, setSession } = useSession();
    const [loggingOut, setLoggingOut] = useState(false);
    async function endSession() {
        if (loggingOut) return;
        setLoggingOut(true);
        await logout(); // aunque no se confirme la revocación central, la interfaz cierra la sesión (el backend borra la cookie local)
        setSession({ status: "anonymous" });
        setLoggingOut(false);
    }
    const sessionLost = () => setSession({ status: "anonymous" }); // 401 de una API central: vuelve al Login y se descarta el estado administrativo (el componente se desmonta)
    if (view.status === "checking") return <AuthChecking/>;
    if (view.status === "unavailable") return <AuthUnavailable onRetry={retry}/>;
    if (view.status === "anonymous") return <Login onAuthenticated={(user) => setSession({ status: "authenticated", user })}/>;
    if (!canAdminister(view.user)) return <AdminDenied onBack={() => { window.location.assign("/"); }} onLogout={endSession}/>;
    return <AdminConsole key={view.user.id} user={view.user} onLogout={endSession} onSessionLost={sessionLost}/>;
}
