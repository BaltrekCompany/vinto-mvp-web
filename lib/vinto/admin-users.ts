// USR-05: contratos de cuentas, validación cerrada y controlador de mutaciones.
// Nunca se guarda un secreto en el estado del controlador, en storage ni en los mensajes de resultado.
import {
    createAdminRequester, isRecord, isUuid, parseAdminUser,
    type AdminFailure, type AdminResult, type AdminUser,
} from "@/lib/vinto/admin";

export type AccountProfile = { code: string; name: string };
export type AccountAction = "create" | "edit" | "reset" | "deactivate" | "reactivate";
export type AccountTarget = { action: AccountAction; user: AdminUser | null };
export type AccountInput =
    | { action: "create"; username: string; display_name: string; profile_code: string; password: string }
    | { action: "edit"; display_name: string; profile_code: string }
    | { action: "reset"; password: string }
    | { action: "deactivate" | "reactivate"; reason: string };
export type AccountOutcome = {
    action: AccountAction; userId: string; username: string; changed: boolean;
    sessionsRevoked: number; requestId: string | null;
};
export type AccountClient = {
    listProfiles: (signal?: AbortSignal) => Promise<AdminResult<AccountProfile[]>>;
    mutate: (target: AccountTarget, input: AccountInput, signal?: AbortSignal) => Promise<AdminResult<AccountOutcome>>;
};

const PROFILE = /^[A-Z][A-Z0-9_]{0,63}$/;
const USERNAME = /^[a-z0-9._-]{1,64}$/;
const fail = (): AdminResult<never> => ({ ok: false, kind: "invalid", status: 0 });

export function parseAccountProfiles(payload: unknown): AccountProfile[] | null {
    if (!Array.isArray(payload)) return null;
    const result: AccountProfile[] = [];
    for (const row of payload) {
        if (!isRecord(row) || typeof row.code !== "string" || !PROFILE.test(row.code) ||
            typeof row.name !== "string" || row.name.trim().length === 0 ||
            result.some((known) => known.code === row.code)) return null;
        result.push({ code: row.code, name: row.name });
    }
    return result;
}

function auditFields(row: Record<string, unknown>): { changed: boolean; count: number; id: string | null } | null {
    const changed = row.changed, count = row.sessions_revoked, id = row.request_id;
    if (typeof changed !== "boolean" || !Number.isSafeInteger(count) || (count as number) < 0 ||
        (id !== null && (typeof id !== "string" || !id)) ||
        (changed && id === null) || (!changed && id !== null)) return null;
    return { changed, count: count as number, id: id as string | null };
}

export function parseAccountOutcome(action: AccountAction, target: AccountTarget, body: unknown): AccountOutcome | null {
    if (!isRecord(body)) return null;
    if (action === "create") {
        const user = parseAdminUser(body);
        if (user === null || !user.active || user.username === null || user.profiles.length !== 1 || user.sectors.length !== 0) return null;
        return { action, userId: user.id, username: user.username, changed: true, sessionsRevoked: 0, requestId: null };
    }
    if (target.user === null || !isUuid(target.user.id) ||
        body.user_id !== target.user.id || body.username !== undefined && body.username !== target.user.username) return null;
    const fields = auditFields(body);
    if (fields === null) return null;
    if (action === "edit") {
        if (typeof body.username !== "string" || typeof body.display_name !== "string" ||
            !body.display_name.trim() || typeof body.profile_code !== "string" || !PROFILE.test(body.profile_code) ||
            typeof body.active !== "boolean") return null;
    } else if (action === "reset") {
        if (body.changed !== true || body.must_change !== false) return null;
    } else if (body.active !== (action === "reactivate") || typeof body.username !== "string") return null;
    return { action, userId: target.user.id, username: String(body.username ?? target.user.username ?? ""),
             changed: fields.changed, sessionsRevoked: fields.count, requestId: fields.id };
}

export function validateAccountInput(target: AccountTarget, input: AccountInput, profiles: readonly AccountProfile[]): string | null {
    if (target.action !== input.action) return "La operación ya no corresponde al formulario.";
    if (target.action !== "create" && (target.user === null || !isUuid(target.user.id))) return "Selecciona un usuario válido.";
    if (input.action === "create" || input.action === "edit") {
        const name = input.display_name.trim();
        if (!name || name.length > 200) return "El nombre debe tener entre 1 y 200 caracteres.";
        if (!profiles.some((item) => item.code === input.profile_code)) return "Selecciona un perfil vigente del catálogo.";
        if (input.action === "edit") {
            if (target.user === null || (name === target.user.display_name && input.profile_code === target.user.profiles[0])) return "No hay cambios para guardar.";
        } else {
            const username = input.username.trim().toLowerCase();
            if (!USERNAME.test(username)) return "El usuario debe tener 1 a 64 caracteres: letras, números, punto, guion o guion bajo.";
        }
    }
    if (input.action === "create" || input.action === "reset") {
        if (input.password.length < 12 || input.password.length > 256) return "La contraseña debe tener entre 12 y 256 caracteres.";
    }
    if (input.action === "deactivate" || input.action === "reactivate") {
        const reason = input.reason.trim();
        if (!reason || reason.length > 500) return "Indica un motivo de 1 a 500 caracteres.";
        if (target.user?.active === (input.action === "reactivate")) return "El estado del usuario ya cambió; vuelve a consultar.";
    }
    return null;
}

export function createAccountClient(baseUrl: () => string, fetchImpl: (url: string, init: RequestInit) => Promise<Response>): AccountClient {
    const request = createAdminRequester(baseUrl, fetchImpl);
    return {
        listProfiles: (signal) => request("/api/admin/profiles", { signal }, parseAccountProfiles),
        async mutate(target, input, signal) {
            if (target.action !== input.action) return fail();
            const userId = target.user?.id;
            if (target.action !== "create" && !isUuid(userId)) return fail();
            if (input.action === "create") {
                if (!USERNAME.test(input.username.trim().toLowerCase()) || !input.display_name.trim() ||
                    !PROFILE.test(input.profile_code) || input.password.length < 12 || input.password.length > 256) return fail();
                const result = await request("/api/admin/users",
                    { method: "POST", signal, body: {
                        username: input.username.trim().toLowerCase(), display_name: input.display_name.trim(),
                        profile_code: input.profile_code, password: input.password,
                    } }, (body) => parseAccountOutcome("create", target, body));
                if (result.ok && result.data.username !== input.username.trim().toLowerCase()) return { ok: false, kind: "unavailable", status: result.status };
                return result;
            }
            if (input.action === "edit") {
                if (!input.display_name.trim() || !PROFILE.test(input.profile_code)) return fail();
                const result = await request("/api/admin/users/" + userId, { method: "PATCH", signal, body: {
                    display_name: input.display_name.trim(), profile_code: input.profile_code,
                } }, (body) => parseAccountOutcome("edit", target, body));
                return result;
            }
            if (input.action === "reset") {
                if (input.password.length < 12 || input.password.length > 256) return fail();
                return request("/api/admin/users/" + userId + "/reset-password", { method: "POST", signal, body: { password: input.password } },
                    (body) => parseAccountOutcome("reset", target, body));
            }
            const reason = input.reason.trim();
            if (!reason || reason.length > 500) return fail();
            return request("/api/admin/users/" + userId + "/" + input.action, { method: "POST", signal, body: { reason } },
                (body) => parseAccountOutcome(input.action as "deactivate" | "reactivate", target, body));
        },
    };
}

export type AccountState =
    | { step: "closed" }
    | { step: "draft" | "submitting"; target: AccountTarget }
    | { step: "done"; target: AccountTarget; outcome: AccountOutcome }
    | { step: "failed"; target: AccountTarget; failure: AdminFailure };
export const ACCOUNT_CLOSED: AccountState = { step: "closed" };
export type AccountController = {
    readonly state: AccountState; open: (target: AccountTarget) => void; close: () => void;
    submit: (input: AccountInput) => Promise<void>; dispose: () => void;
};

export function createAccountController(
    client: Pick<AccountClient, "mutate">,
    onChange: (state: AccountState) => void,
    onSettled: (result: AdminResult<AccountOutcome>, target: AccountTarget) => void,
): AccountController {
    let state: AccountState = ACCOUNT_CLOSED;
    let disposed = false, busy = false;
    const abort = new AbortController();
    const setState = (next: AccountState) => { if (disposed) return; state = next; onChange(next); };
    return {
        get state() { return state; },
        open(target) {
            if (disposed || busy) return;
            if (target.action !== "create" && !isUuid(target.user?.id)) return;
            if (target.action === "create" && target.user !== null) return;
            setState({ step: "draft", target });
        },
        close() { if (!disposed && !busy) setState(ACCOUNT_CLOSED); },
        dispose() { disposed = true; abort.abort(); },
        async submit(input) {
            if (disposed || busy || state.step !== "draft" || state.target.action !== input.action) return;
            const target = state.target;
            busy = true;
            setState({ step: "submitting", target });
            let result: AdminResult<AccountOutcome>;
            try { result = await client.mutate(target, input, abort.signal); }
            catch { result = { ok: false, kind: "unavailable", status: 0 }; }
            busy = false;
            if (disposed) return; // otro login/sesión ya no recibe eventos ni escrituras de UI tardías
            setState(result.ok ? { step: "done", target, outcome: result.data } : { step: "failed", target, failure: result });
            onSettled(result, target);
        },
    };
}
