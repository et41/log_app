"""
Live per-file edit-history monitor for the TEST RAPORLARI and TÜRKAK network shares.

Tracks EVERY file type, not just Excel. Files in OOXML format (.xlsx/.xlsm/
.docx/.dotx/.pptx/.potx/...) carry embedded creator/last-modified-by metadata
(docProps/core.xml) that this reads on each event. Every other file type
(legacy .xls/.doc/.ppt, PDFs, images, plain files, ...) still gets a row -
just without that author metadata, since the file format doesn't carry it.

Unlike the one-time report (test_raporlari_report.py), which only ever sees
the CURRENT creator/last-modified-by baked into each file, this watches the
share continuously. Every time a file is saved, it re-reads the file's
embedded metadata (where available) and appends a new row to
edit_history_log.csv - so over time this builds a real multi-editor history
per file (who touched it, and when), instead of just the latest snapshot.

Network shares don't reliably deliver native filesystem change notifications
over SMB, so this uses watchdog's PollingObserver (checks for changes every
few seconds) instead of the native OS observer.

Requires: pip install watchdog
"""

import csv
import os
import sys
import time
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WATCH_PATHS = [
    r"\\192.168.100.3\test\TÜRKAK",
]
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edit_history_log.csv")
POLL_INTERVAL_SECONDS = 60

# OOXML (zip-based) formats - readable via docProps/core.xml.
OOXML_EXTENSIONS = (
    ".xlsx", ".xlsm", ".xltx", ".xltm",
    ".docx", ".docm", ".dotx", ".dotm",
    ".pptx", ".pptm", ".potx", ".potm",
)

# Noise files that change constantly and aren't meaningful edits.
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}


def is_tracked_file(path: str) -> bool:
    name = os.path.basename(path)
    if name.startswith("~$") or name.startswith("."):
        return False
    if name.lower() in IGNORED_NAMES:
        return False
    return True


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


def log_event(event_type: str, path: str):
    seen_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lower = path.lower()

    if lower.endswith(OOXML_EXTENSIONS):
        creator, last_modified_by, created, modified, err = read_core_properties(path)
    else:
        creator, last_modified_by, created, modified, err = "", "", "", "", "file type has no embedded author metadata"

    row = [seen_at, event_type, path, last_modified_by, creator, modified, err]

    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["SeenAt", "EventType", "FilePath", "LastModifiedBy", "Creator", "ModifiedInFile", "Note"])
        writer.writerow(row)

    who = last_modified_by or "(unknown)"
    print(f"[{seen_at}] {event_type}: {os.path.basename(path)} -> {who}")
    sys.stdout.flush()


class FileHistoryHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and is_tracked_file(event.src_path):
            log_event("CREATED", event.src_path)

    def on_modified(self, event):
        if not event.is_directory and is_tracked_file(event.src_path):
            log_event("MODIFIED", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and is_tracked_file(event.src_path):
            log_event("DELETED", event.src_path)

    def on_moved(self, event):
        if not event.is_directory and (is_tracked_file(event.src_path) or is_tracked_file(event.dest_path)):
            log_event("RENAMED/MOVED", event.dest_path)


def main():
    handler = FileHistoryHandler()
    observer = PollingObserver(timeout=POLL_INTERVAL_SECONDS)

    watched_any = False
    for path in WATCH_PATHS:
        if not os.path.isdir(path):
            print(f"Skipping (not found or not accessible): {path}")
            continue
        print(f"Watching (polling every {POLL_INTERVAL_SECONDS}s): {path}")
        observer.schedule(handler, path, recursive=True)
        watched_any = True

    if not watched_any:
        raise SystemExit("None of the configured watch paths are accessible.")

    print(f"Logging to: {LOG_FILE}")
    sys.stdout.flush()
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
