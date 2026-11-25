/**
 * Device identity gate for the existing VINTO Quality offline editor.
 *
 * Only a persisted device key is eligible. The ordinary online capture key
 * can fall back to memory when Storage fails; offline enrollment must NOT.
 * This module never creates a device identity or grants CAPTURE permissions.
 */
import { DEVICE_KEY_STORAGE, isUuid } from "./device";
import type { OfflineVaultIdentity, OfflineVaultRecord } from "./offline-vault";

export type PersistedDeviceStorage = Pick<Storage,"getItem">;
export type VerifiedQualityLogin = Readonly<{userId:string}>;
export type QualityDeviceBinding = Readonly<{
  ownerId:string;
  deviceKey:string;
  record:OfflineVaultRecord;
}>;

const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();

export function requirePersistedQualityDevice(
  login:VerifiedQualityLogin,
  enrollment:QualityDeviceBinding,
  storage:PersistedDeviceStorage,
): OfflineVaultIdentity {
  if(!isUuid(login.userId)||!isUuid(enrollment.ownerId)||!isUuid(enrollment.deviceKey)||
      !isUuid(enrollment.record.ownerId)||!isUuid(enrollment.record.deviceKey))
    throw new Error("offline_quality_identity_invalid");
  let persisted:string|null=null;
  try {persisted=storage.getItem(DEVICE_KEY_STORAGE);}
  catch {throw new Error("offline_quality_device_storage_unavailable");}
  if(!isUuid(persisted)||!same(persisted,enrollment.deviceKey))
    throw new Error("offline_quality_device_not_enrolled");
  if(!same(login.userId,enrollment.ownerId)||
      !same(enrollment.record.ownerId,enrollment.ownerId)||
      !same(enrollment.record.deviceKey,enrollment.deviceKey))
    throw new Error("offline_quality_user_device_mismatch");
  return {ownerId:login.userId.toLowerCase(),deviceKey:persisted.toLowerCase()};
}
