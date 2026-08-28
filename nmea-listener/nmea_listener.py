#!/usr/bin/env python3
"""
NMEA 0183 Navigation Data Listener

Captures UDP-broadcast NMEA sentences from R/V navigation systems,
parses GPS position, heading, and motion data, and POSTs batches
to the pscheduler-result-archiver REST API.

Listens on one or more UDP ports (NMEA_UDP_PORTS, comma-separated) —
some vessels broadcast every sentence on a single port, others use a
separate port per feed. All ports feed one shared batch pipeline;
sentences are routed by type, not by port.

Supported sentences:
  $xxGGA     — GPS fix (lat, lon, altitude, satellites, HDOP, fix quality)
               Talker IDs: GP, GN, IN, GL, GA, GB, GQ, etc.
  $xxHDT     — True heading
               Talker IDs: HE, IN, GP, GN, HC, MG, etc.
  $PASHR     — Hemisphere/Ashtech attitude & heading (heading, roll, pitch)
  $PSXN,20   — Kongsberg Seapath MRU quality/status
  $PSXN,23   — Roll, pitch, heading, heave
  $RELWS     — Relative wind speed and direction
  $RELWD     — True wind speed and direction
  $xxXDR     — Transducer measurements: PRESS (bar → hPa), RH (%), TEMP (→ aux)
  (bare)     — Barometric pressure (hPa) and relative humidity (%),
               detected as trailing bare numbers after $RELWD
  <STX>...   — Gill anemometer polar format: \x02<node>,<dir>,<speed>,<units>,
               <status>,\x03<checksum> (relative wind)

Lines may be wrapped in an SCS-style prefix (R/V Sikuliaq):
    <feed_label> <TAB> <ISO-8601 timestamp> <TAB> <sentence>
The wrapper timestamp is used for sentences that carry no time of their own,
and the feed label is recorded in aux.

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

# Comma-separated list of UDP ports to listen on. Some vessels broadcast all
# sentences on one port (R/V Thompson: 13551); others use one port per feed
# (R/V Sikuliaq: GGA on 52119, HDT/PSXN on 53122, wind on 53124,
# pressure/humidity on 53118). Falls back to legacy NMEA_UDP_PORT.
NMEA_UDP_PORTS = os.getenv("NMEA_UDP_PORTS", os.getenv("NMEA_UDP_PORT", "13551"))
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
VESSEL_ID = os.getenv("VESSEL_ID", "rv-thompson")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "65000"))
FLUSH_INTERVAL_S = float(os.getenv("FLUSH_INTERVAL_S", "300.0"))
REMOTE_FLUSH_INTERVAL_S = float(os.getenv("REMOTE_FLUSH_INTERVAL_S", "21600.0"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "false").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Archiver accepts max 1000 points per request; chunk large flushes
_MAX_POINTS_PER_REQUEST = 1000

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


def _parse_ports() -> List[int]:
    """Parse NMEA_UDP_PORTS into a deduplicated list of ports (order preserved)."""
    ports: List[int] = []
    for entry in NMEA_UDP_PORTS.split(","):
        entry = entry.strip()
        if not entry:
            continue
        port = int(entry)  # fail fast on a bad config
        if port not in ports:
            ports.append(port)
    return ports


ARCHIVE_DESTINATIONS = _parse_archive_urls()
LISTEN_PORTS = _parse_ports()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nmea_listener")

if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --------------- NMEA Parsing ---------------

# Sentence types seen but not parsed — logged once per type so an operator
# can spot unsupported feeds (e.g. a vessel using $WIMWV instead of $RELWS)
# without drowning the log.
_unseen_lock = threading.Lock()
_unknown_types_seen: set = set()


def _log_unknown_sentence(sentence: str) -> None:
    stype = _sentence_type(sentence) or sentence[:10]
    with _unseen_lock:
        if stype in _unknown_types_seen:
            return
        _unknown_types_seen.add(stype)
    logger.info("Unrecognized sentence type %r (sample: %s)", stype, sentence[:120])


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


def _parse_iso_ts(text: str) -> Optional[str]:
    """Validate/normalize an ISO 8601 timestamp string (e.g. from an SCS wrapper).

    Returns a normalized ISO string, or None if the text isn't a timestamp.
    Handles a trailing 'Z' and fractional seconds of any width.
    """
    t = text.strip()
    if len(t) < 19 or t[4] != "-" or t[10] not in ("T", " "):
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t).isoformat()
    except ValueError:
        pass
    # Older Pythons only accept 3 or 6 fractional digits — pad/truncate and retry
    try:
        if "." in t:
            base, frac = t.split(".", 1)
            tz = ""
            for sep in ("+", "-"):
                if sep in frac:
                    frac, tz = frac.split(sep, 1)
                    tz = sep + tz
                    break
            t = f"{base}.{frac[:6].ljust(6, '0')}{tz}"
        return datetime.fromisoformat(t).isoformat()
    except ValueError:
        return None


def _split_scs_wrapper(line: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split an SCS-style wrapped line into (payload, ts_iso, feed_label).

    SCS broadcasts (e.g. R/V Sikuliaq) prefix each sentence with a feed label
    and receipt timestamp, tab-separated:
        gyro_mgc_1<TAB>2026-08-28T18:15:00.7679Z<TAB>$MGHDT,337.32,T*1E
    Unwrapped lines are returned as-is with (line, None, None).
    """
    parts = line.split("\t")
    if len(parts) >= 3:
        ts = _parse_iso_ts(parts[1])
        if ts:
            return "\t".join(parts[2:]), ts, parts[0].strip()
    return line, None, None


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


def parse_hdt(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse HDT sentence using pynmea2 (any talker ID: HE, IN, GP, GN, MG, etc.)."""
    try:
        msg = pynmea2.parse(sentence)
        heading = _safe_float(msg.data[0]) if msg.data else None
        if heading is None:
            return None

        return {
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
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


def parse_psxn20(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
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


def parse_psxn23(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
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


def parse_relws(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse $RELWS — Relative wind speed and direction.

    Format: $RELWS,<rel_wind_speed_kts>,<rel_wind_dir_deg>,<field3>,<field4>,
    """
    try:
        core = sentence.split("*")[0]
        fields = core.split(",")
        # fields[0]='$RELWS', fields[1]=speed, fields[2]=direction
        if len(fields) < 3:
            return None

        speed = _safe_float(fields[1])
        direction = _safe_float(fields[2])
        if speed is None and direction is None:
            return None

        return {
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "rel_wind_speed_kts": speed,
            "rel_wind_dir_deg": direction,
            "aux": {"sentence_type": "RELWS", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse RELWS: %s — %s", sentence.strip(), e)
        return None


def parse_relwd(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse $RELWD — True wind speed and direction.

    Format: $RELWD,<true_wind_speed_kts>,<true_wind_dir_deg>,<calc1>,<calc2>,<field5>,
    """
    try:
        core = sentence.split("*")[0]
        fields = core.split(",")
        # fields[0]='$RELWD', fields[1]=speed, fields[2]=direction
        if len(fields) < 3:
            return None

        speed = _safe_float(fields[1])
        direction = _safe_float(fields[2])
        if speed is None and direction is None:
            return None

        return {
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "true_wind_speed_kts": speed,
            "true_wind_dir_deg": direction,
            "aux": {"sentence_type": "RELWD", "raw": sentence.strip()},
        }
    except Exception as e:
        logger.debug("Failed to parse RELWD: %s — %s", sentence.strip(), e)
        return None


# Pressure unit → hPa conversion factors ($xxXDR PRESS group)
_PRESSURE_TO_HPA = {
    "bar": 1000.0, "b": 1000.0,       # bar (Vaisala met4a reports 'bar')
    "hpa": 1.0, "mbar": 1.0,
    "pa": 0.01, "p": 0.01,            # pascal
}


def parse_xdr(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse $xxXDR — transducer measurements (met sensor).

    Observed R/V Sikuliaq (Vaisala met4a) format, with irregular grouping:
        $WIXDR,PRESS,1.004098,bar,s/n146582,TEMP,9.80,C,RH,99.98,%RH,s/n20268816,FAN,1

    Rather than assuming standard 4-field (type,value,unit,id) groups, scan for
    known measurement tags and read the value/unit that follow each.
    PRESS → pressure_hpa, RH → humidity_pct; TEMP has no nav_data column, so it
    goes into aux only.
    """
    try:
        core = sentence.split("*")[0]
        fields = core.split(",")

        point: Dict[str, Any] = {}
        aux: Dict[str, Any] = {"sentence_type": "XDR", "raw": sentence.strip()}
        for i, field in enumerate(fields[1:-1], start=1):
            tag = field.strip().upper()
            value = _safe_float(fields[i + 1])
            unit = fields[i + 2].strip().lower() if i + 2 < len(fields) else ""
            if value is None:
                continue
            if tag == "PRESS":
                factor = _PRESSURE_TO_HPA.get(unit)
                if factor is not None:
                    point["pressure_hpa"] = round(value * factor, 4)
            elif tag == "RH":
                point["humidity_pct"] = value
            elif tag == "TEMP":
                aux["air_temp_c"] = value

        if not point and "air_temp_c" not in aux:
            return None

        point.update({
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "aux": aux,
        })
        return point
    except Exception as e:
        logger.debug("Failed to parse XDR: %s — %s", sentence.strip(), e)
        return None


# Gill anemometer speed unit → knots conversion factors
_GILL_UNITS_TO_KTS = {
    "M": 1.943844,   # m/s
    "N": 1.0,        # knots
    "K": 0.539957,   # km/h
    "P": 0.868976,   # mph
}


def parse_gill_wind(payload: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse Gill anemometer polar format (not NMEA).

    Observed R/V Sikuliaq format:
        \\x02A,284,012.44,M,60,\\x0305
    i.e. <STX><node>,<direction_deg>,<speed>,<units>,<status>,<ETX><checksum>
    Units: M=m/s, N=knots, P=mph, K=km/h. Anemometer wind is relative to the ship.
    """
    try:
        data = payload.lstrip("\x02").split("\x03")[0]
        fields = data.split(",")
        # fields[0]=node, fields[1]=direction, fields[2]=speed, fields[3]=units, fields[4]=status
        if len(fields) < 5:
            return None

        direction = _safe_float(fields[1])
        speed = _safe_float(fields[2])
        units = fields[3].strip().upper()
        if speed is not None:
            factor = _GILL_UNITS_TO_KTS.get(units)
            speed = round(speed * factor, 3) if factor is not None else None
        if speed is None and direction is None:
            return None

        return {
            "ts": default_ts or datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "rel_wind_speed_kts": speed,
            "rel_wind_dir_deg": direction,
            "aux": {
                "sentence_type": "GILL_WIND",
                "node": fields[0],
                "units": units,
                "status": fields[4],
                "raw": data,
            },
        }
    except Exception as e:
        logger.debug("Failed to parse Gill wind: %r — %s", payload.strip(), e)
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


def parse_sentence(sentence: str, default_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Route an NMEA sentence to the appropriate parser.

    default_ts (e.g. from an SCS wrapper) is used by parsers whose sentences
    carry no time of their own; GGA and PASHR keep their embedded NMEA time.
    """
    s = sentence.strip()
    if not s:
        return None

    stype = _sentence_type(s)

    if stype == "GGA":
        return parse_gga(s)
    elif stype == "HDT":
        return parse_hdt(s, default_ts)
    elif stype == "XDR":
        return parse_xdr(s, default_ts)
    elif stype == "PASHR":
        return parse_pashr(s)
    elif stype == "LWS":
        return parse_relws(s, default_ts)
    elif stype == "LWD":
        return parse_relwd(s, default_ts)
    elif s.startswith("$PSXN,20"):
        return parse_psxn20(s, default_ts)
    elif s.startswith("$PSXN,23"):
        return parse_psxn23(s, default_ts)

    return None


def parse_datagram(text: str) -> List[Dict[str, Any]]:
    """Parse all NMEA sentences and bare environmental values from a UDP datagram.

    Each line may be plain NMEA (R/V Thompson) or SCS-wrapped
    `<label>\\t<ISO ts>\\t<sentence>` (R/V Sikuliaq) — see _split_scs_wrapper.
    Gill anemometer polar lines (STX-prefixed, not NMEA) are also handled.

    Bare numeric lines after $RELWD are interpreted as barometric pressure (hPa)
    and relative humidity (%), based on the observed SCS broadcast format:
        $RELWD,...
        1016.9        ← pressure_hpa
        081.5         ← humidity_pct
    """
    lines = text.splitlines()
    points: List[Dict[str, Any]] = []
    relwd_seen = False
    bare_after_relwd: List[float] = []

    for line in lines:
        payload, wrapper_ts, feed_label = _split_scs_wrapper(line)
        stripped = payload.strip()
        if not stripped:
            continue

        if stripped.startswith("$"):
            point = parse_sentence(stripped, wrapper_ts)
            if point:
                if feed_label:
                    point.setdefault("aux", {})["feed"] = feed_label
                points.append(point)
            else:
                _log_unknown_sentence(stripped)
            if stripped.startswith("$RELWD"):
                relwd_seen = True
                bare_after_relwd = []
        elif stripped.startswith("\x02"):
            point = parse_gill_wind(stripped, wrapper_ts)
            if point:
                if feed_label:
                    point["aux"]["feed"] = feed_label
                points.append(point)
            else:
                _log_unknown_sentence(stripped)
        elif relwd_seen:
            val = _safe_float(stripped)
            if val is not None:
                bare_after_relwd.append(val)

    # Trailing bare numbers after $RELWD: pressure (hPa), then humidity (%)
    if len(bare_after_relwd) >= 2:
        points.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "vessel_id": VESSEL_ID,
            "pressure_hpa": bare_after_relwd[0],
            "humidity_pct": bare_after_relwd[1],
            "aux": {
                "sentence_type": "ENV_BARE",
                "raw": f"pressure={bare_after_relwd[0]}, humidity={bare_after_relwd[1]}",
            },
        })

    return points


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
        flush_needed = False
        with self._lock:
            self._buffer.append(point)
            if BATCH_SIZE and len(self._buffer) >= BATCH_SIZE:
                flush_needed = True
        if flush_needed:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = _merge_batch(self._buffer[:])
            self._buffer.clear()

        # POST outside the lock so add() isn't blocked during HTTP calls.
        # Chunk into ≤1000-point requests (archiver max per request).
        for i in range(0, len(batch), _MAX_POINTS_PER_REQUEST):
            chunk = batch[i:i + _MAX_POINTS_PER_REQUEST]
            self._post_batch(chunk)

    def _post_batch(self, batch: List[Dict[str, Any]]) -> None:
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
    """Per-port loop: receive UDP datagrams and parse NMEA sentences."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # SO_REUSEPORT not available on all platforms
    sock.bind(("", port))

    logger.info("Listening for NMEA sentences on UDP port %d", port)

    first_datagram = True
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            text = data.decode("ascii", errors="replace")
            if first_datagram:
                logger.info("First datagram on port %d from %s: %r", port, addr, text[:200])
                first_datagram = False
            logger.debug("Received %d bytes on port %d from %s", len(data), port, addr)
            # Parse entire datagram (handles both $-prefixed sentences and bare values)
            for point in parse_datagram(text):
                logger.debug("Parsed %s point", point.get("aux", {}).get("sentence_type", "?"))
                flusher.add(point)
        except Exception:
            logger.exception("Error receiving UDP datagram on port %d", port)


# --------------- Main ---------------


def main():
    if not AUTH_TOKEN:
        logger.warning("AUTH_TOKEN is not set — requests will be unauthenticated")
    if not ARCHIVE_DESTINATIONS:
        logger.error("ARCHIVE_URLS is not set — nowhere to send data")
        return
    if not LISTEN_PORTS:
        logger.error("NMEA_UDP_PORTS is empty — nothing to listen on")
        return

    logger.info("Vessel ID: %s", VESSEL_ID)
    for url, interval in ARCHIVE_DESTINATIONS:
        logger.info("Archive: %s  (flush every %.0fs)", url, interval)
    logger.info("Batch size limit: %d", BATCH_SIZE)

    flusher = BatchFlusher(ARCHIVE_DESTINATIONS, AUTH_TOKEN)
    flusher.start_timers()

    # One listener thread per port, all feeding the same flusher
    threads = []
    for port in LISTEN_PORTS:
        t = threading.Thread(
            target=listen_udp,
            args=(port, flusher),
            daemon=True,
            name=f"udp-{port}",
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
