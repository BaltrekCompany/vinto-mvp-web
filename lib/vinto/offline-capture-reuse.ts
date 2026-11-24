/** VINTO OFF-04.8 v6 (Issue #247): safe REUSE of an already stored, independently signed CAPTURE authority, and coalescing of automatic preparation.
 *
 * Pure decision logic (no IndexedDB, no network, no DOM). Nothing in this file grants authority: a candidate is only an envelope that the caller has ALREADY decrypted and verified
 * (signature, trusted pin, user, device, snapshot, operation, version, expiry) through `readCaptureAuthority`; the server still verifies issuance, revocation, the original author,
 * the CURRENT MF-13 grant and expiry inside the receipt transaction. A reused authority can therefore never widen what the server accepts; it only avoids issuing (and
 * registering) a redundant snapshot when the stored one is provably equivalent to what the server would sign now.
 *
 * Reuse requires ALL of:
 *  - a FRESH, verified readiness scope obtained in the same preparation (never inferred from cache);
 *  - the candidate's complete set of (machine, form, version, operation, grant) entries EQUALS the fresh set for the Quality forms (a removed pair, a version change,
 *    a re-issued grant, an extra pair or a different machine all forbid reuse);
 *  - more than REUSE_MIN_REMAINING_MS left, measured against the LATER of the device clock and the server clock (a device clock that is behind never extends a lifetime).
 * Anything else, or any error while reading a candidate: the caller issues a new authority (or fails closed).
 */
import type {CaptureScopeEnvelope} from "./offline-operational-capture-scope-verify.ts";

export const REUSE_MIN_REMAINING_MS=8*60*60*1000;
export const AUTO_COOLDOWN_MS=10*60*1000;

export type FreshPair=Readonly<{machine_code:string;form_code:string;form_version:number;operation:string;grant_id:string}>;
export type ReuseReason="reuse"|"no_fresh_pairs"|"no_candidate"|"coverage_mismatch"|"too_old";
export type ReuseSelection=Readonly<{envelope:CaptureScopeEnvelope|null;reason:ReuseReason}>;

const pairKey=(p:Readonly<{machine_code:string;form_code:string;form_version:number;operation:string;grant_id:string}>)=>
 [p.machine_code,p.form_code,String(p.form_version),p.operation,p.grant_id.toLowerCase()].join("|");

/** `candidates` MUST already be verified. Returns the newest candidate that satisfies every reuse condition, or null with the most informative refusal reason. */
export function selectReusableCapture(
 candidates:ReadonlyArray<CaptureScopeEnvelope>,fresh:ReadonlyArray<FreshPair>,nowMs:number,
 minRemainingMs:number=REUSE_MIN_REMAINING_MS,
):ReuseSelection{
 if(!Number.isFinite(nowMs)||fresh.length===0)return {envelope:null,reason:"no_fresh_pairs"};
 const wanted=new Set(fresh.map(pairKey));
 if(wanted.size!==fresh.length)return {envelope:null,reason:"coverage_mismatch"};   // duplicate fresh pairs: refuse to reason about it
 let best:CaptureScopeEnvelope|null=null,sawMismatch=false,sawShort=false;
 for(const c of candidates){
  const entries=c.payload.form_scopes.map(pairKey);
  const got=new Set(entries);
  if(got.size!==entries.length||got.size!==wanted.size||![...got].every(k=>wanted.has(k))){sawMismatch=true;continue;}
  const issued=Date.parse(c.payload.issued_at),expires=Date.parse(c.payload.expires_at);
  if(!Number.isFinite(issued)||!Number.isFinite(expires)||issued>nowMs||expires-nowMs<=minRemainingMs){sawShort=true;continue;}
  if(best===null||issued>Date.parse(best.payload.issued_at))best=c;
 }
 if(best)return {envelope:best,reason:"reuse"};
 return {envelope:null,reason:sawMismatch?"coverage_mismatch":sawShort?"too_old":"no_candidate"};
}

export type ResolveDeps=Readonly<{
 fresh:ReadonlyArray<FreshPair>;
 nowMs:number;                                            // already the later of device and server time
 listSnapshots:()=>Promise<string[]>;
 readVerified:(snapshotId:string)=>Promise<CaptureScopeEnvelope>;   // decrypt + FULL verification; throws on any failure
 issue:()=>Promise<CaptureScopeEnvelope>;                 // network + verification + store; throws on any failure (the caller keeps the previous set)
}>;
export type ResolveOutcome=Readonly<{envelope:CaptureScopeEnvelope;reused:boolean;considered:number;reason:ReuseReason}>;

export async function resolveCaptureAuthority(d:ResolveDeps):Promise<ResolveOutcome>{
 const verified:CaptureScopeEnvelope[]=[];
 let ids:string[]=[];
 try{ids=await d.listSnapshots();}catch{ids=[];}
 for(const id of ids){
  try{verified.push(await d.readVerified(id));}catch{/* unreadable, expired, other pin/identity or tampered: never a candidate, never deleted */}
 }
 const pick=selectReusableCapture(verified,d.fresh,d.nowMs);
 if(pick.envelope)return {envelope:pick.envelope,reused:true,considered:verified.length,reason:pick.reason};
 return {envelope:await d.issue(),reused:false,considered:verified.length,reason:pick.reason};
}

export type PreparedMark=Readonly<{at:number;ownerId:string;deviceKey:string;machine:string;authorityExpiresMs:number}>;
export type PrepareContext=Readonly<{nowMs:number;ownerId:string;deviceKey:string;machine:string}>;

/** Automatic triggers (login with an open vault, unlock, `online`) may skip a preparation only when the previous one COMPLETED for the same user, device and machine less than
 * AUTO_COOLDOWN_MS ago AND the CAPTURE authority obtained then is still comfortably valid. The manual retry never calls this. Trade-off (documented): a grant revoked during
 * the cooldown is seen at the next preparation, and the server rejects it at receipt in any case. */
export function shouldSkipAutomatic(mark:PreparedMark|null,c:PrepareContext,cooldownMs:number=AUTO_COOLDOWN_MS,minRemainingMs:number=REUSE_MIN_REMAINING_MS):boolean{
 if(!mark)return false;
 if(mark.ownerId.toLowerCase()!==c.ownerId.toLowerCase()||mark.deviceKey.toLowerCase()!==c.deviceKey.toLowerCase()||mark.machine!==c.machine)return false;
 const age=c.nowMs-mark.at;
 if(!Number.isFinite(age)||age<0||age>=cooldownMs)return false;
 return Number.isFinite(mark.authorityExpiresMs)&&mark.authorityExpiresMs-c.nowMs>minRemainingMs;
}
