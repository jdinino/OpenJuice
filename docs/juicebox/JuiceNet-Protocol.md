# JuiceNet Protocol and Module Interfaces — JuiceBox Gen 1

Reference for everything the stock JuiceBox Gen 1 exposes on the network: the JuiceNet UDP
telemetry and command protocol, the WiFi module's web command interface, and the energy logs on the
module's flash. Extracted from the [security assessment](JuiceBox-Gen1-Pentest-RE.md) and extended
with later verification.

**Reference unit:** `EMWERK-JB_1_1-1.4.0.28` on ZentriOS-WZ 3.6.4.0, protocol `v07`, unencrypted.
**Tiers:** **[V]** verified on the reference unit · **[D]** documented by a primary source ·
**[I]** inferred.

Working implementations of everything here are in [tools/juicebox/](../../tools/juicebox/).

---

## 1. Who talks to whom

| Link | Carrier | Notes |
|---|---|---|
| Charging controller ↔ WiFi module | UART | The module's vendor app, `JB1_0.zap`, exchanges data with the ATmega |
| WiFi module → cloud | UDP to port 8042 | **Composed by the module's app, not the ATmega** **[V]**: frames carry WiFi RSSI and HTTP errors only the module can know, and a `zn_` native-API function name |
| Cloud → WiFi module | UDP replies on the same socket | Commands, relayed to the ATmega |
| WiFi module → LAN | UDP 55555 broadcast | Discovery beacon; see [ZentriOS-Gecko-LAN-Discovery.md](../ZentriOS-Gecko-LAN-Discovery.md) |
| LAN → WiFi module | HTTP port 80, TCP port 2000 | Web command interface and remote terminal, both unauthenticated |

### 1.1 How the charger picks its server

At boot the module asks `directory-api.emotorwerks.com` over HTTPS for its server **[V]**.

- **When that succeeds** it uses the returned endpoint, which can be a fixed IP address, and makes
  no further DNS lookups. Seen in February 2026: telemetry to `158.47.1.128:8042` **[V]**.
- **When it fails** it falls back to a built-in hostname and resolves it by DNS. Seen from September
  2026 on the reference unit: `jbv1.emotorwerks.com:8042` **[V]**. The Enel X name
  `juicenet-udp-prod5-usa.enelx.com` has also been queried **[V]**.

The DNS redirect used for local control only works in the second case. The directory response also
carries an `encrypt` flag, which switched another unit to encrypted telemetry mid-session **[D]**.

### 1.2 The socket is connected

The module opens a *connected* UDP socket to its server. It accepts replies **only from the exact
address and port it sent to** **[V]**. A local server therefore has to be the address the charger
resolved, which is what the DNS redirect arranges, or has to spoof that address. When no reply comes
back, the module periodically reopens the socket from a new ephemeral source port **[V]**, so a
server must answer to the source port of the latest frame, not a cached one.

---

## 2. Telemetry frames

Sent every `t` seconds, 9 s by default. One frame per datagram, ASCII:

```
<serial>:v07,<field><value>,<field><value>,...!<checksum>:
0817081001070449032218248303:v07,s0011,u05212,V2346,L0028642122,S2,T26,M26,m40,t09,i17,e-001,f6003,X0,Y0,E006188,A0257,p0996!8U9:
```

The checksum covers everything from the serial number to the last field, and uses the same algorithm
as commands (§3.3): **7,523 of 7,523 logged frames verify** **[V]**.

### 2.1 Fields

| Field | Meaning | Scale | Tier |
|---|---|---|---|
| `v` | Protocol version | `07` on this unit | V |
| `s` | **Command acknowledgement:** the `S` sequence number of the last command accepted | — | V |
| `u` | Counter, **not uptime**: advances 100 per second and wraps at 65,536 | 0.01 s | V |
| `V` | Line voltage | × 0.1 V | V |
| `L` | Lifetime energy | Wh | V |
| `S` | Status: `0` unplugged, `1` plugged in, `2` charging, `5` error | — | V for 0–2 |
| `T` | Board temperature. The sensor is a dedicated thermistor on v8.12 boards and the ATmega's die sensor on V8.9 and V8.10 **[D]**; which one this unit uses is unconfirmed | °C | V |
| `M` | **Online** current limit, the value the server last set | A | V |
| `m` | Circuit rating, the hardware ceiling | A | V |
| `t` | Report interval. The gap between frames equals it | s | V |
| `i` | Frame counter: steps once per frame and wraps 0–95 | — | V |
| `e` | Undecoded. `-001` in every idle frame so far | — | — |
| `f` | Line frequency | × 0.01 Hz | V |
| `X`, `Y` | Undecoded. Always `0` so far | — | — |

Present only while charging:

| Field | Meaning | Scale | Tier |
|---|---|---|---|
| `A` | Charging current | × 0.1 A | V |
| `p` | Power factor | × 0.001 | V |
| `E` | Energy this session | Wh | V |

`C`, the **offline** limit, is defined by other implementations but has never appeared in this
unit's telemetry **[V]**. The offline limit cannot be read back.

**Corrections to earlier readings of this table.** `t` was once labelled board temperature, `f` free
memory, `T` a temperature offset, `u` uptime in seconds, and `S1` "normal operation". Each is
disproved by the data above.

### 2.2 Debug frames

The same socket also carries module diagnostics in place of the field list **[V]**:

```
<serial>:DBG,NFO:RSSI -73
<serial>:DBG,ERR:JCom_TxTcpData req err 301,2(http://callcenter.voltie.us/.../keys)
<serial>:DBG,CRI:zn_app_deinit
```

---

## 3. Commands

### 3.1 Format

```
CMD<weekday><HHMM>A<online>M<offline>C<command>S<seq>!<checksum>$
CMD41247A26M26C006S011!67I$
```

| Part | Meaning |
|---|---|
| `<weekday>` | `0` Sunday … `6` Saturday, local time |
| `<HHMM>` | Local time, 24-hour |
| `A<online>` | **Online** current limit, two digits on `v07` |
| `M<offline>` | **Offline** current limit, two digits on `v07`. The charger falls back to it when commands stop, after roughly 6 minutes **[I]** |
| `C<command>` | Three digits; `006` works. **Not an opcode table** |
| `S<seq>` | Sequence number, three digits. Echoed in telemetry `s` when accepted |

⚠️ **The letters swap meaning between directions.** In a command, `A` is the online limit and `M` the
offline limit. In telemetry, `A` is the measured current and `M` the online limit.

Later JuiceBox models use a wider form, `A<4 digits>M<3 digits>`, still in **whole amps**: `0040`
means 40 A **[D]**.

### 3.2 Behaviour

- **Whole amps only** **[D]**. No format carries a fraction, the stock firmware parses the value
  into an integer, and the vendor's setup app offers whole amps. The J1772 minimum is 6 A.
- **Acknowledgement** **[V]**. The next frame after an accepted command reports its sequence number
  in `s` and the new online limit in `M`.
- **EEPROM** **[I]**. Each accepted command rewrites the offline limit in the ATmega's EEPROM, so
  commands should be sent once and confirmed, never repeated every frame. `set_limit.py` does this.
- **No start or stop command.** Setting the online limit to `0` pauses charging, and resets session
  energy and cycles the contactor **[D]**.
- **After a module reboot** the cloud re-pushed its own limit, 40 A, on both occasions observed **[V]**.

### 3.3 Checksum

A 16-bit hash, then base 35 with the least significant digit first. Digit 24, which would be `O`, is
written as `Z` to avoid confusion with zero.

```python
def checksum(payload):
    h = 0
    for c in payload:
        h ^= (h << 5) + (h >> 2) + ord(c)
        h &= 0xFFFF
    alphabet, out = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", ""
    while h > 1 or len(out) < 3:
        h, i = divmod(h, 35)
        out += alphabet[35 if i == 24 else i]
    return out
```

For commands, `payload` runs from `CMD` to the sequence number. For telemetry it runs from the serial
number to the last field.

---

## 4. The WiFi module's web command interface

ZentriOS serves its full command API over HTTP on port 80, with **no authentication** **[V]**.

```
GET  http://<charger>/command/<command with spaces as %20>
POST http://<charger>/command/      {"command": "...", "data": "..."}      for commands carrying data
->   {"id": 12, "code": 0, "flags": 0, "response": "Success\r\n"}           code 0 success, 3 unknown command
```

| Command | Use | Effect |
|---|---|---|
| `get <variable>`, `get all` | Read configuration and state | None |
| `faults_print` | Crash log; Safe Mode after 8 entries | None |
| `ls`, `ls -v` | File list, with types and handles | None |
| `stream_list` | Open sockets, including the cloud stream and its source port | None |
| `set <variable> <value>` | Change a variable, live until the next reboot | Live only |
| `save` | Persist all variables to flash | **Persistent** |
| `network_restart` | Rejoin WiFi with the current settings; back in about 5 s | Brief outage |
| `reboot` | Restart the module; back in about 35–45 s. Not counted as a fault | Reverts unsaved changes |

**Do not use without a specific reason:** `network_verify` drops the WiFi connection; `stream_read`
consumes the live telemetry; `file_open` leaks a handle; `factory_reset`, `format_flash` and `ota`
are destructive; `set zap.auto_run` can permanently stop the vendor app, which may be what brings
WiFi up.

**Practical limits.** At most 3 HTTP clients. One command parser is shared with the module's serial
link to the charging controller, so send one request at a time. Port 2000 is the same parser as a raw
TCP shell with an empty password, and a connected session disables the local command interface.

Commands added by the vendor's later apps do not exist on this firmware: `maxcurrent_app` returns
`Unknown command` **[V]**.

---

## 5. Energy logs on the module's flash

Three families of files, all served over plain HTTP at `http://<charger>/<filename>` **[V]**.

### 5.1 Container

They are ZentriOS **log files**, written by the module's app through the native API **[V]**. The
command interface has no way to write them, which is how we know the ATmega is not the author.

Parse from offset 0: read a `u16`, little-endian. `0xFFFF` means end of data. Otherwise the low 15
bits are the payload length and the top bit is a *valid* flag, **clear when valid**. Read the payload
and repeat. `size = slots × (2 + payload) + 2` holds for all three.

| File | Size | Slots | Payload |
|---|---|---|---|
| `ECache_03_<day>Z-01-01` | 1,538 | 192 | 6 bytes: three `u16` LE watt-hour samples |
| `Events_03_<day>Z-01-01` | 2,342 | 130 | 16 bytes, §5.3 |
| `ELife_<n>` | 122 | 20 | 4 bytes: `u32` LE lifetime watt-hours |

`<day>` is the hex count of days since 1970-01-01, always even; each file covers 48 hours **UTC**.
Example: `050ee` is day 20,718, 2026-09-22.

### 5.2 `ECache`: 5-minute energy

192 slots × 3 samples = **576 five-minute buckets** per file. `0xFFFF` means no data.
Watt-hours × 12 = average watts over the bucket. The buckets agree with the session records
exactly: a charge on 2026-09-24 logged 23,651 Wh here, and its two session-end records in `Events`
sum to the same figure **[V]**.

### 5.3 `Events`: plug and session events

| Offset | Size | Field |
|---|---|---|
| 0–3 | 4 | Session energy, `u32` **big-endian** Wh; non-zero only on `0x43` |
| 4–10 | 7 | Always zero so far |
| 11 | 1 | Event code |
| 12–15 | 4 | Monotonic tick counter, big-endian. Unit unknown; do not convert to time |

| Code | Event |
|---|---|
| `0x40` / `0x41` | EV connected / disconnected |
| `0x42` / `0x43` | Session start / end, with energy |
| `0x80` / `0x81` | Seen in pairs; meaning unknown |

Filter out zero-watt-hour `0x43` records before totalling. Sessions can span two files.

### 5.4 `ELife`: lifetime energy

A 20-slot ring of the lifetime counter. It matches telemetry `L` exactly when idle and trails it by
tens of watt-hours while charging, because it is written periodically **[V]**. **The suffix rotates**: `ELife_0`, `_1` and `_2` have all been seen. Match by
prefix; never hardcode the name.

---

## 6. Open questions

| Item | What is known |
|---|---|
| `e`, `X`, `Y` telemetry fields | Undecoded; constant while idle |
| Events `0x80` / `0x81` | Paired; meaning unknown |
| Events tick unit | No single rate fits the sessions measured |
| Offline-limit fallback delay | About 6 minutes, from community reports, not measured here |
| Status `5` | Error, per other implementations; never observed here |
