# OpenJuice — Functional Specification Document

**Project:** OpenJuice (OJ)
**Version:** 0.1 DRAFT
**Date:** 2026-02-27 (rev. 2026-07-14 — added §9.9 beacon discovery)
**Author:** OpenJuice Contributors

---

## 1. Overview

### 1.1 Purpose

OpenJuice ports the open-source **OpenEVSE** firmware to run on the **JuiceBox Gen 1** EVSE (Electric Vehicle Supply Equipment) hardware — without any hardware modifications. This gives JuiceBox owners a fully functional, locally-controlled EV charger after the Enel X / eMotorWerks cloud infrastructure was decommissioned in October 2024.

### 1.2 Problem Statement

JuiceBox Gen 1 units were designed as cloud-dependent devices. With the shutdown of `emw.juice.net`, `ocpp.juice.net`, and related eMotorWerks/Enel X services, these chargers lost all smart features (scheduling, energy monitoring, remote control). The stock firmware has no local fallback — charging still works, but all telemetry and control is gone.

### 1.3 Solution

Flash the ATmega328P MCU with OpenEVSE firmware, remapping pins to match JuiceBox hardware. This provides:

- **Local RAPI control** via serial (USB or WiFi module)
- **Real-time metering** (current, voltage, energy)
- **Configurable current limits** (6A–40A)
- **SAE J1772 compliant** pilot signal generation and state machine
- **GFI protection** with self-test
- **Open-source** — fully auditable safety-critical code

### 1.4 Scope

| In Scope | Out of Scope |
|---|---|
| ATmega328P firmware replacement | WiFi module (AMW106) firmware changes |
| Pin remapping (firmware only) | Hardware board modifications |
| GFI detection + D-latch reset | Cloud connectivity / MQTT / WiFi portal |
| J1772 pilot signal on D9 (OC1A) | LCD/button menu system |
| Current/voltage metering | Temperature monitoring (no sensor present) |
| RAPI serial protocol on D0/D1 | ADVPWR (advanced power supply sensing) |

### 1.5 Related Projects

| Project | Relationship |
|---|---|
| [OpenEVSE](https://github.com/OpenEVSE/open_evse) | Upstream firmware — we fork and add JuiceBox target |
| [JuiceRescueController](https://oshwlab.com/LarryMcGovern/juicerescuecontroller) | Drop-in replacement board ($129) — alternative approach |
| [JuiceBox protocol RE](https://github.com/snicker/juiceern) | Community reverse engineering of JuiceBox protocol |

---

## 2. Hardware Architecture

### 2.1 JuiceBox Gen 1 Block Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │              JuiceBox Gen 1                  │
                    │                                             │
  AC LINE ─────────┤─── Relay (D5) ──────────── J1772 Connector  │
  (240V L1/L2)     │        │                        │            │
                    │   Current Transformer ──── ADC2/A2          │
                    │   (18.5 A/V, 120Ω burden)                   │
                    │                                             │
                    │   Voltage Divider ──────── ADC1/A1          │
                    │   (120V:1V ratio)                           │
                    │                                             │
                    │   Pilot Generator ──────── D9/OC1A (PWM)    │
                    │   Pilot Sense ──────────── ADC0/A0          │
                    │   (100k/27k divider)                        │
                    │                                             │
                    │   GFI Sense ────────────── D3/INT1          │
                    │   GFI Test ─────────────── D12              │
                    │   GFI Latch Reset ──────── D7 (active LOW)  │
                    │                                             │
                    │   ┌──────────┐    SoftSerial     ┌────────┐ │
                    │   │ATmega328P│◄── D2/D4 9600 ───►│ AMW106 │ │
                    │   │ 16MHz 5V │    (ZAP protocol)  │ WiFi   │ │
                    │   │          │                    │ Module  │ │
                    │   │  D0/D1 ──┼── RAPI 115200 ──► │(unused) │ │
                    │   └──────────┘                    └────────┘ │
                    │        │                                     │
                    │   ISP Header (MOSI/MISO/SCK/RESET)          │
                    └─────────────────────────────────────────────┘
```

### 2.2 MCU Specifications

| Parameter | Value |
|---|---|
| MCU | ATmega328P-AU |
| Clock | 16 MHz external crystal |
| Flash | 32 KB |
| SRAM | 2 KB |
| EEPROM | 1 KB |
| Operating Voltage | 5V |
| Package | TQFP-32 (on JuiceBox board) |
| Bootloader | **ATmegaBOOT_168, 2 KB, 57600 baud** — *not* Optiboot. eMotorWerks' documented board target is "Arduino Pro or Pro Mini 5V, 16 MHz w/ ATmega328", which maps to `ATmegaBOOT_168_atmega328.hex` with `upload.speed=57600` and `maximum_size=30720` (= 32768 − 2048, confirming a 2 KB boot section). **Connecting at 115200 fails with `stk500_getsync()` and falsely suggests no bootloader exists.** Inferred from the documented update path; unconfirmed on PCB 8.14+. |

### 2.3 WiFi Module (Not Modified)

| Parameter | Value |
|---|---|
| Module | **Zentri AMW106** (inferred — see provenance note below; previously recorded as AMW006-A01.1) |
| Firmware | ZentriOS-WZ 3.6.4.0 (app `EMWERK-JB_1_1-1.4.0.28`) — live unit. A dev board sampled earlier ran WiConnect 2.2.0.12; see [JuiceBox-Gen1-Pentest-RE.md](JuiceBox-Gen1-Pentest-RE.md). |
| Interface to MCU | SoftwareSerial on D2(RX)/D4(TX) at 9600 baud |
| Protocol | ZAP (Zentri Application Protocol) |
| Status | Left untouched — WiFi module is independent |

> **Part-number provenance (corrected 2026-09-21).** Earlier revisions of this document said
> **AMW006**. The evidence favours **AMW106**: the ZentriOS-WZ 3.6 command reference that this unit
> actually runs lists its supported platforms as AMW004 / AMW106 / AMW136 — 242 occurrences of
> AMW106 across the archived docs versus 5 of AMW006, and those 5 are incidental TX-power asides
> rather than platform-support declarations. Computest Sector 7's teardown likewise attributes
> **AMW106** to ZentriOS-era JuiceBoxes, and AMW006 is the *WiConnect*-era part — which is exactly
> what the dev board in `research/amw006-firmware-backup/` ran. The live unit reports no part number
> of its own, so this remains inference; confirm visually when the case is opened. Directory names
> under `research/` still carry the old spelling.

---

## 3. Pin Mapping

### 3.1 Complete Pin Assignment Table

> ⚠️ **This table encodes the PCB V8.9 pin map and is UNVERIFIED for this unit (PCB 8.14+).**
> The stock V8.9 source states in its own header that it matches "V8.9 boards ONLY", and warns that
> pinouts "changed significantly between 8.7 and 8.9" and "will also change between 8.9 and 8.10
> versions". **No public source exists for 8.10 or later** — the archived `JuiceBox_Public/` index
> contains folders only up to 8.10, and eMotorWerks never published a schematic for any revision
> (the archived `Schematics/` directory holds a single 0-byte file named "COMING SOON").
> **Verify D3/D5/D7/D9/D12 electrically before flashing** — a wrong relay or GFI pin on a 40 A
> mains circuit is the failure mode that actually matters.
>
> Recovering the map from the stock firmware image was evaluated as a shortcut and is **not
> sufficient on its own**. `tools/avr_pinmap.py`, calibrated against the published `firmware_8.9.hex`,
> recovered the Timer1/pilot pins and the peripheral configuration but missed the relay, GFI sense,
> GFI test and latch reset — the stock firmware reaches those through Arduino's `digitalWrite()`
> with a variable pin number, which compiles to indirect register access. A linear opcode scan also
> cannot separate code from flash data tables. Use it to corroborate, not to decide; the electrical
> check above remains the primary method.
>
> ⚠️ **ISP hazard.** Three of these lines carry stock functions that fight the programmer: **D11**
> is driven by the RF remote receiver's output (an external push-pull driver on MOSI is the classic
> cause of ISP sync failure), **D12** drives a **GFCI-tripping relay**, and **D13** drives a 6 W
> heater pad and buzzer. Ordinary SPI traffic toggles all three as a side effect.
> **Only ever run ISP with the unit unplugged from mains.**

| ATmega328P Pin | Arduino Pin | JuiceBox Function | OpenEVSE Default | Remap Required |
|---|---|---|---|---|
| PD0 | D0 | UART RX (RAPI) | UART RX (RAPI) | No |
| PD1 | D1 | UART TX (RAPI) | UART TX (RAPI) | No |
| PD2 | D2 | SoftSerial RX (to WiFi) | GFI detect (INT0) | **Yes — freed** |
| PD3 | D3 | **GFI detect (INT1)** | N/A | **Yes — new** |
| PD4 | D4 | SoftSerial TX (to WiFi) | N/A | No |
| PD5 | D5 | **Relay control** | N/A | **Yes — new** |
| PD6 | D6 | (available) | GFI test | **Yes — freed** |
| PD7 | D7 | **GFI latch reset** | N/A | **Yes — new** |
| PB0 | D8 | (available) | Relay control | **Yes — freed** |
| PB1 | D9 | **Pilot PWM (OC1A)** | N/A | **Yes — new** |
| PB2 | D10 | (available) | Pilot PWM (OC1B) | **Yes — freed** |
| PB3 | D11 | **`pin_ctrlBtn_A` — RF remote receiver output** (shared with ISP MOSI) | ISP MOSI | No |
| PB4 | D12 | **`pin_GFItest` — drives a GFCI-tripping relay** (shared with ISP MISO) | ISP MISO | **Yes — new** |
| PB5 | D13 | **`pin_PCBHeater` — 6 W heating pad / buzzer** (shared with ISP SCK) | ISP SCK | No |
| PC0 | A0 | **Pilot voltage sense** | Current sense | **Yes — swapped** |
| PC1 | A1 | **Voltage sense** | Pilot voltage sense | **Yes — swapped** |
| PC2 | A2 | **Current sense** | Voltage sense | **Yes — swapped** |
| PC3 | A3 | (available) | N/A | No |

### 3.2 OpenEVSE Firmware Pin Defines

These `#define` values go in `open_evse.h` under `#ifdef JUICEBOX_GEN1`:

```cpp
#ifdef JUICEBOX_GEN1
// --- Pilot ---
#define PILOT_PIN        0      // Pilot sense on ADC0/A0
#define PILOT_IDX        1      // OC1A (PB1/D9) for PWM
#define PILOT_REG        &PINB

// --- Current Transformer ---
#define CURRENT_PIN      2      // CT sense on ADC2/A2

// --- AC Voltage ---
#define VOLTMETER_PIN    1      // Voltage divider on ADC1/A1

// --- GFI ---
#define GFI_INTERRUPT    1      // INT1 on PD3/D3
#define GFI_PIN          3      // PD3
#define GFI_REG          &PIND
#define GFITEST_PIN      12     // PB4/D12
#define GFI_LATCH_RESET               // Enable D-latch reset feature
#define GFI_LATCH_RESET_PIN    7      // PD7 — active LOW pulse to clear

// --- Relay ---
#define CHARGING_REG     &PORTD
#define CHARGING_IDX     5      // PD5/D5
#define CHARGING_PIN     PORTD5
#define CHARGINGOFF_REG  &PORTD
#define CHARGINGOFF_IDX  5
#define CHARGINGOFF_PIN  PORTD5

// --- Voltmeter calibration ---
#define DEFAULT_VOLT_SCALE_FACTOR  120  // 120V:1V divider
#define DEFAULT_VOLT_OFFSET        0
#endif
```

---

## 4. Functional Requirements

### 4.1 J1772 Pilot Signal Generation

| Requirement | Specification |
|---|---|
| PWM Output | D9/PB1 via Timer1 OC1A |
| PWM Mode | Phase-and-frequency-correct (PAFC) |
| Frequency | 1 kHz ± 0.5% |
| Voltage Levels | +12V (no EV), +9V/+6V/+3V (EV states), -12V |
| Duty Cycle | 10%–96% encoding 6A–80A per J1772 |
| Resolution | 0.6A per duty cycle step |

**Implementation Note:** OpenEVSE already supports `PILOT_IDX==1` (OC1A) in PAFC_PWM mode. The `#if (PILOT_IDX == 1)` conditionals in `J1772Pilot.cpp` (lines 36, 55, 82) handle OCR1A and COM1A1 — no changes needed to this file.

### 4.2 Pilot Voltage Sensing

The pilot return voltage indicates EV state. JuiceBox uses a **100k/27k voltage divider** on the pilot sense line (ratio = 27/(100+27) = 0.2126).

| J1772 State | Pilot Voltage | After Divider | ADC Count (5V ref, 10-bit) |
|---|---|---|---|
| A (No vehicle) | +12V | 2.55V | 522 |
| B (Connected) | +9V | 1.91V | 391 |
| C (Charging) | +6V | 1.28V | 261 |
| D (Ventilation) | +3V | 0.64V | 130 |
| F (Fault) | -12V | ~0V | 0 |

**Threshold midpoints** (halfway between adjacent states):

```cpp
#ifdef JUICEBOX_GEN1
THRESH_DATA = {456, 326, 196, 0, 130};
//              A/B  B/C  C/D  D/F  min-D
#endif
```

**Risk:** These are calculated values. Must be verified with an EV simulator or oscilloscope on real hardware. Fine-tuning via RAPI `$S0`/`$S1` commands.

### 4.3 Current Measurement

| Parameter | Value |
|---|---|
| ADC Input | A2 (ADC2) |
| Current Transformer | 18.5 A/V (typical JuiceBox CT) |
| Burden Resistor | 120 Ω |
| Scale Factor | 90 (DEFAULT_CURRENT_SCALE_FACTOR) |
| Calibration | Via RAPI `$SA` command with clamp meter |

**Calculation:**
- CT ratio: 3000:1 (typical)
- Burden: 120 Ω
- At 30A: secondary current = 30/3000 = 10mA, voltage = 10mA × 120Ω = 1.2V
- ADC count = 1.2V / 5V × 1024 = 245

Scale factor 90 is theoretical — **must be calibrated** against a clamp meter reading on a real load.

### 4.4 Voltage Measurement

| Parameter | Value |
|---|---|
| ADC Input | A1 (ADC1) |
| Divider Ratio | ~120:1 (240V → 2.0V at ADC) |
| Scale Factor | 120 (DEFAULT_VOLT_SCALE_FACTOR) |
| Offset | 0 |

### 4.5 GFI (Ground Fault Interrupt) Detection

| Parameter | Value |
|---|---|
| Sense Input | D3/INT1 (rising edge interrupt) |
| Test Output | D12/PB4 (generates test pulse) |
| Trip Threshold | ~5mA differential (hardware) |
| Self-test | At boot and periodically — pulse on D12, verify D3 triggers |
| Latch Reset | D7 active-LOW pulse, 100ms (see §4.6) |

**GFI Interrupt Change:** OpenEVSE defaults to INT0 (D2). JuiceBox uses INT1 (D3) because D2 is occupied by WiFi module SoftwareSerial RX. The interrupt vector and configuration registers differ:

```cpp
// INT0 (default OpenEVSE)
ISR(INT0_vect) { ... }
EICRA |= (1 << ISC01);  // falling edge
EIMSK |= (1 << INT0);

// INT1 (JuiceBox remap)
ISR(INT1_vect) { ... }
EICRA |= (1 << ISC11);  // falling edge
EIMSK |= (1 << INT1);
```

### 4.6 GFI D-Latch Reset (New Feature)

The JuiceBox V8.9 PCB includes a hardware D-type latch (likely 74HC74 or equivalent) that captures the GFI fault signal. Once triggered, the latch holds the fault state until explicitly cleared. OpenEVSE has no equivalent — this requires new code.

**Behavior:**
1. Normal state: D7 = HIGH (latch transparent)
2. GFI fault occurs: latch captures and holds fault on D3
3. To clear: pull D7 LOW for ≥100ms, then release HIGH
4. After clearing: D3 should return to idle state if fault condition is gone

**Integration points:**
- `Gfi::Init()` — set D7 as OUTPUT HIGH
- `Gfi::Reset()` — call `ResetLatch()` before reading GFI pin
- `Gfi::SelfTest()` — call `ResetLatch()` before/after test pulse sequence

```cpp
void Gfi::ResetLatch() {
    digitalWrite(GFI_LATCH_RESET_PIN, LOW);
    delay(100);
    digitalWrite(GFI_LATCH_RESET_PIN, HIGH);
    delay(10);  // settling time
}
```

### 4.7 Relay Control

| Parameter | Value |
|---|---|
| Output Pin | D5/PD5 |
| Logic | HIGH = relay energized (charging) |
| Type | Single relay (no ADVPWR dual-relay) |
| PWM Hold | Disabled (RELAY_PWM not defined) |

OpenEVSE default uses D8/PB0. JuiceBox uses D5/PD5 — handled by redefining `CHARGING_REG`, `CHARGING_IDX`, and `CHARGING_PIN`.

### 4.8 RAPI Serial Interface

| Parameter | Value |
|---|---|
| UART | Hardware UART on D0(RX)/D1(TX) |
| Baud Rate | 115200 |
| Protocol | RAPI (Remote API) — text command/response |
| Connection | USB-serial adapter or dev board |

Key RAPI commands for commissioning:

| Command | Description |
|---|---|
| `$GV` | Get firmware version |
| `$GS` | Get EVSE state (0=unknown, 1=A, 2=B, 3=C, 4=D, 5=fault) |
| `$GC` | Get current capacity (amps) |
| `$GG` | Get charging current and voltage |
| `$GF` | Get fault counts (GFI, ground, stuck relay) |
| `$SC nn` | Set current capacity to nn amps |
| `$SA nn` | Set ammeter scale factor |
| `$FE` | Enable EVSE |
| `$FD` | Disable EVSE |
| `$FR` | Reset EVSE |
| `$FF` | Enable/disable GFI self-test |

---

## 5. Build System

### 5.1 PlatformIO Configuration

New environment in `platformio.ini`:

```ini
[env:juicebox_gen1]
platform = atmelavr
board = pro16MHzatmega328
framework = arduino
upload_protocol = arduino  ; serial bootloader — preserves it (see §7.2)
upload_speed = 57600       ; ATmegaBOOT_168, NOT 115200 (see §2.2)
; upload_protocol = usbasp ; ISP fallback only if no bootloader responds; read §3.1 hazards first
;
; DO NOT add `-e`. Chip erase destroys the bootloader AND the stock EEPROM (R4, R9).
; Drift note: firmware/openevse-juicebox-gen1.patch specifies `upload_flags = "-e -B0.5"`.
; `-B0.5` is avrdude's BITCLOCK, not a fuse. The patch is authoritative for flag *names*;
; both erase settings are superseded by §7.2.
build_src_flags =          ; the patch uses build_src_flags, not build_flags
    -D JUICEBOX_GEN1
    -D AMMETER
    -D VOLTMETER
    -D RAPI
    -D RAPI_SERIAL
    -D GFI_LATCH_RESET
    -D NO_AUTOSVCLEVEL
    -D DEFAULT_SERVICE_LEVEL=2
    -D DEFAULT_CURRENT_CAPACITY_L2=30
    -D MAX_CURRENT_CAPACITY_L2=40
    -D DEFAULT_CURRENT_SCALE_FACTOR=90
    -D SERIAL_BAUD=115200
    -D 'VERSION="${common.version}.OJ"'
    -D SERIAL_BAUD=115200
```

### 5.2 Excluded Features

> ⚠️ **`GFI_SELFTEST` is OFF in this build, and that appears unintended.**
> The patch wraps `#define UL_COMPLIANT` in `#ifndef JUICEBOX_GEN1`, and `GFI_SELFTEST` is defined
> *inside* the `#ifdef UL_COMPLIANT` block in `open_evse.h`. Disabling UL_COMPLIANT therefore also
> disables the GFI power-on self-test, as a side effect of excluding `ADVPWR` (which *is*
> intended — §5.2). The patch does not pass `-D GFI_SELFTEST` to compensate.
>
> **Ground-fault *detection* is unaffected and remains ON.** `GFI` is default-defined in
> `open_evse.h` outside the UL_COMPLIANT block and the patch never disables it — which is why the
> `-D GFI` previously listed here was redundant rather than load-bearing. This is a missing
> self-test, not a missing protection.
>
> The patch already carries JuiceBox pin mappings for the self-test (`GFITEST_REG &PINB`,
> `GFITEST_IDX 4` → PB4/D12) guarded by `#ifdef GFI_SELFTEST`, so the capability is wired up and one
> flag away. **Decide deliberately:** add `-D GFI_SELFTEST` to restore the boot POST, or accept its
> absence — but §7.3 currently asserts a POST that does not run, so one of the two must change.
>
> Two further drifts corrected above: the patch does not pass `-D PAFC_PWM` either, though §4.1 and
> the "Files Confirmed Compatible" table both assume PAFC_PWM mode — verify before relying on it.
> And the patch still specifies `upload_flags = "-e -B0.5"`, i.e. **it still chip-erases**; §7.2 now
> forbids that, so `firmware/openevse-juicebox-gen1.patch` needs the same fix.

These OpenEVSE features are explicitly NOT enabled (no hardware support on JuiceBox Gen 1):

| Feature Flag | Reason for Exclusion |
|---|---|
| `ADVPWR` | No dual-relay, no AC sense on pilot |
| `OEV6` | OpenEVSE v6 board layout — different from JuiceBox |
| `BTN_MENU` | No button on JuiceBox |
| `RGBLCD` | No LCD display |
| `MENNEKES_LOCK` | No Type 2 locking actuator |
| `RELAY_PWM` | No relay PWM hold circuit |
| `TEMPERATURE_MONITORING` | No temperature sensors populated |
| `PP_AUTO_AMPACITY` | No proximity pilot detection |

### 5.3 Build Commands

```bash
# Build
cd C:/AI/open_evse
pio run -e juicebox_gen1

# Flash via USBasp ISP
pio run -e juicebox_gen1 -t upload

# Clean build
pio run -e juicebox_gen1 -t clean
```

---

## 6. Files Modified (from OpenEVSE upstream)

| File | Modification | Lines Changed (est.) |
|---|---|---|
| `platformio.ini` | Add `[env:juicebox_gen1]` section | +20 |
| `firmware/open_evse/open_evse.h` | Add `#ifdef JUICEBOX_GEN1` pin definitions block | +35 |
| `firmware/open_evse/Gfi.h` | Add `GFI_LATCH_RESET` member and method declaration | +8 |
| `firmware/open_evse/Gfi.cpp` | Add `ResetLatch()` implementation + calls | +25 |
| `firmware/open_evse/J1772EvseController.cpp` | Add JuiceBox pilot threshold values | +5 |

### Files Confirmed Compatible (No Changes)

| File | Why No Changes Needed |
|---|---|
| `J1772Pilot.cpp` | `PILOT_IDX==1` (OC1A/D9) already supported in PAFC_PWM mode |
| `rapi_proc.cpp/h` | RAPI on hardware UART works as-is |
| `main.cpp` | No board-specific logic |

---

## 7. Commissioning & Verification

### 7.1 Pre-Flash Checklist

> 🛑 **STOP — reversibility gate.** No dump of this unit's stock ATmega firmware exists, and
> eMotorWerks/Enel X never published one. **Flashing without first reading the chip out is a
> one-way door.** The EEPROM is the irreplaceable part: on JB1.x it holds the unit's identity
> (`IDstamp`), the meter calibration, and a checksum of the flash. Nobody has ever published a
> JuiceBox flash, fuse or lock-bit readout — completing this step would be the first.

**Backup — before anything else:**

> ⚠️ **Read this before issuing the first command.** Fuses and lock bits are **ISP-only** — serial
> bootloaders can read flash and EEPROM but *cannot* read fuses. And **the ISP header location on
> PCB 8.14+ is unresolved**: the archived V8.9 layout shows no ISP silkscreen at all, while a
> secondhand account describes a 9-pin SPI header beside a 12-pin on some revision. **Read §3.1's
> ISP hazard warning first** — D11, D12 and D13 all carry live stock functions.
>
> What *is* known, from the archived V8.9 board file
> (`research/emotorwerks-archive-8.9/JB-V8.9-board.txt`): the MCU is an **Arduino Pro Mini
> daughterboard, part designator `A1`**, and its 6-pin serial header is silkscreened
> `BLK · GND · VCC · RXI · TXO · GRN` with **`BLK` at the GND end** (the vendor's assembly manual
> says to align the FTDI's GND to the `BLK` position). On V8.9 it sits at roughly
> **x 0.63–1.32 in, y ≈ 6.1 in** on a 2.40 × 8.8 in board. **V8.9 only — unverified on 8.14+.**

- [ ] **Read lock bits and fuses**, recorded verbatim:
      `avrdude -c usbasp -p m328p -U lock:r:-:h -U lfuse:r:-:h -U hfuse:r:-:h -U efuse:r:-:h`
- [ ] **Dump flash.** Prefer serial (`-c arduino -b 57600`) — serial bootloaders *can* read back
      (`ATmegaBOOT_168.c:703`, `optiboot.c:1150`), and bootloader readback uses internal LPM so it
      is **not gated by lock bits**. Fall back to `-c usbasp` only if no bootloader responds.
- [ ] **Dump EEPROM** — `-U eeprom:r:stock_eeprom.hex:i`
- [ ] **Verify the dump is genuine:** two consecutive reads must hash identically, and the image
      must not be blank `0xFF`. A dump failing either test is not a backup.
- [ ] Module filesystem backed up — 97 files, `research/juicebox-module-backup-<date>/`.
      Note `JB1_0.zap`, `sys/kernel.bin` and `sys/services.bin` **cannot** be extracted (`file_open`
      and `file_stat` both refuse), so the module application is *not* recoverable.
- [ ] Module configuration backed up — `research/amw006-live-config-*.txt` (`get all`)

**Hardware:**

- [ ] JuiceBox **unplugged from mains**. This is a plug-in NEMA 14-50 unit, so unplugging is
      sufficient and is the correct procedure — do not rely on the breaker alone.
- [ ] Exactly **one** 5 V source present. The vendor's own FTDI adapter carried a VCC jumper for
      precisely this reason; mains-off with USB supplying 5 V was the documented default.
- [ ] Programmer connected — **read the ISP hazard warning in §3.1 before attaching anything**
- [ ] USB-serial adapter for RAPI on D0/D1 at 115200 — **but confirm first** that D0/D1 is not the
      inter-processor bus on this PCB revision (see R10)

### 7.2 Flash Procedure

> ⚠️ **Do not chip-erase.** Earlier revisions of this document specified `upload_flags = -e`.
> A chip erase **destroys the bootloader**, permanently removing the serial programming route
> unless it is re-burned with an ISP programmer — and it wipes the EEPROM identity and calibration.
> OpenEVSE v0.1 measures **12,450 bytes**, comfortably inside the bootloader's 30,720-byte limit,
> so **the bootloader can be kept and OpenEVSE still runs.**

1. Complete §7.1 in full. Do not proceed on a dump that failed verification.
2. **Preferred — serial, preserving the bootloader:**
   `avrdude -c arduino -p m328p -P COM<n> -b 57600 -U flash:w:juicebox_gen1.hex:i`
   (PlatformIO: `upload_protocol = arduino`, `upload_speed = 57600`, **no** `-e`)
3. **Fallback — ISP**, only if no bootloader responds. Re-read the §3.1 ISP hazard first.
4. Verify via RAPI: `$GV` returns the OpenEVSE version string
5. `$GS` returns state 1 (State A — no vehicle connected)

### 7.3 Functional Tests

| Test | RAPI Command | Expected Result |
|---|---|---|
| Version check | `$GV` | Version string returned |
| State A (idle) | `$GS` | State 1 |
| GFI self-test | `$GF` | ⚠️ **No boot POST runs** — `GFI_SELFTEST` is disabled in the shipped build (§5.1). `$GF` returns fault counts only. Add `-D GFI_SELFTEST` if you want the power-on self-test; the pin mappings already exist |
| Current reading | `$GG` | ~0A, ~240V (or 0V if unpowered) |
| Capacity setting | `$SC 24` | OK; `$GC` returns 24 |
| Enable/disable | `$FE` / `$FD` | State changes; relay clicks |

### 7.4 Calibration (With EV or Load Connected)

1. **Current calibration:**
   - Connect known load or clamp meter
   - Read `$GG` for firmware's current reading
   - Adjust with `$SA <scale_factor>` until readings match clamp meter
   - Default scale factor: 90

2. **Pilot threshold verification:**
   - Use EV simulator or real EV
   - Verify state transitions: A→B (connect), B→C (charge request), C→B (stop)
   - If state detection fails, adjust thresholds via `$S0`/`$S1` RAPI commands

---

## 8. Risk Register

| # | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Pilot thresholds incorrect — EV not detected | High | Medium | Verify with scope/simulator; adjustable via RAPI |
| R2 | Current scale factor wrong — overcurrent | **Critical** | Medium | Calibrate with clamp meter before live use; hardware CT limits max anyway |
| R3 | GFI latch timing too short — self-test fails | Medium | Low | Start at 100ms; increase if needed; adjustable in code |
| R4 | **Chip erase destroys the stock EEPROM** — identity (`IDstamp`), meter calibration and the flash checksum live there, and no copy exists | **Critical** | High | **Dump EEPROM first (§7.1); do not pass `-e`.** Erasing is not a mitigation, it *is* the damage |
| R5 | **ISP lines carry live stock functions** — D12 drives a GFCI-tripping relay, D11 is driven by the RF remote receiver, D13 drives a 6 W heater pad | **High** | High | Run ISP only with mains unplugged. If sync fails, suspect D11 driver contention first; lift the receiver output or the Pro Mini's D11 pin |
| R6 | Relay pin D5 conflicts with Timer0 OC0B | Low | Low | OpenEVSE doesn't use Timer0 OC0B for relay — uses direct GPIO |
| R7 | WiFi module SoftSerial interrupts interfere | Low | Low | WiFi module is independent; D2/D4 not used in v0.1 (used in v0.2) |
| R8 | **Pin map is V8.9; this unit is PCB 8.14+** — no public source exists for 8.10 or later, and no schematic was ever published for any revision | **Critical** | High | Verify D3/D5/D7/D9/D12 electrically before flashing (§3.1) |
| R9 | **No stock firmware dump exists** — flashing without one is irreversible, and the vendor's own advice was to preserve *source*, not a binary | **Critical** | High | §7.1 backup gate. Alternatively flash a spare Arduino Pro Mini 5V module (~$3–8) and shelf the original — reversible regardless of lock bits, **but only if the original is removable.** V8.9 solders the Pro Mini by its header pins; socket-vs-solder on 8.14+ is NOT FOUND and must be established by opening the unit |
| R10 | **D0/D1 may be the inter-processor bus on 8.14+.** On Gen 2 the ATmega UART *is* the WiFi-module link; an FTDI adapter would contend with it | High | Unknown | Trace where the WiFi module's UART meets the ATmega before connecting. V8.9 used SoftSerial D2/D4, leaving D0/D1 free — unverified for 8.14+ |

---

## 9. v0.2 — WiFi RAPI Tunneling via AMW106

### 9.1 Overview

> **Revised 2026-09-14 (live-hardware correction).** Earlier drafts assumed the AMW106 already ran in *stream* mode. The live unit is in `bus.mode: command`, and its TCP port 2000 is the **ZentriOS remote-terminal command shell**, not a transparent UART bridge — confirmed by a live `get all` and [JuiceBox-Gen1-Pentest-RE.md](JuiceBox-Gen1-Pentest-RE.md). The RAPI-stream design below needs the one-time module switch in §9.4 and presupposes OpenJuice/OpenEVSE firmware on the ATmega (which speaks RAPI). For a no-reflash interface the stock module already supports, see §9.10.

Once the AMW106 is switched to **stream mode** (§9.4), it transparently bridges its UART0 to TCP connections. By adding a SoftwareSerial RAPI channel on D2/D4, any WiFi client can then send RAPI commands to the ATmega328P.

**No ZAP protocol is needed.** The original eMotorWerks ZAP protocol was proprietary and cloud-dependent. Instead, we tunnel standard RAPI commands through the AMW106's stream mode (once enabled per §9.4) — the WiFi module acts as a dumb serial-to-WiFi bridge.

### 9.2 Architecture

```
WiFi Client (phone/laptop/HA)
        │
        ▼ TCP connection
┌──────────────┐
│   AMW106     │  stream mode: TCP ↔ UART0 transparent bridge
│   WiFi       │  IP: 192.168.x.x, port 2000 (default)
│   Module     │
└──────┬───────┘
       │ UART0 at 9600 baud (8N1)
       ▼
┌──────────────┐
│ ATmega328P   │  SoftwareSerial RX=D2, TX=D4
│ OpenJuice    │  New: EvseSoftSerialRapiProcessor
│ Firmware     │  Existing: EvseSerialRapiProcessor on D0/D1 (115200)
└──────────────┘
```

Both RAPI channels run simultaneously — local USB serial (D0/D1 at 115200) and WiFi (D2/D4 at 9600).

### 9.3 Implementation

OpenEVSE's RAPI architecture already supports multiple concurrent channels via subclasses of `EvseRapiProcessor`:

| Channel | Class | Transport | Status |
|---|---|---|---|
| Hardware UART | `EvseSerialRapiProcessor` | `Serial` on D0/D1 at 115200 | v0.1 (done) |
| I2C | `EvseI2cRapiProcessor` | `Wire` | Exists upstream (not used) |
| **SoftwareSerial** | **`EvseSoftSerialRapiProcessor`** | **`SoftwareSerial` on D2/D4 at 9600** | **v0.2 (new)** |

New class in `rapi_proc.h`:

```cpp
#ifdef RAPI_SOFTSERIAL
#include <SoftwareSerial.h>
class EvseSoftSerialRapiProcessor : public EvseRapiProcessor {
  SoftwareSerial &m_ss;
  int available() { return m_ss.available(); }
  int read() { return m_ss.read(); }
  int write(uint8_t u8) { return m_ss.write(u8); }
  int write(const char *str) { return m_ss.write(str); }
public:
  EvseSoftSerialRapiProcessor(SoftwareSerial &ss);
  void init();
};
extern EvseSoftSerialRapiProcessor g_ESSRP;
#endif
```

Integration points in `rapi_proc.cpp` — add `g_ESSRP` calls alongside existing `g_ESRP` and `g_EIRP` in:
- `RapiInit()` — initialize SoftwareSerial at 9600 baud
- `RapiDoCmd()` — process incoming commands from WiFi
- `RapiSendEvseState()` — push state changes to WiFi clients
- `RapiSendBootNotification()` — notify WiFi on boot
- `RapiSetWifiMode()` — forward WiFi mode changes

### 9.4 AMW106 Configuration (One-Time Reconfiguration)

The stock AMW106 runs in **command** mode (verified live), not stream. The target stream-tunnel config — applied once over the port-2000 command shell (or the `/command/*` HTTP API) with `set …` then `save` — is:

```
bus.mode: stream              ← transparent serial↔network bridge
bus.data_bus: uart0           ← UART0 is the data channel
uart.baud: uart0:9600         ← matches SoftwareSerial baud rate
bus.stream.cmd_seq: $$$       ← escape to command mode (3 sec idle + $$$)
bus.stream.flush_time: 100    ← 100ms flush interval
```

WiFi clients then connect via TCP to the AMW106's IP; data sent over TCP is forwarded to UART0 (D2/D4 on the ATmega328P). Switching to stream mode takes over port 2000, so the `$$$` escape is the way back to the command shell — the earlier *No Changes Needed* wording was wrong; this switch is the one change required.

### 9.5 Build Flags (v0.2)

```ini
build_src_flags =
  ... (all v0.1 flags) ...
  -D RAPI_SOFTSERIAL
  -D RAPI_SOFTSERIAL_RX=2
  -D RAPI_SOFTSERIAL_TX=4
  -D RAPI_SOFTSERIAL_BAUD=9600
```

### 9.6 Usage

```bash
# From any device on the same WiFi network. The IP + port are obtained from
# the UDP 55555 discovery beacon (see §9.9); 192.168.1.18 below is illustrative.
# Connect via TCP (e.g., netcat, PuTTY raw mode, or custom app)
nc 192.168.1.18 2000

# Send RAPI commands as plain text:
$GV          # get firmware version
$GS          # get EVSE state
$GG          # get current and voltage
$SC 24       # set current capacity to 24A
$FE          # enable charging
$FD          # disable charging
```

### 9.7 Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| W1 | SoftwareSerial interrupts interfere with pilot PWM timing | Medium | Test with scope; SoftwareSerial at 9600 has short ISRs |
| W2 | Flash/RAM overhead of SoftwareSerial library | Low | SoftwareSerial adds ~1.5KB flash, ~70 bytes RAM; v0.1 uses 40.5% flash |
| W3 | ~~AMW106 stream mode TCP port unknown~~ **Resolved** | Low | **Confirmed port 2000** — the live JuiceBox's UDP 55555 beacon advertises `remote_terminal_port: 2000` (§9.9; [discovery doc](ZentriOS-Gecko-LAN-Discovery.md)) |
| W4 | No authentication on TCP connection | Medium | AMW106 is on local WiFi only; add `http.server.password` if needed |

### 9.8 Prerequisites

- v0.1 firmware flashed and verified (RAPI working on D0/D1)
- WiFi module connected to the local WLAN — **verify; do not assume** (an earlier revision of this
  document named a stale SSID)
- Stream mode — ⚠️ **NOT already configured.** The live unit reports `bus.mode: command`, confirmed
  by `get all` and by §9.4. Switching to stream is a one-time reconfiguration you must perform, and
  `$$$` is the documented way back out. Earlier revisions asserted this precondition was already
  met; it is not.

### 9.9 Local Discovery & Health Monitoring (UDP 55555 Beacon)

The AMW106 — like all ZentriOS/Gecko OS modules — broadcasts a JSON **discovery beacon on UDP 55555** every ~10 seconds. This removes the need to hardcode the JuiceBox IP (§9.6) and provides a passive health feed **with zero changes to the AMW106 or the ATmega firmware**. Full protocol spec and live captures: [ZentriOS-Gecko-LAN-Discovery.md](ZentriOS-Gecko-LAN-Discovery.md).

Verified beacon from a live JuiceBox Gen 1:

```json
{"mac":"4C:55:CC:18:1D:09","bssid":"38:94:ED:5E:BE:0F","channel":1,
 "ip":"192.168.1.62","ssid":"StumpyNet","rssi":-68,
 "remote_terminal_port":2000,"time":1784058085337,
 "version":"EMWERK-JB_1_1-1.4.0.28, 2021-04-27T20:39:50Z, ZentriOS-WZ-3.6.4.0",
 "uuid":"06413041000000001D003F00055136313535 3738"}
```

#### 9.9.1 Auto-discovery flow

Instead of a hardcoded address, the RAPI client discovers the JuiceBox dynamically and stays correct across DHCP lease changes:

```
listen UDP 0.0.0.0:55555
  on datagram:
    j = json.loads(payload)
    if "EMWERK-JB" in j["version"]:          # it's a JuiceBox
        host = j["ip"]                        # current IP, even after DHCP churn
        port = j["remote_terminal_port"]      # 2000 (command shell stock; stream tunnel after §9.4)
        open TCP host:port  →  speak RAPI
```

The beacon's `remote_terminal_port` (2000) is the single TCP port used by both the stock command shell and — after the §9.4 switch — the RAPI stream tunnel, so discovery and transport line up on one port. This retires risk **W3** (the port was unknown); the *mode* still needs the one-time §9.4 change.

#### 9.9.2 Health telemetry from the beacon (no firmware change)

The beacon is itself a monitoring feed. A ~30-line UDP listener (see [`tools/beacon_extract.py`](../tools/beacon_extract.py)) can publish these to MQTT alongside the RAPI-tunneled charging data:

| Beacon field | Metric | Home Assistant entity |
|---|---|---|
| `ip` present / stale | online / offline | `binary_sensor` |
| `rssi` | WiFi signal (dBm) | `sensor` |
| `time` | device clock / coarse uptime | diagnostic |
| `bssid` | associated AP | roaming diagnostic |
| `version` | firmware inventory | diagnostic |

Note the beacon clock free-runs and drifts (~0.7 %), so treat `time` as a liveness/rough signal, not an accurate RTC.

#### 9.9.3 Requirements

| ID | Requirement |
|---|---|
| D1 | The RAPI client SHALL listen on UDP 55555 and parse JSON beacons |
| D2 | The client SHALL identify the JuiceBox by `version` containing `EMWERK-JB` |
| D3 | The client SHALL use the beacon's `ip` + `remote_terminal_port` for the RAPI TCP connection (§9.6) rather than a hardcoded address |
| D4 | The client MAY publish `rssi` and online-state as diagnostic sensors |

**Constraint:** the beacon is a limited broadcast (`255.255.255.255`), so the listener must sit on the **same L2 segment** as the JuiceBox — or capture on the router/AP bridge (see [discovery doc §5](ZentriOS-Gecko-LAN-Discovery.md#5-capturing-the-beacon-router--ap-side)).

---

### 9.10 Alternative: device-hosted web UI (no ATmega reflash)

The stock WiFi module runs a ZentriOS **HTTP server on port 80 with the `/command/*` REST API enabled** (`http.server.api_enabled: 1`) — verified live, and it is how this project reads and reconfigures the module.

⚠️ **Correction (2026-09-21):** an earlier revision claimed the module "serves a web app from `webapp/` … all verified live". **It does not.** A live `ls` shows **no `webapp/` directory exists**, and `GET /` returns **404** even though `http.server.root_filename` is set to `webapp/index.html`. That claim came from a dev board, not this unit. The practical consequence is favourable — **the `webapp/` namespace is empty and free to claim**, and `root_filename` already points at it — but it must be created, not assumed.

An OpenEVSE-style HTML interface is therefore possible **without flashing the ATmega**: upload an HTML/JS app into `webapp/` via `file_create`, and have it read module state through `/command/*` plus the on-flash charge-data files (`ECache*`/`Events*`/`ELife_1`), which download over plain HTTP.

**What this path cannot do on its own.** Live status (voltage, current, power, charging state) and current control exist **only** in the JuiceNet UDP stream the ATmega generates; the module is a pipe for that stream and exposes none of it — `help commands` returns pure stock ZentriOS with nothing charger-related. Both therefore require something acting as the JuiceNet server: this PC, a Pi, or (post-port) the module itself in stream mode. Note also there is **no start/stop opcode** — the `C` field is not an opcode table, and pausing is done by sending online current `A=0` (which resets session energy and cycles the contactor).

The proven route for live status and control is redirecting the JuiceNet UDP telemetry — v07 packet format decoded in [JuiceBox-Gen1-Pentest-RE.md](JuiceBox-Gen1-Pentest-RE.md) — to a local collector (`tools/juicebox_rawcap.py`, or [`JuiceRescue/juicepassproxy`](../datasheets/SOURCES.md)), which replies as the JuiceNet server. **The reply must be sourced from the exact IP:port the device addresses** — verified on this unit, where spoofing that source produced five confirmed current changes.

*Why* that is required is inferred rather than established here: juicepassproxy issue #149 reports that the firmware honours commands only after completing its `directory-api.emotorwerks.com` handshake **and** only from the endpoint that handshake named. **That finding is from an EO Mini Pro rebadge (`EMWERK-JEO2`), not from `EMWERK-JB_1_1`, and is unconfirmed on this hardware.** It is consistent with our observations but has not been isolated. One practical consequence if it holds: blocking the directory server — sometimes recommended to prevent the encryption switch — could stop the device accepting *any* commands after its next reboot.

---

## 10. Future Enhancements (Out of Scope for v0.1 and v0.2)

- **MQTT support:** Expose RAPI data via MQTT through the WiFi module
- **Web UI:** Serve a local configuration page from the AMW106's HTTP server
- **Energy metering:** Accumulate kWh from current/voltage readings
- **Scheduled charging:** Time-based charge windows via RAPI or WiFi
- **Home Assistant integration:** MQTT discovery for auto-configuration
- **OpenEVSE WiFi module replacement:** Swap AMW106 for ESP32 running OpenEVSE WiFi firmware (full web UI, MQTT, OCPP out of the box)

---

## Appendix A: JuiceBox Gen 1 Board Revisions

| Board Rev | Key Differences |
|---|---|
| V8.9 | GFI D-latch on D7; confirmed pin mapping in this FSD |
| V8.x (earlier) | May lack D-latch; verify GFI circuit before flashing |

## Appendix B: Upstream OpenEVSE Compatibility

This port is based on OpenEVSE firmware from the `master` branch. All changes are gated behind `#ifdef JUICEBOX_GEN1` and do not affect other build targets. The goal is to submit upstream as a new board variant if the port proves stable.

## Appendix C: AMW106 WiFi Module Backup

> 🛑 **Corrected 2026-09-21 — the "16 files" are NOT a backup of this unit.** They match a
> **dev board** byte-for-byte (WiConnect-2.2.0.12, built 2015-04-08, MAC `4C:55:CC:10:35:E5`),
> not this charger (ZentriOS-WZ-3.6.4.0, `EMWERK-JB_1_1-1.4.0.28`, MAC `4C:55:CC:18:1D:09`).
> They are also **web/config assets, not a firmware image** — no kernel, services or application
> binary is present. Any checklist item reading "WiFi module firmware backed up" on the strength
> of that folder was false.

**What is actually held for the live unit:**

| Artifact | Contents |
|---|---|
| `research/juicebox-module-backup-<date>/` | **97 files, 397,957 bytes**, pulled over plain HTTP — full charge history (`ECache_*`, `Events_*`), `ELife_1`, `index.html`, CA cert, and three of five system binaries (`sys/wifi_fw.bin`, `sys/safemode.bin`, `sys/wl_table.bin`) |
| `research/amw006-live-config-*.txt` | Full `get all` dumps of the live module |
| `research/emotorwerks-archive-8.9/` | Archived V8.9 board layout (`.rrb` + decompressed text) and stock `.hex` images — **V8.9, not 8.14** |

**Not recoverable:** `JB1_0.zap` (the EVSE application), `sys/kernel.bin` and `sys/services.bin`
all refuse `file_open`/`file_stat` and are not served over HTTP. Module firmware was historically
obtainable from Zentri DMS/OTA (`dfu.zentri.com`), but that channel is cloud-gated and these
devices are owned in the vendor's DMS account — treat it as unavailable. **Any change that
displaces `JB1_0.zap` is irreversible.**

## Appendix D: Glossary

| Term | Definition |
|---|---|
| EVSE | Electric Vehicle Supply Equipment — the charger unit |
| J1772 | SAE standard for AC EV charging connectors and pilot signaling |
| RAPI | Remote API — OpenEVSE's text-based serial command protocol |
| GFI | Ground Fault Interrupter — safety device detecting current leakage |
| CT | Current Transformer — sensor measuring AC current non-invasively |
| PAFC_PWM | Phase-and-frequency-correct PWM — Timer1 mode used for pilot signal |
| ISP | In-System Programming — programming the MCU via SPI (MOSI/MISO/SCK/RESET) |
| ZAP | Zentri Application Protocol — WiFi module's serial communication protocol |
| OC1A/OC1B | Timer1 Output Compare channels A and B (D9 and D10 respectively) |
