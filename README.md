# OpenJuice

**OpenEVSE ported to the JuiceBox Gen 1 EV charger, on its existing hardware, with a local web
interface served by the charger itself.** No cloud, no helper machine, no board or chip swaps.

Enel X Way shut down its North American JuiceBox service in October 2024. The chargers still
charge, but they lost local visibility and control. OpenJuice restores both.

> ## 🛑 Do not flash yet
>
> `firmware/openevse-juicebox-gen1.patch` encodes the pin map of **PCB V8.9**. eMotorWerks' own
> source and factory test firmware show the pin map changed at **V8.10** and again at **v8.12**,
> including the **main relay, current sensing and ground-fault test pins**. Flashing the patch onto a
> newer board could drive the wrong pins on a 40 A mains circuit. No dump of the stock firmware
> exists either, so a flash cannot be undone.
>
> The port is gated on reading the board revision, dumping the stock firmware, and verifying every
> safety-critical pin electrically. See [docs/STATUS.md](docs/STATUS.md).

## What works today

| Capability | How | Firmware change |
|---|---|---|
| Read module state, faults, uptime, network | The WiFi module's unauthenticated web command interface on port 80 | None |
| Read energy history: lifetime, 5-minute buckets, charging sessions | Log files on the module's flash, served over plain HTTP; formats decoded | None |
| Live telemetry: state, current, voltage, power, session energy, temperature | Redirect the charger's cloud lookups to a PC and receive its UDP telemetry | None |
| Set the charge-current limit, whole amps 6–40 A | Reply to that telemetry as the cloud server would | None |

The last two need a helper running on a PC on the same network, and the charger falls back to the
vendor cloud whenever its WiFi module reboots. Both limits go away with the port. The procedure is
in [docs/STATUS.md](docs/STATUS.md); the tools are in [tools/](tools/).

## The plan in one paragraph

**Stage A** puts a read-only dashboard on the charger itself: one HTML file in the WiFi module's
empty web root, reading the module's own data. **Stage B** ports OpenEVSE to the existing
ATmega328P and turns that dashboard into a control surface. Stage B begins with zero-risk
reconnaissance: read the side sticker for the board revision, and triage a spare board as a bench
rehearsal target. Details, gates and the current state: [docs/STATUS.md](docs/STATUS.md).

## Hardware at a glance

| Part | What we know |
|---|---|
| Charging controller | ATmega328P, 16 MHz, 5 V. Runs eMotorWerks firmware; OpenEVSE replaces it in Stage B |
| WiFi module | Zentri **AMW106**, ZentriOS-WZ 3.6.4.0, the final release for this part. The vendor app on it, `JB1_0.zap`, owns the cloud link and cannot be backed up |
| Board revision | 8.14 or later on the reference unit; unconfirmed until the sticker is read |
| Pin map | Published for V8.9, V8.10 and v8.12, all different; **unknown for 8.14+** |
| Programming interface | Unknown for 8.14+; the v8.12 evidence points to an Arduino Pro Mini daughterboard |

## Documentation

| Document | What it covers |
|---|---|
| [STATUS.md](docs/STATUS.md) | Goal, constraints, where things stand, next steps, interim control procedure |
| [OpenJuice-FSD.md](docs/OpenJuice-FSD.md) | Functional specification for the port: hardware, per-revision pin maps, build, commissioning, risks |
| [JuiceBox-Gen1-Pentest-RE.md](docs/JuiceBox-Gen1-Pentest-RE.md) | Security assessment and protocol reverse engineering of the live unit |
| [ZentriOS-Gecko-LAN-Discovery.md](docs/ZentriOS-Gecko-LAN-Discovery.md) | The UDP 55555 discovery beacon shared by ZentriOS and Gecko OS devices |
| [datasheets/SOURCES.md](datasheets/SOURCES.md) | Datasheets and reference sources |

The repository also holds a sister project, reverse engineering of the Generac Mobile Link Tether,
which runs the same WiFi OS family. It is documented in
[Generac-MobileLink-Tether-RE.md](docs/Generac-MobileLink-Tether-RE.md),
[MobileLink-App-Lineage.md](docs/MobileLink-App-Lineage.md) and
[MobileLink-Cloud-API.md](docs/MobileLink-Cloud-API.md).

## Safety

This project touches a 240 V, 40 A appliance. Unplug it from mains before opening the enclosure;
it is a plug-in unit, so unplugging is the correct isolation, not the breaker alone. Never flash
the charging controller without a verified dump of its flash and EEPROM. Never set
`zap.auto_run 0` on the WiFi module: the vendor app it disables also brings up WiFi and cannot be
restored.

## License

GPL v3, inherited from OpenEVSE. The eMotorWerks JuiceBox firmware is also GPL v3.
