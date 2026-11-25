/** Encrypted metadata for prepared Quality forms; no measurements or passwords
 * are stored in this database. Local vaults are partitioned per operator/device.
 */
import {openLocalDraft,sealLocalDraft,isOfflineVaultRecord,
  type OfflineVaultIdentity,type OfflineVaultRecord,type DraftBinding} from "./offline-vault";
const DB="vinto-quality-offline-preparations-v1";
const USERS="users", PREPS="preparations";
export type OfflineLocalProfile=Readonly<{
 id:string;ownerId:string;deviceKey:string;displayName:string;
 vaultRecord:OfflineVaultRecord;trustedPublicKeyB64url:string;
}>;
export type OfflinePreparationRef=Readonly<{
 id:string;ownerId:string;deviceKey:string;formCode:string;
 formVersion:number;scopeSnapshotId:string;machineCode:string;
 sealed:{format:"aes-gcm-v1";iv:string;ciphertext:string};
}>;
const fail=()=>new Error("offline_preparation_storage_unavailable");
const profileId=(id:OfflineVaultIdentity)=>id.ownerId.toLowerCase()+":"+id.deviceKey.toLowerCase();
const binding=(row:OfflinePreparationRef):DraftBinding=>({
 ownerId:row.ownerId,deviceKey:row.deviceKey,id:row.id,
 contextId:row.scopeSnapshotId,formCode:row.formCode,formVersion:row.formVersion,
});
async function withDb<T>(fn:(db:IDBDatabase)=>Promise<T>):Promise<T>{
 if(typeof indexedDB==="undefined")throw fail();
 const db=await new Promise<IDBDatabase>((resolve,reject)=>{
  const req=indexedDB.open(DB,1);
  req.onupgradeneeded=()=>{
   const target=req.result;
   if(!target.objectStoreNames.contains(USERS))
    target.createObjectStore(USERS,{keyPath:"id"});
   if(!target.objectStoreNames.contains(PREPS))
    target.createObjectStore(PREPS,{keyPath:"id"}).createIndex("ownerDevice",["ownerId","deviceKey"]);
  };
  req.onsuccess=()=>resolve(req.result);
  req.onerror=()=>reject(fail());
  req.onblocked=()=>reject(fail());
 });
 try{return await fn(db);}finally{db.close();}
}
function transaction<T>(db:IDBDatabase,name:string,mode:IDBTransactionMode,
 run:(store:IDBObjectStore,resolve:(value:T)=>void,reject:(error:Error)=>void)=>void):Promise<T>{
 return new Promise((resolve,reject)=>{
  let tx:IDBTransaction;
  try{tx=db.transaction(name,mode);}catch{reject(fail());return;}
  let value:T,ready=false;
  tx.oncomplete=()=>ready?resolve(value):reject(fail());
  tx.onabort=()=>reject(fail());
  tx.onerror=()=>reject(fail());
  try{run(tx.objectStore(name),v=>{value=v;ready=true;},reject);}catch{try{tx.abort();}catch{}reject(fail());}
 });
}
export async function listOfflineProfiles():Promise<OfflineLocalProfile[]>{
 return withDb(db=>transaction(db,USERS,"readonly",(store,ok,bad)=>{
  const req=store.getAll();
  req.onsuccess=()=>ok((req.result as OfflineLocalProfile[]).filter(p=>
   p&&isOfflineVaultRecord(p.vaultRecord)&&
   p.ownerId===p.vaultRecord.ownerId&&p.deviceKey===p.vaultRecord.deviceKey));
  req.onerror=()=>bad(fail());
 }));
}
export async function getOfflineProfile(identity:OfflineVaultIdentity):Promise<OfflineLocalProfile|null>{
 return withDb(db=>transaction(db,USERS,"readonly",(store,ok,bad)=>{
  const req=store.get(profileId(identity));
  req.onsuccess=()=>ok(req.result??null);
  req.onerror=()=>bad(fail());
 }));
}
export async function saveOfflineProfile(profile:OfflineLocalProfile):Promise<void>{
 if(profile.id!==profileId(profile)||!isOfflineVaultRecord(profile.vaultRecord)||
    profile.ownerId!==profile.vaultRecord.ownerId||
    profile.deviceKey!==profile.vaultRecord.deviceKey)throw fail();
 const existing=await getOfflineProfile(profile);
 if(existing&&(existing.trustedPublicKeyB64url!==profile.trustedPublicKeyB64url||
    JSON.stringify(existing.vaultRecord)!==JSON.stringify(profile.vaultRecord)))
   throw new Error("offline_profile_pin_or_vault_changed");
 return withDb(db=>transaction<void>(db,USERS,"readwrite",(store,ok,bad)=>{
  const req=store.put(profile);req.onsuccess=()=>ok(undefined);req.onerror=()=>bad(fail());
 }));
}
export async function saveOfflinePreparation(
 identity:OfflineVaultIdentity,key:CryptoKey,
 data:{draftId:string;scopeSnapshotId:string;formCode:string;formVersion:number;machineCode:string;payload:Record<string,unknown>},
):Promise<OfflinePreparationRef>{
 const partial={id:data.draftId,ownerId:identity.ownerId.toLowerCase(),
  deviceKey:identity.deviceKey.toLowerCase(),formCode:data.formCode,
  formVersion:data.formVersion,scopeSnapshotId:data.scopeSnapshotId,machineCode:data.machineCode};
 const sealed=await sealLocalDraft(key,binding({...partial,sealed:{format:"aes-gcm-v1",iv:"",ciphertext:""}}),data.payload);
 const row:OfflinePreparationRef={...partial,sealed};
 // Never overwrite a prepared context in another tab / after a frozen capture.
 const previous=(await listOfflinePreparations(identity)).find(x=>x.id===row.id);
 if(previous)throw new Error("offline_preparation_already_exists");
 return withDb(db=>transaction(db,PREPS,"readwrite",(store,ok,bad)=>{
  const req=store.add(row);req.onsuccess=()=>ok(row);req.onerror=()=>bad(fail());
 }));
}
export async function listOfflinePreparations(identity:OfflineVaultIdentity):Promise<OfflinePreparationRef[]>{
 return withDb(db=>transaction(db,PREPS,"readonly",(store,ok,bad)=>{
  const req=store.index("ownerDevice").getAll([identity.ownerId.toLowerCase(),identity.deviceKey.toLowerCase()]);
  req.onsuccess=()=>ok(req.result as OfflinePreparationRef[]);
  req.onerror=()=>bad(fail());
 }));
}
export async function readOfflinePreparation(key:CryptoKey,row:OfflinePreparationRef):Promise<Record<string,unknown>>{
 return openLocalDraft(key,binding(row),row.sealed);
}
