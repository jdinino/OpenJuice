# tools/ — ZentriOS / Gecko OS reverse-engineering utilities

Pure-Python (stdlib only, no pip installs) utilities used to reverse-engineer the
ZentriOS/Gecko OS LAN protocols documented in
[`../docs/ZentriOS-Gecko-LAN-Discovery.md`](../docs/ZentriOS-Gecko-LAN-Discovery.md)
and [`../docs/Generac-MobileLink-Tether-RE.md`](../docs/Generac-MobileLink-Tether-RE.md).

They work against **any** device in this OS family — the JuiceBox Gen 1 (AMW006)
and the Generac Mobile Link Tether (WGM160P) both emit the same UDP 55555 beacon,
so `beacon_extract.py` decodes either.

> Requires only Python 3 (stdlib). The pcap tools parse classic `.pcap`
> (libpcap) files directly — no Wireshark, scapy, or tshark needed.

| Script | What it does |
|---|---|
| **`beacon_extract.py`** | Pull the UDP 55555 discovery-beacon JSON out of a pcap; dump the first beacon in full, list the union of keys, and compare the device's `time` field against the capture clock (shows clock drift). |
| **`pcap_analyze.py`** | Targeted decode: DNS queries, NTP servers, TLS ClientHello **SNI**, and every destination a given device IP contacted. Answers "does it phone the cloud, and where." |
| **`pcap_overview.py`** | Whole-capture overview: time span, ethertype/L2 buckets, top `(proto, dstport)` histogram, all traffic to/from a device, and TCP SYNs (connection attempts). |
| **`mdns_dump.py`** | Decode mDNS (UDP 5353) records a device emits — reveals whether it advertises any local service/port (PTR/SRV/TXT) or just claims a hostname. |
| **`generac_provision.py`** | Full SoftAP provisioning client for the Generac Tether V2 API (`192.168.51.1`): `probe`, `scan`, `dump`, `connect`, `portscan`, `listen-udp`. Implements the `wifi_enable`-first join sequence (see Generac RE doc §3). |

## Usage

```sh
# Decode a JuiceBox beacon from a router-side capture
python beacon_extract.py beacon.pcap 192.168.1.62

# What did a device talk to during a boot?
python pcap_analyze.py boot.pcap 192.168.1.94
python pcap_overview.py boot.pcap 192.168.1.94

# Provision a Generac Tether onto WiFi (run while joined to its SoftAP)
python generac_provision.py probe
python generac_provision.py connect "YourSSID" "YourPassword"
python generac_provision.py portscan 192.168.1.94 --ports 2000,23,80,8883
```

## Capturing input pcaps

The 55555 beacon is a limited broadcast — capture on the router/AP bridge, not a
PC on another segment. On DD-WRT / FreshTomato + Entware:

```sh
opkg install tcpdump ngrep
IF=$(ip -o -4 addr show | awk '/192\.168\.1\./{print $2; exit}')
tcpdump -i "$IF" -n -s 0 -c 30 -w /tmp/beacon.pcap 'udp port 55555'
```

Notes for this firmware's toolchain: `tcpdump` lacks the `ether` BPF keyword
(filter on `host`/`port`), and there is no `timeout` applet (use `-c <count>` to
self-terminate). Transfer pcaps with `scp -O` (the router has no sftp-server), or
`ssh root@router "cat /tmp/beacon.pcap" > beacon.pcap`.

## Note on device identifiers

Example IPs/MACs/SSID in these scripts and docs (`192.168.1.94`,
`94:DE:B8:2A:18:EA`, `StumpyNet`, etc.) are from the author's own lab hardware —
substitute your own. The scripts take the target IP/args on the command line.
