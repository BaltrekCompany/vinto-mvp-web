/** FOFF-02B.3 — encrypted, isolated production preparation metadata.
 * No capture-authority is issued or validated here. This is NOT an editor gate.
 * Do not use saved metadata to authorize offline submission.
 */
import { openLocalDraft, sealLocalDraft, type OfflineVaultIdentity, type DraftBinding } from "./offline-vault";

export const PRODUCTION_PREPARATIONS_DB = "vinto-production-offline-preparations-v1";
const STORE = "preparations";
const OWNER = "ownerDevice";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MACHINE = /^[A-Za-z0-9_.-]{1,48}$/;
const FORM = /^VINTO-P1-[0-9]{2}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const SECTORS = new Set(["CONVERSION", "REBOBINADO", "BOBINAS"]);
type Sealed = Readonly<{format: "aes-gcm-v1"; iv: string; ciphertext: string}>;

export type ProductionPreparationContext = Readonly<{
  id: string; assignmentId: string; scopeSnapshotId: string;
  sectorCode: string; machineCode: string; formCode: string; formVersion: number;
  contextDigest: string; capturedContextAt: string;
}>;
export type ProductionPreparationRecord = ProductionPreparationContext & OfflineVaultIdentity & Readonly<{sealed: Sealed}>;
export type ProductionPreparationPayload = Readonly<{
  // Values may contain arrays/objects for repeated P1-11 groups. No user credentials.
  workOrderId: string; lineId: string; articleCode: string;
  assignmentStatus: string; operatingDate: string; shiftCode: string;
  formDefinition: Record<string, unknown>; referenceData: Record<string, unknown>;
}>;

const fail = (reason: string): never => { throw new Error("foff_preparation_" + reason); };
const lower = (value: string): string => value.toLowerCase();
function checkIdentity(identity: OfflineVaultIdentity) {
  if (!UUID.test(identity.ownerId) || !UUID.test(identity.deviceKey)) fail("identity");
}
export function validateProductionPreparationContext(context: ProductionPreparationContext): void {
  if (![context.id,context.assignmentId,context.scopeSnapshotId].every(v => typeof v === "string" && UUID.test(v)) ||
    !SECTORS.has(context.sectorCode) || !MACHINE.test(context.machineCode) || !FORM.test(context.formCode) ||
    !Number.isSafeInteger(context.formVersion) || context.formVersion < 1 ||
    !SHA256.test(context.contextDigest) ||
    !Number.isFinite(Date.parse(context.capturedContextAt))) fail("context");
}
function binding(identity: OfflineVaultIdentity, context: ProductionPreparationContext): DraftBinding {
  return { ownerId: lower(identity.ownerId), deviceKey: lower(identity.deviceKey),
    id: lower(context.id), contextId: lower(context.scopeSnapshotId),
    formCode: context.formCode, formVersion: context.formVersion };
}
function validatePayload(value: ProductionPreparationPayload): void {
  if (!value || !UUID.test(value.workOrderId) || !UUID.test(value.lineId) ||
    typeof value.articleCode !== "string" || !value.articleCode ||
    typeof value.assignmentStatus !== "string" || !value.assignmentStatus ||
    typeof value.operatingDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.operatingDate) ||
    typeof value.shiftCode !== "string" || !value.shiftCode ||
    !value.formDefinition || Array.isArray(value.formDefinition) || typeof value.formDefinition !== "object" ||
    !value.referenceData || Array.isArray(value.referenceData) || typeof value.referenceData !== "object") fail("payload");
}
async function withDb<T>(fn: (db: IDBDatabase) => Promise<T>): Promise<T> {
  if (typeof indexedDB === "undefined") return fail("unavailable");
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const r = indexedDB.open(PRODUCTION_PREPARATIONS_DB, 1);
    r.onupgradeneeded = () => {
      if (!r.result.objectStoreNames.contains(STORE))
        r.result.createObjectStore(STORE, {keyPath: "id"}).createIndex(OWNER, ["ownerId","deviceKey"]);
    };
    r.onsuccess = () => { r.result.onversionchange = () => r.result.close(); resolve(r.result); };
    r.onerror = () => reject(new Error("foff_preparation_storage"));
    r.onblocked = () => reject(new Error("foff_preparation_storage"));
  });
  try { return await fn(db); } finally { db.close(); }
}
function transaction<T>(db: IDBDatabase, mode: IDBTransactionMode,
  read: (store: IDBObjectStore, done: (data:T)=>void, reject: (error:Error)=>void)=>void):Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    let result: T, complete = false, failed = false;
    const rejectOnce=(error:Error)=>{failed=true;try{tx.abort();}catch{/* ended */}reject(error);};
    tx.oncomplete=()=>complete&&!failed?resolve(result):reject(new Error("foff_preparation_storage"));
    tx.onabort=()=>reject(new Error("foff_preparation_storage"));
    tx.onerror=()=>reject(new Error("foff_preparation_storage"));
    read(tx.objectStore(STORE), v=>{result=v;complete=true;}, rejectOnce);
  });
}
export async function saveProductionPreparation(identity: OfflineVaultIdentity,key: CryptoKey,
  context: ProductionPreparationContext,payload: ProductionPreparationPayload): Promise<ProductionPreparationRecord> {
  checkIdentity(identity); validateProductionPreparationContext(context); validatePayload(payload);
  const sealed=await sealLocalDraft(key,binding(identity,context),{...payload});
  const record: ProductionPreparationRecord={...context,id:lower(context.id),assignmentId:lower(context.assignmentId),
    scopeSnapshotId:lower(context.scopeSnapshotId),ownerId:lower(identity.ownerId),deviceKey:lower(identity.deviceKey),sealed};
  // IndexedDB add is atomic and prevents overwriting a prepared context, including concurrent tabs.
  return withDb(db=>transaction(db,"readwrite",(store,done,reject)=>{
    const request=store.add(record);
    request.onsuccess=()=>done(record);
    request.onerror=()=>reject(new Error("foff_preparation_exists_or_storage"));
  }));
}
export async function listProductionPreparations(identity: OfflineVaultIdentity):Promise<ProductionPreparationRecord[]> {
  checkIdentity(identity);
  return withDb(db=>transaction(db,"readonly",(store,done,reject)=>{
    const req=store.index(OWNER).getAll([lower(identity.ownerId),lower(identity.deviceKey)]);
    req.onsuccess=()=>done(req.result as ProductionPreparationRecord[]);
    req.onerror=()=>reject(new Error("foff_preparation_storage"));
  }));
}
export async function readProductionPreparation(identity: OfflineVaultIdentity,key: CryptoKey,
  row: ProductionPreparationRecord):Promise<ProductionPreparationPayload> {
  checkIdentity(identity); validateProductionPreparationContext(row);
  if (lower(row.ownerId)!==lower(identity.ownerId) || lower(row.deviceKey)!==lower(identity.deviceKey)) fail("identity_mismatch");
  const values=await openLocalDraft(key,binding(identity,row),row.sealed);
  validatePayload(values as ProductionPreparationPayload);
  return values as ProductionPreparationPayload;
}
