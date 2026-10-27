// Pantallas centrales CANDIDATAS del sector Rebobinado (DEV-R2): P1-30 «Producción Perichun» y P1-07 «Registro de producción de bobinas rebobinadas» (MF-10; antes «refiladas»). Configuración PURA que enlaza cada formulario con su
// definición declarativa (candidate-form.ts, contexto de asignación), su cliente de API de Producción (/api/captures) y los textos de sus decisiones pendientes. Se ofrecen solo si el backend publica el
// formulario para la máquina de la sesión (GET /api/production/machines); con la configuración real Rebobinado no es operativo y no se ofrece nada.
import { candidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P107, P107_AUTOMATIC, P107_PENDING, P107_SECTIONS, P1_07_CODE } from "./p1-07.ts";
import { P130, P130_AUTOMATIC, P130_PENDING, P1_30_CODE } from "./p1-30.ts";

export const REBOBINADO_CANDIDATE_SCREENS = ["p130", "p107"] as const;
export type RebobinadoCandidateScreen = (typeof REBOBINADO_CANDIDATE_SCREENS)[number];
export const isRebobinadoCandidate = (screen: string | null): screen is RebobinadoCandidateScreen => screen !== null && (REBOBINADO_CANDIDATE_SCREENS as readonly string[]).includes(screen);

export type RebobinadoCandidate = Omit<CandidateScreen, "api"> & { api: ReturnType<typeof candidateApi> }; // con `list` para el historial

export const REBOBINADO_CANDIDATES: Record<RebobinadoCandidateScreen, RebobinadoCandidate> = {
    p130: { code: P1_30_CODE, form: P130, api: candidateApi(P130), kicker: "Producción Perichun · Rebobinado", title: "Producción Perichun", automatic: P130_AUTOMATIC, pending: P130_PENDING,
        historyNote: "Ficha candidata: horas de inicio y fin digitadas (desde la versión 2); el número de bobina es texto y no crea bobinas. Los valores se muestran tal como se digitaron; los campos retirados se marcan como versión anterior." },
    p107: { code: P1_07_CODE, form: P107, api: candidateApi(P107), kicker: "Bobinas rebobinadas · Rebobinado", title: "Registro de producción de bobinas rebobinadas", automatic: P107_AUTOMATIC, pending: P107_PENDING,
        sections: P107_SECTIONS, historyNote: "Captura técnica candidata, NO genealogía: no hay bobinas hijas, relaciones madre-hija ni balances; los pesos de las 21 crías se muestran tal como se digitaron." },
};
