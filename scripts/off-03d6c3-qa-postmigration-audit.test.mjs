import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';

const filename = new URL('./off-03d6c3-qa-postmigration-audit.sh',import.meta.url).pathname;
const src=readFileSync(filename,'utf8');
const run=args=>spawnSync('bash',[filename,...args],{
  encoding:'utf8', timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test('only an audit mode is supported; no DDL or restore mode',()=>{
  const help=run(['--help']);
  assert.equal(help.status,0);
  assert.match(help.stdout,/audit/);
  for(const mode of ['apply','inspect','migrate','restore','backup','install','rollback','deploy','reset']){
    const result=run([mode]);
    assert.equal(result.status,1,mode);
    assert.match(result.stderr,/solo audit/);
  }
  assert.equal(run([]).status,2);
});
test('does not rerun pre-DDL gates after legitimate schema changes',()=>{
  assert.doesNotMatch(src,/(?:bash|sudo bash) "\$(?:C1|B2|D5)"/);
  assert.doesNotMatch(src,/OFF03D6B2_SOURCE_QA_UNCHANGED/);
  assert.match(src,/PRE-DDL recovery point/);
  assert.match(src,/RESTORE_VERIFIED/);
  assert.match(src,/sha256sum','-c','SHA256SUMS'/);
});
test('fixed QA container, network, volume, local port and pilot status checks',()=>{
  for(const phrase of [
    'vinto-mvp-frontend','vinto-mvp-backend','vinto-web',
    'vinto-mvp-postgres','postgres-vinto',
    'vinto-qa-postgres','vinto-qa-internal','127.0.0.1:6554',
    'vinto-qa-offline-pgdata','vinto_qa_offline',
    '7b9eb8c82a290d06e719ee4990c2020076bbd11b'
  ]) assert.ok(src.includes(phrase),phrase);
});
test('migration checksums compared against all 31 exact SQL files and DB history',()=>{
  assert.match(src,/len\(sql_files\)!=31/);
  assert.match(src,/migration_blob_drift/);
  assert.match(src,/hashlib\.sha256\(sql\.encode\('utf-8'\)\)\.hexdigest/);
  assert.match(src,/history_version_filename_or_checksum_drift/);
  assert.match(src,/OFF03D6C3_MIGRATION_CHECKSUMS=PASS/);
  assert.match(src,/to_regclass|vinto_meta\.schema_migration/);
});
test('post-DDL role and ACL checks are read only, without identity cut',()=>{
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/has_database_privilege\('public',current_database\(\),'CONNECT'\)/);
  assert.match(src,/has_schema_privilege\('vinto_app','vinto_meta','USAGE'\)/);
  assert.match(src,/has_table_privilege\('vinto_app','vinto_master\.user','INSERT'\)/);
  assert.match(src,/vinto_identity','vinto_test_admin/);
  assert.match(src,/OFF03D6C3_NO_IDENTITY_CUT=PASS/);
  assert.match(src,/OFF03D6C3_AUDIT=PASS_READ_ONLY/);
  assert.match(src,/NO_DATABASE_WRITES=PASS/);
  assert.doesNotMatch(src,/migrate\.py|pg_restore|pg_dump|docker (?:run|stop|rm|restart|volume|network)|\bCREATE TABLE\b|\bDROP TABLE\b/);
});
test('embedded Python parses, and command environment strips external PG configuration',()=>{
  const m=src.match(/<<'PY'\n([\s\S]*?)\nPY\n/);
  assert.ok(m);
  const parsed=spawnSync('python3',['-c','import ast,sys; ast.parse(sys.stdin.read())'],{
    input:m[1],encoding:'utf8'
  });
  assert.equal(parsed.status,0,parsed.stderr);
  assert.match(m[1],/env=CLEAN/);
  assert.match(src,/export PATH=\/usr\/sbin:\/usr\/bin:\/sbin:\/bin/);
});
