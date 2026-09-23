"""
Categorizes the test_raporlari_report.csv (produced by test_raporlari_report.py)
into useful breakdowns:
  - by person who last modified files
  - by customer/brand (parsed from the top-level project folder name)
  - by year last modified
  - by file type (.xlsx/.xlsm vs legacy .xls)

Writes category_summary.json (for the dashboard artifact) and prints a
plain-text summary to the console.
"""

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_raporlari_report.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_summary.json")
ROOT_MARKER = "TEST RAPORLARI\\"

# e.g. "138307 (1000 kVA) BETA" -> customer "BETA"
CUSTOMER_RE = re.compile(r"\)\s*(.+)$")


def top_level_folder(path):
    idx = path.find(ROOT_MARKER)
    if idx == -1:
        return None
    rest = path[idx + len(ROOT_MARKER):]
    return rest.split("\\", 1)[0] if rest else None


def extract_customer(folder_name):
    if not folder_name:
        return "Unknown"
    m = CUSTOMER_RE.search(folder_name)
    if m:
        return m.group(1).strip()
    return folder_name.strip()


def main():
    if not os.path.isfile(INPUT_CSV):
        raise SystemExit(f"Input not found: {INPUT_CSV}. Run test_raporlari_report.py first.")

    by_user = Counter()
    by_creator = Counter()
    by_customer = Counter()
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

            creator = row.get("Creator") or "(unknown / legacy file)"
            by_creator[creator] += 1

            folder = top_level_folder(path)
            customer = extract_customer(folder)
            by_customer[customer] += 1

            modified = row.get("ModifiedInFile") or ""
            year = modified[:4] if len(modified) >= 4 else "Unknown"
            by_year[year] += 1

    summary = {
        "total_files": total,
        "unreadable_files": unreadable,
        "by_last_modified_by": by_user.most_common(),
        "by_creator": by_creator.most_common(),
        "by_customer": by_customer.most_common(),
        "by_year_modified": sorted(by_year.items()),
        "by_extension": by_ext.most_common(),
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Total files: {total} ({unreadable} unreadable)\n")

    print("=== Top 15 by Last Modified By ===")
    for name, count in by_user.most_common(15):
        print(f"  {name}: {count}")

    print("\n=== Top 15 Customers/Brands (by file count) ===")
    for name, count in by_customer.most_common(15):
        print(f"  {name}: {count}")

    print("\n=== By Year Last Modified ===")
    for year, count in sorted(by_year.items()):
        print(f"  {year}: {count}")

    print("\n=== By File Extension ===")
    for ext, count in by_ext.most_common():
        print(f"  {ext or '(no ext)'}: {count}")

    print(f"\nFull summary written to: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
