"""
Filters turkak_all_files_report.csv (every file type) down to files whose
filesystem modified time falls within the last 30 days, and emits a JSON
array for the dashboard's "Recent changes" panel, sorted newest first.
"""

import csv
import json
import os
from datetime import datetime, timedelta

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_all_files_report.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turkak_recent_changes.json")
ROOT_MARKER = "TÜRKAK\\"
DAYS_BACK = 2


def short_path(path):
    idx = path.find(ROOT_MARKER)
    return path[idx + len(ROOT_MARKER):] if idx != -1 else path


def main():
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    rows = []

    with open(INPUT_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fs_time = row.get("FileSystemModifiedTime") or ""
            try:
                dt = datetime.strptime(fs_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if dt < cutoff:
                continue
            rows.append({
                "path": short_path(row["FilePath"]),
                "fullPath": row["FilePath"],
                "extension": row.get("Extension") or "",
                "modifiedAt": fs_time,
                "lastModifiedBy": row.get("LastModifiedBy") or "",
                "creator": row.get("Creator") or "",
                "createdInFile": row.get("CreatedInFile") or "",
                "sizeBytes": int(row.get("SizeBytes") or 0),
                "note": row.get("Note") or "",
            })

    rows.sort(key=lambda r: r["modifiedAt"], reverse=True)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"{len(rows)} files modified in the last {DAYS_BACK} days (since {cutoff:%Y-%m-%d}).")
    print(f"Written to: {OUTPUT_JSON}")
    for r in rows[:20]:
        print(f"  {r['modifiedAt']}  {r['lastModifiedBy'] or '(unknown)':<20}  {r['path']}")


if __name__ == "__main__":
    main()
