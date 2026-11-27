/** FOFF-03: encrypted autosaved conversion DRAFTS.
 * One stable captureId is reserved at first save, never regenerated on retries.
 * The draft is private to the original author/device/signed preparation.
 * Never stores an unencrypted form or credentials in IndexedDB.
 */
import {openLocalDraft,sealLocalDraft,type DraftBinding,type OfflineVaultIdentity} from "./offline-vault.ts";
const NAME="vinto-foff-conversion-drafts-v1";
const STORE="drafts";
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const UUID4=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const FORM=/^VINTO-P1-(11|12|13|16)$/;
type Sealed=Readonly<{format:"aes-gcm-v1";iv:string;ciphertext:string}>;
export type ConversionDraftRow=Readonly<{
  captureId:string;ownerId:string;deviceKey:string;preparationId:string;
  assignmentId:string;machineCode:string;formCode:string;formVersion:number;
  revision:number;sealed:Sealed;updatedAt:string;
}>;
export type ConversionDraftValues=Readonly<{values:Record<string,unknown>}>;
const fail=(reason:string):never=>{throw new Error("foff_conversion_draft_"+reason);};
function check(identity:OfflineVaultIdentity,row:ConversionDraftRow){
  if(!UUID.test(identity.ownerId)||!UUID4.test(identity.deviceKey)||!UUID4.test(row.captureId)||
     !UUID4.test(row.preparationId)||!UUID.test(row.assignmentId)||!FORM.test(row.formCode)||
     !Number.isSafeInteger(row.formVersion)||row.formVersion<1||
     identity.ownerId.toLowerCase()!==row.ownerId||identity.deviceKey.toLowerCase()!==row.deviceKey)fail("identity");
}
function binding(row:ConversionDraftRow):DraftBinding{
  return {ownerId:row.ownerId,deviceKey:row.deviceKey,id:row.captureId,
    contextId:row.preparationId,formCode:row.formCode,formVersion:row.formVersion};
}
async function withDb<T>(fn:(db:IDBDatabase)=>Promise<T>):Promise<T>{
  if(typeof indexedDB==="undefined")return fail("unavailable");
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{
    const request=indexedDB.open(NAME,1);
    request.onupgradeneeded=()=>{
      if(!request.result.objectStoreNames.contains(STORE)){
        const store=request.result.createObjectStore(STORE,{keyPath:"captureId"});
        store.createIndex("ownerDevice",["ownerId","deviceKey"]);
        store.createIndex("preparation",["ownerId","deviceKey","preparationId"],{unique:true});
      }
    };
    request.onsuccess=()=>{request.result.onversionchange=()=>request.result.close();resolve(request.result);};
    request.onerror=()=>reject(new Error("foff_conversion_draft_storage"));
    request.onblocked=()=>reject(new Error("foff_conversion_draft_storage"));
  });
  try{return await fn(db);}finally{db.close();}
}
function transaction<T>(db:IDBDatabase,mode:IDBTransactionMode,
  task:(store:IDBObjectStore,resolve:(value:T)=>void,reject:(error:Error)=>void)=>void):Promise<T>{
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(STORE,mode);
    let result!:T,hasResult=false;
    tx.oncomplete=()=>hasResult?resolve(result):reject(new Error("foff_conversion_draft_storage"));
    tx.onabort=()=>reject(new Error("foff_conversion_draft_storage"));
    tx.onerror=()=>reject(new Error("foff_conversion_draft_storage"));
    task(tx.objectStore(STORE),v=>{result=v;hasResult=true;},e=>{try{tx.abort();}catch{}reject(e);});
  });
}
export async function loadConversionDraft(identity:OfflineVaultIdentity,preparationId:string):Promise<ConversionDraftRow|null>{
  if(!UUID.test(identity.ownerId)||!UUID4.test(identity.deviceKey)||!UUID4.test(preparationId))
    fail("identity");
  return withDb(db=>transaction(db,"readonly",(store,done,reject)=>{
    const request=store.index("preparation").get([identity.ownerId.toLowerCase(),identity.deviceKey.toLowerCase(),preparationId.toLowerCase()]);
    request.onsuccess=()=>{
      const row=request.result as ConversionDraftRow|undefined;
      if(row){try{check(identity,row);}catch{reject(new Error("foff_conversion_draft_corrupt"));return;}}
      done(row??null);
    };
    request.onerror=()=>reject(new Error("foff_conversion_draft_storage"));
  }));
}
export async function readConversionDraft(identity:OfflineVaultIdentity,key:CryptoKey,row:ConversionDraftRow):Promise<Record<string,unknown>>{
  check(identity,row);
  const data=await openLocalDraft(key,binding(row),row.sealed);
  const internal=data._foffDraft;
  if(!internal||typeof internal!=="object"||Array.isArray(internal))fail("corrupt");
  const ctx=internal as Record<string,unknown>;
  if(ctx.captureId!==row.captureId||ctx.preparationId!==row.preparationId||
     ctx.assignmentId!==row.assignmentId||ctx.machineCode!==row.machineCode||
     ctx.formCode!==row.formCode||ctx.formVersion!==row.formVersion||
     ctx.revision!==row.revision||!data.values||typeof data.values!=="object"||
     Array.isArray(data.values))fail("corrupt");
  return data.values as Record<string,unknown>;
}
export async function saveConversionDraft(input:{
  identity:OfflineVaultIdentity;key:CryptoKey;preparationId:string;assignmentId:string;
  machineCode:string;formCode:string;formVersion:number;
  captureId:string;expectedRevision:number;values:Record<string,unknown>;
}):Promise<ConversionDraftRow>{
  const {identity}=input;
  if(!UUID4.test(input.captureId)||!UUID4.test(input.preparationId)||!UUID.test(input.assignmentId)||
     !FORM.test(input.formCode)||!Number.isSafeInteger(input.formVersion)||
     input.formVersion<1||!Number.isSafeInteger(input.expectedRevision)||input.expectedRevision<0||
     !input.values||typeof input.values!=="object"||Array.isArray(input.values))fail("invalid");
  const rowWithoutSeal={captureId:input.captureId.toLowerCase(),
    ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
    preparationId:input.preparationId.toLowerCase(),assignmentId:input.assignmentId.toLowerCase(),
    machineCode:input.machineCode,formCode:input.formCode,formVersion:input.formVersion,
    revision:input.expectedRevision+1,updatedAt:new Date().toISOString()};
  const row:ConversionDraftRow={...rowWithoutSeal,sealed:await sealLocalDraft(input.key,{
    ownerId:rowWithoutSeal.ownerId,deviceKey:rowWithoutSeal.deviceKey,
    id:rowWithoutSeal.captureId,contextId:rowWithoutSeal.preparationId,
    formCode:rowWithoutSeal.formCode,formVersion:rowWithoutSeal.formVersion,
  },{values:input.values,_foffDraft:{
    captureId:rowWithoutSeal.captureId,preparationId:rowWithoutSeal.preparationId,
    assignmentId:rowWithoutSeal.assignmentId,machineCode:rowWithoutSeal.machineCode,
    formCode:rowWithoutSeal.formCode,formVersion:rowWithoutSeal.formVersion,
    revision:rowWithoutSeal.revision,
  }})};
  check(identity,row);
  return withDb(db=>transaction(db,"readwrite",(store,done,reject)=>{
    // Compare-and-swap inside the same IDB transaction: two tabs cannot clobber.
    const existing=store.index("preparation").get([row.ownerId,row.deviceKey,row.preparationId]);
    existing.onsuccess=()=>{
      const prior=existing.result as ConversionDraftRow|undefined;
      if((prior&&prior.captureId!==row.captureId)||
         (prior?prior.revision:0)!==input.expectedRevision){
        reject(new Error("foff_conversion_draft_conflict"));return;
      }
      if(prior&&(prior.assignmentId!==row.assignmentId||prior.machineCode!==row.machineCode||
        prior.formCode!==row.formCode||prior.formVersion!==row.formVersion)){
        reject(new Error("foff_conversion_draft_context"));return;
      }
      const put=store.put(row);
      put.onsuccess=()=>done(row);
      put.onerror=()=>reject(new Error("foff_conversion_draft_storage"));
    };
    existing.onerror=()=>reject(new Error("foff_conversion_draft_storage"));
  }));
}
export const CONVERSION_DRAFT_DB=NAME;
