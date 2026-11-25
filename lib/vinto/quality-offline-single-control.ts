/** Presentation-level one-control-per-bobbin projection.
 * Do not delete historical drafts or redefine the operational capture identity.
 * Machine controls remain repeatable pending a separate periodicity decision.
 */
import type {SyncRecord,SyncState} from "./offline-sync-types";
import type {OperationalPendingRow} from "./offline-operational-model";

export type BobbinFormRef=Readonly<{
 id:string;machineCode:string;formCode:string;bobbinId:string|null;
}>;
export type ControlStatus="completed"|"pending"|"review"|"editable";
export type VisibleControl<T extends BobbinFormRef>=Readonly<{
 item:T;status:ControlStatus;duplicates:number;
}>;
const completed=new Set<SyncState>(["synced","synced_warning"]);
const pending=new Set<SyncState>(["queued","retry_wait","syncing"]);
const priority:Readonly<Record<ControlStatus,number>>={
 completed:4,pending:3,review:2,editable:1,
};
export function controlKey(item:BobbinFormRef):string{
 return item.machineCode+"|"+item.formCode+"|"+(item.bobbinId??"machine");
}
export function projectOfflineControls<T extends BobbinFormRef>(
 preparations:readonly T[],pendingRows:readonly OperationalPendingRow[],
 queue:readonly SyncRecord[],
):VisibleControl<T>[]{
 const captureByDraft=new Map(pendingRows.map(p=>[p.sourceDraftId,p.capture_id]));
 const queueById=new Map(queue.map(q=>[q.capture_id,q]));
 const groups=new Map<string,VisibleControl<T>>();
 for(const item of preparations){
  const captureId=captureByDraft.get(item.id);
  const state=captureId?queueById.get(captureId)?.state:undefined;
  const status:ControlStatus=state&&completed.has(state)?"completed":
   state&&pending.has(state)?"pending":
   state==="conflict"||state==="requires_review"?"review":"editable";
  // One visible control per form + bobbin, even if old drafts accumulated.
  const key=controlKey(item);
  const previous=groups.get(key);
  if(!previous){
   groups.set(key,{item,status,duplicates:0});
  }else{
   const keepNew=priority[status]>priority[previous.status];
   groups.set(key,{
    item:keepNew?item:previous.item,
    status:keepNew?status:previous.status,
    duplicates:previous.duplicates+1,
   });
  }
 }
 return [...groups.values()];
}
export function isBobbinControlLocked<T extends BobbinFormRef>(
 controls:readonly VisibleControl<T>[],candidate:BobbinFormRef,
):boolean{
 return candidate.bobbinId!==null&&controls.some(c=>
  controlKey(c.item)===controlKey(candidate)&&
  (c.status==="completed"||c.status==="pending"||c.status==="review"));
}
