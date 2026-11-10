import { requestJson } from "./central-http.ts";
import { parsePalletPreview } from "./pallet-weight.ts";
export { parsePalletPreview, previewTotalKg } from "./pallet-weight.ts";
export type { PalletPreview } from "./pallet-weight.ts";

export const getPalletPreview = (assignmentId: string, signal?: AbortSignal) =>
    requestJson(`/api/production/pallet-preview?assignment_id=${encodeURIComponent(assignmentId)}`, { signal }, parsePalletPreview);
