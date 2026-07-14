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

- [Functional Specification (FSD)](docs/OpenJuice-FSD.md)
- [Datasheets & References](datasheets/SOURCES.md)

### Related reverse engineering (Zentri / Gecko OS family)

The JuiceBox's AMW006 WiFi module and its ZentriOS/Gecko OS relatives share a
common LAN discovery protocol and a stream-mode port that OpenJuice v0.2 relies on:

- [ZentriOS/Gecko OS LAN Discovery Beacon & Local Protocols](docs/ZentriOS-Gecko-LAN-Discovery.md) — the UDP 55555 JSON beacon (auto-discovers the JuiceBox IP for v0.2), port 2000, and how to capture it. Verified on live JuiceBox + Generac hardware.
- [Generac Mobile Link Tether — RE Notes](docs/Generac-MobileLink-Tether-RE.md) — a sister cloud-tethered device on the same OS family (Gecko OS / WGM160P): provisioning protocol, locked-down local surface, and cloud API. A cautionary counterpoint to the recoverable JuiceBox.
- [Mobile Link App Lineage & Legacy V1 Provisioning](docs/MobileLink-App-Lineage.md) — three app generations (Xamarin → Xamarin → React Native) reverse-engineered to recover the legacy **GainSpan V1** provisioning API for older controllers, mapped against the modern V2 Gecko OS flow.
- [Mobile Link Cloud REST API](docs/MobileLink-Cloud-API.md) — the full cloud contract (endpoints, telemetry model, B2C auth, enrollment flow) recovered from the Xamarin `MobileLinkClient` by LZ4-decompressing the .NET assembly store. The spec for a local-independent telemetry/control integration.
- [tools/](tools/) — pure-Python (stdlib-only) beacon/pcap decoders, a Gecko OS provisioning client, and APK framework/endpoint analyzers. `beacon_extract.py` decodes JuiceBox *and* Generac beacons.

## Status

**v0.1 — In Development**

## License

GPL v3 (inherits from OpenEVSE)
