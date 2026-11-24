// OFF-04.8T: the ONLY exception to package progression: a KNOWN OFF-04.7 pilot-synthetic package -> the real package (same form/machine/version/source checksum).
// Packages are signed by the real Python signer (OFF048T_FIXTURE_JSON). Old/new packages are first verified like the app does (signature, pin, identity, digest, scope binding).
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {verifyOfflineScope} from "../lib/vinto/offline-scope-verify.ts";
import {verifyQualityPackage,QualityPackageError} from "../lib/vinto/offline-quality-verify.ts";
import {assertPackageProgression,assertPackageTransition} from "../lib/vinto/offline-quality-store.ts";
import {isSyntheticPilotToRealTransition,SYNTHETIC_PILOT_PACKAGES,SYNTHETIC_PILOT_NOTE,SYNTHETIC_PILOT_MACHINE} from "../lib/vinto/offline-synthetic-pilot.ts";
import {RenewalError} from "../lib/vinto/offline-renewal.ts";

const path=process.env.OFF048T_FIXTURE_JSON;
if(!path)throw new Error("OFF048T_FIXTURE_JSON required (python scripts/off048t_fixture.py)");
const fx=JSON.parse(readFileSync(path,"utf8"));
const id=fx.identity, pin=fx.scopes.pilot.public_key_b64url;
const read=(p)=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const scopeOf=async(name)=>({envelope:await verifyOfflineScope(fx.scopes[name],pin,id),trustedPublicKey:pin});
const pkg=async(scopeName,key,identity=id)=>(await verifyQualityPackage(fx.packages[key],await scopeOf(scopeName),identity)).envelope.payload;
const rejects=(fn)=>assert.throws(fn,e=>e instanceof QualityPackageError&&e.reason==="invalid");

test("1) known pilot-synthetic -> real, same form/machine/version/source checksum: accepted (and ONLY thanks to the exception)",async()=>{
  for(const form of fx.four){
    const old=await pkg("pilot","pilot|"+form), next=await pkg("real","real|"+form);
    assert.equal(old.form_version,next.form_version);
    assert.notEqual(old.content_sha256,next.content_sha256);
    assert.equal(old.definition.source_definition_checksum,next.definition.source_definition_checksum);
    assert.throws(()=>assertPackageProgression(old,next),QualityPackageError);   // the strict rule alone still refuses
    assert.doesNotThrow(()=>assertPackageTransition(old,next),form);              // the pinned provenance lets exactly this through
    assert.equal(isSyntheticPilotToRealTransition(old,next),true);
  }
});

test("1b) the pinned allowlist is exactly what the OFF-04.7 pilot generator produces (ten forms, MP1 only)",()=>{
  assert.equal(SYNTHETIC_PILOT_MACHINE,"MP1");
  assert.deepEqual(Object.keys(SYNTHETIC_PILOT_PACKAGES).sort(),Object.keys(fx.known_pilot).sort());
  for(const [form,[version,content,source]] of Object.entries(fx.known_pilot))
    assert.deepEqual(SYNTHETIC_PILOT_PACKAGES[form],{version,content,source},form);
  assert.equal(new Set(Object.values(SYNTHETIC_PILOT_PACKAGES).map(p=>p.content)).size,10);
  assert.equal(SYNTHETIC_PILOT_NOTE,fx.pilot_note);
});

test("2) real -> synthetic is REJECTED (never the reverse direction)",async()=>{
  const old=await pkg("real","real|VINTO-P1-22"), next=await pkg("real2","reverse_new_synthetic");
  assert.equal(next.definition.note,SYNTHETIC_PILOT_NOTE);
  rejects(()=>assertPackageTransition(old,next));
  assert.equal(isSyntheticPilotToRealTransition(old,next),false);
});

test("3) same version + different hash WITHOUT valid pilot provenance is REJECTED (a matching note is not provenance)",async()=>{
  const forged=await pkg("pilot","forged_old"), noteOnly=await pkg("pilot","note_only_old"), good=await pkg("real","real|VINTO-P1-22");
  assert.equal(forged.definition.note,SYNTHETIC_PILOT_NOTE);                        // same note as the pilot...
  rejects(()=>assertPackageTransition(forged,good));                               // ...but its body hash is not one of the ten pinned hashes
  rejects(()=>assertPackageTransition(noteOnly,good));
  const other=await pkg("real2","real_other_body");
  rejects(()=>assertPackageTransition(good,other));                                // real -> other real body at the same version
});

test("4) lower version is REJECTED",async()=>{
  const old=await pkg("pilot","pilot|VINTO-P1-22"), low=await pkg("lower","lower_new");
  assert.equal(low.form_version,1);
  rejects(()=>assertPackageTransition(old,low));
  assert.equal(isSyntheticPilotToRealTransition(old,low),false);
});

test("5) different source_definition_checksum is REJECTED",async()=>{
  const old=await pkg("pilot","pilot|VINTO-P1-22"), next=await pkg("real2","other_source_new");
  rejects(()=>assertPackageTransition(old,next));
  assert.equal(isSyntheticPilotToRealTransition(old,next),false);
});

test("5b) other machine, other user/device, capture-enabled or older-issued NEW packages never use the exception",async()=>{
  const old=await pkg("pilot","pilot|VINTO-P1-22"), next=await pkg("real","real|VINTO-P1-22");
  const mut=(o,patch)=>structuredClone({...o,...patch});
  assert.equal(isSyntheticPilotToRealTransition(mut(old,{machine_code:"MP3"}),mut(next,{machine_code:"MP3"})),false);
  assert.equal(isSyntheticPilotToRealTransition(old,mut(next,{subject_user_id:"99999999-9999-4999-8999-999999999999"})),false);
  assert.equal(isSyntheticPilotToRealTransition(old,mut(next,{device_key:"99999999-9999-4999-8999-999999999999"})),false);
  assert.equal(isSyntheticPilotToRealTransition(old,mut(next,{captures_enabled:true})),false);
  assert.equal(isSyntheticPilotToRealTransition(old,mut(next,{issued_at:"2026-11-20T00:00:00Z"})),false);
  assert.equal(isSyntheticPilotToRealTransition(mut(old,{form_version:3}),mut(next,{form_version:3})),false);
  assert.equal(isSyntheticPilotToRealTransition(old,old),false);
});

test("6) wrong identity, wrong device, wrong signing key or altered content are REJECTED before any transition is considered",async()=>{
  for(const [identity,why] of [[fx.other_identity,"user"],[fx.other_device_identity,"device"]])
    await assert.rejects(pkg("real","real|VINTO-P1-22",identity),e=>e instanceof QualityPackageError&&e.reason==="scope",why);
  await assert.rejects(verifyQualityPackage(fx.packages.foreign_subject,await scopeOf("real"),id),e=>e instanceof QualityPackageError&&e.reason==="scope");
  await assert.rejects(verifyQualityPackage(fx.packages.foreign_device,await scopeOf("real"),id),e=>e instanceof QualityPackageError&&e.reason==="scope");
  await assert.rejects(verifyQualityPackage(fx.packages.rotated_key,await scopeOf("real"),id),e=>e instanceof QualityPackageError&&(e.reason==="pin"||e.reason==="scope"));
  const tampered=structuredClone(fx.packages["real|VINTO-P1-22"]); tampered.payload.definition.note="otra nota";
  await assert.rejects(verifyQualityPackage(tampered,await scopeOf("real"),id),e=>e instanceof QualityPackageError&&e.reason==="digest");
  const resigned=structuredClone(fx.packages["real|VINTO-P1-22"]); resigned.signature_b64url=fx.packages["real|VINTO-P1-18"].signature_b64url;
  await assert.rejects(verifyQualityPackage(resigned,await scopeOf("real"),id),e=>e instanceof QualityPackageError&&e.reason==="signature");
  const oldTampered=structuredClone(fx.packages["pilot|VINTO-P1-22"]); oldTampered.payload.definition.note="Synthetic QA-only definition; no industrial captures";
  await assert.rejects(verifyQualityPackage(oldTampered,await scopeOf("pilot"),id),e=>e instanceof QualityPackageError&&e.reason==="digest");
});

test("2b) the two rollback causes are distinguishable and user-readable",()=>{
  assert.equal(new RenewalError("rollback_scope").message,"OFFLINE_RENEWAL_ROLLBACK_SCOPE");
  assert.equal(new RenewalError("rollback_package").message,"OFFLINE_RENEWAL_ROLLBACK_PACKAGE");
  const r=read("lib/vinto/offline-renewal.ts");
  assert.match(r,/if \(order !== "newer" && order !== "identical"\) throw new RenewalError\("rollback_scope"\)/);
  assert.match(r,/assertPackageTransition\(old\.envelope\.payload, p\)[\s\S]*?throw new RenewalError\("rollback_package"\)/);
  assert.doesNotMatch(r,/RenewalError\("rollback"\)/);
  const m=read("lib/vinto/offline-operational-mobile-page.ts");
  assert.match(m,/OFFLINE_RENEWAL_ROLLBACK_SCOPE/); assert.match(m,/OFFLINE_RENEWAL_ROLLBACK_PACKAGE/);
  assert.doesNotMatch(m.slice(m.indexOf("const RENEWAL_TEXT"),m.indexOf("let preparationBusy")),/signature_b64url|payload_sha256|content_sha256/);
});

test("7-9) renewal stays atomic; first-time storage stays strict; drafts untouched; CAPTURE authority is independent and still required",()=>{
  const r=read("lib/vinto/offline-renewal.ts"), s=read("lib/vinto/offline-quality-store.ts"), m=read("lib/vinto/offline-operational-mobile-page.ts"), p=read("lib/vinto/offline-synthetic-pilot.ts");
  assert.match(r,/db\.transaction\(\["profiles", SCOPE_STORE_NAME, PACKAGE_STORE_NAME\], "readwrite"\)/);   // ONE transaction: scope + packages
  assert.doesNotMatch(r.slice(0,r.indexOf("Explicit recovery policy")),/deleteDatabase|\.clear\(\)|\.delete\(/);   // renewal never deletes anything
  assert.match(s,/if\(previous\)assertPackageProgression\(previous\.envelope\.payload,p\)/);               // storeQualityPackage keeps the STRICT rule
  assert.match(s,/export function assertPackageTransition/);
  assert.doesNotMatch(p,/fetch\(|indexedDB|localStorage|crypto\.subtle\.sign/);                            // pure predicate, no I/O
  const enroll=m.slice(m.indexOf("async function enroll("),m.indexOf("function offlineReadyStatus")>0?m.indexOf("function offlineReadyStatus"):m.indexOf("async function offlineReadyStatus"));
  assert.match(enroll,/await renewOfflineBundle\(/);
  assert.match(enroll,/api\("POST","\/api\/offline\/capture-scope"/);
  assert.match(enroll,/storeCaptureAuthority\(opened,identityNow,signed/);
  assert.ok(enroll.indexOf("renewOfflineBundle(")<enroll.indexOf("capture-scope"));                       // CAPTURE is issued AFTER, by the server, independently
  assert.doesNotMatch(enroll,/indexedDB\.deleteDatabase|caches\.delete|localStorage\.clear|discardSupersededPackages/);
  assert.match(m,/quality-static-v7/);
});
