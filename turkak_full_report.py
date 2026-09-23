"""
Full recursive scan of the TÜRKAK network folder (no date filter) - same
metadata extraction as test_raporlari_report.py. Used to rebuild the
dashboard's static charts/tables around TÜRKAK instead of TEST RAPORLARI.

Output: turkak_full_report.csv in this script's folder.
"""

import csv
import os
import sys
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

ROOT_PATH = r"\\192.168.100.3\test\TÜRKAK"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_full_report.csv")

MODERN_EXTENSIONS = (".xlsx", ".xlsm")
LEGACY_EXTENSIONS = (".xls",)

NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}


def read_core_properties(path):
    try:
        with zipfile.ZipFile(path) as z:
            with z.open("docProps/core.xml") as f:
                root = ET.parse(f).getroot()

                def find(tag_ns, tag):
                    el = root.find(f"{{{NS[tag_ns]}}}{tag}")
                    return el.text if el is not None and el.text else ""

                return (
                    find("dc", "creator"),
                    find("cp", "lastModifiedBy"),
                    find("dcterms", "created"),
                    find("dcterms", "modified"),
                    "",
                )
    except Exception as e:
        return "", "", "", "", str(e)


def fs_modified(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def main():
    if not os.path.isdir(ROOT_PATH):
        raise SystemExit(f"Path not found or not accessible: {ROOT_PATH}")

    rows = []
    scanned = 0

    print(f"Scanning: {ROOT_PATH}")

    for dirpath, _dirnames, filenames in os.walk(ROOT_PATH):
        for name in filenames:
            lower = name.lower()
            full_path = os.path.join(dirpath, name)

            if lower.endswith(MODERN_EXTENSIONS):
                creator, last_modified_by, created, modified, err = read_core_properties(full_path)
                rows.append({
                    "FilePath": full_path, "Creator": creator, "LastModifiedBy": last_modified_by,
                    "CreatedInFile": created, "ModifiedInFile": modified,
                    "FileSystemModifiedTime": fs_modified(full_path), "Note": err,
                })
                scanned += 1
            elif lower.endswith(LEGACY_EXTENSIONS):
                rows.append({
                    "FilePath": full_path, "Creator": "", "LastModifiedBy": "",
                    "CreatedInFile": "", "ModifiedInFile": "",
                    "FileSystemModifiedTime": fs_modified(full_path),
                    "Note": "legacy .xls format - embedded author metadata not read",
                })
                scanned += 1

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FilePath", "Creator", "LastModifiedBy",
            "CreatedInFile", "ModifiedInFile", "FileSystemModifiedTime", "Note",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. {scanned} Excel files scanned, report written to: {OUTPUT_CSV}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
