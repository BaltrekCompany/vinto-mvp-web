import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { candidateViewer, humidityViewer, parseQualityBobbinHistory, physicalViewer, qualityHistoryLoad, type ExpectedBobbin, type HistoryViewers, type QualityHistoryLoad } from "@/lib/vinto/quality-history";
import { Q19_FORM_CODE, parseQualityCapture } from "@/lib/vinto/quality-captures";
import { Q20_FORM_CODE, parsePhysicalCapture } from "@/lib/vinto/quality-physical";
import { P1_21_CODE, P121 } from "@/lib/vinto/p1-21";
import { P1_24_CODE, P124 } from "@/lib/vinto/p1-24";
import { P1_25_CODE, P125 } from "@/lib/vinto/p1-25";
import { P1_28_CODE, P128 } from "@/lib/vinto/p1-28";

// Historial de controles de Calidad de una Bobina: SOLO GET /api/quality/bobbins/{id}/captures. Cookie HttpOnly vía requestJson (credentials
// "include"); sin tokens, sin almacenamiento local. P1-19 y P1-20 pasan por SUS parsers estrictos (Q2 y Q3.2-B); P1-21/P1-24/P1-25/P1-28
// (INT-02B) pasan por el parser ESTRICTO ya existente de su definición candidata (candidate-form.ts), sin relajar ninguno. El backend
// (INT-01A) ya filtra qué formularios llegan por esta ruta: registrar aquí su visor NO los habilita ni cambia su disponibilidad.
const GET_TIMEOUT_MS = 10000;
const VIEWERS: HistoryViewers = {
    [Q19_FORM_CODE]: humidityViewer(parseQualityCapture), [Q20_FORM_CODE]: physicalViewer(parsePhysicalCapture),
    [P1_21_CODE]: candidateViewer(P121.parseCapture), [P1_24_CODE]: candidateViewer(P124.parseCapture),
    [P1_25_CODE]: candidateViewer(P125.parseCapture), [P1_28_CODE]: candidateViewer(P128.parseCapture),
};

// Cancelación del llamador (cambio de Bobina, Volver, cierre de sesión) + tiempo máximo. Un AbortError se propaga y useResource lo ignora.
function withTimeout(signal: AbortSignal): AbortSignal {
    return typeof AbortSignal.any === "function" ? AbortSignal.any([signal, AbortSignal.timeout(GET_TIMEOUT_MS)]) : signal;
}

export async function getQualityBobbinHistory(bobbin: ExpectedBobbin, signal: AbortSignal): Promise<ApiResult<QualityHistoryLoad>> {
    const result = await requestJson(`/api/quality/bobbins/${encodeURIComponent(bobbin.id)}/captures`, { signal: withTimeout(signal) },
        (raw) => parseQualityBobbinHistory(raw, bobbin, VIEWERS));
    if (!result.ok && result.kind === "session") return result;
    return { ok: true, status: result.status, data: qualityHistoryLoad(bobbin.id, result) };
}
