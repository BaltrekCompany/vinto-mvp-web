// Pantalla central CANDIDATA de Calidad ligada a UNA BOBINA física (DEV-Q2): P1-21 «Perfil de gramaje y humedad». Configuración PURA que enlaza el formulario con su definición declarativa (contexto "bobbin"), su cliente de
// API (rutas de capturas de Calidad por bobina) y los textos de sus decisiones pendientes. Se ofrece solo si el backend publica el candidato para la máquina de la bobina (GET /api/quality/bobbin-forms).
import { bobbinCandidateApi } from "./candidate-form-api.ts";
import type { CandidateScreen } from "./candidate-screen.ts";
import { P121, P121_AUTOMATIC, P121_BOBBIN_CODE_FIELD, P121_CALCULATED, P121_PENDING, P1_21_CODE } from "./p1-21.ts";
import type { QualityBobbinScreen } from "./quality-offers.ts";

export type QualityBobbinCandidate = CandidateScreen & { bobbinApi: ReturnType<typeof bobbinCandidateApi> };

const make = (rest: Omit<CandidateScreen, "api">, api: ReturnType<typeof bobbinCandidateApi>): QualityBobbinCandidate => ({ ...rest, api, bobbinApi: api });

export const QUALITY_BOBBIN_CANDIDATES: Record<QualityBobbinScreen, QualityBobbinCandidate> = {
    p121: make({ code: P1_21_CODE, form: P121, kicker: "Calidad · control de una bobina", title: "Perfil de gramaje y humedad", automatic: P121_AUTOMATIC, pending: P121_PENDING, calculated: P121_CALCULATED,
        bobbinCodeField: P121_BOBBIN_CODE_FIELD,
        historyNote: "Control candidato de ESTA bobina (registros guardados en PostgreSQL). Una captura es una posición declarada; no se calculan humedad ni promedios y registrar un control no libera ni rechaza la bobina." }, bobbinCandidateApi(P121)),
};
