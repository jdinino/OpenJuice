# OpenJuice — Functional Specification

**Version:** 0.2 DRAFT · **Date:** 2026-09-24 · **Status:** pre-hardware; not yet flashed to any unit

This specifies the port of [OpenEVSE](https://github.com/OpenEVSE/open_evse) onto the JuiceBox
Gen 1's existing ATmega328P, and the local interface served by its existing WiFi module. For current
project state, the interim control procedure and the roadmap, see [STATUS.md](../STATUS.md). For the
wire protocol and the module's interfaces, see [JuiceNet-Protocol.md](JuiceNet-Protocol.md).

Evidence tiers: **[V]** verified on the reference unit · **[D]** documented by a primary source ·
**[I]** inferred. A changelog from the v0.1 specification is in Appendix D.

---

## 1. Overview

### 1.1 Purpose

Enel X Way shut down its North American JuiceBox service in October 2024. The chargers still charge,
but lost local visibility and control. OpenJuice restores both by replacing the charging
controller's firmware with OpenEVSE, remapped to the JuiceBox's pins, and serving a status and
control page from the WiFi module the charger already has.

### 1.2 Scope

| In scope | Out of scope |
|---|---|
| Reflashing the existing ATmega328P with OpenEVSE | Replacing the PCB, the ATmega, a Pro Mini carrier or the WiFi module |
| Firmware changes to the AMW106 WiFi module, if the interface needs them | Buying a swappable kit (JuiceRescue controller, ESP32 gateway) |
| A page served by the existing WiFi module | Cloud, MQTT and OCPP connectivity |
| Pin remap, GFI D-latch reset, pilot, metering, relay | The LCD and button menu |
| RAPI control | ADVPWR dual-relay sensing |

Clip-on programming tools, a USB-serial adapter, an ISP programmer or a JTAG pod, are tools, not
hardware changes: nothing is left installed.

### 1.3 Related projects

| Project | Relationship |
|---|---|
| [OpenEVSE](https://github.com/OpenEVSE/open_evse) | Upstream firmware; we add a JuiceBox build target |
| [JuiceRescue](https://github.com/JuiceRescue/juicepassproxy) | Community JuiceNet reverse engineering and a proxy |
| eMotorWerks JuiceBox firmware | The stock firmware, GPL v3; source recovered for V8.6 through V8.10, and a v8.12 factory test build. The source of the per-revision pin maps in §3 |

---

## 2. Hardware

### 2.1 Block diagram (revision-agnostic)

```
            ┌──────────────────────── JuiceBox Gen 1 ────────────────────────┐
            │                                                                 │
 AC 240V ───┤── Relay ─────────────────────────────────── J1772 connector    │
            │      │                                            │             │
            │  Current sensing ──────┐                     Pilot generate ────┤─► pilot
            │  (CT on ADC, or an     │                     Pilot sense        │
            │   ATM90E26 on serial   │                                        │
            │   from v8.12)          ▼                                        │
            │                  ┌───────────┐   UART    ┌──────────────┐       │
            │  GFI sense ─────►│ ATmega328P│◄─────────►│   AMW106     │◄──────┤ WiFi/LAN
            │  GFI test  ◄─────│  (OpenJuice│  RAPI     │  WiFi module │       │
            │  GFI latch reset │  after the │           │  (unchanged) │       │
            │                  │  port)     │           └──────────────┘       │
            │                  └───────────┘                                   │
            │                      │ programming header (serial and/or ISP)    │
            └─────────────────────────────────────────────────────────────────┘
```

Which ATmega pin performs each function, and how the WiFi module's UART reaches the ATmega, depends
on the board revision. See §3.

### 2.2 Charging controller

| Parameter | Value |
|---|---|
| MCU | ATmega328P, 16 MHz, 5 V |
| Flash / SRAM / EEPROM | 32 KB / 2 KB / 1 KB |
| Bootloader | **ATmegaBOOT_168, 2 KB, 57600 baud** **[D]**, not Optiboot. eMotorWerks' documented target is "Arduino Pro or Pro Mini 5V 16 MHz", i.e. `upload.speed=57600`, `maximum_size=30720`. Connecting at 115200 fails with `stk500_getsync()` and looks like no bootloader. Unconfirmed on 8.14+ **[I]** |

The v8.12 test firmware notes that only pins 2 and 3 can serve interrupts "on Pro Mini", which
suggests that board still carries a Pro Mini daughterboard **[D]**. That bears on where the
programming header is, and on whether the controller is socketed.

### 2.3 WiFi module

| Parameter | Value |
|---|---|
| Module | Zentri **AMW106** **[D]**. The ZentriOS-WZ 3.6 command reference this unit runs lists AMW004/AMW106/AMW136; AMW006 is the older WiConnect part. The unit reports no part number of its own, so confirm visually |
| Firmware | ZentriOS-WZ 3.6.4.0, app `EMWERK-JB_1_1-1.4.0.28` **[V]**. The final ZentriOS-WZ release; no Gecko OS build exists for this part |
| Link to the ATmega | UART, 9600 8N1. SoftwareSerial on D2/D4 on V8.9 and V8.10 **[D]**; probably the hardware pins D0/D1 from v8.12 **[I]**; unconfirmed on 8.14+. The module's app composes the telemetry from data the ATmega supplies **[V]**; the dialogue itself is unknown. See [JuiceNet-Protocol.md §1.3](JuiceNet-Protocol.md) |
| Role | **Owns the JuiceNet cloud link** through its app `JB1_0.zap` **[V]**, and re-enables DHCP at each boot. Left in place by the port; **never disabled**, since it also brings up WiFi and cannot be backed up |

The module's interfaces, the flash logs and the cloud handshake are documented in
[JuiceNet-Protocol.md](JuiceNet-Protocol.md).

---

## 3. Pin mapping

> ⚠️ **The patch encodes the V8.9 map. It is not correct for later boards, and the reference unit is
> 8.14 or later.** Establish every safety-critical pin electrically before flashing. A wrong relay
> or GFI pin on a 40 A circuit is the failure that matters.

### 3.1 What the published revisions show

From eMotorWerks' own source and factory test firmware. Each column is a real, different board.
Where a function moved, it is in **bold**.

| Function | V8.9 (our patch) | V8.10 | v8.12 |
|---|---|---|---|
| GFI trip input | D3 (INT1) | D3 | D3 |
| GFI latch reset | D7 | D7 | D7 |
| Pilot PWM | D9 (OC1A) | D9 | D9 |
| Remote button A | D11 | D11 | D11 |
| Main relay | D5 | D5 | **A3** |
| GFI test | **D12** | **A0** | **D6** |
| WiFi module reset | none | **D12** | **D12** |
| Pilot sense | **A0** | **A6** | A6 |
| Voltage sense | **A1** | **A7** | A7 |
| Current sense | **A2** (CT) | A2 (CT) | **thermistor; current via ATM90E26** |
| PCB heater | D13 | **A1** | none seen |
| Buzzer | shared on D13 | — | D13 |

Only GFI trip, GFI latch reset, pilot PWM and remote button A held across all three. Expect the
8.14+ board to differ again.

Sources: `research/v810-hunt/community/` (V8.9 and V8.10 in `JB_firmware_V8_10_7.ino`) and the
`vinay-emw/JuiceBoxTester` repository (v8.12). Both are catalogued in
[RESEARCH-INDEX.md](../RESEARCH-INDEX.md).

### 3.2 The patch's V8.9 pin block

`open_evse.h` under `#ifdef JUICEBOX_GEN1`, current values, **V8.9 only**:

```cpp
#define PILOT_PIN        0     // pilot sense on ADC0/A0
#define PILOT_IDX        1     // OC1A (PB1/D9) for the PWM
#define CURRENT_PIN      2     // CT on ADC2/A2
#define VOLTMETER_PIN    1     // voltage divider on ADC1/A1
#define GFI_INTERRUPT    1     // INT1 on PD3/D3
#define GFITEST_PIN      12    // PB4/D12
#define GFI_LATCH_RESET_PIN 7  // PD7, active-LOW pulse to clear the latch
#define CHARGING_IDX     5     // relay on PD5/D5
```

Phase 4 of the port edits this block to the verified map. The block should become switchable per
revision, so the bench result selects a column rather than rewriting the file.

### 3.3 Current sensing differs by revision

V8.9 and V8.10 read a current transformer on an analog pin. **From v8.12 the board carries an
ATM90E26 energy-metering chip** read over a serial link **[D]**. If the reference board follows
v8.12, the port needs an ATM90E26 driver in place of OpenEVSE's analog ammeter and voltmeter. A
reference driver exists in the v8.12 test firmware, but it carries no license, so a clean-room
driver from the chip's datasheet is required.

A later data point **[D]**: the teardown of a **JuiceBox 40** in the Zero Day Initiative's Pwn2Own
hardware write-up shows an **Atmel M90E36A** (a three-phase sibling of the ATM90E26) beside the
ATmega328P, with a Silicon Labs WGM160P WiFi module rather than our AMW106. That is a newer unit
than this reference charger, so it only bounds the possibilities: the 8.14+ board most likely uses
an ATM90E26 as v8.12 does, but an M90E36A is possible. The chip is read the same way, over a serial
link, so the driver work is similar either way. The write-up carries labelled PCB photos (its
Figures 12–14), a candidate source for the board-photo research lead.

---

## 4. Functional requirements

### 4.1 J1772 pilot

PWM on D9 via Timer1 OC1A, phase-and-frequency-correct, 1 kHz, encoding 6–80 A per J1772. OpenEVSE
supports `PILOT_IDX == 1` already. **The build must pass `-D PAFC_PWM`**; the current patch does not,
so this needs adding and verifying.

### 4.2 Pilot sensing

A resistor divider on the pilot line reports the EV state. State thresholds in the patch are
calculated from the V8.9 divider and **must be verified with an EV or a J1772 simulator**, and tuned
over RAPI. On later boards the divider ratio may differ.

### 4.3 Current and voltage

| | V8.9 / V8.10 | v8.12 and later |
|---|---|---|
| Current | CT on an analog pin, scaled | ATM90E26 over serial |
| Voltage | divider on an analog pin | ATM90E26 |
| Calibration | scale factor, tuned against a clamp meter over RAPI `$SA` | driver register configuration |

The patch's scale factor of 90 is theoretical and must be calibrated on a real load.

### 4.4 GFI

Ground-fault detection is on an interrupt pin, INT1/D3 on the boards seen. OpenEVSE defaults to
INT0/D2, so the interrupt vector is remapped. From V8.9 the board adds a hardware latch that holds a
fault until cleared, which OpenEVSE has no equivalent for; the port pulses the latch-reset pin
(D7, active low, about 100 ms) in `Gfi::Init`, before reads, and around the self-test.

**GFI self-test is currently disabled** in the build, as a side effect of excluding `UL_COMPLIANT`.
Detection is unaffected. Decide deliberately in Phase 5 whether to add `-D GFI_SELFTEST`: the pin
mappings exist, but the stock hardware drives a GFCI-tripping relay, which may not follow OpenEVSE's
60 Hz test pulse. A self-test that fails every boot is worse than none.

### 4.5 Relay

Single relay, energized to charge. Pin is D5 on V8.9 and V8.10 but **A3 on v8.12** — the highest-risk
disagreement in §3.1, because a command meant for the relay would otherwise hit the metering chip's
serial line.

### 4.6 RAPI

Text command protocol on the hardware UART, D0/D1. Commissioning commands: `$GV` version, `$GS`
state, `$GC`/`$SC` current capacity, `$GG` current and voltage, `$GF` fault counts, `$FE`/`$FD`
enable and disable, `$SA` ammeter scale. **Whether D0/D1 is free or is the link to the WiFi module on
8.14+ must be established in Phase 1** before a serial adapter is attached (§7, risk R10).

---

## 5. Build

### 5.1 PlatformIO

```ini
[env:juicebox_gen1]
platform = atmelavr
board = pro16MHzatmega328
framework = arduino
upload_protocol = arduino     ; serial bootloader; preserves it
upload_speed = 57600          ; ATmegaBOOT_168, not 115200
; NO chip erase: -e destroys the bootloader and the stock EEPROM identity
build_src_flags =
    -D JUICEBOX_GEN1
    -D AMMETER -D VOLTMETER
    -D RAPI -D RAPI_SERIAL
    -D GFI_LATCH_RESET
    -D NO_AUTOSVCLEVEL
    -D DEFAULT_SERVICE_LEVEL=2
    -D DEFAULT_CURRENT_CAPACITY_L2=30
    -D MAX_CURRENT_CAPACITY_L2=40
    -D DEFAULT_CURRENT_SCALE_FACTOR=90
    -D SERIAL_BAUD=115200
```

**Known gaps between this and the committed patch**, to reconcile in Phase 4:

- The patch does not pass `-D PAFC_PWM`, although §4.1 needs it.
- The patch does not pass `-D GFI_SELFTEST` (§4.4).
- The patch's `platformio.ini` still carries `upload_flags = "-e -B0.5"`, i.e. it still chip-erases.
  Remove `-e` before any flash.

### 5.2 Excluded features

`ADVPWR`, `OEV6`, `BTN_MENU`, `RGBLCD`, `MENNEKES_LOCK`, `RELAY_PWM` and `PP_AUTO_AMPACITY` are all
off: no hardware for them. `TEMPERATURE_MONITORING` is off in the build, but the hardware **does**
have a temperature sensor (§3.1), so it could be enabled once the sensor pin is confirmed.

---

## 6. Files changed from upstream

| File | Change |
|---|---|
| `platformio.ini` | add the `[env:juicebox_gen1]` environment |
| `open_evse.h` | the `#ifdef JUICEBOX_GEN1` pin block and flags |
| `Gfi.h` / `Gfi.cpp` | latch-reset member and `ResetLatch()` |
| `J1772EvseController.cpp` | JuiceBox pilot thresholds |

`J1772Pilot.cpp`, `rapi_proc.*` and `main.cpp` need no changes for V8.9.

---

## 7. Commissioning

Follow the phase gates in [STATUS.md](../STATUS.md) §6. The safety-critical rules:

1. **Dump first.** No stock firmware dump exists and none was published. Read flash and EEPROM twice,
   confirm the two reads hash identically and are not blank `0xFF`, and read fuses and lock bits over
   ISP. The EEPROM holds the unit's identity and meter calibration and is irreplaceable. **This dump
   is the only way to undo a flash**, since chip swaps are out of scope.
2. **Mains unplugged** for any ISP or enclosure work. It is a plug-in unit, so unplugging is the
   correct isolation, not the breaker.
3. **No chip erase.** OpenEVSE fits in the bootloader's 30,720 bytes, so the bootloader is kept.
4. **Establish safety-critical pins electrically** before flashing (§3).
5. **Rehearse on the spare board first** where possible.

### 7.1 Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Pilot thresholds wrong; EV not detected | High | Verify with a simulator; tune over RAPI |
| R2 | Current scale wrong; over-current | **Critical** | Calibrate against a clamp meter; the hardware CT or metering chip caps it |
| R3 | GFI latch or self-test timing wrong | Medium | Start at 100 ms; decide the self-test on the bench (§4.4) |
| R4 | **Chip erase wipes the stock EEPROM identity** | **Critical** | Dump first; never pass `-e` |
| R5 | **ISP lines carry live functions** on V8.9: D11 the RF receiver, D12 a GFCI relay, D13 a heater | High | ISP only with mains unplugged; if sync fails, suspect D11 first |
| R8 | **Pin map is V8.9; this board is 8.14+** and every published revision differs (§3) | **Critical** | Establish each safety-critical pin electrically before flashing |
| R9 | **No stock firmware dump exists**; a flash is irreversible | **Critical** | The Phase 2 dump gate. Chip swaps are out of scope, so this is the only revert path |
| R10 | **D0/D1 is probably the WiFi-module link on 8.14+**, not a free serial port; RAPI output would reach the module | High | Trace where the module's UART meets the ATmega before attaching an adapter. Capture the stock dialogue with a receive-only tap before flashing |
| R13 | **D12 resets the WiFi module on V8.10 and v8.12**, but the V8.9 patch pulses it as the GFI test pin | High | Hold D12 inactive on later boards; move the GFI test to the verified pin |
| R14 | **The vendor WiFi app loses its data source after the port**; its reaction is unknown, and it must keep running to bring up WiFi | High | The pre-flash capture shows what it expects; rehearse on the spare board if it has a module |
| R11 | **Metering moved to an ATM90E26 from v8.12** | High | If the board follows v8.12, write a driver; do not assume an analog CT |
| R12 | **WiFi module Safe Mode at 8 faults**; it then attempts an OTA on its own. The helper also pauses control at 6, and **while paused the 26 A cap is unenforced** — 2026-10-12 the module held 40 A for ~2 h and the car drew 31.7 A | Medium | Watch the fault count (§ STATUS watch items); keep the PC awake so outages stop adding crashes; clear the log with `faults_reset` before it reaches 6; do not provoke crashes |

---

## 8. The interface

The port turns the Stage A dashboard into a control surface. The browser reaches the ATmega's RAPI
through the existing WiFi module by the **mailbox** transport (STATUS §6, T1): the page writes a
small command file through the module's web command interface, the reflashed ATmega polls it over
the UART and writes status back the same way. No cloud, no DNS trick, nothing running off the
charger.

The earlier v0.1 design, a RAPI tunnel through the module's "stream mode" on port 2000, **does not
work** and is withdrawn (Appendix D). ZentriOS cannot make a WebSocket the stream-mode connection,
forbids reading or writing a stream-mode stream over the command interface, and port 2000 is the
remote command shell, not a bridge.

---

## Appendix A: board revisions

| Revision | Notes |
|---|---|
| V8.6 and earlier | Published schematic (V8.6); no GFI latch |
| V8.9 | GFI D-latch added; the map the patch encodes; PCB heater on D13 |
| V8.10 | GFI test and heater move to analog pins; pilot sense to A6; WiFi reset on D12 |
| v8.12 | Relay to A3; ATM90E26 metering; no heater seen; factory test firmware exists |
| 8.14+ | The reference unit. Map unpublished; establish on the bench |

## Appendix B: upstream compatibility

Based on OpenEVSE `master`. All changes are gated behind `#ifdef JUICEBOX_GEN1` and do not affect
other targets. If the port proves stable, submit it upstream as a board variant.

## Appendix C: what can and cannot be recovered from the module

Held for the reference unit: a 97-file backup of the module's flash (energy logs, `index.html`, the
CA certificate, three of five system binaries), and full `get all` configuration dumps. In
`research/`, catalogued in [RESEARCH-INDEX.md](../RESEARCH-INDEX.md).

**Not recoverable:** the vendor app `JB1_0.zap` and the two largest ZentriOS binaries refuse the file
API and HTTP. The app cannot be backed up, so any change that displaces it is irreversible. This is
why the module is left running the stock firmware.

## Appendix D: changelog from v0.1

The v0.1 specification (2026-02-27, revised through 2026-09-21) accumulated inline corrections; this
revision is rewritten. Substantive changes:

- **Scope.** WiFi-module firmware changes are no longer out of scope; a hardware swap, including an
  ESP32 WiFi gateway, is explicitly out, per the project owner's 2026-09-23 decision.
- **The WiFi module is not a passive pipe.** Its app owns the cloud link and writes the energy logs
  **[V]**. v0.1 called it a dumb bridge.
- **Pin map.** v0.1 presented the V8.9 map as this unit's. §3 now shows three published revisions
  differing at the relay, current sensing, GFI test and pilot pins, and states the patch is V8.9-only.
- **Current sensing.** From v8.12 an ATM90E26 replaces the analog CT (§3.3, R11).
- **Temperature.** v0.1 said "no sensor present". The board has a temperature sensor (§3.1, §5.2).
- **v0.2 interface.** The port-2000 stream-mode RAPI tunnel is withdrawn as protocol-wrong and
  replaced by the mailbox transport (§8). Risk W3, previously "resolved", was resolved wrongly.
- **Recovery.** The v0.1 fallback of flashing a spare Pro Mini and shelving the original is removed:
  it is a chip swap, out of scope. The Phase 2 dump is the only revert path (R9).
- Module Safe Mode at 8 faults added as a risk (R12).

## Appendix E: glossary

| Term | Meaning |
|---|---|
| EVSE | Electric Vehicle Supply Equipment, the charger |
| J1772 | SAE standard for AC charging connectors and pilot signalling |
| RAPI | OpenEVSE's text serial command protocol |
| GFI | Ground Fault Interrupter |
| CT | Current Transformer |
| ATM90E26 | A single-phase energy-metering IC, on v8.12+ boards |
| ISP | In-System Programming over SPI |
| PAFC_PWM | Phase-and-frequency-correct PWM, the pilot timer mode |
