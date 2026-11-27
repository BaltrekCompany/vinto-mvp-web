/** FOFF-03 — explicit, original-author Conversion queue synchronization.
 * Runs only after normal online login, never with local passphrase as a
 * substitute for a session. A lost ACK is retried using SAME capture_id.
 */
import {apiBaseUrl} from "./api.ts";
import {getCurrentUser} from "./auth-api.ts";
import type {OfflineVaultIdentity} from "./offline-vault.ts";
import {readConversionQueuePayload,markConversionQueue,
  type ConversionQueueRow} from "./foff-conversion-local-queue.ts";

export type ConversionSyncOutcome=Readonly<{
  captureId:string;kind:"synced"|"requires_review"|"retry"|"blocked";
  message:string;
}>;
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
export async function syncConversionPending(
  identity:OfflineVaultIdentity,key:CryptoKey,row:ConversionQueueRow,
  signal?:AbortSignal,
):Promise<ConversionSyncOutcome>{
  if(row.state!=="queued")
    return {captureId:row.captureId,kind:"blocked",message:"El registro ya no está pendiente."};
  const session=await getCurrentUser(signal);
  if(session.status!=="authenticated"||
     !same(session.user.id,identity.ownerId)||
     !session.user.permissions.includes("production.capture"))
    return {captureId:row.captureId,kind:"blocked",message:"Debes iniciar sesión con el autor original."};
  let payload;
  try{payload=await readConversionQueuePayload(identity,key,row);}
  catch{
    return {captureId:row.captureId,kind:"blocked",message:"No se pudo abrir la captura cifrada."};
  }
  let response:Response;
  try{
    response=await fetch(`${apiBaseUrl()}/api/offline/production/conversion/captures`,{
      method:"POST",credentials:"include",cache:"no-store",signal,
      headers:{"Content-Type":"application/json"},body:JSON.stringify(payload),
    });
  }catch{
    return {captureId:row.captureId,kind:"retry",message:"Sin confirmación del servidor. Se conservará para reintento."};
  }
  let result:unknown=null;
  try{result=await response.json();}catch{/* unreadable response: preserve */}
  if(!result||typeof result!=="object"||Array.isArray(result))
    return {captureId:row.captureId,kind:"retry",message:"Respuesta desconocida. Se conservará el envío."};
  const data=result as Record<string,unknown>;
  if(data.capture_id!==row.captureId||data.payload_sha256!==row.payloadSha256){
    // Never acknowledge a different payload/capture even if status is 200.
    return {captureId:row.captureId,kind:"retry",message:"Confirmación no conciliable. Revisión requerida."};
  }
  if((response.status===200||response.status===201)&&
     data.operational_registered===true&&(data.outcome==="created"||data.outcome==="duplicate")){
    await markConversionQueue(identity,row.captureId,row.payloadSha256,"synced");
    return {captureId:row.captureId,kind:"synced",message:"Registrado en Conversión."};
  }
  if(response.status===202&&data.outcome==="review"&&data.operational_registered===false){
    await markConversionQueue(identity,row.captureId,row.payloadSha256,"requires_review");
    return {captureId:row.captureId,kind:"requires_review",
      message:"Recibido por el servidor, pendiente de revisión. No registrado en Conversión."};
  }
  return {captureId:row.captureId,kind:"retry",
    message:"Registro sin confirmación operativa. Conservado para reintento."};
}
