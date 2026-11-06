import { requestJson, type ApiResult } from "@/lib/vinto/central-http";
import { parseMachineExecution, type MachineExecution } from "@/lib/vinto/machine-execution";

// Server resolves machine scope and assignment -> OT baseline state. No client
// sends an OT, product, actor, line status or operation permission.
export function getMachineExecution(machineCode: string, signal?: AbortSignal): Promise<ApiResult<MachineExecution>> {
    return requestJson("/api/assignments/execution-status?machine_code=" + encodeURIComponent(machineCode),
        { signal }, parseMachineExecution);
}
