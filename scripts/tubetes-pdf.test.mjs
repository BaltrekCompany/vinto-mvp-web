import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTubetesPdf,
  paginateTubetesReport,
  tubetesPdfFilename,
} from "../lib/vinto/tubetes-pdf.ts";

const base = () => ({
  generated_at: "2026-11-27T15:00:00Z",
  source_form: "VINTO-P1-03",
  date_basis: "operating_date",
  timezone: "America/La_Paz",
  machines: [
    { machine: "MP1", usage_total: 0, records_without_code: 0, tubetes: [] },
    { machine: "MP3", usage_total: 0, records_without_code: 0, tubetes: [] },
  ],
});

function addUses(report, machine, code, dates) {
  const target = report.machines.find(item => item.machine === machine);
  target.tubetes.push({ code: String(code), usage_count: dates.length, dates });
  target.usage_total += dates.length;
  target.tubetes.sort((a, b) => Number(a.code) - Number(b.code));
}

const date = index => "2026-11-" + String((index % 27) + 1).padStart(2, "0");

test("ten utilizations stay in one row with ten date columns", () => {
  const report = base();
  addUses(report, "MP1", 7, Array.from({ length: 10 }, (_, index) => date(index)));
  const pages = paginateTubetesReport(report);
  const rows = pages.filter(page => page.machine === "MP1").flatMap(page => page.rows);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].continuation, false);
  assert.equal(rows[0].dates.length, 10);
});

test("eleven utilizations create one continuation row with one remaining date", () => {
  const report = base();
  addUses(report, "MP3", 12, Array.from({ length: 11 }, (_, index) => date(index)));
  const pages = paginateTubetesReport(report);
  const rows = pages.filter(page => page.machine === "MP3").flatMap(page => page.rows);
  assert.deepEqual(rows.map(row => [row.code, row.continuation, row.dates.length]), [
    ["12", false, 10],
    ["12", true, 1],
  ]);
});

test("twenty-three utilizations split into 10, 10 and 3 without losing same-day duplicates", () => {
  const report = base();
  const dates = Array.from({ length: 23 }, () => "2026-11-27");
  addUses(report, "MP1", 47, dates);
  const pages = paginateTubetesReport(report);
  const rows = pages.filter(page => page.machine === "MP1").flatMap(page => page.rows);
  assert.deepEqual(rows.map(row => [row.code, row.continuation, row.dates.length]), [
    ["47", false, 10],
    ["47", true, 10],
    ["47", true, 3],
  ]);
  assert.equal(rows.flatMap(row => row.dates).length, 23);
  assert.equal(new Set(rows.flatMap(row => row.dates)).size, 1);
});

test("each machine has its own titled section and pagination continues automatically", () => {
  const report = base();
  for (let code = 1; code <= 35; code++) addUses(report, "MP1", code, [date(code)]);
  addUses(report, "MP3", 90, ["2026-11-27"]);
  const pages = paginateTubetesReport(report);
  assert.deepEqual(pages.map(page => [page.machine, page.rows.length]), [
    ["MP1", 34],
    ["MP1", 1],
    ["MP3", 1],
  ]);
  assert.deepEqual(pages.map(page => [page.pageNumber, page.totalPages]), [[1, 3], [2, 3], [3, 3]]);
});

test("empty machines still produce a page with the expected table section", () => {
  const pages = paginateTubetesReport(base());
  assert.deepEqual(pages.map(page => [page.machine, page.rows.length]), [["MP1", 0], ["MP3", 0]]);
  const pdf = buildTubetesPdf(base());
  assert.equal((pdf.match(/SIN UTILIZACIONES REGISTRADAS/g) ?? []).length, 2);
});

test("PDF is a valid indexed PDF 1.4 document with A4 portrait pages and continuation labels", () => {
  const report = base();
  addUses(report, "MP3", 1, Array.from({ length: 23 }, () => "2026-11-27"));
  const pdf = buildTubetesPdf(report);
  assert.ok(pdf.startsWith("%PDF-1.4\n"));
  assert.match(pdf, /\/MediaBox \[0 0 595\.28 841\.89\]/);
  assert.match(pdf, /\(REGISTRO DE TUBETES UTILIZADOS EN MP3\)/);
  assert.match(pdf, /\(FECHA 10\)/);
  assert.ok(pdf.includes("1 \\(cont.\\)"));
  assert.match(pdf, /\(PAGINA 1 DE 2\)/);
  const startXref = Number(pdf.match(/startxref\n(\d+)\n%%EOF/)?.[1]);
  assert.ok(Number.isInteger(startXref));
  assert.equal(pdf.slice(startXref, startXref + 4), "xref");
  const xref = pdf.slice(startXref).split("\n");
  const objectCount = Number(xref[1].split(" ")[1]);
  for (let id = 1; id < objectCount; id++) {
    const offset = Number(xref[id + 2].slice(0, 10));
    assert.ok(pdf.slice(offset).startsWith(id + " 0 obj\n"), "xref object " + id);
  }
});

test("filename uses the plant operating timezone", () => {
  assert.equal(tubetesPdfFilename(base()), "tubetes-utilizados-2026-11-27.pdf");
});

test("invalid or inconsistent report data is rejected before PDF generation", () => {
  const invalid = base();
  invalid.machines[0].usage_total = 1;
  assert.throws(() => buildTubetesPdf(invalid));
});
