import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { Q19_FORM_CODE, parseQualityCapture } from "@/lib/vinto/quality-captures";
import { humidityViewer, parseQualityBobbinHistory, physicalViewer, qualityHistoryLoad, type ExpectedBobbin, type HistoryViewers, type QualityHistoryLoad } from "@/lib/vinto/quality-history";
import { Q20_FORM_CODE, parsePhysicalCapture } from "@/lib/vinto/quality-physical";

// Historial de controles de Calidad de una Bobina: SOLO GET /api/quality/bobbins/{id}/captures. Cookie HttpOnly vía requestJson (credentials
// "include"); sin tokens, sin almacenamiento local. P1-19 y P1-20 pasan por SUS parsers estrictos (Q2 y Q3.2-B), sin relajarlos.
// Un 401 se devuelve como fallo para que useResource dispare el flujo de sesión perdida; el resto de resultados (incluidos 403, 404, red y
// respuesta inválida) se entregan clasificados con la Bobina a la que pertenecen, para no mostrarlos nunca en otra Bobina.

const GET_TIMEOUT_MS = 10000;
const VIEWERS: HistoryViewers = { [Q19_FORM_CODE]: humidityViewer(parseQualityCapture), [Q20_FORM_CODE]: physicalViewer(parsePhysicalCapture) };

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
