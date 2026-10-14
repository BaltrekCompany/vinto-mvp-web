// Pantallas centrales CANDIDATAS de Calidad por máquina (DEV-Q1 y DEV-Q2): P1-18 «Porcentaje de consistencia», P1-22 «Grado de refinación Schopper» y P1-26 «Medición de secos». Configuración PURA que enlaza cada formulario con su definición declarativa
// (contexto "machine"), su cliente de API y los textos de sus decisiones pendientes. Se ofrecen solo si el backend publica el formulario para la máquina (GET /api/quality/machine-forms).
import { machineCandidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P118, P118_AUTOMATIC, P118_CALCULATED, P118_PENDING, P1_18_CODE } from "./p1-18.ts";
import { P122, P122_AUTOMATIC, P122_PENDING, P1_22_CODE } from "./p1-22.ts";
import { P127, P127_AUTOMATIC, P127_CALCULATED, P127_PENDING, P127_SECTIONS, P1_27_CODE } from "./p1-27.ts";
import { P126, P126_AUTOMATIC, P126_CALCULATED, P126_PENDING, P1_26_CODE } from "./p1-26.ts";
import type { QualityCandidateScreen } from "./quality-offers.ts";

export type QualityCandidate = CandidateScreen & { machineApi: ReturnType<typeof machineCandidateApi> };

const make = (rest: Omit<CandidateScreen, "api">, api: ReturnType<typeof machineCandidateApi>): QualityCandidate => ({ ...rest, api, machineApi: api });

export const QUALITY_CANDIDATES: Record<QualityCandidateScreen, QualityCandidate> = {
    p118: make({ code: P1_18_CODE, form: P118, kicker: "Calidad · control por máquina", title: "Porcentaje de consistencia", automatic: P118_AUTOMATIC, pending: P118_PENDING, calculated: P118_CALCULATED,
        historyNote: "Control candidato por máquina (sin bobina ni OT): las masas y los pesos se muestran tal como se digitaron; la consistencia no se calcula y la hora es la de registro." }, machineCandidateApi(P118)),
    p122: make({ code: P1_22_CODE, form: P122, kicker: "Calidad · control por máquina", title: "Grado de refinación Schopper", automatic: P122_AUTOMATIC, pending: P122_PENDING,
        historyNote: "Control candidato por máquina (sin bobina ni OT): registros guardados en PostgreSQL. La hora es la de registro; no hay rangos ni criterio de aceptación aprobados." }, machineCandidateApi(P122)),
    p126: make({ code: P1_26_CODE, form: P126, kicker: "Calidad · control por máquina", title: "Medición de secos", automatic: P126_AUTOMATIC, pending: P126_PENDING, calculated: P126_CALCULATED,
        historyNote: "Control candidato por máquina (sin bobina ni OT): las masas se muestran tal como se digitaron; el porcentaje de secos no se calcula." }, machineCandidateApi(P126)),
    p127: make({ code: P1_27_CODE, form: P127, kicker: "Calidad · control por máquina", title: "Análisis de agua para caldero", automatic: P127_AUTOMATIC, pending: P127_PENDING, calculated: P127_CALCULATED, sections: P127_SECTIONS,
        historyNote: "Control candidato por máquina (sin bobina ni OT): contrato completo de 23 campos (incluye condensado MP1 y MP3); valores tal como se digitaron; la alcalinidad total no se calcula y la hora es la de registro." }, machineCandidateApi(P127)),
};
