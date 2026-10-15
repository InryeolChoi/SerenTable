"""Read an XLSX source without changing it; emit aggregate diagnostics only.

Usage: python scripts/audit_source_data.py /absolute/path/to/source.xlsx
Uses the standard library. Cell strings are data, never commands or formulas.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def audit(path):
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(n.itertext()) for n in
                       ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        relationships = {r.attrib["Id"]: r.attrib["Target"] for r in
                         ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = ET.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS)
        reports = []
        for sheet in sheets:
            target = relationships[sheet.attrib[f"{{{REL}}}id"]]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(member))
            rows = {}
            formula_count = 0
            for row in root.findall("s:sheetData/s:row", NS):
                cells = {}
                for cell in row.findall("s:c", NS):
                    column = re.match(r"[A-Z]+", cell.attrib["r"])[0]
                    value = cell.findtext("s:v", default="", namespaces=NS)
                    if cell.attrib.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.find("s:is", NS).itertext())
                    formula_count += cell.find("s:f", NS) is not None
                    cells[column] = value
                rows[int(row.attrib["r"])] = cells
            headers = rows[2]
            data = [r for n, r in rows.items() if n > 2 and any(str(v).strip() for v in r.values())]
            get = lambda column: [str(r.get(column, "")).strip() for r in data]
            names = Counter(get("B"))
            mbti = get("H")
            single = lambda value: re.fullmatch(r"[EI][NS][TF][JP]", value, re.I) is not None
            tokens = lambda value: re.findall(r"(?<![A-Z])[EI][NS][TF][JP](?![A-Z])", value.upper())
            dates = get("N")
            reports.append({
                "sheet": sheet.attrib["name"],
                "header_row": 2,
                "last_serialized_row": max(rows),
                "serialized_rows": len(rows),
                "response_rows": len(data),
                "blank_rows_through_last": max(rows) - 1 - len(data),
                "formula_cells": formula_count,
                "columns": [{"column": c, "header": h, "present": sum(bool(v) for v in get(c)),
                             "missing": sum(not v for v in get(c))}
                            for c, h in headers.items() if str(h).strip()],
                "distinct_name_strings": len(names),
                "repeated_name_groups": sum(n > 1 for n in names.values()),
                "rows_in_repeated_name_groups": sum(n for n in names.values() if n > 1),
                "mbti": {"single_case_insensitive": sum(single(v) for v in mbti),
                         "single_with_lowercase_letters": sum(single(v) and v != v.upper() for v in mbti),
                         "rows_with_surrounding_whitespace": sum(str(r.get("H", "")) != str(r.get("H", "")).strip() for r in data),
                         "multiple_valid_tokens": sum(not single(v) and len(tokens(v)) > 1 for v in mbti),
                         "single_token_with_other_text": sum(not single(v) and len(tokens(v)) == 1 for v in mbti),
                         "no_valid_token": sum(not tokens(v) for v in mbti)},
                "date_rows_with_year": sum(bool(re.search(r"\b\d{4}\b", v)) for v in dates),
                "date_rows_multiple_month_day": sum(len(re.findall(r"\d{1,2}/\d{1,2}", v)) > 1 for v in dates),
                "date_rows_with_region_note": sum("가능" in v for v in dates),
                "interests_rows_embedded_parenthetical_comma": sum(bool(re.search(r"\([^)]*,[^)]*\)", v)) for v in get("J")),
                "price_rows_multiple_ranges": sum(len(re.findall(r"10,000~20,000원|20,000~30,000원|30,000원 이상", v)) > 1 for v in get("M")),
                "consent_distinct_strings": len(set(get("P"))),
            })
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("Source hash changed during read-only audit")
    return {"sha256": before, "source_unchanged": True, "sheets": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.source), ensure_ascii=False, indent=2))
