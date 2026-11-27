// node --test scripts/tubetes-report.test.mjs
// Contrato frontend puro de GET /api/reports/tubetes-used: sin red ni DOM.
import assert from "node:assert/strict";
import test from "node:test";
import { parseTubetesReport } from "../lib/vinto/tubetes-report.ts";

const payload = () => ({
  generated_at: "2026-11-27T15:00:00Z",
  source_form: "VINTO-P1-03",
  date_basis: "operating_date",
  timezone: "America/La_Paz",
  machines: [
    { machine: "MP1", usage_total: 3, records_without_code: 1, tubetes: [
      { code: "2", usage_count: 2, dates: ["2026-11-02", "2026-11-02"] },
      { code: "10", usage_count: 1, dates: ["2026-11-05"] },
    ] },
    { machine: "MP3", usage_total: 1, records_without_code: 0, tubetes: [
      { code: "7", usage_count: 1, dates: ["2026-11-13"] },
    ] },
  ],
});

test("accepts both machines and preserves repeated same-day dates", () => {
  const parsed = parseTubetesReport(payload());
  assert.ok(parsed);
  assert.deepEqual(parsed.machines.map(machine => machine.machine), ["MP1", "MP3"]);
  assert.deepEqual(parsed.machines[0].tubetes[0].dates, ["2026-11-02", "2026-11-02"]);
  assert.equal(parsed.machines[0].tubetes[0].usage_count, 2);
  assert.equal(parsed.machines[0].records_without_code, 1);
});

test("accepts an empty machine but requires both machine slots", () => {
  const value = payload();
  value.machines[0] = { machine: "MP1", usage_total: 0, records_without_code: 0, tubetes: [] };
  assert.ok(parseTubetesReport(value));
  value.machines = [value.machines[0]];
  assert.equal(parseTubetesReport(value), null);
});

test("rejects an incorrect source, date basis, timezone or machine order", () => {
  for (const change of [
    value => { value.source_form = "VINTO-P1-05"; },
    value => { value.date_basis = "captured_at"; },
    value => { value.timezone = "UTC"; },
    value => { [value.machines[0], value.machines[1]] = [value.machines[1], value.machines[0]]; },
  ]) {
    const value = payload();
    change(value);
    assert.equal(parseTubetesReport(value), null);
  }
});

test("rejects inconsistent counts, duplicate codes and non-numeric order", () => {
  const cases = [
    value => { value.machines[0].usage_total = 2; },
    value => { value.machines[0].tubetes[0].usage_count = 1; },
    value => { value.machines[0].tubetes[1].code = "2"; },
    value => { value.machines[0].tubetes.reverse(); },
    value => { value.machines[0].tubetes[0].code = "02"; },
  ];
  for (const change of cases) {
    const value = payload();
    change(value);
    assert.equal(parseTubetesReport(value), null);
  }
});

test("rejects invalid calendar dates and descending dates", () => {
  for (const date of ["2026-02-30", "2026-1-02", "not-a-date"]) {
    const value = payload();
    value.machines[0].tubetes[0].dates[0] = date;
    assert.equal(parseTubetesReport(value), null);
  }
  const descending = payload();
  descending.machines[0].tubetes[0].dates = ["2026-11-03", "2026-11-02"];
  assert.equal(parseTubetesReport(descending), null);
});

test("requires an explicit offset on generated_at", () => {
  const value = payload();
  value.generated_at = "2026-11-27T15:00:00";
  assert.equal(parseTubetesReport(value), null);
});
