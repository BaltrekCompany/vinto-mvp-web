/** OFF-04.8I — TEST-ONLY real-browser driver for the operational encrypted IndexedDB.
 * Bundled only with OFFLINE_DRAFT_LAB=1, NEVER mounted in VINTO app.
 * The synthetic values used here are inert; no backend, endpoint or network sender.
 */
import {createOperationalLocalStore} from "./offline-operational-local-store.ts";
import {createLocalVault,unlockLocalVault,sealLocalDraft,openLocalDraft,
  type OfflineVaultIdentity,type OfflineVaultRecord,type DraftBinding} from "./offline-vault.ts";
import {payloadHash} from "./offline-sync-engine.ts";
import type {OperationalDraftRow,OperationalPendingRow} from "./offline-operational-model.ts";
import type {SyncRecord} from "./offline-sync-types.ts";
const store=createOperationalLocalStore();
let localKey:CryptoKey|null=null;
let identity:OfflineVaultIdentity|null=null;
const storageKey="off048i-test-wrapped-vault";
function ensureIdentity():OfflineVaultIdentity {
 if(!identity || !localKey)throw Error("test vault is locked");
 return identity;
}
const aad=(id:string,contextId:string,formCode:string,formVersion:number):DraftBinding=>({
 ...ensureIdentity(),id,contextId,formCode,formVersion
});
async function enroll(ownerId:string,deviceKey:string,passphrase:string) {
 identity={ownerId,deviceKey};
 const v=await createLocalVault(identity,passphrase);
 localKey=v.key;
 window.localStorage.setItem(storageKey,JSON.stringify(v.record));
 return {ready:true};
}
async function unlock(passphrase:string) {
 const raw=window.localStorage.getItem(storageKey);
 if(!raw)throw Error("wrapped vault missing");
 const saved=JSON.parse(raw) as OfflineVaultRecord;
 identity={ownerId:saved.ownerId,deviceKey:saved.deviceKey};
 localKey=await unlockLocalVault(saved,passphrase);
 return {ready:true};
}
async function saveDraft(args:{id:string;revision:number;expectedRevision:number|null;scopeId:string;formCode:string;formVersion:number;machineCode:string;content:Record<string,unknown>}) {
 if(!localKey)throw Error("locked");
 const owner=ensureIdentity();
 const sealed=await sealLocalDraft(localKey,aad(args.id,args.scopeId,args.formCode,args.formVersion),args.content);
 const row:OperationalDraftRow={id:args.id,ownerId:owner.ownerId,deviceKey:owner.deviceKey,
  revision:args.revision,machineCode:args.machineCode,formCode:args.formCode,
  formVersion:args.formVersion,scopeSnapshotId:args.scopeId,contextVersion:args.scopeId,
  frozenBy:null,sealed,updatedAt:new Date().toISOString()};
 await store.saveDraft(row,args.expectedRevision);
 return {revision:row.revision};
}
async function openDraft(id:string){
 if(!localKey)throw Error("locked");
 const row=await store.getDraft(id);
 if(!row)return null;
 const payload=await openLocalDraft(localKey,aad(row.id,row.scopeSnapshotId,row.formCode,row.formVersion),row.sealed);
 return {revision:row.revision,frozenBy:row.frozenBy,payload};
}
async function confirm(args:{draftId:string;captureId:string;revision:number}) {
 if(!localKey)throw Error("locked");
 const row=await store.getDraft(args.draftId);
 if(!row)throw Error("draft missing");
 const owner=ensureIdentity();
 const content={synthetic:false,payload:{test:"operational-synthetic-only",revision:args.revision}};
 const encrypted=await sealLocalDraft(localKey,aad(args.captureId,row.scopeSnapshotId,row.formCode,row.formVersion),content);
 const sha=await payloadHash(content);
 const iso=new Date().toISOString();
 const pending:OperationalPendingRow={
  capture_id:args.captureId,sourceDraftId:args.draftId,sourceRevision:args.revision,
  ownerId:owner.ownerId,deviceKey:owner.deviceKey,payloadSha256:sha,
  synthetic:false,sealed:encrypted,createdAt:iso
 };
 const queue:SyncRecord={
  capture_id:args.captureId,ownerId:owner.ownerId,deviceKey:owner.deviceKey,
  seq:1,dependsOn:null,formCode:row.formCode,formVersion:row.formVersion,
  machineCode:row.machineCode,scopeSnapshotId:row.scopeSnapshotId,contextVersion:row.contextVersion,
  payloadSha256:sha,sealed:encrypted,state:"queued",attempts:0,nextAttemptAt:null,
  uncertain:false,lease:null,version:1,lastError:null,serverRef:null,warnings:[],createdAt:iso,updatedAt:iso,
 };
 return store.confirm(args.revision,row.sealed.ciphertext,pending,queue);
}
async function inspect(){
 const owner=ensureIdentity();
 const [drafts,pendings,queued]=await Promise.all([
  store.listDrafts(owner.ownerId,owner.deviceKey),
  store.listPending(owner.ownerId,owner.deviceKey),
  store.sync.list(owner.ownerId,owner.deviceKey)
 ]);
 return {drafts:drafts.map(x=>({id:x.id,revision:x.revision,frozenBy:x.frozenBy,
  ciphertext:x.sealed.ciphertext})),
  pending:pendings.map(x=>({id:x.capture_id,sourceRevision:x.sourceRevision,synthetic:x.synthetic})),
  queue:queued.map(x=>({id:x.capture_id,state:x.state,attempts:x.attempts}))};
}
async function claim(captureId:string,tab:string) {
 return store.sync.claim(captureId,tab,Date.now(),30000);
}
async function finalize(captureId:string,tab:string){
 return store.sync.finalize(captureId,tab,{state:"synced",lastError:null,uncertain:false},Date.now());
}
async function openPending(captureId:string) {
 if(!localKey)throw Error("locked");
 const owner=ensureIdentity();
 const row=(await store.sync.get(captureId));
 if(!row)return null;
 if(row.ownerId!==owner.ownerId||row.deviceKey!==owner.deviceKey)throw Error("identity mismatch");
 return openLocalDraft(localKey,aad(row.capture_id,row.scopeSnapshotId!,row.formCode,row.formVersion),row.sealed);
}
(window as unknown as Record<string,unknown>).VINTO_OFF048I={
 enroll,unlock,saveDraft,openDraft,confirm,inspect,claim,finalize,openPending,
 };
