# Generac Mobile Link — App Lineage & Legacy (V1 GainSpan) Provisioning

**Status:** Reverse-engineered from three APK generations, 2026-07-14
**Companion to:** [Generac-MobileLink-Tether-RE.md](Generac-MobileLink-Tether-RE.md)

---

## 1. Why this is here

The current [Tether RE notes](Generac-MobileLink-Tether-RE.md) document the **V2 Gecko OS** provisioning API. But the Mobile Link generator platform is old (the app dates to Feb 2014), and older controllers use a different **V1 "GainSpan"** provisioning path. Pulling apart three APK generations recovered that legacy API and explains why the `/gainspan/system/...` probes **404'd** on the modern Tether — those endpoints belong to the *previous* module generation.

Relevance to OpenJuice: same story as the JuiceBox — a cloud-tethered device whose provisioning/telemetry evolved across firmware generations, documented so owners of **older controllers** aren't stranded.

---

## 2. Three generations, three frameworks

| Version | App (package) | Framework | Provisioning | APK size |
|---|---|---|---|---|
| **1.0.2707** | Mobile Link **Setup** (`Generac.Applications.Mobile.Installer`) | Xamarin.Forms (.NET) | **V1 GainSpan** | 31,045,475 B |
| **2.28.0.47091** | Mobile Link for Generators (`com.generac.standbystatus`) | Xamarin (.NET, assembly-store blob) | V1→V2 transition | 48,153,959 B |
| **3.16.0** | Mobile Link for Generators (`com.generac.standbystatus`) | React Native / Hermes bytecode | V2 Gecko OS | 142,712,707 B |

SHA-256 fingerprints are in [../datasheets/SOURCES.md §8d](../datasheets/SOURCES.md).

---

## 3. The V1 GainSpan provisioning API

Recovered from the 1.x Installer's `Generac.Applications.Mobile.Installer.dll` — including its embedded `appsettings`:

```json
"BasePaths": {
    "LegacyGainspanApi": "http://192.168.51.1/gainspan/system/",
    "InstallMLApi": "https://installml.com/"
}
```

Same SoftAP IP (`192.168.51.1`) as the modern module, different base path. The `LegacyConnectionService` implements the flow:

| C# method / constant | Role | V2 Gecko equivalent |
|---|---|---|
| `GetApiVersionAsync` | `api/version` | `getConfig` (system) |
| `GetScanParametersAsync` → `SCAN_PARAMS_ENDPOINT` | scan config | `scan` |
| `GetNetworksAsync` | list APs the generator sees | `networks` |
| `PostNetworkConfigAsync` → `NETWORK_CONFIG_ENDPOINT` | push credentials | `setConfig` (wlan) |
| `CheckConnection` → `CheckConnectionResponse` | poll join status | `status` |
| `BuildEndpoint` | base + endpoint constant | — |
| — | (none) | `complete` |

Request model `NetworkConfigRequest` carries: `Ssid`, `PassPhrase` / `Passphrase`, `WifiSecurity`, `Bssid` — the same fields the V2 `setConfig` wlan body uses.

### 3.1 SoftAP join flow (Android `WifiService`)

The Installer auto-joins the generator's SoftAP before talking to the API:

```
ScanForGenerators
  → filter SSIDs by GeneratorWifiNetworkPrefix = "MLG"
  → CreateNetworkIfNotExists / AddNetwork / EnableNetwork
  → ConnectToWifiNetwork
  → (now on 192.168.51.1) GainSpan V1 API calls above
```

Confirmed by the app's own UX strings: *"Check your generator's display for a network name starting with **MLG** and connect to that network"* and *"verify your generator's display is showing **SETUP WIFI NOW!**"*.

---

## 4. V1 ↔ V2 at a glance

| | V1 — GainSpan (1.x Installer) | V2 — Gecko OS (current Tether) |
|---|---|---|
| Module | GainSpan (e.g. GS2011-class) | Silicon Labs WGM160P / Gecko OS 4.2.3 |
| SoftAP IP | `192.168.51.1` | `192.168.51.1` |
| API base | `/gainspan/system/` | `/Generac/api/` |
| List networks | `GetNetworksAsync` | `networks` |
| Push creds | `PostNetworkConfig` | `setConfig` (wlan) |
| Poll status | `CheckConnection` | `status` |
| Finalize | — | `complete` |
| Enable iface | (implicit) | **`wifi_enable:true` first** (the fix) |
| SoftAP SSID | `MLG…` | `MLG…` |

> **The SoftAP SSID does not indicate the version.** Both generations broadcast an `MLG…` setup network — the V2/3.16 app's own troubleshooting text refers to "the MLG network". Version is decided by **which API answers at `192.168.51.1`**: `/gainspan/system/` = **V1**, `/Generac/api/` = **V2**. The `G0071700-…` name seen on the LAN is the device's DHCP **hostname**, not its SoftAP SSID. (Use `generac_provision.py probe` to detect the version directly.)

The shapes line up almost 1:1 — Generac kept the provisioning model and swapped the module + transport. The one modern wrinkle that isn't in V1 is the `wifi_enable`-first requirement (see [Tether RE §3.1](Generac-MobileLink-Tether-RE.md#31-the-critical-fix--wifi_enable)).

---

## 5. How each generation was analyzed

| Gen | Artifact | Method |
|---|---|---|
| 1.x | `assemblies/*.dll` (plain .NET PE) | strings from DLL + embedded `appsettings` JSON |
| 2.x | `assemblies/assemblies.blob` (Xamarin **XABA** store, partly LZ4) | strings from blob — partial (compressed sections opaque) |
| 3.x | `assets/index.android.bundle` (**Hermes** bytecode v96) | string-table extraction + pseudo-JS decompile |

Framework detection: `.bundle` magic `c61fbc03…` = Hermes; `Generac.*.dll` names = Xamarin; neither = native. Tooling in [../tools/](../tools/): `analyze_apk.py` (framework + marker matrix), `extract_native.py` (native/Xamarin string mining), `list_entries.py` (locate assemblies), `find_config.py` (dump a config block), `extract_dll_endpoints.py` (.NET endpoints), `verify_apk.py` (confirm an APK matches a known build).

---

## 6. Other artifacts surfaced

| Item | Value |
|---|---|
| Install/registration backend | `https://installml.com/` (V1 `InstallMLApi`) |
| Telemetry | Microsoft **AppCenter** — Android AppId `913bd46c-168d-4d66-be39-1f9dfe06ed9b`, iOS `7eecdaeb-f2e2-4f2a-b975-da7d79b87f49` |
| SoftAP SSID prefix | `MLG` (both V1 and V2 — not a version marker); `G0071700-…` is the LAN DHCP hostname |
| Generator display cue | `SETUP WIFI NOW!` when in provisioning mode |

---

## 7. What this unlocks

- **Older-controller provisioning** without the app: if a generator exposes the V1 GainSpan SoftAP, the same `generac_provision.py` approach applies against `/gainspan/system/` instead of `/Generac/api/` (the V1 path handler already exists in the tool as the `v1` firmware branch).
- A clean **before/after** of a vendor tightening a cloud tether across three app rewrites — the OpenJuice thesis, in a second device family.
