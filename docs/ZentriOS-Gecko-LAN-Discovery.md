# ZentriOS / Gecko OS — LAN Discovery Beacon & Local Protocols

**Status:** Reverse-engineered and verified on live hardware, 2026-07-14
**Applies to:** Any ZentriOS / WiConnect / Gecko OS module in "gateway/discovery" mode — including the **JuiceBox Gen 1 (AMW006)** and the **Generac Mobile Link Tether (WGM160P)**

---

## 1. Why this is in the OpenJuice repo

The JuiceBox Gen 1 WiFi module (Zentri **AMW006**) and the Generac Mobile Link Tether (Silicon Labs **WGM160P**) run the **same OS family** — ZentriOS/WiConnect and its successor Gecko OS. Both emit an identical **UDP broadcast discovery beacon on port 55555**, and both advertise a **stream-mode TCP service on port 2000**.

This matters for OpenJuice directly:

- The beacon is a **zero-touch way to find the JuiceBox's IP** on the LAN — no port scan, no router login. This is the missing auto-discovery piece for the [v0.2 WiFi RAPI tunneling](OpenJuice-FSD.md#9-v02--wifi-rapi-tunneling-via-amw006) feature, which connects to the AMW006 on **port 2000** (the same `remote_terminal_port` the beacon advertises).
- The beacon carries **RSSI, uptime clock, firmware version, and the AP it's joined to** — a free local telemetry/health feed for a JuiceBox running stock WiFi firmware, requiring **zero changes to the AMW006**.

Everything here was captured live from a home LAN that happened to host **both** a JuiceBox and a Generac Tether at once, giving a clean side-by-side of the two firmware generations.

---

## 2. The UDP 55555 discovery beacon

### 2.1 Transport

| Property | Value |
|---|---|
| Protocol | UDP |
| Source port | 55555 |
| Destination | `255.255.255.255:55555` (limited broadcast) |
| Cadence | ~10 seconds (measured 10.0–10.8 s) |
| Payload | ASCII **JSON**, one object per datagram (~287 bytes) |
| Reachability | Limited broadcast — **stays on the local L2 segment; routers do not forward it.** Capture on the router/AP bridge or a host on the same subnet (see §5). |

### 2.2 Field reference

| Key | Type | Meaning |
|---|---|---|
| `mac` | string | The module's **station** (client) MAC — the interface joined to your WiFi |
| `bssid` | string | MAC of the **access point** it associated to (identifies which AP/repeater) |
| `channel` | int | 2.4 GHz channel currently in use |
| `ip` | string | The device's DHCP-assigned IP — **this is the discovery payoff** |
| `ssid` | string | The WiFi network it joined |
| `rssi` | int (dBm) | Received signal strength (e.g. −43 = excellent, −68 = usable) |
| `remote_terminal_port` | int | TCP port of the module's stream/remote-terminal service (default **2000**) |
| `time` | int (ms) | Device wall-clock as **Unix epoch milliseconds** (see §4) |
| `version` | string | Firmware banner: `<app>, [<build date>,] <OS>-<ver>, <module>` |
| `uuid` | string | Module unique ID (hex) — distinct from any cloud/account device ID |

### 2.3 Live sample — JuiceBox Gen 1 (AMW006)

```json
{
  "mac": "4C:55:CC:18:1D:09",
  "bssid": "38:94:ED:5E:BE:0F",
  "channel": 1,
  "ip": "192.168.1.62",
  "ssid": "StumpyNet",
  "rssi": -68,
  "remote_terminal_port": 2000,
  "time": 1784058085337,
  "version": "EMWERK-JB_1_1-1.4.0.28, 2021-04-27T20:39:50Z, ZentriOS-WZ-3.6.4.0",
  "uuid": "06413041000000001D003F00055136313535 3738"
}
```

> **FSD correction:** [OpenJuice-FSD §2.3](OpenJuice-FSD.md#23-wifi-module-not-modified) lists the AMW006 firmware as *WiConnect 2.2.0.12*. The live unit reports **`ZentriOS-WZ-3.6.4.0`** with the eMotorWerks app layer **`EMWERK-JB_1_1-1.4.0.28`** (built 2021-04-27). ZentriOS-WZ is the "WiZnet"/JuiceBox variant. v0.2 planning should target the ZentriOS 3.6 command set, not WiConnect 2.2.

### 2.4 Live sample — Generac Mobile Link Tether (WGM160P)

```json
{
  "mac": "94:DE:B8:2A:18:EA",
  "bssid": "38:94:ED:5E:BE:0F",
  "channel": 1,
  "ip": "192.168.1.94",
  "ssid": "StumpyNet",
  "rssi": -43,
  "remote_terminal_port": 2000,
  "time": 1784058086991,
  "version": "H42069-TETHER-1.0.8, Gecko_OS-STANDARD-4.2.3-9237, WGM160P",
  "uuid": "EADE2FF34B76B3EF7EA72B5A84B4DBFFFECB7CB4"
}
```

Identical schema, different firmware generation — confirming the beacon is a **stock ZentriOS/Gecko OS feature**, not something either vendor added.

---

## 3. Port 2000 — the stream / remote-terminal service

Both beacons advertise `remote_terminal_port: 2000`. In ZentriOS/Gecko OS this is the TCP endpoint that bridges the module's UART (stream mode) or exposes its command shell (remote terminal), depending on configuration.

| Device | Port 2000 state | Implication |
|---|---|---|
| **JuiceBox (AMW006)** | Stream mode → UART0 (per FSD §9.4, `bus.mode: stream`) | **This is the v0.2 tunnel.** A client connects to `<juicebox_ip>:2000` and speaks RAPI straight to the ATmega328P. The beacon hands you `<juicebox_ip>` for free. |
| **Generac (WGM160P)** | **Firewalled/disabled** (TCP *and* UDP both refused; the Gecko OS `/command/*` HTTP API returns `Feature not initialized`) | Generac locked the module down to a pure cloud relay. Advertised-but-closed — the beacon reports the configured port regardless of firewall state. |

**Takeaway for OpenJuice v0.2:** the beacon *validates the port-2000 assumption* in FSD §9.6 and removes the "TCP port unknown" risk (FSD risk **W3**). The auto-discovery flow becomes:

```
listen UDP 55555  →  parse JSON  →  match version contains "EMWERK-JB"
                  →  connect TCP  {ip}:{remote_terminal_port}  →  speak RAPI
```

---

## 4. The `time` field — occasional sync, free-running clock

The beacon `time` is genuine Unix epoch **milliseconds** (as uptime it would be decades). Tracking it across a 13.5-minute capture against the router's clock:

| | device `time` | drift vs real |
|---|---|---|
| start | matched | −0.5 s |
| +13 min | behind | −6.2 s |

The clock advanced 806.8 s while 812.4 s of real time elapsed — it is **free-running and drifting (~0.7 %)**, i.e. synced occasionally (SNTP at boot / periodic), **not continuously fed by any cloud connection.** Useful as a coarse "device is alive and roughly time-aware" signal; do **not** treat it as an accurate RTC.

---

## 5. Capturing the beacon (router / AP side)

Because the beacon is a limited broadcast, a PC on a different segment (or behind Windows Firewall) usually won't see it. Capture on the router/AP bridge instead. On **DD-WRT / FreshTomato + Entware** (`opkg install tcpdump ngrep`):

```sh
# find the LAN bridge that holds 192.168.1.1
ip -o -4 addr show | awk '/192\.168\.1\./{print $2; exit}'      # e.g. br0

# live hex+ASCII peek (Ctrl-C after a few)
ngrep -d br0 -x -q '' 'udp port 55555'

# or capture N to a pcap for offline decode
tcpdump -i br0 -n -s 0 -c 30 -w /tmp/beacon.pcap 'udp port 55555'
```

Then decode with the repo tool (works on JuiceBox *and* Generac beacons):

```sh
python tools/beacon_extract.py /path/to/beacon.pcap 192.168.1.62   # JuiceBox
```

See [`tools/`](../tools/) for `beacon_extract.py`, `pcap_analyze.py`, `pcap_overview.py`, and `mdns_dump.py`.

---

## 6. Other LAN chatter observed

For completeness, over a full 13-minute window (including a cold boot with a captured WPA 4-way/EAPOL handshake), a **locked** Gecko OS device (the Generac Tether) emitted **only**:

1. **DHCP** — to obtain its IP.
2. **mDNS** (`224.0.0.251:5353`) — a hostname *claim* only: it probes/announces `gecko_os-<suffix>.local → A <ip>`. **No SRV/TXT/PTR records — it advertises no service.**
3. The **UDP 55555 beacon** described above.

No unicast DNS, no NTP, no TCP, no TLS. This is the useful baseline: on a stock/locked ZentriOS/Gecko device, the **55555 beacon is the entire local-telemetry surface** unless stream mode (port 2000) is open — which, on the JuiceBox, it is.

---

## 7. Relevance summary

| Finding | OpenJuice impact |
|---|---|
| UDP 55555 JSON beacon on JuiceBox | Auto-discovery of JuiceBox IP for v0.2 (no scan/login) |
| `remote_terminal_port: 2000` advertised | Confirms v0.2 tunnel port; retires FSD risk W3 |
| Beacon carries RSSI / uptime / firmware | Free local health feed, zero AMW006 changes |
| AMW006 runs ZentriOS-WZ 3.6.4.0 (not WiConnect 2.2) | Corrects FSD §2.3; target the right command set |
| `mac` = station iface, `bssid` = AP | Roaming/AP diagnostics for install troubleshooting |

## Appendix: DDWRT/FreshTomato + Entware capture toolchain

| Tool | `opkg` package | Use |
|---|---|---|
| `tcpdump` | `tcpdump` | packet capture to pcap |
| `ngrep` | `ngrep` | live hex/ASCII payload grep |
| `conntrack` | `conntrack` | list active/idle connections (`/proc/net/nf_conntrack`) |

Note: this firmware's `tcpdump` lacks the `ether` BPF keyword and there is no `timeout` applet — filter on `host`/`port` and use `-c <count>` to self-terminate.
