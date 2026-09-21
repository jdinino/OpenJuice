#!/usr/bin/env python3
"""
juicebox_collector.py -- local JuiceNet UDP telemetry + control for JuiceBox Gen 1.

The stock JuiceBox sends plaintext "JuiceNet" telemetry over UDP (~every 9 s) to its
cloud server and expects a command packet in reply. This tool receives that telemetry
locally, decodes it (query), and can reply -- as the server -- with a command that sets
the charge current (set), after which the next telemetry confirms the change (verify).

  Protocol/field decode + CRC ported faithfully from the JuiceRescue project
  (juicepassproxy: juicebox_message.py / juicebox_crc.py), which is the mature
  reverse engineering of the JuiceNet UDP protocol. See docs/JuiceBox-Gen1-Pentest-RE.md.

Redirect the charger's telemetry host to this PC on your router (NO writes to the
charger). For CONTROL, use the DNS-override redirect so the charger addresses THIS host
as the server -- then our command replies are accepted. Startup prints the exact rule.

SAFETY: sending a command changes real charging hardware. This tool only TRANSMITS a
command when you pass --send; without it, it prints the command it WOULD send (dry run).
Lowering the current is inherently safe; keep any value at/below the circuit rating.

Usage:
  python juicebox_collector.py                       # listen + decode (query only)
  python juicebox_collector.py --selftest            # decode sample + build a command
  python juicebox_collector.py --set-online 16       # DRY RUN: show the set-to-16A cmd
  python juicebox_collector.py --set-online 16 --send   # actually set online max to 16A
"""
import argparse, datetime, re, socket, sys, time

JUICENET_HOST = "juicenet-udp-prod5-usa.enelx.com"
DEFAULT_PORT = 8042
SAMPLE = ("0817081001070449032218248303:v07,s0001,u38100,V2436,L0026201508,"
          "S1,T00,M25,m40,t09,i28,e-001,f6000,X0,Y0")


# ------------------------------ CRC (base35) -------------------------------- #
class CRC:
    ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    @classmethod
    def crc(cls, data):
        h = 0
        for s in data:
            h ^= (h << 5) + (h >> 2) + ord(s)
            h &= 0xFFFF
        return h

    @classmethod
    def base35(cls, payload):
        number = cls.crc(payload)
        out = ""
        while (number > 1) or (len(out) < 3):
            number, i = divmod(number, 35)
            if i == 24:
                i = 35
            out += cls.ALPHABET[i]
        return out


# ---------------------------- telemetry decode ------------------------------ #
STATUS = {0: "Unplugged", 1: "Plugged In", 2: "Charging", 5: "Error"}


def _volt(v):   return "%.1f V" % (float(v) if len(v) < 4 else round(float(v) * 0.1, 1))
def _cur(v):    return "%.1f A" % round(float(v) * 0.1, 1)
def _temp(v):   return "%.1f F" % round(float(v) * 1.8 + 32, 1)
def _freq(v):   return "%.2f Hz" % round(float(v) * 0.01, 2)
def _pf(v):     return "%.3f" % round(float(v) * 0.001, 3)
def _wh(v):     return "%s Wh (%.2f kWh)" % ("{:,}".format(int(v)), int(v) / 1000.0)
def _amps(v):   return "%d A" % int(v)
def _status(v): return "%s (%s)" % (v, STATUS.get(int(v), "unknown"))

# field letter -> (label, formatter, show-order). Faithful to juicepassproxy defs.
DEFS = {
    "v": ("protocol version", None),
    "S": ("status", _status),
    "A": ("charging current", _cur),
    "M": ("max current ONLINE", _amps),
    "C": ("max current OFFLINE", _amps),
    "m": ("circuit rating (hw limit)", _amps),
    "V": ("voltage", _volt),
    "f": ("line frequency", _freq),
    "p": ("power factor", _pf),
    "E": ("session energy", _wh),
    "L": ("lifetime energy", _wh),
    "T": ("temperature", _temp),
    "t": ("report interval", lambda v: "%d s" % int(v)),
    "i": ("interval slot", None),
    # NOT a message counter: it echoes the S sequence of the last command the device ACCEPTED.
    # Verified live -- we sent S001/S002/S003 and the device reported s0001/s0002/s0003.
    # Useful as a free per-command acknowledgement check.
    "s": ("cmd ack (echoes our S)", None),
    "u": ("loop counter", None),
}
ORDER = ["v", "S", "A", "M", "C", "m", "V", "f", "p", "E", "L", "T", "t", "i", "s", "u"]

BASE = re.compile(r"^(?P<serial>[0-9]+):(?P<version>v[0-9]+[eu]?)")
PART = re.compile(r"[,]?(?P<type>[A-Za-z]+)(?P<value>-?[0-9]+u?)")


def parse(payload):
    payload = payload.strip().strip("\x00")
    m = BASE.search(payload)
    if not m:
        return None
    serial = m.group("serial")
    version = m.group("version")
    body = payload.split(":", 1)[1]
    body = body.split("!", 1)[0]                      # drop CRC tail if present
    fields = {}
    for tok in body.split(","):
        pm = PART.match(tok.strip())
        if pm:
            fields.setdefault(pm.group("type"), pm.group("value"))
    return serial, version, fields


def render(serial, version, fields, src):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    out = ["[%s] telemetry from %s  serial %s  (%s)" % (ts, src, serial, version)]
    for k in ORDER:
        if k in fields:
            lbl, fn = DEFS[k]
            try:
                val = fn(fields[k]) if fn else fields[k]
            except Exception:
                val = fields[k] + " (raw)"
            out.append("    %-26s %s" % (lbl + ":", val))
    extra = [k for k in fields if k not in DEFS]
    if extra:
        out.append("    %-26s %s" % ("(undecoded):",
                                     " ".join("%s=%s" % (k, fields[k]) for k in extra)))
    return "\n".join(out)


# ------------------------------- command build ------------------------------ #
def build_command(online_amps, offline_amps, counter, command=6, new_version=False, when=None):
    """Return the exact CMD...!<crc>$ string that sets the charge current.
       online_amps  -> device 'A' (max current while connected to server / telemetry M)
       offline_amps -> device 'M' (max current when offline / telemetry C)"""
    when = when or datetime.datetime.now()
    payload = "CMD%s%s" % (when.strftime("%w"), when.strftime("%H%M"))
    if new_version:
        payload += "A%04dM%03d" % (online_amps, offline_amps)
    else:
        payload += "A%02dM%02d" % (online_amps, offline_amps)
    payload += "C%03dS%03d" % (command, counter)
    return "%s!%s$" % (payload, CRC.base35(payload))


# --------------------------------- helpers ---------------------------------- #
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except Exception:
        return "<this-host-LAN-IP>"
    finally:
        s.close()


def redirect_help(ip, port):
    return "\n".join([
        "-" * 72,
        "Redirect the charger's telemetry to this host (no writes to the charger).",
        "For CONTROL use the DNS override so the charger addresses THIS host directly:",
        "  DD-WRT > Services > DNSMasq > Additional DNSMasq Options:",
        "      address=/%s/%s" % (JUICENET_HOST, ip),
        "  then power-cycle the JuiceBox so it re-resolves.",
        "",
        "This host: %s   listening udp/%d" % (ip, port),
        "-" * 72,
    ])


def selftest():
    r = parse(SAMPLE)
    if not r:
        sys.exit("SELFTEST FAILED: sample did not parse")
    print("decode of the documented sample (corrected fields):\n")
    print(render(r[0], r[1], r[2], "sample"))
    print("\n" + "-" * 72)
    cmd = build_command(online_amps=16, offline_amps=16, counter=1,
                        when=datetime.datetime(2026, 9, 14, 12, 0))
    print("example command to set online max = 16 A:\n    %s" % cmd)
    # round-trip: our parser should validate the CRC we just computed
    payload = cmd.split("!")[0]
    crc_in = cmd.split("!")[1].rstrip("$")
    ok = (CRC.base35(payload) == crc_in)
    print("CRC round-trip: %s  (payload=%r crc=%s)" % ("OK" if ok else "FAIL", payload, crc_in))
    # confirm the corrected decode caught the big ones
    checks = {"S": ("status", "Plugged In"), "f": ("freq", "60.00"), "M": ("M", "25")}
    print("field sanity:", ", ".join(
        "%s=%s" % (v[0], r[2].get(k)) for k, v in checks.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bind", default="")
    ap.add_argument("--log")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--set-online", type=int, metavar="AMPS",
                    help="reply to each telemetry with a command setting the ONLINE max current")
    ap.add_argument("--set-offline", type=int, metavar="AMPS",
                    help="also set the OFFLINE max current (defaults to the online value)")
    ap.add_argument("--command", type=int, default=6, help="C field (default 6)")
    ap.add_argument("--new-version", action="store_true",
                    help="use 4/3-digit amperage format (newer firmware); default 2/2 for v07")
    ap.add_argument("--send", action="store_true",
                    help="ACTUALLY transmit the command to the charger (else dry run)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    ip = lan_ip()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.bind, args.port))
    except OSError as e:
        sys.exit("Cannot bind udp/%d (%s)." % (args.port, e))

    print(redirect_help(ip, args.port))
    if args.set_online is not None:
        off = args.set_offline if args.set_offline is not None else args.set_online
        mode = "SEND" if args.send else "DRY-RUN (add --send to transmit)"
        print("CONTROL: set online=%dA offline=%dA on next telemetry  [%s]"
              % (args.set_online, off, mode))
    print("waiting for telemetry... (Ctrl-C to stop)\n")

    logf = open(args.log, "a", encoding="utf-8") if args.log else None
    counter = 0
    last = None
    try:
        while True:
            data, addr = s.recvfrom(4096)
            now = time.monotonic()
            raw = data.decode("latin1", "replace")
            if logf:
                logf.write("%s\t%s\t%s\n" % (datetime.datetime.now().isoformat(), addr[0], raw)); logf.flush()
            r = parse(raw)
            if not r:
                print("[%s] non-telemetry from %s: %r\n"
                      % (datetime.datetime.now().strftime("%H:%M:%S"), addr[0], raw[:80]))
                continue
            cad = "" if last is None else "  (+%.1fs)" % (now - last)
            last = now
            print(render(r[0], r[1], r[2], addr[0]) + cad)
            if args.set_online is not None:
                counter = counter + 1 if counter < 999 else 1
                off = args.set_offline if args.set_offline is not None else args.set_online
                cmd = build_command(args.set_online, off, counter,
                                    command=args.command, new_version=args.new_version)
                if args.send:
                    s.sendto(cmd.encode(), addr)
                    print("    >> SENT command: %s" % cmd)
                else:
                    print("    >> would send (dry run): %s" % cmd)
            print()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        s.close()
        if logf:
            logf.close()


if __name__ == "__main__":
    main()
