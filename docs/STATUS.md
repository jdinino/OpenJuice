# OpenJuice — Project Status

**Updated:** 2026-09-24 · **Reference unit:** JuiceBox Gen 1, PCB 8.14 or later, WiFi firmware
`EMWERK-JB_1_1-1.4.0.28` on ZentriOS-WZ 3.6.4.0

Evidence tiers used below: **[V]** verified on the reference unit · **[D]** documented by a primary
source · **[I]** inferred.

---

## 1. Goal and constraints

**Goal.** Port OpenEVSE to the JuiceBox Gen 1 **on its existing hardware**, and serve an
OpenEVSE-style status and control page **from the charger itself**, on the LAN, with no cloud and
no helper machine.

**Constraints**, set by the project owner:

- **Hardware stays intact.** Out of scope: replacing the PCB; replacing, removing or adding any chip
  or module, including the ATmega328P, a Pro Mini carrier and the AMW106 WiFi module; buying a
  swappable OpenEVSE kit such as the JuiceRescue controller or an ESP32 WiFi gateway.
- **Firmware reflashing is allowed** where the port needs it: on the ATmega, and on the AMW106 if it
  comes to that.
- **Programming tools** that clip on temporarily, such as a USB-serial adapter, an ISP programmer
  or a JTAG pod, are treated as tools rather than hardware changes. The owner's spare board is tried
  as the tool first, and nothing is bought unless it fails.

---

## 2. Where things stand

| Area | State |
|---|---|
| Interim local control | **Working.** A PC helper receives telemetry and sets the limit. 26 A verified on a real charge: 25.8–26.1 A across 71 frames **[V]** |
| Stage A: dashboard on the charger | Not started. Every data format it needs is decoded **[V]** |
| Stage B: the OpenEVSE port | Patch written for **V8.9 only**; not flashable on this board. Phase 0 not started |
| WiFi module health | 3 watchdog crashes of 8 before Safe Mode, all while on the local redirect **[V]** |
| Research | Broad searches finished; five targeted leads remain (§8) |

---

## 3. What we have established

1. **The WiFi module's vendor app owns the cloud link, not the charging controller** **[V]**. The app,
   `JB1_0.zap`, composes the JuiceNet traffic, writes the energy logs, and re-enables DHCP at every
   boot. It cannot be backed up: the module refuses to read it and the web server returns 404.
   Disabling it would stop telemetry, control and logging together, and may stop WiFi from coming
   up at all. **Never set `zap.auto_run 0`.**
2. **No helper-free control exists on stock firmware** **[V]**. A 49-path census with adversarial review
   found every route to control needs either a process on another machine or a firmware change. The
   "charger talks to itself" idea fails because the module has no way to override name resolution.
3. **The DNS redirect works only while the vendor's directory service stays broken** **[V]**. Today the
   charger's directory lookup fails at every boot, so it falls back to a hostname we can redirect.
   When that lookup succeeded, in February 2026, the charger used a fixed IP and a DNS redirect
   would have done nothing. The same response can switch the charger to encrypted telemetry.
4. **The pin map changed at every published board revision** **[D]**. eMotorWerks' V8.10.7 source
   carries both the V8.9 and V8.10 maps, and its v8.12 factory test firmware carries a third. Only
   GFI trip, GFI latch reset, pilot PWM and one remote button stayed put. Our patch matches V8.9
   exactly. The per-revision table is in the [FSD](juicebox/OpenJuice-FSD.md#3-pin-mapping).
5. **From v8.12, current and voltage come from an ATM90E26 metering chip** over serial, not from an
   analog input **[D]**. The port needs a driver for it if this board follows v8.12.
6. **Replacing the WiFi module's software is not a practical route** **[D]**. No Gecko OS build exists
   for the AMW106; ZentriOS-WZ 3.6.4.0 is its final release. A custom application would need a JTAG
   pod inside the enclosure and a vendor build service that may refuse a device Enel X owns. It
   would also have to fit a web server, the charger protocol and WiFi bring-up into a 32 KB code
   budget, of which the vendor app uses 98%.
7. **The charge limit is whole amps only** **[D]**. The protocol has no fractional field, the stock
   firmware parses an integer, and the vendor's own setup app offers whole amps. That app's local
   `maxcurrent_app` command does not exist on this firmware **[V]**.
8. **The temperature reading is a board sensor** **[D]**, cut off at 80 °C in V8.10 firmware. It does
   not see the plug, cable or supply wiring. V8.9 and V8.10 boards had a 6 W mains-powered PCB heater;
   the v8.12 test firmware shows no sign of one.
9. **The module has a hardwired recovery path** **[D]**: holding GPIO 0 high through a reset forces a
   factory reset regardless of any setting. It still requires opening the enclosure.

---

## 4. Interim local control

This is the working stopgap until the port. It needs a PC on the same network running two helpers,
and it lapses whenever the WiFi module reboots, which has happened every one to two days.

**How it works.** The charger's DNS is pointed at the PC. The PC answers the charger's cloud
hostname with its own address, so the charger sends its UDP telemetry to the PC, which can read it
and reply with commands exactly as the cloud would.

**One-time setup, already saved on the reference unit:**

| Module variable | Value | Why |
|---|---|---|
| `wlan.static.ip` | the charger's address, e.g. `192.168.1.63` | used when DHCP is off |
| `wlan.static.dns` | the PC's address, e.g. `192.168.1.74` | points lookups at the helper |
| `wlan.static.gateway` | **the router**, e.g. `192.168.1.1` | never the PC: a sleeping PC would cut the charger's internet |

**Each time control is needed:**

```sh
# 1. On the PC: the resolver and the listener. Both run until stopped.
python tools/juicebox/juicebox_dns.py --to 192.168.1.74 --upstream 192.168.1.1
python tools/juicebox/juicebox_collector.py --bind 192.168.1.74 --log telemetry.log

# 2. On the charger: switch to the static settings for this boot only. Never `save` this.
curl "http://192.168.1.63/command/set%20wlan.dhcp.enabled%200"
curl "http://192.168.1.63/command/network_restart"

# 3. Set the limit once. Stop the collector first: only one program can own UDP 8042.
python tools/juicebox/set_limit.py 26 --send
python tools/juicebox/read_counters.py --host 192.168.1.63
```

**What to expect.** The module is back in about 5 seconds and its first telemetry reaches the PC
within about 30 seconds. After a reboot the cloud has pushed its own limit each time, 40 A; one
command restores yours. Each accepted command also sets the offline limit, which the charger falls
back to after roughly 6 minutes without commands **[I]**, so your limit survives the gap after the
next reboot.

**To hand the charger back to the cloud,** reboot it: `curl http://<charger>/command/reboot`. DHCP
comes back on because the change was never saved. A commanded reboot does not count toward the
module's fault limit **[V]**.

**Cautions:**

- **Never `save` with DHCP off**, and never set `zap.auto_run`. An unsaved change is the escape hatch.
- **Never connect to port 2000.** It is an unauthenticated command shell, and a connected session
  disables the module's local command interface.
- **One request at a time to the module.** Its web interface shares one command parser with the
  serial link to the charging controller.
- **Keep the resolver running** whenever the charger's DNS points at the PC. A charger left pointed
  at a dead resolver cannot reach anything, and one of the three watchdog crashes happened that way.
- **On Windows, Internet Connection Sharing holds UDP 53.** Disable it; **never delete it.** Windows
  keeps the firewall's whole configuration inside the ICS registry key, so deleting the service wiped
  the reference PC's firewall rules and left the firewall unable to start.
- **If the Windows firewall is on**, allow inbound UDP 53 and UDP 8042.

---

## 5. Stage A — a dashboard served by the charger

No firmware change, no case opened. The module's web server is on, unauthenticated, and its web
root `webapp/index.html` is empty but already configured, so a single uploaded file becomes the
home page.

**It can show:** identity and firmware, network and signal strength, uptime, the fault log, lifetime
energy, whether it is charging, a 5-minute power curve, the session list, and 92 days of history.
**It cannot show** live current, voltage or temperature, or offer control: those exist only in the
UDP telemetry. Formats: [JuiceNet-Protocol.md](juicebox/JuiceNet-Protocol.md).

**Steps:**

1. **A0, read-only probes:** `GET /log`, `ls -v`, `/command_help.csv`, and the stock recovery page.
2. **A0b, the mailbox test:** can a browser write a small file through `file_create`, read it back
   and delete it? This decides Stage B's transport, and it is testable today.
3. **A1–A3:** build the page offline against a backup of the module's files, then upload it as one
   self-contained HTML file. One request in flight at a time, because the module accepts only three
   clients.
4. **A4:** raw-file download links, so the data stays recoverable whatever the page decodes.

The same page becomes the control surface after the port, and the GUI for any helper app before it.

---

## 6. Stage B — the OpenEVSE port

OpenEVSE on the existing ATmega328P, with the page served by the existing AMW106. Every step that
cannot be undone is gated.

| Phase | What | Gate |
|---|---|---|
| **0. Recon** | Read the side sticker for the PCB revision. Triage the spare board | Opens nothing, buys nothing |
| **1. Access** | Unplug from mains, open the enclosure, find the programming interface and where the WiFi module's UART meets the ATmega | Mains **unplugged**, not just the breaker |
| **2. Dump** | Read flash and EEPROM twice; confirm identical and not blank. Read fuses and lock bits over ISP | **Hard gate.** The dump is the only way back |
| **3. Pin map** | Establish every safety-critical pin electrically, using the three published maps as hypotheses | Any disagreement blocks Phase 4 |
| **4. Flash** | Edit the pin block, add an ATM90E26 driver if needed, rebuild, flash the spare first. No chip erase | Rehearsed on the bench first |
| **5. Bring-up** | RAPI checks, relay, GFI, pilot state transitions; calibrate current against a clamp meter | Full RAPI table green |
| **6. Interface** | The browser reaches RAPI through the module | See transports below |

**The spare board is a bench rehearsal target and a programming tool only.** It is never installed
in place of the working unit's board. With chip swaps ruled out, the Phase 2 dump is the **only**
revert path.

**Transport for Phase 6:**

| | Transport | Module firmware | Status |
|---|---|---|---|
| **T1** | A mailbox over the stock web command interface: the browser writes a small file or variable; the reflashed ATmega polls it over its serial link and writes status back | Unchanged | **Default.** Its one unknown is the A0b test |
| **T2** | A custom module app acting as a RAPI gateway | Replaces `JB1_0.zap` | Allowed, but needs JTAG inside the enclosure, a vendor build service that may refuse this device, and a 32 KB code budget |

The earlier design, a RAPI tunnel through the module's "stream mode" on port 2000, **does not work**:
ZentriOS has no way to make a WebSocket the stream-mode connection, forbids reading or writing a
stream-mode stream, and port 2000 is the remote command shell.

---

## 7. Next steps

1. **Owner, zero risk:** read the side sticker and triage the spare board. This picks the pin-map
   hypothesis, tells us whether the metering chip and heater exist, and decides whether every
   irreversible step can be rehearsed first.
2. **Desk:** follow the five research leads in §8.
3. **Desk:** Stage A. A0, A0b, then the dashboard.
4. **Desk:** port preparation: a working PlatformIO build, an ATM90E26 driver if the board is 8.12 or
   later, and a pin block switchable per board revision.
5. **Optional:** a Windows helper service to replace the manual interim procedure. Go is the easiest
   toolchain; the Stage A page doubles as its GUI.

---

## 8. Remaining research leads

The broad searches are finished and closed: Gecko OS, custom ZAP tooling, the V8.10 source (found),
archive.org, forum and code hosts, and the vendor setup app. What remains targets the 8.14+ board:

1. **FCC filing internal photos** of the JuiceBox itself, not just its WiFi module.
2. **OpenEVSE's install guide** for its JuiceBox v1 replacement electronics, for its photos of the
   stock board and connectors. The guide is the value; the kit stays out of scope.
3. **Two unread forum threads:** myrav4ev "How to modify JuiceBox firmware", and the 11-page
   MyNissanLeaf JuiceBox thread.
4. **Software Heritage copies** of the deleted EMotorWerks GitHub organization: the DipTrace
   libraries' legacy folder, and `Validation-JBFirmware`.
5. **Contacting Matt Falcon** (`FalconFour`), who wrote the v8.12 test firmware. The owner's decision.

After these, what is left needs the sticker, the spare board, or the enclosure open.

---

## 9. Watch items

| Item | Why it matters |
|---|---|
| Module fault count, now 3 of 8 | At 8 the module enters Safe Mode and attempts a firmware update on its own, against a vendor server that still answers |
| The vendor directory service coming back | Would end the DNS redirect and could switch the charger to encrypted telemetry |
| Helpers stop with the PC session | The charger stays pointed at a dead resolver until it reboots |
| Every module reboot | Returns the charger to the cloud, which pushes 40 A |

---

## 10. Decisions

| Date | Decision |
|---|---|
| 2026-09-22 | Board replacement, e.g. the JuiceRescue controller, rejected: the goal is to port OpenEVSE to this chipset |
| 2026-09-23 | Goal revised: existing hardware stays intact; firmware reflashing allowed; no kit purchase |
| 2026-09-23 | Gecko OS closed: no build exists for the AMW106, and its only successor part would be a module swap |
| 2026-09-24 | Charge limit set to 26 A, whole amps |
| 2026-09-24 | Helper PC: ICS removed; Windows firewall repaired and left off |
