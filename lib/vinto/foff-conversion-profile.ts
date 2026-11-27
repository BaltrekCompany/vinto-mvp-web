/** FOFF-03: isolated device profile for Conversion.
 * The vault key is never persisted in plaintext. Public pins, once enrolled
 * over authenticated HTTPS, cannot be overwritten by another response/tab.
 */
import {isOfflineVaultRecord,type OfflineVaultRecord,type OfflineVaultIdentity} from "./offline-vault.ts";

export const CONVERSION_PROFILE_DB="vinto-foff-conversion-profile-v1";
const STORE="profiles";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const B64=/^[A-Za-z0-9_-]{43}$/;
export type ConversionOfflineProfile=Readonly<{
  id:string;ownerId:string;deviceKey:string;displayName:string;
  vaultRecord:OfflineVaultRecord;preparationPin:string;capturePin:string;
}>;
const fail=(reason:string):never=>{throw new Error("foff_conversion_profile_"+reason);};
const profileId=(identity:OfflineVaultIdentity)=>identity.ownerId.toLowerCase()+":"+identity.deviceKey.toLowerCase();
function valid(profile:ConversionOfflineProfile):boolean{
  return Boolean(profile&&profile.id===profileId(profile)&&
    UUID.test(profile.ownerId)&&UUID.test(profile.deviceKey)&&
    typeof profile.displayName==="string"&&isOfflineVaultRecord(profile.vaultRecord)&&
    profile.vaultRecord.ownerId===profile.ownerId&&profile.vaultRecord.deviceKey===profile.deviceKey&&
    B64.test(profile.preparationPin)&&B64.test(profile.capturePin)&&
    profile.preparationPin!==profile.capturePin);
}
async function withProfileDb<T>(run:(db:IDBDatabase)=>Promise<T>):Promise<T>{
  if(typeof indexedDB==="undefined")return fail("unavailable");
  const db=await new Promise<IDBDatabase>((ok,bad)=>{
    const req=indexedDB.open(CONVERSION_PROFILE_DB,1);
    req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(STORE))
      req.result.createObjectStore(STORE,{keyPath:"id"});};
    req.onsuccess=()=>{req.result.onversionchange=()=>req.result.close();ok(req.result);};
    req.onerror=()=>bad(new Error("foff_conversion_profile_storage"));
    req.onblocked=()=>bad(new Error("foff_conversion_profile_storage"));
  });
  try{return await run(db);}finally{db.close();}
}
function request<T>(db:IDBDatabase,mode:IDBTransactionMode,
  task:(store:IDBObjectStore,finish:(value:T)=>void,reject:(error:Error)=>void)=>void):Promise<T>{
  return new Promise((ok,bad)=>{
    const tx=db.transaction(STORE,mode);
    let value!:T,ready=false,failed=false;
    tx.oncomplete=()=>ready&&!failed?ok(value):bad(new Error("foff_conversion_profile_storage"));
    tx.onabort=()=>bad(new Error("foff_conversion_profile_storage"));
    tx.onerror=()=>bad(new Error("foff_conversion_profile_storage"));
    task(tx.objectStore(STORE),v=>{value=v;ready=true;},e=>{
      failed=true;try{tx.abort();}catch{/* ended */}bad(e);
    });
  });
}
export async function getConversionOfflineProfile(identity:OfflineVaultIdentity):Promise<ConversionOfflineProfile|null>{
  if(!UUID.test(identity.ownerId)||!UUID.test(identity.deviceKey))fail("identity");
  return withProfileDb(db=>request(db,"readonly",(store,ok,bad)=>{
    const r=store.get(profileId(identity));
    r.onsuccess=()=>{
      if(r.result!==undefined&&!valid(r.result as ConversionOfflineProfile)){bad(new Error("foff_conversion_profile_corrupt"));return;}
      ok((r.result as ConversionOfflineProfile|undefined)??null);
    };
    r.onerror=()=>bad(new Error("foff_conversion_profile_storage"));
  }));
}
export async function saveConversionOfflineProfile(profile:ConversionOfflineProfile):Promise<void>{
  if(!valid(profile))fail("invalid");
  // add() is atomic: no TOCTOU pin replacement in two concurrent tabs.
  return withProfileDb(db=>request<void>(db,"readwrite",(store,ok,bad)=>{
    const r=store.add(profile);
    r.onsuccess=()=>ok(undefined);
    r.onerror=()=>bad(new Error("foff_conversion_profile_already_enrolled"));
  }));
}

/** Offline login only lists previously enrolled profiles on this device.
 * Unlock still requires the local passphrase. This does not restore server
 * permissions or create a backend session.
 */
export async function listConversionOfflineProfiles(deviceKey:string):Promise<ConversionOfflineProfile[]>{
  if(!UUID.test(deviceKey))fail("identity");
  return withProfileDb(db=>request(db,"readonly",(store,done,reject)=>{
    const r=store.getAll();
    r.onsuccess=()=>{
      const all=r.result as ConversionOfflineProfile[];
      if(all.some(profile=>!valid(profile))){reject(new Error("foff_conversion_profile_corrupt"));return;}
      done(all.filter(profile=>profile.deviceKey===deviceKey.toLowerCase()));
    };
    r.onerror=()=>reject(new Error("foff_conversion_profile_storage"));
  }));
}
