import { parseTubetesReport, type TubetesReport, type MachineTubetes } from "./tubetes-report.ts";

const PAGE_WIDTH = 595.28;
const PAGE_HEIGHT = 841.89;
const LEFT = 28;
const RIGHT = 28;
const TABLE_WIDTH = PAGE_WIDTH - LEFT - RIGHT;
const CODE_WIDTH = 72;
const DATE_WIDTH = (TABLE_WIDTH - CODE_WIDTH) / 10;
const TABLE_TOP = 82;
const HEADER_HEIGHT = 22;
const BODY_TOP = TABLE_TOP + HEADER_HEIGHT;
const ROW_HEIGHT = 20;
const FOOTER_LINE = 812;
const ROWS_PER_PAGE = 34;
const DATE_COLUMNS = 10;

export type TubetesPdfRow = {
    code: string;
    continuation: boolean;
    dates: string[];
};

export type TubetesPdfPage = {
    machine: "MP1" | "MP3";
    rows: TubetesPdfRow[];
    pageNumber: number;
    totalPages: number;
};

function requireValidReport(value: unknown): TubetesReport {
    const report = parseTubetesReport(value);
    if (!report) throw new Error("Los datos del reporte de tubetes no cumplen el contrato esperado.");
    return report;
}

function rowsForMachine(machine: MachineTubetes): TubetesPdfRow[] {
    const rows: TubetesPdfRow[] = [];
    for (const tubete of machine.tubetes) {
        for (let offset = 0; offset < tubete.dates.length; offset += DATE_COLUMNS) {
            rows.push({
                code: tubete.code,
                continuation: offset > 0,
                dates: tubete.dates.slice(offset, offset + DATE_COLUMNS),
            });
        }
    }
    return rows;
}

export function paginateTubetesReport(value: unknown): TubetesPdfPage[] {
    const report = requireValidReport(value);
    const pending: Array<Omit<TubetesPdfPage, "pageNumber" | "totalPages">> = [];

    for (const machine of report.machines) {
        const rows = rowsForMachine(machine);
        if (rows.length === 0) {
            pending.push({ machine: machine.machine, rows: [] });
            continue;
        }
        for (let offset = 0; offset < rows.length; offset += ROWS_PER_PAGE) {
            pending.push({
                machine: machine.machine,
                rows: rows.slice(offset, offset + ROWS_PER_PAGE),
            });
        }
    }

    return pending.map((page, index) => ({
        ...page,
        pageNumber: index + 1,
        totalPages: pending.length,
    }));
}

function n(value: number): string {
    return Number(value.toFixed(3)).toString();
}

function pdfString(value: string): string {
    if (/[^\x20-\x7E]/.test(value)) throw new Error("El PDF contiene texto no compatible con la fuente estándar.");
    return value.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function textCommand(value: string, x: number, top: number, size: number, font = "F1", align: "left" | "center" | "right" = "left"): string {
    const safe = pdfString(value);
    const estimatedWidth = value.length * size * 0.52;
    const textX = align === "center" ? x - estimatedWidth / 2 : align === "right" ? x - estimatedWidth : x;
    const y = PAGE_HEIGHT - top;
    return "BT /" + font + " " + n(size) + " Tf 1 0 0 1 " + n(textX) + " " + n(y) + " Tm (" + safe + ") Tj ET\n";
}

function lineCommand(x1: number, top1: number, x2: number, top2: number, width = 0.4): string {
    return n(width) + " w " + n(x1) + " " + n(PAGE_HEIGHT - top1) + " m " + n(x2) + " " + n(PAGE_HEIGHT - top2) + " l S\n";
}

function rectCommand(x: number, top: number, width: number, height: number): string {
    return n(x) + " " + n(PAGE_HEIGHT - top - height) + " " + n(width) + " " + n(height) + " re S\n";
}

function displayDate(value: string): string {
    const [year, month, day] = value.split("-");
    return day + "/" + month + "/" + year.slice(-2);
}

function drawPage(page: TubetesPdfPage): string {
    let content = "0 G 0 g\n";
    content += textCommand("PAPELERA VINTO | PROYECTO SINERGIA", LEFT, 25, 7, "F2");
    content += textCommand("REGISTRO DE TUBETES UTILIZADOS EN " + page.machine, LEFT, 47, 13, "F2");
    content += textCommand("CODIGO + FECHA 1 A FECHA 10 | FECHA OPERATIVA: AMERICA/LA_PAZ", LEFT, 62, 7, "F1");
    content += lineCommand(LEFT, 70, PAGE_WIDTH - RIGHT, 70, 0.7);

    const headers = ["CODIGO", ...Array.from({ length: DATE_COLUMNS }, (_, index) => "FECHA " + (index + 1))];
    const xPositions = [LEFT, LEFT + CODE_WIDTH];
    for (let index = 1; index <= DATE_COLUMNS; index++) {
        xPositions.push(LEFT + CODE_WIDTH + DATE_WIDTH * index);
    }

    content += rectCommand(LEFT, TABLE_TOP, TABLE_WIDTH, HEADER_HEIGHT);
    for (const x of xPositions.slice(1, -1)) {
        content += lineCommand(x, TABLE_TOP, x, TABLE_TOP + HEADER_HEIGHT);
    }
    content += textCommand(headers[0], LEFT + 4, TABLE_TOP + 14, 6.5, "F2");
    for (let index = 1; index < headers.length; index++) {
        const center = LEFT + CODE_WIDTH + DATE_WIDTH * (index - 0.5);
        content += textCommand(headers[index], center, TABLE_TOP + 14, 6.1, "F2", "center");
    }

    if (page.rows.length === 0) {
        content += rectCommand(LEFT, BODY_TOP, TABLE_WIDTH, ROW_HEIGHT);
        content += textCommand("SIN UTILIZACIONES REGISTRADAS", LEFT + TABLE_WIDTH / 2, BODY_TOP + 13, 7, "F1", "center");
    } else {
        page.rows.forEach((row, rowIndex) => {
            const top = BODY_TOP + rowIndex * ROW_HEIGHT;
            content += rectCommand(LEFT, top, TABLE_WIDTH, ROW_HEIGHT);
            for (const x of xPositions.slice(1, -1)) {
                content += lineCommand(x, top, x, top + ROW_HEIGHT);
            }
            const codeLabel = row.continuation ? row.code + " (cont.)" : row.code;
            const codeFontSize = Math.max(4.5, Math.min(6.5, (CODE_WIDTH - 8) / (codeLabel.length * 0.52)));
            content += textCommand(codeLabel, LEFT + 4, top + 13, codeFontSize, row.continuation ? "F1" : "F2");
            row.dates.forEach((date, index) => {
                const center = LEFT + CODE_WIDTH + DATE_WIDTH * (index + 0.5);
                content += textCommand(displayDate(date), center, top + 13, 6.3, "F1", "center");
            });
        });
    }

    content += lineCommand(LEFT, FOOTER_LINE, PAGE_WIDTH - RIGHT, FOOTER_LINE, 0.5);
    content += textCommand("REPORTE DE TUBETES UTILIZADOS", LEFT, 827, 6.5, "F1");
    content += textCommand("PAGINA " + page.pageNumber + " DE " + page.totalPages, PAGE_WIDTH - RIGHT, 827, 6.5, "F1", "right");
    return content;
}

function buildPdfDocument(pages: TubetesPdfPage[]): string {
    const objects = new Map<number, string>();
    const pageIds = pages.map((_, index) => 5 + index * 2);
    objects.set(1, "<< /Type /Catalog /Pages 2 0 R >>");
    objects.set(2, "<< /Type /Pages /Kids [" + pageIds.map(id => id + " 0 R").join(" ") + "] /Count " + pages.length + " >>");
    objects.set(3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
    objects.set(4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");

    pages.forEach((page, index) => {
        const pageId = 5 + index * 2;
        const contentId = pageId + 1;
        const stream = drawPage(page);
        objects.set(pageId, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + PAGE_WIDTH + " " + PAGE_HEIGHT + "] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents " + contentId + " 0 R >>");
        objects.set(contentId, "<< /Length " + stream.length + " >>\nstream\n" + stream + "endstream");
    });

    const maxObject = 4 + pages.length * 2;
    let pdf = "%PDF-1.4\n";
    const offsets = [0];
    for (let id = 1; id <= maxObject; id++) {
        const object = objects.get(id);
        if (!object) throw new Error("Falta un objeto interno del PDF.");
        offsets[id] = pdf.length;
        pdf += id + " 0 obj\n" + object + "\nendobj\n";
    }

    const xrefOffset = pdf.length;
    pdf += "xref\n0 " + (maxObject + 1) + "\n";
    pdf += "0000000000 65535 f \n";
    for (let id = 1; id <= maxObject; id++) {
        pdf += String(offsets[id]).padStart(10, "0") + " 00000 n \n";
    }
    pdf += "trailer\n<< /Size " + (maxObject + 1) + " /Root 1 0 R >>\nstartxref\n" + xrefOffset + "\n%%EOF\n";
    return pdf;
}

export function buildTubetesPdf(value: unknown): string {
    return buildPdfDocument(paginateTubetesReport(value));
}

export function tubetesPdfFilename(value: unknown): string {
    const report = requireValidReport(value);
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/La_Paz",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(new Date(report.generated_at));
    const part = (type: string) => parts.find(item => item.type === type)?.value ?? "0000";
    return "tubetes-utilizados-" + part("year") + "-" + part("month") + "-" + part("day") + ".pdf";
}

export function downloadTubetesPdf(value: unknown): void {
    const pdf = buildTubetesPdf(value);
    const blob = new Blob([pdf], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = tubetesPdfFilename(value);
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function openTubetesPdfForPrint(value: unknown): void {
    const pdf = buildTubetesPdf(value);
    const blob = new Blob([pdf], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const printWindow = window.open(url, "_blank");
    if (!printWindow) {
        URL.revokeObjectURL(url);
        throw new Error("El navegador bloqueó la apertura del PDF para imprimir.");
    }
    printWindow.opener = null;
    printWindow.focus();
    // El visor PDF de la nueva pestaña ofrece la acción nativa de impresión.
    window.setTimeout(() => URL.revokeObjectURL(url), 300_000);
}
