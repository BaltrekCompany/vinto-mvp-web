/** OFF-04.8O — only an independently trusted CAPTURE envelope can arm
 * the isolated Save Capture button. Readiness packages supply field metadata
 * but are NEVER used as authorization. Server verification remains mandatory.
 */
import {verifyOperationalCaptureScope,type CaptureScopeEnvelope,type CaptureScopeTarget}
 from "./offline-operational-capture-scope-verify.ts";
import type {OfflineScopeIdentity} from "./offline-scope-verify.ts";

export type OperationalCaptureGateDeps=Readonly<{
 envelope:unknown;
 /** Existing enrollment pin obtained over authenticated HTTPS, NOT envelope key. */
 trustedPublicKeyB64url:string;
 identity:OfflineScopeIdentity;
 target:CaptureScopeTarget;
 now:()=>number;
}>;
export function createOperationalCaptureGate(deps:OperationalCaptureGateDeps){
 return async():Promise<void>=>{
  await verifyOperationalCaptureScope(deps.envelope,deps.trustedPublicKeyB64url,
   deps.identity,deps.target,deps.now());
 };
}
export async function verifyCaptureBeforeEditor(deps:OperationalCaptureGateDeps):Promise<{
 assertCaptureScope:()=>Promise<void>;
 scope:CaptureScopeEnvelope;
}>{
 const scope=await verifyOperationalCaptureScope(deps.envelope,deps.trustedPublicKeyB64url,
  deps.identity,deps.target,deps.now());
 return {scope,assertCaptureScope:createOperationalCaptureGate(deps)};
}
