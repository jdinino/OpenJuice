# OpenJuice — Functional Specification Document

**Project:** OpenJuice (OJ)
**Version:** 0.1 DRAFT
**Date:** 2026-02-27
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
| ATmega328P firmware replacement | WiFi module (AMW006) firmware changes |
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
                    │   │ATmega328P│◄── D2/D4 9600 ───►│ AMW006 │ │
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
| Bootloader | None (ISP programmed) |

### 2.3 WiFi Module (Not Modified)

| Parameter | Value |
|---|---|
| Module | Zentri AMW006-A01.1 |
| Firmware | WiConnect 2.2.0.12 |
| Interface to MCU | SoftwareSerial on D2(RX)/D4(TX) at 9600 baud |
| Protocol | ZAP (Zentri Application Protocol) |
| Status | Left untouched — WiFi module is independent |

---

## 3. Pin Mapping

### 3.1 Complete Pin Assignment Table

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
| PB3 | D11 | ISP MOSI | ISP MOSI | No |
| PB4 | D12 | **GFI test output** | ISP MISO | **Yes — new** |
| PB5 | D13 | ISP SCK / Status LED | ISP SCK | No |
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
upload_protocol = usbasp
upload_flags = -e          ; erase chip (clear old EEPROM)
build_flags =
    -D JUICEBOX_GEN1
    -D AMMETER
    -D VOLTMETER
    -D RAPI
    -D RAPI_SERIAL
    -D GFI
    -D GFI_SELFTEST
    -D GFI_LATCH_RESET
    -D PAFC_PWM
    -D NO_AUTOSVCLEVEL
    -D DEFAULT_SERVICE_LEVEL=2
    -D DEFAULT_CURRENT_CAPACITY_L2=30
    -D DEFAULT_CURRENT_SCALE_FACTOR=90
    -D SERIAL_BAUD=115200
```

### 5.2 Excluded Features

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

- [ ] AMW006 WiFi module firmware backed up (see `C:\AI\amw006_firmware_backup\`)
- [ ] AMW006 configuration backed up (see `C:\AI\amw006_config_backup.txt`)
- [ ] USBasp ISP programmer connected (MOSI→D11, MISO→D12, SCK→D13, RESET→RESET)
- [ ] USB-serial adapter connected to D0/D1 at 115200 baud for RAPI
- [ ] JuiceBox unplugged from mains AC

### 7.2 Flash Procedure

1. Connect USBasp to ISP header
2. `pio run -e juicebox_gen1 -t upload` (includes `-e` chip erase)
3. Verify via RAPI: `$GV` should return OpenEVSE version string
4. `$GS` should return state 1 (State A — no vehicle connected)

### 7.3 Functional Tests

| Test | RAPI Command | Expected Result |
|---|---|---|
| Version check | `$GV` | Version string returned |
| State A (idle) | `$GS` | State 1 |
| GFI self-test | `$GF` | No fault counts; POST passes at boot |
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
| R4 | EEPROM contains old JuiceBox data — erratic behavior | Medium | High | Chip erase (`-e`) during flash clears EEPROM |
| R5 | ISP conflicts with GFI test pin (D12/MISO) | Low | Medium | GFI test only active during self-test; ISP only during programming |
| R6 | Relay pin D5 conflicts with Timer0 OC0B | Low | Low | OpenEVSE doesn't use Timer0 OC0B for relay — uses direct GPIO |
| R7 | WiFi module SoftSerial interrupts interfere | Low | Low | WiFi module is independent; D2/D4 not used by OpenEVSE |

---

## 9. Future Enhancements (Out of Scope for v0.1)

- **WiFi integration:** Bridge RAPI commands through AMW006 WiFi module to enable remote control
- **MQTT support:** Expose RAPI data via MQTT through the WiFi module
- **Web UI:** Serve a local configuration page from the AMW006
- **Energy metering:** Accumulate kWh from current/voltage readings
- **Scheduled charging:** Time-based charge windows via RAPI or WiFi
- **OpenEVSE WiFi module replacement:** Swap AMW006 for ESP32 running OpenEVSE WiFi firmware

---

## Appendix A: JuiceBox Gen 1 Board Revisions

| Board Rev | Key Differences |
|---|---|
| V8.9 | GFI D-latch on D7; confirmed pin mapping in this FSD |
| V8.x (earlier) | May lack D-latch; verify GFI circuit before flashing |

## Appendix B: Upstream OpenEVSE Compatibility

This port is based on OpenEVSE firmware from the `master` branch. All changes are gated behind `#ifdef JUICEBOX_GEN1` and do not affect other build targets. The goal is to submit upstream as a new board variant if the port proves stable.

## Appendix C: AMW006 WiFi Module Backup

Full backup stored at `C:\AI\amw006_firmware_backup\` (16 files). Configuration dump at `C:\AI\amw006_config_backup.txt`. Internal firmware files (wiconnect.exe, upgrade_app.exe, wifi_fw.bin) are recoverable from Zentri DMS/OTA servers (verified alive as of 2026-02-27).

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
