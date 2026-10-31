"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/vinto/brand";
import { AdminChangeDialog, AdminNotice, AdminSummaryCards, AdminUserDetail, AdminUserList } from "@/components/vinto/admin/admin-parts";
import { AdminGrantDialog, AdminGrantsSection, type GrantsPanelProps } from "@/components/vinto/admin/admin-grants-parts";
import { adminApi, grantsApi } from "@/lib/vinto/admin-api";
import {
    BLOCK_TITLES, FAILURE_MESSAGES, blockMessage, deriveAccess, filterUsers, isLimited, summarize, userLabel,
    type AccessBlock, type AdminFailureKind, type AdminResource, type AdminResult, type AdminSector, type AdminUser, type ChangeState, type SectorChange, type UserSectors,
} from "@/lib/vinto/admin";
import { profileLabel, type AuthUser } from "@/lib/vinto/auth";
import {
    actionsLocked, findMachine, grantResultText, inertReasons, isReread, markUncertain, nextUncertainty, refreshPlan, visibleFeedback,
    type ChangeOperation, type FormRow, type GrantFeedback, type FormsCatalog, type GrantChangeState, type GrantChange, type GrantTarget, type MachineCatalog, type Uncertainty, type UserDetail, type UserGrants,
} from "@/lib/vinto/admin-grants";
import { useAdminResource, useGrantChange, useSectorChange } from "@/lib/vinto/use-admin";

// Vista de presentación de la consola: recibe los recursos ya cargados y los manejadores (sin hooks de red), de modo que cada estado se puede renderizar y probar.
export type AdminConsoleViewProps = {
    user: AuthUser; users: AdminResource<AdminUser[]>; catalog: AdminResource<AdminSector[]>; detail: AdminResource<UserSectors>;
    query: string; onQuery: (value: string) => void; selectedId: string | null; onSelect: (id: string) => void;
    block: AccessBlock; change: ChangeState; onOpen: (operation: "grant" | "revoke", sector: AdminSector) => void; onConfirm: () => void; onClose: () => void;
    onRetryUsers: () => void; onRetryCatalog: () => void; onRetryDetail: () => void; onLogout: () => void;
    // MF-13-01C.3 (opcionales: la administración por sector se puede renderizar sola): sección «Máquinas y formularios» y su diálogo de confirmación.
    grantsPanel?: GrantsPanelProps; grantDialog?: { state: GrantChangeState; onConfirm: () => void; onClose: () => void };
};

export function AdminConsoleView(props: AdminConsoleViewProps) {
    const { user, users, catalog, detail, query, selectedId, block, change } = props;
    const list = users.status === "ready" ? users.data : null;
    const visible = useMemo(() => (list ? filterUsers(list, query) : []), [list, query]);
    const summary = list ? summarize(list, catalog.status === "ready" ? catalog.data : []) : null;
    const selected = list?.find((candidate) => candidate.id === selectedId) ?? null;
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950">
        <header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between gap-2 px-4"><Brand />
            <div className="flex items-center gap-2"><Link href="/" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-semibold text-[#146b4f] hover:bg-emerald-50"><ArrowLeft className="h-4 w-4" aria-hidden/>Volver</Link>
                <span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{user.profiles.map(profileLabel).join(" · ") || "Sin perfil activo"}</span></span>
                <Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={props.onLogout}><LogOut className="h-4 w-4"/></Button></div></div></header>
        <section className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-8">
            <div><Badge className="bg-[#146b4f]">Administración</Badge><h1 className="mt-3 text-3xl font-black">Administración de usuarios</h1>
                <p className="mt-1 text-slate-700">Concede o revoca el acceso de cada usuario a los sectores. El perfil define qué puede hacer; la concesión, dónde. Una concesión no habilita un sector.</p></div>
            {block && <AdminNotice title={BLOCK_TITLES[block]} text={blockMessage(block)}/>}
            {users.status === "error" && !block && <AdminNotice title="No se pudieron cargar los usuarios" text={FAILURE_MESSAGES[users.kind]} onRetry={props.onRetryUsers}/>}
            <AdminSummaryCards summary={summary} catalogSize={catalog.status === "ready" ? catalog.data.length : null}/>
            {(users.status === "loading" || users.status === "idle") && <div role="status" aria-live="polite" className="rounded-2xl border bg-white p-6 text-sm font-semibold text-slate-700">Cargando usuarios…</div>}
            {list && <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
                <AdminUserList users={visible} retrieved={list.length} query={query} onQuery={props.onQuery} selectedId={selectedId} onSelect={props.onSelect} limited={isLimited(list.length)} disabled={block !== null}/>
                <AdminUserDetail user={selected} detail={detail} catalog={catalog} block={block} onGrant={(sector) => props.onOpen("grant", sector)} onRevoke={(sector) => props.onOpen("revoke", sector)} onRetryDetail={props.onRetryDetail} onRetryCatalog={props.onRetryCatalog}/></div>}
            {selected && props.grantsPanel && <AdminGrantsSection user={selected} {...props.grantsPanel}/>}
        </section>
        <AdminChangeDialog state={change} onConfirm={props.onConfirm} onClose={props.onClose}/>
        {props.grantDialog && <AdminGrantDialog state={props.grantDialog.state} onConfirm={props.grantDialog.onConfirm} onClose={props.grantDialog.onClose}/>}
    </main>;
}

// Administración de usuarios y concesiones por sector. Se monta SOLO con una sesión válida que tiene `user.manage` (la decide app/admin/page.tsx a partir de /api/auth/me;
// la autorización real es del backend). Se monta con key = id de usuario y se DESMONTA al cerrar sesión: sus controladores se liberan (abortan la petición en vuelo e ignoran
// cualquier resultado tardío), de modo que nada de una sesión anterior puede afectar a otra.
export function AdminConsole({ user, onLogout, onSessionLost }: { user: AuthUser; onLogout: () => void; onSessionLost: () => void }) {
    const session = user.id;
    const [query, setQuery] = useState(""), [selectedId, setSelectedId] = useState<string | null>(null), [changeFailure, setChangeFailure] = useState<AdminFailureKind | null>(null);
    // MF-13-01C.3: máquina elegida (solo para MOSTRAR formularios; el objetivo de una operación se fija al abrir el diálogo), resultado incierto y último resultado de ESTE usuario.
    const [machineCode, setMachineCode] = useState<string | null>(null), [uncertainty, setUncertainty] = useState<Uncertainty>(null);
    const [feedback, setFeedback] = useState<GrantFeedback | null>(null);
    const users = useAdminResource<AdminUser[]>(`users:${session}`, true, (signal) => adminApi.listUsers(signal), onSessionLost);
    const catalog = useAdminResource<AdminSector[]>(`sectors:${session}`, true, (signal) => adminApi.listSectors(signal), onSessionLost);
    const detail = useAdminResource<UserSectors>(`detail:${session}:${selectedId ?? "none"}`, selectedId !== null, (signal) => adminApi.getUserSectors(selectedId ?? "", signal), onSessionLost);
    // Lecturas de «Máquinas y formularios»: solo con un usuario seleccionado, siempre desde la API (nada de listas estáticas ni almacenamiento local). Las claves incluyen sesión y usuario:
    // al cambiar se cancela la petición anterior y su resultado jamás se muestra en la vista del usuario actual.
    const picked = selectedId !== null;
    const machines = useAdminResource<MachineCatalog>(`machines:${session}`, picked, (signal) => grantsApi.getMachineCatalog(signal), onSessionLost);
    const forms = useAdminResource<FormsCatalog>(`forms:${session}`, picked, (signal) => grantsApi.getFormsCatalog(signal), onSessionLost);
    const userDetail = useAdminResource<UserDetail>(`user:${session}:${selectedId ?? "none"}`, picked, (signal) => grantsApi.getUserDetail(selectedId ?? "", signal), onSessionLost);
    const grants = useAdminResource<UserGrants>(`grants:${session}:${selectedId ?? "none"}`, picked, (signal) => grantsApi.getUserGrants(selectedId ?? "", signal), onSessionLost);
    const history = useAdminResource<UserGrants>(`history:${session}:${selectedId ?? "none"}`, picked, (signal) => grantsApi.getUserGrantsHistory(selectedId ?? "", signal), onSessionLost);
    // Un 403 (permiso u origen) en cualquier lectura o cambio bloquea las acciones; nunca se interpreta como sesión vencida (eso es el 401).
    const block = deriveAccess([users.view, catalog.view, detail.view, machines.view, forms.view, userDetail.view, grants.view, history.view], changeFailure);
    const change = useSectorChange((result: AdminResult<SectorChange>) => {
        if (!result.ok && result.kind === "session") { onSessionLost(); return; } // 401: vuelve al Login y se limpia el estado administrativo
        if (!result.ok && (result.kind === "forbidden" || result.kind === "origin")) setChangeFailure(result.kind); // 403: se bloquean las acciones
        users.refresh(); detail.refresh(); userDetail.refresh(); // se vuelve a leer la API central; nunca se asume el resultado
    });
    // Concesión / revocación de un formulario: tras CUALQUIER resultado (también un fallo de red) se vuelve a leer el estado desde el backend. Un resultado incierto bloquea nuevas
    // acciones sobre ese usuario hasta que una relectura completa lo confirme. El resultado de otro usuario no se muestra en la vista del actual.
    const grantChange = useGrantChange((result: AdminResult<GrantChange>, target: GrantTarget) => {
        if (!result.ok && result.kind === "session") { onSessionLost(); return; }
        if (!result.ok && (result.kind === "forbidden" || result.kind === "origin")) setChangeFailure(result.kind);
        setUncertainty(markUncertain(result, target.userId));
        setFeedback(result.ok ? { owner: target.userId, ...grantResultText(result.data, target.userLabel, target.machineCode, target.formCode) } : null);
        const plan = refreshPlan(result);
        if (plan.user) { grants.refresh(); history.refresh(); userDetail.refresh(); }
        if (plan.catalogs) { machines.refresh(); forms.refresh(); }
    });
    // La incertidumbre se cierra solo con una relectura completa y correcta del usuario seleccionado (o al cambiar de usuario). Se ajusta durante el render, no en un efecto.
    const settledUncertainty = nextUncertainty(uncertainty, selectedId, isReread([grants.view, userDetail.view]));
    if (settledUncertainty !== uncertainty) setUncertainty(settledUncertainty);
    const uncertain = settledUncertainty !== null && settledUncertainty.userId === selectedId;
    const selected = users.view.status === "ready" ? users.view.data.find((candidate) => candidate.id === selectedId) ?? null : null;
    function openGrant(operation: ChangeOperation, row: FormRow, machine: { code: string; name: string }) {
        if (selected === null || userDetail.view.status !== "ready" || machines.view.status !== "ready" || grants.view.status !== "ready") return;
        if (actionsLocked({ block, uncertain, views: [userDetail.view, machines.view, grants.view] })) return;
        const sector = findMachine(machines.view.data, machine.code)?.sector ?? null, person = userDetail.view.data;
        const inert = operation === "grant" ? inertReasons({ userActive: person.active, grantedSectors: person.sectors, sector, offered: row.offered }) : row.inert;
        grantChange.open({ operation, userId: selected.id, userLabel: userLabel(selected), machineCode: machine.code, machineName: machine.name, formCode: row.code, formName: row.name, offered: row.offered,
            inert, sectorGranted: sector !== null && person.sectors.some((granted) => granted.code === sector.code) });
    }
    const panel: GrantsPanelProps = {
        detail: userDetail.view, catalog: machines.view, forms: forms.view, grants: grants.view, history: history.view, machineCode, onSelectMachine: setMachineCode, block, uncertain,
        feedback: visibleFeedback(feedback, selectedId), onOpen: openGrant,
        onRetryDetail: userDetail.refresh, onRetryCatalog: machines.refresh, onRetryForms: forms.refresh, onRetryGrants: grants.refresh, onRetryHistory: history.refresh,
    };
    return <AdminConsoleView user={user} users={users.view} catalog={catalog.view} detail={detail.view} query={query} onQuery={setQuery} selectedId={selectedId} onSelect={setSelectedId}
        block={block} change={change.state} onOpen={(operation, sector) => { if (selected && block === null) change.open({ operation, userId: selected.id, userLabel: userLabel(selected), sector }); }}
        onConfirm={change.confirm} onClose={change.close} onRetryUsers={users.refresh} onRetryCatalog={catalog.refresh} onRetryDetail={detail.refresh} onLogout={onLogout}
        grantsPanel={panel} grantDialog={{ state: grantChange.state, onConfirm: grantChange.confirm, onClose: grantChange.close }}/>;
}
