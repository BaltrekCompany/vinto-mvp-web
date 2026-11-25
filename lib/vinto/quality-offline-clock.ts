/**
 * An offline CAPTURE scope is signed by VINTO, not by the device. Calibrate
 * only the local wall-clock offset using the Date header on the SAME
 * authenticated HTTPS response which provided that signed scope. Never
 * extend the signed expiration or accept a cached/unsigned authority.
 */
import type {CaptureScopeEnvelope} from "./offline-operational-capture-scope-verify";

export type QualityOfflineClock=Readonly<{
  serverDateMs:number;
  clientReceivedAtMs:number;
}>;

const MAX_RESPONSE_SKEW_MS=5000;
const HEADER_GRANULARITY_MS=1000;
const MAX_SCOPE_MS=24*60*60*1000;

export function validateQualityServerClock(
 envelope:CaptureScopeEnvelope,clock:QualityOfflineClock,
):QualityOfflineClock{
 const issued=Date.parse(envelope.payload.issued_at);
 const expires=Date.parse(envelope.payload.expires_at);
 if(!Number.isFinite(issued)||!Number.isFinite(expires)||
    !Number.isFinite(clock.serverDateMs)||!Number.isFinite(clock.clientReceivedAtMs)||
    expires<=issued||expires-issued>MAX_SCOPE_MS||
    clock.serverDateMs<issued-MAX_RESPONSE_SKEW_MS||
    clock.serverDateMs>=expires)
   throw new Error("offline_quality_server_clock_invalid");
 return clock;
}
/** Offline age uses the offset anchored to authenticated server time.
 * Expired grants still fail closed even when the handset clock is inaccurate.
 */
export function qualityScopeNow(clock:QualityOfflineClock):number{
 return clock.serverDateMs + Math.max(0,Date.now()-clock.clientReceivedAtMs)+HEADER_GRANULARITY_MS;
}
