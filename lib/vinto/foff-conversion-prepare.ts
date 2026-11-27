/** FOFF-03 — authenticated online preparation for one already-authorized
 * Conversion assignment and published form. Never trusts an envelope key as
 * a pin, never enables a capture editor based on preparation alone.
 */
import {apiBaseUrl} from "./api.ts";
import {getCurrentUser} from "./auth-api.ts";
import {getDeviceKey} from "./device.ts";
import {createLocalVault,unlockLocalVault,type OfflineVaultIdentity} from "./offline-vault.ts";
import {getConversionOfflineProfile,saveConversionOfflineProfile} from "./foff-conversion-profile.ts";
import {saveProductionPreparation} from "./foff-production-preparation-store.ts";
import {verifyConversionPreparation,verifyConversionReferencePackage}
  from "./foff-conversion-preparation-verify.ts";
import {verifyConversionCaptureAuthority} from "./foff-conversion-capture-authority-verify.ts";

type R=Record<string,unknown>;
const isObj=(v:unknown):v is R=>Boolean(v&&typeof v==="object"&&!Array.isArray(v));
const isPin=(v:unknown):v is {algorithm:"Ed25519";key_id:string;public_key_b64url:string}=>isObj(v)&&
  v.algorithm==="Ed25519"&&typeof v.key_id==="string"&&typeof v.public_key_b64url==="string";
const isUuid4=(v:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);

async function postJson(path:string,body:R,signal?:AbortSignal):Promise<R>{
  const result=await fetch(`${apiBaseUrl()}${path}`,{
    method:"POST",credentials:"include",cache:"no-store",signal,
    headers:{"Content-Type":"application/json"},body:JSON.stringify(body),
  });
  if(!result.ok)throw new Error(result.status===503?"foff_conversion_not_enabled":
    result.status===403?"foff_conversion_not_authorized":"foff_conversion_server_rejected");
  const json:unknown=await result.json();
  if(!isObj(json))throw new Error("foff_conversion_invalid_response");
  return json;
}
export type ConversionPrepareRequest=Readonly<{
  assignmentId:string;machineCode:string;formCode:string;formVersion:number;
  localPassphrase:string;
}>;
export async function prepareConversionForm(
  request:ConversionPrepareRequest,signal?:AbortSignal,
):Promise<{preparationId:string;formCode:string;machineCode:string}>{
  if(!isUuid4(request.assignmentId)&&!/^[a-f0-9]{8}-[a-f0-9-]{27,}$/i.test(request.assignmentId))
    throw new Error("foff_conversion_invalid_assignment");
  if(!/^VINTO-P1-(11|12|13|16)$/.test(request.formCode)||request.formVersion<1||
     !Number.isSafeInteger(request.formVersion)||!request.localPassphrase)
    throw new Error("foff_conversion_invalid_target");
  if(typeof navigator!=="undefined"&&!navigator.onLine)
    throw new Error("foff_conversion_prepare_requires_online");
  const session=await getCurrentUser(signal);
  if(session.status!=="authenticated"||!session.user.permissions.includes("production.capture"))
    throw new Error("foff_conversion_login_required");
  const identity:OfflineVaultIdentity={ownerId:session.user.id.toLowerCase(),deviceKey:getDeviceKey().toLowerCase()};
  if(!isUuid4(identity.deviceKey))throw new Error("foff_conversion_persistent_device_required");
  // Existing enrolled profiles are immutable. Reuse only matching signer pins.
  // Do not change local passphrase or trust a new server pin silently.
  const current=await getConversionOfflineProfile(identity);
  const enrolled=await postJson("/api/offline/production/enroll",{device_key:identity.deviceKey},signal);
  if(enrolled.enrolled!==true||enrolled.device_key!==identity.deviceKey||
     !isPin(enrolled.preparation_signing_pin)||!isPin(enrolled.capture_signing_pin))
    throw new Error("foff_conversion_enrollment_incomplete");
  const prepPin=enrolled.preparation_signing_pin.public_key_b64url;
  const capPin=enrolled.capture_signing_pin.public_key_b64url;
  if(current&&(current.preparationPin!==prepPin||current.capturePin!==capPin))
    throw new Error("foff_conversion_pin_rotation_requires_reenrollment");
  // Construct a new encrypted profile only after successful authenticated
  // enrolment. Never substitute a previously unlocked Quality profile.
  const vault=current?null:await createLocalVault(identity,request.localPassphrase);
  const key=current?await unlockLocalVault(current.vaultRecord,request.localPassphrase):vault!.key;
  const response=await postJson("/api/offline/production/conversion/prepare",{
    device_key:identity.deviceKey,assignment_id:request.assignmentId,form_code:request.formCode,
  },signal);
  if(response.captureEnabled!==true||!isObj(response.envelope)||
     !isObj(response.captureAuthority)||!isObj(response.referencePackage))
    throw new Error("foff_conversion_capture_not_enabled");
  const verified=await verifyConversionPreparation(response.envelope,prepPin,{
    ownerId:identity.ownerId,deviceKey:identity.deviceKey,
    assignmentId:request.assignmentId,machineCode:request.machineCode,
    formCode:request.formCode,formVersion:request.formVersion,
  },Date.now());
  await verifyConversionReferencePackage(response.referencePackage,verified);
  await verifyConversionCaptureAuthority(response.captureAuthority,capPin,{
    ownerId:identity.ownerId,deviceKey:identity.deviceKey,
    assignmentId:request.assignmentId,machineCode:request.machineCode,
    formCode:request.formCode,formVersion:request.formVersion,
    scopeSnapshotId:verified.snapshotId,
  },verified,Date.now());
  // Preserve the two original signed envelopes encrypted; they'll be required
  // for the later offline editor / original-author synchronization.
  const payload={
    workOrderId:verified.context.work_order_id,lineId:verified.context.line_id,
    articleCode:verified.context.article_code,assignmentStatus:"active",
    operatingDate:verified.context.operating_date,shiftCode:verified.context.shift_code,
    formDefinition:response.referencePackage.definition as R,
    referenceData:{
      ...response.referencePackage.references as R,
      referencePackage:response.referencePackage,
      preparationEnvelope:response.envelope,
      captureAuthority:response.captureAuthority,
    },
  };
  if(!current)await saveConversionOfflineProfile({
    id:identity.ownerId+":"+identity.deviceKey,...identity,
    displayName:session.user.display_name??"Operador",
    vaultRecord:vault!.record,preparationPin:prepPin,capturePin:capPin,
  });
  const prepared=await saveProductionPreparation(identity,key,{
    id:verified.snapshotId,assignmentId:request.assignmentId,
    scopeSnapshotId:verified.snapshotId,sectorCode:"CONVERSION",
    machineCode:request.machineCode,formCode:request.formCode,
    formVersion:request.formVersion,contextDigest:verified.context.context_digest,
    capturedContextAt:verified.issuedAt,
  },payload);
  return {preparationId:prepared.id,formCode:prepared.formCode,machineCode:prepared.machineCode};
}
