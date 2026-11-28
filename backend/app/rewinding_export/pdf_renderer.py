"""Render the final RBE snapshot without reading any source data."""
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from zoneinfo import ZoneInfo

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import getFont, registerFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

MAX_PDF_BYTES = 25 * 1024 * 1024
TITLE = "Reporte de Bobinas Refiladas para Exportación"
FONT = "RBE-Vera"
BOLD = "RBE-Vera-Bold"
MARGIN = 22
BOTTOM = 32
WIDTH, HEIGHT = A4
COLUMNS = ("N.º", "Bobina madre", "Cría A", "Cría B", "Cría C", "Cría D", "Cría E",
           "Diámetro", "Cortes", "Tubete", "Ayudante", "Operador original")
WIDTHS = tuple((WIDTH - 2 * MARGIN) * percent / 100
               for percent in (6, 12, 7, 7, 7, 7, 7, 8, 6, 9, 10, 14))


class PDFTooLarge(ValueError):
    pass


class PDFLayoutError(ValueError):
    pass


class _LimitedBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_PDF_BYTES:
            raise PDFTooLarge("El PDF supera el límite técnico de 25 MiB")
        return super().write(data)


@lru_cache(maxsize=1)
def _register_fonts():
    registerFont(TTFont(FONT, "Vera.ttf"))
    registerFont(TTFont(BOLD, "VeraBd.ttf"))


def _lines(value, width, size, font):
    value = "" if value is None else str(value)
    cmap = getFont(font).face.charToGlyph
    if any(ord(char) not in cmap for char in value if char not in "\r\n\t"):
        raise PDFLayoutError("Un campo contiene caracteres que la fuente del PDF no admite")
    # Paragraph breaks and long unbroken source identifiers must survive wrapping.
    lines = []
    for paragraph in value.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"):
        current, measured = "", 0
        for word in paragraph.split(" "):
            segment = (" " if current else "") + word
            segment_width = getFont(font).stringWidth(segment, size)
            if current and measured + segment_width > width:
                lines.append(current)
                current, measured = "", 0
                segment = word
            for part in (segment,) if segment_width <= width else segment:
                part_width = getFont(font).stringWidth(part, size)
                if measured + part_width > width:
                    lines.append(current)
                    current, measured = "", 0
                current += part
                measured += part_width
        lines.append(current)
    return lines


def _row(values, widths, size=8, font=FONT, min_height=24):
    cells = [_lines(value, width - 6, size, font) for value, width in zip(values, widths, strict=True)]
    return cells, max(min_height, 6 + max(map(len, cells)) * (size + 2))


def _draw_row(canvas, top, row, widths, size=8, font=FONT):
    cells, height = row
    x = MARGIN
    canvas.setFont(font, size)
    for width, lines in zip(widths, cells, strict=True):
        canvas.rect(x, top - height, width, height)
        for index, line in enumerate(lines):
            canvas.drawString(x + 3, top - 3 - size - index * (size + 2), line)
        x += width
    return top - height


def _package_row(package):
    children = {child["slot"]: f'{child["position"]}\n{child["weight_kg"]}'
                for child in package["children"]}
    return _row((package["package_number"], package["mother_label"],
                 *(children.get(slot) for slot in "ABCDE"),
                 package["diameter"], package["cuts"], package["tubete"],
                 package["helper"], package["operator"]), WIDTHS)


def render_pdf(snapshot: dict) -> tuple[bytes, int]:
    _register_fonts()
    zone = ZoneInfo("America/La_Paz")
    date = datetime.fromisoformat(snapshot["generated_at"]).astimezone(zone)
    product = snapshot["article_code"]
    if snapshot["article_description"]:
        product += f' - {snapshot["article_description"]}'
    header_widths = ((WIDTH - 2 * MARGIN) / 2,) * 2
    header_rows = [
        _row(pair, header_widths, size=9, min_height=18)
        for pair in (
            (f'Máquina: {snapshot["machine_name"]}', f'Fecha: {date:%d/%m/%Y %H:%M}'),
            (f'Camión: {snapshot["truck_number"]}', f'Orden: {snapshot["order_number"]}'),
            (f'Producto: {product}', f'Formato: {snapshot["format"]}'),
            (f'PV: {snapshot["pv_reference"]}', f'Destino: {snapshot["destination"]}'),
        )
    ]
    table_header = _row(COLUMNS, WIDTHS, size=7, font=BOLD, min_height=25)
    header_top = HEIGHT - 48
    table_top = header_top - sum(row[1] for row in header_rows) - 8
    first_row_top = table_top - table_header[1]
    pages = [{"rows": [], "notes": []}]
    room = first_row_top - BOTTOM
    remaining = room
    for package in snapshot["packages"]:
        row = _package_row(package)
        if row[1] > room:
            raise PDFLayoutError("Un paquete supera el espacio de una página A4")
        if len(pages[-1]["rows"]) == 20 or row[1] > remaining:
            pages.append({"rows": [], "notes": []})
            remaining = room
        pages[-1]["rows"].append(row)
        remaining -= row[1]
    if not pages[0]["rows"]:
        raise PDFLayoutError("El PDF requiere al menos un paquete")

    observations = snapshot["observations"]
    if observations:
        note_lines = _lines(observations, WIDTH - 2 * MARGIN, 9, FONT)
        if remaining < 34:
            pages.append({"rows": [], "notes": []})
            remaining = table_top - BOTTOM
        for line in note_lines:
            if remaining < 11:
                pages.append({"rows": [], "notes": []})
                remaining = table_top - BOTTOM
            if not pages[-1]["notes"]:
                remaining -= 23
            pages[-1]["notes"].append(line)
            remaining -= 11

    output = _LimitedBuffer()
    canvas = Canvas(output, pagesize=A4, pageCompression=1, invariant=1, lang="es-BO")
    canvas.setTitle(TITLE)
    for number, page in enumerate(pages, 1):
        canvas.setLineWidth(0.35)
        canvas.setFont(BOLD, 13)
        canvas.drawString(MARGIN, HEIGHT - 35, TITLE)
        top = header_top
        for row in header_rows:
            top = _draw_row(canvas, top, row, header_widths, size=9)
        top = table_top
        if page["rows"]:
            top = _draw_row(canvas, top, table_header, WIDTHS, size=7, font=BOLD)
            for row in page["rows"]:
                top = _draw_row(canvas, top, row, WIDTHS)
        if page["notes"]:
            canvas.setFont(BOLD, 9)
            title = "Observaciones generales"
            if number > 1 and pages[number - 2]["notes"]:
                title += " (continuación)"
            canvas.drawString(MARGIN, top - 16, title)
            canvas.setFont(FONT, 9)
            for index, line in enumerate(page["notes"]):
                canvas.drawString(MARGIN, top - 30 - 11 * index, line)
        canvas.setFont(FONT, 8)
        canvas.drawRightString(WIDTH - MARGIN, 18, f"Página {number} de {len(pages)}")
        canvas.showPage()
    canvas.save()

    reader = PdfReader(output, strict=True)
    if len(reader.pages) != len(pages) or any(
        page.get_contents() is None or not page.get_contents().get_data() for page in reader.pages
    ):
        raise PDFLayoutError("El PDF generado está incompleto")
    return output.getvalue(), len(pages)
