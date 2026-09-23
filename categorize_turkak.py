"""
Categorizes turkak_full_report.csv into breakdowns for the dashboard:
by last-modified-by, by top-level folder, by year, by extension.
"""

import csv
import json
import os
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_full_report.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_summary_turkak.json")
ROOT_MARKER = "TÜRKAK\\"


def top_level_folder(path):
    idx = path.find(ROOT_MARKER)
    if idx == -1:
        return "Unknown"
    rest = path[idx + len(ROOT_MARKER):]
    return rest.split("\\", 1)[0] if rest else "Unknown"


def main():
    by_user = Counter()
    by_folder = Counter()
    by_year = Counter()
    by_ext = Counter()
    unreadable = 0
    total = 0

    with open(INPUT_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            path = row["FilePath"]
            ext = os.path.splitext(path)[1].lower()
            by_ext[ext] += 1

            if row.get("Note"):
                unreadable += 1

            user = row.get("LastModifiedBy") or "(unknown / legacy file)"
            by_user[user] += 1

            by_folder[top_level_folder(path)] += 1

            modified = row.get("ModifiedInFile") or ""
            year = modified[:4] if len(modified) >= 4 else "Unknown"
            by_year[year] += 1

    summary = {
        "total_files": total,
        "unreadable_files": unreadable,
        "by_last_modified_by": by_user.most_common(),
        "by_folder": by_folder.most_common(),
        "by_year_modified": sorted(by_year.items()),
        "by_extension": by_ext.most_common(),
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Total: {total} ({unreadable} unreadable)")
    print("\nBy Last Modified By:")
    for name, count in by_user.most_common():
        print(f"  {name}: {count}")
    print("\nBy Folder:")
    for name, count in by_folder.most_common():
        print(f"  {name}: {count}")
    print("\nBy Year:")
    for year, count in sorted(by_year.items()):
        print(f"  {year}: {count}")
    print("\nBy Extension:")
    for ext, count in by_ext.most_common():
        print(f"  {ext or '(no ext)'}: {count}")


if __name__ == "__main__":
    main()
