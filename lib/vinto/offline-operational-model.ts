/** OFF-04.8H: pure rules for the future operational encrypted IndexedDB store.
 * No auth decision lives here. A caller must validate the SIGNED capture-capable
 * snapshot before making a draft; the server checks it AGAIN on upload.
 * The old synthetic laboratory records are structurally incompatible.
 */
import { isSyncRecord } from "./offline-queue-record.ts";
import type { SyncRecord } from "./offline-sync-types.ts";
export type Sealed = Readonly<{format:"aes-gcm-v1";iv:string;ciphertext:string}>;
export type OperationalDraftRow = Readonly<{
  id:string;ownerId:string;deviceKey:string;revision:number;
  machineCode:string;formCode:string;formVersion:number;
  scopeSnapshotId:string;contextVersion:string;
  frozenBy:string|null;sealed:Sealed;updatedAt:string;
}>;
export type OperationalPendingRow = Readonly<{
  capture_id:string;sourceDraftId:string;sourceRevision:number;
  ownerId:string;deviceKey:string;payloadSha256:string;
  synthetic:false;sealed:Sealed;createdAt:string;
}>;
export class OperationalLocalError extends Error {
  readonly reason:"invalid"|"conflict"|"frozen"|"missing"|"corrupt"|"unavailable"|"storage";
  constructor(reason:OperationalLocalError["reason"]) {
    super("OFF048_OPERATIONAL_LOCAL_"+reason.toUpperCase());
    this.reason=reason;
  }
}
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA=/^[0-9a-f]{64}$/;
const sealed=(x:unknown):x is Sealed=>{
  if(!x||typeof x!=="object")return false;
  const s=x as Record<string,unknown>;
  return s.format==="aes-gcm-v1"&&typeof s.iv==="string"&&s.iv.length>0&&typeof s.ciphertext==="string"&&s.ciphertext.length>0;
};
const eq=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
export function validOperationalDraft(x:unknown):x is OperationalDraftRow {
  if(!x||typeof x!=="object")return false;
  const d=x as Record<string,unknown>;
  return typeof d.id==="string"&&UUID.test(d.id)&&typeof d.ownerId==="string"&&UUID.test(d.ownerId)&&
    typeof d.deviceKey==="string"&&UUID.test(d.deviceKey)&&Number.isSafeInteger(d.revision)&&(d.revision as number)>0&&
    typeof d.machineCode==="string"&&d.machineCode.length>0&&typeof d.formCode==="string"&&/^VINTO-P1-(18|19|20|21|22|24|25|26|27|28)$/.test(d.formCode)&&
    Number.isSafeInteger(d.formVersion)&&(d.formVersion as number)>0&&
    typeof d.scopeSnapshotId==="string"&&UUID.test(d.scopeSnapshotId)&&
    typeof d.contextVersion==="string"&&d.contextVersion.length>0&&
    (d.frozenBy===null||(typeof d.frozenBy==="string"&&UUID.test(d.frozenBy)))&&
    typeof d.updatedAt==="string"&&Number.isFinite(Date.parse(d.updatedAt))&&sealed(d.sealed);
}
export function validOperationalPending(x:unknown):x is OperationalPendingRow {
  if(!x||typeof x!=="object")return false;
  const p=x as Record<string,unknown>;
  return p.synthetic===false&&typeof p.capture_id==="string"&&UUID.test(p.capture_id)&&
    typeof p.sourceDraftId==="string"&&UUID.test(p.sourceDraftId)&&
    Number.isSafeInteger(p.sourceRevision)&&(p.sourceRevision as number)>0&&
    typeof p.ownerId==="string"&&UUID.test(p.ownerId)&&typeof p.deviceKey==="string"&&UUID.test(p.deviceKey)&&
    typeof p.payloadSha256==="string"&&SHA.test(p.payloadSha256)&&
    typeof p.createdAt==="string"&&Number.isFinite(Date.parse(p.createdAt))&&sealed(p.sealed);
}
export function nextOperationalDraft(current:unknown,incoming:OperationalDraftRow,expected:number|null):OperationalDraftRow {
  if(!validOperationalDraft(incoming)||incoming.frozenBy!==null)throw new OperationalLocalError("invalid");
  if(current===undefined) {
    if(expected!==null||incoming.revision!==1)throw new OperationalLocalError("conflict");
    return incoming;
  }
  if(!validOperationalDraft(current))throw new OperationalLocalError("corrupt");
  if(current.frozenBy!==null)throw new OperationalLocalError("frozen");
  if(expected!==current.revision||incoming.revision!==current.revision+1)throw new OperationalLocalError("conflict");
  for(const k of ["id","ownerId","deviceKey","machineCode","formCode","formVersion","scopeSnapshotId","contextVersion"] as const){
    if(current[k]!==incoming[k])throw new OperationalLocalError("conflict");
  }
  return incoming;
}
/** A single atomic draft+pending+queue write, no bridge button. */
export function decideOperationalFreeze(
  current:unknown,existingPending:unknown,existingQueue:unknown,
  expectedRevision:number,expectedCiphertext:string,pending:OperationalPendingRow,queue:SyncRecord,
):{created:boolean;draft:OperationalDraftRow;pending:OperationalPendingRow;queue:SyncRecord}{
  if(!validOperationalDraft(current)||!validOperationalPending(pending)||!isSyncRecord(queue))throw new OperationalLocalError("invalid");
  if(pending.sourceDraftId!==current.id||pending.sourceRevision!==expectedRevision||
    !eq(pending.ownerId,current.ownerId)||!eq(pending.deviceKey,current.deviceKey)||
    pending.capture_id!==queue.capture_id||queue.ownerId!==pending.ownerId||queue.deviceKey!==pending.deviceKey||
    queue.payloadSha256!==pending.payloadSha256||queue.sealed.iv!==pending.sealed.iv||
    queue.sealed.ciphertext!==pending.sealed.ciphertext||
    queue.formCode!==current.formCode||queue.formVersion!==current.formVersion||
    queue.machineCode!==current.machineCode||queue.scopeSnapshotId!==current.scopeSnapshotId||
    queue.contextVersion!==current.contextVersion||queue.state!=="queued"||queue.attempts!==0||
    queue.lease!==null||queue.uncertain||!eq(pending.sourceDraftId,current.id))
    throw new OperationalLocalError("conflict");
  if(current.frozenBy!==null){
    if(current.frozenBy!==pending.capture_id||!validOperationalPending(existingPending)||
      existingPending.sourceDraftId!==current.id||existingPending.sourceRevision!==expectedRevision||
      existingPending.payloadSha256!==pending.payloadSha256||
      existingPending.ownerId!==pending.ownerId||existingPending.deviceKey!==pending.deviceKey||
      !isSyncRecord(existingQueue)||existingQueue.capture_id!==pending.capture_id||
      existingQueue.ownerId!==pending.ownerId||existingQueue.deviceKey!==pending.deviceKey||
      existingQueue.payloadSha256!==pending.payloadSha256)
      throw new OperationalLocalError("corrupt");
    return {created:false,draft:current,pending:existingPending,queue:existingQueue};
  }
  if(current.revision!==expectedRevision||current.sealed.ciphertext!==expectedCiphertext)
    throw new OperationalLocalError("conflict");
  if(existingPending!==undefined||existingQueue!==undefined)throw new OperationalLocalError("conflict");
  return {created:true,draft:{...current,frozenBy:pending.capture_id},pending,queue};
}
