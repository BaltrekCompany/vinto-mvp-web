/** OFF-04.8H. Operational local storage candidate, NOT mounted into VINTO.
 *
 * ONE IndexedDB database and ONE readwrite transaction across drafts,
 * pending and sync_queue for Save Capture. Every payload is already encrypted
 * by the caller using the owner+device+form+context AAD vault. This module
 * never stores plaintext, sends data, or grants online capture authority.
 * The synthetic OFF-04 lab databases are neither opened nor migrated.
 */
import { applyClaim, applyFinalize } from "./offline-sync-rules.ts";
import type { SyncQueueStore, SyncRecord, ClaimResult, FinalizePatch } from "./offline-sync-types.ts";
import { validOperationalDraft, validOperationalPending, nextOperationalDraft, decideOperationalFreeze,
  OperationalLocalError, type OperationalDraftRow, type OperationalPendingRow } from "./offline-operational-model.ts";
import { isSyncRecord } from "./offline-sync-store.ts";

export const OPERATIONAL_LOCAL_DB = "vinto-off048-operational-v1";
const DRAFTS="drafts", PENDING="pending", QUEUE="sync_queue";
const OWNER="ownerDevice";
export type OperationalLocalStore=Readonly<{
  saveDraft(row:OperationalDraftRow, expectedRevision:number|null):Promise<void>;
  getDraft(id:string):Promise<OperationalDraftRow|null>;
  listDrafts(ownerId:string,deviceKey:string):Promise<OperationalDraftRow[]>;
  /** Same transaction freezes source, adds immutable pending AND the queue item. */
  confirm(expectedRevision:number, expectedCiphertext:string, pending:OperationalPendingRow, queue:SyncRecord):Promise<{created:boolean;captureId:string}>;
  listPending(ownerId:string,deviceKey:string):Promise<OperationalPendingRow[]>;
  sync:SyncQueueStore;
}>;

function open():Promise<IDBDatabase>{
 if(typeof indexedDB==="undefined")return Promise.reject(new OperationalLocalError("unavailable"));
 return new Promise((resolve,reject)=>{
   const r=indexedDB.open(OPERATIONAL_LOCAL_DB,1);
   r.onupgradeneeded=()=>{
     const db=r.result;
     if(!db.objectStoreNames.contains(DRAFTS))db.createObjectStore(DRAFTS,{keyPath:"id"}).createIndex(OWNER,["ownerId","deviceKey"]);
     if(!db.objectStoreNames.contains(PENDING))db.createObjectStore(PENDING,{keyPath:"capture_id"}).createIndex(OWNER,["ownerId","deviceKey"]);
     if(!db.objectStoreNames.contains(QUEUE))db.createObjectStore(QUEUE,{keyPath:"capture_id"}).createIndex(OWNER,["ownerId","deviceKey"]);
   };
   r.onsuccess=()=>{r.result.onversionchange=()=>r.result.close();resolve(r.result);};
   r.onerror=()=>reject(new OperationalLocalError("storage"));
   r.onblocked=()=>reject(new OperationalLocalError("storage"));
 });
}
const failure=(e?:unknown)=> e instanceof OperationalLocalError?e:new OperationalLocalError("storage");
async function withDb<T>(f:(db:IDBDatabase)=>Promise<T>):Promise<T>{
 const db=await open();
 try{return await f(db);}finally{db.close();}
}
function single<T>(db:IDBDatabase, name:string, mode:IDBTransactionMode,
 key:string, fn:(current:unknown,store:IDBObjectStore)=>T):Promise<T>{
 return new Promise((resolve,reject)=>{
   let tx:IDBTransaction;
   try{tx=db.transaction(name,mode);}catch{reject(new OperationalLocalError("storage"));return;}
   let value:T;
   let bad:unknown=null;
   const store=tx.objectStore(name);
   const get=store.get(key);
   get.onsuccess=()=>{
     try{value=fn(get.result,store);}catch(error){bad=error;try{tx.abort();}catch{/* already closed */}}
   };
   get.onerror=()=>{bad=new OperationalLocalError("storage");try{tx.abort();}catch{/* closed */}};
   tx.oncomplete=()=>resolve(value);
   tx.onabort=()=>reject(failure(bad));
   tx.onerror=()=>{bad ??= new OperationalLocalError("storage");};
 });
}
function readList<T>(db:IDBDatabase,storeName:string,owner:string,device:string,
 guard:(x:unknown)=>x is T):Promise<T[]>{
 return new Promise((resolve,reject)=>{
   const tx=db.transaction(storeName,"readonly");
   const req=tx.objectStore(storeName).index(OWNER).getAll([owner.toLowerCase(),device.toLowerCase()]);
   req.onsuccess=()=>{
      if(!(req.result as unknown[]).every(guard)){reject(new OperationalLocalError("corrupt"));return;}
      resolve(req.result as T[]);
   };
   req.onerror=()=>reject(new OperationalLocalError("storage"));
 });
}

export function createOperationalLocalStore():OperationalLocalStore{
 const sync:SyncQueueStore={
   enqueue:rec=>withDb(db=>single(db,QUEUE,"readwrite",rec.capture_id,(existing,store)=>{
     if(!isSyncRecord(rec))throw new OperationalLocalError("invalid");
     if(existing!==undefined){
       if(!isSyncRecord(existing)||existing.payloadSha256!==rec.payloadSha256||
           existing.ownerId!==rec.ownerId||existing.deviceKey!==rec.deviceKey)
         throw new OperationalLocalError("conflict");
       return {created:false,record:existing};
     }
     store.add(rec);
     return {created:true,record:rec};
   })),
   get:id=>withDb(db=>single(db,QUEUE,"readonly",id,(row)=>{
     if(row===undefined)return null;
     if(!isSyncRecord(row))throw new OperationalLocalError("corrupt");
     return row;
   })),
   list:(owner,device)=>withDb(db=>readList(db,QUEUE,owner,device,isSyncRecord)),
   claim:(id,tabId,now,leaseMs):Promise<ClaimResult>=>withDb(db=>single(db,QUEUE,"readwrite",id,(row,store)=>{
     if(row===undefined)return null;
     if(!isSyncRecord(row))throw new OperationalLocalError("corrupt");
     const next=applyClaim(row,tabId,now,leaseMs);
     if(next)store.put(next.record);
     return next;
   })),
   finalize:(id,tabId,patch:FinalizePatch,now)=>withDb(db=>single(db,QUEUE,"readwrite",id,(row,store)=>{
     if(row===undefined)return false;
     if(!isSyncRecord(row))throw new OperationalLocalError("corrupt");
     const next=applyFinalize(row,tabId,patch,now);
     if(!next)return false;
     store.put(next);
     return true;
   })),
 };
 return {
   saveDraft:(row,expected)=>withDb(db=>single(db,DRAFTS,"readwrite",row.id,(existing,store)=>{
     const next=nextOperationalDraft(existing,row,expected);
     store.put(next);
   })),
   getDraft:id=>withDb(db=>single(db,DRAFTS,"readonly",id,row=>{
     if(row===undefined)return null;
     if(!validOperationalDraft(row))throw new OperationalLocalError("corrupt");
     return row;
   })),
   listDrafts:(owner,device)=>withDb(db=>readList(db,DRAFTS,owner,device,validOperationalDraft)),
   listPending:(owner,device)=>withDb(db=>readList(db,PENDING,owner,device,validOperationalPending)),
   confirm:(expectedRevision,expectedCiphertext,pending,queue)=>withDb(db=>new Promise((resolve,reject)=>{
     let tx:IDBTransaction;
     try{tx=db.transaction([DRAFTS,PENDING,QUEUE],"readwrite");}
     catch{reject(new OperationalLocalError("storage"));return;}
     let bad:unknown=null, outcome:{created:boolean;captureId:string};
     const drafts=tx.objectStore(DRAFTS),pendingStore=tx.objectStore(PENDING),queueStore=tx.objectStore(QUEUE);
     // Requests are chained inside one active IDB transaction, not separated
     // by unrelated async operations or a second database.
     const d=drafts.get(pending.sourceDraftId);
     d.onsuccess=()=>{
       const p=pendingStore.get(pending.capture_id);
       p.onsuccess=()=>{
         const q=queueStore.get(pending.capture_id);
         q.onsuccess=()=>{
           try{
             const decision=decideOperationalFreeze(d.result,p.result,q.result,
               expectedRevision,expectedCiphertext,pending,queue);
             if(decision.created){
               drafts.put(decision.draft);
               pendingStore.add(decision.pending);
               queueStore.add(decision.queue);
             }
             outcome={created:decision.created,captureId:pending.capture_id};
           }catch(e){bad=e;try{tx.abort();}catch{/* already finished */}}
         };
       };
     };
     tx.oncomplete=()=>resolve(outcome);
     tx.onerror=()=>{bad ??= new OperationalLocalError("storage");};
     tx.onabort=()=>reject(failure(bad));
   })),
   sync,
 };
}
