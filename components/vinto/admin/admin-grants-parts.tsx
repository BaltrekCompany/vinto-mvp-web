"use client";

import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AdminNotice, BadgeList } from "@/components/vinto/admin/admin-parts";
import { BLOCK_TITLES, FAILURE_MESSAGES, blockMessage, type AccessBlock, type AdminFailureKind, type AdminResource, type AdminUser } from "@/lib/vinto/admin";
import {
    NOT_EFFECTIVE_NOTICE, NO_POLICY_NOTE, SECTOR_NOT_GRANTED_NOTICE, actionsLocked, findMachine, formRows, grantConfirmationText, grantResultText, historyNotice, historyRows,
    inertText, machineGroups, notOfferedForms, type ChangeOperation, type FormRow, type FormsCatalog, type GrantChangeState, type MachineCatalog, type UserDetail, type UserGrants,
} from "@/lib/vinto/admin-grants";

// Componentes de presentación de «Máquinas y formularios». No hacen peticiones ni guardan nada: reciben recursos ya validados. Ninguna concesión se presenta como acceso
// operativo efectivo (todavía no se aplican a las capturas) y las acciones solo se ofrecen cuando las reglas puras de lib/vinto/admin-grants.ts las permiten.

export type GrantsPanelProps = {
    detail: AdminResource<UserDetail>; catalog: AdminResource<MachineCatalog>; forms: AdminResource<FormsCatalog>; grants: AdminResource<UserGrants>; history: AdminResource<UserGrants>;
    machineCode: string | null; onSelectMachine: (code: string) => void; block: AccessBlock; uncertain: boolean; feedback: { tone: "ok" | "info"; text: string } | null;
    onOpen: (operation: ChangeOperation, row: FormRow, machine: { code: string; name: string }) => void;
    onRetryDetail: () => void; onRetryCatalog: () => void; onRetryForms: () => void; onRetryGrants: () => void; onRetryHistory: () => void;
};

function Loading({ label }: { label: string }) {
    return <div role="status" aria-live="polite" className="mt-3 space-y-2"><Skeleton className="h-14 w-full"/><span className="text-xs text-slate-600">{label}</span></div>;
}

function ResourceGate({ view, title, label, onRetry }: { view: AdminResource<unknown>; title: string; label: string; onRetry: () => void }) {
    if (view.status === "idle" || view.status === "loading") return <Loading label={label}/>;
    if (view.status === "error") return <div className="mt-3"><AdminNotice title={title} text={FAILURE_MESSAGES[view.kind]} onRetry={onRetry}/></div>;
    return null;
}

function RowBadges({ row }: { row: FormRow }) {
    return <div className="mt-1 flex flex-wrap gap-1"><BadgeList badges={row.badges}/></div>;
}

function FormRowItem({ row, machine, locked, onOpen }: { row: FormRow; machine: { code: string; name: string }; locked: boolean; onOpen: (operation: ChangeOperation, row: FormRow) => void }) {
    return <li className="rounded-xl border p-3" data-form={row.code}>
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0"><b>{row.code}</b>{row.name && <span className="text-sm text-slate-700"> · {row.name}</span>}{row.area && <span className="ml-2 text-xs text-slate-600">área: {row.area}</span>}<RowBadges row={row}/></div>
            <div className="flex gap-2">
                {row.canGrant && <Button size="sm" className="bg-[#146b4f]" disabled={locked} aria-label={`Conceder ${row.code} en ${machine.code}`} onClick={() => onOpen("grant", row)}>Conceder</Button>}
                {row.canRevoke && <Button size="sm" variant="outline" disabled={locked} aria-label={`Revocar ${row.code} en ${machine.code}`} onClick={() => onOpen("revoke", row)}>Revocar</Button>}
            </div>
        </div>
        {row.inert.length > 0 && <p role="note" className="mt-2 text-xs font-semibold text-amber-950">{inertText(row.inert)}</p>}
        {!row.enabledForCapture && row.offered && <p className="mt-2 text-xs text-slate-700">{NO_POLICY_NOTE}</p>}
        {row.grantBlockedReason && <p className="mt-2 text-xs text-slate-700">{row.grantBlockedReason}</p>}
    </li>;
}

function MachineForms({ catalog, forms, grants, detail, machineCode, locked, onOpen }: {
    catalog: MachineCatalog; forms: AdminResource<FormsCatalog>; grants: UserGrants; detail: UserDetail; machineCode: string | null; locked: boolean;
    onOpen: (operation: ChangeOperation, row: FormRow, machine: { code: string; name: string }) => void;
}) {
    const found = findMachine(catalog, machineCode);
    if (machineCode === null) return <div className="rounded-xl border border-dashed p-4 text-sm text-slate-700">Selecciona una máquina para ver sus formularios y las concesiones de este usuario.</div>;
    if (found === null) return <div className="rounded-xl border border-dashed p-4 text-sm text-slate-700">La máquina seleccionada ya no figura en el catálogo central. Selecciona otra.</div>;
    const { machine, sector } = found;
    const rows = formRows(machine, sector, grants.grants, { active: detail.active, sectors: detail.sectors });
    const sectorGranted = detail.sectors.some((granted) => granted.code === sector.code);
    const hidden = forms.status === "ready" ? notOfferedForms(forms.data.forms, machine.code) : null;
    return <div aria-label={`Formularios de ${machine.code}`} role="region">
        <h4 className="font-black">{machine.code}{machine.name !== machine.code ? ` · ${machine.name}` : ""}</h4>
        <p className="text-xs text-slate-600">Sector {sector.name} ({sector.code}) · {sector.operational ? "operativo" : "no operativo"}{machine.active ? "" : " · máquina inactiva"}</p>
        {!sectorGranted && <p role="note" className="mt-2 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">{SECTOR_NOT_GRANTED_NOTICE}</p>}
        {sectorGranted && !sector.operational && <p role="note" className="mt-2 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">El sector {sector.code} no está operativo: las concesiones de sus máquinas quedan inertes.</p>}
        {!detail.active && <p role="note" className="mt-2 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">El usuario está inactivo: las concesiones quedan inertes.</p>}
        {rows.length === 0 ? <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-slate-700">Esta máquina no tiene formularios ofrecidos por el catálogo vigente.</p>
            : <ul className="mt-3 space-y-2">{rows.map((row) => <FormRowItem key={row.key} row={row} machine={machine} locked={locked} onOpen={(operation, target) => onOpen(operation, target, machine)}/>)}</ul>}
        {forms.status === "ready" && hidden && hidden.length > 0 && <details className="mt-4 text-sm"><summary className="cursor-pointer font-semibold">No ofrecidos a esta máquina ({hidden.length})</summary>
            <ul className="mt-2 space-y-1 text-xs text-slate-700">{hidden.map((form) => <li key={form.code}><b>{form.code}</b>{form.name ? ` · ${form.name}` : ""}: {form.reason} No se puede conceder.</li>)}</ul></details>}
        {(forms.status === "idle" || forms.status === "loading") && <p className="mt-3 text-xs text-slate-600">Consultando los formularios publicados…</p>}
        {forms.status === "error" && <p className="mt-3 text-xs text-amber-950">No se pudo consultar el catálogo de formularios; las demás acciones siguen disponibles.</p>}
    </div>;
}

export function AdminGrantHistory({ history, onRetry }: { history: AdminResource<UserGrants>; onRetry: () => void }) {
    return <section aria-label="Historial de concesiones" className="mt-6">
        <h3 className="font-black">Historial de concesiones y revocaciones</h3>
        <ResourceGate view={history} title="No se pudo cargar el historial" label="Consultando el historial…" onRetry={onRetry}/>
        {history.status === "ready" && (history.data.grants.length === 0
            ? <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-slate-700">Sin historial: este usuario nunca tuvo concesiones de formularios por máquina.</p>
            : <>
                {historyNotice(history.data) && <p role="note" className="mt-2 text-xs text-slate-700">{historyNotice(history.data)}</p>}
                <div className="mt-3 overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Máquina</TableHead><TableHead>Formulario</TableHead><TableHead>Estado</TableHead><TableHead>Concedida</TableHead><TableHead>Concedió</TableHead><TableHead>Revocada</TableHead><TableHead>Revocó</TableHead></TableRow></TableHeader>
                    <TableBody>{historyRows(history.data.grants).map((row) => <TableRow key={row.id}>
                        <TableCell>{row.machine}</TableCell><TableCell>{row.form}</TableCell>
                        <TableCell><Badge variant="outline" className={row.state === "Activa" ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-slate-300 bg-slate-100 text-slate-700"}>{row.state}</Badge></TableCell>
                        <TableCell>{row.grantedAt}</TableCell><TableCell>{row.grantedBy}</TableCell><TableCell>{row.revokedAt}</TableCell><TableCell>{row.revokedBy}</TableCell></TableRow>)}</TableBody></Table></div>
            </>)}
    </section>;
}

export function AdminGrantsSection({ user, ...props }: GrantsPanelProps & { user: AdminUser }) {
    const { detail, catalog, forms, grants, history, machineCode, block, uncertain } = props;
    // Mientras no se hayan leído el detalle, el catálogo y las concesiones —o mientras se relee tras un cambio o un resultado incierto— no se ofrece ninguna acción.
    const locked = actionsLocked({ block, uncertain, views: [detail, catalog, grants] });
    const ready = detail.status === "ready" && catalog.status === "ready" && grants.status === "ready";
    return <section aria-label="Máquinas y formularios" className="rounded-2xl border bg-white p-5" data-section="grants">
        <h2 className="text-xl font-black">Máquinas y formularios</h2>
        <p className="text-sm text-slate-700">Acceso de <b>{user.display_name}</b> a formularios concretos de máquinas concretas. Es independiente de la administración por sector.</p>
        <p role="note" className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-800" data-notice="not-effective">{NOT_EFFECTIVE_NOTICE}</p>
        {block && <div className="mt-4"><AdminNotice title={BLOCK_TITLES[block]} text={blockMessage(block)}/></div>}
        {uncertain && <div className="mt-4"><AdminNotice title="No se pudo confirmar el último cambio" text="El resultado es incierto: se está consultando el estado real. Las acciones se habilitan cuando termine la consulta; no se asume que el cambio se aplicó ni que no se aplicó." onRetry={props.onRetryGrants} retryLabel="Consultar de nuevo"/></div>}
        {props.feedback && <p role="status" aria-live="polite" className={`mt-4 rounded-lg p-3 text-sm font-semibold ${props.feedback.tone === "ok" ? "bg-emerald-50 text-emerald-950" : "bg-slate-100 text-slate-900"}`}>{props.feedback.text}</p>}

        <ResourceGate view={detail} title="No se pudo cargar el usuario" label="Consultando el usuario…" onRetry={props.onRetryDetail}/>
        <ResourceGate view={catalog} title="No se pudo cargar el catálogo de máquinas" label="Consultando el catálogo de máquinas y formularios…" onRetry={props.onRetryCatalog}/>
        <ResourceGate view={grants} title="No se pudieron cargar las concesiones" label="Consultando las concesiones…" onRetry={props.onRetryGrants}/>

        {ready && <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
            <nav aria-label="Máquinas por sector" className="space-y-4">
                {machineGroups(catalog.data, grants.data.grants).map((sector) => <div key={sector.code}>
                    <h3 className="text-sm font-black">{sector.name} <span className="text-xs font-normal text-slate-600">({sector.code}){sector.operational ? "" : " · no operativo"}</span></h3>
                    <ul className="mt-2 space-y-2">{sector.machines.map((machine) => <li key={machine.code}>
                        <button type="button" aria-pressed={machine.code === machineCode} aria-label={`Seleccionar máquina ${machine.code}`} onClick={() => props.onSelectMachine(machine.code)}
                            className={`flex w-full items-center justify-between gap-2 rounded-xl border p-3 text-left text-sm ${machine.code === machineCode ? "border-[#146b4f] bg-emerald-50" : "bg-white hover:bg-slate-50"}`}>
                            <span><b>{machine.code}</b>{machine.name !== machine.code ? <span className="text-slate-700"> · {machine.name}</span> : null}{machine.active ? "" : <span className="ml-1 text-xs text-slate-600">(inactiva)</span>}</span>
                            <span className="text-xs text-slate-600">{machine.offered} ofrecidos · {machine.granted} concedidos</span></button></li>)}</ul></div>)}
            </nav>
            <div><MachineForms catalog={catalog.data} forms={forms} grants={grants.data} detail={detail.data} machineCode={machineCode} locked={locked} onOpen={props.onOpen}/></div>
        </div>}
        <AdminGrantHistory history={history} onRetry={props.onRetryHistory}/>
    </section>;
}

type DialogSlots = { Header: React.ElementType; Title: React.ElementType; Description: React.ElementType; Footer: React.ElementType };
const RADIX_SLOTS: DialogSlots = { Header: AlertDialogHeader, Title: AlertDialogTitle, Description: AlertDialogDescription, Footer: AlertDialogFooter };
// Ranuras simples para renderizar el cuerpo sin el portal de Radix (las pruebas de interfaz se ejecutan en el servidor, donde el portal no se monta).
export const PLAIN_SLOTS: DialogSlots = {
    Header: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>, Title: ({ children }: { children?: React.ReactNode }) => <h2>{children}</h2>,
    Description: ({ children }: { children?: React.ReactNode }) => <p>{children}</p>, Footer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
};

export function GrantDialogBody({ state, onConfirm, onClose, slots = RADIX_SLOTS }: { state: GrantChangeState; onConfirm: () => void; onClose: () => void; slots?: DialogSlots }) {
    const { Header, Title, Description, Footer } = slots;
    const target = state.step === "closed" ? null : state.target;
    const text = target ? grantConfirmationText(target) : null;
    const pending = state.step === "submitting";
    return <>
        {target && text && (state.step === "confirming" || state.step === "submitting") && <>
            <Header><Title>{text.title}</Title><Description>{text.body}</Description></Header>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">{text.lines.map((line) => <div key={line.label} className="contents"><dt className="font-semibold text-slate-700">{line.label}</dt><dd>{line.value}</dd></div>)}</dl>
            {text.warnings.map((warning) => <p key={warning} role="note" className="rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">{warning}</p>)}
            <Footer>
                <Button variant="outline" disabled={pending} onClick={onClose}>Cancelar</Button>
                <Button className={target.operation === "revoke" ? "bg-red-700 hover:bg-red-800" : "bg-[#146b4f]"} disabled={pending} onClick={onConfirm}>{pending ? "Aplicando…" : text.confirm}</Button>
            </Footer></>}
        {state.step === "done" && (() => {
            const result = grantResultText(state.change, state.target.userLabel, state.target.machineCode, state.target.formCode);
            return <>
                <Header><Title>{result.tone === "ok" ? "Cambio aplicado" : "Sin cambios"}</Title><Description>{result.text}</Description></Header>
                {result.warning && <p role="note" className="rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">{result.warning}</p>}
                {state.change.request_id && <details className="text-xs text-slate-600"><summary className="cursor-pointer">Detalle técnico</summary><p className="mt-1 break-all">Identificador de auditoría: {state.change.request_id}</p></details>}
                <Footer><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></Footer></>;
        })()}
        {state.step === "failed" && <>
            <Header><Title>{state.failure.kind === "forbidden" ? BLOCK_TITLES.forbidden : state.failure.kind === "origin" ? BLOCK_TITLES.origin
                : state.failure.kind === "unavailable" ? "No se pudo confirmar el cambio" : state.failure.kind === "pair_not_offered" ? "El par no se ofrece" : "No se aplicó el cambio"}</Title>
                <Description>{FAILURE_MESSAGES[state.failure.kind as AdminFailureKind]}</Description></Header>
            {state.failure.kind === "unavailable" && <p role="note" className="rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-950">El resultado es incierto: se vuelve a consultar el estado real antes de permitir otra acción.</p>}
            <Footer><Button className="bg-[#146b4f]" onClick={onClose}>Cerrar</Button></Footer></>}
    </>;
}

export function AdminGrantDialog({ state, onConfirm, onClose }: { state: GrantChangeState; onConfirm: () => void; onClose: () => void }) {
    const pending = state.step === "submitting";
    return <AlertDialog open={state.step !== "closed"} onOpenChange={(next) => { if (!next && !pending) onClose(); }}>
        <AlertDialogContent aria-busy={pending} data-dialog="grant"><GrantDialogBody state={state} onConfirm={onConfirm} onClose={onClose}/></AlertDialogContent>
    </AlertDialog>;
}
