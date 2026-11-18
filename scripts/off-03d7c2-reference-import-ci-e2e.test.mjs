import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
const path = new URL("./off-03d7c2-reference-import-ci-e2e.sh", import.meta.url).pathname;
const source = readFileSync(path, "utf8");
const run = (args, env={}) => spawnSync("bash", [path, ...args], {
 encoding:"utf8", timeout:4000,
 env:{PATH:process.env.PATH, HOME:process.env.HOME,...env}
});
test("cannot run destructive CI fixture scenario on VPS without runner attestation",()=>{
 const v=run([]);
 assert.equal(v.status,2);
 assert.match(v.stderr,/OFF03D5_CI_ONLY=BLOCKED/);
 assert.match(source,/GITHUB_ACTIONS/);
 assert.match(source,/OFF03D7C2_REAL_VPS_TOUCHED=NO/);
});
test("reference source and independent QA connection are fixed",()=>{
 for(const part of [
   "postgres:17","vinto_qa_offline","vinto_reference",
   "PG_PRIVILEGE_MODE=hardened","REFERENCE_DATABASE_URL=",
   "qa_offline_fixture_contract", "validate_repo_qa_fixture_contract",
   "OFF03D7C2_CANONICAL_BUNDLE=PASS",
 ]) assert.ok(source.includes(part),part);
 assert.match(source,/import_reference\.py --target dev > /);
 assert.match(source,/import_reference\.py --target dev --apply >/);
 assert.match(source,/OFF03D7C2_REFERENCE_DRY_RUN=PASS_READ_ONLY/);
 assert.match(source,/OFF03D7C2_CI_REFERENCE_IMPORT=PASS_EPHEMERAL/);
 assert.match(source,/OFF03D7C2_IDEMPOTENT_RERUN=PASS_READ_ONLY/);
});
test("QA versions remain drafts and no synthetic user or grants created",()=>{
 assert.match(source,/VINTO-P1-18.*2/);
 assert.match(source,/VINTO-P1-22.*2/);
 assert.match(source,/VINTO-P1-26.*3/);
 assert.match(source,/VINTO-P1-27.*2/);
 assert.match(source,/status='draft'/);
 assert.match(source,/OFF03D7C2_CI_FOUR_QUALITY_VERSIONS=DRAFT_NOT_PUBLISHED/);
 assert.match(source,/count\(\*\) FROM vinto_master/);
 assert.match(source,/count\(\*\) FROM vinto_master\.user_machine_form_grant/);
 assert.match(source,/OFF03D7C2_CI_TEST_USER_AND_GRANTS=NOT_CREATED/);
});
test("ephemeral resources are removed and scripts lack real target shortcuts",()=>{
 assert.match(source,/trap cleanup EXIT/);
 assert.match(source,/docker rm -f "\$NAME"/);
 assert.match(source,/mktemp -d/);
 assert.match(source,/127\.0\.0\.1:\$PORT/);
 assert.doesNotMatch(source,/51\.79\.65\.225|6543|6544|:6554|\/srv\/vinto-qa-offline|\/etc\/vinto-qa|qa-vinto-mvp\.baltrekservices\.com/);
});
