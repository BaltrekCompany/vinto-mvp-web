// Pantallas centrales CANDIDATAS de Calidad por máquina (DEV-Q1): P1-22 «Grado de refinación Schopper» y P1-26 «Medición de secos». Configuración PURA que enlaza cada formulario con su definición declarativa
// (contexto "machine"), su cliente de API y los textos de sus decisiones pendientes. Se ofrecen solo si el backend publica el formulario para la máquina (GET /api/quality/machine-forms).
import { machineCandidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P122, P122_AUTOMATIC, P122_PENDING, P1_22_CODE } from "./p1-22.ts";
import { P126, P126_AUTOMATIC, P126_CALCULATED, P126_PENDING, P1_26_CODE } from "./p1-26.ts";
import type { QualityCandidateScreen } from "./quality-offers.ts";

export type QualityCandidate = CandidateScreen & { machineApi: ReturnType<typeof machineCandidateApi> };

const make = (rest: Omit<CandidateScreen, "api">, api: ReturnType<typeof machineCandidateApi>): QualityCandidate => ({ ...rest, api, machineApi: api });

export const QUALITY_CANDIDATES: Record<QualityCandidateScreen, QualityCandidate> = {
    p122: make({ code: P1_22_CODE, form: P122, kicker: "Calidad · control por máquina", title: "Grado de refinación Schopper", automatic: P122_AUTOMATIC, pending: P122_PENDING,
        historyNote: "Control candidato por máquina (sin bobina ni OT): registros guardados en PostgreSQL. La hora es la de registro; no hay rangos ni criterio de aceptación aprobados." }, machineCandidateApi(P122)),
    p126: make({ code: P1_26_CODE, form: P126, kicker: "Calidad · control por máquina", title: "Medición de secos", automatic: P126_AUTOMATIC, pending: P126_PENDING, calculated: P126_CALCULATED,
        historyNote: "Control candidato por máquina (sin bobina ni OT): las masas se muestran tal como se digitaron; el porcentaje de secos no se calcula." }, machineCandidateApi(P126)),
};
