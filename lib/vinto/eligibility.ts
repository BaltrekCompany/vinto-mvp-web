// MF-13-02 · Elegibilidad verificada por el backend. PURO: sin red ni DOM.
//
// `eligible` (GET /api/production/machines, /api/quality/bobbin-forms, /api/quality/machine-forms) es la decisión del motor de autorización: perfil, sector operativo concedido, máquina y formulario
// activos, versión publicada vigente vinculada y concesión máquina-formulario activa. Es INDEPENDIENTE del modo de las compuertas (off/observe/enforce): el modo solo gobierna si el backend RECHAZA
// una captura; la interfaz solo decide qué MOSTRAR. Ocultar nunca sustituye a la autorización del backend, que sigue decidiendo cada captura.
// Falla cerrado: sin el campo `eligible` (respuesta antigua o incompleta) nada se considera elegible.
import type { Availability, FormRef, MachineAvailability } from "./availability.ts";
import type { Resource } from "./resource-view.ts";
import { BOBINAS_SECTOR, CONVERSION_SECTOR, REBOBINADO_SECTOR } from "./availability.ts";

export type FrontName = "Bobinas" | "Rebobinado" | "Conversión" | "Calidad";
export const F3_CODE = "VINTO-P1-03";
export const F6_CODE = "VINTO-P1-06";
export const QUALITY_HUMIDITY_CODE = "VINTO-P1-19";
export const QUALITY_PHYSICAL_CODE = "VINTO-P1-20";

const SECTOR_FRONT: Readonly<Record<string, FrontName>> = { [BOBINAS_SECTOR]: "Bobinas", [REBOBINADO_SECTOR]: "Rebobinado", [CONVERSION_SECTOR]: "Conversión" };
const isEligible = (form: FormRef): boolean => form.eligible === true;

// Copia de la disponibilidad con SOLO lo elegible: formularios, formularios de bobina, máquinas sin ninguno y sectores vacíos desaparecen (se ocultan, no se deshabilitan).
export function onlyEligible(availability: Availability): Availability {
    const sectors = availability.sectors.flatMap((sector) => {
        const machines = sector.machines.flatMap((machine): MachineAvailability[] => {
            const forms = machine.forms.filter(isEligible), bobbinForms = (machine.bobbin_forms ?? []).filter(isEligible);
            if (forms.length === 0 && bobbinForms.length === 0) return [];
            const kept: MachineAvailability = { ...machine, forms };
            if (machine.bobbin_forms !== undefined) kept.bobbin_forms = bobbinForms;
            return [kept];
        });
        return machines.length > 0 ? [{ ...sector, machines }] : [];
    });
    return { sectors };
}

// ¿Esta máquina ofrece (elegible) el formulario, ya sea en `forms` o en `bobbin_forms`? Se espera una máquina ya filtrada o sin filtrar: el campo `eligible` decide.
export const offersForm = (machine: MachineAvailability | undefined, code: string): boolean =>
    machine !== undefined && [...machine.forms, ...(machine.bobbin_forms ?? [])].some((form) => form.code === code && isEligible(form));

export const hasEligibleForm = (availability: Availability): boolean => onlyEligible(availability).sectors.length > 0;

export type AccessInput = {
    canManage: boolean; // work_order.manage o assignment.manage: la programación se rige por permiso + alcance de sector, NO por concesiones máquina-formulario
    canQuality: boolean; // quality.capture
    production: Availability;
    qualityBobbin: Availability | null;
    qualityMachine: Availability | null;
};

// Frentes que la sesión puede ver. Producción: el sector está en su alcance Y (gestiona programación O tiene algún formulario elegible). Calidad: quality.capture Y algún formulario elegible.
export function visibleFronts(input: AccessInput): FrontName[] {
    const fronts = new Set<FrontName>();
    const eligible = onlyEligible(input.production);
    for (const sector of input.production.sectors) {
        const front = SECTOR_FRONT[sector.code];
        if (!front || sector.machines.length === 0) continue;
        if (input.canManage || eligible.sectors.some((s) => s.code === sector.code)) fronts.add(front);
    }
    if (input.canQuality && ((input.qualityBobbin && hasEligibleForm(input.qualityBobbin)) || (input.qualityMachine && hasEligibleForm(input.qualityMachine)))) fronts.add("Calidad");
    return (["Bobinas", "Rebobinado", "Conversión", "Calidad"] as FrontName[]).filter((front) => fronts.has(front));
}

// Estado de acceso de la sesión. Mientras no se confirma (cargando, 503, sin conexión) NO se muestra ningún frente como habilitado.
export type AccessState =
    | { status: "loading" }
    | { status: "unconfirmed" } // 503 / error de conexión: permisos sin confirmar
    | { status: "denied" } // 403: el backend no reconoce permisos de consulta
    | { status: "ready"; fronts: FrontName[] };

type Loaded = { status: "idle" } | { status: "loading" } | { status: "ready"; data: Availability } | { status: "error"; kind: string };

export function deriveAccess(input: { canManage: boolean; canQuality: boolean; production: Loaded; qualityBobbin: Loaded; qualityMachine: Loaded }): AccessState {
    const required = [input.production, ...(input.canQuality ? [input.qualityBobbin, input.qualityMachine] : [])];
    const failed = required.find((r) => r.status === "error") as { status: "error"; kind: string } | undefined;
    if (failed) return failed.kind === "forbidden" ? { status: "denied" } : { status: "unconfirmed" };
    if (required.some((r) => r.status !== "ready")) return { status: "loading" };
    const data = (r: Loaded) => (r.status === "ready" ? r.data : null);
    const production = data(input.production);
    if (!production) return { status: "loading" };
    return { status: "ready", fronts: visibleFronts({ canManage: input.canManage, canQuality: input.canQuality, production, qualityBobbin: data(input.qualityBobbin), qualityMachine: data(input.qualityMachine) }) };
}

// El frente efectivo: el elegido si sigue visible; si no, el primero visible; sin ninguno, null.
export const effectiveFront = (fronts: readonly FrontName[], chosen: FrontName): FrontName | null => (fronts.includes(chosen) ? chosen : fronts[0] ?? null);

// Calidad · acciones sobre una bobina de la máquina dada (P1-19 humedad, P1-20 propiedades físicas): solo si el backend las marca elegibles para ESA máquina.
export function qualityBobbinActions(availability: Availability | null, machineCode: string): { humidity: boolean; physical: boolean } {
    const machine = availability?.sectors.flatMap((s) => s.machines).find((m) => m.code === machineCode);
    return { humidity: offersForm(machine, QUALITY_HUMIDITY_CODE), physical: offersForm(machine, QUALITY_PHYSICAL_CODE) };
}

// La misma vista de un recurso de disponibilidad, pero con SOLO lo elegible (los estados que no son «ready» no cambian).
export const eligibleView = (view: Resource<Availability>): Resource<Availability> => (view.status === "ready" ? { ...view, data: onlyEligible(view.data) } : view);

// Máquinas de Bobinas con algún formulario elegible, en el orden del backend.
export const eligibleMachineCodes = (availability: Availability, sectorCode: string): string[] => onlyEligible(availability).sectors.find((s) => s.code === sectorCode)?.machines.map((m) => m.code) ?? [];
