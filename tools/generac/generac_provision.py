"""
Generac MLG (Mobile Link Gen) Wi-Fi accessory provisioning — without the app.

Use:
    1. On the generator controller, start Wi-Fi setup.
    2. Watch the controller display: it should show "SETUP WIFI?" then a
       countdown timer and an SSID like "MLGxxxx" rotating across the panel.
    3. On the laptop running this script, disable mobile data / unplug
       Ethernet so all traffic goes via Wi-Fi, then join "MLGxxxx".
       Accept "stay connected" if the OS warns the network has no internet.
    4. Verify your laptop got an address in 192.168.51.0/24:
           python -c "import socket; print(socket.gethostbyname(socket.gethostname()))"
       (Should be 192.168.51.x — the AP is the gateway at 192.168.51.1.)
    5. Run:   python generac_provision.py probe
       to detect V1 (gainspan) vs V2 (Generac/api) firmware.
    6. Run:   python generac_provision.py scan
       to list nearby Wi-Fi networks the generator can see.
    7. Run:   python generac_provision.py connect "YourHomeSSID" "YourPassword"
       (add --bssid / --channel / --security if needed — see scan output).

Endpoints reverse-engineered from Mobile Link 3.16.0
(com.generac.standbystatus, package version code 87617).
"""

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request

AP_HOST = "192.168.51.1"
V1_BASE = f"http://{AP_HOST}/gainspan/system/"
V2_BASE = f"http://{AP_HOST}/Generac/api/"

V1_TIMEOUT = 10.0
V2_TIMEOUT = 20.0


# ---------- UDP broadcast listener (offline telemetry sniff) ----------

def listen_udp(port=55555, count=10, save=None, from_ip=None):
    """Listen for UDP broadcasts and dump payloads.

    The generator's Tether module broadcasts continuously to
    255.255.255.255:55555 — likely local telemetry with no TLS/auth. Since
    it's a LAN broadcast, any host on the subnet receives it; no router
    capture needed. We print each packet as hex + printable-ASCII so we can
    fingerprint the format (JSON? binary struct? protobuf?).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    s.bind(("", port))
    print(f"[listen] bound to UDP :{port}, waiting for {count} packet(s) …")
    print(f"[listen] (if nothing arrives, allow inbound UDP {port} in Windows Firewall)\n")

    raw_saved = []
    got = 0
    s.settimeout(30.0)
    while got < count:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            print("[listen] 30s with no packet — is the device powered / on the LAN?")
            break
        if from_ip and addr[0] != from_ip:
            continue
        got += 1
        raw_saved.append(data)
        print(f"--- packet {got}  from {addr[0]}:{addr[1]}  len={len(data)} ---")
        # printable-ASCII view
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        print(f"  ascii: {printable[:200]}")
        # hex view of first 64 bytes
        hexstr = " ".join(f"{b:02x}" for b in data[:64])
        print(f"  hex  : {hexstr}{' …' if len(data) > 64 else ''}")
        # if it looks like JSON, try to pretty-print
        stripped = data.strip()
        if stripped[:1] in (b"{", b"["):
            try:
                print(f"  JSON : {json.dumps(json.loads(stripped))[:300]}")
            except Exception:
                pass
        print()

    s.close()
    if save and raw_saved:
        with open(save, "wb") as f:
            for pkt in raw_saved:
                # length-prefixed frames so we can re-parse later
                f.write(len(pkt).to_bytes(4, "big") + pkt)
        print(f"[listen] saved {len(raw_saved)} raw packets to {save}")


# ---------- low-level HTTP helper ----------

def http(method, url, body=None, headers=None, timeout=10.0):
    data = None
    h = {"Accept": "*/*"}
    if headers:
        h.update(headers)
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except (ConnectionResetError, OSError):
            return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"<network: {e}>"


# ---------- probe ----------

def probe():
    """Return 'v2', 'v1', or None."""
    print(f"[probe] POST {V2_BASE}getConfig …")
    status, body = http(
        "POST", V2_BASE + "getConfig",
        body={"interface": "system"}, timeout=V2_TIMEOUT,
    )
    print(f"  -> {status} {body[:200]!r}")
    if status == 200:
        return "v2"

    print(f"[probe] GET {V1_BASE}api/version …")
    status, body = http(
        "GET", V1_BASE + "api/version", timeout=2.0,
    )
    print(f"  -> {status} {body[:200]!r}")
    if status == 200:
        return "v1"

    return None


# ---------- V2 (Generac/api, JSON) ----------

def v2_scan(max_polls=15, interval=2.0):
    """
    List nearby networks the generator sees.

    The /networks endpoint is async: first hit returns 202 with `null` while
    the radio is scanning, and subsequent hits return 200 once the result is
    ready. The Mobile Link app polls every 2s and gives up after 3 tries; we
    are more patient since a busy 2.4GHz band can take ~10s to enumerate.
    """
    for attempt in range(1, max_polls + 1):
        status, body = http("GET", V2_BASE + "networks", timeout=V2_TIMEOUT)
        print(f"[v2 scan attempt {attempt}] -> {status}  body={body[:120]!r}")
        if status == 200:
            try:
                return json.loads(body)
            except Exception:
                print("  (response was 200 but not JSON)")
                return body
        if status not in (200, 202):
            print(f"  (unexpected status {status}; bailing)")
            return None
        time.sleep(interval)
    print("[v2 scan] gave up — scan still pending after",
          f"{max_polls * interval:.0f}s")
    return None


def v2_enable_interfaces():
    """Enable the Wi-Fi (and Ethernet) radios.

    This is the app's `initializeSystemConfig` call, fired on the ConnectToAp
    screen when the device is a Tether (bundle line 1073447). The fresh device
    reports wifi_enable=false; if the STA radio is gated on this flag, we must
    flip it true BEFORE attempting to join, or the join silently never
    completes. We were skipping this entirely.
    """
    return http(
        "POST", V2_BASE + "setConfig",
        body={"interface": "system", "wifi_enable": True, "eth_enable": True},
        timeout=V2_TIMEOUT,
    )


def v2_initialize_system():
    """Put the connectivity module into system/wlan mode.

    NOTE: interface names are lowercase. Uppercase returns {"reason": 19}.
    """
    return http(
        "POST", V2_BASE + "setConfig",
        body={"interface": "system", "primary_interface": "wlan"},
        timeout=V2_TIMEOUT,
    )


def v2_set_wifi(ssid, passphrase, bssid="00:00:00:00:00:00",
                channel=0, security="WPA2-AES"):
    """Write the home Wi-Fi credentials to the accessory.

    `security`: scan reports values like "WPA2-AES", "WPA-AES", "WPA2-MIXED",
    "OPEN" — the firmware expects the SAME string back here. The hardcoded
    default matches what most home routers in 2024 broadcast. Override via
    --security if scan says otherwise.
    """
    payload = {
        "interface": "wlan",
        "ssid": ssid,
        "bssid": bssid,
        "channel": channel,
        "security": security,
        "passphrase": passphrase,
        "dhcp_enable": True,
    }
    # Echo the outgoing payload (passphrase length only — don't print it)
    safe = dict(payload)
    safe["passphrase"] = f"<{len(passphrase)} chars>"
    print(f"[v2] outgoing setConfig body: {json.dumps(safe)}")
    return http(
        "POST", V2_BASE + "setConfig",
        body=payload, timeout=V2_TIMEOUT,
    )


def v2_connect():
    return http("GET", V2_BASE + "connect", timeout=V2_TIMEOUT)


def v2_status():
    return http("GET", V2_BASE + "status", timeout=V2_TIMEOUT)


def v2_complete():
    return http("POST", V2_BASE + "complete", timeout=V2_TIMEOUT)


def v2_provision(ssid, passphrase, security="Auto", bssid="", channel=0,
                 poll_secs=60):
    print(f"[v2] enable interfaces (wifi_enable=true) …")
    s, b = v2_enable_interfaces()
    print(f"     -> {s} {b[:200]!r}")
    if s != 200:
        print("     WARNING: enable-interfaces did not return 200; continuing anyway")

    # Read back to confirm wifi_enable actually flipped.
    s, b = http("POST", V2_BASE + "getConfig", body={"interface": "system"},
                timeout=V2_TIMEOUT)
    if s == 200:
        try:
            cfg = json.loads(b)
            print(f"     readback: wifi_enable={cfg.get('wifi_enable')} "
                  f"eth_enable={cfg.get('eth_enable')} "
                  f"primary_interface={cfg.get('primary_interface')!r}")
        except Exception:
            pass

    print(f"[v2] initializeSystemConfig (primary_interface=wlan) …")
    s, b = v2_initialize_system()
    print(f"     -> {s} {b[:200]!r}")
    if s != 200:
        sys.exit("initializeSystemConfig failed; aborting before writing creds")

    print(f"[v2] setConfig(WLAN, ssid={ssid!r}) …")
    s, b = v2_set_wifi(ssid, passphrase, bssid=bssid, channel=channel,
                       security=security)
    print(f"     -> {s} {b[:200]!r}")
    if s != 200:
        sys.exit("setConfig(WLAN) failed; credentials NOT applied")

    print(f"[v2] connect …")
    s, b = v2_connect()
    print(f"     -> {s} {b[:200]!r}")

    deadline = time.time() + poll_secs
    while time.time() < deadline:
        time.sleep(2)
        s, b = v2_status()
        print(f"[v2] status -> {s} {b[:200]!r}")
        if s is None:
            # network gone — likely because the AP shut down and our phone/PC
            # is now hunting for its previous Wi-Fi; that's the success signal.
            print("[v2] AP dropped — generator probably joined your Wi-Fi.")
            break
        if s == 200 and "successful" in b.lower():
            break

    # Best-effort final ACK; will often fail because the AP is gone.
    s, b = v2_complete()
    print(f"[v2] complete -> {s} {b[:200]!r}")


# ---------- V1 (gainspan, XML) ----------

def v1_xml_build(obj):
    """Render a nested dict to a simple XML doc, fast-xml-parser-compatible."""
    def render(node):
        out = []
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    out.append(f"<{k}>{render(v)}</{k}>")
                else:
                    out.append(f"<{k}>{'' if v is None else v}</{k}>")
        elif isinstance(node, list):
            for item in node:
                out.append(render(item))
        else:
            out.append(str(node))
        return "".join(out)
    return render(obj)


def v1_initialize_wifi():
    """V1 sends POST to the base path with empty body. Yes, really."""
    return http("POST", V1_BASE, body={}, timeout=V1_TIMEOUT)


def v1_scan():
    """V1 ap_list returns XML; we just dump it for the caller."""
    return http("GET", V1_BASE + "prov/ap_list",
                headers={"Accept": "text/xml"}, timeout=V1_TIMEOUT)


def v1_set_network(ssid, passphrase, security="wpa2", channel=0):
    body = {
        "network": {
            "client": {
                "mode": "client",
                "wireless": {
                    "ssid": ssid,
                    "password": passphrase if security != "open" else "",
                    "channel": channel,
                    "security": security,    # 'wpa2' or 'open' (lowercase)
                },
                "ip": {"ip_type": "dhcp"},
            }
        }
    }
    xml = v1_xml_build(body)
    return http(
        "POST", V1_BASE + "config/network",
        body=xml.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=V1_TIMEOUT,
    )


def v1_provision(ssid, passphrase, security="wpa2", channel=0):
    print(f"[v1] initializeWifi …")
    s, b = v1_initialize_wifi()
    print(f"     -> {s} {b[:200]!r}")
    print(f"[v1] config/network ssid={ssid!r} …")
    s, b = v1_set_network(ssid, passphrase, security=security, channel=channel)
    print(f"     -> {s} {b[:200]!r}")
    print("[v1] No explicit /connect on V1 — the accessory should leave the")
    print("     SoftAP and join your network within ~30s. Reconnect your PC")
    print("     to your home Wi-Fi and look for the generator's IP via your")
    print("     router admin page.")


# ---------- dump (read-only recon) ----------

# Endpoints proven safe to hit (read-only, no side effects on the device).
# Order: known-good first, then speculative.
DUMP_PROBES = [
    # ---- V2 known-good (decompiled from app) ----
    ("POST", V2_BASE + "getConfig", {"interface": "system"}),
    ("POST", V2_BASE + "getConfig", {"interface": "SYSTEM"}),
    ("POST", V2_BASE + "getConfig", {"interface": "WLAN"}),
    ("POST", V2_BASE + "getConfig", {"interface": "wlan"}),
    ("POST", V2_BASE + "getConfig", {"interface": "ETHERNET"}),
    ("POST", V2_BASE + "getConfig", {"interface": "ethernet"}),
    ("POST", V2_BASE + "getConfig", {"interface": "AP"}),
    ("POST", V2_BASE + "getConfig", {"interface": "STATION"}),
    ("POST", V2_BASE + "getConfig", {}),
    ("GET",  V2_BASE + "status",    None),
    # ---- V1 names tried on V2 path (Gecko OS shares its underlying surface) ----
    ("GET",  V2_BASE + "api/version",       None),
    ("GET",  V2_BASE + "capabilities",      None),
    ("GET",  V2_BASE + "firmware/version",  None),
    ("GET",  V2_BASE + "config/id",         None),
    ("GET",  V2_BASE + "config/network",    None),
    ("GET",  V2_BASE + "config/otafu",      None),
    ("GET",  V2_BASE + "certs",             None),
    ("GET",  V2_BASE + "time",              None),
    ("GET",  V2_BASE + "prov/scan_params",  None),
    ("GET",  V2_BASE + "GeneracTimeServerJWT", None),
    ("GET",  V2_BASE + "GeneracTimeZone",   None),
    ("GET",  V2_BASE + "GeneracConfig",     None),
    # ---- Same names on the V1 base, just in case ----
    ("GET",  V1_BASE + "api/version",       None),
    ("GET",  V1_BASE + "capabilities",      None),
    ("GET",  V1_BASE + "firmware/version",  None),
    ("GET",  V1_BASE + "config/id",         None),
    ("GET",  V1_BASE + "config/network",    None),
    ("GET",  V1_BASE + "config/otafu",      None),
    ("GET",  V1_BASE + "certs",             None),
    ("GET",  V1_BASE + "time",              None),
    ("GET",  V1_BASE + "prov/scan_params",  None),
    ("GET",  V1_BASE + "prov/ap_list",      None),
    # ---- Roots / discovery ----
    ("GET",  f"http://{AP_HOST}/",                 None),
    ("GET",  f"http://{AP_HOST}/index.html",       None),
    ("GET",  f"http://{AP_HOST}/info",             None),
    ("GET",  f"http://{AP_HOST}/Generac/",         None),
    ("GET",  f"http://{AP_HOST}/Generac/api/",     None),
    ("GET",  f"http://{AP_HOST}/gainspan/",        None),
    ("GET",  f"http://{AP_HOST}/gainspan/system/", None),
    # ---- Gecko OS / ZentriOS stock REST surface (often disabled in prod) ----
    ("GET",  f"http://{AP_HOST}/command/version",          None),
    ("GET",  f"http://{AP_HOST}/command/get/system.uuid",  None),
    ("GET",  f"http://{AP_HOST}/command/get/wlan.ssid",    None),
    ("GET",  f"http://{AP_HOST}/command/get/wlan.network.mac", None),
    ("GET",  f"http://{AP_HOST}/command/get/system.info",  None),
    ("GET",  f"http://{AP_HOST}/command/help",             None),
    ("GET",  f"http://{AP_HOST}/command/scan",             None),
    ("GET",  f"http://{AP_HOST}/var/system/version",       None),
    ("GET",  f"http://{AP_HOST}/var/wlan/info",            None),
    ("GET",  f"http://{AP_HOST}/var/wlan/ssid",            None),
    ("GET",  f"http://{AP_HOST}/var/wlan/network/mac",     None),
    ("GET",  f"http://{AP_HOST}/var",                      None),
]


def dump(verbose=True, host=None):
    """Hit every safe read-only endpoint and report what came back.

    host: override AP_HOST. When the device is on the home network, pass its
    home-network IP to probe the post-provisioning surface.
    """
    probes = DUMP_PROBES
    if host is not None and host != AP_HOST:
        probes = [
            (m, u.replace(AP_HOST, host), b) for (m, u, b) in DUMP_PROBES
        ]
        print(f"[dump] probing host {host} (substituted for {AP_HOST})\n")

    findings = []
    for method, url, body in probes:
        label = f"{method} {url}"
        if body is not None:
            label += f"  body={json.dumps(body)}"
        status, resp = http(method, url, body=body, timeout=8.0)
        snippet = (resp or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + f"... <truncated, {len(resp)} total>"
        findings.append((status, label, snippet))
        if verbose:
            tag = "OK " if status == 200 else (f"{status:>3}" if status else "ERR")
            print(f"[{tag}] {label}")
            if snippet:
                print(f"       {snippet}")

    # Final summary of which endpoints returned a real body
    print("\n========== SUMMARY ==========")
    print("Endpoints that returned 200 with a body:")
    found_any = False
    for status, label, snippet in findings:
        if status == 200 and snippet:
            print(f"  - {label}")
            found_any = True
    if not found_any:
        print("  (none — only 404/405/timeouts/errors)")


# ---------- portscan (pure Python, no nmap) ----------

# Ports worth checking on a Gecko OS / WGM160P device on the LAN.
DEFAULT_PORTS = [
    22,    # ssh
    23,    # telnet (ZentriOS/Gecko OS command console sometimes here)
    53,    # dns
    80,    # http — the /Generac/api surface we know
    443,   # https
    333,   # Gecko OS / ZentriOS default tcp.server.port
    1883,  # MQTT
    8883,  # MQTT over TLS
    8080,  # alt-http
    8443,  # alt-https
    4321,  # ZentriOS example stream port
    2000,  # common embedded telnet/console
    5000,  # common embedded http/api
    9000,  # common embedded
    502,   # modbus (some generators)
    47808, # bacnet
]


def portscan(host, ports=None, timeout=1.0, grab_banner=True):
    """Pure-Python TCP connect scan. Avoids nmap entirely.

    Reports each open port and, for open ports, tries a tiny banner grab
    (send nothing / a bare HTTP HEAD) so we can fingerprint the service.
    """
    ports = ports or DEFAULT_PORTS
    print(f"[portscan] {host}  ({len(ports)} ports, {timeout}s timeout each)\n")
    open_ports = []
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            result = s.connect_ex((host, port))
        except OSError as e:
            print(f"  {port:>5}  error: {e}")
            s.close()
            continue
        if result == 0:
            banner = ""
            if grab_banner:
                try:
                    s.settimeout(1.5)
                    # For HTTP-ish ports, poke it; otherwise just read.
                    if port in (80, 8080, 5000, 9000):
                        s.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
                    try:
                        data = s.recv(256)
                        banner = data.decode("latin-1", "replace").strip()
                    except (socket.timeout, OSError):
                        banner = "(open, no banner)"
                except OSError:
                    banner = "(open, banner grab failed)"
            print(f"  {port:>5}  OPEN   {banner[:120]!r}")
            open_ports.append((port, banner))
        s.close()

    print("\n========== PORTSCAN SUMMARY ==========")
    if open_ports:
        for port, banner in open_ports:
            print(f"  OPEN {port}  {banner[:100]!r}")
    else:
        print("  No open TCP ports found in the probed set.")
        print("  (Device may only make OUTBOUND cloud connections — no local listener.)")
    return open_ports


# ---------- fuzz-interface (read-only by default) ----------

# Candidate interface values for /Generac/api/getConfig {"interface": <name>}.
# All-lowercase: confirmed-known {system, wlan} get 200; uppercase variants and
# {ethernet, AP, STATION} get {"reason": 19}. So the firmware checks for
# specific lowercase keys. These are guesses for what else might be recognized.
INTERFACE_CANDIDATES = [
    # already-known, included as sanity baseline
    "system", "wlan",
    # things the firmware seems to track but didn't accept literally
    "eth", "ethernet", "ap", "softap", "softAp", "soft_ap", "sta", "station",
    # Gecko OS / ZentriOS standard interface names
    "setup", "setup_web", "wac", "web", "command", "commands", "rest",
    # diagnostic / vendor-mode candidates
    "diag", "diagnostic", "debug", "installer", "dealer", "factory",
    "manufacturing", "production", "service", "test",
    # subsystems / config groupings
    "time", "ntp", "clock", "dns", "dhcp", "ip",
    "cloud", "mqtt", "broker", "iot", "telemetry",
    "tls", "ssl", "certs", "pki", "https",
    "power", "battery", "uptime",
    "gpio", "uart", "spi", "i2c",
    "controller", "panel", "apparatus", "generator", "pnp", "engine", "module",
    "update", "ota", "otafu", "fwupd", "firmware",
    "log", "logs", "journal", "events",
    "subscription", "enrollment", "registration",
    "language", "locale", "timezone",
    # Generac-flavored hunches
    "tether", "mlg", "mobilelink", "standby",
]


def fuzz_interface(verbose=True, host=None, do_writes=False):
    """Probe many candidate interface names against getConfig (and optionally
    setConfig) to discover undocumented interfaces — particularly anything
    that might enable the dormant /command/* surface.
    """
    target_host = host or AP_HOST
    base = f"http://{target_host}/Generac/api/"
    print(f"[fuzz] probing getConfig against {base}\n")

    discovered = []
    for name in INTERFACE_CANDIDATES:
        body = {"interface": name}
        status, resp = http("POST", base + "getConfig", body=body, timeout=6.0)
        snippet = (resp or "").strip()
        snippet_short = (snippet[:200] + "...") if len(snippet) > 200 else snippet

        is_interesting = (
            status == 200
            or (status == 400 and '"reason"' in snippet and "19" not in snippet)
            or (status not in (None, 200, 400, 404))
        )

        if verbose:
            if is_interesting:
                tag = f"** {status} **"
            else:
                tag = f"{status:>3}" if status else "ERR"
            print(f"[{tag}] interface={name!r:<18} -> {snippet_short}")

        if is_interesting:
            discovered.append((name, status, snippet))

    if do_writes:
        print(f"\n[fuzz] --write mode: trying setConfig with each candidate")
        print(f"       (this WILL attempt to change device state; abort with ^C)")
        for name in INTERFACE_CANDIDATES:
            body = {"interface": name}
            status, resp = http("POST", base + "setConfig", body=body, timeout=6.0)
            snippet = (resp or "").strip()
            snippet_short = (snippet[:200] + "...") if len(snippet) > 200 else snippet
            interesting = status not in (None, 400, 404) or (
                status == 400 and "19" not in snippet
            )
            tag = f"** {status} **" if interesting else (f"{status:>3}" if status else "ERR")
            print(f"[{tag}] setConfig interface={name!r:<18} -> {snippet_short}")
            if interesting:
                discovered.append((f"set:{name}", status, snippet))

    print("\n========== FUZZ SUMMARY ==========")
    if not discovered:
        print("Nothing novel — every candidate returned the expected rejection.")
        print("The firmware's interface enum is tight.")
    else:
        print("Interesting responses (status != 19 / != 404):")
        for name, status, snippet in discovered:
            print(f"  - interface={name!r}  status={status}")
            print(f"    {snippet[:300]}")


# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="detect V1 vs V2 firmware")
    sub.add_parser("scan",  help="list Wi-Fi networks the generator sees")

    pd = sub.add_parser("dump", help="hit every safe read-only endpoint")
    pd.add_argument("--host", default=None,
                    help="probe this IP instead of 192.168.51.1 (use after "
                         "provisioning to see what the device exposes on the LAN)")

    pf = sub.add_parser("fuzz-interface",
                        help="try many candidate interface values against "
                             "getConfig to find undocumented endpoints")
    pf.add_argument("--host", default=None,
                    help="probe this IP instead of 192.168.51.1")
    pf.add_argument("--write", action="store_true",
                    help="ALSO attempt setConfig with each candidate "
                         "(may change device state — be sure)")

    pp = sub.add_parser("portscan",
                        help="pure-Python TCP port scan (no nmap needed)")
    pp.add_argument("host", help="IP to scan, e.g. 192.168.1.94")
    pp.add_argument("--ports", default=None,
                    help="comma-separated ports; default is a curated set")
    pp.add_argument("--timeout", type=float, default=1.0,
                    help="per-port connect timeout in seconds")

    pl = sub.add_parser("listen-udp",
                        help="listen for the device's UDP broadcasts and dump "
                             "payloads (offline telemetry discovery)")
    pl.add_argument("--port", type=int, default=55555,
                    help="UDP port to listen on (default 55555)")
    pl.add_argument("--count", type=int, default=10,
                    help="how many packets to capture before stopping")
    pl.add_argument("--from-ip", default=None,
                    help="only show packets from this source IP "
                         "(e.g. 192.168.1.94)")
    pl.add_argument("--save", default=None,
                    help="save raw packets (length-prefixed) to this file")

    pc = sub.add_parser("connect", help="send home Wi-Fi credentials")
    pc.add_argument("ssid")
    pc.add_argument("password")
    pc.add_argument("--force", choices=["v1", "v2"], default=None,
                    help="skip probe and force a firmware variant")
    pc.add_argument("--from-scan", action="store_true",
                    help="scan first and copy ONLY the security string from "
                         "the matching SSID (leaves bssid/channel free so the "
                         "device can roam / follow channel changes)")
    pc.add_argument("--pin-bssid", action="store_true",
                    help="also pin to the BSSID from the scan (prevents "
                         "roaming across mesh / repeaters)")
    pc.add_argument("--pin-channel", action="store_true",
                    help="also pin to the channel from the scan (prevents "
                         "following AP auto-channel changes)")
    pc.add_argument("--bssid", default="00:00:00:00:00:00",
                    help="V2 only — '00:00:00:00:00:00' (default) is the "
                         "Gecko OS 'any AP with this SSID' sentinel")
    pc.add_argument("--channel", type=int, default=0,
                    help="V1/V2 — 0 lets the device scan all channels")
    pc.add_argument("--security", default=None,
                    help="V2: scan-reported string (e.g. 'WPA2-AES', 'OPEN'); "
                         "V1: 'wpa2' or 'open'")
    pc.add_argument("--poll-secs", type=int, default=60,
                    help="V2 only — how long to poll status before bailing")

    args = p.parse_args()

    if args.cmd == "probe":
        v = probe()
        print(f"\nfirmware = {v!r}")
        return

    if args.cmd == "dump":
        dump(host=args.host)
        return

    if args.cmd == "fuzz-interface":
        fuzz_interface(host=args.host, do_writes=args.write)
        return

    if args.cmd == "portscan":
        ports = None
        if args.ports:
            ports = [int(p) for p in args.ports.split(",") if p.strip()]
        portscan(args.host, ports=ports, timeout=args.timeout)
        return

    if args.cmd == "listen-udp":
        listen_udp(port=args.port, count=args.count,
                   save=args.save, from_ip=args.from_ip)
        return

    if args.cmd == "scan":
        v = probe()
        if v == "v2":
            print(json.dumps(v2_scan(), indent=2))
        elif v == "v1":
            s, b = v1_scan()
            print(f"status={s}")
            print(b)
        else:
            sys.exit("could not detect firmware — check you're on MLG SoftAP")
        return

    if args.cmd == "connect":
        v = args.force or probe()
        if v == "v2":
            bssid = args.bssid
            channel = args.channel
            security = args.security
            if args.from_scan:
                print(f"[from-scan] scanning to locate {args.ssid!r} …")
                result = v2_scan()
                if not result or "networks" not in result:
                    sys.exit("scan failed; can't auto-fill")
                match = next(
                    (n for n in result["networks"] if n.get("ssid") == args.ssid),
                    None,
                )
                if match is None:
                    sys.exit(f"SSID {args.ssid!r} not in scan results")
                # Always copy security — it has to match the AP's actual auth.
                security = security or match.get("security")
                # Only copy bssid/channel if user explicitly asked to pin them.
                if args.pin_bssid:
                    bssid = match.get("bssid", "00:00:00:00:00:00")
                if args.pin_channel:
                    channel = channel or match.get("channel", 0)
                print(f"[from-scan] using security={security!r} "
                      f"bssid={bssid!r} channel={channel} "
                      f"(pin_bssid={args.pin_bssid} pin_channel={args.pin_channel})")
            sec = security or "WPA2-AES"
            v2_provision(args.ssid, args.password, security=sec,
                         bssid=bssid, channel=channel,
                         poll_secs=args.poll_secs)
        elif v == "v1":
            sec = args.security or "wpa2"
            v1_provision(args.ssid, args.password,
                         security=sec, channel=args.channel)
        else:
            sys.exit("could not detect firmware — check you're on MLG SoftAP")
        return


if __name__ == "__main__":
    main()
