import assert from "node:assert/strict";
import test from "node:test";
import { writeFileSync } from "node:fs";
import {
  buildTubetesWorkbook,
  tubetesExcelFilename,
} from "../lib/vinto/tubetes-excel.ts";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function base() {
  return {
    generated_at: "2026-11-27T15:00:00Z",
    source_form: "VINTO-P1-03",
    date_basis: "operating_date",
    timezone: "America/La_Paz",
    machines: [
      { machine: "MP1", usage_total: 0, records_without_code: 0, tubetes: [] },
      { machine: "MP3", usage_total: 3, records_without_code: 2, tubetes: [
        { code: "1", usage_count: 1, dates: ["2026-11-13"] },
        { code: "50", usage_count: 1, dates: ["2026-11-16"] },
        { code: "70", usage_count: 1, dates: ["2026-11-16"] },
      ] },
    ],
  };
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc & 1) ? (0xedb88320 ^ (crc >>> 1)) : (crc >>> 1);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function readStoredZip(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const files = new Map();
  let offset = 0;
  while (offset + 4 <= bytes.length && view.getUint32(offset, true) === 0x04034b50) {
    const flags = view.getUint16(offset + 6, true);
    const method = view.getUint16(offset + 8, true);
    const checksum = view.getUint32(offset + 14, true);
    const compressedSize = view.getUint32(offset + 18, true);
    const uncompressedSize = view.getUint32(offset + 22, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);
    assert.equal(method, 0, "ZIP entry must use store method");
    assert.ok(flags & 0x0800, "ZIP entry must declare UTF-8 names");
    assert.equal(compressedSize, uncompressedSize);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const name = decoder.decode(bytes.slice(nameStart, nameStart + nameLength));
    const data = bytes.slice(dataStart, dataStart + compressedSize);
    assert.equal(crc32(data), checksum, "CRC32 " + name);
    files.set(name, decoder.decode(data));
    offset = dataStart + compressedSize;
  }
  assert.equal(view.getUint32(offset, true), 0x02014b50, "central directory signature");
  const endOffset = bytes.length - 22;
  assert.equal(view.getUint32(endOffset, true), 0x06054b50, "end of central directory signature");
  assert.equal(view.getUint16(endOffset + 10, true), files.size);
  return files;
}

test("workbook is a valid ZIP package with two named machine sheets", () => {
  const bytes = buildTubetesWorkbook(base());
  writeFileSync("/tmp/vinto-tubetes-excel-ci.xlsx", bytes);
  assert.ok(bytes instanceof Uint8Array);
  assert.equal(new DataView(bytes.buffer, bytes.byteOffset).getUint32(0, true), 0x04034b50);
  const files = readStoredZip(bytes);
  for (const path of [
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/styles.xml",
    "xl/worksheets/sheet1.xml",
    "xl/worksheets/sheet2.xml",
  ]) assert.ok(files.has(path), path);
  assert.match(files.get("xl/workbook.xml"), /sheet name="MP1"/);
  assert.match(files.get("xl/workbook.xml"), /sheet name="MP3"/);
  assert.match(files.get("[Content_Types].xml"), /spreadsheetml\.sheet\.main\+xml/);
});

test("MP1 and MP3 have separate worksheets and one row per tubete code", () => {
  const files = readStoredZip(buildTubetesWorkbook(base()));
  const mp1 = files.get("xl/worksheets/sheet1.xml");
  const mp3 = files.get("xl/worksheets/sheet2.xml");
  assert.match(mp1, /<dimension ref="A1"\/>/);
  assert.match(mp1, /Código/);
  assert.doesNotMatch(mp1, /<row r="2">/);
  assert.match(mp3, /<dimension ref="A1:B4"\/>/);
  assert.match(mp3, /<t xml:space="preserve">1<\/t>/);
  assert.match(mp3, /<t xml:space="preserve">50<\/t>/);
  assert.match(mp3, /<t xml:space="preserve">70<\/t>/);
  assert.match(mp3, /autoFilter ref="A1:B4"/);
});

test("Excel keeps codes as text and dates as real date cells with DD/MM/YY format", () => {
  const files = readStoredZip(buildTubetesWorkbook(base()));
  const mp3 = files.get("xl/worksheets/sheet2.xml");
  const styles = files.get("xl/styles.xml");
  assert.match(mp3, /<c r="A2" s="3" t="inlineStr"><is><t xml:space="preserve">1<\/t>/);
  assert.match(mp3, /<c r="B2" s="1"><v>\d+<\/v><\/c>/);
  assert.match(styles, /formatCode="dd\/mm\/yy"/);
});

test("more than ten uses expand dynamically without truncation and same-day duplicates stay in separate columns", () => {
  const report = base();
  const dates = Array.from({ length: 23 }, () => "2026-11-27");
  report.machines[0] = {
    machine: "MP1",
    usage_total: 23,
    records_without_code: 0,
    tubetes: [{ code: "9001", usage_count: 23, dates }],
  };
  const files = readStoredZip(buildTubetesWorkbook(report));
  const mp1 = files.get("xl/worksheets/sheet1.xml");
  assert.match(mp1, /<dimension ref="A1:X2"\/>/);
  assert.match(mp1, /<t xml:space="preserve">Fecha 23<\/t>/);
  assert.match(mp1, /autoFilter ref="A1:X2"/);
  assert.match(mp1, /<c r="A2" s="3" t="inlineStr"><is><t xml:space="preserve">9001<\/t>/);
  const dateCells = mp1.match(/<c r="[B-X]2" s="1"><v>\d+<\/v><\/c>/g) ?? [];
  assert.equal(dateCells.length, 23);
  const serials = dateCells.map(cell => cell.match(/<v>(\d+)<\/v>/)?.[1]);
  assert.equal(new Set(serials).size, 1, "all 23 dates have the same date value but remain separate cells");
});

test("dynamic columns use the maximum uses for any code on that machine", () => {
  const report = base();
  report.machines[1] = {
    machine: "MP3",
    usage_total: 4,
    records_without_code: 0,
    tubetes: [
      { code: "1", usage_count: 1, dates: ["2026-11-13"] },
      { code: "50", usage_count: 3, dates: ["2026-11-14", "2026-11-15", "2026-11-16"] },
    ],
  };
  const files = readStoredZip(buildTubetesWorkbook(report));
  const mp3 = files.get("xl/worksheets/sheet2.xml");
  assert.match(mp3, /<dimension ref="A1:D3"\/>/);
  assert.match(mp3, /<t xml:space="preserve">Fecha 3<\/t>/);
  assert.doesNotMatch(mp3, /Fecha 4/);
});

test("each sheet freezes its header row and uses an autofilter when it has records", () => {
  const files = readStoredZip(buildTubetesWorkbook(base()));
  const mp1 = files.get("xl/worksheets/sheet1.xml");
  const mp3 = files.get("xl/worksheets/sheet2.xml");
  assert.match(mp1, /state="frozen"/);
  assert.match(mp3, /state="frozen"/);
  assert.doesNotMatch(mp1, /autoFilter/);
  assert.match(mp3, /autoFilter/);
});

test("filename uses the plant operating timezone", () => {
  assert.equal(tubetesExcelFilename(base()), "tubetes-utilizados-2026-11-27.xlsx");
});

test("invalid report data is rejected before workbook generation", () => {
  const invalid = base();
  invalid.machines[1].usage_total = 99;
  assert.throws(() => buildTubetesWorkbook(invalid));
});
