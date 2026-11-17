import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const preflight = new URL('./off-03d5-qa-migration-preflight.sh', import.meta.url).pathname;
const ci = new URL('./off-03d5-migrations-ci-e2e.sh', import.meta.url).pathname;
const src = readFileSync(preflight,'utf8');
const ciSrc = readFileSync(ci,'utf8');
const run = (file,args,env={}) => spawnSync('bash',[file,...args],{
  encoding:'utf8',
  timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME,...env},
});
test('preflight help lists only inspect',()=>{
  const r=run(preflight,['--help']);
  assert.equal(r.status,0);
  assert.match(r.stdout,/inspect/);
});
test('preflight rejects migration/install modes',()=>{
  for(const mode of ['migrate','install','apply','rollback','drop']){
    const r=run(preflight,[mode]);
    assert.notEqual(r.status,0);
    assert.match(r.stderr,/operacion no soportada/);
  }
});
test('preflight requires one action',()=>{
  const r=run(preflight,[]);
  assert.equal(r.status,2);
});
test('CI e2e refuses execution outside GitHub Actions',()=>{
  const r=run(ci,[]);
  assert.equal(r.status,2);
  assert.match(r.stderr,/OFF03D5_CI_ONLY=BLOCKED/);
});
test('CI e2e covers real migration and 03b hardening in disposable cluster',()=>{
  assert.match(ciSrc,/postgres:17/);
  assert.match(ciSrc,/len\(migrations\) == 31/);
  assert.match(ciSrc,/migrate\.py --target dev/);
  assert.match(ciSrc,/migrate\.py --target dev --check/);
  assert.match(ciSrc,/03b_d3b1_restrict_catalog_writes\.sql/);
  assert.match(ciSrc,/07_verification_queries\.sql/);
  assert.match(ciSrc,/08_release_preflight\.sql/);
  assert.match(ciSrc,/OFF03D5_REAL_VPS_TOUCHED=NO/);
});
test('real VPS preflight checks QA-only metadata and cannot execute writes',()=>{
  assert.match(src,/vinto-qa-postgres/);
  assert.match(src,/vinto_qa_offline/);
  assert.match(src,/127\.0\.0\.1:6554/);
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/QA_MIGRATOR_AUTH=PASS/);
  assert.doesNotMatch(src,/docker (?:run|stop|restart|rm|volume rm|network create)/);
  assert.doesNotMatch(src,/(?:migrate\.py|--apply|psql.*-f)/);
});
