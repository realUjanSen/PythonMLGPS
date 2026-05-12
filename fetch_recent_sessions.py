#!/usr/bin/env python3
"""
Fetch only the 2 most recent sessions from phone.
"""
import argparse
import subprocess
import sqlite3
import json
import csv
import os
import tempfile
from datetime import datetime

PACKAGE_NAME = "com.example.shuttleestimator"
DB_BASENAME = "commute_tracker.db"
CSV_FOLDER = "csv"

def run_command(command, capture_output=True, text=True):
    """Run a command as list args for safer quoting."""
    return subprocess.run(command, capture_output=capture_output, text=text)

def get_online_adb_device_serial():
    """Return the first online adb device serial, or None if none are online."""
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]

    return None

def dump_file_with_run_as(remote_rel_path, local_path, serial=None):
    """Dump a private app file via adb exec-out + run-as."""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["exec-out", "run-as", PACKAGE_NAME, "cat", remote_rel_path])

    with open(local_path, "wb") as output:
        result = subprocess.run(
            cmd,
            stdout=output,
            stderr=subprocess.PIPE,
            text=False,
        )
    stderr_text = result.stderr.decode(errors="ignore").strip() if result.stderr else ""
    return result.returncode == 0, stderr_text

def pull_database(tmpdir, serial=None):
    """Pull DB with run-as including WAL files."""
    db_path_local = os.path.join(tmpdir, DB_BASENAME)
    
    print("[*] Pulling database from device...")
    dumped_main, main_err = dump_file_with_run_as(f"databases/{DB_BASENAME}", db_path_local, serial)
    if not dumped_main:
        print(f"[!] Failed to pull database: {main_err or 'no stderr returned'}")
        return None

    wal_ok, wal_err = dump_file_with_run_as(f"databases/{DB_BASENAME}-wal", db_path_local + "-wal", serial)
    if not wal_ok and wal_err:
        print(f"[!] WAL pull failed: {wal_err}")

    shm_ok, shm_err = dump_file_with_run_as(f"databases/{DB_BASENAME}-shm", db_path_local + "-shm", serial)
    if not shm_ok and shm_err:
        print(f"[!] SHM pull failed: {shm_err}")
    
    print(f"[+] Database pulled successfully")
    return db_path_local

def export_recent_sessions(conn, limit=2, after_session_id=None):
    """Export sessions by either recency limit or session-id lower bound."""
    cursor = conn.cursor()

    if after_session_id is not None:
        cursor.execute(
            """
            SELECT s.id, s.direction, s.class_label, s.polling_ms, s.start_time, s.end_time
            FROM sessions s
            WHERE s.id > ?
            ORDER BY s.id ASC
            """,
            (after_session_id,),
        )
    else:
        cursor.execute(
            """
            SELECT s.id, s.direction, s.class_label, s.polling_ms, s.start_time, s.end_time
            FROM sessions s
            ORDER BY s.start_time DESC
            LIMIT ?
            """,
            (limit,),
        )
    
    sessions = cursor.fetchall()
    
    for session_id, direction, class_label, polling_ms, start_time, end_time in sessions:
        cursor.execute("""
            SELECT timestamp, latitude, longitude, accuracy, speed, bearing, altitude,
                   satellite_name, satellite_country
            FROM location_points
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        
        points = cursor.fetchall()
        
        if not points:
            continue
        
        dt = datetime.fromtimestamp(start_time / 1000)
        safe_direction = direction.replace(" -> ", "_to_").replace("<", "").replace(">", "")
        csv_filename = f"session_{session_id:03d}_{dt.strftime('%Y%m%d_%H%M%S')}_{safe_direction}.csv"
        csv_path = os.path.join(CSV_FOLDER, csv_filename)
        
        os.makedirs(CSV_FOLDER, exist_ok=True)
        
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Latitude", "Longitude", "Accuracy(m)", "Speed(m/s)", 
                            "Bearing(°)", "Altitude(m)", "Satellite", "Country"])
            for pt in points:
                dt_str = datetime.fromtimestamp(pt[0] / 1000).isoformat()
                writer.writerow([dt_str] + list(pt[1:]))
        
        print(f"  Session #{session_id}: {len(points)} points → {csv_filename}")
    
    return len(sessions)

def main():
    parser = argparse.ArgumentParser(description="Fetch and export ShuttleEstimator sessions from device")
    parser.add_argument("--limit", type=int, default=2, help="How many latest sessions to fetch (default: 2)")
    parser.add_argument("--after", type=int, default=None, help="Fetch sessions with id > this value")
    parser.add_argument("--serial", type=str, default=None, help="ADB device serial (optional)")
    args = parser.parse_args()

    serial = args.serial or get_online_adb_device_serial()
    if not serial:
        print("[!] No online adb device found. Run `adb devices` and make sure one device is in `device` state.")
        return

    if args.serial is None:
        print(f"[*] Using active adb device: {serial}")

    os.makedirs(CSV_FOLDER, exist_ok=True)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = pull_database(tmpdir, serial=serial)
        
        if not db_path:
            print("[!] Failed to pull database")
            return
        
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            
            cursor = conn.cursor()

            if args.after is not None:
                cursor.execute(
                    """
                    SELECT s.id, s.direction, s.start_time, COUNT(lp.id) as point_count
                    FROM sessions s
                    LEFT JOIN location_points lp ON s.id = lp.session_id
                    WHERE s.id > ?
                    GROUP BY s.id
                    ORDER BY s.id ASC
                    """,
                    (args.after,),
                )
                selected_sessions = cursor.fetchall()

                print("\n" + "="*60)
                print(f"SESSIONS WITH ID > {args.after}")
                print("="*60)

                if not selected_sessions:
                    print("No sessions found for this filter.")
                else:
                    for row in selected_sessions:
                        session_id, direction, start_time, point_count = row
                        dt = datetime.fromtimestamp(start_time / 1000)
                        print(
                            f"Session #{session_id}: {dt.strftime('%Y-%m-%d %H:%M:%S')} | "
                            f"{direction} | {point_count} points"
                        )

                print("\n" + "="*60)
                print(f"Fetching sessions with ID > {args.after}...")
                print("="*60)

                count = export_recent_sessions(conn, after_session_id=args.after)
            else:
                cursor.execute(
                    """
                    SELECT s.id, s.direction, s.start_time, COUNT(lp.id) as point_count
                    FROM sessions s
                    LEFT JOIN location_points lp ON s.id = lp.session_id
                    GROUP BY s.id
                    ORDER BY s.start_time DESC
                    LIMIT ?
                    """,
                    (args.limit,),
                )

                selected_sessions = cursor.fetchall()

                print("\n" + "="*60)
                print(f"LAST {args.limit} SESSIONS IN DATABASE")
                print("="*60)

                for row in selected_sessions:
                    session_id, direction, start_time, point_count = row
                    dt = datetime.fromtimestamp(start_time / 1000)
                    print(
                        f"Session #{session_id}: {dt.strftime('%Y-%m-%d %H:%M:%S')} | "
                        f"{direction} | {point_count} points"
                    )

                print("\n" + "="*60)
                print(f"Fetching these {args.limit} sessions...")
                print("="*60)

                count = export_recent_sessions(conn, limit=args.limit)
            
            print("\n" + "="*60)
            print(f"✅ DONE - {count} sessions exported to csv/")
            print("="*60)
            
            conn.close()
            
        except sqlite3.Error as e:
            print(f"[!] Database error: {e}")

if __name__ == "__main__":
    main()
