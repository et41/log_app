"""
Windows file-access audit collector for the TÜRKAK folder.

The other scripts only know "who" from the Office author metadata embedded in
each file, which says nothing about reads or copies and is blank for PDFs,
legacy .doc/.xls, images, etc. This reads the Windows Security event log of
the machine holding the folder instead, so every access is attributed to the
real Windows account that made it, for every file type:

  4663  "An attempt was made to access an object"  (needs a SACL on the folder)
  5145  "A network share object was checked"       (shares only; adds client IP)

Two modes, set by SERVER / WATCH_ROOT below:
  - local  (SERVER = None): the folder is on this PC; reads this PC's
    Security log. Must run elevated.
  - server (SERVER = "192.168.100.3", WATCH_ROOT = the UNC path): reads the
    file server's Security log remotely.

enable_file_auditing.ps1 does the one-time setup (audit policy + SACL); for
the local folder run it here with -FolderPath, for the share run it on the
server.

Each access is classified from its access mask as READ / WRITE / DELETE /
PERMISSIONS. A WRITE of a new file that closely follows a READ of a file with
the same name (or the same name plus " - Kopya" / " - Copy") by the same user
is reported as COPY, with the source path. Copies from the share to a user's
own PC can only ever show up as READ - the server never sees the destination.

Repeated events for the same user + file + action within MERGE_WINDOW_SECONDS
collapse into one row (Office opens a file many times per "open").

Rows are appended to file_access_log.csv; the last N days are also written to
file_access_recent.json, and the newest rows to file_access_live.json - the
body of the dashboard's live db document "logs/access". The last processed EventRecordID is
kept in file_access_state.json, so each run only fetches new events.

Usage:
  python file_access_collector.py                  # one pass
  python file_access_collector.py --watch          # keep polling
  python file_access_collector.py --evtx Security.evtx   # exported log file

Run as an account that can read the Security log (elevated admin locally;
"Event Log Readers" or admin on the server). No extra Python packages.
dashboard_server.py runs this on a timer and serves the dashboard.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# None = this PC's own Security log; "192.168.100.3" = the file server's
# (then WATCH_ROOT = r"\\192.168.100.3\test\TÜRKAK").
SERVER = None
WATCH_ROOT = r"C:\Users\Ares Trafo\Desktop\TÜRKAK"
ROOT_MARKER = "\\TÜRKAK\\"

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "file_access_log.csv")
STATE_FILE = os.path.join(HERE, "file_access_state.json")
RECENT_JSON = os.path.join(HERE, "file_access_recent.json")
# Body of the dashboard's live db doc "logs/access" (newest LIVE_MAX_EVENTS rows).
LIVE_JSON = os.path.join(HERE, "file_access_live.json")
LIVE_MAX_EVENTS = 400

RECENT_DAYS = 2
FIRST_RUN_DAYS_BACK = 7
POLL_INTERVAL_SECONDS = 60
BATCH_SIZE = 5000
MERGE_WINDOW_SECONDS = 60
COPY_WINDOW_SECONDS = 15

EVENT_IDS = (4663, 5145)
EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

# File access-mask bits (winnt.h).
READ_DATA = 0x1
WRITE_DATA = 0x2
APPEND_DATA = 0x4
DELETE = 0x10000
WRITE_DAC = 0x40000
WRITE_OWNER = 0x80000

IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
IGNORED_USERS = {"", "-", "system", "local service", "network service", "anonymous logon"}
# Background readers that touch every file (indexing, antivirus) - not a person opening it.
IGNORED_PROCESSES = {
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe",
    "msmpeng.exe", "mpdefendercoreservice.exe", "mssense.exe",
}
COPY_SUFFIX_RE = re.compile(r"( - (kopya|copy))( \(\d+\))?$|( \(\d+\))$", re.IGNORECASE)

CSV_HEADER = ["Time", "User", "Action", "FilePath", "CopiedFrom", "ClientIP", "Process", "Count", "EventID", "RecordID"]


def classify(mask):
    if mask & DELETE:
        return "DELETE"
    if mask & (WRITE_DATA | APPEND_DATA):
        return "WRITE"
    if mask & (WRITE_DAC | WRITE_OWNER):
        return "PERMISSIONS"
    if mask & READ_DATA:
        return "READ"
    return None  # attribute/ACL reads - noise


def relative_path(object_path):
    """'D:\\test\\TÜRKAK\\a\\b.xlsx' or 'TÜRKAK\\a\\b.xlsx' -> 'a\\b.xlsx'."""
    p = "\\" + object_path.lstrip("\\")
    idx = p.upper().find(ROOT_MARKER)
    if idx == -1:
        return None
    rel = p[idx + len(ROOT_MARKER):]
    if ":" in rel:
        return None  # alternate data stream (file.docx:Zone.Identifier), not a file
    return rel.rstrip("\\") or None


def is_tracked_file(rel):
    name = rel.rsplit("\\", 1)[-1]
    if name.startswith("~$") or name.startswith("."):
        return False
    return name.lower() not in IGNORED_NAMES


_isdir_cache = {}


def is_directory(rel):
    if rel not in _isdir_cache:
        _isdir_cache[rel] = os.path.isdir(os.path.join(WATCH_ROOT, rel))
    return _isdir_cache[rel]


def parse_time(system_time):
    # '2026-09-24T05:12:33.1234567Z' -> local naive datetime
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?", system_time)
    frac = (m.group(2) or ".0")[:7]
    dt = datetime.strptime(m.group(1) + frac, "%Y-%m-%dT%H:%M:%S.%f")
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def parse_event(xml_text):
    """Returns (record_id, access_dict_or_None)."""
    root = ET.fromstring(xml_text)
    system = root.find("e:System", EVENT_NS)
    event_id = int(system.find("e:EventID", EVENT_NS).text)
    record_id = int(system.find("e:EventRecordID", EVENT_NS).text)
    when = parse_time(system.find("e:TimeCreated", EVENT_NS).get("SystemTime"))

    data = {}
    event_data = root.find("e:EventData", EVENT_NS)
    if event_data is not None:
        for d in event_data.findall("e:Data", EVENT_NS):
            data[d.get("Name")] = d.text or ""

    user = data.get("SubjectUserName", "")
    if user.lower() in IGNORED_USERS or user.endswith("$"):
        return record_id, None

    if event_id == 4663:
        object_path, client_ip, process = data.get("ObjectName", ""), "", data.get("ProcessName", "")
    elif event_id == 5145:
        object_path, client_ip, process = data.get("RelativeTargetName", ""), data.get("IpAddress", ""), ""
    else:
        return record_id, None

    if os.path.basename(process).lower() in IGNORED_PROCESSES:
        return record_id, None

    rel = relative_path(object_path)
    if not rel or not is_tracked_file(rel) or is_directory(rel):
        return record_id, None

    try:
        mask = int(data.get("AccessMask", "0"), 16)
    except ValueError:
        return record_id, None
    action = classify(mask)
    if not action:
        return record_id, None

    domain = data.get("SubjectDomainName", "")
    return record_id, {
        "time": when,
        "user": f"{domain}\\{user}" if domain and domain != "-" else user,
        "action": action,
        "path": rel,
        "copiedFrom": "",
        "clientIp": client_ip if client_ip not in ("-", "::1", "127.0.0.1") else "",
        "process": os.path.basename(process) if process and process != "-" else "",
        "count": 1,
        "eventId": event_id,
        "recordId": record_id,
    }


def fetch_events(after_record_id, evtx_path=None):
    """Returns a list of event XML strings, oldest first."""
    ids = " or ".join(f"EventID={i}" for i in EVENT_IDS)
    if after_record_id:
        xpath = f"*[System[({ids}) and EventRecordID > {after_record_id}]]"
    else:
        ms = FIRST_RUN_DAYS_BACK * 24 * 3600 * 1000
        xpath = f"*[System[({ids}) and TimeCreated[timediff(@SystemTime) <= {ms}]]]"

    def ps_quote(s):
        return "'" + s.replace("'", "''") + "'"

    if evtx_path:
        source = f"-Path {ps_quote(evtx_path)}"
    elif SERVER:
        source = f"-ComputerName {ps_quote(SERVER)} -LogName Security"
    else:
        source = "-LogName Security"
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "try { "
        f"Get-WinEvent {source} -FilterXPath {ps_quote(xpath)} -MaxEvents {BATCH_SIZE} -Oldest -ErrorAction Stop "
        "| ForEach-Object { $_.ToXml() -replace \"`r|`n\", '' } "
        "} catch { "
        "if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') "
        "{ [Console]::Error.WriteLine($_.Exception.Message); exit 1 } "
        "}; exit 0"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "Get-WinEvent failed")
    text = result.stdout.decode("utf-8-sig", "replace")
    return [line for line in text.splitlines() if line.startswith("<Event")]


def merge_repeats(accesses):
    merged = []
    last_by_key = {}
    for a in sorted(accesses, key=lambda a: (a["time"], a["recordId"])):
        key = (a["user"].lower(), a["path"].lower(), a["action"])
        prev = last_by_key.get(key)
        if prev and (a["time"] - prev["lastTime"]).total_seconds() <= MERGE_WINDOW_SECONDS:
            prev["count"] += 1
            prev["lastTime"] = a["time"]
            prev["clientIp"] = prev["clientIp"] or a["clientIp"]
            prev["process"] = prev["process"] or a["process"]
            continue
        a["lastTime"] = a["time"]
        merged.append(a)
        last_by_key[key] = a
    return merged


def base_name_key(rel):
    stem, ext = os.path.splitext(rel.rsplit("\\", 1)[-1])
    return (COPY_SUFFIX_RE.sub("", stem).strip() + ext).lower()


def drop_copy_permissions(accesses):
    """Copying a file also copies its ACL, which logs a PERMISSIONS access on the new file."""
    written = [a for a in accesses if a["action"] in ("WRITE", "COPY")]

    def is_side_effect(p):
        return p["action"] == "PERMISSIONS" and any(
            w["user"].lower() == p["user"].lower()
            and w["path"].lower() == p["path"].lower()
            and abs((w["time"] - p["time"]).total_seconds()) <= COPY_WINDOW_SECONDS
            for w in written
        )

    return [a for a in accesses if not is_side_effect(a)]


def detect_copies(accesses):
    reads = [a for a in accesses if a["action"] == "READ"]
    for w in accesses:
        if w["action"] != "WRITE":
            continue
        key = base_name_key(w["path"])
        for r in reads:
            if (
                r["user"].lower() == w["user"].lower()
                and r["path"].lower() != w["path"].lower()
                and base_name_key(r["path"]) == key
                and abs((w["time"] - r["time"]).total_seconds()) <= COPY_WINDOW_SECONDS
            ):
                w["action"] = "COPY"
                w["copiedFrom"] = r["path"]
                break


def append_log(accesses):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_HEADER)
        for a in accesses:
            writer.writerow([
                a["time"].strftime("%Y-%m-%d %H:%M:%S"), a["user"], a["action"], a["path"],
                a["copiedFrom"], a["clientIp"], a["process"], a["count"], a["eventId"], a["recordId"],
            ])


def write_dashboard_json():
    """Writes the last-N-days snapshot and the live db doc body; returns the recent count."""
    rows = []
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, "r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "time": row["Time"],
                    "user": row["User"],
                    "action": row["Action"],
                    "path": row["FilePath"],
                    "copiedFrom": row["CopiedFrom"],
                    "clientIp": row["ClientIP"],
                    "process": row["Process"],
                    "count": int(row["Count"] or 1),
                })
    rows.sort(key=lambda r: r["time"], reverse=True)

    cutoff = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    recent = [r for r in rows if r["time"] >= cutoff]
    with open(RECENT_JSON, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=2)

    live = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalRecorded": len(rows),
        "events": rows[:LIVE_MAX_EVENTS],
    }
    with open(LIVE_JSON, "w", encoding="utf-8") as f:
        json.dump(live, f, ensure_ascii=False)
    return len(recent)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def collect_once(evtx_path=None):
    state = load_state()
    state_key = os.path.abspath(evtx_path) if evtx_path else (SERVER or "local")
    last_id = state.get(state_key, 0)

    accesses = []
    fetched = 0
    while True:
        events = fetch_events(last_id, evtx_path)
        for xml_text in events:
            record_id, access = parse_event(xml_text)
            last_id = max(last_id, record_id)
            if access:
                accesses.append(access)
        fetched += len(events)
        if len(events) < BATCH_SIZE:
            break

    accesses = merge_repeats(accesses)
    detect_copies(accesses)
    accesses = drop_copy_permissions(accesses)
    if accesses:
        append_log(accesses)
    state[state_key] = last_id
    save_state(state)
    recent = write_dashboard_json()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {fetched} audit events read, {len(accesses)} file accesses logged "
          f"(last record {last_id}); {recent} in the last {RECENT_DAYS} days.")
    for a in accesses[-20:]:
        extra = f"  <- {a['copiedFrom']}" if a["copiedFrom"] else ""
        print(f"  {a['time']:%Y-%m-%d %H:%M:%S}  {a['action']:<11} {a['user']:<24} {a['path']}{extra}")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Collect Windows file-access audit events for the TÜRKAK folder.")
    parser.add_argument("--watch", action="store_true", help=f"keep polling every {POLL_INTERVAL_SECONDS}s")
    parser.add_argument("--evtx", help="read an exported Security .evtx file instead of the live server log")
    args = parser.parse_args()

    if not args.watch:
        try:
            collect_once(args.evtx)
        except RuntimeError as e:
            raise SystemExit(f"Collection failed: {e}")
        return

    print(f"Collecting from {args.evtx or SERVER or 'this PC'} every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.")
    try:
        while True:
            try:
                collect_once(args.evtx)
            except RuntimeError as e:
                print(f"Collection failed: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
