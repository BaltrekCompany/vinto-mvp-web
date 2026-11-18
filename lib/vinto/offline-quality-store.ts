/**
 * OFF-03C.2 encrypted immutable Quality form-definition packages.
 * Only a verified active local scope can bind/refresh definitions. Decrypting
 * historical metadata never grants offline capture authority.
 */
import { openProfileDb, PACKAGE_STORE_NAME } from "./offline-profile-store.ts";
import { readOfflineScope, type VerifiedLocalScope } from "./offline-scope-store.ts";
import { openLocalDraft, sealLocalDraft, type OfflineVaultIdentity } from "./offline-vault.ts";
import type { SealedValues } from "./offline-store";
import {
  verifyQualityPackage, type VerifiedQualityDefinition, type QualityPayload, QualityPackageError
} from "./offline-quality-verify.ts";

const VAULT_FORM="VINTO-QUALITY-PACKAGE";
const VAULT_VERSION=1;
const encoder=new TextEncoder();
export type StoredPackage={
  packageKey:string;ownerId:string;deviceKey:string;packageId:string;
  scopeSnapshotId:string;sealed:SealedValues
};
type Stored=StoredPackage;
function profileKey(identity:OfflineVaultIdentity):string{
    return identity.ownerId.toLowerCase()+":"+identity.deviceKey.toLowerCase();
}
export async function packageIndexKey(identity:OfflineVaultIdentity,machine:string,form:string):Promise<string>{
    return indexKey(identity,machine,form);
}
async function indexKey(identity:OfflineVaultIdentity,machine:string,form:string):Promise<string>{
    const bytes=encoder.encode("VINTO:OFF03C2:PKG:v1:"+profileKey(identity)+":"+machine+":"+form);
    const hash=new Uint8Array(await crypto.subtle.digest("SHA-256",bytes as BufferSource));
    return profileKey(identity)+":"+Array.from(hash,b=>b.toString(16).padStart(2,"0")).join("");
}
function binding(identity:OfflineVaultIdentity,stored:Pick<Stored,"packageId"|"scopeSnapshotId">){
  return {...identity,id:stored.packageId,contextId:stored.scopeSnapshotId,
          formCode:VAULT_FORM,formVersion:VAULT_VERSION};
}
export function validPackageRecord(input:unknown,identity:OfflineVaultIdentity,index:string):input is StoredPackage{
  return validRecord(input,identity,index);
}
function validRecord(input:unknown,identity:OfflineVaultIdentity,index:string):input is Stored{
  if(!input||typeof input!=="object"||Array.isArray(input))return false;
  const r=input as Record<string,unknown>;
  return r.packageKey===index&&r.ownerId===identity.ownerId.toLowerCase()&&
    r.deviceKey===identity.deviceKey.toLowerCase()&&typeof r.packageId==="string"&&
    typeof r.scopeSnapshotId==="string"&&!!r.sealed&&typeof r.sealed==="object";
}
export function readRawPackage(identity:OfflineVaultIdentity,machine:string,form:string):Promise<StoredPackage|null>{
  return getStored(identity,machine,form);
}
async function getStored(identity:OfflineVaultIdentity,machine:string,form:string):Promise<Stored|null>{
  const idx=await indexKey(identity,machine,form);
  const db=await openProfileDb();
  try{
    return await new Promise((resolve,reject)=>{
      const tx=db.transaction(PACKAGE_STORE_NAME,"readonly");
      const r=tx.objectStore(PACKAGE_STORE_NAME).get(idx);
      r.onsuccess=()=>{
        if(r.result===undefined){resolve(null);return;}
        if(!validRecord(r.result,identity,idx)){reject(new QualityPackageError("invalid"));return;}
        resolve(r.result);
      };
      r.onerror=()=>reject(new QualityPackageError("unavailable"));
      tx.onerror=()=>reject(new QualityPackageError("unavailable"));
      tx.onabort=()=>reject(new QualityPackageError("unavailable"));
    });
  }finally{db.close();}
}
/** Offline: validates both signed scope and signed package again, plus AES-GCM. */
export async function readQualityPackage(
    key:CryptoKey,identity:OfflineVaultIdentity,scope:VerifiedLocalScope,
    machine:string,form:string):Promise<VerifiedQualityDefinition|null>{
  const stored=await getStored(identity,machine,form);
  if(!stored)return null;
  if(stored.scopeSnapshotId!==scope.envelope.payload.snapshot_id) return null;
  const payload=await openLocalDraft(key,binding(identity,stored),stored.sealed);
  const verified=await verifyQualityPackage(payload.envelope,scope,identity);
  if(verified.envelope.payload.package_id!==stored.packageId ||
     verified.envelope.payload.scope_snapshot_id!==stored.scopeSnapshotId ||
     verified.envelope.payload.machine_code!==machine ||
     verified.envelope.payload.form_code!==form) throw new QualityPackageError("invalid");
  return verified;
}
/** A package may only move forward: never a lower form version, never a different body at the same version. */
export function assertPackageProgression(old:QualityPayload,next:QualityPayload):void{
  if(old.form_version>next.form_version ||
     (old.form_version===next.form_version&&old.content_sha256!==next.content_sha256))
     throw new QualityPackageError("invalid");
}
/** Encrypt an ALREADY VERIFIED package into its storage record without touching IndexedDB. */
export async function sealPackageRecord(key:CryptoKey,identity:OfflineVaultIdentity,
                                        verified:VerifiedQualityDefinition):Promise<StoredPackage>{
  const p=verified.envelope.payload;
  return {
    packageKey:await indexKey(identity,p.machine_code,p.form_code),
    ownerId:identity.ownerId.toLowerCase(),deviceKey:identity.deviceKey.toLowerCase(),
    packageId:p.package_id,scopeSnapshotId:p.scope_snapshot_id,
    sealed:await sealLocalDraft(key,binding(identity,{packageId:p.package_id,scopeSnapshotId:p.scope_snapshot_id}),
                            {envelope:verified.envelope})
  };
}
/**
 * Online only: caller has reauthenticated and retrieved the package from HTTPS.
 * No plaintext of the signed package is written to IndexedDB.
 */
export async function storeQualityPackage(key:CryptoKey,identity:OfflineVaultIdentity,
                                          envelope:unknown):Promise<void>{
  const scope=await readOfflineScope(key,identity);
  if(!scope)throw new QualityPackageError("scope");
  const verified=await verifyQualityPackage(envelope,scope,identity);
  const p=verified.envelope.payload;
  const idx=await indexKey(identity,p.machine_code,p.form_code);
  const before=await getStored(identity,p.machine_code,p.form_code);
  const previous=before?await readQualityPackage(key,identity,scope,p.machine_code,p.form_code):null;
  if(before&&!previous){
    // Different previously issued scope: do not silently overwrite old encrypted
    // metadata without a controlled recovery flow / approved rotation.
    throw new QualityPackageError("scope");
  }
  if(previous)assertPackageProgression(previous.envelope.payload,p);
  const record:Stored=await sealPackageRecord(key,identity,verified);
  const db=await openProfileDb();
  try{
    await new Promise<void>((resolve,reject)=>{
      const tx=db.transaction(["profiles","scopes",PACKAGE_STORE_NAME],"readwrite");
      let denied:Error|undefined;
      const fail=()=>{denied=new QualityPackageError("scope");tx.abort();};
      const profile=tx.objectStore("profiles").get(profileKey(identity));
      profile.onsuccess=()=>{
        if(!profile.result||profile.result.ownerId!==identity.ownerId.toLowerCase()||
            profile.result.deviceKey!==identity.deviceKey.toLowerCase()){fail();return;}
        const savedScope=tx.objectStore("scopes").get(profileKey(identity));
        savedScope.onsuccess=()=>{
          if(!savedScope.result||savedScope.result.snapshotId!==p.scope_snapshot_id){fail();return;}
          const store=tx.objectStore(PACKAGE_STORE_NAME);
          const prior=store.get(idx);
          prior.onsuccess=()=>{
            if(prior.result&&( !validRecord(prior.result,identity,idx) ||
                  prior.result.packageId!==before?.packageId)){fail();return;}
            store.put(record);
          };
        };
      };
      tx.oncomplete=()=>resolve();
      tx.onerror=()=>reject(denied??new QualityPackageError("unavailable"));
      tx.onabort=()=>reject(denied??new QualityPackageError("unavailable"));
    });
  }finally{db.close();}
}
