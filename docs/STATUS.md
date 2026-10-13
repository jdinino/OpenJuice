# OpenJuice — Project Status

**Updated:** 2026-09-28 · **Reference unit:** JuiceBox Gen 1, PCB 8.14 or later, WiFi firmware
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
| Interim local control | **Working, unattended.** `juicebox_helper.py` keeps the limit, reattaches the charger after module reboots and recovers a hung module ([issue #1](https://github.com/jdinino/OpenJuice/issues/1)). Reboot-to-26 A recovery verified end to end in 87 s **[V]**. 26 A verified on a real charge: a multi-hour attended session on 2026-10-12/13 held the car pinned at 25.6–25.8 A under the 26 A cap with 0 of 8 faults and no reboots — the car wanted more than 26 A throughout, so the cap is an active throttle an attached helper enforces **[V]** |
| Stage A: dashboard on the charger | Not started. Every data format it needs is decoded **[V]** |
| Stage B: the OpenEVSE port | Patch written for **V8.9 only**; not flashable on this board. Phase 0 not started |
| WiFi module health | Reached **6 of 8** watchdog crashes (3 by 09-28, +1 on 10-04, +2 on 10-12, each during a PC-asleep / dead-resolver window); fault log **cleared to 0 of 8 on 2026-10-12** by owner-authorized `faults_reset` **[V]** |
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

This is the working stopgap until the port. It needs a PC on the same network running the helper,
`tools/juicebox/juicebox_helper.py`. Installed as a scheduled task, it starts at boot and keeps the
charger local without anyone watching, including across the module's reboots every one to two days.

**How it works.** The charger's DNS is pointed at the PC. The PC answers the charger's cloud
hostname with its own address, so the charger sends its UDP telemetry to the PC, which can read it
and reply with commands exactly as the cloud would.

**One-time setup, already saved on the reference unit:**

| Module variable | Value | Why |
|---|---|---|
| `wlan.static.ip` | the charger's address, e.g. `192.168.1.63` | used when DHCP is off |
| `wlan.static.dns` | the PC's address, e.g. `192.168.1.74` | points lookups at the helper |
| `wlan.static.gateway` | **the router**, e.g. `192.168.1.1` | never the PC: a sleeping PC would cut the charger's internet |

**Install the helper once,** from an elevated PowerShell. Details in
[../tools/README.md](../tools/README.md).

```powershell
powershell -ExecutionPolicy Bypass -File tools\juicebox\install_helper.ps1
python %LOCALAPPDATA%\OpenJuice\helper\juicebox_helper.py status
```

**What the helper does.** One process runs the resolver, the telemetry listener, a beacon listener
and a watchdog. While telemetry arrives it only listens. When telemetry stops for a minute it asks
the module one question, whether DHCP is on, and acts on the answer:

| Module state | Evidence | Helper action |
|---|---|---|
| Rebooted onto the cloud | Answers, DHCP on | Checks the saved static IP, gateway and DNS still lead to this PC and the fault count is below 6, then switches DHCP off for this boot and restarts WiFi. Corrects the limit the cloud pushed |
| Hung, as in issue #1 | Accepts connections, returns nothing, three probes in a row | `reboot`, then as above |
| Silent | Answers, DHCP off, no telemetry for 15 minutes | `reboot`, then as above |
| Away | No connection | Nothing |

Reboots are limited to one per 20 minutes and four per day. Limit corrections are capped at 12 a
day, because each one rewrites the charging controller's EEPROM. Every command the helper can send
to the module is on a fixed allowlist, and `save` is not on it.

**Verified 2026-09-28 [V].** After a commanded module reboot, the helper found the module on DHCP
63 s later and reattached it. The cloud had already pushed 40 A. One correction brought it back to
26 A, acknowledged 87 s after the reboot, with no one involved. The hang branch is covered by tests
against a simulated module, since a real hang cannot be induced safely.

**By hand, when the helper is not installed:**

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
command restores yours. **The charger does not fall back to 26 A on its own.** It was once assumed
**[I]** that each accepted command set an "offline limit" the module reverted to after a few minutes,
so the cap would survive a reboot unattended; **2026-10-12 disproved that [V].** While the helper was
blocked (at 6 faults) the module sat at its 40 A ceiling for about 2 hours and the car drew 31.7 A —
well above 26 A — until local control was restored. Only an **attached, actively-correcting helper**
holds the cap; a reboot, or a `blocked`/`released` helper, leaves the module at 40 A. (The earlier
"26 A held through the 10-04 standby" reading was most likely just the car not demanding more than
26 A then, not an enforced offline limit.) The car's onboard charger tops out near 32 A, so an
uncapped session runs at ~32 A, and the 26 A cap is an active throttle, not a value the car would
stay under on its own.

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
  at a dead resolver cannot reach anything. After about 90 minutes of that, the module hung
  ([issue #1](https://github.com/jdinino/OpenJuice/issues/1)), and one of the three watchdog crashes
  happened that way. The installed helper is the fix. Before taking the PC away for a long time,
  run `juicebox_helper.py release`, then `attach` on return.
- **The charger's saved DNS is the PC's literal address.** If the PC's address ever changes, the
  helper refuses to reattach and says why. The owner has chosen to leave the PC's addressing alone.
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

**Design decision (2026-10-02): mirror the OpenEVSE web UI, do not invent a bespoke one.** A custom
dashboard marches away from the goal, which is an OpenEVSE-style charger. We copy as much of the
real OpenEVSE interface as possible, straight from upstream, and only *remove* features we cannot yet
feed. The upstream UI is **[`OpenEVSE/openevse-gui-nightshift`](https://github.com/OpenEVSE/openevse-gui-nightshift)**,
the GUI submodule the current ESP32 gateway firmware
([`openevse_esp32_firmware`](https://github.com/OpenEVSE/openevse_esp32_firmware)) embeds (branch
`RePartition`), most-starred and actively maintained. It normally runs on the ESP32 gateway and
talks to the controller over RAPI via an HTTP/WebSocket API; on the JuiceBox the AMW106 module plays
that gateway role. Stage A reproduces its look and screens, backed for now by the flash logs and the
PC helper's telemetry, and switched to the real RAPI API after the Stage B port. Licence: OpenEVSE
UI is GPLv3, compatible with vendoring under the repo with headers preserved.

**Steps:**

1. **A0, read-only probes:** `GET /log`, `ls -v`, `/command_help.csv`, and the stock recovery page.
2. **A0b, the mailbox test: passed 2026-10-02 [V].** Over HTTP, `file_create` wrote a 16-byte
   file, a plain `GET` read it back, and `file_delete` removed it, about 0.3 s per request.
   `file_create` on an existing name fails, so an update is delete then create. This proves the
   browser half of transport T1. The ATmega half, reaching the same files over the UART, depends on
   whether the vendor app owns that UART, which only the Phase 1 capture can show.
3. **A1–A3:** build the page offline against a backup of the module's files, then upload it as one
   self-contained HTML file. One request in flight at a time, because the module accepts only three
   clients.
4. **A4:** raw-file download links, so the data stays recoverable whatever the page decodes.

The same page becomes the control surface after the port, and the GUI for any helper app before it.

**Self-hosted vs helper (determined 2026-10-02; advisor tool was unavailable, so this is the
model's own analysis).** A fully self-hosted dashboard, served by the charger with no PC, is
achievable and is the end goal. It is not achievable for *live* data on the stock firmware:

- **Live values are not on the module.** Current, voltage, temperature and state exist only in the
  outbound telemetry stream; the module's flash holds history only (ELife/ECache/Events). So a
  module-served page can show history self-hosted today, but for live data before the port a helper
  is required, because the helper is the only place the live stream is readable.
- **After the port it flips to self-hosted.** OpenEVSE on the ATmega emits status over RAPI; via the
  T1 mailbox the ATmega writes that status into the module and the module-served page reads it, no PC
  involved. This matches the goal.

Two design consequences, both manageable:

- **Adapt the UI transport from push to poll.** The nightshift UI listens on a `/ws` websocket only
  OpenEVSE's gateway firmware serves, which the stock module cannot run. Feed the same UI by polling
  a status endpoint instead; the page is served by the module, so it polls same-origin with no look
  change.
- **Mailbox = a module variable, not a file.** The ATmega writes status into a ZentriOS variable the
  browser reads with `get`; a variable is RAM-backed, so a 1–2 s refresh does not wear the flash the
  way rewriting a file would. (Files remain the transport for larger or persistent payloads.)

Risk: the mailbox depends on the reflashed ATmega being able to drive the module UART, which the
Phase 1 capture resolves. If the vendor app blocks that link, the fallbacks are a custom module app
(T2) or keeping the helper.

---

## 6. Stage B — the OpenEVSE port

OpenEVSE on the existing ATmega328P, with the page served by the existing AMW106. Every step that
cannot be undone is gated.

| Phase | What | Gate |
|---|---|---|
| **0. Recon** | Read the side sticker for the PCB revision. Triage the spare board | Opens nothing, buys nothing |
| **1. Access** | Unplug from mains, open the enclosure, find the programming interface and where the WiFi module's UART meets the ATmega. Then capture the stock ATmega-to-module dialogue with a receive-only tap at 9600 baud, before anything is flashed | Mains **unplugged** for all probing and clip-on work |
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
| **T1** | A mailbox over the stock web command interface: the browser writes a small file or variable; the reflashed ATmega polls it over its serial link and writes status back | Unchanged | **Default.** Browser half proven by the A0b test **[V]**; the ATmega half waits on the Phase 1 UART capture |
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
5. **Done 2026-09-28:** a Windows helper service replaces the manual interim procedure:
   `juicebox_helper.py` plus a scheduled task. Written in Python to reuse the protocol code.
   Remaining: the owner runs the installer, and a PC reboot confirms it starts at boot.

---

## 8. Remaining research leads

The broad searches are finished and closed: Gecko OS, custom ZAP tooling, the V8.10 source (found),
archive.org, forum and code hosts, and the vendor setup app. What remains targets the 8.14+ board:

1. **FCC filing internal photos** of the JuiceBox itself, not just its WiFi module.
2. **OpenEVSE's install guide** for its JuiceBox v1 replacement electronics, for its photos of the
   stock board and connectors. The guide is the value; the kit stays out of scope.
2b. **The ZDI Pwn2Own hardware teardown** (`zerodayinitiative.com/blog/2023/11/28/...`), labelled
   PCB photos of a JuiceBox 40. It is the newer WGM160P/Gecko OS board, not our AMW106 unit, so the
   photos are reference-only.

**The CVE-2024-23938 avenue was assessed and closed 2026-10-02 [V].** Question asked: could the
Pwn2Own code-execution bug be a way to take control of this module? Findings:

- **Feature present, OS different.** Our unit fingerprints as `ZentriOS-WZ-3.6.4.0` and does carry
  the templated-message feature the advisory concerns (`system.msg` plus `@`-substitution event
  templates). But the advisory's defect is in **Gecko OS 4.2.7**, a newer OS on a newer module
  (WGM160P). The same defect is not established in 3.6.4.0, and the code differs between the two.
- **A hard prerequisite we cannot meet.** Confirming or using a memory-corruption defect needs the
  module's firmware image to analyse. §3.7 of the pentest report established that this unit's images
  are unextractable by software and unpublished. No image, no analysis, and no public exploit to
  adapt.
- **It would not advance the goal even if it worked.** We already hold broad control of the module
  through its own unauthenticated command API over HTTP (read/write settings, create and serve
  files, reboot, GPIO — the mailbox test exercised this). Code execution would add essentially one
  unique capability, a dump of the sealed flash, which the port does not need. Control toward the
  goal comes from reflashing the ATmega and serving the dashboard from the module's existing web
  server, neither of which needs a defect.

Conclusion: **out of scope** as a control path, on feasibility and on value. Not a refusal of the
owner's own-device research; simply a dead end on the merits.
3. **One unread forum thread:** the 11-page MyNissanLeaf JuiceBox thread. (The myrav4ev "How to
   modify JuiceBox firmware" thread was read 2026-10-02: it covers only the ATmega over an FTDI
   cable, no WiFi-module firmware, confirming the public-source pattern.)
4. **Software Heritage copies** of the deleted EMotorWerks GitHub organization: the DipTrace
   libraries' legacy folder, and `Validation-JBFirmware`.
5. **Contacting Matt Falcon** (`FalconFour`), who wrote the v8.12 test firmware. The owner's decision.

After these, what is left needs the sticker, the spare board, or the enclosure open.

---

## 9. Watch items

| Item | Why it matters |
|---|---|
| Module fault count (hit 6 of 8 on 10-12, cleared to 0) | At 8 the module enters Safe Mode and attempts a firmware update on its own, against a vendor server that still answers. At **6** the helper's fault guard pauses control (`blocked`) and the cap goes unenforced until the owner clears the log with `faults_reset`. Clear it before it reaches 6, and keep the PC awake so outages stop adding crashes |
| The vendor directory service coming back | Would end the DNS redirect and could switch the charger to encrypted telemetry |
| PC shut down, asleep or away | The charger points at a PC that is not answering. The helper recovers it at the next boot; a Windows shutdown does not hand it back first |
| Every module reboot or helper pause | The module runs at 40 A until an attached helper corrects it — about a minute after a normal reboot, but **up to hours if the helper is `blocked`/`released`** (as on 10-12). The car can pull its full ~32 A through that whole gap |

---

## 10. Decisions

| Date | Decision |
|---|---|
| 2026-09-22 | Board replacement, e.g. the JuiceRescue controller, rejected: the goal is to port OpenEVSE to this chipset |
| 2026-09-23 | Goal revised: existing hardware stays intact; firmware reflashing allowed; no kit purchase |
| 2026-09-23 | Gecko OS closed: no build exists for the AMW106, and its only successor part would be a module swap |
| 2026-09-24 | Charge limit set to 26 A, whole amps |
| 2026-09-24 | Helper PC: ICS removed; Windows firewall repaired and left off |
| 2026-10-12 | Owner authorized clearing the module fault log (`faults_reset`) after it reached 6 of 8; cleared to 0. Confirmed the 26 A cap is enforced only by an attached helper, not by any offline fallback |
