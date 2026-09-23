"""
Categorizes turkak_all_files_report.csv (every file type, not just Excel)
into breakdowns for the dashboard: by top-level folder, by subfolder
(one level deeper), by file extension, and by last-modified-by (only
meaningful for OOXML files, which are the only ones carrying that metadata).
"""

import csv
import json
import os
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_all_files_report.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_summary_turkak_all.json")
ROOT_MARKER = "TÜRKAK\\"


def path_parts(path):
    idx = path.find(ROOT_MARKER)
    if idx == -1:
        return "Unknown", "Unknown/(root)"
    rest = path[idx + len(ROOT_MARKER):]
    parts = rest.split("\\")
    if len(parts) <= 1:
        # A file sitting directly in the TÜRKAK root, not inside any folder.
        return "(files in TÜRKAK root)", "(files in TÜRKAK root)"
    top = parts[0]
    sub = top + "/" + parts[1] if len(parts) > 2 else top + "/(root)"
    return top, sub


def main():
    by_top = Counter()
    by_sub = Counter()
    by_ext = Counter()
    by_user = Counter()
    by_year = Counter()
    total = 0
    ooxml_total = 0

    with open(INPUT_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            path = row["FilePath"]
            top, sub = path_parts(path)
            by_top[top] += 1
            by_sub[sub] += 1
            by_ext[row.get("Extension") or "(none)"] += 1

            last_mod = row.get("LastModifiedBy")
            created = row.get("CreatedInFile")
            if created:
                ooxml_total += 1
                by_user[last_mod or "(unknown / unreadable)"] += 1

            fs_time = row.get("FileSystemModifiedTime") or ""
            year = fs_time[:4] if len(fs_time) >= 4 else "Unknown"
            by_year[year] += 1

    summary = {
        "total_files": total,
        "ooxml_files_with_metadata": ooxml_total,
        "by_top_folder": by_top.most_common(),
        "by_subfolder": by_sub.most_common(),
        "by_extension": by_ext.most_common(),
        "by_last_modified_by": by_user.most_common(),
        "by_year_modified": sorted(by_year.items()),
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Total files: {total} ({ooxml_total} OOXML files carry author metadata)\n")
    print("By top folder:")
    for name, count in by_top.most_common():
        print(f"  {name}: {count}")
    print("\nBy subfolder (top 25):")
    for name, count in by_sub.most_common(25):
        print(f"  {name}: {count}")
    print(f"\nBy extension ({len(by_ext)} distinct types):")
    for ext, count in by_ext.most_common():
        print(f"  {ext}: {count}")
    print("\nBy last modified by (OOXML only):")
    for name, count in by_user.most_common():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
