import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdtempSync,mkdirSync,symlinkSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

const file=new URL('./off-03d6c1-qa-migrator-preflight.sh',import.meta.url).pathname;
const src=readFileSync(file,'utf8');
const run=args=>spawnSync('bash',[file,...args],{
  encoding:'utf8',timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test('only inspect is accepted, no migrate/apply/backup modes',()=>{
  const help=run(['--help']);
  assert.equal(help.status,0);
  assert.match(help.stdout,/inspect/);
  for(const mode of ['migrate','apply','install','backup','restore','drop','prepare','deploy']){
    const p=run([mode]);
    assert.equal(p.status,1);
    assert.match(p.stderr,/solo inspect/);
  }
  assert.equal(run([]).status,2);
});
test('pre-DDL backup verify and fixed origin are mandatory',()=>{
  assert.match(src,/B2_BLOB=8d7193acfe59acc243bff47c65048705f2847c1d/);
  assert.match(src,/bash "\$B2" verify \|\| die/);
  assert.match(src,/PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b/);
  assert.match(src,/OFF03D6C1_BACKUP_RESTORE_GATE=PASS/);
  assert.match(src,/OFF03D6C1_CHECKOUT_MIGRATIONS_31=PASS/);
  assert.match(src,/git hash-object "\$SOURCE\/\$file"/);
  assert.match(src,/git -C "\$SOURCE" rev-parse "HEAD:\$file"/);
});
test('host identity from pinned QA venv, known port and role, secret not printed',()=>{
  assert.match(src,/QA_START="\$\(docker exec/);
  assert.match(src,/pg_postmaster_start_time/);
  assert.match(src,/host='127\.0\.0\.1', port=6554, dbname='vinto_qa_offline'/);
  assert.match(src,/user='vinto_migrator'/);
  assert.match(src,/password=secret/);
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/OFF03D6C1_HOST_TO_QA_DB_IDENTITY=PASS/);
  assert.doesNotMatch(src,/migrate\.py|pg_restore|pg_dump|docker (?:run|stop|rm|restart)|CREATE SCHEMA|DROP DATABASE/);
});
test('embedded Python body is syntactically valid',()=>{
  const match=src.match(/<<'PY'\n([\s\S]*?)\nPY\n/);
  assert.ok(match);
  const py=spawnSync('python3',['-c','import ast,sys; ast.parse(sys.stdin.read())'],{
    input:match[1],encoding:'utf8'
  });
  assert.equal(py.status,0,py.stderr);
});

test('venv executable symlink is valid; linked directory and absent interpreter fail',()=>{
  const guard = src.match(/\[ -d "\$VENV" \] && \[ ! -L "\$VENV" \] && \[ -x "\$PYTHON" \]/)?.[0];
  assert.ok(guard,'required venv guard missing');
  assert.doesNotMatch(src,/\[ ! -L "\$PYTHON" \]/);
  const temp=mkdtempSync(join(tmpdir(),'off03d6c1-'));
  try {
    const venv=join(temp,'venv');
    mkdirSync(join(venv,'bin'),{recursive:true});
    const python=join(venv,'bin','python');
    symlinkSync(process.execPath,python);
    const check=(v,p)=>spawnSync('bash',['-c',guard],{
      env:{PATH:process.env.PATH,HOME:process.env.HOME,VENV:v,PYTHON:p},encoding:'utf8'
    }).status;
    assert.equal(check(venv,python),0,'normal venv Python symlink must pass');
    const linked=join(temp,'venv-link');
    symlinkSync(venv,linked);
    assert.notEqual(check(linked,python),0,'linked venv root must fail');
    assert.notEqual(check(venv,join(venv,'bin','missing')),0,'missing Python must fail');
  } finally {
    rmSync(temp,{recursive:true,force:true});
  }
});
test('embedded venv identity Python parses and enforces sys.prefix isolation',()=>{
  const venv=src.match(/<<'PY_VENV'\n([\s\S]*?)\nPY_VENV\n/);
  assert.ok(venv);
  const p=spawnSync('python3',['-c','import ast,sys; ast.parse(sys.stdin.read())'],{
    input:venv[1],encoding:'utf8'
  });
  assert.equal(p.status,0,p.stderr);
  assert.match(venv[1],/sys\.prefix != sys\.base_prefix/);
  assert.match(venv[1],/Path\(sys\.prefix\)\.resolve/);
  assert.match(venv[1],/import psycopg/);
});
