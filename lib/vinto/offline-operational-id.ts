/** OFF-04.8L — deterministic, owner/device/draft-bound operational capture ID.
 * Distinct domain from OFF-04.2 synthetic laboratory. Reconciliation and
 * retries MUST preserve this ID; never mint another ID for the same draft.
 */
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function operationalCaptureId(ownerId:string,deviceKey:string,draftId:string):Promise<string>{
  if(![ownerId,deviceKey,draftId].every(v=>UUID.test(v)))throw new TypeError("invalid identity");
  if(!globalThis.crypto?.subtle)throw new Error("secure crypto required");
  const raw=[ownerId,deviceKey,draftId].map(v=>v.toLowerCase()).join(":");
  const hash=new Uint8Array(await crypto.subtle.digest("SHA-256",
    new TextEncoder().encode("VINTO:OFF048:OPCAP:v1:"+raw)));
  const b=hash.slice(0,16);
  b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
  const h=Array.from(b,x=>x.toString(16).padStart(2,"0")).join("");
  return [h.slice(0,8),h.slice(8,12),h.slice(12,16),h.slice(16,20),h.slice(20)].join("-");
}
