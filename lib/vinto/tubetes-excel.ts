import { parseTubetesReport, type MachineTubetes, type TubetesReport } from "./tubetes-report.ts";

const encoder = new TextEncoder();
const MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const DAY_MS = 86_400_000;
const EXCEL_EPOCH_OFFSET = 25_569;

type ZipEntry = { name: string; data: Uint8Array };

function requireReport(value: unknown): TubetesReport {
    const report = parseTubetesReport(value);
    if (!report) throw new Error("Los datos del reporte de tubetes no cumplen el contrato esperado.");
    return report;
}

function xmlEscape(value: string): string {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function excelSerial(isoDate: string): number {
    const [year, month, day] = isoDate.split("-").map(Number);
    return Math.round(Date.UTC(year, month - 1, day) / DAY_MS) + EXCEL_EPOCH_OFFSET;
}

function columnName(index: number): string {
    let value = index;
    let name = "";
    while (value > 0) {
        const remainder = (value - 1) % 26;
        name = String.fromCharCode(65 + remainder) + name;
        value = Math.floor((value - 1) / 26);
    }
    return name;
}

function inlineStringCell(reference: string, value: string, style: number): string {
    return '<c r="' + reference + '" s="' + style + '" t="inlineStr"><is><t xml:space="preserve">'
        + xmlEscape(value) + "</t></is></c>";
}

function numberCell(reference: string, value: number, style: number): string {
    return '<c r="' + reference + '" s="' + style + '"><v>' + value + "</v></c>";
}

function machineWorksheet(machine: MachineTubetes): string {
    const maxDates = machine.tubetes.reduce((max, item) => Math.max(max, item.dates.length), 0);
    const headers = ["Código", ...Array.from({ length: maxDates }, (_, index) => "Fecha " + (index + 1))];
    const lastColumn = columnName(headers.length);
    const lastRow = machine.tubetes.length + 1;
    const rows: string[] = [];

    rows.push('<row r="1">' + headers.map((header, index) =>
        inlineStringCell(columnName(index + 1) + "1", header, 2),
    ).join("") + "</row>");

    machine.tubetes.forEach((tubete, index) => {
        const rowNumber = index + 2;
        const cells = [inlineStringCell("A" + rowNumber, tubete.code, 3)];
        tubete.dates.forEach((date, dateIndex) => {
            cells.push(numberCell(columnName(dateIndex + 2) + rowNumber, excelSerial(date), 1));
        });
        rows.push('<row r="' + rowNumber + '">' + cells.join("") + "</row>");
    });

    const columnDefinitions = ['<col min="1" max="1" width="18" customWidth="1"/>'];
    if (maxDates > 0) {
        columnDefinitions.push('<col min="2" max="' + (maxDates + 1) + '" width="14" customWidth="1"/>');
    }
    const autoFilter = machine.tubetes.length > 0
        ? '<autoFilter ref="A1:' + lastColumn + lastRow + '"/>'
        : "";

    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        + '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>'
        + '<sheetFormatPr defaultRowHeight="19"/>'
        + '<cols>' + columnDefinitions.join("") + "</cols>"
        + '<sheetData>' + rows.join("") + "</sheetData>"
        + autoFilter
        + '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        + '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        + "</worksheet>";
}

function stylesXml(): string {
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yy"/></numFmts>'
        + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        + '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        + '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
        + '<border><left style="thin"><color auto="1"/></left><right style="thin"><color auto="1"/></right>'
        + '<top style="thin"><color auto="1"/></top><bottom style="thin"><color auto="1"/></bottom><diagonal/></border></borders>'
        + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        + '<cellXfs count="4">'
        + '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        + '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>'
        + '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1"><alignment horizontal="center" vertical="center"/></xf>'
        + '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment horizontal="left" vertical="center"/></xf>'
        + '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        + "</styleSheet>";
}

function workbookEntries(report: TubetesReport): ZipEntry[] {
    const contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        + '<Default Extension="xml" ContentType="application/xml"/>'
        + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        + '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        + "</Types>";
    const rootRelationships = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        + "</Relationships>";
    const workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        + '<sheets><sheet name="MP1" sheetId="1" r:id="rId1"/><sheet name="MP3" sheetId="2" r:id="rId2"/></sheets>'
        + "</workbook>";
    const workbookRelationships = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        + '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        + "</Relationships>";

    return [
        { name: "[Content_Types].xml", data: encoder.encode(contentTypes) },
        { name: "_rels/.rels", data: encoder.encode(rootRelationships) },
        { name: "xl/workbook.xml", data: encoder.encode(workbook) },
        { name: "xl/_rels/workbook.xml.rels", data: encoder.encode(workbookRelationships) },
        { name: "xl/styles.xml", data: encoder.encode(stylesXml()) },
        { name: "xl/worksheets/sheet1.xml", data: encoder.encode(machineWorksheet(report.machines[0])) },
        { name: "xl/worksheets/sheet2.xml", data: encoder.encode(machineWorksheet(report.machines[1])) },
    ];
}

const CRC_TABLE = new Uint32Array(256);
for (let index = 0; index < 256; index++) {
    let value = index;
    for (let bit = 0; bit < 8; bit++) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    CRC_TABLE[index] = value >>> 0;
}

function crc32(bytes: Uint8Array): number {
    let crc = 0xffffffff;
    for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
}

function concat(parts: Uint8Array[]): Uint8Array {
    const length = parts.reduce((total, part) => total + part.length, 0);
    const result = new Uint8Array(length);
    let offset = 0;
    for (const part of parts) {
        result.set(part, offset);
        offset += part.length;
    }
    return result;
}

function zipStored(entries: ZipEntry[]): Uint8Array {
    const localParts: Uint8Array[] = [];
    const centralParts: Uint8Array[] = [];
    let localOffset = 0;

    for (const entry of entries) {
        const name = encoder.encode(entry.name);
        const checksum = crc32(entry.data);
        const localHeader = new Uint8Array(30 + name.length);
        const localView = new DataView(localHeader.buffer);
        localView.setUint32(0, 0x04034b50, true);
        localView.setUint16(4, 20, true);
        localView.setUint16(6, 0x0800, true);
        localView.setUint16(8, 0, true);
        localView.setUint16(10, 0, true);
        localView.setUint16(12, 33, true);
        localView.setUint32(14, checksum, true);
        localView.setUint32(18, entry.data.length, true);
        localView.setUint32(22, entry.data.length, true);
        localView.setUint16(26, name.length, true);
        localView.setUint16(28, 0, true);
        localHeader.set(name, 30);
        localParts.push(localHeader, entry.data);

        const centralHeader = new Uint8Array(46 + name.length);
        const centralView = new DataView(centralHeader.buffer);
        centralView.setUint32(0, 0x02014b50, true);
        centralView.setUint16(4, 20, true);
        centralView.setUint16(6, 20, true);
        centralView.setUint16(8, 0x0800, true);
        centralView.setUint16(10, 0, true);
        centralView.setUint16(12, 0, true);
        centralView.setUint16(14, 33, true);
        centralView.setUint32(16, checksum, true);
        centralView.setUint32(20, entry.data.length, true);
        centralView.setUint32(24, entry.data.length, true);
        centralView.setUint16(28, name.length, true);
        centralView.setUint16(30, 0, true);
        centralView.setUint16(32, 0, true);
        centralView.setUint16(34, 0, true);
        centralView.setUint16(36, 0, true);
        centralView.setUint32(38, 0, true);
        centralView.setUint32(42, localOffset, true);
        centralHeader.set(name, 46);
        centralParts.push(centralHeader);

        localOffset += localHeader.length + entry.data.length;
    }

    const centralDirectory = concat(centralParts);
    const localFileData = concat(localParts);
    const end = new Uint8Array(22);
    const endView = new DataView(end.buffer);
    endView.setUint32(0, 0x06054b50, true);
    endView.setUint16(4, 0, true);
    endView.setUint16(6, 0, true);
    endView.setUint16(8, entries.length, true);
    endView.setUint16(10, entries.length, true);
    endView.setUint32(12, centralDirectory.length, true);
    endView.setUint32(16, localFileData.length, true);
    endView.setUint16(20, 0, true);
    return concat([localFileData, centralDirectory, end]);
}

export function buildTubetesWorkbook(value: unknown): Uint8Array {
    return zipStored(workbookEntries(requireReport(value)));
}

export function tubetesExcelFilename(value: unknown): string {
    const report = requireReport(value);
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/La_Paz",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(new Date(report.generated_at));
    const part = (type: string) => parts.find(item => item.type === type)?.value ?? "0000";
    return "tubetes-utilizados-" + part("year") + "-" + part("month") + "-" + part("day") + ".xlsx";
}

export function downloadTubetesExcel(value: unknown): void {
    const bytes = buildTubetesWorkbook(value);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    const blob = new Blob([buffer], { type: MIME_XLSX });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = tubetesExcelFilename(value);
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
