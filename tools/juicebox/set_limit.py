#!/usr/bin/env python3
"""set_limit.py -- set the JuiceBox charge-current limit once, confirm it, and exit.

The charger must already be sending its telemetry to this host; see the interim local
control procedure in docs/STATUS.md. Only one program can own UDP 8042, so stop any
running juicebox_collector.py first and restart it afterwards.

Sends a single JuiceNet command, waits for the charger to echo its sequence number,
and resends only if no acknowledgement arrives (at most 3 attempts). Each accepted
command rewrites the offline limit in the charger's EEPROM, so it never repeats a
command that has been acknowledged, and by default sends nothing if the online limit
already matches.

Whole amps only: the v07 protocol has no fractional field.

  python set_limit.py 26                # dry run: shows the command it would send
  python set_limit.py 26 --send         # online and offline limit to 26 A
  python set_limit.py 26 --offline 24 --send
"""
import argparse
import datetime
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from juicebox_collector import OneShot, parse  # noqa: E402

STATUS = {"0": "unplugged", "1": "plugged in", "2": "charging", "3": "error"}
J1772_MIN, HARD_MAX = 6, 40


def amps(v):
    n = int(v)
    if not J1772_MIN <= n <= HARD_MAX:
        raise argparse.ArgumentTypeError("must be %d-%d A (whole amps)" % (J1772_MIN, HARD_MAX))
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("amps", type=amps, help="online current limit, whole amps")
    ap.add_argument("--offline", type=amps, help="offline limit (default: same as online)")
    ap.add_argument("--bind", default="", help="local address to listen on (default: all)")
    ap.add_argument("--port", type=int, default=8042)
    ap.add_argument("--timeout", type=int, default=150, help="give up after this many seconds")
    ap.add_argument("--force", action="store_true",
                    help="send even if the online limit already matches")
    ap.add_argument("--send", action="store_true", help="actually transmit (default: dry run)")
    a = ap.parse_args()
    offline = a.offline if a.offline is not None else a.amps

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((a.bind, a.port))
    except OSError as e:
        sys.exit("cannot bind udp/%d (%s). Is juicebox_collector.py still running?" % (a.port, e))
    s.settimeout(5)
    print("listening on udp/%d for up to %d s; target online %d A, offline %d A%s"
          % (a.port, a.timeout, a.amps, offline, "" if a.send else "  [DRY RUN]"))

    o = OneShot(a.amps, offline, force=a.force)
    deadline = time.time() + a.timeout
    checked_rating = False
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        r = parse(data.decode("latin1", "replace"))
        if not r:
            continue
        f = r[2]
        cur = "%.1f A" % (int(f["A"]) / 10.0) if "A" in f else "-"
        print("[%s] %s  %s  current %s  limit %s A  ack %s"
              % (datetime.datetime.now().strftime("%H:%M:%S"), addr[0],
                 STATUS.get(f.get("S"), f.get("S", "?")), cur, f.get("M", "?"), f.get("s", "?")))
        if not checked_rating:
            checked_rating = True
            rating = int(f["m"]) if "m" in f else HARD_MAX
            if max(a.amps, offline) > rating:
                sys.exit("refusing: %d A exceeds the charger's circuit rating of %d A"
                         % (max(a.amps, offline), rating))
        cmd = o.on_frame(f)
        if cmd and not a.send:
            print("   would send: %s\nDRY RUN: add --send to transmit." % cmd)
            return 0
        if cmd:
            s.sendto(cmd.encode(), addr)
            print("   >> sent (attempt %d): %s" % (o.attempts, cmd))
        if o.state in ("done", "unchanged"):
            print("OK: " + o.describe())
            return 0
        if o.state == "failed":
            print("FAILED: " + o.describe())
            return 1
    print("TIMEOUT: no %s within %d s" % ("acknowledgement" if o.seq else "telemetry", a.timeout))
    return 1


if __name__ == "__main__":
    sys.exit(main())
