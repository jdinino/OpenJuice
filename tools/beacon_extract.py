#!/usr/bin/env python3
"""Extract the UDP 55555 beacon JSON the Tether sent during the capture,
and compare its internal clock to the capture (router) timestamp."""
import struct, sys, socket, json, datetime

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\gen_boot.pcap"
DEV  = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.94"


def ip_str(b):
    return socket.inet_ntoa(b)


def human(ms):
    try:
        return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%SZ")
    except Exception:
        return "?"


def main():
    with open(PATH, "rb") as f:
        data = f.read()
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    off = 24
    rows = []
    keys_union = set()
    while off + 16 <= len(data):
        ts_sec, ts_usec, incl, _ = struct.unpack(endian + "IIII", data[off:off + 16])
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
        l4 = l3 + ihl
        if proto != 17 or src != DEV or len(pkt) < l4 + 8:
            continue
        sport, dport = struct.unpack("!HH", pkt[l4:l4 + 4])
        if dport != 55555:
            continue
        payload = pkt[l4 + 8:]
        try:
            j = json.loads(payload.decode("latin1"))
        except Exception:
            continue
        keys_union.update(j.keys())
        rows.append((ts_sec + ts_usec / 1e6, j))

    if not rows:
        print("No beacon JSON from device found.")
        return

    print(f"beacons from {DEV}: {len(rows)}")
    print(f"union of keys seen: {sorted(keys_union)}\n")

    # full first beacon
    print("=== first beacon (full) ===")
    print(json.dumps(rows[0][1], indent=2))

    print("\n=== clock check: device 'time' vs router capture time ===")
    print(f"{'pcap_ts(UTC)':<22}{'beacon time(raw ms)':<22}{'beacon time(UTC)':<22}{'drift_s':>10}  rssi")
    idxs = list(range(min(3, len(rows)))) + list(range(max(0, len(rows) - 3), len(rows)))
    for i in sorted(set(idxs)):
        ts, j = rows[i]
        t = j.get("time")
        pcap_h = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%SZ")
        drift = (t / 1000 - ts) if isinstance(t, (int, float)) else float("nan")
        print(f"{pcap_h:<22}{str(t):<22}{human(t) if t else '?':<22}{drift:>10.1f}  {j.get('rssi')}")

    # uptime / time progression across the whole capture
    t0 = rows[0][1].get("time")
    tN = rows[-1][1].get("time")
    span_pcap = rows[-1][0] - rows[0][0]
    if isinstance(t0, (int, float)) and isinstance(tN, (int, float)):
        print(f"\nbeacon 'time' advanced {(tN - t0)/1000:.1f}s while capture spanned {span_pcap:.1f}s")


if __name__ == "__main__":
    main()
