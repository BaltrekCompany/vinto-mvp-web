// Pantallas centrales CANDIDATAS del sector Bobinas (DEV-B1): P1-05 «Registro de tubetes» y P1-31 «Consumo de químicos». Configuración PURA que enlaza cada formulario con su definición declarativa
// (candidate-form.ts), su cliente de API y los textos de sus decisiones pendientes. Un formulario nuevo de este tipo solo añade una entrada aquí (y su pantalla en availability.ts).
//
// Ninguna de estas pantallas está operativa por sí misma: se ofrecen solo si el backend publica el formulario para la máquina (GET /api/production/machines) y la sesión puede capturar.
import { candidateApi } from "./candidate-form-api.ts";
import type { CandidateForm } from "./candidate-form.ts";
import { BOBINAS_CANDIDATE_SCREENS, type BobinasCandidateScreen } from "./bobinas-offers.ts";
import { P104, P104_AUTOMATIC, P104_CALCULATED, P104_PENDING, P104_UNRESOLVED_AUTOMATIC, P1_04_CODE } from "./p1-04.ts";
import { P101, P101_AUTOMATIC, P101_PENDING, P101_SECTIONS, P101_UNRESOLVED_AUTOMATIC, P1_01_CODE } from "./p1-01.ts";
import { P102, P102_AUTOMATIC, P102_PENDING, P102_SECTIONS, P102_UNRESOLVED_AUTOMATIC, P1_02_CODE } from "./p1-02.ts";
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
    unresolved?: readonly string[]; // campos automáticos de la definición SIN fuente confirmada (no se generan)
    calculated?: readonly string[]; // campos calculados de la definición sin fórmula aprobada (no se calculan ni se muestran)
    sections?: readonly { title: string; hint?: string; keys: readonly string[] }[]; // agrupación SOLO visual (cada campo en una sección)
    titleFor?: (machine: string | undefined) => { kicker: string; title: string }; // MF-09A: ver CandidateScreen
    historyNote: string;
};

// MF-09A: P1-01 sirve a MP1 y MP3; kicker y título llevan la máquina de la asignación activa (ya validada por el backend), no un texto fijo. Sin máquina no se muestra ninguna.
const machineTitles = (kicker: string, title: string) => (machine: string | undefined) => { const m = machine?.trim(); return m ? { kicker: `${kicker} ${m}`, title: `${title} ${m}` } : { kicker, title }; };

export const BOBINAS_CANDIDATES = {
    p104: { code: P1_04_CODE, form: P104, api: candidateApi(P104), kicker: "Fibra · Bobinas", title: "Registro de consumo de fibra", automatic: P104_AUTOMATIC, pending: P104_PENDING, unresolved: P104_UNRESOLVED_AUTOMATIC, calculated: P104_CALCULATED,
        historyNote: "Ficha candidata construida desde la definición original (no desde la pantalla legacy): sin horas ni totales; los valores se muestran tal como se digitaron." },
    p105: { code: P1_05_CODE, form: P105, api: candidateApi(P105), kicker: "Tubetes · Bobinas", title: "Registro de tubetes", automatic: P105_AUTOMATIC, pending: P105_PENDING,
        historyNote: "Ficha candidata: registros guardados en PostgreSQL. Catálogo de tubetes, cantidades y asociación con la bobina pendientes de VINTO." },
    p131: { code: P1_31_CODE, form: P131, api: candidateApi(P131), kicker: "Químicos · Bobinas", title: "Consumo de químicos", automatic: P131_AUTOMATIC, pending: P131_PENDING,
        historyNote: "Ficha candidata: los consumos son los digitados (texto); no se calculan desde los caudales ni forman inventario." },
    p102: { code: P1_02_CODE, form: P102, api: candidateApi(P102), kicker: "Parámetros · Bobinas MP1", title: "Parámetros de operación de máquina MP1", automatic: P102_AUTOMATIC, pending: P102_PENDING, unresolved: P102_UNRESOLVED_AUTOMATIC, sections: P102_SECTIONS,
        historyNote: "Ficha candidata construida desde la definición original: los valores se muestran tal como se digitaron (sin rangos ni cálculos) y la hora de registro no es la hora de la medición." },
    p101: { code: P1_01_CODE, form: P101, api: candidateApi(P101), kicker: "Operación e inspección · Bobinas", title: "Operación e inspección de máquina", titleFor: machineTitles("Operación e inspección · Bobinas", "Operación e inspección de máquina"), automatic: P101_AUTOMATIC, pending: P101_PENDING, unresolved: P101_UNRESOLVED_AUTOMATIC, sections: P101_SECTIONS,
        historyNote: "Ficha candidata construida desde la definición original: valores tal como se digitaron; sin velocidad, firma ni revisión automáticas; las tres horas de cambio de cuchilla son manuales." },
} as const satisfies Record<BobinasCandidateScreen, BobinasCandidate>;

export { BOBINAS_CANDIDATE_SCREENS, type BobinasCandidateScreen };
