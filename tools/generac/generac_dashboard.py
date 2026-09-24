#!/usr/bin/env python3
"""
generac_dashboard.py -- live text dashboard for a Generac Mobile Link Tether
(Gecko OS / Silicon Labs WGM160P) on the local network.

It leverages every locally reachable "known function" of the device:

  * UDP 55555 discovery beacon  -- the only live local telemetry surface
        (IP, SSID, AP BSSID, channel, RSSI, device clock, firmware, uuid, MAC)
  * Port 2000 remote-terminal   -- advertised by the beacon; probed for state
  * Gecko OS  /command/*  HTTP   -- probed (expected: 500 "Feature not initialized")
  * mDNS / reverse name          -- used to VERIFY the discovered IP resolves
  * Cloud REST API (optional)    -- read-only status if a bearer token is present

The device IP is NEVER hard-coded: it is discovered live from the beacon and
then verified four ways (beacon source match, ARP L2 binding, name resolution,
TCP reachability) before anything is shown as trustworthy.

Every field here is grounded in the repo's reverse engineering:
  docs/ZentriOS-Gecko-LAN-Discovery.md   (beacon schema, port 2000, mDNS)
  docs/generac/Generac-MobileLink-Tether-RE.md   (locked local surface, cloud API)

Stdlib only. No admin/root required. Works on Windows, macOS, Linux.

Usage:
  python generac_dashboard.py                 # live auto-refreshing dashboard
  python generac_dashboard.py --once          # single snapshot (scroll-friendly)
  python generac_dashboard.py --all           # show every Gecko/Zentri beacon
  python generac_dashboard.py --serial 3000627313   # + read-only cloud status
                                                    #   (needs a bearer token)

Stop the live view with Ctrl-C.
"""
import argparse
import collections
import datetime
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

BEACON_PORT = 55555
DEFAULT_TERMINAL_PORT = 2000        # only a fallback; real value comes from the beacon
MDNS_ADDR = ("224.0.0.251", 5353)
CLOUD_BASE = "https://app.mobilelinkgen.com/api/v5"

MAC_RE = re.compile(r"([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}")


# --------------------------------------------------------------------------- #
# Terminal helpers (color + screen control, degrade gracefully)               #
# --------------------------------------------------------------------------- #

def _enable_vt():
    """Turn on ANSI/VT processing on the Windows console. Returns True on success."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)                     # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


VT_OK = _enable_vt()


class C:
    """ANSI palette; blanked out when color is disabled."""
    RESET = "\x1b[0m"; BOLD = "\x1b[1m"; DIM = "\x1b[2m"
    RED = "\x1b[31m"; GREEN = "\x1b[32m"; YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"; CYAN = "\x1b[36m"; GREY = "\x1b[90m"

    @classmethod
    def off(cls):
        for k in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "CYAN", "GREY"):
            setattr(cls, k, "")


def clear_screen():
    if VT_OK:
        sys.stdout.write("\x1b[H\x1b[2J")
    else:
        os.system("cls" if os.name == "nt" else "clear")


# --------------------------------------------------------------------------- #
# Beacon reception + parsing                                                    #
# --------------------------------------------------------------------------- #

def open_beacon_socket(bind_addr, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    s.bind((bind_addr, port))
    s.settimeout(1.0)
    return s


def parse_version(v):
    """Split a Gecko/Zentri banner into (app, os, module). Positional, tolerant.

    'H42069-TETHER-1.0.8, Gecko_OS-STANDARD-4.2.3-9237, WGM160P'
        -> app='H42069-TETHER-1.0.8', os='Gecko_OS-STANDARD-4.2.3-9237', module='WGM160P'
    """
    parts = [p.strip() for p in (v or "").split(",") if p.strip()]
    app = os_ = module = ""
    if parts:
        app = parts[0]
    for p in parts[1:]:
        if re.search(r"gecko|zentri|wiconnect", p, re.I):
            os_ = p
        elif re.search(r"^[A-Z]{2,}\d", p) and not os_ and "T" not in p[:4]:
            module = p
    # module is usually the last token; build-date tokens contain 'T..Z'
    if not module and len(parts) >= 3 and "Z" not in parts[-1]:
        module = parts[-1]
    return app, os_, module


class Device:
    """Rolling state for one beacon-emitting device."""
    def __init__(self, key):
        self.key = key
        self.j = {}                     # latest beacon JSON
        self.src_ip = None              # IP the datagram actually came from
        self.first_mono = time.monotonic()
        self.last_mono = self.first_mono
        self.count = 0
        self.arrivals = collections.deque(maxlen=12)
        self.first_version = None       # OTA tripwire baseline
        # cached probe results (refreshed on the slow cadence)
        self.probe = {"when": 0.0, "tcp2000": None, "http_cmd": None,
                      "arp": None, "revname": None, "reach": None}

    def update(self, j, src_ip):
        now = time.monotonic()
        self.j = j
        self.src_ip = src_ip
        self.count += 1
        self.arrivals.append(now)
        self.last_mono = now
        if self.first_version is None:
            self.first_version = j.get("version")

    # --- derived signals -------------------------------------------------- #
    @property
    def ip(self):
        return self.j.get("ip")

    @property
    def mac(self):
        return self.j.get("mac")

    @property
    def age(self):
        return time.monotonic() - self.last_mono

    @property
    def watched(self):
        return time.monotonic() - self.first_mono

    def cadence(self):
        if len(self.arrivals) < 2:
            return None
        deltas = [b - a for a, b in zip(self.arrivals, list(self.arrivals)[1:])]
        return sum(deltas) / len(deltas)

    def presence(self):
        a = self.age
        if a < 25:
            return "ONLINE", C.GREEN
        if a < 60:
            return "STALE", C.YELLOW
        return "OFFLINE", C.RED

    def ota_changed(self):
        return (self.first_version is not None
                and self.j.get("version") not in (None, self.first_version))


def norm_mac(s):
    return re.sub(r"[^0-9a-fA-F]", "", s or "").lower()


def rssi_rating(r):
    if r is None:
        return "?", C.GREY
    if r >= -50:
        return "excellent", C.GREEN
    if r >= -60:
        return "good", C.GREEN
    if r >= -67:
        return "fair", C.YELLOW
    if r >= -75:
        return "weak", C.YELLOW
    return "very weak", C.RED


def rssi_bar(r, width=16):
    if r is None:
        return " " * width
    # map -90..-40 dBm onto the bar
    frac = max(0.0, min(1.0, (r + 90) / 50.0))
    fill = int(round(frac * width))
    return "#" * fill + "." * (width - fill)


# --------------------------------------------------------------------------- #
# Verification of the discovered address (never trust a hard-coded IP)         #
# --------------------------------------------------------------------------- #

def arp_lookup(ip):
    """Return the MAC the OS ARP cache has for `ip`, or None."""
    if not ip:
        return None
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             timeout=4).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if ip in line.split():
            m = MAC_RE.search(line)
            if m:
                return m.group(0)
    return None


def reverse_name(ip):
    """Best-effort: reverse-resolve `ip` to a name. Tries the OS resolver first,
    then a Multicast-DNS reverse (PTR) query -- which is how a Gecko device that
    only speaks mDNS would answer."""
    if not ip:
        return None
    try:
        host = socket.gethostbyaddr(ip)[0]
        if host and host != ip:
            return host
    except Exception:
        pass
    return _mdns_reverse(ip)


def _mdns_reverse(ip, timeout=1.5):
    try:
        octets = ip.split(".")
        if len(octets) != 4:
            return None
        qname = ".".join(reversed(octets)) + ".in-addr.arpa"
        pkt = _mdns_build_query(qname, 12)          # 12 = PTR
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        except OSError:
            pass
        s.settimeout(timeout)
        s.sendto(pkt, MDNS_ADDR)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, _ = s.recvfrom(2048)
            except socket.timeout:
                break
            name = _mdns_first_ptr(data)
            if name:
                s.close()
                return name
        s.close()
    except Exception:
        return None
    return None


def _mdns_build_query(qname, qtype):
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)   # id 0, one question
    body = b""
    for label in qname.split("."):
        body += bytes([len(label)]) + label.encode("ascii")
    body += b"\x00"
    body += struct.pack("!HH", qtype, 0x8001)           # QU bit set -> unicast reply ok
    return header + body


def _mdns_read_name(data, off):
    labels, jumped, ret, steps = [], False, off, 0
    while off < len(data):
        n = data[off]
        if n == 0:
            off += 1
            break
        if (n & 0xC0) == 0xC0:
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            if not jumped:
                ret = off + 2
            off, jumped, steps = ptr, True, steps + 1
            if steps > 64:
                break
            continue
        off += 1
        labels.append(data[off:off + n].decode("latin1", "replace"))
        off += n
    return ".".join(labels), (ret if jumped else off)


def _mdns_first_ptr(data):
    try:
        qd, an = struct.unpack("!HH", data[4:8])
        off = 12
        for _ in range(qd):
            _, off = _mdns_read_name(data, off)
            off += 4
        for _ in range(an):
            _, off = _mdns_read_name(data, off)
            rtype, _, _, rdlen = struct.unpack("!HHIH", data[off:off + 10])
            off += 10
            if rtype == 12:                              # PTR
                name, _ = _mdns_read_name(data, off)
                return name
            off += rdlen
    except Exception:
        return None
    return None


def tcp_probe(ip, port, timeout=1.5):
    """'open' | 'refused' (host up, port closed) | 'timeout' (filtered/down) | 'error'."""
    if not ip:
        return "error"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return "open"
    except ConnectionRefusedError:
        return "refused"
    except socket.timeout:
        return "timeout"
    except OSError as e:
        if getattr(e, "errno", None) in (61, 111, 10061):
            return "refused"
        return "error"
    finally:
        s.close()


def http_probe(url, timeout=2.0):
    """Return (status_int_or_None, short_body). Used to poke the Gecko web server."""
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(160).decode("latin1", "replace").strip()
    except urllib.error.HTTPError as e:
        try:
            body = e.read(160).decode("latin1", "replace").strip()
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return None, str(e)[:80]


def refresh_probes(dev):
    """Run the (slower-cadence) active probes against the discovered IP."""
    ip = dev.ip
    port = dev.j.get("remote_terminal_port", DEFAULT_TERMINAL_PORT)
    state = tcp_probe(ip, port)                      # sent first: also forces ARP resolution
    arp = arp_lookup(ip)                             # now the cache is populated
    mac_ok = (norm_mac(arp) == norm_mac(dev.mac)) if arp else None
    if state == "open":
        # This device is supposed to be locked, so an 'open' is suspicious. Make
        # sure it is really THIS device (ARP MAC matches the beacon) and not a
        # one-off before trusting it: a different host on a stale/reused IP, or a
        # middlebox SYN-proxy, would also complete a handshake.
        if mac_ok is False:
            state = "open-other"                     # a different host answered
        elif tcp_probe(ip, port) != "open":
            state = "flap"                           # transient accept, not a stable service
    dev.probe["tcp2000"] = state
    dev.probe["arp"] = arp
    dev.probe["revname"] = reverse_name(ip)
    dev.probe["http_cmd"] = http_probe("http://%s/command/version" % ip)
    dev.probe["reach"] = state in ("open", "refused", "flap", "open-other")
    dev.probe["when"] = time.monotonic()


# --------------------------------------------------------------------------- #
# Optional read-only cloud status                                              #
# --------------------------------------------------------------------------- #

def find_token(explicit):
    if explicit:
        return explicit
    if os.environ.get("MLG_TOKEN"):
        return os.environ["MLG_TOKEN"]
    for p in ("mlg_token.txt",
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "mlg_token.txt")):
        if os.path.exists(p):
            try:
                return open(p, encoding="utf-8").read().strip().splitlines()[0]
            except Exception:
                pass
    return None


def cloud_status(token, serial):
    """Read-only cloud probe. Never writes; never prints the token."""
    def _get(path):
        req = urllib.request.Request(CLOUD_BASE + "/" + path,
                                     headers={"Authorization": "Bearer " + token,
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read(200).decode("utf-8", "replace")
        except Exception as e:
            return None, str(e)[:80]

    out = {}
    out["list"] = _get("Apparatus/list")
    if serial:
        out["isRegistered"] = _get("Apparatus/isRegistered/%s" % serial)
    return out


# --------------------------------------------------------------------------- #
# Rendering                                                                     #
# --------------------------------------------------------------------------- #

def fmt_dur(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def rule(title="", width=74):
    if not title:
        return C.GREY + "-" * width + C.RESET
    t = " %s " % title
    return C.GREY + "-- " + C.RESET + C.BOLD + title + C.RESET + " " + C.GREY + "-" * (width - len(t) - 3) + C.RESET


def kv(label, value, color="", width=16):
    return "  %-*s %s%s%s" % (width, label + ":", color, value, C.RESET if color else "")


def render(dev, cloud, args):
    L = []
    ver = dev.j.get("version", "")
    app, os_, module = parse_version(ver)
    state, scol = dev.presence()

    L.append(C.BOLD + C.CYAN + "GENERAC MOBILE LINK TETHER -- LOCAL DASHBOARD" + C.RESET
             + "   " + C.GREY + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + C.RESET)
    L.append("  %sstatus %s%s%s   beacons %d   watched %s   last beacon %.1fs ago"
             % (C.GREY, scol + C.BOLD, state, C.RESET, dev.count,
                fmt_dur(dev.watched), dev.age))
    if dev.ota_changed():
        L.append("  " + C.RED + C.BOLD + "!! FIRMWARE VERSION CHANGED SINCE START -- possible OTA push !!" + C.RESET)
    L.append("")

    # --- Identity ---------------------------------------------------------- #
    L.append(rule("IDENTITY (beacon 'version' / 'uuid' / 'mac')"))
    L.append(kv("Module", module or "?"))
    L.append(kv("Gecko OS", os_ or "?"))
    L.append(kv("App / FW", app or "?"))
    L.append(kv("Module UUID", dev.j.get("uuid", "?")))
    L.append(kv("Station MAC", dev.mac or "?"))
    L.append("")

    # --- Network / RF ------------------------------------------------------ #
    L.append(rule("NETWORK  /  RF"))
    r = dev.j.get("rssi")
    rate, rcol = rssi_rating(r)
    L.append(kv("IP (discovered)", dev.ip or "?", C.BOLD))
    L.append(kv("SSID", dev.j.get("ssid", "?")))
    L.append(kv("AP BSSID", dev.j.get("bssid", "?")))
    L.append(kv("Channel", str(dev.j.get("channel", "?"))))
    L.append(kv("RSSI", "%s dBm  [%s]  %s%s" % (r, rssi_bar(r), rcol + rate, C.RESET))
             if r is not None else kv("RSSI", "?"))
    cad = dev.cadence()
    L.append(kv("Beacon cadence", ("%.1f s" % cad) if cad else "(measuring...)"))
    L.append("")

    # --- Discovery & verification ----------------------------------------- #
    L.append(rule("DISCOVERY & IP VERIFICATION"))
    # 1) the beacon literally arrived FROM the advertised IP
    consistent = dev.src_ip and dev.ip and dev.src_ip == dev.ip
    L.append("  %s live at %s%s%s  (beacon received from %s)"
             % (_mark(consistent), C.BOLD, dev.ip or "?", C.RESET,
                dev.src_ip or "?"))
    # 2) ARP L2 binding
    arp = dev.probe.get("arp")
    arp_ok = arp is not None and norm_mac(arp) == norm_mac(dev.mac)
    if arp is None:
        L.append("  %s ARP L2 binding    (not in cache yet)" % _mark(None))
    else:
        L.append("  %s ARP L2 binding    %s  %s"
                 % (_mark(arp_ok), arp, "matches beacon MAC" if arp_ok else "MISMATCH vs beacon"))
    # 3) reverse name resolution
    rn = dev.probe.get("revname")
    L.append("  %s name resolution   %s"
             % (_mark(bool(rn)), rn if rn else "(no PTR / mDNS reverse answer)"))
    # 4) port 2000 state -- reachability is already proven by the live beacon above;
    #    a refused/filtered port is the EXPECTED locked state, not a failure.
    t2k = dev.probe.get("tcp2000")
    if t2k in ("refused", "timeout"):
        pmark = True                       # locked, as expected
    elif t2k in ("open", "open-other"):
        pmark = False                      # genuinely open (or wrong host answered)
    else:
        pmark = None                       # flap / error -- inconclusive
    L.append("  %s port %-4s state   %s"
             % (_mark(pmark),
                dev.j.get("remote_terminal_port", DEFAULT_TERMINAL_PORT), _tcp_word(t2k)))
    L.append("")

    # --- Known local functions -------------------------------------------- #
    L.append(rule("LOCAL FUNCTIONS (probed live -- expected 'locked')"))
    L.append("  %-26s %s" % ("UDP 55555 beacon",
                             C.GREEN + "ACTIVE -- telemetry above" + C.RESET))
    L.append("  %-26s %s" % ("TCP 2000 remote-terminal", _terminal_word(t2k)))
    hc = dev.probe.get("http_cmd") or (None, "")
    L.append("  %-26s %s" % ("HTTP /command/* (Gecko)", _http_word(hc)))
    L.append("  %-26s %s" % ("/Generac/api REST",
                             C.GREY + "SoftAP-only (not served on LAN IP) -- per RE" + C.RESET))
    L.append("")

    # --- Device clock ------------------------------------------------------ #
    L.append(rule("DEVICE CLOCK  (free-running, occasional SNTP -- not an RTC)"))
    t = dev.j.get("time")
    if isinstance(t, (int, float)):
        dev_utc = datetime.datetime.fromtimestamp(
            t / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        drift = t / 1000 - time.time()
        dcol = C.GREEN if abs(drift) < 5 else C.YELLOW
        L.append(kv("Device time", dev_utc))
        L.append(kv("Drift vs host", "%s%+.1f s%s" % (dcol, drift, C.RESET)))
    else:
        L.append(kv("Device time", "(not reported)"))
    L.append("")

    # --- Cloud (optional) -------------------------------------------------- #
    L.append(rule("CLOUD (Mobile Link REST -- deep telemetry lives here, read-only)"))
    if cloud is None:
        L.append("  " + C.GREY + "local-only: no bearer token "
                 "(set MLG_TOKEN / mlg_token.txt to enable read-only cloud status)" + C.RESET)
    else:
        st, body = cloud.get("list", (None, None))
        if st == 200:
            n = len(body) if isinstance(body, list) else "?"
            L.append("  %s Apparatus/list      HTTP 200  (%s device(s) on account)"
                     % (_mark(True), n))
        else:
            L.append("  %s Apparatus/list      %s"
                     % (_mark(False), _cloud_err(st, body)))
        if "isRegistered" in cloud:
            st2, body2 = cloud["isRegistered"]
            L.append("  %s isRegistered/%s  %s"
                     % (_mark(st2 == 200), args.serial,
                        ("HTTP 200  %s" % body2) if st2 == 200 else _cloud_err(st2, body2)))
        L.append("  " + C.GREY + "note: battery/fuel/run-hours/faults require enrollment "
                 "(device is a cloud relay)" + C.RESET)
    L.append("")

    L.append(C.GREY + "  Ctrl-C to exit."
             + ("" if args.once else "  Refresh %.0fs, re-probe %.0fs."
                % (args.interval, args.probe_interval)) + C.RESET)
    return "\n".join(L)


def _mark(ok):
    if ok is True:
        return C.GREEN + "[OK]" + C.RESET
    if ok is False:
        return C.RED + "[!!]" + C.RESET
    return C.YELLOW + "[??]" + C.RESET


def _tcp_word(state):
    return {"open": C.YELLOW + "OPEN (unexpected!)" + C.RESET,
            "refused": C.GREEN + "refused -- closed (locked)" + C.RESET,
            "timeout": C.GREEN + "filtered -- dropped (locked)" + C.RESET,
            "flap": C.YELLOW + "transient accept (did not persist)" + C.RESET,
            "open-other": C.RED + "OPEN on a DIFFERENT host (ARP MAC mismatch)" + C.RESET,
            }.get(state, C.GREY + str(state) + C.RESET)


def _terminal_word(state):
    if state == "refused":
        return C.GREEN + "LOCKED (closed) -- matches RE" + C.RESET
    if state == "open":
        return C.YELLOW + "OPEN -- unexpected for a Generac Tether!" + C.RESET
    if state == "timeout":
        return C.GREEN + "LOCKED (filtered/dropped) -- matches RE" + C.RESET
    if state == "flap":
        return C.YELLOW + "one-off accept, not a stable service" + C.RESET
    if state == "open-other":
        return C.RED + "another host answered -- IP not the Tether right now" + C.RESET
    return C.GREY + str(state) + C.RESET


def _http_word(hc):
    st, body = hc
    if st is None:
        return C.GREY + "no response on :80 (filtered or absent) -- locked" + C.RESET
    snippet = body[:40].replace("\n", " ")
    if st == 500 and "not initialized" in body.lower():
        return C.GREEN + "500 'Feature not initialized' -- LOCKED, matches RE" + C.RESET
    return C.YELLOW + ("HTTP %s  %s" % (st, snippet)) + C.RESET


def _cloud_err(st, body):
    if st is None:
        return C.RED + ("unreachable: %s" % body) + C.RESET
    if st == 401:
        return C.YELLOW + "HTTP 401 -- token expired/invalid" + C.RESET
    return C.YELLOW + ("HTTP %s" % st) + C.RESET


# --------------------------------------------------------------------------- #
# Device selection                                                             #
# --------------------------------------------------------------------------- #

def is_generac(j):
    v = (j.get("version") or "").upper()
    return "TETHER" in v or "WGM160P" in v


def target_label(args):
    if args.match:
        return "device matching '%s'" % args.match
    return "any Gecko/Zentri device" if args.all else "the Generac Tether (WGM160P)"


def pick_device(devices, args):
    """Return the device matching the requested target (the Generac Tether by
    default), or None if none is present yet. It deliberately does NOT fall back
    to a non-matching device: this LAN can host other Gecko/Zentri devices (e.g.
    a JuiceBox, whose port 2000 IS open), and rendering one of those by mistake
    would report another device's state as if it were the Tether's."""
    cand = list(devices.values())
    if args.match:
        m = args.match.lower()
        cand = [d for d in cand if m in (d.j.get("version", "").lower())]
    elif not args.all:
        cand = [d for d in cand if is_generac(d.j)]
    if not cand:
        return None
    return max(cand, key=lambda d: d.last_mono)


# --------------------------------------------------------------------------- #
# Main loop                                                                     #
# --------------------------------------------------------------------------- #

def drain_beacons(sock, devices, deadline):
    """Receive whatever beacons are waiting until `deadline` (monotonic)."""
    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            return
        except OSError:
            return
        try:
            j = json.loads(data.decode("latin1"))
        except Exception:
            continue
        if not isinstance(j, dict) or "version" not in j:
            continue
        key = j.get("uuid") or j.get("mac") or addr[0]
        devices.setdefault(key, Device(key)).update(j, addr[0])


def waiting_screen(elapsed, args, devices=None):
    clear_screen()
    print(C.BOLD + C.CYAN + "GENERAC MOBILE LINK TETHER -- LOCAL DASHBOARD" + C.RESET)
    print()
    print("  " + C.YELLOW + "Listening for the UDP %d beacon of %s... (%ds)"
          % (BEACON_PORT, target_label(args), int(elapsed)) + C.RESET)
    if devices:
        print()
        print(C.GREY + "  Other Gecko/Zentri devices already seen on the LAN "
              "(not the target):" + C.RESET)
        for d in devices.values():
            print(C.GREY + "    - %-15s port2000=%s  %s"
                  % (d.ip, d.j.get("remote_terminal_port"),
                     (d.j.get("version") or "")[:46]) + C.RESET)
    print()
    print(C.GREY + "  The beacon is a LAN broadcast (~every 10s). If nothing appears:" + C.RESET)
    print(C.GREY + "    - this host must be on the SAME subnet/L2 segment as the device" + C.RESET)
    print(C.GREY + "    - allow inbound UDP %d through the host firewall, e.g. on Windows:" % BEACON_PORT + C.RESET)
    print(C.GREY + '        netsh advfirewall firewall add rule name="Generac beacon" '
          "dir=in action=allow protocol=UDP localport=%d" % BEACON_PORT + C.RESET)
    print(C.GREY + "    - confirm the generator's Tether accessory is powered and joined to WiFi" + C.RESET)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=2.0, help="UI refresh seconds (default 2)")
    ap.add_argument("--probe-interval", type=float, default=30.0,
                    help="active re-probe seconds (default 30)")
    ap.add_argument("--match", help="select device whose version contains this substring")
    ap.add_argument("--all", action="store_true", help="consider every beacon, not just Generac")
    ap.add_argument("--once", action="store_true", help="print a single snapshot and exit")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--bind", default="", help="bind address for the beacon socket")
    ap.add_argument("--port", type=int, default=BEACON_PORT)
    ap.add_argument("--serial", help="generator serial for read-only cloud isRegistered check")
    ap.add_argument("--token", help="cloud bearer token (else MLG_TOKEN / mlg_token.txt)")
    ap.add_argument("--no-cloud", action="store_true", help="never touch the cloud API")
    args = ap.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.off()

    try:
        sock = open_beacon_socket(args.bind, args.port)
    except OSError as e:
        sys.exit("Cannot bind UDP :%d (%s). Is another listener running, "
                 "or is the port blocked?" % (args.port, e))

    devices = {}
    token = None if args.no_cloud else find_token(args.token)
    cloud_cache = {"when": 0.0, "data": None}
    start = time.monotonic()

    try:
        # ---- wait until the TARGET device is heard (bounded in --once) -----
        target = None
        first_deadline = start + (20 if args.once else 10 ** 9)
        while target is None and time.monotonic() < first_deadline:
            drain_beacons(sock, devices, time.monotonic() + 1.0)
            target = pick_device(devices, args)
            if target is None:
                waiting_screen(time.monotonic() - start, args, devices)
        if target is None:
            print("\nNo beacon from %s seen in 20s%s.\nSee the firewall/subnet notes above."
                  % (target_label(args),
                     " (other devices were seen -- try --all or --match)" if devices else ""))
            return

        # ---- main render loop ---------------------------------------------
        last = target
        while True:
            dev = pick_device(devices, args) or last   # stay on the target if it goes quiet
            last = dev

            if time.monotonic() - dev.probe["when"] >= args.probe_interval or dev.probe["when"] == 0:
                refresh_probes(dev)

            cloud = None
            if token:
                if time.monotonic() - cloud_cache["when"] >= max(30, args.probe_interval) \
                        or cloud_cache["data"] is None:
                    cloud_cache["data"] = cloud_status(token, args.serial)
                    cloud_cache["when"] = time.monotonic()
                cloud = cloud_cache["data"]

            clear_screen()
            print(render(dev, cloud, args))
            sys.stdout.flush()

            if args.once:
                return

            drain_beacons(sock, devices, time.monotonic() + args.interval)
    except KeyboardInterrupt:
        print(C.RESET + "\nbye.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
