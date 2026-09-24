#!/usr/bin/env python3
"""
juicebox_rawcap.py -- capture + control the JuiceBox Gen 1 with NO router changes and
NO changes to this PC's IP addresses, using raw L2 packet capture (Npcap / scapy).

How it works (device-side only, you own the charger):
  Point the JuiceBox WiFi module's DEFAULT GATEWAY at THIS PC (gateway=us), via the
  module's own HTTP /command API. The module keeps addressing its JuiceNet telemetry to
  the (cached) cloud IP on udp/8042, but -- because we are now its gateway -- it sends
  those frames to THIS PC's MAC. Windows drops them at the IP layer (wrong dst IP), yet
  Npcap captures the L2 frame first. We decode it (query). To CONTROL, we reply with a
  command frame whose source is spoofed to *exactly* the cloud IP:port the module used,
  so the module's connected UDP socket accepts it -- with no re-resolve, no DNS override,
  no NIC address change, and nothing touched on the router.

  Telemetry decode + CRC + command build are imported from juicebox_collector.py, so the
  wire format stays identical to the stdlib collector.

Requires: Npcap (https://npcap.com) + `pip install scapy`, run from an elevated shell.

SAFETY: transmits a command only with --send (otherwise dry-run prints what it WOULD
send). Lowering current is inherently safe; keep any value at/below the circuit rating.

Usage (run elevated):
  python juicebox_rawcap.py                          # capture + decode (query only)
  python juicebox_rawcap.py --set-online 40 --send   # reply, setting ONLINE max to 40 A
  python juicebox_rawcap.py --iface Wi-Fi            # force capture interface (substring)
  python juicebox_rawcap.py --list-ifaces            # show interfaces scapy can see
"""
import argparse
import datetime
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from juicebox_collector import parse, render, build_command  # noqa: E402

try:
    from scapy.all import (sniff, sendp, Ether, IP, UDP, Raw, conf,
                           get_working_ifaces, get_if_addr)
except Exception as e:  # pragma: no cover
    sys.exit("scapy import failed (%s).\nInstall Npcap (https://npcap.com) and "
             "`pip install scapy`, then run from an elevated shell." % e)

PORT = 8042


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "<this-host-LAN-IP>"
    finally:
        s.close()


def iface_label(i):
    return getattr(i, "description", None) or getattr(i, "name", None) or str(i)


def iface_ip(i):
    ip = getattr(i, "ip", None)
    if ip:
        return ip
    try:
        return get_if_addr(i)
    except Exception:
        return None


def pick_iface(want, my_ip):
    """Interface matching name/description substring `want`, else the one carrying my_ip."""
    ifaces = list(get_working_ifaces())
    if want:
        for i in ifaces:
            blob = "%s %s" % (getattr(i, "name", ""), getattr(i, "description", ""))
            if want.lower() in blob.lower():
                return i
        sys.exit("no interface matched %r. Try --list-ifaces." % want)
    for i in ifaces:
        if iface_ip(i) == my_ip:
            return i
    return conf.iface


class State:
    def __init__(self, args, iface):
        self.args = args
        self.iface = iface
        self.counter = 0
        self.m_seen = []


def make_reply(pkt, cmd_bytes):
    """Swap every layer of the captured telemetry frame and substitute our command.
       The reply's source becomes exactly the cloud IP:port the module addressed, so its
       connected UDP socket accepts it. Nothing is hardcoded -- we mirror the packet."""
    eth, ip, udp = pkt[Ether], pkt[IP], pkt[UDP]
    return (Ether(src=eth.dst, dst=eth.src) /
            IP(src=ip.dst, dst=ip.src) /
            UDP(sport=udp.dport, dport=udp.sport) /
            Raw(load=cmd_bytes))


def handle(pkt, st, logf):
    if not (pkt.haslayer(UDP) and pkt.haslayer(Raw)):
        return
    raw = bytes(pkt[Raw].load).decode("latin1", "replace")
    now = datetime.datetime.now()
    if logf:
        logf.write("%s\t%s->%s\t%s\n" % (now.isoformat(), pkt[IP].src, pkt[IP].dst, raw))
        logf.flush()
    r = parse(raw)
    if not r:
        print("[%s] non-telemetry %s->%s: %r"
              % (now.strftime("%H:%M:%S"), pkt[IP].src, pkt[IP].dst, raw[:60]))
        return
    print(render(r[0], r[1], r[2], pkt[IP].src)
          + "   (module -> %s:%d, routed via us)" % (pkt[IP].dst, pkt[UDP].dport))
    if "M" in r[2]:
        st.m_seen.append(r[2]["M"])
    a = st.args
    if a.set_online is not None:
        st.counter = st.counter + 1 if st.counter < 999 else 1
        off = a.set_offline
        cmd = build_command(a.set_online, off, st.counter,
                            command=a.command, new_version=a.new_version)
        if a.send:
            sendp(make_reply(pkt, cmd.encode()), iface=st.iface, verbose=0)
            print("    >> SENT (spoofed src %s:%d): %s" % (pkt[IP].dst, pkt[UDP].dport, cmd))
        else:
            print("    >> would send (dry run): %s" % cmd)
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iface", default="", help="capture interface (name/description substring)")
    ap.add_argument("--list-ifaces", action="store_true", help="list interfaces and exit")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--count", type=int, default=0,
                    help="stop after N captured telemetry packets (0 = until Ctrl-C)")
    ap.add_argument("--seconds", type=int, default=0,
                    help="stop after N seconds (0 = no limit)")
    ap.add_argument("--log")
    ap.add_argument("--set-online", type=int, metavar="AMPS",
                    help="reply to each telemetry with a command setting the ONLINE max current")
    ap.add_argument("--set-offline", type=int, metavar="AMPS",
                    help="REQUIRED with --set-online: the OFFLINE max current. It is a mandatory "
                         "positional field in the wire format, and it is WRITE-ONLY on this "
                         "firmware (telemetry carries no 'C' field), so it cannot be read back or "
                         "verified -- it must be chosen deliberately, never defaulted. It is also "
                         "EEPROM-BACKED: keep it constant across runs, never sweep it, and never "
                         "set it above the circuit rating 'm'.")
    ap.add_argument("--command", type=int, default=6, help="C field (default 6)")
    ap.add_argument("--new-version", action="store_true",
                    help="use 4/3-digit amperage format (newer firmware); default 2/2 for v07")
    ap.add_argument("--send", action="store_true",
                    help="ACTUALLY transmit the command to the charger (else dry run)")
    args = ap.parse_args()

    # The C=006 command ALWAYS carries an offline max (mandatory positional field), and this
    # firmware reports no 'C' field, so the written value can never be verified. Refuse to pick
    # it implicitly -- a write-only safety-adjacent parameter must be an explicit operator choice.
    if args.set_online is not None and args.set_offline is None:
        ap.error("--set-offline is required whenever --set-online is used.\n"
                 "  The command format always carries an offline max, and it is write-only on\n"
                 "  this firmware (no 'C' field in telemetry) -- it cannot be read back.\n"
                 "  Pass it explicitly, e.g. --set-offline %d to mirror the online value."
                 % args.set_online)

    if args.list_ifaces:
        for i in get_working_ifaces():
            print("  %-40s %s" % (iface_ip(i) or "-", iface_label(i)))
        return

    my_ip = lan_ip()
    iface = pick_iface(args.iface, my_ip)
    st = State(args, iface)

    print("-" * 72)
    print("raw JuiceNet capture (Npcap)   this host: %s" % my_ip)
    print("capture iface : %s  [%s]" % (iface_label(iface), iface_ip(iface) or "?"))
    print("filter        : udp and dst port %d" % args.port)
    print("Set the JuiceBox module gateway to %s (gateway=us) so its telemetry routes here."
          % my_ip)
    if args.set_online is not None:
        off = args.set_offline
        print("CONTROL       : set online=%dA offline=%dA  [%s]"
              % (args.set_online, off, "SEND" if args.send else "DRY-RUN (add --send)"))
        print("              ! offline max (M) is EEPROM-backed and is written on EVERY command.")
        print("                Keep it constant; do not run long sessions that vary it.")
    print("-" * 72)
    print("waiting for telemetry... Ctrl-C to stop\n")

    logf = open(args.log, "a", encoding="utf-8") if args.log else None
    try:
        sniff(iface=iface, filter="udp and dst port %d" % args.port, store=0,
              count=args.count, timeout=(args.seconds or None),
              prn=lambda p: handle(p, st, logf))
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        if logf:
            logf.close()
    if st.m_seen:
        print("-" * 72)
        print("M (max current ONLINE) observed, in order: %s A" % " -> ".join(st.m_seen))
    if args.send and args.set_online is not None:
        print("commands transmitted: %d" % st.counter)


if __name__ == "__main__":
    main()
