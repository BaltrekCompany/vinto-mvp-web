// OFF-04.8 v6 (Issue #247): safe reuse of a stored CAPTURE authority + coalescing. CAPTURE envelopes are signed by the REAL Python signer/domain (OFF048V_FIXTURE_JSON).
// "readVerified" below is the app's own verifier (verifyOperationalCaptureScope: signature, trusted pin, user, device, snapshot, operation, version, expiry), so every refusal is the real one.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {verifyOperationalCaptureScope} from "../lib/vinto/offline-operational-capture-scope-verify.ts";
import {selectReusableCapture,resolveCaptureAuthority,shouldSkipAutomatic,REUSE_MIN_REMAINING_MS,AUTO_COOLDOWN_MS} from "../lib/vinto/offline-capture-reuse.ts";

const path=process.env.OFF048V_FIXTURE_JSON;
if(!path)throw new Error("OFF048V_FIXTURE_JSON required (python scripts/off048v_fixture.py)");
const fx=JSON.parse(readFileSync(path,"utf8"));
const NOW=Date.parse(fx.now_iso), H=3600*1000;
const E=fx.env, ids=Object.fromEntries(Object.entries(E).map(([k,v])=>[k,v.payload.snapshot_id]));
const anchor=fx.fresh[0], target=id=>({scopeSnapshotId:id,machineCode:anchor.machine_code,formCode:anchor.form_code,formVersion:anchor.form_version});

// a device store holding the given envelopes; the verifier is the real one
function harness(names,{identity=fx.identity,pin=fx.pin,fresh=fx.fresh,now=NOW,issueEnv=null,listFails=false}={}){
  const byId=new Map(names.map(n=>[ids[n],E[n]])), calls={issue:0,read:[]};
  return {calls,run:()=>resolveCaptureAuthority({
    fresh,nowMs:now,
    listSnapshots:async()=>{if(listFails)throw Error("storage");return [...byId.keys()];},
    readVerified:async id=>{calls.read.push(id);return verifyOperationalCaptureScope(byId.get(id),pin,identity,target(id),now);},
    issue:async()=>{calls.issue++;if(!issueEnv)throw Error("issue_failed");return issueEnv;},
  })};
}
const NEW=E.ok_older; // stands for "what the server would sign now"
const reused=async(names,opts)=>{const h=harness(names,opts);const r=await h.run();assert.equal(h.calls.issue,0);return r;};
const issued=async(names,opts)=>{const h=harness(names,{issueEnv:NEW,...opts});const r=await h.run();assert.equal(h.calls.issue,1);assert.equal(r.reused,false);return r;};

test("1) same identity, same pairs/versions/operations/grants, > 8 h left: REUSED, nothing is issued",async()=>{
  const r=await reused(["ok"]);
  assert.equal(r.envelope.payload.snapshot_id,ids.ok);assert.equal(r.reused,true);assert.equal(r.reason,"reuse");
});
test("2) the newest of several equivalent valid authorities is the one reused",async()=>{
  const r=await reused(["ok_older","ok"]);assert.equal(r.envelope.payload.snapshot_id,ids.ok);
});
test("3) lifetime: exactly 8 h left -> a new one is issued; 8 h + 36 s -> reused; 7 h -> issued",async()=>{
  assert.equal(REUSE_MIN_REMAINING_MS,8*H);
  await issued(["rem_8h_exact"]);
  assert.equal((await reused(["rem_8h_plus"])).envelope.payload.snapshot_id,ids.rem_8h_plus);
  const r=await issued(["rem_7h"]);assert.equal(r.reason,"too_old");
});
test("4) a device clock BEHIND the server never extends a lifetime (the later of the two clocks is used)",async()=>{
  // the app passes max(device, server): with the server 2 h ahead, 8h01 left becomes 6h01 -> not reusable
  await issued(["rem_8h_plus"],{now:NOW+2*H});
  assert.equal((await reused(["rem_8h_plus"],{now:NOW})).reused,true);
});
test("5) expired or not-yet-valid authorities are rejected by the verifier and never reused",async()=>{
  await issued(["expired"]);await issued(["future"]);
  const r=await issued(["expired","future","rem_7h"]);assert.equal(r.considered,1);  // only rem_7h verifies, and it is too short
});
test("6) a pair REMOVED from the fresh scope (revocation) or ADDED to it forbids reuse",async()=>{
  const without=fx.fresh.filter(p=>p.form_code!=="VINTO-P1-22");
  assert.equal((await issued(["ok"],{fresh:without})).reason,"coverage_mismatch");       // candidate still carries the revoked pair
  assert.equal((await issued(["no_p122"])).reason,"coverage_mismatch");                   // fresh still has the pair the candidate lacks
  assert.equal((await reused(["no_p122"],{fresh:without})).reused,true);                  // exact equality on the reduced scope IS reusable
});
test("7) a changed form version or a re-issued grant forbids reuse",async()=>{
  await issued(["version_bump"]);await issued(["grant_changed"]);
  const bumped=fx.fresh.map(p=>p.form_code==="VINTO-P1-22"?{...p,form_version:p.form_version+1}:p);
  assert.equal((await issued(["ok"],{fresh:bumped})).reason,"coverage_mismatch");
});
test("8) NO escalation: a candidate wider than the fresh scope (extra machine) is never reused",async()=>{
  assert.equal((await issued(["extra_machine"])).reason,"coverage_mismatch");
});
test("9) wrong operation for the form, duplicated entry: refused by the verifier",async()=>{
  await issued(["wrong_operation"]);await issued(["duplicate_entry"]);
});
test("10) other user, other device, rotated key (wrong PIN): refused, never reused",async()=>{
  await issued(["other_user"]);await issued(["other_device"]);await issued(["rotated_key"]);
  await issued(["ok"],{pin:fx.rotated_pin});                      // the device pins a DIFFERENT key
  await issued(["ok"],{identity:fx.other_user});await issued(["ok"],{identity:fx.other_device});
});
test("11) tampered payload (expiry extended, pair edited), readiness-domain signature, readiness scope presented as CAPTURE: refused",async()=>{
  await issued(["tampered_expiry"]);await issued(["tampered_pair"]);await issued(["readiness_domain"]);await issued(["readiness_as_capture"]);
});
test("12) a bad candidate never blocks a good one, and nothing is ever deleted (the dependencies expose no delete)",async()=>{
  const r=await reused(["tampered_expiry","expired","ok","other_user"]);assert.equal(r.envelope.payload.snapshot_id,ids.ok);assert.equal(r.considered,1); // only "ok" verifies; the other three are refused by the real verifier
});
test("13) storage failure while listing -> a new authority is issued (fail closed); issuance failure propagates (previous set untouched by the caller)",async()=>{
  await issued(["ok"],{listFails:true});
  await assert.rejects(()=>harness(["rem_7h"]).run(),/issue_failed/);
});
test("14) empty fresh scope -> never reuse",()=>{
  assert.equal(selectReusableCapture([E.ok],[],NOW).reason,"no_fresh_pairs");
  assert.equal(selectReusableCapture([E.ok],[...fx.fresh,fx.fresh[0]],NOW).reason,"coverage_mismatch");
});
test("15) automatic cooldown: skipped only inside 10 min, same user/device/machine, authority comfortably valid; manual-style conditions never skip",()=>{
  const mark={at:NOW,ownerId:fx.identity.ownerId,deviceKey:fx.identity.deviceKey,machine:"MP1",authorityExpiresMs:NOW+20*H};
  const ctx=(dt,over={})=>({nowMs:NOW+dt,ownerId:fx.identity.ownerId,deviceKey:fx.identity.deviceKey,machine:"MP1",...over});
  assert.equal(AUTO_COOLDOWN_MS,10*60*1000);
  assert.equal(shouldSkipAutomatic(mark,ctx(60*1000)),true);
  assert.equal(shouldSkipAutomatic(mark,ctx(AUTO_COOLDOWN_MS)),false);                 // boundary: not skipped
  assert.equal(shouldSkipAutomatic(mark,ctx(-1)),false);                               // clock went backwards
  assert.equal(shouldSkipAutomatic(null,ctx(1000)),false);
  assert.equal(shouldSkipAutomatic(mark,ctx(1000,{ownerId:fx.other_user.ownerId})),false);
  assert.equal(shouldSkipAutomatic(mark,ctx(1000,{deviceKey:fx.other_device.deviceKey})),false);
  assert.equal(shouldSkipAutomatic(mark,ctx(1000,{machine:"MP3"})),false);
  assert.equal(shouldSkipAutomatic({...mark,authorityExpiresMs:NOW+8*H},ctx(1000)),false); // authority no longer comfortably valid
  assert.equal(shouldSkipAutomatic({...mark,authorityExpiresMs:NaN},ctx(1000)),false);
});
test("16) the page wiring: reuse runs AFTER the fresh scope is verified and BEFORE any capture-scope request; single flight; manual retry skips only the cooldown",()=>{
  const m=readFileSync(new URL("../lib/vinto/offline-operational-mobile-page.ts",import.meta.url),"utf8");
  const enroll=m.slice(m.indexOf("async function enroll("),m.indexOf("const RENEWAL_TEXT"));
  const iReadiness=enroll.indexOf("const verifiedReadiness=await readOfflineScope"),iResolve=enroll.indexOf("resolveCaptureAuthority({"),iPost=enroll.indexOf('"/api/offline/capture-scope"');
  assert.ok(iReadiness>0&&iResolve>iReadiness&&iPost>iResolve,"order: renewal -> fresh verified scope -> resolve -> (inside issue) POST");
  assert.equal((m.match(/"\/api\/offline\/capture-scope"/g)||[]).length,1);
  assert.match(enroll,/readVerified:snapshotId=>readCaptureAuthority\(/);
  assert.match(enroll,/nowMs:Math\.max\(Date\.now\(\),readinessResponse\.serverMs\?\?0\)/);
  assert.match(m,/if\(inflight\)return inflight/);
  assert.match(m,/autoPrepare\(\{manual:true\}\)/);
  assert.match(m,/if\(!manual&&shouldSkipAutomatic\(/);
  assert.doesNotMatch(enroll,/deleteDatabase|caches\.delete|localStorage\.clear|\.clear\(\)|\.delete\(/);
});
