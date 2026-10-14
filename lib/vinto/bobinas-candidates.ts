// Pantallas centrales CANDIDATAS del sector Bobinas (DEV-B1): P1-05 «Registro de tubetes» y P1-31 «Consumo de químicos». Configuración PURA que enlaza cada formulario con su definición declarativa
// (candidate-form.ts), su cliente de API y los textos de sus decisiones pendientes. Un formulario nuevo de este tipo solo añade una entrada aquí (y su pantalla en availability.ts).
//
// Ninguna de estas pantallas está operativa por sí misma: se ofrecen solo si el backend publica el formulario para la máquina (GET /api/production/machines) y la sesión puede capturar.
import { candidateApi } from "./candidate-form-api.ts";
import type { CandidateForm } from "./candidate-form.ts";
import { BOBINAS_CANDIDATE_SCREENS, type BobinasCandidateScreen } from "./bobinas-offers.ts";
import { P105, P105_AUTOMATIC, P105_PENDING, P1_05_CODE } from "./p1-05.ts";
import { P131, P131_AUTOMATIC, P131_PENDING, P1_31_CODE } from "./p1-31.ts";

export type BobinasCandidate = {
    code: string;
    form: CandidateForm;
    api: ReturnType<typeof candidateApi>;
    kicker: string;
    title: string; // título de la captura y del historial
    automatic: readonly string[]; // campos automáticos de la definición legacy (no se digitan)
    pending: readonly { label: string; pending: string }[]; // decisiones pendientes de VINTO
    historyNote: string;
};

export const BOBINAS_CANDIDATES = {
    p105: { code: P1_05_CODE, form: P105, api: candidateApi(P105), kicker: "Tubetes · Bobinas", title: "Registro de tubetes", automatic: P105_AUTOMATIC, pending: P105_PENDING,
        historyNote: "Ficha candidata: registros guardados en PostgreSQL. Catálogo de tubetes, cantidades y asociación con la bobina pendientes de VINTO." },
    p131: { code: P1_31_CODE, form: P131, api: candidateApi(P131), kicker: "Químicos · Bobinas", title: "Consumo de químicos", automatic: P131_AUTOMATIC, pending: P131_PENDING,
        historyNote: "Ficha candidata: los consumos son los digitados (texto); no se calculan desde los caudales ni forman inventario." },
} as const satisfies Record<BobinasCandidateScreen, BobinasCandidate>;

export { BOBINAS_CANDIDATE_SCREENS, type BobinasCandidateScreen };
