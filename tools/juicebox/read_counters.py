#!/usr/bin/env python3
"""read_counters.py -- read-only snapshot of the JuiceBox's module state and energy logs.

Talks only to the WiFi module's web interface on port 80. Sends no commands to the
charging controller and changes nothing. Requests go out one at a time, a second
apart: the module shares a single command parser with its serial link to the charging
controller, so bursts can delay the controller's own traffic.

Decodes the three ZentriOS log-file families on the module's flash (format in
docs/juicebox/JuiceNet-Protocol.md):
  ELife_N                  lifetime watt-hours, 20-slot ring; the suffix rotates
  ECache_03_<day>Z-01-01   5-minute watt-hour buckets, 48 h per file, UTC
  Events_03_<day>Z-01-01   plug, session and end-of-session energy events

  python read_counters.py
  python read_counters.py --host 192.168.1.63
"""
import argparse
import datetime
import json
import re
import struct
import time
import urllib.request

UTC = datetime.timezone.utc
EVENTS = {0x40: "EV connect", 0x41: "EV disconnect", 0x42: "session start",
          0x43: "session end", 0x80: "0x80", 0x81: "0x81"}


class Module:
    def __init__(self, host):
        self.base = "http://%s" % host

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as r:
            body = r.read()
        time.sleep(1.0)
        return body

    def command(self, cmd):
        return json.loads(self._get("/command/" + cmd.replace(" ", "%20")))["response"]

    def file(self, name):
        return self._get("/" + name)


def slots(b):
    """ZentriOS log file: u16 LE header (low 15 bits length, MSb clear = valid), payload."""
    out, o = [], 0
    while o + 2 <= len(b):
        h = struct.unpack_from("<H", b, o)[0]
        if h == 0xFFFF:
            break
        n = h & 0x7FFF
        p = b[o + 2:o + 2 + n]
        if len(p) < n:
            break
        out.append(((h & 0x8000) == 0, p))
        o += 2 + n
    return out


def ts(t):
    return datetime.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M UTC")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="192.168.1.63", help="the JuiceBox's IP address")
    a = ap.parse_args()
    m = Module(a.host)

    rtc = int(m.command("get time.rtc").strip())
    up = int(m.command("get time.uptime").strip())
    boot = rtc - up
    faults = [l for l in m.command("faults_print").splitlines() if "Exception" in l]
    print("device clock : %s" % ts(rtc))
    print("last boot    : %s  (uptime %.2f h)" % (ts(boot), up / 3600))
    print("module faults: %d of 8 (Safe Mode at 8)" % len(faults))
    for l in faults:
        print("   " + l.strip())

    names = re.findall(r"(ELife_\d+|ECache_03_[0-9a-f]+Z-01-01|Events_03_[0-9a-f]+Z-01-01)",
                       m.command("ls"))
    day = rtc // 86400
    bucket = "%05x" % (day - day % 2)

    for n in sorted({x for x in names if x.startswith("ELife")}):
        v = [struct.unpack("<I", p)[0] for ok, p in slots(m.file(n)) if ok and len(p) == 4]
        if v:
            print("%-8s slots %2d/20  lifetime %d Wh (%.2f kWh)" % (n, len(v), v[-1], v[-1] / 1000))

    start = int(bucket, 16) * 86400
    samples = []
    for ok, p in slots(m.file("ECache_03_%sZ-01-01" % bucket)):
        if ok and len(p) == 6:
            samples += [struct.unpack_from("<H", p, k * 2)[0] for k in range(3)]
    print("\nECache 0x%s: %d samples, last ends %s" % (bucket, len(samples), ts(start + len(samples) * 300)))
    runs, cur = [], None
    for i, wh in enumerate(samples):
        if wh in (0, 0xFFFF):
            continue
        if cur and i == cur["last"] + 1:
            cur["last"] = i
            cur["wh"] += wh
            cur["peak"] = max(cur["peak"], wh)
        else:
            cur = {"first": i, "last": i, "wh": wh, "peak": wh}
            runs.append(cur)
    for r in runs:
        a0, z0 = start + r["first"] * 300, start + (r["last"] + 1) * 300
        print("  %s .. %s  %6d Wh  peak %3d Wh/5 min = %5d W  (%s reboot)"
              % (ts(a0)[:16], ts(z0)[11:16], r["wh"], r["peak"], r["peak"] * 12,
                 "after" if z0 > boot else "before"))

    ev = slots(m.file("Events_03_%sZ-01-01" % bucket))
    print("\nEvents 0x%s: %d records" % (bucket, len(ev)))
    for i, (ok, p) in enumerate(ev):
        if ok and len(p) == 16 and p[11] in (0x40, 0x41, 0x42, 0x43):
            wh = struct.unpack_from(">I", p, 0)[0]
            print("  #%-3d %-14s%s" % (i, EVENTS[p[11]], ("  %d Wh" % wh) if p[11] == 0x43 else ""))


if __name__ == "__main__":
    main()
