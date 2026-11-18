import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
const file=new URL("./off-03d7c5-qa-reference-import-gate.sh",import.meta.url).pathname;
const s=readFileSync(file,"utf8");
const run=args=>spawnSync("bash",[file,...args],{
  encoding:"utf8",timeout:7000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test("unsupported or unauthorized modes are rejected before remote operations",()=>{
  assert.equal(run([]).status,2);
  assert.equal(run(["--help"]).status,0);
  for(const op of ["migrate","restore","backup","apply-now","reset","deploy","seed","drop"]){
    const z=run([op]);
    assert.equal(z.status,1,op);
    assert.match(z.stderr,/unsupported_operation/);
  }
  const denied=run(["apply"]);
  assert.notEqual(denied.status,0);
  assert.match(denied.stderr,/(sudo_required|CONFIRM_QA_REFERENCE_IMPORT_required)/);
});
test("pin post-DDL backup not the old pre-DDL gate",()=>{
  for(const marker of [
    "6f772a25a9b552d792d7d2215cc5676cca56b5fe",
    "ebb773f88ba6740ddf4fef53f1b76de541346a85",
    "OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY",
    "OFF03D7C4_RESTORE_METADATA=PASS",
    "OFF03D6C3_AUDIT=PASS_READ_ONLY",
    "OFF03D7C5_POST_DDL_RECOVERY_POINT=PASS",
    "OFF03D7C5_MIGRATIONS_ACL=PASS",
  ])assert.ok(s.includes(marker),marker);
  assert.match(s,/bash "\$BACKUP_RUNNER" verify/);
  assert.match(s,/bash "\$AUDITOR" audit/);
  assert.doesNotMatch(s,/off03d6b2.*verify|off03d6c1.*inspect/);
});
test("same canonical checkout and official bundle as CI import evidence",()=>{
  for(const marker of [
    "7b9eb8c82a290d06e719ee4990c2020076bbd11b",
    "26ef9a3b3ce74f9a1df9a47b411758d8ceb1dc24",
    "622dadfe7dbd0b77cde36654733cb4eeda97f415",
    "e50d9842a7e071b754144c04037dc66a39c04bdc",
    "892cabe2acc80e60abf0c52aaf6ff616b84a5bae",
    "OFF03D7C5_OFFICIAL_SOURCE=PASS_PINNED",
    "load_bundle","VINTO-P1-18","VINTO-P1-22","VINTO-P1-26","VINTO-P1-27"
  ])assert.ok(s.includes(marker),marker);
  assert.match(s,/status --porcelain --untracked-files=all/);
});
test("QA-only fixed role and no credential disclosure; no env fallback",()=>{
  for(const marker of [
    "vinto-qa-postgres","vinto-qa-internal","postgres:17",
    "127.0.0.1:6554","vinto_qa_offline",
    "vinto_reference","PG_PRIVILEGE_MODE","hardened",
    "/etc/vinto-qa/role-reference.password","root:600","root:700",
    "CONFIRM_QA_REFERENCE_IMPORT=YES","CONFIRM_QA_TARGET",
    "OFF03D7C5_REFERENCE_ROLE_TARGET=PASS",
    "OFF03D7C5_REFERENCE_BASELINE=EMPTY_QA_ONLY",
  ])assert.ok(s.includes(marker),marker);
  assert.match(s,/subprocess\.run\(cmd, cwd=cwd, env=env, text=True/);
  assert.match(s,/capture_output=True/);
  const identityQuery=s.slice(s.indexOf('with psycopg.connect('),s.indexOf('print("OFF03D7C5_REFERENCE_ROLE_TARGET=PASS")'));
  assert.match(identityQuery,/NOT has_schema_privilege\('vinto_reference','vinto_meta','USAGE'\)/);
  assert.doesNotMatch(identityQuery,/FROM vinto_meta\.schema_migration/);
  assert.doesNotMatch(s,/print\(password\)|print\(clean_env\)|echo .*password|curl |git pull|git checkout|systemctl (?:restart|stop|start)|docker (?:run|rm|restart)/);
});
test("inspect only dry-runs; apply one transaction then metadata and read-only idempotence",()=>{
  assert.match(s,/OFF03D7C5_REFERENCE_DRY_RUN=PASS_READ_ONLY/);
  assert.match(s,/OFF03D7C5_PREFLIGHT=PASS_READ_ONLY/);
  assert.match(s,/OFF03D7C5_IMPORT=NOT_AUTHORIZED/);
  assert.match(s,/OFF03D7C5_REFERENCE_APPLY=PASS_ONE_QA_TRANSACTION/);
  assert.match(s,/OFF03D7C5_FOUR_QUALITY_VERSIONS=PUBLISHED/);
  assert.match(s,/OFF03D7C5_MACHINE_VERSION_LINKS=8/);
  assert.match(s,/OFF03D7C5_USER_AND_GRANTS=NOT_CREATED/);
  assert.match(s,/OFF03D7C5_IMPORT=PASS_QA_ONLY/);
  assert.match(s,/NO_DATABASE_WRITES=PASS/);
  assert.match(s,/default_transaction_read_only=on/);
  assert.match(s,/status='published'/);
  assert.match(s,/modo=dry-run/);
  assert.match(s,/modo=apply/);
  assert.equal((s.match(/"import_reference\.py"/g)||[]).length,1);
  assert.equal((s.match(/"--apply"/g)||[]).length,1);
});
