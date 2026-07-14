#!/usr/bin/env python3
"""Decode the mDNS (UDP 5353) records the Tether emits, to see if it
advertises any local service/port we could talk to."""
import struct, sys, socket

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\gen_boot.pcap"
DEV  = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.94"


def ip_str(b):
    return socket.inet_ntoa(b)


def rdname(data, off):
    labels = []
    jumped = False
    ret = off
    steps = 0
    while off < len(data):
        n = data[off]
        if n == 0:
            off += 1
            break
        if (n & 0xC0) == 0xC0:
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            if not jumped:
                ret = off + 2
            off = ptr
            jumped = True
            steps += 1
            if steps > 128:
                break
            continue
        off += 1
        labels.append(data[off:off + n].decode("latin1", "replace"))
        off += n
    return ".".join(labels), (ret if jumped else off)


TYPES = {1: "A", 12: "PTR", 16: "TXT", 28: "AAAA", 33: "SRV", 47: "NSEC", 5: "CNAME"}


def decode(payload):
    if len(payload) < 12:
        return
    qd, an, ns, ar = struct.unpack("!HHHH", payload[4:12])
    off = 12
    for _ in range(qd):
        name, off = rdname(payload, off)
        if off + 4 > len(payload):
            return
        qt, qc = struct.unpack("!HH", payload[off:off + 4]); off += 4
        print(f"    Q: {name}  ({TYPES.get(qt, qt)})")
    for _ in range(an + ns + ar):
        if off + 1 > len(payload):
            return
        name, off = rdname(payload, off)
        if off + 10 > len(payload):
            return
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", payload[off:off + 10])
        off += 10
        rdata = payload[off:off + rdlen]
        tname = TYPES.get(rtype, str(rtype))
        detail = ""
        try:
            if rtype == 12:                       # PTR
                detail, _ = rdname(payload, off)
            elif rtype == 33:                     # SRV
                pri, wt, port = struct.unpack("!HHH", rdata[:6])
                tgt, _ = rdname(payload, off + 6)
                detail = f"port={port} target={tgt}"
            elif rtype == 16:                     # TXT
                parts, i = [], 0
                while i < len(rdata):
                    ln = rdata[i]; i += 1
                    parts.append(rdata[i:i + ln].decode("latin1", "replace")); i += ln
                detail = " | ".join(parts)
            elif rtype == 1:                      # A
                detail = ip_str(rdata[:4])
        except Exception as e:
            detail = f"<decode err {e}>"
        print(f"    RR: {name}  {tname}  {detail}")
        off += rdlen


def main():
    with open(PATH, "rb") as f:
        data = f.read()
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    off = 24
    seen = 0
    while off + 16 <= len(data):
        _, _, incl, _ = struct.unpack(endian + "IIII", data[off:off + 16])
        off += 16
        pkt = data[off:off + incl]
        off += incl
        if linktype != 1 or len(pkt) < 14:
            continue
        etype = struct.unpack("!H", pkt[12:14])[0]
        l3 = 14
        if etype == 0x8100:
            etype = struct.unpack("!H", pkt[16:18])[0]; l3 = 18
        if etype != 0x0800 or len(pkt) < l3 + 20:
            continue
        ihl = (pkt[l3] & 0x0F) * 4
        proto = pkt[l3 + 9]
        src = ip_str(pkt[l3 + 12:l3 + 16])
        dst = ip_str(pkt[l3 + 16:l3 + 20])
        l4 = l3 + ihl
        if proto != 17 or len(pkt) < l4 + 8:
            continue
        sport, dport = struct.unpack("!HH", pkt[l4:l4 + 4])
        if 5353 not in (sport, dport):
            continue
        # focus on device-originated, but also show any RR that names the device
        payload = pkt[l4 + 8:]
        if src == DEV:
            seen += 1
            print(f"[mDNS #{seen}] {src} -> {dst}")
            decode(payload)
            print()
    if not seen:
        print("No device-originated mDNS packets found.")


if __name__ == "__main__":
    main()
