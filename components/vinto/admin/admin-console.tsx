"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";
import { AdminChangeDialog, AdminNotice, AdminSummaryCards, AdminUserDetail, AdminUserList } from "@/components/vinto/admin/admin-parts";
import { adminApi } from "@/lib/vinto/admin-api";
import { FAILURE_MESSAGES, filterUsers, isLimited, summarize, userLabel, type AdminResult, type AdminSector, type AdminUser, type SectorChange } from "@/lib/vinto/admin";
import { profileLabel, type AuthUser } from "@/lib/vinto/auth";
import { useAdminResource, useSectorChange } from "@/lib/vinto/use-admin";

// Administración de usuarios y concesiones por sector. Se monta SOLO con una sesión válida que tiene `user.manage` (la decide app/admin/page.tsx a partir de /api/auth/me;
// la autorización real es del backend). Se monta con key = id de usuario: al cambiar de sesión TODO el estado administrativo se descarta.
export function AdminConsole({ user, onLogout, onSessionLost }: { user: AuthUser; onLogout: () => void; onSessionLost: () => void }) {
    const session = user.id;
    const [query, setQuery] = useState(""), [selectedId, setSelectedId] = useState<string | null>(null), [forbidden, setForbidden] = useState(false);
    const users = useAdminResource<AdminUser[]>(`users:${session}`, true, (signal) => adminApi.listUsers(signal), onSessionLost);
    const catalog = useAdminResource<AdminSector[]>(`sectors:${session}`, true, (signal) => adminApi.listSectors(signal), onSessionLost);
    const detail = useAdminResource(`detail:${session}:${selectedId ?? "none"}`, selectedId !== null, (signal) => adminApi.getUserSectors(selectedId ?? "", signal), onSessionLost);
    const usersForbidden = users.view.status === "error" && users.view.kind === "forbidden";
    const blocked = forbidden || usersForbidden;
    const change = useSectorChange((result: AdminResult<SectorChange>) => {
        if (!result.ok && result.kind === "session") { onSessionLost(); return; } // 401: vuelve al Login y se limpia el estado administrativo
        if (!result.ok && result.kind === "forbidden") setForbidden(true); // 403: se bloquean las acciones; no se atribuye a sesión vencida
        users.refresh(); detail.refresh(); // se vuelve a leer la API central; nunca se asume el resultado
    });
    const list = users.view.status === "ready" ? users.view.data : null;
    const visible = useMemo(() => (list ? filterUsers(list, query) : []), [list, query]);
    const summary = list ? summarize(list, catalog.view.status === "ready" ? catalog.view.data : []) : null;
    const selected = list?.find((candidate) => candidate.id === selectedId) ?? null;
    const open = (operation: "grant" | "revoke", sector: AdminSector) => { if (selected && !blocked) change.open({ operation, userId: selected.id, userLabel: userLabel(selected), sector }); };
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950">
        <header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between gap-2 px-4"><Brand />
            <div className="flex items-center gap-2"><Link href="/" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-semibold text-[#146b4f] hover:bg-emerald-50"><ArrowLeft className="h-4 w-4" aria-hidden/>Volver</Link>
                <span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{user.profiles.map(profileLabel).join(" · ") || "Sin perfil activo"}</span></span>
                <Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={onLogout}><LogOut className="h-4 w-4"/></Button></div></div></header>
        <section className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-8">
            <div><Badge className="bg-[#146b4f]">Administración</Badge><h1 className="mt-3 text-3xl font-black">Administración de usuarios</h1>
                <p className="mt-1 text-slate-700">Concede o revoca el acceso de cada usuario a los sectores. El perfil define qué puede hacer; la concesión, dónde. Una concesión no habilita un sector.</p></div>
            {blocked && <AdminNotice title="Sin permiso" text={FAILURE_MESSAGES.forbidden}/>}
            {users.view.status === "error" && !usersForbidden && <AdminNotice title="No se pudieron cargar los usuarios" text={FAILURE_MESSAGES[users.view.kind]} onRetry={users.refresh}/>}
            <AdminSummaryCards summary={summary} catalogSize={catalog.view.status === "ready" ? catalog.view.data.length : null}/>
            {(users.view.status === "loading" || users.view.status === "idle") && <div role="status" aria-live="polite" className="rounded-2xl border bg-white p-6 text-sm font-semibold text-slate-700">Cargando usuarios…</div>}
            {list && <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
                <AdminUserList users={visible} retrieved={list.length} query={query} onQuery={setQuery} selectedId={selectedId} onSelect={setSelectedId} limited={isLimited(list.length)} disabled={blocked}/>
                <AdminUserDetail user={selected} detail={detail.view} catalog={catalog.view} blocked={blocked} onGrant={(sector) => open("grant", sector)} onRevoke={(sector) => open("revoke", sector)} onRetryDetail={detail.refresh} onRetryCatalog={catalog.refresh}/></div>}
        </section>
        <AdminChangeDialog state={change.state} onConfirm={change.confirm} onClose={change.close}/>
    </main>;
}
