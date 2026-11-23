/** VINTO OFF-04.8: encrypted, independently signed CAPTURE authority on device.
 *
 * Readiness metadata is NOT a capture permit. Authority is bound to the
 * original user, device and snapshot, never stored in plaintext and never
 * grants any server permission by itself. No records are deleted or silently
 * replaced when the operator renews a signed snapshot.
 */
import {openLocalDraft,sealLocalDraft,type OfflineVaultIdentity} from "./offline-vault.ts";
import {verifyOperationalCaptureScope,type CaptureScopeEnvelope,type CaptureScopeTarget}
  from "./offline-operational-capture-scope-verify.ts";

const DATABASE="vinto-off048-capture-authority-v1";
const TABLE="authorities";
const FORM="VINTO-CAPTURE-SCOPE";
const VERSION=1;
type AuthorityRow=Readonly<{
 key:string; ownerId:string;deviceKey:string;snapshotId:string;sealed:Awaited<ReturnType<typeof sealLocalDraft>>;
}>;
const rowKey=(id:OfflineVaultIdentity,snapshotId:string)=>
 [id.ownerId.toLowerCase(),id.deviceKey.toLowerCase(),snapshotId.toLowerCase()].join(":");
const bind=(id:OfflineVaultIdentity,snapshotId:string)=>({
 ...id,id:snapshotId,contextId:snapshotId,formCode:FORM,formVersion:VERSION,
});
async function db():Promise<IDBDatabase>{
 if(typeof indexedDB==="undefined")throw Error("CAPTURE_AUTH_STORAGE_UNAVAILABLE");
 return new Promise((resolve,reject)=>{
  const req=indexedDB.open(DATABASE,1);
  req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(TABLE))
    req.result.createObjectStore(TABLE,{keyPath:"key"});};
  req.onsuccess=()=>{req.result.onversionchange=()=>req.result.close();resolve(req.result);};
  req.onerror=()=>reject(Error("CAPTURE_AUTH_STORAGE_UNAVAILABLE"));
  req.onblocked=()=>reject(Error("CAPTURE_AUTH_STORAGE_BLOCKED"));
 });
}
async function get(snapshotId:string,identity:OfflineVaultIdentity):Promise<AuthorityRow|null>{
 const handle=await db();
 try{return await new Promise((resolve,reject)=>{
  const req=handle.transaction(TABLE,"readonly").objectStore(TABLE).get(rowKey(identity,snapshotId));
  req.onsuccess=()=>{
   const row=req.result as AuthorityRow|undefined;
   if(!row){resolve(null);return;}
   if(row.snapshotId.toLowerCase()!==snapshotId.toLowerCase()||
      row.ownerId.toLowerCase()!==identity.ownerId.toLowerCase()||
      row.deviceKey.toLowerCase()!==identity.deviceKey.toLowerCase())
      {reject(Error("CAPTURE_AUTH_IDENTITY_MISMATCH"));return;}
   resolve(row);
  };
  req.onerror=()=>reject(Error("CAPTURE_AUTH_STORAGE_UNAVAILABLE"));
 });}finally{handle.close();}
}
export async function storeCaptureAuthority(
 key:CryptoKey,identity:OfflineVaultIdentity,envelope:CaptureScopeEnvelope,
 trustedPublicKey:string,target:CaptureScopeTarget,
):Promise<void>{
 const snapshot=envelope.payload.snapshot_id;
 if(target.scopeSnapshotId!==snapshot)throw Error("CAPTURE_AUTH_SNAPSHOT_MISMATCH");
 // Validate the independent CAPTURE signature and exact published form
 // BEFORE any permanent state change.
 await verifyOperationalCaptureScope(envelope,trustedPublicKey,identity,target,Date.now());
 const row:AuthorityRow={
  key:rowKey(identity,snapshot),ownerId:identity.ownerId.toLowerCase(),
  deviceKey:identity.deviceKey.toLowerCase(),snapshotId:snapshot,
  sealed:await sealLocalDraft(key,bind(identity,snapshot),{
   envelope,trustedPublicKey,
  }),
 };
 const handle=await db();
 try{await new Promise<void>((resolve,reject)=>{
  const tx=handle.transaction(TABLE,"readwrite");
  const request=tx.objectStore(TABLE).add(row);
  request.onerror=()=>reject(Error("CAPTURE_AUTH_ALREADY_STORED"));
  tx.oncomplete=()=>resolve();
  tx.onabort=()=>reject(Error("CAPTURE_AUTH_STORAGE_UNAVAILABLE"));
 });}finally{handle.close();}
}
export async function readCaptureAuthority(
 key:CryptoKey,identity:OfflineVaultIdentity,target:CaptureScopeTarget,
 trustedPublicKey:string,
):Promise<CaptureScopeEnvelope>{
 const row=await get(target.scopeSnapshotId,identity);
 if(!row)throw Error("CAPTURE_AUTH_MISSING");
 const opened=await openLocalDraft(key,bind(identity,target.scopeSnapshotId),row.sealed);
 if(opened.trustedPublicKey!==trustedPublicKey)throw Error("CAPTURE_AUTH_PIN_MISMATCH");
 return verifyOperationalCaptureScope(opened.envelope,trustedPublicKey,identity,target,Date.now());
}

/** Enumerate only authority snapshot identifiers belonging to this device.
 * The caller must decrypt AND verify each envelope before trusting it.
 */
export async function listCaptureAuthoritySnapshots(identity:OfflineVaultIdentity):Promise<string[]>{
 const handle=await db();
 try{return await new Promise((resolve,reject)=>{
  const req=handle.transaction(TABLE,"readonly").objectStore(TABLE).getAll();
  req.onsuccess=()=>{
   const rows=req.result as AuthorityRow[];
   resolve(rows.filter(row=>row.ownerId===identity.ownerId.toLowerCase()&&
    row.deviceKey===identity.deviceKey.toLowerCase()).map(row=>row.snapshotId));
  };
  req.onerror=()=>reject(Error("CAPTURE_AUTH_STORAGE_UNAVAILABLE"));
 });}finally{handle.close();}
}
