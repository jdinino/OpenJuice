# OpenJuice

**Open-source firmware port for JuiceBox Gen 1 EVSE**

OpenJuice ports [OpenEVSE](https://github.com/OpenEVSE/open_evse) firmware to run on JuiceBox Gen 1 hardware — no hardware modifications required. Gives bricked JuiceBox units a second life after the Enel X cloud shutdown.

## What This Does

- Replaces the ATmega328P firmware with OpenEVSE (pin-remapped)
- Provides local RAPI serial control (current, voltage, state, GFI)
- SAE J1772 compliant pilot signal and state machine
- GFI protection with self-test and D-latch support
- Leaves the WiFi module (AMW006) untouched

## Hardware

| Component | Details |
|---|---|
| MCU | ATmega328P @ 16MHz, 5V |
| WiFi | Zentri AMW006 (unchanged) |
| Programming | USBasp ISP via MOSI/MISO/SCK/RESET |
| Serial | RAPI on D0/D1 @ 115200 baud |

## Quick Start

```bash
# Clone OpenEVSE
git clone https://github.com/OpenEVSE/open_evse.git

# Apply OpenJuice patches (see firmware/)
# Build
pio run -e juicebox_gen1

# Flash
pio run -e juicebox_gen1 -t upload

# Verify
# Connect serial at 115200, send: $GV
```

## Documentation

- [Functional Specification (FSD)](docs/FSD.md)
- [Datasheets & References](datasheets/SOURCES.md)
- [AI Agents for Development](docs/AI_AGENTS.md)

## Status

**v0.1 — In Development**

## License

GPL v3 (inherits from OpenEVSE)
