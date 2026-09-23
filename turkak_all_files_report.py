"""
Full recursive scan of TÜRKAK covering EVERY file type (not just Excel).
For OOXML documents (.xlsx/.xlsm/.docx/.pptx/...) it also reads embedded
creator/last-modified-by metadata; every other file type just gets its
path, extension, size and filesystem timestamp.

Output: turkak_all_files_report.csv in this script's folder.
"""

import csv
import os
import sys
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_PATH = r"\\192.168.100.3\test\TÜRKAK"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_all_files_report.csv")

OOXML_EXTENSIONS = (
    ".xlsx", ".xlsm", ".xltx", ".xltm",
    ".docx", ".docm", ".dotx", ".dotm",
    ".pptx", ".pptm", ".potx", ".potm",
)
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

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


def fs_stat(path):
    try:
        st = os.stat(path)
        return st.st_size, datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0, ""


def main():
    if not os.path.isdir(ROOT_PATH):
        raise SystemExit(f"Path not found or not accessible: {ROOT_PATH}")

    rows = []
    scanned = 0

    print(f"Scanning (all file types): {ROOT_PATH}")

    for dirpath, _dirnames, filenames in os.walk(ROOT_PATH):
        for name in filenames:
            if name.startswith("~$") or name.lower() in IGNORED_NAMES:
                continue
            full_path = os.path.join(dirpath, name)
            ext = os.path.splitext(name)[1].lower()
            size, mtime = fs_stat(full_path)

            if ext in OOXML_EXTENSIONS:
                creator, last_modified_by, created, modified, err = read_core_properties(full_path)
            else:
                creator, last_modified_by, created, modified, err = "", "", "", "", ""

            rows.append({
                "FilePath": full_path,
                "Extension": ext or "(none)",
                "SizeBytes": size,
                "Creator": creator,
                "LastModifiedBy": last_modified_by,
                "CreatedInFile": created,
                "ModifiedInFile": modified,
                "FileSystemModifiedTime": mtime,
                "Note": err,
            })
            scanned += 1
            if scanned % 200 == 0:
                print(f"  ...{scanned} files scanned so far")
                sys.stdout.flush()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FilePath", "Extension", "SizeBytes", "Creator", "LastModifiedBy",
            "CreatedInFile", "ModifiedInFile", "FileSystemModifiedTime", "Note",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {scanned} files scanned (all types), report written to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
