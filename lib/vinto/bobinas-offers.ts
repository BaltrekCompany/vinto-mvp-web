// Qué fichas candidatas de Bobinas (P1-05 / P1-31) se ofrecen: DECISIÓN PURA a partir de la disponibilidad que verifica el backend (GET /api/production/machines). Una pantalla solo se ofrece si el backend
// publica el formulario para ESA máquina (versión publicada, vinculada y habilitada por la política) y existe pantalla para el par (BOBINAS, formulario). Sin disponibilidad no se ofrece nada: nunca hay
// listas estáticas ni localStorage como respaldo. Sin red ni DOM.
import { BOBINAS_SECTOR, offeredForms, sectorOf, type Availability, type FormScreen } from "./availability.ts";

export const BOBINAS_CANDIDATE_SCREENS = ["p105", "p131"] as const;
export type BobinasCandidateScreen = (typeof BOBINAS_CANDIDATE_SCREENS)[number];

export const isBobinasCandidate = (screen: FormScreen | null): screen is BobinasCandidateScreen => screen !== null && (BOBINAS_CANDIDATE_SCREENS as readonly string[]).includes(screen);

// Pantallas candidatas que el backend publica para ESTA máquina.
export function candidateScreensFor(availability: Availability, machineCode: string): BobinasCandidateScreen[] {
    const machine = sectorOf(availability, BOBINAS_SECTOR)?.machines.find((m) => m.code === machineCode);
    return machine ? offeredForms(BOBINAS_SECTOR, machine).map((o) => o.screen).filter(isBobinasCandidate) : [];
}

// Pantallas candidatas publicadas en CUALQUIER máquina de Bobinas (historial de Seguimiento), en el orden de BOBINAS_CANDIDATE_SCREENS.
export function publishedCandidateScreens(availability: Availability): BobinasCandidateScreen[] {
    const machines = sectorOf(availability, BOBINAS_SECTOR)?.machines ?? [];
    const published = new Set(machines.flatMap((m) => offeredForms(BOBINAS_SECTOR, m).map((o) => o.screen).filter(isBobinasCandidate)));
    return BOBINAS_CANDIDATE_SCREENS.filter((screen) => published.has(screen));
}
