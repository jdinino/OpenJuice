# Generac Mobile Link — Cloud REST API (recovered contract)

**Status:** Reverse-engineered from the 2.x Xamarin `Generac.Application.MobileLink.ApiClient.dll`, 2026-07-14
**Companion to:** [App Lineage](MobileLink-App-Lineage.md) · [Tether RE](Generac-MobileLink-Tether-RE.md)

---

## 1. Where this came from

The 2.x app (`com.generac.standbystatus` 2.28.0) is Xamarin/.NET. Its cloud client
is an **AutoRest/Swagger-generated** class, `MobileLinkClient`, so every operation,
route template, and model is legible C#. The assemblies were extracted from the
Xamarin **XABA assembly store** (`assemblies/assemblies.blob`), which stores each
DLL **LZ4-compressed** (`XALZ`) — decompressed with a pure-Python LZ4 block decoder
(no external deps). Tooling: [`../tools/xaba_extract.py`](../tools/), `route_config.py`.

This is the authoritative spec for the cloud path chosen for local-independent
telemetry (register once → poll). The 2.x app uses `api/v2`; the current 3.x app
uses `api/v5` at the same host with the same path structure — version-bumped, not
restructured.

---

## 2. Base + auth

| | Value |
|---|---|
| Base URL | `https://app.mobilelinkgen.com/api/v5/` (2.x used `api/v2`; paths below shown as `v2` verbatim) |
| Auth | **Azure AD B2C** bearer token — `Authorization: Bearer <jwt>` |
| B2C authority | `https://generacconnectivity.b2clogin.com/tfp/generacconnectivity.onmicrosoft.com` |
| Tenant | `generacconnectivity.onmicrosoft.com` |
| Policies | `B2C_1A_MobileLink_SignIn`, `…_SignUp`, `…_ChangePassword`, `…_UpdateProfile`, plus an account-**Migration** policy |
| Scope | `https://generacconnectivity.onmicrosoft.com/cf3e2bfb-2d0c-47dd-8067-bf59a6f88ed7/client` + `openid profile offline_access` |
| Client ID | likely `072cb28a-e900-4a82-99c3-a39f5ab188b2` (from the app's `msal072cb28a…` redirect scheme; `cf3e2bfb…` is the API/scope app). Confirm from captured MSAL storage. Used for the refresh-token grant. |

**Bootstrap quirk:** the app doesn't hardcode most of this — `ApplicationService.LoadAllFromAzure()` pulls a config object (`BasePaths`, `Scopes`, `ClientId`, `TenantId`, `PolicySignIn/SignUp/UpdateProfile/Migration`, `FeatureFlags`, `RemoteDatabaseTables`) at runtime from:

```
GET api/v2/Application/{application}/configuration
```

The B2C authority/scope above (from the 3.x bundle) is the piece needed to obtain a token; everything else the config endpoint will return.

---

## 3. Endpoints that matter (exact route templates)

Recovered verbatim from `MobileLinkClient`. Names are the AutoRest operation methods.

### Monitor (read)
| Operation | Route |
|---|---|
| `GetApparatusOverviewList` / `list` | `GET api/v2/Apparatus/list` |
| `GetApparatusById` | `GET api/v2/Apparatus/{id}` |
| **`GetApparatusDetails`** | **`GET api/v2/Apparatus/details/{apparatusId}`** ← battery/fuel/run-hours/signal/status |
| `GetApparatusStatusHistory` | `GET api/v2/Apparatus/statusHistory/{apparatusId}` |
| `GetApparatusMaintenance` | `GET api/v2/Apparatus/maintenanceDetails/{apparatusId}` |
| `GetApparatusTechnicalSpecs` | `GET api/v2/Apparatus/specifications/{apparatusId}` |
| `GetApparatusExerciseSchedule` | `GET api/v2/Apparatus/exercise/{apparatusId}` |

### Control (write)
| Operation | Route |
|---|---|
| **`ExerciseApparatusNow`** | `GET api/v2/Apparatus/exerciseNow/{apparatusId}` (start exercise now) |
| `SetApparatusExerciseSchedule` | `POST api/v2/Apparatus/exercise/{apparatusId}` |
| `UpdateApparatusStatus` | `POST api/v2/Apparatus/status/{apparatusId}/{newStatus}` |
| `ClearMaintenanceAlert` | `POST api/v2/Apparatus/{apparatusId}/clearMaintenanceAlert` |
| `UpdateApparatus` | `PUT api/v2/Apparatus/update/{apparatusId}` |

### Register / enroll (the one-time step to unlock telemetry)
| Operation | Route |
|---|---|
| `VerifySerialNumber` / `IsRegistered` | `GET api/v2/Apparatus/isRegistered/{serialNumber}` |
| `RegisterSerialNumbers` | `POST api/v2/Apparatus/{organizationId}/serial/number/register` |
| `EnrollApparatus` (validate serial) | `POST api/v2/Apparatus/enrollment/validate/serialNumber/{serialNumber}` |
| `EnrollApparatus` (validate device) | `POST api/v2/Apparatus/enrollment/validate/device` |
| `EnrollApparatus` (device) | `POST api/v2/Apparatus/enrollment/device` |
| `EnrollApparatus` (finalize) | `POST api/v2/Apparatus/enrollment` |
| `AddDeviceToApparatus` | `POST api/v2/Apparatus/{id}/connect` |
| `RemoveApparatus` | `DELETE api/v2/Apparatus/remove/{organizationId}/{apparatusId}` |

(Also present but out of scope here: Account/preferences, Dealer, Subscription/billing, TankUtility fuel, VirtualPowerPlant, Ecobee, Migration, push registration.)

---

## 4. Telemetry model (`ApparatusDetails` / status)

Property names straight off the DTO backing fields — these are the metrics a Grafana feed would chart:

| Group | Fields |
|---|---|
| Identity | `ApparatusId`, `ApparatusName`, `ApparatusType`, `ApparatusModelNumber`, `ApparatusPanelId`, `SerialNumber`, `DeviceId` / `FullDeviceId` / `ShortDeviceId` / `CommDeviceId` |
| Status | `ApparatusStatus`, `ApparatusRunHours`, `HasMaintenanceAlert`, `IsEnrolled`, `Provisioned`, `EnrolledInVpp` |
| Battery | `BatteryLevel`, `BatteryPower`, `BatteryVoltage`, `BatteryVoltageatECU` |
| Fuel | `FuelLevel`, `FuelLevelPercent`, `FuelRemaining`, `FuelType`, `FuelCapacity`, `FuelPressure`, `FuelPressureRunning` / `…Cranking` |
| Signal | `SignalStrength`, `Rssi`, `CellularSignalStrength` |
| Engine / other | `ExerciseHours`, `EngineMaintenanceTime`, `CurrentWeather`, `CODeviceStates`, `Maintenance*` |

---

## 5. What this enables

1. **Full local-independent monitoring.** `Apparatus/list` → `Apparatus/details/{id}` gives battery/fuel/run-hours/signal/status with exact field names — a Grafana/InfluxDB poller with zero guesswork. (The device itself exposes none of this locally; see [Tether RE](Generac-MobileLink-Tether-RE.md).)
2. **Control, not just read.** `exerciseNow`, exercise-schedule, and status endpoints mean a home-automation integration can *command* the generator, not merely observe it.
3. **Scripted registration.** The exact `isRegistered → enrollment/validate → enrollment/device → enrollment` sequence lets the one-time device enrollment be done via API (keyed on the generator serial), independent of the app's provisioning webview.
4. **Self-configuring auth.** `Application/{application}/configuration` returns the live B2C client/tenant/policy set + base paths, so a client can bootstrap its own config the way the app does.
5. **A clean OpenAPI target.** Because it's an AutoRest client, the recovered routes + models can be reassembled into an OpenAPI/Swagger doc and a typed client generated in any language.

---

## 6. Reproduce

```sh
python tools/list_entries.py  "Mobile Link ... 2.28.0 ....apk"   # find the XABA blob
python tools/xaba_extract.py                                     # decompress + mine Generac DLLs
python tools/route_config.py                                     # dump route templates + config
```

> All routes/fields here are reverse-engineered from a publicly downloadable APK for
> interoperability with the owner's own hardware — no credentials or private keys are
> included. B2C `client_id`/scope are public mobile-client identifiers.
