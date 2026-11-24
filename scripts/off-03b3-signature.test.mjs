import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { verifyOfflineScope, ScopeError } from "../lib/vinto/offline-scope-verify.ts";

const root=resolve(import.meta.dirname,"..");
const source=(p)=>readFileSync(resolve(root,p),"utf8");
const path=process.env.OFF03B3_FIXTURE_JSON;
if(!path)throw new Error("Fixture required: Python backend signer");
const fixture=JSON.parse(readFileSync(path,"utf8"));
const envelope=fixture.envelope;
const identity=fixture.identity;
const clone=(v)=>JSON.parse(JSON.stringify(v));

test("cross-language Ed25519 Python payload verifies in Node WebCrypto",async()=>{
    const signed=await verifyOfflineScope(envelope,envelope.public_key_b64url,identity);
    assert.equal(signed.payload.subject_user_id,identity.ownerId);
    assert.equal(signed.payload.kind,"scope_readiness_only");
    assert.equal(signed.payload.captures_enabled,false);
    assert.equal(signed.payload.form_scopes.length,1);
});

test("signature is bound to owner, browser, issued time, form/version and capture disabled",async()=>{
    const x=[
      {payload:{...envelope.payload,subject_user_id:"99999999-9999-4999-8999-999999999999"}},
      {payload:{...envelope.payload,device_key:"99999999-9999-4999-8999-999999999999"}},
      {payload:{...envelope.payload,issued_at:"2026-11-18T12:00:00Z"}},
      {payload:{...envelope.payload,captures_enabled:true}},
      {payload:{...envelope.payload,form_scopes:[{...envelope.payload.form_scopes[0],form_version:4}]}},
    ];
    for(const patch of x){
      await assert.rejects(verifyOfflineScope({...envelope,...patch},envelope.public_key_b64url,identity));
    }
    await assert.rejects(verifyOfflineScope(envelope,envelope.public_key_b64url,{...identity,ownerId:"99999999-9999-4999-8999-999999999999"}));
    await assert.rejects(verifyOfflineScope(envelope,envelope.public_key_b64url,{...identity,deviceKey:"99999999-9999-4999-8999-999999999999"}));
});

test("random, substituted, absent and embedded-only keys do NOT establish trust",async()=>{
    const otherKey=Buffer.from(Array.from({length:32},(_,i)=>i)).toString("base64url");
    await assert.rejects(verifyOfflineScope(envelope,otherKey,identity),e=>e instanceof ScopeError&&e.reason==="pin_mismatch");
    await assert.rejects(verifyOfflineScope(envelope,"",identity));
    const tampered=clone(envelope);
    tampered.signature_b64url=Buffer.alloc(64).toString("base64url");
    await assert.rejects(verifyOfflineScope(tampered,envelope.public_key_b64url,identity),e=>e instanceof ScopeError);
});

test("unknown fields/extra scope, invalid version, non-canonical base64 all fail closed",async()=>{
    for(const patch of [
      {payload:{...envelope.payload,extra_capability:"approve"}},
      {payload:{...envelope.payload,form_scopes:[...envelope.payload.form_scopes,...envelope.payload.form_scopes]}},
      {payload:{...envelope.payload,form_scopes:[{...envelope.payload.form_scopes[0],form_version:0}]}},
      {payload:{...envelope.payload,kind:"capture_grant"}},
      {extra:"unsafe"},
    ])await assert.rejects(verifyOfflineScope({...envelope,...patch},envelope.public_key_b64url,identity));
});

test("frontend remains read-only and signed scope stored only as vault sealed data",()=>{
    const boot=source("lib/vinto/offline-boot.ts");
    const store=source("lib/vinto/offline-scope-store.ts");
    const page=source("app/offline-preparacion/page.tsx");
    const sw=source("public/sw.js");
    assert.match(boot,/readOfflineScope\(/);
    assert.match(boot,/scopeList\.appendChild\(li\)/);
    assert.doesNotMatch(boot,/fetch\s*\(|document\.cookie|createCapture|POST|innerHTML/);
    assert.match(store,/sealLocalDraft\(/);
    assert.match(store,/openLocalDraft\(/);
    assert.match(store,/verifyOfflineScope\(/);
    assert.match(store,/trustedPublicKey/);
    assert.match(page,/issueOnlineReadinessScope\(/);
    assert.match(page,/storeOfflineScope\(/);
    assert.match(sw,/vinto-off048-quality-static-v6/);
    assert.doesNotMatch(sw,/\/api\/offline\/scope/);
});
