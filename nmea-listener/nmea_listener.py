#!/usr/bin/env python3
"""
NMEA 0183 Navigation Data Listener

Captures UDP-broadcast NMEA sentences from R/V navigation systems,
parses GPS position, heading, and motion data, and POSTs batches
to the pscheduler-result-archiver REST API.

Supported sentences:
  $xxGGA     — GPS fix (lat, lon, altitude, satellites, HDOP, fix quality)
               Talker IDs: GP, GN, IN, GL, GA, GB, GQ, etc.
  $xxHDT     — True heading
               Talker IDs: HE, IN, GP, GN, HC, etc.
  $PASHR     — Hemisphere/Ashtech attitude & heading (heading, roll, pitch)
  $PSXN,20   — Kongsberg Seapath MRU quality/status
  $PSXN,23   — Roll, pitch, heading, heave

Archive URLs support per-destination flush intervals to conserve
satellite bandwidth on remote links while keeping local archiving frequent.
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pynmea2
import requests
import urllib3

# --------------- Configuration ---------------

NMEA_UDP_PORT = int(os.getenv("NMEA_UDP_PORT", "13551"))
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
VESSEL_ID = os.getenv("VESSEL_ID", "rv-thompson")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "900"))
FLUSH_INTERVAL_S = float(os.getenv("FLUSH_INTERVAL_S", "300.0"))
REMOTE_FLUSH_INTERVAL_S = float(os.getenv("REMOTE_FLUSH_INTERVAL_S", "300.0"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "false").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Parse ARCHIVE_URLS: comma-separated, each optionally suffixed with @<seconds>
# Examples:
#   "https://localhost:8443/ps"                           → uses FLUSH_INTERVAL_S
#   "https://localhost:8443/ps,https://remote:8443/ps"    → both use defaults
#   "https://localhost:8443/ps@300,https://remote:8443/ps@3600"  → 5min local, 1hr remote
#
# URLs containing "localhost" or "127.0.0.1" default to FLUSH_INTERVAL_S.
# All other URLs default to REMOTE_FLUSH_INTERVAL_S.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _parse_archive_urls() -> List[Tuple[str, float]]:
    """Parse ARCHIVE_URLS into (url, flush_interval_seconds) pairs."""
    raw = os.getenv("ARCHIVE_URLS", "https://localhost:8443/ps")
    result = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "@" in entry:
            # Split on last @ to allow URLs with @ in userinfo
            idx = entry.rfind("@")
            url, interval_str = entry[:idx], entry[idx + 1:]
            try:
                interval = float(interval_str)
            except ValueError:
                url = entry  # not a valid interval, treat whole thing as URL
                interval = None
        else:
            url = entry
            interval = None

        if interval is None:
            # Auto-detect local vs remote
            is_local = any(h in url for h in _LOCAL_HOSTS)
            interval = FLUSH_INTERVAL_S if is_local else REMOTE_FLUSH_INTERVAL_S

        result.append((url, interval))
    return result


ARCHIVE_DESTINATIONS = _parse_archive_urls()

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
    """Parse GGA sentence using pynmea2 (any talker ID: GP, GN, IN, GL, etc.)."""
    try:
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
    """Parse HDT sentence using pynmea2 (any talker ID: HE, IN, GP, GN, etc.)."""
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


def parse_pashr(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse $PASHR — Hemisphere/Ashtech attitude & heading.

    Format: $PASHR,<time>,<heading>,T,<roll>,<pitch>,<heave>,
            <roll_acc>,<pitch_acc>,<head_acc>,<aiding_status>,<IMU_status>*hh
    """
    try:
        core = sentence.split("*")[0]
        fields = core.split(",")
        # fields[0]='$PASHR', fields[1]=time, fields[2]=heading, fields[3]='T',
        # fields[4]=roll, fields[5]=pitch, fields[6]=heave, ...
        if len(fields) < 7:
            return None

        nmea_time = fields[1] if len(fields) > 1 else ""
        ts_str = _nmea_timestamp_to_iso(nmea_time)

        return {
            "ts": ts_str,
            "vessel_id": VESSEL_ID,
            "heading_true": _safe_float(fields[2]),
            "roll_deg": _safe_float(fields[4]),
            "pitch_deg": _safe_float(fields[5]),
            "heave_m": _safe_float(fields[6]),
            "aux": {"sentence_type": "PASHR", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse PASHR: %s — %s", sentence.strip(), e)
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


def _sentence_type(s: str) -> str:
    """Extract the 3-letter sentence type from an NMEA sentence.

    Standard NMEA: $XXYYY where XX=talker, YYY=sentence type → returns 'YYY'
    Proprietary:   $Pxxx → returns the full tag up to comma/asterisk
    """
    if len(s) < 6 or s[0] != "$":
        return ""
    # Proprietary sentences start with $P
    if s[1] == "P":
        end = min(
            s.index(",") if "," in s else len(s),
            s.index("*") if "*" in s else len(s),
        )
        return s[1:end]  # e.g. "PASHR", "PSXN"
    # Standard: talker is chars [1:3], sentence type is chars [3:6]
    return s[3:6]


def parse_sentence(sentence: str) -> Optional[Dict[str, Any]]:
    """Route an NMEA sentence to the appropriate parser."""
    s = sentence.strip()
    if not s:
        return None

    stype = _sentence_type(s)

    if stype == "GGA":
        return parse_gga(s)
    elif stype == "HDT":
        return parse_hdt(s)
    elif stype == "PASHR":
        return parse_pashr(s)
    elif s.startswith("$PSXN,20"):
        return parse_psxn20(s)
    elif s.startswith("$PSXN,23"):
        return parse_psxn23(s)

    return None


# --------------- Per-Destination Flushing ---------------


def _merge_batch(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge points with the same (ts, vessel_id) to avoid duplicate-key errors."""
    merged: Dict[tuple, Dict[str, Any]] = {}
    for pt in points:
        key = (pt.get("ts"), pt.get("vessel_id"))
        if key not in merged:
            merged[key] = dict(pt)
        else:
            existing = merged[key]
            for k, v in pt.items():
                if k == "aux":
                    old_aux = existing.get("aux") or {}
                    new_aux = v or {}
                    existing["aux"] = {**old_aux, **new_aux}
                elif v is not None:
                    existing[k] = v
    return list(merged.values())


class DestinationFlusher:
    """Manages an independent buffer and flush schedule for a single archive URL."""

    def __init__(self, url: str, interval: float, auth_token: str):
        self.url = url
        self.interval = interval
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
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

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = _merge_batch(self._buffer[:])
            self._buffer.clear()

        # POST outside the lock
        endpoint = f"{self.url.rstrip('/')}/measurements/nav"
        payload = json.dumps({"points": batch})
        try:
            resp = self._session.post(
                endpoint,
                data=payload,
                timeout=30.0,
                verify=VERIFY_TLS,
            )
            if resp.status_code < 300:
                logger.info(
                    "Flushed %d points to %s (HTTP %d)",
                    len(batch), endpoint, resp.status_code,
                )
            else:
                logger.warning(
                    "POST %s returned HTTP %d: %s",
                    endpoint, resp.status_code, resp.text[:200],
                )
        except Exception as e:
            logger.error("Failed to POST to %s: %s", endpoint, e)

    @property
    def buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)


class BatchFlusher:
    """Dispatches parsed points to per-destination flushers with independent schedules."""

    def __init__(self, destinations: List[Tuple[str, float]], auth_token: str):
        self._flushers = [
            DestinationFlusher(url, interval, auth_token)
            for url, interval in destinations
        ]

    def add(self, point: Dict[str, Any]) -> None:
        for f in self._flushers:
            f.add(point)

    def start_timers(self) -> None:
        for f in self._flushers:
            t = threading.Thread(
                target=self._flush_loop,
                args=(f,),
                daemon=True,
            )
            t.start()

    @staticmethod
    def _flush_loop(flusher: DestinationFlusher) -> None:
        while True:
            time.sleep(flusher.interval)
            try:
                flusher.flush()
            except Exception:
                logger.exception("Error flushing to %s", flusher.url)

    @property
    def buffer_sizes(self) -> Dict[str, int]:
        return {f.url: f.buffer_size for f in self._flushers}


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
    for url, interval in ARCHIVE_DESTINATIONS:
        logger.info("Archive: %s  (flush every %.0fs)", url, interval)
    logger.info("Batch size limit: %d", BATCH_SIZE)

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            text = data.decode("ascii", errors="replace")
            logger.debug("Received %d bytes from %s", len(data), addr)
            # A single datagram may contain multiple NMEA sentences
            for line in text.splitlines():
                point = parse_sentence(line)
                if point:
                    logger.debug("Parsed %s point from: %s", point.get("aux", {}).get("sentence_type", "?"), line.strip()[:80])
                    flusher.add(point)
        except Exception:
            logger.exception("Error receiving UDP datagram")


# --------------- Main ---------------


def main():
    if not AUTH_TOKEN:
        logger.warning("AUTH_TOKEN is not set — requests will be unauthenticated")
    if not ARCHIVE_DESTINATIONS:
        logger.error("ARCHIVE_URLS is not set — nowhere to send data")
        return

    flusher = BatchFlusher(ARCHIVE_DESTINATIONS, AUTH_TOKEN)
    flusher.start_timers()

    # Block on UDP listener
    listen_udp(NMEA_UDP_PORT, flusher)


if __name__ == "__main__":
    main()
