# Generac Mobile Link Tether — Reverse Engineering Notes

**Status:** Reverse-engineered and verified on live hardware, 2026-07-14
**Device:** Generac Mobile Link **external** WiFi/Ethernet accessory ("Tether")
**Module:** Silicon Labs **WGM160P** running **Gecko OS STANDARD 4.2.3-9237**, app layer `H42069-TETHER-1.0.8`

---

## 1. Why this is in the OpenJuice repo

This is a **sister case** to the JuiceBox: another cloud-tethered consumer device built on the **same OS family** (Gecko OS is the successor to the ZentriOS/WiConnect stack the JuiceBox's AMW006 runs). Same discovery beacon ([ZentriOS-Gecko-LAN-Discovery.md](ZentriOS-Gecko-LAN-Discovery.md)), same port-2000 concept, same "the hardware is fine, the cloud is the leash" problem OpenJuice exists to solve.

The contrast is instructive:

- **JuiceBox** left stream-mode **port 2000 open** → locally controllable (that's what OpenJuice v0.2 exploits).
- **Generac** **locked every local interface** → it is a pure cloud relay. The reverse engineering below documents exactly *how* locked, and what remains reachable.

The provisioning tool and packet-analysis scripts developed here live in [`tools/`](../tools/) and are reusable against any Gecko OS / ZentriOS device.

---

## 2. Device identity

From the SoftAP config API (`getConfig`, `interface=system`):

| Field | Value |
|---|---|
| `wifi_module_version` | `H42069-TETHER-1.0.8, Gecko_OS-STANDARD-4.2.3-9237, WGM160P` |
| `comm_module_type` | `10000035491` |
| `mcu_version` | `1.3.45656` |
| `device_id` | `6c9d8f11-f5e3-4795-b5b3-46202705e155` (cloud/account ID) |
| station MAC | `94:DE:B8:2A:18:EA` |
| beacon `uuid` | `EADE2FF34B76B3EF7EA72B5A84B4DBFFFECB7CB4` (module ID — **different** from `device_id`) |

> The Tether is the **external** accessory (cable to the generator controller), not the integrated onboard radio. Its only reboot mechanism is a **physical power-cycle** (unplug the accessory cable ~10 s) — confirmed from the app's own troubleshooting strings. There is **no software reboot command** (see §5).

---

## 3. SoftAP provisioning protocol (V2)

When unprovisioned, the module raises a SoftAP (`G0071700-…` SSID) at **`192.168.51.1`** with an HTTP API. The Android app (`Mobile+Link+for+Generators`, React Native / Hermes bytecode) drives this API. Endpoints:

| Method | Path | Body / notes |
|---|---|---|
| POST | `/Generac/api/getConfig` | `{"interface":"system"}` or `{"interface":"wlan"}` — read config |
| POST | `/Generac/api/setConfig` | write config (per-interface) |
| POST | `/Generac/api/getConfig` | `initializeSystemConfig` variant sets `{"interface":"system","wifi_enable":true,"eth_enable":true}` |
| GET | `/Generac/api/networks` | scan visible APs |
| GET | `/Generac/api/connect` | begin join |
| GET | `/Generac/api/status` | poll join progress (returns `{"reason":<code>}`) |
| GET | `/Generac/api/complete` | finish provisioning |

Interface names are **case-sensitive** (`system`, `wlan`, `ethernet` — uppercase returns `{"reason":19}`).

### 3.1 The critical fix — `wifi_enable`

The device ships with `wifi_enable: false`. If you push WLAN credentials without first enabling the WiFi interface, the join **stalls** (status cycles `reason 12 → 13` and never associates). The winning sequence is:

```
1. setConfig  {"interface":"system","wifi_enable":true,"eth_enable":true}   ← MUST be first
2. read back  getConfig(system)  → verify wifi_enable == true
3. setConfig  {"interface":"system","primary_interface":"wlan"}
4. setConfig  {"interface":"wlan","ssid":..,"passphrase":..,
               "bssid":"00:00:00:00:00:00","channel":0,
               "security":"WPA2-AES","dhcp_enable":true}
5. GET /connect  →  poll /status  →  GET /complete
```

- `bssid = 00:00:00:00:00:00` and `channel = 0` are the Gecko OS "any AP with this SSID / scan all channels" sentinels — leave them unpinned so the module can find the AP on any channel.
- The `/status` `reason` codes are Gecko OS WLAN join states; `12/13` = scanning/associating, cleared once the interface is enabled.

This whole sequence is implemented in [`tools/generac_provision.py`](../tools/generac_provision.py) as the `connect` subcommand:

```sh
python tools/generac_provision.py connect "YourSSID" "YourPassword"
```

### 3.2 DHCP gotcha — sleepy-client OFFER loss

The WGM160P associates but its DHCP client can miss the unicast **Offer** (power-save), leaving it "associated, no IP," then falling back to SoftAP. Fix on the DHCP server (dnsmasq) by forcing **broadcast** replies to that MAC:

```
dhcp-host=94:DE:B8:2A:18:EA,192.168.1.94,generac,set:sleepy
dhcp-broadcast=tag:sleepy
```

---

## 4. Local attack surface after provisioning — all locked

Once on the LAN, the Tether exposes **nothing** useful locally. Verified by port scan, direct probes, and a 13-minute packet capture:

| Interface | Result |
|---|---|
| Gecko OS command API `/command/*` (HTTP) | `500 Feature not initialized` — command shell compiled out |
| Remote terminal, TCP **2000** | closed |
| Remote terminal, UDP **2000** | closed (ICMP port-unreachable) |
| `/Generac/api/*` REST on the LAN IP | closed (bound to SoftAP only) |
| mDNS service records | none — hostname claim only (`gecko_os-8EA.local`) |
| **UDP 55555 beacon** | **the only local data** — presence, RSSI, uptime, firmware |

Over a full boot the device made **zero** outbound cloud connections (no DNS, NTP, TCP, or TLS) **in its bypass-provisioned, unregistered state** — because the *account registration* step, not the WiFi step, is what hands the module its Azure identity. See [ZentriOS-Gecko-LAN-Discovery.md §6](ZentriOS-Gecko-LAN-Discovery.md#6-other-lan-chatter-observed).

**Conclusion:** with the local surface locked, the beacon is the offline-monitoring ceiling. Deep telemetry (battery, fuel, run-hours, faults) only exists in the cloud channel, which requires registration.

---

## 5. No software reboot

Searched the decompiled app bundle and string table — there is **no** device reboot/reset endpoint. The "restart" strings are UI artifacts (`restartPageVisitTimer` = analytics; `restartConnectionFlow` = re-run the setup wizard; `Rebooting` = a *firmware-OTA* status enum). The app's own documented reboot for this accessory is physical:

> *"Unplug the cable from the back side of the Wi-Fi/Ethernet device"*

(The 7.5 A-fuse + battery-disconnect procedure in the app is for the **controller/onboard** radio, **not** the external Tether.)

---

## 6. Cloud architecture

Deep telemetry flows **device → Azure IoT Hub (MQTT/TLS 8883) → Generac cloud**, and the app reads it back over a REST API. Two ways to obtain the deep metrics, both requiring a one-time **enrollment** of the device to an account:

### 6.1 REST API (`app.mobilelinkgen.com`)

- Base: `https://app.mobilelinkgen.com/api/v5/`
- Auth: **Azure AD B2C** (`generacconnectivity.b2clogin.com`, tenant `generacconnectivity.onmicrosoft.com`, policies `B2C_1A_MobileLink_SignIn` / `SignUp` / `ChangePassword`, scope `https://generacconnectivity.onmicrosoft.com/cf3e2bfb-2d0c-47dd-8067-bf59a6f88ed7/client`) → `Authorization: Bearer <jwt>`

| Endpoint | Purpose |
|---|---|
| `GET /Apparatus/list` | devices on the account |
| `GET /Apparatus/details/{id}` | **telemetry**: `batteryVoltage`, `fuelLevel`, `runHours`, `signalStrength`, `apparatusStatus`, weather |
| `GET /Apparatus/maintenanceDetails/{id}`, `/maintenanceHistory/{id}` | service data |
| `GET /Apparatus/specifications/{id}` | model/spec |
| `GET /Apparatus/telemetry/events/{id}` | event history |
| `GET /Apparatus/exerciseNow/{id}` | **control** — start exercise cycle |
| `POST /Apparatus/enrollment/validate/serialNumber/{serial}` | registration step 1 (by serial) |
| `POST /Apparatus/enrollment/validate/device`, `/enrollment/device`, `/enrollment` | registration steps 2–3 |
| `DELETE /Apparatus/remove/{id}` | unenroll |

### 6.2 Enrollment (registration) path

Registration is **by generator serial number** and is *separate* from the WiFi-provisioning flow:

```
validate/serialNumber/{serial}  →  enrollment/validate/device  →  enrollment/device  →  enrollment
```

Because it's decoupled from WiFi setup, a device already on WiFi (e.g. via §3) can be enrolled without re-touching the provisioning webview that commonly throws the "page not found" error.

---

## 7. Firmware analysis artifacts

The Android APK (`Mobile Link for Generators 3.16.0`) is a React Native app compiled to **Hermes bytecode v96**. Notes for anyone re-deriving this:

- `res/8G.xml` (Network Security Config) permits cleartext HTTP **only** to `192.168.51.1` — a strong tell that the SoftAP is the only plaintext endpoint.
- The Hermes bundle string table and a pseudo-JS decompile yield the endpoint list, the `initializeSystemConfig` body, and the B2C config above.

---

## 8. JuiceBox vs Generac Tether — same family, opposite outcomes

| | JuiceBox Gen 1 | Generac Mobile Link Tether |
|---|---|---|
| Module | Zentri AMW006 | Silicon Labs WGM160P |
| OS | ZentriOS-WZ 3.6.4.0 | Gecko OS STANDARD 4.2.3 |
| Discovery beacon (UDP 55555) | ✅ yes | ✅ yes |
| Port 2000 | ✅ **open** (stream→UART) | 🔒 closed |
| Gecko/Zentri command API | (varies) | 🔒 `Feature not initialized` |
| Local control possible? | ✅ **yes** (OpenJuice v0.2 tunnels RAPI) | ❌ no — cloud relay only |
| Deep telemetry locally | via ATmega RAPI over port 2000 | ❌ cloud-only (MQTT→Azure, needs enrollment) |
| Cloud status | dead (Enel X shutdown) | live (Azure IoT + `mobilelinkgen.com`) |

The JuiceBox is *recoverable locally* precisely because its WiFi module was left open; the Generac shows what it looks like when the vendor bolts every local door shut. Same silicon lineage, very different repairability.
