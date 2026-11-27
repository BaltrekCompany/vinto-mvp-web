import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseTubetesReport, type TubetesReport } from "@/lib/vinto/tubetes-report";

// GET sin filtros: el servidor determina BOBINAS/MP1/MP3 y valida report.read + sector.
// requestJson usa cookie HttpOnly, credentials include y cache no-store.
export function getTubetesReport(signal?: AbortSignal): Promise<ApiResult<TubetesReport>> {
    return requestJson("/api/reports/tubetes-used", { signal }, parseTubetesReport);
}
