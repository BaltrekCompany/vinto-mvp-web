import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseQualityBobbinInbox, type QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";

// Inbox central de Calidad: SOLO lectura. Cookie HttpOnly vía requestJson (credentials "include"); sin tokens ni cabeceras manuales.
// La interfaz solicita además todas las hermanas de una madre con al menos una cría pendiente.
// F3 y los filtros status de la API legada permanecen sin cambios.

export function listQualityBobbins(signal?: AbortSignal, allMothers = false): Promise<ApiResult<QualityBobbinInboxItem[]>> {
    const url = "/api/quality/bobbins?include_rewinding_family=true" +
        (allMothers ? "&include_completed_mothers=true" : "");
    return requestJson(url, { signal }, parseQualityBobbinInbox);
}
