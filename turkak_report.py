"""
Same approach as test_raporlari_report.py (reads each .xlsx/.xlsm file's
embedded docProps/core.xml metadata: creator, last-modified-by, created,
modified) but scoped to the TURKAK network folder and restricted to files
whose embedded "modified" timestamp falls within the last 30 days.

Output: turkak_report.csv in this script's folder.
"""

import csv
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

ROOT_PATH = r"\\192.168.100.3\test\TÜRKAK"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_report.csv")
DAYS_BACK = 30

MODERN_EXTENSIONS = (".xlsx", ".xlsm")
LEGACY_EXTENSIONS = (".xls",)

NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}


def read_core_properties(path):
    """Returns (creator, last_modified_by, created, modified, error)."""
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
        return datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


def parse_office_dt(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main():
    if not os.path.isdir(ROOT_PATH):
        raise SystemExit(f"Path not found or not accessible: {ROOT_PATH}")

    cutoff_utc = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    cutoff_local = datetime.now() - timedelta(days=DAYS_BACK)

    rows = []
    scanned = 0
    matched = 0

    print(f"Scanning: {ROOT_PATH}")
    print(f"Only keeping files modified in the last {DAYS_BACK} days (since {cutoff_local:%Y-%m-%d})\n")

    for dirpath, _dirnames, filenames in os.walk(ROOT_PATH):
        for name in filenames:
            lower = name.lower()
            full_path = os.path.join(dirpath, name)

            if lower.endswith(MODERN_EXTENSIONS):
                creator, last_modified_by, created, modified, err = read_core_properties(full_path)
                mod_dt = parse_office_dt(modified)
                in_range = mod_dt is not None and mod_dt >= cutoff_utc
            elif lower.endswith(LEGACY_EXTENSIONS):
                creator, last_modified_by, created, modified, err = "", "", "", "", "legacy .xls format - embedded author metadata not read"
                fs_dt = fs_modified(full_path)
                in_range = fs_dt is not None and fs_dt >= cutoff_local
                modified = fs_dt.strftime("%Y-%m-%dT%H:%M:%S") if fs_dt else ""
            else:
                continue

            scanned += 1
            if in_range:
                matched += 1
                rows.append({
                    "FilePath": full_path,
                    "Creator": creator,
                    "LastModifiedBy": last_modified_by,
                    "CreatedInFile": created,
                    "ModifiedInFile": modified,
                    "FileSystemModifiedTime": fs_modified(full_path).strftime("%Y-%m-%d %H:%M:%S") if fs_modified(full_path) else "",
                    "Note": err,
                })

            if scanned % 200 == 0:
                print(f"  ...{scanned} files scanned so far ({matched} within {DAYS_BACK} days)")
                sys.stdout.flush()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FilePath", "Creator", "LastModifiedBy",
            "CreatedInFile", "ModifiedInFile", "FileSystemModifiedTime", "Note",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {scanned} Excel files scanned, {matched} modified in the last {DAYS_BACK} days.")
    print(f"Report written to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
