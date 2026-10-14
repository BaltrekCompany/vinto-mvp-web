// Disponibilidad de producción verificada por el backend (M4-A): máquinas y formularios centrales que la SESIÓN puede operar (GET /api/production/machines). PURO: sin red ni DOM.
// La interfaz de Rebobinado NO decide qué máquinas ni qué formularios existen: lo dice esta respuesta. Un sector concedido pero no operativo no aparece, y entonces la navegación lo
// muestra como no habilitado (nunca con datos demo ni localStorage). Las listas legacy estáticas no son autoridad para autorizar capturas.

import { isRec, isStr } from "./capture-core.ts";

export type FormRef = { code: string; name: string; version_number: number };
export type ArticleRef = { code: string; description: string };
export type MachineAvailability = { code: string; name: string; forms: FormRef[]; articles?: ArticleRef[] };
export type SectorAvailability = { code: string; name: string; machines: MachineAvailability[] };
export type Availability = { sectors: SectorAvailability[] };

function parseForm(value: unknown): FormRef | null {
    return isRec(value) && isStr(value.code) && typeof value.name === "string" && typeof value.version_number === "number" && Number.isSafeInteger(value.version_number)
        ? { code: value.code, name: value.name, version_number: value.version_number } : null;
}
function parseArticle(value: unknown): ArticleRef | null {
    return isRec(value) && isStr(value.code) && typeof value.description === "string" ? { code: value.code, description: value.description } : null;
}
function parseMachine(value: unknown): MachineAvailability | null {
    if (!isRec(value) || !isStr(value.code) || typeof value.name !== "string" || !Array.isArray(value.forms)) return null;
    const forms = value.forms.map(parseForm);
    if (forms.some((f) => f === null)) return null;
    const machine: MachineAvailability = { code: value.code, name: value.name, forms: forms as FormRef[] };
    if (value.articles !== undefined) {
        if (!Array.isArray(value.articles)) return null;
        const articles = value.articles.map(parseArticle);
        if (articles.some((a) => a === null)) return null;
        machine.articles = articles as ArticleRef[];
    }
    return machine;
}

// Estricto: cualquier elemento mal formado invalida toda la respuesta (nunca se muestran máquinas o formularios a medias).
export function parseAvailability(value: unknown): Availability | null {
    if (!isRec(value) || !Array.isArray(value.sectors)) return null;
    const sectors: SectorAvailability[] = [];
    for (const raw of value.sectors) {
        if (!isRec(raw) || !isStr(raw.code) || typeof raw.name !== "string" || !Array.isArray(raw.machines)) return null;
        const machines = raw.machines.map(parseMachine);
        if (machines.some((m) => m === null)) return null;
        sectors.push({ code: raw.code, name: raw.name, machines: machines as MachineAvailability[] });
    }
    return { sectors };
}

export const REBOBINADO_SECTOR = "REBOBINADO";
export const CONVERSION_SECTOR = "CONVERSION";
export const sectorOf = (availability: Availability, code: string): SectorAvailability | null => availability.sectors.find((s) => s.code === code) ?? null;

// Pantalla central que implementa cada formulario. Solo los formularios con pantalla (y que el backend habilita para la máquina) se pueden abrir.
export type FormScreen = "p110" | "p111" | "p112" | "p113" | "p116" | "p129";
// Una pantalla solo se ofrece para el par (sector, formulario) que Home sabe enrutar: P1-10 y P1-29 en Rebobinado, P1-11, P1-12, P1-13 y P1-16 en Conversión. Un formulario que el backend publique en otro sector
// (p. ej. P1-16 en Rebobinado) se informa como «sin pantalla central» y no se abre. El backend sigue decidiendo qué se publica; esto solo limita lo que la interfaz sabe dibujar.
export const SECTOR_SCREENS: Readonly<Record<string, Readonly<Record<string, FormScreen>>>> = {
    [REBOBINADO_SECTOR]: { "VINTO-P1-10": "p110", "VINTO-P1-29": "p129" },
    [CONVERSION_SECTOR]: { "VINTO-P1-11": "p111", "VINTO-P1-12": "p112", "VINTO-P1-13": "p113", "VINTO-P1-16": "p116" },
};
export const screenFor = (sectorCode: string, formCode: string): FormScreen | null => SECTOR_SCREENS[sectorCode]?.[formCode] ?? null;

export type SectorView =
    | { kind: "disabled" } // el backend no expone el sector a esta sesión (no operativo y/o sin concesión)
    | { kind: "ready"; sector: SectorAvailability };
export type RebobinadoView = SectorView;

// La vista de un sector depende SOLO de lo que el backend devolvió: sin sector o sin máquinas = deshabilitado.
export const sectorView = (availability: Availability, code: string): SectorView => {
    const sector = sectorOf(availability, code);
    return sector && sector.machines.length > 0 ? { kind: "ready", sector } : { kind: "disabled" };
};
export const rebobinadoView = (availability: Availability): RebobinadoView => sectorView(availability, REBOBINADO_SECTOR);
export const conversionView = (availability: Availability): SectorView => sectorView(availability, CONVERSION_SECTOR);

export const DISABLED_TITLE = "Rebobinado no está habilitado";
export const DISABLED_MESSAGE = "El backend no habilita Rebobinado para tu sesión: el sector no es operativo o no tienes concesión. No se registran capturas centrales ni se usan datos de demostración como respaldo.";
export const CONVERSION_DISABLED_TITLE = "Conversión no está habilitado";
export const CONVERSION_DISABLED_MESSAGE = "El backend no habilita Conversión para tu sesión: el sector no es operativo o no tienes concesión. No se registran capturas centrales ni se usan datos de demostración ni registros locales como respaldo.";

// Formularios que se pueden ofrecer en una máquina: los que el backend publica Y que tienen pantalla central; el resto se informan como «sin pantalla».
export function offeredForms(sectorCode: string, machine: MachineAvailability): { form: FormRef; screen: FormScreen | null }[] {
    return machine.forms.map((form) => ({ form, screen: screenFor(sectorCode, form.code) }));
}

export const articlesOf = (machine: MachineAvailability | undefined): ArticleRef[] => machine?.articles ?? [];
