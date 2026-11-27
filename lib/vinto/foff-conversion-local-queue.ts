/** FOFF-03 — isolated, AES-GCM encrypted Conversion submission queue.
 * No credentials, unsealed values, signing keys or demo fallback on disk.
 * The creator must first verify BOTH server-issued pinned signatures and
 * the signed form reference package. No automatic industrial writes here.
 */
import {openLocalDraft,sealLocalDraft,type OfflineVaultIdentity,type DraftBinding} from "./offline-vault.ts";
import {canonicalOfflineJson} from "./offline-scope-verify.ts";
import type {VerifiedConversionPreparation} from "./foff-conversion-preparation-verify.ts";
import type {VerifiedConversionCapture} from "./foff-conversion-capture-authority-verify.ts";

export const CONVERSION_QUEUE_DB="vinto-foff-conversion-queue-v1";
const STORE="pending";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA=/^[a-f0-9]{64}$/;
const FORM=/^VINTO-P1-(11|12|13|16)$/;
export type ConversionQueueState="queued"|"requires_review"|"synced";
type Sealed=Readonly<{format:"aes-gcm-v1";iv:string;ciphertext:string}>;
export type ConversionQueueRow=Readonly<{
  captureId:string;ownerId:string;deviceKey:string;assignmentId:string;
  machineCode:string;formCode:string;formVersion:number;scopeSnapshotId:string;
  payloadSha256:string;sealed:Sealed;state:ConversionQueueState;createdAt:string;
}>;
export type ConversionQueuePayload=Readonly<{
  capture_id:string;author_user_id:string;device_key:string;
  form_code:string;form_version:number;assignment_id:string;machine_code:string;
  scope_snapshot_id:string;payload_sha256:string;values:Record<string,unknown>;
  preparation:Record<string,unknown>;capture_authority:Record<string,unknown>;
  reference_package:Record<string,unknown>;client_captured_at:string;
}>;
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
const fail=(code:string):never=>{throw new Error("foff_conversion_queue_"+code);};
const hex=(a:Uint8Array)=>Array.from(a,b=>b.toString(16).padStart(2,"0")).join("");
function binding(identity:OfflineVaultIdentity,row:ConversionQueueRow):DraftBinding{
  return {ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
    id:row.captureId,contextId:row.scopeSnapshotId,formCode:row.formCode,formVersion:row.formVersion};
}
function check(identity:OfflineVaultIdentity,row:ConversionQueueRow){
  if(!UUID.test(identity.ownerId)||!UUID4.test(identity.deviceKey)||
     !UUID4.test(row.captureId)||!UUID.test(row.assignmentId)||
     !UUID4.test(row.scopeSnapshotId)||!FORM.test(row.formCode)||
     !Number.isSafeInteger(row.formVersion)||row.formVersion<1||
     !SHA.test(row.payloadSha256)||!same(identity.ownerId,row.ownerId)||
     !same(identity.deviceKey,row.deviceKey))fail("invalid");
}
async function withDb<T>(fn:(db:IDBDatabase)=>Promise<T>):Promise<T>{
  if(typeof indexedDB==="undefined")return fail("unavailable");
  const db=await new Promise<IDBDatabase>((ok,bad)=>{
    const req=indexedDB.open(CONVERSION_QUEUE_DB,1);
    req.onupgradeneeded=()=>{
      if(!req.result.objectStoreNames.contains(STORE))
        req.result.createObjectStore(STORE,{keyPath:"captureId"}).createIndex("ownerDevice",["ownerId","deviceKey"]);
    };
    req.onsuccess=()=>{req.result.onversionchange=()=>req.result.close();ok(req.result);};
    req.onerror=()=>bad(new Error("foff_conversion_queue_storage"));
    req.onblocked=()=>bad(new Error("foff_conversion_queue_storage"));
  });
  try{return await fn(db);}finally{db.close();}
}
function tx<T>(db:IDBDatabase,mode:IDBTransactionMode,
  run:(store:IDBObjectStore,done:(v:T)=>void,fail:(e:Error)=>void)=>void):Promise<T>{
  return new Promise((resolve,reject)=>{
    const transaction=db.transaction(STORE,mode);let result!:T,ready=false;
    transaction.oncomplete=()=>ready?resolve(result):reject(new Error("foff_conversion_queue_storage"));
    transaction.onabort=()=>reject(new Error("foff_conversion_queue_storage"));
    transaction.onerror=()=>reject(new Error("foff_conversion_queue_storage"));
    run(transaction.objectStore(STORE),v=>{result=v;ready=true;},error=>{try{transaction.abort();}catch{}reject(error);});
  });
}
export async function enqueueConversionCapture(input:{
  identity:OfflineVaultIdentity;key:CryptoKey;captureId:string;
  preparation:VerifiedConversionPreparation;captureAuthority:VerifiedConversionCapture;
  formCode:string;formVersion:number;machineCode:string;assignmentId:string;
  values:Record<string,unknown>;preparationEnvelope:Record<string,unknown>;
  authorityEnvelope:Record<string,unknown>;referencePackage:Record<string,unknown>;
}):Promise<ConversionQueueRow>{
  const {identity,preparation,captureAuthority}=input;
  if(!globalThis.crypto?.subtle||!UUID4.test(input.captureId)||
     !same(captureAuthority.snapshotId,preparation.snapshotId)||
     !same(input.assignmentId,preparation.context.assignment_id)||
     input.formCode!==preparation.context.form_code||
     input.formVersion!==preparation.context.form_version||
     input.machineCode!==preparation.context.machine_code||
     !UUID.test(identity.ownerId)||!UUID4.test(identity.deviceKey))
    fail("scope");
  let sha:string;
  try{sha=hex(new Uint8Array(await crypto.subtle.digest("SHA-256",
    new TextEncoder().encode(canonicalOfflineJson(input.values)))));}
  catch{fail("invalid_values");}
  const rowWithoutSeal={
    captureId:input.captureId,ownerId:identity.ownerId.toLowerCase(),
    deviceKey:identity.deviceKey.toLowerCase(),assignmentId:input.assignmentId,
    machineCode:input.machineCode,formCode:input.formCode,formVersion:input.formVersion,
    scopeSnapshotId:preparation.snapshotId,payloadSha256:sha,
    state:"queued" as const,createdAt:new Date().toISOString(),
  };
  const row:ConversionQueueRow={...rowWithoutSeal,sealed:await sealLocalDraft(input.key,
    binding(identity,{...rowWithoutSeal,sealed:{format:"aes-gcm-v1",iv:"",ciphertext:""}}),
    {capture_id:input.captureId,author_user_id:identity.ownerId,device_key:identity.deviceKey,
      form_code:input.formCode,form_version:input.formVersion,assignment_id:input.assignmentId,
      machine_code:input.machineCode,scope_snapshot_id:preparation.snapshotId,
      payload_sha256:sha,values:input.values,preparation:input.preparationEnvelope,
      capture_authority:input.authorityEnvelope,reference_package:input.referencePackage,
      client_captured_at:rowWithoutSeal.createdAt})};
  check(identity,row);
  return withDb(db=>tx(db,"readwrite",(store,done,reject)=>{
    const req=store.add(row);req.onsuccess=()=>done(row);
    req.onerror=()=>reject(new Error("foff_conversion_queue_conflict"));
  }));
}
export async function listConversionQueue(identity:OfflineVaultIdentity):Promise<ConversionQueueRow[]>{
  if(!UUID.test(identity.ownerId)||!UUID4.test(identity.deviceKey))fail("identity");
  return withDb(db=>tx(db,"readonly",(store,done,reject)=>{
    const req=store.index("ownerDevice").getAll([identity.ownerId.toLowerCase(),identity.deviceKey.toLowerCase()]);
    req.onsuccess=()=>done(req.result as ConversionQueueRow[]);
    req.onerror=()=>reject(new Error("foff_conversion_queue_storage"));
  }));
}
export async function readConversionQueuePayload(identity:OfflineVaultIdentity,key:CryptoKey,row:ConversionQueueRow):Promise<ConversionQueuePayload>{
  check(identity,row);
  const payload=await openLocalDraft(key,binding(identity,row),row.sealed);
  if(payload.capture_id!==row.captureId||payload.author_user_id!==row.ownerId||
     payload.device_key!==row.deviceKey||payload.assignment_id!==row.assignmentId||
     payload.form_code!==row.formCode||payload.form_version!==row.formVersion||
     payload.machine_code!==row.machineCode||payload.scope_snapshot_id!==row.scopeSnapshotId||
     payload.payload_sha256!==row.payloadSha256||!payload.values||
     typeof payload.values!=="object"||Array.isArray(payload.values))
    fail("tampered");
  return payload as unknown as ConversionQueuePayload;
}
export async function markConversionQueue(identity:OfflineVaultIdentity,captureId:string,
  expectedSha:string,state:ConversionQueueState):Promise<void>{
  if(!UUID4.test(captureId)||!SHA.test(expectedSha)||!["synced","requires_review"].includes(state))
    fail("invalid");
  return withDb(db=>tx<void>(db,"readwrite",(store,done,reject)=>{
    const read=store.get(captureId);
    read.onsuccess=()=>{
      const row=read.result as ConversionQueueRow|undefined;
      if(!row){reject(new Error("foff_conversion_queue_missing"));return;}
      try{check(identity,row);}catch{reject(new Error("foff_conversion_queue_identity"));return;}
      if(row.payloadSha256!==expectedSha||row.state!=="queued"){
        reject(new Error("foff_conversion_queue_conflict"));return;
      }
      const put=store.put({...row,state});
      put.onsuccess=()=>done(undefined);
      put.onerror=()=>reject(new Error("foff_conversion_queue_storage"));
    };
    read.onerror=()=>reject(new Error("foff_conversion_queue_storage"));
  }));
}
