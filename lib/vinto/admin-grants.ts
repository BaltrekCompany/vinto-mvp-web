// Administración de concesiones MÁQUINA-FORMULARIO (MF-13-01C.3): contratos, validadores, cliente HTTP, reglas de presentación y controlador de la operación.
// Todo es PURO e independiente de React y del DOM (el cliente recibe `fetch` y la URL base por parámetro) para poder probarlo con Node. Se apoya en lib/vinto/admin.ts: la misma
// petición administrativa (cookie de sesión HttpOnly, sin Origin, errores mapeados) y los mismos fallos; aquí no se duplica la autenticación.
// La autoridad es el backend (/api/admin, permiso user.manage). El frontend no decide quién está autorizado, no guarda nada, no envía actor_id, revoked_by ni request_id y no
// contiene listas de máquinas ni de formularios: todo sale de PostgreSQL a través de la API. NINGUNA concesión se presenta como acceso operativo efectivo: todavía no se aplican a las capturas.

import { createAdminRequester, isRecord, isUuid } from "./admin.ts";
import type { AdminFailure, AdminResource, AdminResult, AdminSector } from "./admin.ts";

export type ChangeOperation = "grant" | "revoke";
export type CatalogForm = {
    code: string; name: string | null; area: string | null; active: boolean; effective_version: number; published: true;
    capture_policies: string[]; offered: boolean; enabled_for_capture: boolean;
};
export type CatalogMachine = { code: string; name: string; active: boolean; forms: CatalogForm[] };
export type CatalogSector = { code: string; name: string; active: boolean; operational: boolean; machines: CatalogMachine[] };
export type MachineCatalog = { sectors: CatalogSector[] };
export type FormMachineLink = { code: string; sector_code: string; active: boolean; offered: boolean; enabled_for_capture: boolean };
export type FormCatalogEntry = {
    code: string; name: string | null; area: string | null; active: boolean; published: boolean; effective_version: number | null;
    capture_policies: string[]; enabled_for_capture: boolean; machines: FormMachineLink[];
};
export type FormsCatalog = { forms: FormCatalogEntry[] };
export type UserDetail = {
    id: string; username: string | null; display_name: string; active: boolean; profiles: { code: string; name: string }[]; permissions: string[]; sectors: AdminSector[];
};
export type PersonRef = { id: string; display_name: string };
export type GrantCatalogStatus = { published_version: number | null; offered: boolean; enabled_for_capture: boolean; capture_policies: string[] };
export type GrantRow = {
    id: string; state: "active" | "revoked"; machine: { code: string; name: string | null; sector_code: string | null }; form: { code: string; name: string | null; area: string | null };
    granted_at: string; granted_by: PersonRef | null; revoked_at: string | null; revoked_by: PersonRef | null; catalog: GrantCatalogStatus;
};
export type UserGrants = { user_id: string; total: number; truncated: boolean; grants: GrantRow[] };
export type GrantContext = { user_active: boolean; sector_code: string | null; sector_granted: boolean; sector_operational: boolean };
export type GrantChange = {
    user_id: string; machine_code: string; form_code: string; operation: ChangeOperation; changed: boolean; active: boolean; request_id: string | null;
    grant: GrantRow | null; catalog: GrantCatalogStatus; context: GrantContext;
};

// Historial: se pide este número de filas; el endpoint admite 1-500 y informa `truncated` cuando recorta.
export const HISTORY_LIMIT = 200;

const SECTOR_CODE = /^[A-Z][A-Z0-9_]{0,31}$/;
const MACHINE_CODE = /^[A-Z0-9][A-Z0-9_]{0,63}$/; // misma forma que valida el backend; la EXISTENCIA la decide PostgreSQL
const FORM_CODE = /^[A-Z][A-Z0-9_-]{0,63}$/;
const POLICY_CODE = /^[a-z][a-z0-9_]{0,63}$/;
const AREA = /^[a-z][a-z_]{0,31}$/;
const isText = (value: unknown): value is string => typeof value === "string" && value !== "";
const isBool = (value: unknown): value is boolean => typeof value === "boolean";
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const optText = (value: unknown): string | null | undefined => (value === null ? null : typeof value === "string" ? value : undefined);
const optArea = (value: unknown): string | null | undefined => (value === null ? null : typeof value === "string" && AREA.test(value) ? value : undefined);
const isInstant = (value: unknown): value is string => typeof value === "string" && value !== "" && !Number.isNaN(Date.parse(value));

function policyList(value: unknown): string[] | null {
    if (!Array.isArray(value)) return null;
    const list: string[] = [];
    for (const item of value) {
        if (typeof item !== "string" || !POLICY_CODE.test(item) || list.includes(item)) return null;
        list.push(item);
    }
    return list;
}

function unique<T>(items: T[], key: (item: T) => string): boolean {
    return new Set(items.map(key)).size === items.length;
}

// ---- validadores (devuelven una copia limpia o null; las inconsistencias entre campos invalidan toda la respuesta) -----------------------------------

function parseCatalogForm(payload: unknown): CatalogForm | null {
    if (!isRecord(payload)) return null;
    const name = optText(payload.name), area = optArea(payload.area), policies = policyList(payload.capture_policies);
    if (typeof payload.code !== "string" || !FORM_CODE.test(payload.code) || name === undefined || area === undefined || policies === null) return null;
    const { active, published, offered, enabled_for_capture: enabled, effective_version: version } = payload;
    if (!isBool(active) || published !== true || !isBool(offered) || !isBool(enabled) || typeof version !== "number" || !Number.isSafeInteger(version) || version < 1) return null;
    if (offered && !active) return null; // un formulario inactivo no se ofrece
    if (enabled && (!offered || policies.length === 0)) return null; // habilitado para captura implica ofrecido y con una política que lo acepta
    return { code: payload.code, name, area, active, effective_version: version, published: true, capture_policies: policies, offered, enabled_for_capture: enabled };
}

function parseCatalogMachine(payload: unknown): CatalogMachine | null {
    if (!isRecord(payload)) return null;
    if (typeof payload.code !== "string" || !MACHINE_CODE.test(payload.code) || !isText(payload.name) || !isBool(payload.active) || !Array.isArray(payload.forms)) return null;
    const forms: CatalogForm[] = [];
    for (const item of payload.forms) {
        const form = parseCatalogForm(item);
        if (form === null) return null;
        forms.push(form);
    }
    if (!unique(forms, (form) => form.code)) return null;
    if (!payload.active && forms.some((form) => form.offered)) return null; // una máquina inactiva no ofrece nada
    return { code: payload.code, name: payload.name, active: payload.active, forms };
}

export function parseMachineCatalog(payload: unknown): MachineCatalog | null {
    if (!isRecord(payload) || !Array.isArray(payload.sectors)) return null;
    const sectors: CatalogSector[] = [];
    for (const item of payload.sectors) {
        if (!isRecord(item) || typeof item.code !== "string" || !SECTOR_CODE.test(item.code) || !isText(item.name) || !isBool(item.active) || !isBool(item.operational) || !Array.isArray(item.machines)) return null;
        if (item.operational && !item.active) return null;
        const machines: CatalogMachine[] = [];
        for (const raw of item.machines) {
            const machine = parseCatalogMachine(raw);
            if (machine === null) return null;
            if (!item.active && machine.forms.some((form) => form.offered)) return null; // un sector inactivo no ofrece nada
            if (!item.operational && machine.forms.some((form) => form.enabled_for_capture)) return null; // habilitado para captura exige sector operativo
            machines.push(machine);
        }
        sectors.push({ code: item.code, name: item.name, active: item.active, operational: item.operational, machines });
    }
    if (!unique(sectors, (sector) => sector.code)) return null;
    if (!unique(sectors.flatMap((sector) => sector.machines), (machine) => machine.code)) return null; // un código de máquina pertenece a un solo sector
    return { sectors };
}

export function parseFormsCatalog(payload: unknown): FormsCatalog | null {
    if (!isRecord(payload) || !Array.isArray(payload.forms)) return null;
    const forms: FormCatalogEntry[] = [];
    for (const item of payload.forms) {
        if (!isRecord(item) || typeof item.code !== "string" || !FORM_CODE.test(item.code)) return null;
        const name = optText(item.name), area = optArea(item.area), policies = policyList(item.capture_policies);
        const { active, published, enabled_for_capture: enabled, effective_version: version } = item;
        if (name === undefined || area === undefined || policies === null || !isBool(active) || !isBool(published) || !isBool(enabled) || !Array.isArray(item.machines)) return null;
        if (published !== (version !== null) || (version !== null && (typeof version !== "number" || !Number.isSafeInteger(version) || version < 1))) return null; // publicado <=> hay versión vigente
        const machines: FormMachineLink[] = [];
        for (const raw of item.machines) {
            if (!isRecord(raw) || typeof raw.code !== "string" || !MACHINE_CODE.test(raw.code) || typeof raw.sector_code !== "string" || !SECTOR_CODE.test(raw.sector_code)) return null;
            if (!isBool(raw.active) || !isBool(raw.offered) || !isBool(raw.enabled_for_capture)) return null;
            if (raw.enabled_for_capture && !raw.offered) return null;
            machines.push({ code: raw.code, sector_code: raw.sector_code, active: raw.active, offered: raw.offered, enabled_for_capture: raw.enabled_for_capture });
        }
        if (!unique(machines, (machine) => machine.code)) return null;
        if (!published && (machines.length > 0 || enabled)) return null; // sin versión publicada vigente no hay vínculos ni captura
        if (enabled !== machines.some((machine) => machine.enabled_for_capture)) return null; // habilitado = habilitado en alguna máquina
        forms.push({ code: item.code, name, area, active, published, effective_version: version as number | null, capture_policies: policies, enabled_for_capture: enabled, machines });
    }
    return unique(forms, (form) => form.code) ? { forms } : null;
}

export function parseUserDetail(payload: unknown): UserDetail | null {
    if (!isRecord(payload) || !isUuid(payload.id) || !isText(payload.display_name) || !isBool(payload.active)) return null;
    const username = optText(payload.username);
    if (username === undefined || !Array.isArray(payload.profiles) || !Array.isArray(payload.permissions) || !Array.isArray(payload.sectors)) return null;
    const profiles: { code: string; name: string }[] = [];
    for (const profile of payload.profiles) {
        if (!isRecord(profile) || !isText(profile.code) || !isText(profile.name) || profiles.some((known) => known.code === profile.code)) return null;
        profiles.push({ code: profile.code, name: profile.name });
    }
    if (!payload.permissions.every((permission) => typeof permission === "string")) return null;
    const sectors: AdminSector[] = [];
    for (const raw of payload.sectors) {
        if (!isRecord(raw) || typeof raw.code !== "string" || !SECTOR_CODE.test(raw.code) || !isText(raw.name) || !isBool(raw.active) || !isBool(raw.operational)) return null;
        if (raw.operational && !raw.active) return null;
        if (sectors.some((known) => known.code === raw.code)) return null;
        sectors.push({ code: raw.code, name: raw.name, active: raw.active, operational: raw.operational });
    }
    return { id: payload.id, username, display_name: payload.display_name, active: payload.active, profiles, permissions: [...payload.permissions] as string[], sectors };
}

function parsePerson(value: unknown): PersonRef | null | undefined {
    if (value === null) return null;
    return isRecord(value) && isUuid(value.id) && isText(value.display_name) ? { id: value.id, display_name: value.display_name } : undefined;
}

function parseGrantStatus(value: unknown): GrantCatalogStatus | null {
    if (!isRecord(value)) return null;
    const policies = policyList(value.capture_policies), version = value.published_version;
    if (policies === null || !isBool(value.offered) || !isBool(value.enabled_for_capture)) return null;
    if (version !== null && (typeof version !== "number" || !Number.isSafeInteger(version) || version < 1)) return null;
    if (value.enabled_for_capture && !value.offered) return null; // habilitado implica ofrecido
    if (value.offered && version === null) return null; // ofrecido implica una versión publicada vigente
    return { published_version: version as number | null, offered: value.offered, enabled_for_capture: value.enabled_for_capture, capture_policies: policies };
}

export function parseGrantRow(payload: unknown): GrantRow | null {
    if (!isRecord(payload) || !isUuid(payload.id) || (payload.state !== "active" && payload.state !== "revoked")) return null;
    const { machine, form } = payload;
    if (!isRecord(machine) || typeof machine.code !== "string" || !MACHINE_CODE.test(machine.code) || optText(machine.name) === undefined || optText(machine.sector_code) === undefined) return null;
    if (!isRecord(form) || typeof form.code !== "string" || !FORM_CODE.test(form.code) || optText(form.name) === undefined || optArea(form.area) === undefined) return null;
    const grantedBy = parsePerson(payload.granted_by), revokedBy = parsePerson(payload.revoked_by), status = parseGrantStatus(payload.catalog);
    if (grantedBy === undefined || revokedBy === undefined || status === null || !isInstant(payload.granted_at)) return null;
    const revokedAt = payload.revoked_at;
    if (revokedAt !== null && !isInstant(revokedAt)) return null;
    if (payload.state === "active" && (revokedAt !== null || revokedBy !== null)) return null; // una concesión activa no tiene revocación
    if (payload.state === "revoked" && (revokedAt === null || revokedBy === null)) return null; // toda revocación está fechada y atribuida
    return {
        id: payload.id, state: payload.state, machine: { code: machine.code, name: optText(machine.name) as string | null, sector_code: optText(machine.sector_code) as string | null },
        form: { code: form.code, name: optText(form.name) as string | null, area: optArea(form.area) as string | null }, granted_at: payload.granted_at, granted_by: grantedBy,
        revoked_at: revokedAt as string | null, revoked_by: revokedBy, catalog: status,
    };
}

export function parseUserGrants(payload: unknown): UserGrants | null {
    if (!isRecord(payload) || !isUuid(payload.user_id) || !isCount(payload.total) || !isBool(payload.truncated) || !Array.isArray(payload.grants)) return null;
    const grants: GrantRow[] = [];
    for (const item of payload.grants) {
        const grant = parseGrantRow(item);
        if (grant === null) return null;
        grants.push(grant);
    }
    if (!unique(grants, (grant) => grant.id)) return null;
    if (payload.truncated ? payload.total <= grants.length : payload.total !== grants.length) return null; // `truncated` solo si hay más filas de las devueltas
    return { user_id: payload.user_id, total: payload.total, truncated: payload.truncated, grants };
}

export function parseGrantChange(payload: unknown): GrantChange | null {
    if (!isRecord(payload) || !isUuid(payload.user_id)) return null;
    const { machine_code, form_code, operation, changed, active, request_id } = payload;
    if (typeof machine_code !== "string" || !MACHINE_CODE.test(machine_code) || typeof form_code !== "string" || !FORM_CODE.test(form_code)) return null;
    if ((operation !== "grant" && operation !== "revoke") || !isBool(changed) || !isBool(active)) return null;
    if (request_id !== null && !isText(request_id)) return null;
    if (changed !== (request_id !== null)) return null; // un cambio efectivo trae su identificador de auditoría; uno idempotente, no
    if (active !== (operation === "grant")) return null; // el estado resultante corresponde a la operación
    let grant: GrantRow | null = null;
    if (payload.grant !== null) {
        grant = parseGrantRow(payload.grant);
        if (grant === null) return null; // fila presente pero inválida: respuesta inválida (null solo es válido si el servidor dijo que nunca existió)
    }
    const status = parseGrantStatus(payload.catalog), context = payload.context;
    if (status === null || !isRecord(context)) return null;
    if (!isBool(context.user_active) || optText(context.sector_code) === undefined || !isBool(context.sector_granted) || !isBool(context.sector_operational)) return null;
    if (grant !== null) {
        if (grant.machine.code !== machine_code || grant.form.code !== form_code) return null;
        if ((grant.state === "active") !== active) return null; // la fila más reciente es la activa si y solo si queda concesión activa
    } else if (active) return null;
    return { user_id: payload.user_id, machine_code, form_code, operation, changed, active, request_id, grant, catalog: status,
        context: { user_active: context.user_active, sector_code: optText(context.sector_code) as string | null, sector_granted: context.sector_granted, sector_operational: context.sector_operational } };
}

// ---- cliente HTTP (reutiliza la petición administrativa de admin.ts) --------------------------------------------------------------------------------

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export type GrantsClient = {
    getMachineCatalog: (signal?: AbortSignal) => Promise<AdminResult<MachineCatalog>>;
    getFormsCatalog: (signal?: AbortSignal) => Promise<AdminResult<FormsCatalog>>;
    getUserDetail: (userId: string, signal?: AbortSignal) => Promise<AdminResult<UserDetail>>;
    getUserGrants: (userId: string, signal?: AbortSignal) => Promise<AdminResult<UserGrants>>;
    getUserGrantsHistory: (userId: string, signal?: AbortSignal) => Promise<AdminResult<UserGrants>>;
    changeGrant: (operation: ChangeOperation, userId: string, machineCode: string, formCode: string, signal?: AbortSignal) => Promise<AdminResult<GrantChange>>;
};

export function createGrantsClient(baseUrl: () => string, fetchImpl: FetchLike): GrantsClient {
    const request = createAdminRequester(baseUrl, fetchImpl);
    const invalid = (): AdminResult<never> => ({ ok: false, kind: "invalid", status: 0 }); // identificadores mal formados: ni siquiera se envía la petición
    const forUser = <T>(userId: string, suffix: string, signal: AbortSignal | undefined, parse: (payload: unknown) => T | null): Promise<AdminResult<T>> =>
        (isUuid(userId) ? request(`/api/admin/users/${userId}${suffix}`, { signal }, parse) : Promise.resolve(invalid()));
    return {
        getMachineCatalog: (signal) => request("/api/admin/catalog", { signal }, parseMachineCatalog),
        getFormsCatalog: (signal) => request("/api/admin/catalog/forms", { signal }, parseFormsCatalog),
        getUserDetail: (userId, signal) => forUser(userId, "", signal, (payload) => { const detail = parseUserDetail(payload); return detail && detail.id.toLowerCase() === userId.toLowerCase() ? detail : null; }),
        getUserGrants: (userId, signal) => forUser(userId, "/grants", signal, (payload) => { const grants = parseUserGrants(payload); return grants && grants.user_id.toLowerCase() === userId.toLowerCase() ? grants : null; }),
        getUserGrantsHistory: (userId, signal) => forUser(userId, `/grants/history?limit=${HISTORY_LIMIT}`, signal, (payload) => { const grants = parseUserGrants(payload); return grants && grants.user_id.toLowerCase() === userId.toLowerCase() ? grants : null; }),
        changeGrant: (operation, userId, machineCode, formCode, signal) => {
            if (!isUuid(userId) || !MACHINE_CODE.test(machineCode) || !FORM_CODE.test(formCode)) return Promise.resolve(invalid());
            // El cuerpo lleva SOLO machine_code y form_code: el actor es la sesión, el usuario va en la ruta y el request_id lo genera el servidor.
            return request(`/api/admin/users/${userId}/grants/${operation}`, { method: "POST", body: { machine_code: machineCode, form_code: formCode }, signal }, (payload) => {
                const change = parseGrantChange(payload);
                // la respuesta debe corresponder exactamente a lo solicitado
                return change && change.user_id.toLowerCase() === userId.toLowerCase() && change.machine_code === machineCode && change.form_code === formCode && change.operation === operation ? change : null;
            });
        },
    };
}

// ---- reglas de presentación -------------------------------------------------------------------------------------------------------------------------

export type Badge = { text: string; tone: "ok" | "warn" | "muted" };
export const pairKey = (machineCode: string, formCode: string): string => `${machineCode}|${formCode}`;

export const POLICY_LABELS: Record<string, string> = {
    production_central: "Captura central de producción",
    quality_by_bobbin: "Control de Calidad por bobina",
    quality_by_machine: "Control de Calidad por máquina",
};
export const policyLabel = (code: string): string => POLICY_LABELS[code] ?? code;

// `enabled_for_capture: false` NO es una prueba de que el formulario no exista: puede registrarse por una ruta especializada (p. ej. el registro de bobinas). Solo dice que ninguna
// política de captura CENTRAL lo acepta hoy.
export const NO_POLICY_NOTE = "Ninguna política de captura central lo acepta hoy. Eso no significa que el formulario no exista: puede registrarse por otra ruta especializada (por ejemplo, el registro de bobinas).";
export const NOT_EFFECTIVE_NOTICE = "Las concesiones por máquina y formulario se registran, se auditan y determinan qué formularios ve el usuario en la interfaz. Que el servidor rechace una captura sin concesión todavía no depende de ellas: solo ocurre cuando la autorización efectiva (modo «enforce») está activada; mientras tanto la concesión no restringe la captura.";
export const SECTOR_NOT_GRANTED_NOTICE = "El usuario no tiene concedido el sector de esta máquina. Puedes conceder el formulario igualmente, pero quedará inerte: el sector NO se concede automáticamente (se administra en «Sectores»).";

export type InertReason = "user_inactive" | "sector_missing" | "sector_not_operational" | "pair_not_offered";
export const INERT_REASON_TEXT: Record<InertReason, string> = {
    user_inactive: "el usuario está inactivo",
    sector_missing: "el usuario no tiene concedido el sector de la máquina",
    sector_not_operational: "el sector de la máquina no está operativo",
    pair_not_offered: "el catálogo vigente ya no ofrece este formulario a la máquina",
};

// Una concesión es INERTE cuando falta alguna de las condiciones que la harían útil; sigue existiendo y siempre se puede revocar.
export function inertReasons(input: { userActive: boolean; grantedSectors: readonly { code: string }[]; sector: { code: string; active: boolean; operational: boolean } | null; offered: boolean }): InertReason[] {
    const reasons: InertReason[] = [];
    if (!input.userActive) reasons.push("user_inactive");
    if (input.sector === null || !input.grantedSectors.some((granted) => granted.code === input.sector?.code)) reasons.push("sector_missing");
    if (input.sector === null || !input.sector.active || !input.sector.operational) reasons.push("sector_not_operational");
    if (!input.offered) reasons.push("pair_not_offered");
    return reasons;
}
export const inertText = (reasons: readonly InertReason[]): string => (reasons.length === 0 ? "" : `Concesión inerte: ${reasons.map((reason) => INERT_REASON_TEXT[reason]).join("; ")}.`);

export type FormRow = {
    key: string; code: string; name: string | null; area: string | null; version: number | null; policies: string[]; offered: boolean; enabledForCapture: boolean; fromCatalog: boolean;
    grant: GrantRow | null; inert: InertReason[]; badges: Badge[]; canGrant: boolean; canRevoke: boolean; grantBlockedReason: string | null;
};

// Filas de una máquina: los formularios que la versión vigente le vincula MÁS las concesiones activas cuyo par ya no se ofrece (inertes pero revocables). Independiente por máquina:
// una concesión de otra máquina nunca aparece aquí aunque comparta el formulario (P1-01 en MP1 y en MP3 son filas distintas).
export function formRows(machine: { code: string; forms: readonly CatalogForm[] }, sector: { code: string; active: boolean; operational: boolean } | null,
    activeGrants: readonly GrantRow[], user: { active: boolean; sectors: readonly { code: string }[] }): FormRow[] {
    const mine = new Map(activeGrants.filter((grant) => grant.state === "active" && grant.machine.code === machine.code).map((grant) => [grant.form.code, grant]));
    const build = (code: string, name: string | null, area: string | null, version: number | null, policies: string[], offered: boolean, enabled: boolean, fromCatalog: boolean): FormRow => {
        const grant = mine.get(code) ?? null;
        const inert = grant ? inertReasons({ userActive: user.active, grantedSectors: user.sectors, sector, offered }) : [];
        const badges: Badge[] = [
            version === null ? { text: "Sin versión publicada", tone: "warn" } : { text: `Publicado v${version}`, tone: "ok" },
            offered ? { text: "Ofrecido a la máquina", tone: "ok" } : { text: "No ofrecido hoy", tone: "warn" },
            enabled ? { text: `Habilitado: ${policies.map(policyLabel).join(" · ")}`, tone: "ok" } : { text: "Sin política de captura central", tone: "muted" },
            grant ? (inert.length > 0 ? { text: "Concedido · inerte", tone: "warn" } : { text: "Concedido", tone: "ok" }) : { text: "No concedido", tone: "muted" },
        ];
        return { key: pairKey(machine.code, code), code, name, area, version, policies, offered, enabledForCapture: enabled, fromCatalog, grant, inert, badges,
            canGrant: offered && grant === null, canRevoke: grant !== null, grantBlockedReason: grant === null && !offered ? "No se puede conceder: el catálogo vigente no ofrece este formulario a la máquina." : null };
    };
    const rows = machine.forms.map((form) => build(form.code, form.name, form.area, form.effective_version, form.capture_policies, form.offered, form.enabled_for_capture, true));
    const listed = new Set(machine.forms.map((form) => form.code));
    for (const [code, grant] of mine) {
        if (!listed.has(code)) rows.push(build(code, grant.form.name, grant.form.area, grant.catalog.published_version, grant.catalog.capture_policies, false, false, false)); // concesión inerte heredada: revocable
    }
    return rows.sort((a, b) => a.code.localeCompare(b.code));
}

// Formularios que NO se pueden conceder a la máquina: publicados cuya versión vigente no la vincula, o sin versión publicada. Se muestran para distinguir «publicado» de «ofrecido».
export function notOfferedForms(forms: readonly FormCatalogEntry[], machineCode: string): { code: string; name: string | null; reason: string }[] {
    return forms.filter((form) => !form.machines.some((machine) => machine.code === machineCode)).map((form) => ({
        code: form.code, name: form.name,
        reason: form.published ? `Publicado (v${form.effective_version}), pero su versión vigente no lo vincula a esta máquina.` : "Sin versión publicada.",
    }));
}

export type MachineSummary = { code: string; name: string; active: boolean; offered: number; granted: number };
export type SectorGroup = { code: string; name: string; active: boolean; operational: boolean; machines: MachineSummary[] };
// Máquinas agrupadas por sector, con cuántos formularios ofrece cada una y cuántos tiene concedidos el usuario (solo informativo; no mezcla máquinas).
export function machineGroups(catalog: MachineCatalog, activeGrants: readonly GrantRow[]): SectorGroup[] {
    return catalog.sectors.map((sector) => ({
        code: sector.code, name: sector.name, active: sector.active, operational: sector.operational,
        machines: sector.machines.map((machine) => ({
            code: machine.code, name: machine.name, active: machine.active, offered: machine.forms.filter((form) => form.offered).length,
            granted: activeGrants.filter((grant) => grant.state === "active" && grant.machine.code === machine.code).length,
        })),
    }));
}

export function findMachine(catalog: MachineCatalog, code: string | null): { machine: CatalogMachine; sector: CatalogSector } | null {
    if (code === null) return null;
    for (const sector of catalog.sectors) {
        const machine = sector.machines.find((candidate) => candidate.code === code);
        if (machine) return { machine, sector };
    }
    return null;
}

// UTC y sin segundos: inequívoco y estable (no depende de la zona del navegador).
export const formatWhen = (iso: string | null): string => (iso === null || Number.isNaN(Date.parse(iso)) ? "—" : `${new Date(iso).toISOString().slice(0, 16).replace("T", " ")} UTC`);
export const personLabel = (person: PersonRef | null): string => (person ? person.display_name : "—");

export type HistoryRow = { id: string; machine: string; form: string; state: "Activa" | "Revocada"; grantedAt: string; grantedBy: string; revokedAt: string; revokedBy: string };
export function historyRows(grants: readonly GrantRow[]): HistoryRow[] {
    return grants.map((grant) => ({
        id: grant.id, machine: grant.machine.name && grant.machine.name !== grant.machine.code ? `${grant.machine.code} · ${grant.machine.name}` : grant.machine.code,
        form: grant.form.name ? `${grant.form.code} · ${grant.form.name}` : grant.form.code, state: grant.state === "active" ? "Activa" : "Revocada",
        grantedAt: formatWhen(grant.granted_at), grantedBy: personLabel(grant.granted_by), revokedAt: formatWhen(grant.revoked_at), revokedBy: personLabel(grant.revoked_by),
    }));
}
export const historyNotice = (history: UserGrants): string | null =>
    (history.truncated ? `Se muestran las ${history.grants.length} concesiones más recientes de ${history.total}. El historial completo existe en el servidor; los registros no se modifican ni se borran.` : null);

// ---- bloqueo de acciones, incertidumbre y refresco ---------------------------------------------------------------------------------------------------

// Tras un fallo de red / 503 NO se sabe si el servidor aplicó el cambio. Hasta releer el estado real, no se permite otra acción sobre ese usuario.
export type Uncertainty = { userId: string } | null;
export const markUncertain = (result: AdminResult<unknown>, userId: string): Uncertainty => (!result.ok && result.kind === "unavailable" ? { userId } : null);
// Se cierra solo con una relectura COMPLETA y correcta del usuario seleccionado; si cambia el usuario, la incertidumbre del anterior deja de aplicar.
export function nextUncertainty(previous: Uncertainty, selectedId: string | null, rereadOk: boolean): Uncertainty {
    if (previous === null || previous.userId !== selectedId) return null;
    return rereadOk ? null : previous;
}
export const isReread = (views: readonly { status: string; refreshing?: boolean }[]): boolean => views.every((view) => view.status === "ready" && view.refreshing === false);

// Qué lecturas se repiten tras un resultado: siempre las del usuario; si el par no se ofrece o algo no existe, también los catálogos.
export function refreshPlan(result: AdminResult<GrantChange>): { user: boolean; catalogs: boolean } {
    if (result.ok) return { user: true, catalogs: false };
    const catalogs = result.kind === "pair_not_offered" || result.kind === "machine_not_found" || result.kind === "form_not_found" || result.kind === "not_found";
    return { user: true, catalogs };
}

// El último resultado pertenece a UN usuario: si el administrador ya seleccionó a otro, no se muestra (una respuesta tardía no modifica la vista del usuario actual).
export type GrantFeedback = { owner: string; tone: "ok" | "info"; text: string };
export const visibleFeedback = (feedback: GrantFeedback | null, selectedId: string | null): { tone: "ok" | "info"; text: string } | null =>
    (feedback !== null && feedback.owner === selectedId ? { tone: feedback.tone, text: feedback.text } : null);

export function actionsLocked(input: { block: string | null; uncertain: boolean; views: readonly AdminResource<unknown>[] }): boolean {
    if (input.block !== null || input.uncertain) return true;
    return input.views.some((view) => view.status !== "ready" || view.refreshing);
}

// ---- operación de concesión / revocación (máquina de estados pura) -------------------------------------------------------------------------------------

export type GrantTarget = {
    operation: ChangeOperation; userId: string; userLabel: string; machineCode: string; machineName: string; formCode: string; formName: string | null; offered: boolean; inert: InertReason[];
    sectorGranted: boolean;
};
export type GrantChangeState =
    | { step: "closed" }
    | { step: "confirming"; target: GrantTarget }
    | { step: "submitting"; target: GrantTarget; token: number }
    | { step: "done"; target: GrantTarget; change: GrantChange }
    | { step: "failed"; target: GrantTarget; failure: AdminFailure };

export type GrantChangeAction =
    | { type: "open"; target: GrantTarget }
    | { type: "submit"; token: number }
    | { type: "resolved"; token: number; result: AdminResult<GrantChange> }
    | { type: "close" }
    | { type: "reset" };

export const GRANT_CLOSED: GrantChangeState = { step: "closed" };

// Reglas: nada se envía sin abrir y confirmar; "submit" solo es válido desde "confirming" (el segundo clic no hace nada); una respuesta tardía (otro token, diálogo cerrado) se
// ignora; mientras se envía no se puede cerrar ni abrir otro; jamás se ofrece conceder un par que no se ofrece.
export function grantChangeReducer(state: GrantChangeState, action: GrantChangeAction): GrantChangeState {
    switch (action.type) {
        case "open": {
            if (state.step === "submitting") return state;
            if (action.target.operation === "grant" && !action.target.offered) return state;
            return { step: "confirming", target: action.target };
        }
        case "submit":
            return state.step === "confirming" ? { step: "submitting", target: state.target, token: action.token } : state;
        case "resolved": {
            if (state.step !== "submitting" || state.token !== action.token) return state;
            return action.result.ok ? { step: "done", target: state.target, change: action.result.data } : { step: "failed", target: state.target, failure: action.result };
        }
        case "close":
            return state.step === "submitting" ? state : GRANT_CLOSED;
        case "reset":
            return GRANT_CLOSED;
    }
}

export function grantConfirmationText(target: GrantTarget): { title: string; lines: { label: string; value: string }[]; body: string; confirm: string; warnings: string[] } {
    const lines = [
        { label: "Usuario", value: target.userLabel },
        { label: "Máquina", value: target.machineName && target.machineName !== target.machineCode ? `${target.machineCode} · ${target.machineName}` : target.machineCode },
        { label: "Formulario", value: target.formName ? `${target.formCode} · ${target.formName}` : target.formCode },
        { label: "Operación", value: target.operation === "grant" ? "Conceder" : "Revocar" },
    ];
    const warnings: string[] = [];
    if (target.operation === "grant") {
        if (!target.sectorGranted) warnings.push(SECTOR_NOT_GRANTED_NOTICE);
        if (target.inert.length > 0) warnings.push(inertText(target.inert));
        warnings.push(NOT_EFFECTIVE_NOTICE);
        return { title: "Conceder acceso a un formulario", lines, body: "Se concederá el acceso a ese formulario SOLO en esa máquina. No se modifican otras máquinas ni otros formularios, ni los sectores ni el perfil del usuario.", confirm: "Conceder acceso", warnings };
    }
    if (target.inert.length > 0) warnings.push(inertText(target.inert));
    warnings.push("La revocación conserva el historial y queda auditada con tu usuario.");
    return { title: "Revocar acceso a un formulario", lines, body: "Se revocará el acceso a ese formulario SOLO en esa máquina. Las concesiones de otras máquinas no cambian y el registro anterior se conserva en el historial.", confirm: "Revocar acceso", warnings };
}

// Las mismas razones de inercia, a partir del contexto que informa el backend en la respuesta del cambio.
export function contextInert(change: Pick<GrantChange, "context" | "catalog">): InertReason[] {
    const reasons: InertReason[] = [];
    if (!change.context.user_active) reasons.push("user_inactive");
    if (!change.context.sector_granted) reasons.push("sector_missing");
    if (!change.context.sector_operational) reasons.push("sector_not_operational");
    if (!change.catalog.offered) reasons.push("pair_not_offered");
    return reasons;
}

export function grantResultText(change: GrantChange, label: string, machine: string, form: string): { tone: "ok" | "info"; text: string; warning: string | null } {
    const where = `${form} en ${machine}`;
    const inert = change.operation === "grant" && change.active ? contextInert(change) : [];
    const warning = inert.length > 0 ? inertText(inert) : null;
    if (change.operation === "grant") {
        if (!change.changed) return { tone: "info", text: `${label} ya tenía concedido ${where}. No se modificó nada.`, warning };
        return { tone: "ok", text: `Acceso concedido a ${label}: ${where}. Queda registrado; todavía no se aplica a las capturas.`, warning };
    }
    if (!change.changed) return { tone: "info", text: `${label} no tenía concedido ${where}. No se modificó nada.`, warning: null };
    return { tone: "ok", text: `Acceso revocado a ${label}: ${where}. El registro anterior se conserva en el historial.`, warning: null };
}

// ---- controlador de la operación (imperativo, sin React: lo usa el hook y lo prueban los tests) --------------------------------------------------------------

export type GrantChangeController = {
    readonly state: GrantChangeState;
    open: (target: GrantTarget) => void;
    close: () => void;
    reset: () => void;
    confirm: () => Promise<void>;
    dispose: () => void;
};

// Abrir el diálogo NO envía nada; solo confirm() envía, una sola vez (candado síncrono + reductor). La respuesta solo se aplica si sigue siendo la de ESTE envío. Tras CUALQUIER
// respuesta mientras el controlador sigue ACTIVO (incluso un fallo de red, cuyo resultado real se desconoce) se llama a onSettled para volver a leer la API central; el objetivo se
// captura al abrir, así que cambiar de máquina o de usuario después no puede desviar la operación. dispose() aborta la petición en vuelo y descarta cualquier resultado tardío.
export function createGrantChangeController(
    client: Pick<GrantsClient, "changeGrant">,
    onState: (state: GrantChangeState) => void,
    onSettled: (result: AdminResult<GrantChange>, target: GrantTarget) => void,
): GrantChangeController {
    let state: GrantChangeState = GRANT_CLOSED, tokens = 0, inFlight = false, disposed = false;
    const abort = new AbortController();
    const apply = (action: GrantChangeAction) => { const next = grantChangeReducer(state, action); if (next !== state) { state = next; if (!disposed) onState(state); } };
    return {
        get state() { return state; },
        open: (target) => apply({ type: "open", target }),
        close: () => apply({ type: "close" }),
        reset: () => apply({ type: "reset" }),
        dispose: () => { disposed = true; abort.abort(); },
        async confirm() {
            if (disposed || inFlight || state.step !== "confirming") return;
            inFlight = true;
            const token = ++tokens, { target } = state;
            apply({ type: "submit", token });
            let result: AdminResult<GrantChange>;
            try {
                result = await client.changeGrant(target.operation, target.userId, target.machineCode, target.formCode, abort.signal);
            } catch {
                result = { ok: false, kind: "unavailable", status: 0 };
            }
            inFlight = false;
            if (disposed) return;
            apply({ type: "resolved", token, result });
            onSettled(result, target);
        },
    };
}
