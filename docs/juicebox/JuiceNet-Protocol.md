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
| Charging controller ↔ WiFi module | UART, 9600 baud | The module's vendor app, `JB1_0.zap`, exchanges data with the ATmega; see §1.3 |
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

**Infrastructure status, checked 2026-10-05 [V].** The vendor domains are alive and actively held,
not dead or for sale. `emotorwerks.com` is registered through 2027-03-24, locked
(`clientTransferProhibited` and the rest), and served from Microsoft Azure DNS; `enelx.com` sits on
Enel's own nameservers behind Fastly. Both `directory-api.emotorwerks.com` (behind an Imperva WAF)
and `jbv1.emotorwerks.com` answer HTTP 200. The apex `emotorwerks.com` refuses HTTPS, so there is no
public website, but the API hosts are maintained. Despite the directory endpoint being up, this unit
still cannot complete the handshake: its `/log` loops `Opening … Open failed` and telemetry carries
`JCom_TxTcpData open err 5035` against the directory URL, consistent with its 2021-era bundled CAs
(`godaddy_ca.pem`, `starfield.pem`) no longer validating the current endpoint's certificate **[I]**.
That ongoing handshake failure is exactly what keeps the DNS fallback, and therefore our redirect,
working. Watch it: if a cert refresh or firmware change let the handshake succeed, the fallback would
stop and the redirect with it. The domain is not acquirable, so hosting our own endpoint under that
name is not an option.

### 1.2 The socket is connected

The module opens a *connected* UDP socket to its server. It accepts replies **only from the exact
address and port it sent to** **[V]**. A local server therefore has to be the address the charger
resolved, which is what the DNS redirect arranges, or has to spoof that address. When no reply comes
back, the module periodically reopens the socket from a new ephemeral source port **[V]**, so a
server must answer to the source port of the latest frame, not a cached one.

### 1.3 The controller-to-module link

Researched 2026-10-02 from the recovered eMotorWerks source, the v8.12 factory tester, this unit's
module configuration and its logged telemetry. No source for the 8.14+ controller firmware has been
found, so the dialogue on this unit's link is **not known**.

**What the older design did** **[D]**, `JB_firmware_V8_10_7.ino` and `JB_WiFi_Programmer_V8P.ino`:

- The WiFi module was a Roving Networks WiFly in transparent UDP mode. The ATmega composed each
  report itself and printed it to the module: `<ID>:V..,L..,E..,A..,T..,t..:` plus a newline.
- The link was SoftwareSerial at 9600 baud, D2 receive and D4 transmit.
- The server's reply arrived raw on the same link, `CMD<w><HH><MM>A<amps>C<flag>$`, and the ATmega
  parsed it. An amps value below 6 stopped charging.
- With no reply for 90 s, the ATmega pulsed the module's reset pin, D12, and went back to its full
  current rating. This is the ancestor of today's offline-limit fallback.

Today's frame keeps that shape: the same `ID:` prefix, trailing colon, field letters and `CMD`
format, with a checksum and more fields added.

**What this unit does:**

- **The module's app composes the frames, not the ATmega** **[V]**. `u` and `i` restart from zero
  when the module alone reboots: `u` read 6700 and 10700, 67 s and 107 s after two module reboots.
  Both counters also froze while the app was stuck opening its socket: in a 3,165 s gap on
  2026-09-26, `u` advanced exactly 900 and `i` by one.
- So the ATmega supplies the measurements (`V`, `A`, `f`, `p`, `T`, `S`, `E`, `L`, `M`, `m`) to
  the module's app over the UART, and takes the limit back. Whether it pushes or is polled, and in
  what format, is unknown.
- The module's UART is `uart0`, 9600 8N1, no flow control, with the bus in **command mode**, echo
  and prompt on **[V]**. Echo and prompt are the human-terminal settings, which suggests the app
  reads the UART through the native API and the command parser is not what the ATmega talks to
  **[I]**.
- **The link is probably on the ATmega's hardware serial pins, D0 and D1** **[I]**. The v8.12 tester
  gives D4 and D5 to the metering chip and calls D2 free, leaving D0/D1 as the only serial pair.

**Consequences for the port:**

1. **Capture the stock dialogue before flashing.** With the enclosure open in Phase 1, a
   receive-only tap on both UART lines at 9600 baud records exactly what the stock ATmega and the
   app say to each other. Once the ATmega is reflashed that knowledge is gone for good.
2. **OpenEVSE's RAPI also lives on D0/D1 at a configurable baud.** If the link is there, RAPI
   reaches the module with no wiring change. It also means a serial adapter on those pins fights
   the module, and everything OpenEVSE prints lands in the module's command parser or its app.
3. **D12 resets the WiFi module on V8.10 and v8.12**, active low on V8.10 and either polarity on
   v8.12. The current patch drives D12 as the GFI test pin, which is right only for V8.9. On a later
   board that would reset the module at every self-test. The port must hold D12 inactive.
4. **The vendor app will lose its data source.** After the port it will see OpenEVSE output
   instead of the stock dialogue. Its reaction is unknown: stale or empty frames at best. It still
   has to run, because it brings up WiFi. The capture in item 1 shows what it expects.

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
| `M<offline>` | **Offline** current limit, two digits on `v07`. Believed to be the value the charger reverts to when commands stop (~6 min) **[I]** — but **2026-10-12 saw no such fallback [V]:** with the helper blocked ~2 h the module held its 40 A online limit and the car drew 31.7 A, never 26 A. Do not rely on this field protecting the circuit |
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
| `faults_reset` (short `faur`) | Clear the crash log back to 0 of 8; present in `help commands`, returns `Success` **[V]** | Clears the stored fault counter (owner's decision) |
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

**When the module hangs** ([issue #1](https://github.com/jdinino/OpenJuice/issues/1)). The module
can hang at the application layer. It still answers pings and accepts TCP connections on port 80,
but closes every request after about 2 s with **0 bytes**, stops its beacon, and sends no DNS
queries or telemetry **[V]**. A hang does **not** add an entry to `faults_print`, and the module
does not reboot itself **[V]**. `reboot` still takes effect in this state even though the reply is
empty **[V]**. `tools/juicebox/juicebox_helper.py` treats three empty replies in a row as a hang and
sends `reboot`.

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
| Offline-limit fallback | Claimed ~6 min from community reports; **not reproduced** — 2026-10-12 the module stayed at 40 A for ~2 h with no fallback to the stored limit |
| Status `5` | Error, per other implementations; never observed here |
