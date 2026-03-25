#!/usr/bin/env python3
"""
NMEA 0183 Navigation Data Listener

Captures UDP-broadcast NMEA sentences from R/V navigation systems,
parses GPS position, heading, and motion data, and POSTs batches
to the pscheduler-result-archiver REST API.

Supported sentences:
  $INGGA     — GPS fix (lat, lon, altitude, satellites, HDOP, fix quality)
  $INHDT     — True heading
  $PSXN,20   — Kongsberg Seapath MRU quality/status
  $PSXN,23   — Roll, pitch, heading, heave
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pynmea2
import requests
import urllib3

# --------------- Configuration ---------------

NMEA_UDP_PORT = int(os.getenv("NMEA_UDP_PORT", "13551"))
ARCHIVE_URLS = [u.strip() for u in os.getenv("ARCHIVE_URLS", "https://localhost:8443/ps").split(",") if u.strip()]
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
VESSEL_ID = os.getenv("VESSEL_ID", "rv-thompson")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
FLUSH_INTERVAL_S = float(os.getenv("FLUSH_INTERVAL_S", "5.0"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "false").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nmea_listener")

if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --------------- NMEA Parsing ---------------


def _nmea_timestamp_to_iso(nmea_time: str, nmea_date: Optional[str] = None) -> str:
    """Convert NMEA time (HHMMSS.ss) + optional date (DDMMYY) to ISO 8601 UTC."""
    if not nmea_time:
        return datetime.now(timezone.utc).isoformat()
    try:
        h, m = int(nmea_time[0:2]), int(nmea_time[2:4])
        s = float(nmea_time[4:])
        sec = int(s)
        usec = int((s - sec) * 1_000_000)

        if nmea_date and len(nmea_date) >= 6:
            day, mon, yr = int(nmea_date[0:2]), int(nmea_date[2:4]), int(nmea_date[4:6])
            yr += 2000 if yr < 80 else 1900
        else:
            now = datetime.now(timezone.utc)
            day, mon, yr = now.day, now.month, now.year

        dt = datetime(yr, mon, day, h, m, sec, usec, tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_gga(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse $INGGA (GGA) sentence using pynmea2."""
    try:
        # pynmea2 expects the talker to be 2 chars; IN is valid
        msg = pynmea2.parse(sentence)
        if not isinstance(msg, pynmea2.GGA):
            return None

        ts_str = _nmea_timestamp_to_iso(msg.timestamp.strftime("%H%M%S.%f") if hasattr(msg.timestamp, 'strftime') else str(msg.data[0]))

        return {
            "ts": ts_str,
            "vessel_id": VESSEL_ID,
            "latitude": msg.latitude if msg.latitude else None,
            "longitude": msg.longitude if msg.longitude else None,
            "altitude_m": _safe_float(msg.altitude),
            "fix_quality": _safe_int(msg.gps_qual),
            "num_satellites": _safe_int(msg.num_sats),
            "hdop": _safe_float(msg.horizontal_dil),
            "aux": {"sentence_type": "GGA", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse GGA: %s — %s", sentence.strip(), e)
        return None


def parse_hdt(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse $INHDT (HDT) sentence using pynmea2."""
    try:
        msg = pynmea2.parse(sentence)
        heading = _safe_float(msg.data[0]) if msg.data else None
        if heading is None:
            return None

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "heading_true": heading,
            "aux": {"sentence_type": "HDT", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse HDT: %s — %s", sentence.strip(), e)
        return None


def parse_psxn20(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse $PSXN,20 — Kongsberg Seapath MRU quality/status.

    Format: $PSXN,20,<horiz_qual>,<hgt_qual>,<head_qual>,<rp_qual>*hh
    """
    try:
        # Strip checksum
        core = sentence.split("*")[0]
        fields = core.split(",")
        # fields[0]='$PSXN', fields[1]='20', fields[2..5] = quality codes
        if len(fields) < 6:
            return None

        motion_status = _safe_int(fields[5])  # roll/pitch quality (0=normal)

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "motion_status": motion_status,
            "aux": {
                "sentence_type": "PSXN20",
                "horiz_qual": _safe_int(fields[2]),
                "hgt_qual": _safe_int(fields[3]),
                "head_qual": _safe_int(fields[4]),
                "rp_qual": _safe_int(fields[5]),
                "raw": sentence.strip(),
            },
        }
    except Exception as e:
        logger.debug("Failed to parse PSXN,20: %s — %s", sentence.strip(), e)
        return None


def parse_psxn23(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse $PSXN,23 — Roll, pitch, heading, heave.

    Format: $PSXN,23,<roll>,<pitch>,<heading>,<heave>*hh
    """
    try:
        core = sentence.split("*")[0]
        fields = core.split(",")
        # fields[0]='$PSXN', fields[1]='23', fields[2..5] = roll, pitch, heading, heave
        if len(fields) < 6:
            return None

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "roll_deg": _safe_float(fields[2]),
            "pitch_deg": _safe_float(fields[3]),
            "heading_true": _safe_float(fields[4]),
            "heave_m": _safe_float(fields[5]),
            "aux": {"sentence_type": "PSXN23", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse PSXN,23: %s — %s", sentence.strip(), e)
        return None


def parse_sentence(sentence: str) -> Optional[Dict[str, Any]]:
    """Route an NMEA sentence to the appropriate parser."""
    s = sentence.strip()
    if not s:
        return None

    if s.startswith("$INGGA") or s.startswith("$GPGGA"):
        return parse_gga(s)
    elif s.startswith("$INHDT") or s.startswith("$GPHDT"):
        return parse_hdt(s)
    elif s.startswith("$PSXN,20"):
        return parse_psxn20(s)
    elif s.startswith("$PSXN,23"):
        return parse_psxn23(s)

    return None


# --------------- Batch Flushing ---------------


class BatchFlusher:
    """Thread-safe buffer that flushes to archiver endpoints."""

    def __init__(self, archive_urls: List[str], auth_token: str):
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._archive_urls = archive_urls
        self._auth_token = auth_token
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nmea-listener/1.0.0",
        })
        if auth_token:
            self._session.headers["Authorization"] = f"Bearer {auth_token}"

    def add(self, point: Dict[str, Any]) -> None:
        with self._lock:
            self._buffer.append(point)
            if len(self._buffer) >= BATCH_SIZE:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buffer:
            return

        batch = self._buffer[:]
        self._buffer.clear()

        payload = json.dumps({"points": batch})
        for url in self._archive_urls:
            endpoint = f"{url.rstrip('/')}/measurements/nav"
            try:
                resp = self._session.post(
                    endpoint,
                    data=payload,
                    timeout=10.0,
                    verify=VERIFY_TLS,
                )
                if resp.status_code < 300:
                    logger.info("Flushed %d points to %s (HTTP %d)", len(batch), endpoint, resp.status_code)
                else:
                    logger.warning("POST %s returned HTTP %d: %s", endpoint, resp.status_code, resp.text[:200])
            except Exception as e:
                logger.error("Failed to POST to %s: %s", endpoint, e)

    @property
    def buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)


def flush_timer(flusher: BatchFlusher, interval: float) -> None:
    """Daemon thread that flushes the buffer periodically."""
    while True:
        time.sleep(interval)
        try:
            flusher.flush()
        except Exception:
            logger.exception("Error in flush timer")


# --------------- UDP Listener ---------------


def listen_udp(port: int, flusher: BatchFlusher) -> None:
    """Main loop: receive UDP datagrams and parse NMEA sentences."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # SO_REUSEPORT not available on all platforms
    sock.bind(("", port))

    logger.info("Listening for NMEA sentences on UDP port %d", port)
    logger.info("Vessel ID: %s", VESSEL_ID)
    logger.info("Archive URLs: %s", ", ".join(ARCHIVE_URLS))
    logger.info("Batch size: %d, Flush interval: %.1fs", BATCH_SIZE, FLUSH_INTERVAL_S)

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            text = data.decode("ascii", errors="replace")
            # A single datagram may contain multiple NMEA sentences
            for line in text.splitlines():
                point = parse_sentence(line)
                if point:
                    flusher.add(point)
        except Exception:
            logger.exception("Error receiving UDP datagram")


# --------------- Main ---------------


def main():
    if not AUTH_TOKEN:
        logger.warning("AUTH_TOKEN is not set — requests will be unauthenticated")
    if not ARCHIVE_URLS:
        logger.error("ARCHIVE_URLS is not set — nowhere to send data")
        return

    flusher = BatchFlusher(ARCHIVE_URLS, AUTH_TOKEN)

    # Start periodic flush thread
    timer = threading.Thread(
        target=flush_timer, args=(flusher, FLUSH_INTERVAL_S), daemon=True
    )
    timer.start()

    # Block on UDP listener
    listen_udp(NMEA_UDP_PORT, flusher)


if __name__ == "__main__":
    main()
