#!/usr/bin/env python3
"""
Simulate NMEA 0183 UDP broadcasts for testing the nmea-listener pipeline.

Sends realistic GGA, HDT, PSXN,20, and PSXN,23 sentences at ~1 Hz for
a configurable duration, simulating a vessel underway with gentle rolling.

Usage:
    python3 nmea_sim.py [UDP_PORT] [DURATION_S]
    python3 nmea_sim.py 13551 30

No external dependencies — uses only the Python standard library.
"""

import math
import socket
import sys
import time
from datetime import datetime, timezone

UDP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 13551
DURATION_S = int(sys.argv[2]) if len(sys.argv) > 2 else 30
BROADCAST_ADDR = "255.255.255.255"

# Simulated vessel track: start near Seattle, heading NW at ~10 knots
BASE_LAT = 47.6062    # degrees N
BASE_LON = -122.3321  # degrees W
HEADING_DEG = 315.0   # NW
SPEED_KTS = 10.0
ALTITUDE_M = 12.5


def nmea_checksum(sentence: str) -> str:
    """Compute NMEA XOR checksum for content between $ and *."""
    body = sentence.split("$", 1)[1] if "$" in sentence else sentence
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"{cs:02X}"


def make_gga(lat, lon, alt, utc_now):
    """Build $INGGA sentence."""
    ts = utc_now.strftime("%H%M%S.00")
    lat_abs = abs(lat)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60.0
    ns = "N" if lat >= 0 else "S"
    lon_abs = abs(lon)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60.0
    ew = "E" if lon >= 0 else "W"
    body = f"INGGA,{ts},{lat_deg:02d}{lat_min:07.4f},{ns},{lon_deg:03d}{lon_min:07.4f},{ew},1,09,0.9,{alt:.1f},M,0.0,M,,"
    return f"${body}*{nmea_checksum(body)}"


def make_hdt(heading):
    """Build $INHDT sentence."""
    body = f"INHDT,{heading:.1f},T"
    return f"${body}*{nmea_checksum(body)}"


def make_psxn20(horiz_q=0, hgt_q=0, head_q=0, rp_q=0):
    """Build $PSXN,20 sentence (MRU quality)."""
    body = f"PSXN,20,{horiz_q},{hgt_q},{head_q},{rp_q}"
    return f"${body}*{nmea_checksum(body)}"


def make_psxn23(roll, pitch, heading, heave):
    """Build $PSXN,23 sentence (motion)."""
    body = f"PSXN,23,{roll:.2f},{pitch:.2f},{heading:.1f},{heave:.2f}"
    return f"${body}*{nmea_checksum(body)}"


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    print(f"Sending simulated NMEA on UDP :{UDP_PORT} for {DURATION_S}s")
    start = time.time()
    tick = 0

    while (time.time() - start) < DURATION_S:
        now = datetime.now(timezone.utc)
        t = time.time() - start

        # Simulate gentle motion and slow course
        lat = BASE_LAT + (SPEED_KTS * 1852 / 3600) * t * math.cos(math.radians(HEADING_DEG)) / 111320.0
        lon = BASE_LON + (SPEED_KTS * 1852 / 3600) * t * math.sin(math.radians(HEADING_DEG)) / (111320.0 * math.cos(math.radians(BASE_LAT)))
        heading = HEADING_DEG + 2.0 * math.sin(t / 30.0)
        roll = 3.5 * math.sin(t / 8.0) + 1.2 * math.sin(t / 3.0)
        pitch = 1.5 * math.sin(t / 10.0) + 0.8 * math.cos(t / 4.5)
        heave = 0.4 * math.sin(t / 6.0) + 0.15 * math.sin(t / 2.5)

        sentences = [
            make_gga(lat, lon, ALTITUDE_M, now),
            make_hdt(heading),
            make_psxn20(0, 0, 0, 0),
            make_psxn23(roll, pitch, heading, heave),
        ]

        # Send each sentence as a separate UDP datagram (like real NMEA systems)
        for s in sentences:
            payload = (s + "\r\n").encode("ascii")
            try:
                sock.sendto(payload, (BROADCAST_ADDR, UDP_PORT))
            except OSError:
                # Fallback to localhost if broadcast fails
                sock.sendto(payload, ("127.0.0.1", UDP_PORT))

        tick += 1
        if tick % 10 == 0:
            print(f"  [{tick}s] lat={lat:.4f} lon={lon:.4f} hdg={heading:.1f} roll={roll:.1f} pitch={pitch:.1f} heave={heave:.2f}")

        time.sleep(1.0)

    sock.close()
    print(f"Done. Sent {tick} sets of NMEA sentences ({tick * 4} total datagrams).")


if __name__ == "__main__":
    main()
