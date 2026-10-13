"use client";

import { Search } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { profileLabel } from "@/lib/vinto/auth";
import {
    ADMIN_USERS_MAX, BLOCK_TITLES, FAILURE_MESSAGES, INERT_NOTICE, blockMessage, confirmationText, grantableSectors, resultText, revocableSectors, sectorBadges, userLabel,
    type AccessBlock, type AdminFailureKind, type AdminResource, type AdminSector, type AdminSummary, type AdminUser, type ChangeState, type ChangeTarget, type SectorBadge, type UserSectors,
} from "@/lib/vinto/admin";

// Componentes de presentación de la administración de usuarios y sectores. No hacen peticiones ni guardan nada: reciben datos ya validados.
const TONES: Record<SectorBadge["tone"], string> = {
    ok: "border-emerald-300 bg-emerald-50 text-emerald-900",
    warn: "border-amber-300 bg-amber-50 text-amber-950",
    muted: "border-slate-300 bg-slate-100 text-slate-700",
};

export function BadgeList({ badges }: { badges: SectorBadge[] }) {
    return <>{badges.map((badge) => <Badge key={badge.text} variant="outline" className={TONES[badge.tone]}>{badge.text}</Badge>)}</>;
}

function SectorChip({ sector }: { sector: AdminSector }) {
    // En el listado se distingue de un vistazo: concedido y operativo (verde), concedido pero inerte/inactivo (ámbar o gris).
    const tone = sector.operational ? TONES.ok : sector.active ? TONES.warn : TONES.muted;
    const hint = sector.operational ? "operativo" : sector.active ? "no operativo (inerte)" : "inactivo";
    return <Badge variant="outline" className={tone} title={`${sector.name}: ${hint}`}>{sector.code}</Badge>;
}

export function AdminNotice({ title, text, onRetry, retryLabel = "Reintentar", tone = "warn" }: { title: string; text: string; onRetry?: () => void; retryLabel?: string; tone?: "warn" | "info" }) {
    return <Alert role="alert" className={tone === "warn" ? "border-amber-300 bg-amber-50 text-amber-950" : "border-slate-300 bg-white text-slate-900"}>
        <AlertTitle className="font-black">{title}</AlertTitle>
        <AlertDescription className="text-inherit"><p>{text}</p>{onRetry && <Button className="mt-3 bg-[#146b4f]" size="sm" onClick={onRetry}>{retryLabel}</Button>}</AlertDescription>
    </Alert>;
}

export function AdminSummaryCards({ summary, catalogSize }: { summary: AdminSummary | null; catalogSize: number | null }) {
    const cards = [
        { label: "Usuarios recuperados", value: summary?.users, note: summary?.limited ? `Posible límite: la API devuelve como máximo ${ADMIN_USERS_MAX}; puede haber más usuarios.` : "Incluye activos e inactivos." },
        { label: "Usuarios activos", value: summary?.activeUsers, note: "Entre los recuperados." },
        { label: "Concesiones visibles", value: summary?.grants, note: "Suma de concesiones de los usuarios recuperados." },
        { label: "Sectores operativos", value: summary?.operationalSectors, note: catalogSize === null ? "Catálogo central no disponible." : `De ${catalogSize} en el catálogo central.` },
    ];
    return <div className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">{cards.map((card) => <div key={card.label} className="rounded-2xl border bg-white p-4 md:p-5" data-testid="admin-summary-card">
        <p className="text-sm text-slate-700">{card.label}</p><p className="mt-2 text-2xl font-black md:text-3xl">{card.value ?? "—"}</p><p className="mt-2 text-xs text-slate-600">{card.note}</p></div>)}</div>;
}

export function AdminUserList({ users, retrieved, query, onQuery, selectedId, onSelect, limited, disabled }: {
    users: AdminUser[]; retrieved: number; query: string; onQuery: (value: string) => void; selectedId: string | null; onSelect: (id: string) => void; limited: boolean; disabled: boolean;
}) {
    return <section aria-label="Usuarios" className="rounded-2xl border bg-white p-4 md:p-5">
        <Label htmlFor="admin-search" className="text-sm font-bold">Buscar usuario</Label>
        <div className="relative mt-2"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-600" aria-hidden/><Input id="admin-search" type="search" className="h-11 pl-9" placeholder="Usuario, nombre o perfil" value={query} onChange={(event) => onQuery(event.target.value)} autoComplete="off" spellCheck={false}/></div>
        <p className="mt-2 text-xs text-slate-600">La búsqueda opera solo sobre los {retrieved} usuarios recuperados{limited ? `; se alcanzó el máximo de ${ADMIN_USERS_MAX} de la API, así que podría haber usuarios que no se muestran.` : "."}</p>
        {retrieved === 0 ? <p className="mt-4 rounded-lg border border-dashed p-4 text-sm text-slate-700">No hay usuarios para mostrar.</p>
            : users.length === 0 ? <p className="mt-4 rounded-lg border border-dashed p-4 text-sm text-slate-700">Ningún usuario recuperado coincide con «{query}».</p>
                : <>
                    <div className="mt-4 hidden md:block"><Table><TableHeader><TableRow><TableHead>Usuario</TableHead><TableHead>Estado</TableHead><TableHead>Perfiles</TableHead><TableHead>Sectores concedidos</TableHead><TableHead className="text-right">Acción</TableHead></TableRow></TableHeader>
                        <TableBody>{users.map((user) => <TableRow key={user.id} data-state={user.id === selectedId ? "selected" : undefined} aria-selected={user.id === selectedId}>
                            <TableCell><b>{user.username ?? "—"}</b><br /><span className="text-xs text-slate-600">{user.display_name}</span></TableCell>
                            <TableCell><Badge variant="outline" className={user.active ? TONES.ok : TONES.muted}>{user.active ? "Activo" : "Inactivo"}</Badge></TableCell>
                            <TableCell><div className="flex flex-wrap gap-1">{user.profiles.length ? user.profiles.map((profile) => <Badge key={profile} variant="outline" className="border-slate-300 bg-white text-slate-800">{profileLabel(profile)}</Badge>) : <span className="text-xs text-slate-600">Sin perfil activo</span>}</div></TableCell>
                            <TableCell><div className="flex flex-wrap gap-1">{user.sectors.length ? user.sectors.map((sector) => <SectorChip key={sector.code} sector={sector}/>) : <span className="text-xs text-slate-600">Sin concesiones</span>}</div></TableCell>
                            <TableCell className="text-right"><Button size="sm" variant={user.id === selectedId ? "default" : "outline"} className={user.id === selectedId ? "bg-[#146b4f]" : ""} disabled={disabled} aria-label={`Administrar ${user.username ?? user.display_name}`} onClick={() => onSelect(user.id)}>Administrar</Button></TableCell></TableRow>)}</TableBody></Table></div>
                    <ul className="mt-4 space-y-3 md:hidden">{users.map((user) => <li key={user.id} className={`rounded-xl border p-4 ${user.id === selectedId ? "border-[#146b4f] bg-emerald-50" : ""}`}>
                        <div className="flex items-start justify-between gap-3"><div><b>{user.username ?? "—"}</b><br /><span className="text-xs text-slate-600">{user.display_name}</span></div><Badge variant="outline" className={user.active ? TONES.ok : TONES.muted}>{user.active ? "Activo" : "Inactivo"}</Badge></div>
                        <div className="mt-2 flex flex-wrap gap-1">{user.profiles.map((profile) => <Badge key={profile} variant="outline" className="border-slate-300 bg-white text-slate-800">{profileLabel(profile)}</Badge>)}</div>
                        <div className="mt-2 flex flex-wrap gap-1">{user.sectors.length ? user.sectors.map((sector) => <SectorChip key={sector.code} sector={sector}/>) : <span className="text-xs text-slate-600">Sin concesiones</span>}</div>
                        <Button size="sm" className="mt-3 w-full bg-[#146b4f]" disabled={disabled} aria-label={`Administrar ${user.username ?? user.display_name}`} onClick={() => onSelect(user.id)}>Administrar</Button></li>)}</ul></>}
    </section>;
}

function SectorRow({ sector, action }: { sector: AdminSector; action: React.ReactNode }) {
    return <li className="rounded-xl border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><b>{sector.name}</b> <span className="text-xs text-slate-600">({sector.code})</span><div className="mt-1 flex flex-wrap gap-1"><BadgeList badges={sectorBadges(sector)}/></div></div>{action}</div>
        {sector.active && !sector.operational && <p className="mt-2 text-xs text-amber-950">{INERT_NOTICE}</p>}
    </li>;
}

export function AdminUserDetail({ user, detail, catalog, block, onGrant, onRevoke, onRetryDetail, onRetryCatalog }: {
    user: AdminUser | null; detail: AdminResource<UserSectors>; catalog: AdminResource<AdminSector[]>; block: AccessBlock;
    onGrant: (sector: AdminSector) => void; onRevoke: (sector: AdminSector) => void; onRetryDetail: () => void; onRetryCatalog: () => void;
}) {
    const blocked = block !== null; // 403 (permiso u origen): las acciones quedan bloqueadas; nunca se confunde con una sesión vencida
    if (user === null) return <section aria-label="Detalle de usuario" className="rounded-2xl border border-dashed bg-white p-6"><h2 className="font-black">Detalle de usuario</h2><p className="mt-2 text-sm text-slate-700">Selecciona un usuario del listado para ver y administrar su acceso por sector.</p></section>;
    return <section aria-label="Detalle de usuario" className="rounded-2xl border bg-white p-5">
        <h2 className="text-xl font-black">{userLabel(user)}</h2>
        <p className="text-sm text-slate-700">{user.username ?? "Sin usuario de acceso"} · <Badge variant="outline" className={user.active ? TONES.ok : TONES.muted}>{user.active ? "Activo" : "Inactivo"}</Badge></p>
        <div className="mt-2 flex flex-wrap gap-1">{user.profiles.length ? user.profiles.map((profile) => <Badge key={profile} variant="outline" className="border-slate-300 bg-white text-slate-800">{profileLabel(profile)}</Badge>) : <span className="text-xs text-slate-600">Sin perfil activo</span>}</div>
        <p className="mt-3 text-xs text-slate-600">Aquí solo se administra el acceso por sector (<b>dónde</b> puede trabajar). Los perfiles y permisos (<b>qué</b> puede hacer) y el estado operativo de los sectores no se editan desde esta pantalla.</p>
        {block && <div className="mt-4"><AdminNotice title={BLOCK_TITLES[block]} text={blockMessage(block)}/></div>}

        <h3 className="mt-5 font-black">Sectores concedidos</h3>
        {(detail.status === "idle" || detail.status === "loading") && <div role="status" aria-live="polite" className="mt-3 space-y-2"><Skeleton className="h-14 w-full"/><span className="text-xs text-slate-600">Consultando las concesiones…</span></div>}
        {detail.status === "error" && <div className="mt-3"><AdminNotice title="No se pudieron cargar las concesiones" text={FAILURE_MESSAGES[detail.kind]} onRetry={onRetryDetail}/></div>}
        {detail.status === "ready" && (detail.data.sectors.length === 0
            ? <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-slate-700">Sin concesiones: este usuario no accede a ningún sector.</p>
            : <ul className="mt-3 space-y-2">{revocableSectors(detail.data.sectors).map((sector) => <SectorRow key={sector.code} sector={sector} action={
                <Button size="sm" variant="outline" disabled={blocked || detail.refreshing} aria-label={`Revocar acceso a ${sector.name}`} onClick={() => onRevoke(sector)}>Revocar</Button>}/>)}</ul>)}

        <h3 className="mt-6 font-black">Sectores disponibles</h3>
        {(catalog.status === "idle" || catalog.status === "loading") && <div role="status" aria-live="polite" className="mt-3 space-y-2"><Skeleton className="h-14 w-full"/><span className="text-xs text-slate-600">Consultando el catálogo central…</span></div>}
        {catalog.status === "error" && <div className="mt-3"><AdminNotice title="No se pudo cargar el catálogo de sectores" text={FAILURE_MESSAGES[catalog.kind]} onRetry={onRetryCatalog}/></div>}
        {catalog.status === "ready" && detail.status === "ready" && <AvailableSectors catalog={catalog.data} granted={detail.data.sectors} blocked={blocked || detail.refreshing} onGrant={onGrant}/>}
        {catalog.status === "ready" && detail.status !== "ready" && <p className="mt-3 text-xs text-slate-600">Las acciones de concesión se habilitan cuando se cargan las concesiones actuales.</p>}
    </section>;
}

function AvailableSectors({ catalog, granted, blocked, onGrant }: { catalog: AdminSector[]; granted: AdminSector[]; blocked: boolean; onGrant: (sector: AdminSector) => void }) {
    const grantable = grantableSectors(catalog, granted);
    const heldCodes = new Set(granted.map((sector) => sector.code));
    const inactive = catalog.filter((sector) => !sector.active && !heldCodes.has(sector.code));
    if (catalog.length === 0) return <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-slate-700">Sin sectores disponibles: el catálogo central no tiene sectores.</p>;
    return <>
        {grantable.length === 0 ? <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-slate-700">Sin sectores disponibles para conceder: el usuario ya tiene todos los sectores activos del catálogo.</p>
            : <ul className="mt-3 space-y-2">{grantable.map((sector) => <SectorRow key={sector.code} sector={sector} action={
                <Button size="sm" className="bg-[#146b4f]" disabled={blocked} aria-label={`Conceder acceso a ${sector.name}`} onClick={() => onGrant(sector)}>Conceder</Button>}/>)}</ul>}
        {inactive.length > 0 && <p className="mt-3 text-xs text-slate-600">Inactivos (no admiten nuevas concesiones): {inactive.map((sector) => `${sector.name} (${sector.code})`).join(", ")}.</p>}
    </>;
}

export function AdminChangeDialog({ state, onConfirm, onClose }: { state: ChangeState; onConfirm: () => void; onClose: () => void }) {
    const open = state.step !== "closed";
    const target: ChangeTarget | null = state.step === "closed" ? null : state.target;
    const text = target ? confirmationText(target) : null;
    const pending = state.step === "submitting";
    return <AlertDialog open={open} onOpenChange={(next) => { if (!next && !pending) onClose(); }}>
        <AlertDialogContent aria-busy={pending}>
            {target && text && (state.step === "confirming" || state.step === "submitting") && <>
                <AlertDialogHeader><AlertDialogTitle>{text.title}</AlertDialogTitle><AlertDialogDescription>{text.body}</AlertDialogDescription></AlertDialogHeader>
                {text.warning && <p role="note" className="rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">{text.warning}</p>}
                <AlertDialogFooter>
                    <Button variant="outline" disabled={pending} onClick={onClose}>Cancelar</Button>
                    <Button className={target.operation === "revoke" ? "bg-red-700 hover:bg-red-800" : "bg-[#146b4f]"} disabled={pending} onClick={onConfirm}>{pending ? "Aplicando…" : text.confirm}</Button>
                </AlertDialogFooter></>}
            {state.step === "done" && (() => {
                const result = resultText(state.change, state.target.userLabel);
                return <>
                    <AlertDialogHeader><AlertDialogTitle>{result.tone === "ok" ? "Cambio aplicado" : "Sin cambios"}</AlertDialogTitle><AlertDialogDescription>{result.text}</AlertDialogDescription></AlertDialogHeader>
                    {state.change.request_id && <details className="text-xs text-slate-600"><summary className="cursor-pointer">Detalle técnico</summary><p className="mt-1 break-all">Identificador de auditoría: {state.change.request_id}</p></details>}
                    <AlertDialogFooter><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></AlertDialogFooter></>;
            })()}
            {state.step === "failed" && <>
                <AlertDialogHeader><AlertDialogTitle>{state.failure.kind === "forbidden" ? BLOCK_TITLES.forbidden : state.failure.kind === "origin" ? BLOCK_TITLES.origin : state.failure.kind === "unavailable" ? "No se pudo confirmar el cambio" : "No se aplicó el cambio"}</AlertDialogTitle>
                    <AlertDialogDescription>{FAILURE_MESSAGES[state.failure.kind as AdminFailureKind]}</AlertDialogDescription></AlertDialogHeader>
                <AlertDialogFooter><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></AlertDialogFooter></>}
        </AlertDialogContent>
    </AlertDialog>;
}
