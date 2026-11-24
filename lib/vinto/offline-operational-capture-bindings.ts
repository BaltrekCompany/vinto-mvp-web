/** OFF-04.8L — operational encrypted draft adapter (opt-in, never mounted).
 *
 * The ten Quality forms use a signed, capture-capable definition checked by
 * the injected authority verifier. The client may save an editable encrypted
 * draft and confirm it once. Data and owner are NEVER replaced with a fixture.
 * This adapter only writes LOCAL IndexedDB. Backend authorization and actual
 * operational registration remain independently mandatory on upload.
 */
import { sealLocalDraft, openLocalDraft, type DraftBinding, type OfflineVaultIdentity } from "./offline-vault.ts";
import { payloadHash } from "./offline-sync-engine.ts";
import { operationalCaptureId } from "./offline-operational-id.ts";
import type { OperationalLocalStore } from "./offline-operational-local-store.ts";
import { OperationalLocalError, type OperationalDraftRow, type OperationalPendingRow } from "./offline-operational-model.ts";
import type { SyncRecord } from "./offline-sync-types.ts";

export type OperationalFormContext=Readonly<{
  draftId:string;machineCode:string;formCode:string;formVersion:number;
  scopeSnapshotId:string;contextVersion:string;
  bobbin?:Readonly<{bobbin_id:string;context_digest:string}>;
}>;
export type OperationalCaptureBindingsDeps=Readonly<{
  key:CryptoKey;
  identity:OfflineVaultIdentity;
  context:OperationalFormContext;
  store:OperationalLocalStore;
  /** Verify signed CAPTURE authority, current owner/device/form/version/machine
   * and offline validity; readiness-only QA scope MUST fail here.
   * A separate server-side check is always required at sync time.
   */
  assertCaptureScope:()=>Promise<void>;
  /** Run the same editable-field / required-field checks as Quality online.
   * Must reject calculated, unknown, malformed and incomplete field values.
   */
  validateComplete:(values:Readonly<Record<string,string|boolean>>)=>void;
  /** Reference known at offline preparation; cannot be changed during editing. */
  now?:()=>number;
}>;

const binding=(id:OfflineVaultIdentity,ctx:OperationalFormContext,draftOrCaptureId:string):DraftBinding=>({
  ...id,id:draftOrCaptureId,contextId:ctx.scopeSnapshotId,formCode:ctx.formCode,formVersion:ctx.formVersion,
});
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();

export function createOperationalCaptureBindings(deps:OperationalCaptureBindingsDeps){
  const {key,identity,context,store}=deps;
  const now=deps.now??Date.now;
  const assertRow=(row:OperationalDraftRow)=>{
    if(!same(row.ownerId,identity.ownerId)||!same(row.deviceKey,identity.deviceKey)||
      row.id!==context.draftId||row.formCode!==context.formCode||
      row.formVersion!==context.formVersion||row.machineCode!==context.machineCode||
      row.scopeSnapshotId!==context.scopeSnapshotId||row.contextVersion!==context.contextVersion)
      throw new OperationalLocalError("conflict");
  };
  const readValues=async(row:OperationalDraftRow):Promise<Record<string,string|boolean>>=>{
    assertRow(row);
    const original=await openLocalDraft(key,binding(identity,context,row.id),row.sealed);
    if(!original||typeof original!=="object"||Array.isArray(original))throw new OperationalLocalError("corrupt");
    // No synthetic wrapper or internal field is allowed inside the editor values.
    const values:Record<string,string|boolean>={};
    for(const [k,v] of Object.entries(original)){
      if(typeof v!=="string"&&typeof v!=="boolean")throw new OperationalLocalError("invalid");
      values[k]=v;
    }
    return values;
  };
  return {
    /** Used by autosave.persist; revision and storage CAS remain authoritative. */
    async persist(snapshot:Readonly<{draftId:string;ownerId:string;revision:number|null;values:Readonly<Record<string,string|boolean>>}>){
      if(!same(snapshot.ownerId,identity.ownerId)||snapshot.draftId!==context.draftId)
        throw new OperationalLocalError("conflict");
      // Editable drafts are NOT operational captures. A lapse in network or
      // signed-scope renewal must never discard the operator's unfinished
      // measurements. Capture authority is mandatory at freeze/upload time.
      const prev=await store.getDraft(context.draftId);
      if(prev)assertRow(prev);
      const revision=(snapshot.revision??0)+1;
      // Don't check required fields here: unfinished forms must be recoverable.
      const sealed=await sealLocalDraft(key,binding(identity,context,context.draftId),snapshot.values);
      const row:OperationalDraftRow={
        id:context.draftId,ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
        revision,machineCode:context.machineCode,formCode:context.formCode,formVersion:context.formVersion,
        scopeSnapshotId:context.scopeSnapshotId,contextVersion:context.contextVersion,
        frozenBy:null,sealed,updatedAt:new Date(now()).toISOString(),
      };
      await store.saveDraft(row,snapshot.revision);
      return {revision};
    },
    /** Used by the one Guardar captura button AFTER editor is locked & flush is durable.
     * No second bridge/enqueue action is necessary: confirm() is one transaction.
     */
    async freeze(expectedRevision:number){
      await deps.assertCaptureScope();
      const row=await store.getDraft(context.draftId);
      if(!row)throw new OperationalLocalError("missing");
      assertRow(row);
      if(row.revision!==expectedRevision)throw new OperationalLocalError("conflict");
      const values=await readValues(row);
      deps.validateComplete(values);
      const captureId=await operationalCaptureId(identity.ownerId,identity.deviceKey,context.draftId);
      if(row.frozenBy!==null&&row.frozenBy!==captureId)throw new OperationalLocalError("conflict");
      const payload={synthetic:false,payload:values,
        ...(context.bobbin?{bobbin:context.bobbin}:{})};
      const sealed=await sealLocalDraft(key,binding(identity,context,captureId),payload);
      const sha=await payloadHash(payload);
      const timestamp=new Date(now()).toISOString();
      const pending:OperationalPendingRow={
        capture_id:captureId,sourceDraftId:context.draftId,sourceRevision:expectedRevision,
        ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
        synthetic:false,payloadSha256:sha,sealed,createdAt:timestamp,
      };
      const queue:SyncRecord={
        capture_id:captureId,ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
        seq:now(),dependsOn:null,formCode:context.formCode,formVersion:context.formVersion,
        machineCode:context.machineCode,scopeSnapshotId:context.scopeSnapshotId,contextVersion:context.contextVersion,
        payloadSha256:sha,state:"queued",attempts:0,nextAttemptAt:null,uncertain:false,
        lease:null,version:1,lastError:null,serverRef:null,warnings:[],
        sealed,createdAt:timestamp,updatedAt:timestamp,
      };
      return store.confirm(expectedRevision,row.sealed.ciphertext,pending,queue);
    },
    async resume(){
      const row=await store.getDraft(context.draftId);
      if(!row)return null;
      const values=await readValues(row);
      return {revision:row.revision,frozen:row.frozenBy!==null,values};
    },
  };
}
