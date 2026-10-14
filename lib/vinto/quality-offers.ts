// Qué controles de Calidad POR MÁQUINA (P1-22 / P1-26) se ofrecen: DECISIÓN PURA a partir de la disponibilidad que verifica el backend (GET /api/quality/machine-forms: política habilitada, versión publicada
// de área quality y vínculo con la máquina) y de las pantallas que la interfaz sabe dibujar. Sin disponibilidad no se ofrece nada: nunca hay listas estáticas ni localStorage como respaldo. Sin red ni DOM.
import type { Availability, MachineAvailability } from "./availability.ts";

export const QUALITY_CANDIDATE_SCREENS = ["p122", "p126"] as const;
export type QualityCandidateScreen = (typeof QUALITY_CANDIDATE_SCREENS)[number];
export const QUALITY_SCREEN_BY_FORM: Readonly<Record<string, QualityCandidateScreen>> = { "VINTO-P1-22": "p122", "VINTO-P1-26": "p126" };

const screenOf = (code: string): QualityCandidateScreen | null => QUALITY_SCREEN_BY_FORM[code] ?? null;

// Máquinas del alcance que tienen al menos una pantalla ofrecida (en el orden del backend).
export function qualityMachines(availability: Availability): MachineAvailability[] {
    return availability.sectors.flatMap((s) => s.machines).filter((m) => m.forms.some((f) => screenOf(f.code) !== null));
}

// Pantallas de control por máquina que el backend publica para ESTA máquina.
export function qualityScreensFor(availability: Availability, machineCode: string): QualityCandidateScreen[] {
    const machine = availability.sectors.flatMap((s) => s.machines).find((m) => m.code === machineCode);
    return machine ? machine.forms.map((f) => screenOf(f.code)).filter((s): s is QualityCandidateScreen => s !== null) : [];
}

// Pantallas publicadas en CUALQUIER máquina (para el historial), en el orden de QUALITY_CANDIDATE_SCREENS.
export function publishedQualityScreens(availability: Availability): QualityCandidateScreen[] {
    const published = new Set(qualityMachines(availability).flatMap((m) => qualityScreensFor(availability, m.code)));
    return QUALITY_CANDIDATE_SCREENS.filter((s) => published.has(s));
}
