# tools/

Pure-Python utilities, standard library only unless noted. Organised by device:

| Folder | Contents |
|---|---|
| `tools/` | Shared ZentriOS / Gecko OS utilities: discovery beacon and pcap decoders |
| [`juicebox/`](juicebox/) | JuiceBox Gen 1: telemetry, current-limit control, DNS redirect, counters, pin mapping |
| [`generac/`](generac/) | Generac Mobile Link Tether: provisioning, dashboard, APK and .NET analysis |

Example IPs, MACs and SSIDs in these scripts are from the author's lab hardware. Substitute your own.

---

## Shared: `tools/`

The JuiceBox's AMW106 and the Generac Tether's WGM160P run the same OS family, so these decode
either device. Protocol background: [../docs/ZentriOS-Gecko-LAN-Discovery.md](../docs/ZentriOS-Gecko-LAN-Discovery.md).

| Script | What it does |
|---|---|
| `beacon_extract.py` | Pull the UDP 55555 discovery-beacon JSON out of a pcap, list its keys, and compare the device clock with the capture clock |
| `pcap_analyze.py` | DNS queries, NTP servers, TLS ClientHello SNI, and every destination a given device contacted |
| `pcap_overview.py` | Whole-capture overview: time span, protocol and port histogram, traffic to and from one device, TCP SYNs |
| `mdns_dump.py` | Decode the mDNS records a device emits, to see whether it advertises any local service |

```sh
python beacon_extract.py beacon.pcap 192.168.1.62
python pcap_analyze.py boot.pcap 192.168.1.94
```

The beacon is a limited broadcast, so capture on the router or AP bridge. On DD-WRT or FreshTomato
with Entware:

```sh
opkg install tcpdump
IF=$(ip -o -4 addr show | awk '/192\.168\.1\./{print $2; exit}')
tcpdump -i "$IF" -n -s 0 -c 30 -w /tmp/beacon.pcap 'udp port 55555'
```

That firmware's `tcpdump` lacks the `ether` keyword and there is no `timeout` applet; use `-c`.
Copy captures off with `scp -O`, or `ssh root@router "cat /tmp/beacon.pcap" > beacon.pcap`.

---

## JuiceBox Gen 1: `juicebox/`

These implement the **interim local control** described in
[../docs/STATUS.md](../docs/STATUS.md): the charger is pointed at this PC for DNS, resolves its
cloud hostname to this PC, and sends its UDP telemetry here, where it can be read and answered.
Wire format: [../docs/juicebox/JuiceNet-Protocol.md](../docs/juicebox/JuiceNet-Protocol.md).

| Script | What it does | Changes the charger? |
|---|---|---|
| `juicebox_helper.py` | **The unattended helper.** Resolver, listener and a watchdog in one process: keeps the limit at a target, reattaches the charger after the module reboots, and reboots a hung module (issue #1). `status`, `target N`, `release`, `attach` | Yes: live-only DHCP switch, `reboot`, limit corrections |
| `install_helper.ps1` | Installs the helper as a scheduled task that starts at boot and runs while logged off; `-Uninstall` hands the charger back to the cloud and removes it | Only on `-Uninstall` |
| `test_juicebox_helper.py` | Tests for the helper's decisions, web client, resolver and listener. No charger needed | No |
| `juicebox_dns.py` | DNS resolver that answers both JuiceNet hostnames (`jbv1.emotorwerks.com`, `juicenet-udp-prod5-usa.enelx.com`) with this PC's address and forwards everything else. Needs UDP 53 | No |
| `juicebox_collector.py` | Receives and decodes the telemetry on UDP 8042. With `--set-online N --send` it sets the limit once and confirms it | Only with `--send` |
| `set_limit.py` | Sets the current limit once, confirms the acknowledgement, and exits. The preferred way to change the limit | Only with `--send` |
| `read_counters.py` | Read-only snapshot: uptime, module fault count, lifetime energy, 5-minute history, session events | No |
| `juicebox_rawcap.py` | Legacy Npcap method: captures telemetry in transit to the real cloud and spoofs the cloud's reply. Needs Npcap and scapy, and the charger's gateway pointed at this PC | Only with `--send` |
| `avr_pinmap.py` | Hints at ATmega328P pin usage from a firmware image. **Corroboration only**: calibrated against V8.9 and found to miss the relay and GFI pins | No |

### Unattended: `juicebox_helper.py`

Install once from an elevated PowerShell. It copies the helper to `%LOCALAPPDATA%\OpenJuice\helper`,
because the task starts before network drives are mounted:

```powershell
powershell -ExecutionPolicy Bypass -File tools\juicebox\install_helper.ps1
```

Day to day:

```sh
python %LOCALAPPDATA%\OpenJuice\helper\juicebox_helper.py status      # what it sees and did
python %LOCALAPPDATA%\OpenJuice\helper\juicebox_helper.py target 24   # change the kept limit
python %LOCALAPPDATA%\OpenJuice\helper\juicebox_helper.py release     # hand back to the cloud
python %LOCALAPPDATA%\OpenJuice\helper\juicebox_helper.py attach      # take it back
python -m unittest tools/juicebox/test_juicebox_helper.py             # tests, no charger needed
```

Config, logs and telemetry live in `%LOCALAPPDATA%\OpenJuice`: `helper.json` for settings,
`helper.log` for what it did, `status.json` for the last snapshot, and `telemetry.log` in the
collector's format.

**What it will and will not do to the charger.** Every module command goes through one allowlist:
`get`, `faults_print`, `set wlan.dhcp.enabled 0` (never saved), `network_restart` and `reboot`.
Before switching DHCP off it checks that the charger's saved static address, gateway and DNS lead
back to this PC. It pauses local control at 6 module faults of 8, because Safe Mode starts at 8 —
but while paused the cap is **unenforced** (the module sits at its 40 A ceiling and the car can pull
its full draw, ~32 A), so clear the log promptly. `faults_reset` is deliberately **not** on the
allowlist; clearing is the owner's decision, sent by hand: `release` the helper first (frees the
module's one command parser), then `GET http://<charger>/command/faults_reset`, confirm with
`faults_print` (empty = 0 of 8), then `attach`. After clearing, a stale precheck block can keep the
helper paused for up to an hour (`BLOCK_BACKOFF`); nudge `target` to a different value to lift it at
once. Reboots are rate limited to one per 20 minutes and four per day. Limit corrections are capped
at 12 per day to spare the EEPROM.

**Before a planned long PC outage**, run `release`, and `attach` on return: the released mode is
saved and survives reboots. A Windows shutdown, crash or power loss does not hand the charger back
first. The helper recovers it at the next boot, which after a short reboot is usually a no-op.

### Manual tools

Only one program can own UDP 8042 and one can own UDP 53. Stop the helper's scheduled task before
using these, and stop the collector before running `set_limit.py`.

```sh
python juicebox/juicebox_dns.py --to 192.168.1.74 --upstream 192.168.1.1      # needs UDP 53
python juicebox/juicebox_collector.py --bind 192.168.1.74 --log telemetry.log  # passive
python juicebox/set_limit.py 26                                               # dry run
python juicebox/set_limit.py 26 --send                                        # set and confirm
python juicebox/read_counters.py --host 192.168.1.63
```

**EEPROM wear.** Every accepted command rewrites the offline limit in the charger's EEPROM. All
three sending tools share one routine that sends once, resends only when unacknowledged, gives up
after three attempts, and by default sends nothing if the limit is already set. Older revisions
replied to every telemetry frame, about every 9 seconds.

**Whole amps only**, 6 A to the charger's circuit rating. `set_limit.py` refuses values above the
rating the charger reports.

---

## Generac Mobile Link Tether: `generac/`

Background: [../docs/generac/Generac-MobileLink-Tether-RE.md](../docs/generac/Generac-MobileLink-Tether-RE.md).

### Device

| Script | What it does |
|---|---|
| `generac_provision.py` | SoftAP provisioning client for the Tether V2 API (`192.168.51.1`): `probe`, `scan`, `dump`, `connect`, `portscan`, `listen-udp`. Implements the `wifi_enable`-first join sequence |
| `generac_dashboard.py` | Live text dashboard for a Tether on the LAN. Discovers it from its beacon, verifies the address four ways, and shows identity, RF, clock drift, the state of every known local function, and a firmware-version tripwire. Optional read-only cloud status with a bearer token |
| `mobilelink.py` | Minimal client for the Mobile Link cloud API (api/v5) |

```sh
python generac/generac_provision.py probe
python generac/generac_provision.py connect "YourSSID" "YourPassword"
python generac/generac_dashboard.py --once
```

### App and .NET analysis

Each takes an APK path as its first argument. Used to build the
[app lineage](../docs/generac/MobileLink-App-Lineage.md) and
[cloud API](../docs/generac/MobileLink-Cloud-API.md) documents.

| Script | What it does |
|---|---|
| `analyze_apk.py` | Framework detection and a marker matrix of provisioning and cloud strings |
| `extract_native.py` | String-mine dex, resources, assets and Xamarin assemblies for URLs, IPs and API paths |
| `list_entries.py` | Locate the Xamarin .NET assemblies and detect how they are stored |
| `find_config.py` | Dump the config block containing a given marker, e.g. `LegacyGainspanApi` |
| `extract_dll_endpoints.py` | Endpoint paths and provisioning method names from the .NET assemblies |
| `verify_apk.py` | Confirm a downloaded APK matches an analysed build |
| `xaba_explore.py` | Parse the Xamarin XABA assembly-store header and manifest |
| `xaba_extract.py` | Extract and LZ4-decompress the assemblies from `assemblies.blob` |
| `route_config.py` | REST route templates, base URLs and B2C config from the decompressed assemblies |
| `verify_analysis.py` | Re-test the load-bearing claims against the 3.x APK |
| `ble_check.py` | Confirms the local Bluetooth telemetry mode is portable-generator only |
| `dotnet_inspect.py` | Parse the .NET `#Strings` heap for the sent, stored and undo review |
| `ota_hunt.py` | Search the assemblies and bundle for firmware and OTA machinery |
