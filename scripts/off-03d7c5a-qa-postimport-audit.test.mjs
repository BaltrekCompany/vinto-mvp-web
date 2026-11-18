import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const path = new URL("./off-03d7c5a-qa-postimport-audit.sh", import.meta.url).pathname;
const source = readFileSync(path,"utf8");
const run = (...args) => spawnSync("bash",[path,...args],{
  encoding:"utf8", timeout:5000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("only audit accepted; all mutating/legacy modes denied before tools",()=>{
  assert.equal(run().status,2);
  assert.equal(run("--help").status,0);
  for(const arg of ["apply","import","inspect","backup","restore","migrate","seed","deploy","reset","verify"]){
    const x=run(arg);
    assert.equal(x.status,1,arg);
    assert.match(x.stderr,/only_read_only_audit_permitted/);
  }
});

test("uses only postimport-valid C3 and D7C4 verify, NEVER preimport gates",()=>{
  for(const key of [
    "ebb773f88ba6740ddf4fef53f1b76de541346a85",
    "6f772a25a9b552d792d7d2215cc5676cca56b5fe",
    "OFF03D6C3_AUDIT=PASS_READ_ONLY",
    "OFF03D6C3_MIGRATION_HISTORY_31=PASS",
    "OFF03D6C3_MIGRATION_CHECKSUMS=PASS",
    "OFF03D6C3_POSTMIGRATION_ACL=PASS",
    "OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY",
    "OFF03D7C4_RESTORE_METADATA=PASS",
    "OFF03D7C5A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY",
    "OFF03D7C5A_PILOT_TVC_STATUS=PASS_AT_AUDIT",
  ]) assert.ok(source.includes(key),key);
  assert.match(source,/bash "\$C3" audit/);
  assert.match(source,/bash "\$BACKUP" verify/);
  assert.doesNotMatch(source,/bash .*off03d7c5.*inspect|bash .*off03d7c4.*inspect|bash .*off03d6b2.*verify|bash .*off03d6c1.*inspect/);
});

test("pins QA isolated DB, vetted importer and bundle, never production",()=>{
  for(const key of [
    "vinto-qa-postgres","vinto_qa_offline","vinto-qa-internal",
    "127.0.0.1:6554","postgres:17",
    "7b9eb8c82a290d06e719ee4990c2020076bbd11b",
    "892cabe2acc80e60abf0c52aaf6ff616b84a5bae",
    "26ef9a3b3ce74f9a1df9a47b411758d8ceb1dc24",
    "622dadfe7dbd0b77cde36654733cb4eeda97f415",
    "source_checksum", "load_bundle()",
    "OFF03D7C5A_CANONICAL_BUNDLE=PASS"
  ])assert.ok(source.includes(key),key);
  assert.match(source,/git -C "\$SOURCE" status --porcelain --untracked-files=all/);
  assert.doesNotMatch(source,/51\.79\.65\.225|:6543|:6544|docker (?:run|rm|stop|restart)|systemctl (?:start|stop|restart)/);
});

test("SQL checks all canonical categories and exactly eight quality pairs",()=>{
  const sql=source.slice(source.indexOf('SQL="$(cat <<SQL'),source.indexOf('metadata="$(docker exec'));
  assert.match(sql,/current_database\(\)='vinto_qa_offline'/);
  assert.match(sql,/count\(\*\) FROM vinto_meta\.schema_migration\)=31/);
  for(const part of ["sector)=3","profile)=5","machine)=18","article)=315","article_machine)=340","form)=26","form_version)=26"])
    assert.ok(sql.includes(part),part);
  assert.match(sql,/status='published'\)=26/);
  assert.match(sql,/source_checksum='\$CHECKSUM'/);
  assert.match(sql,/source='vinto-reference-bobinas'/);
  assert.match(sql,/count\(\*\) FROM pairs\)=8/);
  assert.match(sql,/CROSS JOIN \(VALUES \('MP1'\),\('MP3'\)\)/);
  assert.match(sql,/count\(\*\) FROM vinto_master\."user"\)=0/);
  assert.match(sql,/count\(\*\) FROM vinto_master\.user_machine_form_grant\)=0/);
  assert.match(source,/default_transaction_read_only=on/);
  assert.match(source,/OFF03D7C5A_FULL_REFERENCE_CATALOG=PASS_COUNTS/);
  assert.match(source,/OFF03D7C5A_QUALITY_PUBLISHED=PASS_FOUR_VERSIONS/);
});

test("postimport dry-run enforces readonly at libpq and never calls apply",()=>{
  assert.match(source,/PGOPTIONS":"-c default_transaction_read_only=on -c statement_timeout=120000/);
  assert.match(source,/PG_PRIVILEGE_MODE":"hardened"/);
  assert.match(source,/REFERENCE_DATABASE_URL":/);
  assert.match(source,/PGPASSWORD":password/);
  assert.match(source,/capture_output=True/);
  assert.match(source,/--target","dev"/);
  assert.match(source,/CONSISTENT \/ NO CHANGES/);
  assert.match(source,/NO-OP:/);
  assert.match(source,/OFF03D7C5A_IDEMPOTENCE=PASS_READ_ONLY/);
  assert.match(source,/OFF03D7C5A_AUDIT=PASS_READ_ONLY/);
  assert.match(source,/NO_DATABASE_WRITES=PASS/);
  assert.doesNotMatch(source,/["']--apply["']|import_reference\.py.*--apply|INSERT INTO|DELETE FROM|UPDATE .* SET|CREATE TABLE|pg_restore --|pg_dump --/);
});
