"""
Produces a report of every Excel file under the TEST RAPORLARI network share,
showing who last saved each file and when, using the metadata Excel embeds
in every .xlsx/.xlsm file (docProps/core.xml: creator, last modified by,
created/modified timestamps). This works retroactively on existing files and
correctly attributes changes made from any computer, unlike relying on the
local Windows username.

Legacy .xls files (old binary format) don't carry this XML metadata, so for
those only the filesystem's last-modified time is recorded.

Output: test_raporlari_report.csv in this script's folder.
"""

import csv
import os
import sys
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

ROOT_PATH = r"\\192.168.100.3\test\TEST RAPORLARI"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_raporlari_report.csv")

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

                creator = find("dc", "creator")
                last_modified_by = find("cp", "lastModifiedBy")
                created = find("dcterms", "created")
                modified = find("dcterms", "modified")
                return creator, last_modified_by, created, modified, ""
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
    errors = 0

    print(f"Scanning: {ROOT_PATH}")
    print("This may take a while over the network...\n")

    for dirpath, _dirnames, filenames in os.walk(ROOT_PATH):
        for name in filenames:
            lower = name.lower()
            full_path = os.path.join(dirpath, name)

            if lower.endswith(MODERN_EXTENSIONS):
                creator, last_modified_by, created, modified, err = read_core_properties(full_path)
                rows.append({
                    "FilePath": full_path,
                    "Creator": creator,
                    "LastModifiedBy": last_modified_by,
                    "CreatedInFile": created,
                    "ModifiedInFile": modified,
                    "FileSystemModifiedTime": fs_modified(full_path),
                    "Note": err,
                })
                scanned += 1
                if err:
                    errors += 1
            elif lower.endswith(LEGACY_EXTENSIONS):
                rows.append({
                    "FilePath": full_path,
                    "Creator": "",
                    "LastModifiedBy": "",
                    "CreatedInFile": "",
                    "ModifiedInFile": "",
                    "FileSystemModifiedTime": fs_modified(full_path),
                    "Note": "legacy .xls format - embedded author metadata not read",
                })
                scanned += 1

            if scanned % 200 == 0 and scanned > 0:
                print(f"  ...{scanned} files scanned so far")
                sys.stdout.flush()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FilePath", "Creator", "LastModifiedBy",
            "CreatedInFile", "ModifiedInFile", "FileSystemModifiedTime", "Note",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {scanned} Excel files scanned ({errors} could not be read), report written to:")
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()
