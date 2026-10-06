// Autenticación del frontend: tipos, validación de respuestas y reglas de vista. Todo es PURO (sin red, sin DOM,
// sin imports) para poder probarlo con Node. La autoridad es el backend: /api/auth/me. Aquí no se guarda nada.

export type Permission =
    | "work_order.read" | "work_order.manage" | "assignment.read" | "assignment.manage"
    | "production.capture" | "quality.capture" | "quality.release"
    | "catalog.read" | "catalog.manage" | "user.manage";

export type AuthUser = {
    id: string;
    username: string;
    display_name: string;
    profiles: string[];
    permissions: string[];
    must_change: boolean;
};

export type SessionResult =
    | { status: "authenticated"; user: AuthUser }
    | { status: "anonymous" }
    | { status: "unavailable" };

export type LoginResult =
    | { status: "ok"; user: AuthUser }
    | { status: "invalid" }
    | { status: "rejected" }
    | { status: "unavailable" };

export type AuthView = { status: "checking" } | SessionResult;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isStringList = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string");

// Valida { user: {...} } sin confiar ciegamente en la forma. Devuelve una copia limpia o null.
export function parseAuthResponse(payload: unknown): AuthUser | null {
    if (!isRecord(payload) || !isRecord(payload.user)) return null;
    const { id, username, display_name, profiles, permissions, must_change } = payload.user;
    if (typeof id !== "string" || !UUID.test(id)) return null;
    if (typeof username !== "string" || !username) return null;
    if (typeof display_name !== "string" || !display_name) return null;
    if (!isStringList(profiles) || !isStringList(permissions)) return null;
    if (typeof must_change !== "boolean") return null;
    return { id, username, display_name, profiles: [...profiles], permissions: [...permissions], must_change };
}

// 200 -> sesión; 401 -> anónimo; cualquier otra cosa (503, 5xx, cuerpo malformado) -> no disponible, NUNCA "sesión cerrada".
export function interpretSession(status: number, payload: unknown): SessionResult {
    if (status === 200) {
        const user = parseAuthResponse(payload);
        return user ? { status: "authenticated", user } : { status: "unavailable" };
    }
    return status === 401 ? { status: "anonymous" } : { status: "unavailable" };
}

export function interpretLogin(status: number, payload: unknown): LoginResult {
    if (status === 200) {
        const user = parseAuthResponse(payload);
        return user ? { status: "ok", user } : { status: "unavailable" };
    }
    if (status === 401) return { status: "invalid" };
    if (status === 422) return { status: "rejected" };
    return { status: "unavailable" };
}

// Solo 204 confirma la revocación central; el 503 también borra la cookie local pero no la confirma.
export function interpretLogout(status: number): { confirmed: boolean } {
    return { confirmed: status === 204 };
}

export const LOGIN_MESSAGES = {
    invalid: "Credenciales inválidas",
    rejected: "Solicitud inválida",
    unavailable: "No se pudo conectar con el servidor",
} as const;

// ---- perfiles -> vista ---------------------------------------------------------------------------------------

export type OperationalRole = "jefatura" | "supervision" | "operacion" | "calidad";

const PROFILE_TO_ROLE: Record<string, OperationalRole> = {
    JEFATURA: "jefatura",
    SUPERVISION: "supervision",
    OPERACION: "operacion",
    CALIDAD: "calidad",
};
const ROLE_ORDER: OperationalRole[] = ["jefatura", "supervision", "operacion", "calidad"];

export const ROLE_LABELS: Record<OperationalRole, string> = {
    jefatura: "Jefatura",
    supervision: "Supervisión",
    operacion: "Operación",
    calidad: "Calidad",
};

// Solo los perfiles que el usuario realmente posee, en orden estable. DATA_BALTREK no es un rol operativo.
export function operationalRolesFromProfiles(profiles: readonly string[]): OperationalRole[] {
    const owned = new Set(profiles.map((profile) => PROFILE_TO_ROLE[profile]).filter((role): role is OperationalRole => role !== undefined));
    return ROLE_ORDER.filter((role) => owned.has(role));
}

export function profileLabel(profile: string): string {
    const role = PROFILE_TO_ROLE[profile];
    if (role) return ROLE_LABELS[role];
    return profile === "DATA_BALTREK" ? "Data Baltrek" : profile;
}

// El rol activo es el elegido SOLO si el usuario lo posee; si no, el primero que posee.
export function activeRole(roles: readonly OperationalRole[], chosen: OperationalRole | null): OperationalRole | null {
    return chosen !== null && roles.includes(chosen) ? chosen : roles[0] ?? null;
}

export type InitialView = { front: "Bobinas" | "Calidad"; module: "programacion" | "ejecucion" };
export const INITIAL_VIEW: Record<OperationalRole, InitialView> = {
    jefatura: { front: "Bobinas", module: "programacion" },
    supervision: { front: "Bobinas", module: "programacion" },
    operacion: { front: "Bobinas", module: "ejecucion" },
    calidad: { front: "Calidad", module: "ejecucion" },
};

// ---- permisos (UX; la autorización real vive en el backend) -----------------------------------------------------

export function hasPermission(user: Pick<AuthUser, "permissions"> | null | undefined, permission: Permission): boolean {
    return user ? user.permissions.includes(permission) : false;
}
