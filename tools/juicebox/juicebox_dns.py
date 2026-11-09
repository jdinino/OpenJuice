#!/usr/bin/env python3
"""
juicebox_dns.py -- tiny local DNS resolver that points the JuiceNet hostnames at this PC.

Purpose: make the JuiceBox resolve its JuiceNet telemetry host to this machine, so
its UDP telemetry (and our command replies) flow here -- without touching the router.
Point the charger's DNS at this host (set static.dns <this-ip> on the charger), run
this, and power-cycle the charger. Every query is logged, so you can see the charger
re-resolve. All non-matching queries are forwarded to a real upstream DNS unchanged.

Binds UDP :53 -> needs admin/root. On Windows run from an elevated shell.

Usage:
  python juicebox_dns.py                       # hijack both JuiceNet hosts -> this PC
  python juicebox_dns.py --to 192.168.1.74 --upstream 192.168.1.1
  python juicebox_dns.py --map host=ip --map host2=ip2
"""
import argparse, socket, struct, sys, time

# The charger resolves whichever name its directory handshake left it with; on the
# reference unit that is jbv1.emotorwerks.com. Hijacking only the Enel X name let the
# lookup fall through to the real cloud, silently defeating the redirect.
DEFAULT_HOSTS = ("jbv1.emotorwerks.com", "juicenet-udp-prod5-usa.enelx.com")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    finally:
        s.close()


def parse_question(data):
    """Return (qname_lower, qtype, qend) for the first question."""
    off = 12
    labels = []
    while off < len(data):
        n = data[off]
        if n == 0:
            off += 1; break
        off += 1
        labels.append(data[off:off + n].decode("latin1")); off += n
    qtype, _qclass = struct.unpack("!HH", data[off:off + 4])
    off += 4
    return ".".join(labels).lower().rstrip("."), qtype, off


def build_a_response(query, qend, ip):
    tid = query[0:2]
    flags = b"\x81\x80"                       # response, recursion available, no error
    counts = query[4:6] + b"\x00\x01\x00\x00\x00\x00"   # qd(copy) an=1 ns=0 ar=0
    question = query[12:qend]
    answer = (b"\xc0\x0c" + b"\x00\x01" + b"\x00\x01" +   # name ptr, type A, class IN
              struct.pack("!I", 30) + b"\x00\x04" + socket.inet_aton(ip))
    return tid + flags + counts + question + answer


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", default=None, help="IP to answer for the hijacked host (default: this PC's LAN IP)")
    ap.add_argument("--upstream", default="192.168.1.1", help="real DNS to forward other queries to")
    ap.add_argument("--map", action="append", default=[], help="extra host=ip overrides")
    ap.add_argument("--listen", default="0.0.0.0")
    args = ap.parse_args()

    me = args.to or lan_ip()
    table = {h: me for h in DEFAULT_HOSTS}
    for m in args.map:
        h, _, ip = m.partition("=")
        if h and ip:
            table[h.lower().rstrip(".")] = ip

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.listen, 53))
    except PermissionError:
        sys.exit("Cannot bind udp/53 -- run this from an elevated (Administrator) shell.")
    except OSError as e:
        sys.exit("Cannot bind udp/53 (%s). Elevated? Another DNS/resolver already on :53?" % e)

    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); up.settimeout(4.0)
    print("DNS resolver up on :53   hijack:")
    for h, ip in table.items():
        print("    %s  ->  %s" % (h, ip))
    print("    (everything else forwarded to %s)\nwaiting for queries... Ctrl-C to stop\n" % args.upstream)

    QT = {1: "A", 28: "AAAA", 5: "CNAME", 12: "PTR"}
    try:
        while True:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                qname, qtype, qend = parse_question(data)
            except Exception:
                continue
            ts = time.strftime("%H:%M:%S")
            if qname in table and qtype == 1:
                resp = build_a_response(data, qend, table[qname])
                s.sendto(resp, addr)
                print("[%s] %-15s HIJACK  %s (A) -> %s" % (ts, addr[0], qname, table[qname]))
            else:
                mark = "FWD"
                try:
                    up.sendto(data, (args.upstream, 53))
                    resp, _ = up.recvfrom(2048)
                    s.sendto(resp, addr)
                except Exception as e:
                    mark = "FWD-ERR(%s)" % e
                # log target-host lookups even when we forward (e.g. AAAA), quiet on the rest
                if qname in table or qname.endswith("enelx.com") or qname.endswith("juice.net") or qname.endswith("voltie.us"):
                    print("[%s] %-15s %-5s  %s (%s)" % (ts, addr[0], mark, qname, QT.get(qtype, qtype)))
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        s.close(); up.close()


if __name__ == "__main__":
    main()
