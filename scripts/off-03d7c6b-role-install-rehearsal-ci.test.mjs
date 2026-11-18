import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
const path=new URL("./off-03d7c6b-role-install-rehearsal-ci.sh",import.meta.url).pathname;
const s=readFileSync(path,"utf8");
test("CI-only runner rejects local/VPS execution before Docker",()=>{
 const p=spawnSync("bash",[path],{
   encoding:"utf8",timeout:5000,
   env:{PATH:process.env.PATH,HOME:process.env.HOME,GITHUB_ACTIONS:"false"}
 });
 assert.equal(p.status,2);
 assert.match(p.stderr,/OFF03D5_CI_ONLY=BLOCKED/);
});
test("role creation and grants only in disposable runner, exact approved SQL",()=>{
 for(const marker of [
  "04bc90dfeaf225d2c139587899fa46ce54913fe5",
  "6df9ac8c96d6cf85a00aecccc6631f8eddc7450b",
  "0039f4c530b611873f4b60710bf42aec54edd2c7",
  "00c_create_identity_role.sql",
  "03c_d3b2_identity_role_grants.sql",
  "rollback/ROLLBACK_D3B2.sql",
  "openssl rand -hex 32",
  "IFS= read -r IDENTITY_PASSWORD; export IDENTITY_PASSWORD",
  "OFF03D7C6B_CI_ROLE_GRANTS=PASS_ADDITIVE_ONLY",
  "OFF03D7C6B_CI_ROLLBACK_D3B2=PASS_REVOKES_ONLY",
  "OFF03D7C6B_CI_IDENTITY_DML_CUT=NOT_EXECUTED",
  "OFF03D7C6B_CI_PILOT_TVC=NOT_TOUCHED",
  "OFF03D7C6B_CI_FULL_REHEARSAL=PASS_EPHEMERAL_ONLY",
 ])assert.ok(s.includes(marker),marker);
 assert.match(s,/docker exec -i "\$NAME" bash/);
 assert.match(s,/docker exec -i "\$NAME" psql/);
 assert.doesNotMatch(s,/docker exec.* -e IDENTITY_PASSWORD=|psql .* -v identity_password=|IDENTITY_PASSWORD="\$\(cat/);
});
test("rollback leaves role present and preserves original vinto_app identity DML",()=>{
 assert.match(s,/EXISTS \(SELECT 1 FROM pg_roles WHERE rolname='vinto_identity'\)/);
 assert.match(s,/has_table_privilege\('vinto_app','vinto_master\.\\"user\\"','INSERT'\)/);
 assert.match(s,/NOT has_database_privilege\('vinto_identity',current_database\(\),'CONNECT'\)/);
 assert.match(s,/OFF03D7C6B_CI_IDENTITY_ROLE_REMOVAL=NOT_TESTED_NOT_PART_OF_D3B2/);
});
test("no source-controlled secrets, no SSH to QA or production, and no D3B4 cut",()=>{
 assert.doesNotMatch(s,/51\.79\.65\.225|:6554|\/etc\/vinto-qa|ssh |kubectl |git pull|off03d7c6b-qa-identity-role-preflight\.sh apply/);
 assert.doesNotMatch(s,/03d_d3b4_cut_identity_dml\.sql|DROP ROLE vinto_identity|REVOKE .* FROM vinto_app/);
});
