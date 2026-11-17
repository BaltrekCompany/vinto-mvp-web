import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
const file=new URL('./off-03d6c2-qa-migration-runner.sh',import.meta.url).pathname;
const src=readFileSync(file,'utf8');
const run=(args=[])=>spawnSync('bash',[file,...args],{
  encoding:'utf8',timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test('help and unsupported commands reject without filesystem/DB access',()=>{
  const help=run(['--help']);
  assert.equal(help.status,0,help.stderr);
  assert.match(help.stdout,/inspect/);
  assert.match(help.stdout,/CONFIRM_QA_MIGRATIONS=YES/);
  for(const op of ['migrate','deploy','reset','drop','restore','install','status','verify']){
    const out=run([op]);
    assert.equal(out.status,1,op);
    assert.match(out.stderr,/modo no soportado/);
  }
  assert.equal(run([]).status,2);
});
test('apply gated before any subprocess or Docker call',()=>{
  assert.match(src,/\[ "\$\(printenv CONFIRM_QA_MIGRATIONS[^\n]*" = YES \]/);
  assert.match(src,/CONFIRM_QA_TARGET=vinto_qa_offline_6554/);
  assert.match(src,/if \[ "\$MODE" = apply \]; then/);
  assert.ok(src.indexOf('CONFIRM_QA_MIGRATIONS')<src.indexOf('bash "$C1" inspect'));
  assert.match(src,/os\.environ\.get\("CONFIRM_QA_MIGRATIONS"\) != "YES"/);
  assert.match(src,/os\.environ\.get\("CONFIRM_QA_TARGET"\) != "vinto_qa_offline_6554"/);
});
test('refuses drift and requires C1 restore-proof before DDL',()=>{
  assert.match(src,/C1_BLOB=376bad3820642ac0efa038222f171bd5f2d97607/);
  assert.match(src,/bash "\$C1" inspect \|\| die/);
  assert.match(src,/PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b/);
  assert.match(src,/git hash-object/);
  assert.match(src,/HEAD:/);
  assert.match(src,/OFF03D6C2_PINNED_MIGRATOR_ACL=PASS/);
  assert.match(src,/OFF03D6C2_HISTORY_BEFORE=EMPTY/);
});
test('target is hard-coded QA, all migration env is freshly sanitized',()=>{
  assert.match(src,/host="127\.0\.0\.1", port=6554, dbname="vinto_qa_offline"/);
  assert.match(src,/user="vinto_migrator", password=password/);
  assert.match(src,/vinto-qa-postgres/);
  assert.match(src,/pg_postmaster_start_time\(\)/);
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/clean_env = \{/);
  assert.match(src,/"PG_PRIVILEGE_MODE": "hardened"/);
  assert.match(src,/"MIGRATOR_DATABASE_URL":/);
  assert.match(src,/postgresql:\/\/vinto_migrator@127\.0\.0\.1:6554\/vinto_qa_offline/);
  assert.match(src,/"PGPASSWORD": password/);
  assert.match(src,/env=clean_env/);
  assert.doesNotMatch(src,/postgresql:\/\/[^@\s]*:[^@\s]*@/);
  assert.doesNotMatch(src,/PGPASSWORD=.+-e /);
});
test('applying 31 SQL and ACL order is explicit; no production modifications',()=>{
  assert.match(src,/--target", "dev", "--status"/);
  assert.match(src,/status\.stdout\.count\(": pendiente"\) != 31/);
  assert.match(src,/--target", "dev", "--check"/);
  assert.match(src,/checked\.stdout\.count\(": aplicada"\) != 31/);
  const order=[
    '02_schema_grants.sql','03_table_grants.sql',
    '03b_d3b1_restrict_catalog_writes.sql',
    '04_function_grants.sql','05_no_default_privileges.sql',
    '06_public_and_meta_protection.sql',
    '07_verification_queries.sql','08_release_preflight.sql'
  ];
  const indices=order.map(item=>src.indexOf('"'+item+'"'));
  assert.ok(indices.every(n=>n>=0));
  assert.deepEqual([...indices].sort((x,y)=>x-y),indices);
  assert.match(src,/OFF03D6C2_POSTMIGRATION_ACL=PASS/);
  assert.match(src,/OFF03D6C2_APPLY=PASS_QA_ONLY/);
  assert.doesNotMatch(src,/docker (?:run|rm|stop|restart|volume|network)/);
  assert.doesNotMatch(src,/postgres-vinto|vinto-mvp-postgres|vinto_piloto|6544|6543/);
});
test('embedded Python syntax and absence of filesystem changes during inspect',()=>{
  const m=src.match(/<<'PY'\n([\s\S]*?)\nPY\n/);
  assert.ok(m);
  const parsed=spawnSync('python3',['-c','import ast,sys; ast.parse(sys.stdin.read())'],{
    input:m[1],encoding:'utf8'
  });
  assert.equal(parsed.status,0,parsed.stderr);
  assert.match(m[1],/if mode == "inspect":/);
  assert.match(m[1],/OFF03D6C2_PREFLIGHT=PASS_READ_ONLY/);
  assert.match(m[1],/OFF03D6C2_MIGRATIONS=NOT_STARTED/);
  assert.match(src,/export PATH=\/usr\/sbin:\/usr\/bin:\/sbin:\/bin/);
});
