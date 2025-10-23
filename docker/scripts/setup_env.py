#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

KV_KEYS = ["HOSTS", "AUTH_TOKEN", "ARCHIVE_URLS", "TZ", "CRON_EXPRESSION"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create/update a .env file with key=value pairs (no quotes), preserving other lines."
    )
    p.add_argument("env_path", type=Path, help="Path to .env (e.g., pscheduler-result-archiver/.env)")
    p.add_argument("AUTH_TOKEN", help="Bearer/auth token to write to AUTH_TOKEN")
    p.add_argument("--hosts", default="23.134.232.50@shore-STAR", help="Value for HOSTS")
    p.add_argument("--archive-urls", default="https://localhost:8443/ps,https://23.134.232.50:8443/ps",
                   help="Value for ARCHIVE_URLS")
    p.add_argument("--tz", default="UTC", dest="tz", help="Value for TZ")
    p.add_argument("--cron", default="0 */4 * * *", dest="cron", help="Value for CRON_EXPRESSION")
    return p.parse_args()


def _is_kv_line(line: str) -> bool:
    # Basic KEY=VALUE (allow leading spaces). Ignore commented lines.
    if not line.strip() or line.lstrip().startswith("#"):
        return False
    # Must contain '=' with non-empty key before '='
    if "=" not in line:
        return False
    key = line.split("=", 1)[0].strip()
    return bool(key) and not key.startswith("#")


def _get_key(line: str) -> str:
    return line.split("=", 1)[0].strip()


def _kv_line(key: str, value: str) -> str:
    # Write exactly KEY=VALUE\n with no quotes
    return f"{key}={value}\n"


def load_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return f.readlines()


def backup_file(path: Path) -> None:
    if not path.exists():
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(path.read_bytes())


def update_env_lines(lines: List[str], updates: dict) -> List[str]:
    """
    Update/insert KEY=VALUE lines while preserving other content and comments.
    - Replace first occurrence if key exists; remove any later duplicates.
    - Append missing keys at end (with newline).
    """
    # Map of first index for existing keys and list of duplicates
    first_index = {}
    dup_indices = []

    for idx, line in enumerate(lines):
        if _is_kv_line(line):
            key = _get_key(line)
            if key in first_index:
                dup_indices.append(idx)
            else:
                first_index[key] = idx

    # Remove duplicates (later occurrences)
    if dup_indices:
        lines = [ln for i, ln in enumerate(lines) if i not in set(dup_indices)]

        # Recompute first_index after filtering
        first_index.clear()
        for idx, line in enumerate(lines):
            if _is_kv_line(line):
                key = _get_key(line)
                if key not in first_index:
                    first_index[key] = idx

    # Apply updates
    for key, value in updates.items():
        if key in first_index:
            idx = first_index[key]
            lines[idx] = _kv_line(key, value)
        else:
            # Ensure file ends with a newline before appending (if not empty)
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(_kv_line(key, value))

    return lines


def main() -> int:
    args = parse_args()

    env_path: Path = args.env_path
    env_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare updates dict
    updates = {
        "HOSTS": args.hosts,
        "AUTH_TOKEN": args.AUTH_TOKEN,
        "ARCHIVE_URLS": args.archive_urls,
        "TZ": args.tz,
        "CRON_EXPRESSION": args.cron,
    }

    # Load, backup, update, write
    lines = load_lines(env_path)
    backup_file(env_path)
    new_lines = update_env_lines(lines, updates)

    with env_path.open("w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Wrote {env_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
