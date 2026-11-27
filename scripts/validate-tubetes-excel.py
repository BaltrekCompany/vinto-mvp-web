#!/usr/bin/env python3
"""Validate the generated TUB-05 workbook as an actual OOXML ZIP package."""

from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vinto-tubetes-excel-ci.xlsx")
assert path.is_file(), f"Workbook fixture not found: {path}"

expected = {
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/styles.xml",
    "xl/worksheets/sheet1.xml",
    "xl/worksheets/sheet2.xml",
}

with zipfile.ZipFile(path, "r") as workbook:
    assert workbook.testzip() is None, "ZIP CRC validation failed"
    names = set(workbook.namelist())
    assert expected == names, f"Unexpected OOXML parts: {sorted(names ^ expected)}"

    roots = {}
    for name in sorted(expected):
        roots[name] = ET.fromstring(workbook.read(name))

main_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
workbook_root = roots["xl/workbook.xml"]
sheet_names = [node.attrib["name"] for node in workbook_root.findall("x:sheets/x:sheet", main_ns)]
assert sheet_names == ["MP1", "MP3"], sheet_names

styles_root = roots["xl/styles.xml"]
formats = [node.attrib.get("formatCode") for node in styles_root.findall("x:numFmts/x:numFmt", main_ns)]
assert "dd/mm/yy" in formats, formats

mp1 = roots["xl/worksheets/sheet1.xml"]
mp3 = roots["xl/worksheets/sheet2.xml"]
assert mp1.find("x:dimension", main_ns).attrib["ref"] == "A1"
assert mp3.find("x:dimension", main_ns).attrib["ref"] == "A1:B4"
assert len(mp1.findall("x:sheetData/x:row", main_ns)) == 1
assert len(mp3.findall("x:sheetData/x:row", main_ns)) == 4
assert mp3.find("x:autoFilter", main_ns).attrib["ref"] == "A1:B4"

print("TUBETES_XLSX_OOXML=PASS")
