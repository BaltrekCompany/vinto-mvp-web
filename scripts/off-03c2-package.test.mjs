// OFF-03C.2: Python Ed25519 package verified in Node WebCrypto with SHA256 and scope pin.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { verifyOfflineScope } from "../lib/vinto/offline-scope-verify.ts";
import { verifyQualityPackage, QualityPackageError } from "../lib/vinto/offline-quality-verify.ts";

const path=process.env.OFF03C2_FIXTURE_JSON;
if(!path)throw new Error("Python signed fixture required");
const fixture=JSON.parse(readFileSync(path,"utf8"));
const identity=fixture.identity;
const scope=await verifyOfflineScope(fixture.envelope,fixture.envelope.public_key_b64url,identity);
const trusted={envelope:scope,trustedPublicKey:fixture.envelope.public_key_b64url};
const packageEnvelope=fixture.quality_package;
const tamper=(field,value)=>{
    const next=structuredClone(packageEnvelope);
    next.payload[field]=value;
    return next;
};
test("real Python Ed25519 package and SHA256 accepted by Node under pinned signed scope",async()=>{
    const result=await verifyQualityPackage(packageEnvelope,trusted,identity);
    assert.equal(result.envelope.payload.form_code,"VINTO-P1-18");
    assert.equal(result.envelope.payload.definition.fields.length,3);
    assert.equal(result.envelope.payload.definition.capture_eligible,false);
    assert.equal(result.envelope.payload.captures_enabled,false);
});
test("mutable field/option, digest, machine, grant, actor, version, capture flag all rejected",async()=>{
    const mutations=[
      tamper("content_sha256","f".repeat(64)),
      tamper("machine_code","MP3"),
      tamper("form_version",5),
      tamper("grant_id","66666666-6666-4666-8666-666666666666"),
      tamper("subject_user_id","77777777-7777-4777-8777-777777777777"),
      tamper("captures_enabled",true),
      tamper("definition",{...packageEnvelope.payload.definition,fields:[]})
    ];
    for(const candidate of mutations)await assert.rejects(verifyQualityPackage(candidate,trusted,identity));
    const changed=structuredClone(packageEnvelope);
    changed.payload.definition.fields[0].label="Malicious edited label";
    await assert.rejects(verifyQualityPackage(changed,trusted,identity),e=>e instanceof QualityPackageError && e.reason==="digest");
});
test("scope snapshot, username, device and pin not transferable",async()=>{
    await assert.rejects(verifyQualityPackage(packageEnvelope,{...trusted,trustedPublicKey:"A".repeat(43)},identity));
    await assert.rejects(verifyQualityPackage(packageEnvelope,trusted,{...identity,ownerId:"77777777-7777-4777-8777-777777777777"}));
    const other=structuredClone(scope);
    other.payload.snapshot_id="88888888-8888-4888-8888-888888888888";
    await assert.rejects(verifyQualityPackage(packageEnvelope,{...trusted,envelope:other},identity));
    const different=structuredClone(scope);
    different.payload.form_scopes=[];
    await assert.rejects(verifyQualityPackage(packageEnvelope,{...trusted,envelope:different},identity));
});
test("unknown fields, calculated inconsistencies and automatic field forbidden",async()=>{
    for(const change of [
       {extra:true},
       {fields:packageEnvelope.payload.definition.fields.map(x=>({...x,source:"automatic"}))},
       {fields:packageEnvelope.payload.definition.fields.map(x=>({...x,source:"calculated"}))},
       {groups:[{repeatable:true}]},
       {recipe_bundle_included:true},
       {capture_eligible:true},
    ]){
       const candidate=structuredClone(packageEnvelope);
       Object.assign(candidate.payload.definition,change);
       await assert.rejects(verifyQualityPackage(candidate,trusted,identity));
    }
});
test("frontend only lists metadata, encrypted storage and no API sync",()=>{
    const root=resolve(import.meta.dirname,"..");
    const read=p=>readFileSync(resolve(root,p),"utf8");
    const store=read("lib/vinto/offline-quality-store.ts");
    const boot=read("lib/vinto/offline-boot.ts");
    const sw=read("public/sw.js");
    assert.match(store,/sealLocalDraft\(/);
    assert.match(store,/openLocalDraft\(/);
    assert.match(store,/verifyQualityPackage\(/);
    assert.match(store,/PACKAGE_STORE_NAME/);
    assert.match(boot,/readQualityPackage\(/);
    assert.match(boot,/document\.createElement\("details"\)/);
    assert.doesNotMatch(boot,/fetch\s*\(|innerHTML|postCapture|submitCapture|sendCapture/);
    assert.doesNotMatch(sw,/\/api\/offline\/quality-package/);
    assert.match(read("backend/app/offline_scope/router.py"),/offline_quality_package_issue_enabled/);
});
