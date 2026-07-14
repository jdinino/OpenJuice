#!/usr/bin/env python3
"""Minimal pure-Python pcap analyzer for the Generac Tether boot capture.

Pulls out the things that decide the offline-monitor path:
  - DNS queries (hostnames the device wants -> intent)
  - NTP servers (time sync)
  - TLS ClientHello SNI (exact cloud hostname + whether it even tries)
  - a summary of every dst ip:port the device (default 192.168.1.94) contacted
  - DHCP presence (confirms the broadcast fix)

Usage:  python pcap_analyze.py [file.pcap] [device_ip]
"""
import struct, sys, socket, collections

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\gen_boot.pcap"
DEV  = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.94"


def ip_str(b):
    return socket.inet_ntoa(b)


def parse_dns_name(data, off):
    """Return (name, new_off). Handles compression pointers."""
    labels = []
    jumped = False
    orig_off = off
    steps = 0
    while True:
        if off >= len(data):
            break
        length = data[off]
        if length == 0:
            off += 1
            break
        if (length & 0xC0) == 0xC0:  # pointer
            if off + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[off + 1]
            if not jumped:
                orig_off = off + 2
            off = ptr
            jumped = True
            steps += 1
            if steps > 128:
                break
            continue
        off += 1
        labels.append(data[off:off + length].decode("latin1", "replace"))
        off += length
    return (".".join(labels), orig_off if jumped else off)


def parse_dns(payload):
    """Return list of (qname, qtype) from a DNS message."""
    out = []
    if len(payload) < 12:
        return out
    qd = struct.unpack("!H", payload[4:6])[0]
    off = 12
    for _ in range(qd):
        name, off = parse_dns_name(payload, off)
        if off + 4 > len(payload):
            break
        qtype, qclass = struct.unpack("!HH", payload[off:off + 4])
        off += 4
        out.append((name, qtype))
    return out


def parse_tls_sni(payload):
    """Best-effort SNI extraction from a TLS ClientHello in this TCP payload."""
    try:
        if len(payload) < 6 or payload[0] != 0x16:      # handshake
            return None
        # TLS record: type(1) ver(2) len(2) ; handshake: type(1) len(3) ver(2)...
        if payload[5] != 0x01:                          # ClientHello
            return None
        p = 43                                          # skip to session id len
        if p >= len(payload):
            return None
        sid_len = payload[p]; p += 1 + sid_len
        if p + 2 > len(payload):
            return None
        cs_len = struct.unpack("!H", payload[p:p + 2])[0]; p += 2 + cs_len
        if p >= len(payload):
            return None
        comp_len = payload[p]; p += 1 + comp_len
        if p + 2 > len(payload):
            return None
        ext_total = struct.unpack("!H", payload[p:p + 2])[0]; p += 2
        end = min(len(payload), p + ext_total)
        while p + 4 <= end:
            etype, elen = struct.unpack("!HH", payload[p:p + 4]); p += 4
            if etype == 0x0000:                         # server_name
                # server_name_list(2) type(1) name_len(2) name
                if p + 5 <= len(payload):
                    nlen = struct.unpack("!H", payload[p + 3:p + 5])[0]
                    return payload[p + 5:p + 5 + nlen].decode("latin1", "replace")
            p += elen
    except Exception:
        return None
    return None


def main():
    with open(PATH, "rb") as f:
        data = f.read()

    magic = data[:4]
    if magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    elif magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    else:
        print(f"Not a classic pcap (magic={magic.hex()}). "
              f"If it's pcapng, re-capture or convert.")
        return

    linktype = struct.unpack(endian + "I", data[20:24])[0]
    print(f"pcap: endian={endian} linktype={linktype} size={len(data)} bytes")
    off = 24
    npkt = 0

    dns_q = collections.Counter()
    ntp_dst = collections.Counter()
    tls_sni = collections.Counter()
    dev_dests = collections.Counter()   # (dst_ip, dport, proto) device -> world
    dhcp = 0
    other_dns_all = collections.Counter()

    while off + 16 <= len(data):
        ts_sec, ts_usec, incl, orig = struct.unpack(endian + "IIII", data[off:off + 16])
        off += 16
        pkt = data[off:off + incl]
        off += incl
        npkt += 1

        # Ethernet
        if linktype != 1 or len(pkt) < 14:
            continue
        etype = struct.unpack("!H", pkt[12:14])[0]
        l3 = 14
        if etype == 0x8100:                 # VLAN
            etype = struct.unpack("!H", pkt[16:18])[0]
            l3 = 18
        if etype != 0x0800:                 # only IPv4
            continue
        if len(pkt) < l3 + 20:
            continue
        ihl = (pkt[l3] & 0x0F) * 4
        proto = pkt[l3 + 9]
        src = ip_str(pkt[l3 + 12:l3 + 16])
        dst = ip_str(pkt[l3 + 16:l3 + 20])
        l4 = l3 + ihl

        if proto == 17 and len(pkt) >= l4 + 8:            # UDP
            sport, dport, ulen = struct.unpack("!HHH", pkt[l4:l4 + 6])
            payload = pkt[l4 + 8:]
            if dport == 53 or sport == 53:
                for name, qtype in parse_dns(payload):
                    other_dns_all[name] += 1
                    if src == DEV or dst == DEV:
                        dns_q[name] += 1
            if dport == 123 or sport == 123:
                if src == DEV:
                    ntp_dst[dst] += 1
            if dport in (67, 68) or sport in (67, 68):
                dhcp += 1
            if src == DEV and dst != "255.255.255.255" and dport != 55555:
                dev_dests[(dst, dport, "udp")] += 1

        elif proto == 6 and len(pkt) >= l4 + 20:          # TCP
            sport, dport = struct.unpack("!HH", pkt[l4:l4 + 4])
            doff = (pkt[l4 + 12] >> 4) * 4
            payload = pkt[l4 + doff:]
            if payload and (dport in (443, 8883, 8443) or sport in (443, 8883, 8443)
                            or payload[:1] == b"\x16"):
                sni = parse_tls_sni(payload)
                if sni:
                    tls_sni[sni] += 1
            if src == DEV:
                dev_dests[(dst, dport, "tcp")] += 1

    print(f"total packets: {npkt}\n")

    print("=== DNS queries involving the device ===")
    if dns_q:
        for name, c in dns_q.most_common():
            print(f"  {c:4d}x  {name}")
    else:
        print("  (none)")

    print("\n=== ALL DNS queries in capture (context) ===")
    for name, c in other_dns_all.most_common(40):
        print(f"  {c:4d}x  {name}")

    print("\n=== NTP servers the device contacted ===")
    if ntp_dst:
        for ip, c in ntp_dst.most_common():
            print(f"  {c:4d}x  {ip}")
    else:
        print("  (none)")

    print("\n=== TLS SNI (ClientHello hostnames) ===")
    if tls_sni:
        for name, c in tls_sni.most_common():
            print(f"  {c:4d}x  {name}")
    else:
        print("  (none seen)")

    print(f"\n=== Every dst the device {DEV} reached (excl. beacon/broadcast) ===")
    if dev_dests:
        for (ip, port, pr), c in dev_dests.most_common():
            print(f"  {c:4d}x  {pr:3s} {ip}:{port}")
    else:
        print("  (none — device only broadcast the beacon)")

    print(f"\nDHCP packets seen: {dhcp}")


if __name__ == "__main__":
    main()
