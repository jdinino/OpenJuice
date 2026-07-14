#!/usr/bin/env python3
"""Broad overview of the pcap: time span, protocol/port histogram, and
everything to/from the device in both directions. Sanity-checks the parser."""
import struct, sys, socket, collections

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\gen_boot.pcap"
DEV  = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.94"


def ip_str(b):
    return socket.inet_ntoa(b)


def main():
    with open(PATH, "rb") as f:
        data = f.read()
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    off = 24
    npkt = 0
    first_ts = last_ts = None

    proto_port = collections.Counter()
    ethertypes = collections.Counter()
    dev_traffic = collections.Counter()     # (dir, proto, port)
    dev_syn = collections.Counter()          # tcp SYNs from device
    l2_types = collections.Counter()

    while off + 16 <= len(data):
        ts_sec, ts_usec, incl, orig = struct.unpack(endian + "IIII", data[off:off + 16])
        off += 16
        pkt = data[off:off + incl]
        off += incl
        npkt += 1
        ts = ts_sec + ts_usec / 1e6
        if first_ts is None:
            first_ts = ts
        last_ts = ts

        if linktype != 1 or len(pkt) < 14:
            l2_types["short/non-eth"] += 1
            continue
        etype = struct.unpack("!H", pkt[12:14])[0]
        l3 = 14
        if etype == 0x8100:
            etype = struct.unpack("!H", pkt[16:18])[0]
            l3 = 18
        ethertypes[hex(etype)] += 1
        if etype == 0x0806:
            l2_types["ARP"] += 1
            continue
        if etype == 0x86DD:
            l2_types["IPv6"] += 1
            continue
        if etype != 0x0800 or len(pkt) < l3 + 20:
            continue

        ihl = (pkt[l3] & 0x0F) * 4
        proto = pkt[l3 + 9]
        src = ip_str(pkt[l3 + 12:l3 + 16])
        dst = ip_str(pkt[l3 + 16:l3 + 20])
        l4 = l3 + ihl

        if proto == 17 and len(pkt) >= l4 + 8:
            sport, dport = struct.unpack("!HH", pkt[l4:l4 + 4])
            proto_port[("udp", dport)] += 1
            if src == DEV:
                dev_traffic[("OUT", "udp", dport)] += 1
            if dst == DEV:
                dev_traffic[("IN ", "udp", sport)] += 1
        elif proto == 6 and len(pkt) >= l4 + 14:
            sport, dport = struct.unpack("!HH", pkt[l4:l4 + 4])
            flags = pkt[l4 + 13]
            proto_port[("tcp", dport)] += 1
            if src == DEV:
                dev_traffic[("OUT", "tcp", dport)] += 1
                if flags & 0x02:                 # SYN
                    dev_syn[(dst, dport)] += 1
            if dst == DEV:
                dev_traffic[("IN ", "tcp", sport)] += 1
        elif proto == 1:
            proto_port[("icmp", 0)] += 1
            if src == DEV:
                dev_traffic[("OUT", "icmp", 0)] += 1

    span = (last_ts - first_ts) if first_ts else 0
    print(f"packets={npkt}  span={span:.1f}s  linktype={linktype}")
    print(f"ethertypes: {dict(ethertypes)}")
    print(f"L2 buckets: {dict(l2_types)}")

    print("\n=== top (proto, dstport) across whole capture ===")
    for (pr, port), c in proto_port.most_common(25):
        print(f"  {c:5d}x  {pr} :{port}")

    print(f"\n=== ALL traffic involving device {DEV} (both directions) ===")
    if dev_traffic:
        for (d, pr, port), c in sorted(dev_traffic.items(), key=lambda x: -x[1]):
            print(f"  {c:5d}x  {d} {pr} port {port}")
    else:
        print("  (none)")

    print(f"\n=== TCP SYNs FROM device (connection attempts) ===")
    if dev_syn:
        for (ip, port), c in dev_syn.most_common():
            print(f"  {c:4d}x  -> {ip}:{port}")
    else:
        print("  (none — device opened no TCP connections)")


if __name__ == "__main__":
    main()
