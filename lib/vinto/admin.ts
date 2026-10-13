// Administración de usuarios y concesiones por sector (M1-C2-b2): contratos, validadores, cliente HTTP, reglas de selección y mensajes.
// Todo es PURO e independiente de React y del DOM (el cliente recibe `fetch` y la URL base por parámetro) para poder probarlo con Node.
// La autoridad es el backend (/api/admin, permiso user.manage): aquí no se guarda nada y nunca se lee document.cookie ni se envía `Origin`
// (lo administra el navegador). Ningún cuerpo HTTP sin validar llega a la interfaz.

export type AdminSector = { code: string; name: string; active: boolean; operational: boolean };
export type AdminUser = { id: string; username: string | null; display_name: string; active: boolean; profiles: string[]; sectors: AdminSector[] };
export type UserSectors = { user_id: string; username: string | null; active: boolean; sectors: AdminSector[] };
export type ChangeOperation = "grant" | "revoke";
export type SectorChange = { user_id: string; sector_code: string; operation: ChangeOperation; changed: boolean; sector: AdminSector; granted_sectors: AdminSector[]; request_id: string | null };

// El backend devuelve como máximo 500 usuarios por petición (por defecto 200): pedimos el máximo y avisamos si podría haber más.
export const ADMIN_USERS_MAX = 500;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SECTOR_CODE = /^[A-Z][A-Z0-9_]{0,31}$/;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isUuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);

// ---- validadores (devuelven una copia limpia o null; nunca confían en la forma) ---------------------------------------------------

export function parseAdminSector(payload: unknown): AdminSector | null {
    if (!isRecord(payload)) return null;
    const { code, name, active, operational } = payload;
    if (typeof code !== "string" || !SECTOR_CODE.test(code) || typeof name !== "string" || !name) return null;
    if (typeof active !== "boolean" || typeof operational !== "boolean") return null;
    if (operational && !active) return null; // un sector inactivo jamás es operativo: una respuesta así es inconsistente
    return { code, name, active, operational };
}

function parseSectorList(payload: unknown): AdminSector[] | null {
    if (!Array.isArray(payload)) return null;
    const list: AdminSector[] = [];
    for (const item of payload) {
        const sector = parseAdminSector(item);
        if (sector === null || list.some((known) => known.code === sector.code)) return null; // código repetido: respuesta inválida
        list.push(sector);
    }
    return list;
}

const parseUsername = (value: unknown): string | null | undefined => (value === null ? null : typeof value === "string" ? value : undefined);

export function parseAdminUser(payload: unknown): AdminUser | null {
    if (!isRecord(payload)) return null;
    const { id, display_name, active, profiles } = payload;
    const username = parseUsername(payload.username);
    if (!isUuid(id) || username === undefined || typeof display_name !== "string" || typeof active !== "boolean") return null;
    if (!Array.isArray(profiles) || !profiles.every((profile) => typeof profile === "string")) return null;
    const sectors = parseSectorList(payload.sectors);
    return sectors === null ? null : { id, username, display_name, active, profiles: [...profiles], sectors };
}

export function parseAdminUsers(payload: unknown): AdminUser[] | null {
    if (!Array.isArray(payload)) return null;
    const users: AdminUser[] = [];
    for (const item of payload) {
        const user = parseAdminUser(item);
        if (user === null || users.some((known) => known.id === user.id)) return null;
        users.push(user);
    }
    return users;
}

export const parseAdminSectors = parseSectorList;

export function parseUserSectors(payload: unknown): UserSectors | null {
    if (!isRecord(payload)) return null;
    const username = parseUsername(payload.username);
    const sectors = parseSectorList(payload.sectors);
    if (!isUuid(payload.user_id) || username === undefined || typeof payload.active !== "boolean" || sectors === null) return null;
    return { user_id: payload.user_id, username, active: payload.active, sectors };
}

export function parseSectorChange(payload: unknown): SectorChange | null {
    if (!isRecord(payload)) return null;
    const { user_id, sector_code, operation, changed, request_id } = payload;
    if (!isUuid(user_id) || typeof sector_code !== "string" || !SECTOR_CODE.test(sector_code)) return null;
    if (operation !== "grant" && operation !== "revoke") return null;
    if (typeof changed !== "boolean") return null;
    if (request_id !== null && (typeof request_id !== "string" || !request_id)) return null;
    if (changed && request_id === null) return null; // un cambio efectivo siempre trae su identificador de auditoría
    if (!changed && request_id !== null) return null; // idempotente: no hay evento de auditoría
    const sector = parseAdminSector(payload.sector);
    const granted = parseSectorList(payload.granted_sectors);
    if (sector === null || granted === null || sector.code !== sector_code) return null;
    if (granted.some((item) => item.code === sector_code) !== (operation === "grant")) return null; // el estado final debe corresponder a la operación
    return { user_id, sector_code, operation, changed, sector, granted_sectors: granted, request_id };
}

// ---- fallos -----------------------------------------------------------------------------------------------------------------------

export type AdminFailureKind = "session" | "forbidden" | "origin" | "user_not_found" | "sector_not_found" | "not_found" | "unsupported" | "sector_inactive" | "invalid" | "unavailable";
export type AdminFailure = { ok: false; kind: AdminFailureKind; status: number; code?: string };
export type AdminResult<T> = { ok: true; data: T; status: number } | AdminFailure;

// Solo el código estable del backend (p. ej. SECTOR_INACTIVE), validado por forma; nunca el mensaje ni el cuerpo.
const CODE = /^[A-Z][A-Z_]{0,63}$/;

export function failureKind(status: number, code?: string): AdminFailureKind {
    if (status === 401) return "session"; // sesión vencida o ausente
    if (status === 403) return code === "ORIGIN_NOT_ALLOWED" ? "origin" : "forbidden"; // falta de permiso: nunca se atribuye a sesión vencida
    if (status === 404) return code === "USER_NOT_FOUND" ? "user_not_found" : code === "SECTOR_NOT_FOUND" ? "sector_not_found" : "not_found";
    if (status === 415) return "unsupported";
    if (status === 422) return code === "SECTOR_INACTIVE" ? "sector_inactive" : "invalid";
    return "unavailable"; // 0 (red), 5xx, 503 y cualquier otro estado: no se asume nada sobre el estado central
}

export const FAILURE_MESSAGES: Record<AdminFailureKind, string> = {
    session: "La sesión ya no es válida. Ingresa de nuevo.",
    forbidden: "No tienes permiso para administrar usuarios y sectores.",
    origin: "Esta dirección no está autorizada para administrar. Abre VINTO desde la dirección habitual.",
    user_not_found: "El usuario ya no existe.",
    sector_not_found: "El sector no existe en el catálogo central.",
    not_found: "El registro ya no existe.",
    unsupported: "El servidor rechazó el formato de la solicitud. Recarga la página e inténtalo de nuevo.",
    sector_inactive: "El sector está inactivo y no admite nuevas concesiones.",
    invalid: "La solicitud no es válida.",
    unavailable: "No se pudo conectar con el servidor. No se asume ningún cambio: vuelve a consultar.",
};

// ---- cliente HTTP (fetch y URL base inyectados) -----------------------------------------------------------------------------------

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export type AdminClient = {
    listUsers: (signal?: AbortSignal) => Promise<AdminResult<AdminUser[]>>;
    listSectors: (signal?: AbortSignal) => Promise<AdminResult<AdminSector[]>>;
    getUserSectors: (userId: string, signal?: AbortSignal) => Promise<AdminResult<UserSectors>>;
    changeSector: (operation: ChangeOperation, userId: string, sectorCode: string, signal?: AbortSignal) => Promise<AdminResult<SectorChange>>;
};

export function createAdminClient(baseUrl: () => string, fetchImpl: FetchLike): AdminClient {
    async function request<T>(path: string, init: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal }, parse: (payload: unknown) => T | null): Promise<AdminResult<T>> {
        let response: Response;
        try {
            response = await fetchImpl(`${baseUrl()}${path}`, {
                method: init.method ?? "GET",
                signal: init.signal,
                cache: "no-store",
                credentials: "include", // cookie de sesión HttpOnly: la envía el navegador; este código nunca la lee ni la guarda
                headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
                body: init.body === undefined ? undefined : JSON.stringify(init.body),
            });
        } catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") throw error; // el llamador descarta la petición obsoleta
            return { ok: false, kind: "unavailable", status: 0 };
        }
        let payload: unknown = null;
        try { payload = await response.json(); } catch { /* cuerpo vacío o inválido */ }
        if (!response.ok) {
            const code = isRecord(payload) && typeof payload.code === "string" && CODE.test(payload.code) ? payload.code : undefined;
            return { ok: false, kind: failureKind(response.status, code), status: response.status, code };
        }
        const data = parse(payload);
        return data === null ? { ok: false, kind: "unavailable", status: response.status } : { ok: true, data, status: response.status };
    }
    const invalid = (): AdminResult<never> => ({ ok: false, kind: "invalid", status: 0 }); // identificadores mal formados: ni siquiera se envía la petición
    return {
        listUsers: (signal) => request(`/api/admin/users?limit=${ADMIN_USERS_MAX}`, { signal }, parseAdminUsers),
        listSectors: (signal) => request("/api/admin/sectors", { signal }, parseAdminSectors),
        getUserSectors: (userId, signal) => (isUuid(userId) ? request(`/api/admin/users/${userId}/sectors`, { signal }, parseUserSectors) : Promise.resolve(invalid())),
        changeSector: (operation, userId, sectorCode, signal) => {
            if (!isUuid(userId) || !SECTOR_CODE.test(sectorCode)) return Promise.resolve(invalid());
            return request(`/api/admin/users/${userId}/sectors/${operation}`, { method: "POST", body: { sector_code: sectorCode }, signal }, (payload) => {
                const change = parseSectorChange(payload);
                // la respuesta debe corresponder exactamente a lo solicitado
                return change && change.user_id.toLowerCase() === userId.toLowerCase() && change.sector_code === sectorCode && change.operation === operation ? change : null;
            });
        },
    };
}

// ---- reglas de vista ------------------------------------------------------------------------------------------------------------------

// La autoridad es el permiso devuelto por /api/auth/me, nunca el nombre de un perfil.
export const canAdminister = (user: { permissions: readonly string[] } | null | undefined): boolean => user !== null && user !== undefined && user.permissions.includes("user.manage");

const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Búsqueda LOCAL: solo sobre los usuarios realmente recuperados (username, nombre visible y perfiles).
export function filterUsers(users: readonly AdminUser[], query: string): AdminUser[] {
    const terms = fold(query).split(/\s+/).filter(Boolean);
    if (terms.length === 0) return [...users];
    return users.filter((user) => {
        const haystack = fold([user.username ?? "", user.display_name, ...user.profiles, ...user.profiles.map((p) => p.replace(/_/g, " "))].join(" "));
        return terms.every((term) => haystack.includes(term));
    });
}

export const isLimited = (count: number): boolean => count >= ADMIN_USERS_MAX;

export type AdminSummary = { users: number; activeUsers: number; grants: number; operationalSectors: number; limited: boolean };
export function summarize(users: readonly AdminUser[], catalog: readonly AdminSector[]): AdminSummary {
    return {
        users: users.length,
        activeUsers: users.filter((user) => user.active).length,
        grants: users.reduce((total, user) => total + user.sectors.length, 0),
        operationalSectors: catalog.filter((sector) => sector.active && sector.operational).length,
        limited: isLimited(users.length),
    };
}

// Conceder: solo sectores del catálogo central que existan, estén ACTIVOS y no estén ya concedidos.
export function grantableSectors(catalog: readonly AdminSector[], granted: readonly AdminSector[]): AdminSector[] {
    const held = new Set(granted.map((sector) => sector.code));
    return catalog.filter((sector) => sector.active && !held.has(sector.code));
}

// Revocar: cualquier concesión actual, incluida la de un sector inactivo (para poder limpiar concesiones antiguas).
export const revocableSectors = (granted: readonly AdminSector[]): AdminSector[] => [...granted];

export type SectorBadge = { text: string; tone: "ok" | "warn" | "muted" };
// Concedido, activo y operativo son tres cosas distintas: una concesión sobre un sector no operativo es INERTE.
export function sectorBadges(sector: AdminSector): SectorBadge[] {
    return [
        { text: sector.active ? "Activo" : "Inactivo", tone: sector.active ? "ok" : "muted" },
        sector.operational ? { text: "Operativo", tone: "ok" } : { text: "No operativo", tone: "warn" },
    ];
}

export const INERT_NOTICE = "Este sector no está operativo: la concesión queda registrada pero no da acceso a nada hasta que el sector se habilite.";

// ---- operación de concesión / revocación (máquina de estados pura) ----------------------------------------------------------------

export type ChangeTarget = { operation: ChangeOperation; userId: string; userLabel: string; sector: AdminSector };
export type ChangeState =
    | { step: "closed" }
    | { step: "confirming"; target: ChangeTarget }
    | { step: "submitting"; target: ChangeTarget; token: number }
    | { step: "done"; target: ChangeTarget; change: SectorChange }
    | { step: "failed"; target: ChangeTarget; failure: AdminFailure };

export type ChangeAction =
    | { type: "open"; target: ChangeTarget }
    | { type: "submit"; token: number }
    | { type: "resolved"; token: number; result: AdminResult<SectorChange> }
    | { type: "close" }
    | { type: "reset" };

export const CLOSED: ChangeState = { step: "closed" };

// Reglas: nada se envía sin abrir y confirmar el diálogo; "submit" solo es válido desde "confirming" (el segundo clic no hace nada);
// una respuesta tardía (otro token, otro usuario, diálogo ya cerrado) se ignora; mientras se envía no se puede cerrar ni abrir otro.
export function changeReducer(state: ChangeState, action: ChangeAction): ChangeState {
    switch (action.type) {
        case "open": {
            if (state.step === "submitting") return state;
            const { target } = action;
            if (target.operation === "grant" && !target.sector.active) return state; // jamás se ofrece conceder un sector inactivo
            return { step: "confirming", target };
        }
        case "submit":
            return state.step === "confirming" ? { step: "submitting", target: state.target, token: action.token } : state;
        case "resolved": {
            if (state.step !== "submitting" || state.token !== action.token) return state;
            return action.result.ok ? { step: "done", target: state.target, change: action.result.data } : { step: "failed", target: state.target, failure: action.result };
        }
        case "close":
            return state.step === "submitting" ? state : CLOSED;
        case "reset":
            return CLOSED;
    }
}

export function confirmationText(target: ChangeTarget): { title: string; body: string; confirm: string; warning?: string } {
    const who = target.userLabel, what = `${target.sector.name} (${target.sector.code})`;
    if (target.operation === "grant") {
        return {
            title: "Conceder acceso a un sector",
            body: `Se concederá a ${who} el acceso al sector ${what}. El acceso real depende además de los permisos de su perfil y de que el sector esté operativo.`,
            confirm: "Conceder acceso",
            warning: target.sector.operational ? undefined : INERT_NOTICE,
        };
    }
    return {
        title: "Revocar acceso a un sector",
        body: `Se revocará a ${who} el acceso al sector ${what}. El efecto es inmediato: en su siguiente petición dejará de ver y operar en ese sector, aunque tenga la sesión abierta.`,
        confirm: "Revocar acceso",
        warning: "Esta acción queda auditada con tu usuario.",
    };
}

export function resultText(change: SectorChange, label: string): { tone: "ok" | "info"; text: string } {
    const sector = `${change.sector.name} (${change.sector.code})`;
    if (change.operation === "grant") {
        if (!change.changed) return { tone: "info", text: `${label} ya tenía acceso a ${sector}. No se modificó nada.` };
        return { tone: "ok", text: `Acceso concedido a ${label} en ${sector}.${change.sector.operational ? "" : " El sector no está operativo: la concesión es inerte."}` };
    }
    if (!change.changed) return { tone: "info", text: `${label} no tenía acceso a ${sector}. No se modificó nada.` };
    return { tone: "ok", text: `Acceso revocado a ${label} en ${sector}. Rige desde su siguiente petición.` };
}

export const userLabel = (user: { username: string | null; display_name: string }): string => user.display_name || user.username || "Usuario";

// ---- controlador de la operación (imperativo, sin React: lo usa el hook y lo prueban los tests) ----------------------------------------------

export type ChangeController = {
    readonly state: ChangeState;
    open: (target: ChangeTarget) => void;
    close: () => void;
    reset: () => void;
    confirm: () => Promise<void>;
    dispose: () => void;
};

// Abrir el diálogo NO envía nada; solo confirm() envía, una sola vez (candado síncrono + reductor). La respuesta solo se aplica si sigue siendo la de ESTE envío;
// después de CUALQUIER respuesta mientras el controlador sigue ACTIVO (incluso un fallo de red, cuyo resultado real se desconoce) se llama a onSettled para volver a leer la API central.
// dispose() (desmontaje, cierre de sesión): el controlador deja de existir. Se aborta la petición en vuelo, pero abortar un POST NO garantiza que el servidor no lo haya
// ejecutado (puede haberse aplicado en PostgreSQL); por eso un controlador liberado ignora por completo cualquier resultado tardío —ni estado ni onSettled—, de modo que un 401
// de la sesión anterior jamás puede cerrar una sesión posterior. La consola nueva lee de nuevo la API central y refleja lo que realmente ocurrió.
export function createChangeController(
    client: Pick<AdminClient, "changeSector">,
    onState: (state: ChangeState) => void,
    onSettled: (result: AdminResult<SectorChange>) => void,
): ChangeController {
    let state: ChangeState = CLOSED, tokens = 0, inFlight = false, disposed = false;
    const abort = new AbortController();
    const apply = (action: ChangeAction) => { const next = changeReducer(state, action); if (next !== state) { state = next; if (!disposed) onState(state); } };
    return {
        get state() { return state; },
        open: (target) => apply({ type: "open", target }),
        close: () => apply({ type: "close" }),
        reset: () => apply({ type: "reset" }),
        dispose: () => { disposed = true; abort.abort(); },
        async confirm() {
            if (disposed || inFlight || state.step !== "confirming") return; // liberado, doble clic o diálogo no confirmable: no hace nada
            inFlight = true;
            const token = ++tokens, { target } = state;
            apply({ type: "submit", token });
            let result: AdminResult<SectorChange>;
            try {
                result = await client.changeSector(target.operation, target.userId, target.sector.code, abort.signal);
            } catch {
                result = { ok: false, kind: "unavailable", status: 0 };
            }
            inFlight = false;
            if (disposed) return; // liberado mientras la petición estaba en vuelo: ni estado ni callbacks
            apply({ type: "resolved", token, result });
            onSettled(result);
        },
    };
}

// ---- bloqueo por falta de permiso / origen no autorizado y pantalla de /admin (puros) ------------------------------------------------------

export type AccessBlock = "forbidden" | "origin" | null;

type ViewLike = { status: string; kind?: AdminFailureKind };

// Un 403 en CUALQUIER lectura (usuarios, catálogo, detalle) o en un cambio bloquea las acciones. Nunca se confunde con un 401 (eso es sesión y lo gestiona el Login) y
// ORIGIN_NOT_ALLOWED se distingue de la falta de permiso para no atribuir el error a lo que no es. `changeFailure` es el último fallo de una operación (se conserva: un 403 no se "recupera").
export function deriveAccess(views: readonly ViewLike[], changeFailure: AdminFailureKind | null): AccessBlock {
    const kinds = [...views.filter((view) => view.status === "error").map((view) => view.kind), changeFailure];
    if (kinds.includes("origin")) return "origin";
    if (kinds.includes("forbidden")) return "forbidden";
    return null;
}

export const BLOCK_TITLES: Record<Exclude<AccessBlock, null>, string> = { forbidden: "Sin permiso", origin: "Origen no autorizado" };
export const blockMessage = (block: Exclude<AccessBlock, null>): string => FAILURE_MESSAGES[block];

export type AdminScreen = "checking" | "unavailable" | "login" | "denied" | "closing" | "console";
// Qué muestra /admin. Mientras se cierra la sesión la consola NO existe (se desmonta y libera sus controladores), aunque la sesión todavía figure como válida.
export function adminScreen(view: { status: string; user?: { permissions: readonly string[] } }, loggingOut: boolean): AdminScreen {
    if (loggingOut) return "closing";
    if (view.status === "checking") return "checking";
    if (view.status === "unavailable") return "unavailable";
    if (view.status !== "authenticated") return "login";
    return canAdminister(view.user) ? "console" : "denied";
}

// ---- recurso administrativo: derivación de la vista (pura) ----------------------------------------------------------------------------------

export type AdminResource<T> =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; data: T; refreshing: boolean }
    | { status: "error"; kind: AdminFailureKind; refreshing: boolean };

export type StoredResource<T> = { key: string; attempt: number; result: { ok: true; data: T } | { ok: false; kind: AdminFailureKind } };

// "loading" y "refreshing" se derivan: un resultado guardado con OTRA clave (otra sesión u otro usuario) nunca se muestra.
export function deriveResource<T>(enabled: boolean, key: string, attempt: number, stored: StoredResource<T> | null): AdminResource<T> {
    if (!enabled) return { status: "idle" };
    if (!stored || stored.key !== key) return { status: "loading" };
    return stored.result.ok
        ? { status: "ready", data: stored.result.data, refreshing: stored.attempt !== attempt }
        : { status: "error", kind: stored.result.kind, refreshing: stored.attempt !== attempt };
}

// Carga una vez; si la señal se aborta (cambio de clave, desmontaje) el resultado se descarta sin tocar el estado. Un 401 se informa a onUnauthorized.
export async function loadResource<T>(
    load: (signal: AbortSignal) => Promise<AdminResult<T>>, signal: AbortSignal, key: string, attempt: number,
    store: (stored: StoredResource<T>) => void, onUnauthorized: () => void,
): Promise<void> {
    try {
        const result = await load(signal);
        if (signal.aborted) return;
        if (!result.ok && result.kind === "session") onUnauthorized();
        store({ key, attempt, result: result.ok ? { ok: true, data: result.data } : { ok: false, kind: result.kind } });
    } catch {
        if (!signal.aborted) store({ key, attempt, result: { ok: false, kind: "unavailable" } });
    }
}
