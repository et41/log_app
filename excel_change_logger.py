"""
Monitors the current user's Desktop for changes to Excel files and logs
who (Windows user) made the change and when.

Requires: pip install watchdog

Run it, leave it running in the background, and it will append a row to
excel_change_log.csv every time an Excel file on the Desktop is created,
modified, renamed, or deleted.

Note: this only records changes made WHILE this script is running.
"""

import csv
import getpass
import os
import time
from datetime import datetime

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "excel_change_log.csv")
EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".csv")


def is_excel_file(path: str) -> bool:
    name = os.path.basename(path)
    # Ignore Excel's temporary lock files, e.g. "~$report.xlsx"
    if name.startswith("~$"):
        return False
    return name.lower().endswith(EXCEL_EXTENSIONS)


def log_event(event_type: str, path: str, extra: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = getpass.getuser()
    row = [timestamp, user, event_type, path, extra]

    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "User", "EventType", "FilePath", "Details"])
        writer.writerow(row)

    print(f"[{timestamp}] {user} -> {event_type}: {path} {extra}")


class ExcelChangeHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and is_excel_file(event.src_path):
            log_event("CREATED", event.src_path)

    def on_modified(self, event):
        if not event.is_directory and is_excel_file(event.src_path):
            log_event("MODIFIED", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and is_excel_file(event.src_path):
            log_event("DELETED", event.src_path)

    def on_moved(self, event):
        if not event.is_directory and (is_excel_file(event.src_path) or is_excel_file(event.dest_path)):
            log_event("RENAMED/MOVED", event.src_path, f"-> {event.dest_path}")


def main():
    if not os.path.isdir(DESKTOP_PATH):
        raise SystemExit(f"Desktop path not found: {DESKTOP_PATH}")

    print(f"Watching for Excel file changes in: {DESKTOP_PATH}")
    print(f"Logging to: {LOG_FILE}")
    print("Press Ctrl+C to stop.\n")

    event_handler = ExcelChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, DESKTOP_PATH, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nStopped.")
    observer.join()


if __name__ == "__main__":
    main()
