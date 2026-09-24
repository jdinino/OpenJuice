#!/usr/bin/env python3
"""Pull interesting strings (URLs, IPs, API paths, provisioning/controller terms)
out of a NATIVE Android APK: scans classes*.dex, resources.arsc, assets/*, and
res/raw/*. Reveals what the pre-React-Native Mobile Link build talks to."""
import zipfile, sys, os, re

APK = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"

PRINTABLE = re.compile(rb"[\x20-\x7e]{5,}")
URL   = re.compile(r"https?://[^\s\"'<>]{3,}")
IP    = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
APIPATH = re.compile(r"/[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z0-9_{}.]+)+")
KEYWORDS = ["gainspan", "zentri", "gecko", "mobilelink", "azure", "iothub",
            "b2clogin", "provision", "softap", "Nexus", "Evolution",
            "Diagnostic", "PZ200", "RCM", "HPanel", "H-panel", "exercise",
            "apparatus", "telemetry", "wifi_enable", "getConfig", "setConfig",
            "passphrase", "SSID", " ssid", "webservice", "generac.com"]


def main():
    print(f"=== {os.path.basename(APK)} ===")
    z = zipfile.ZipFile(APK)
    names = z.namelist()
    targets = [n for n in names if n.endswith(".dex")
               or n == "resources.arsc"
               or n.startswith("assets/")
               or n.startswith("res/raw/")
               or n.startswith("assemblies/")          # Xamarin .NET assembly store
               or n.endswith("libxamarin-app.so")]     # Xamarin typemap
    print(f"scanning {len(targets)} entries: "
          f"{sum(1 for n in targets if n.endswith('.dex'))} dex, "
          f"{'resources.arsc' if 'resources.arsc' in targets else 'no arsc'}, "
          f"{sum(1 for n in targets if n.startswith('assets/'))} assets, "
          f"{sum(1 for n in targets if n.startswith('res/raw/'))} raw")

    strings = set()
    for n in targets:
        try:
            blob = z.read(n)
        except Exception:
            continue
        for m in PRINTABLE.finditer(blob):
            s = m.group().decode("latin1")
            strings.add(s)

    urls, ips, apis, kw = set(), set(), set(), {}
    for s in strings:
        for u in URL.findall(s):
            urls.add(u.rstrip('.,)"\''))
        for ip in IP.findall(s):
            if ip.startswith(("192.168.", "10.", "172.")) or ip.count('.') == 3:
                ips.add(ip)
        for a in APIPATH.findall(s):
            if any(t in a.lower() for t in ("api", "gainspan", "generac",
                                            "apparatus", "config", "provision")):
                apis.add(a)
        low = s.lower()
        for k in KEYWORDS:
            if k.lower() in low:
                kw.setdefault(k, set()).add(s.strip()[:120])

    def dump(title, items, cap=60):
        print(f"\n--- {title} ({len(items)}) ---")
        for x in sorted(items)[:cap]:
            print(f"  {x}")

    dump("URLs", urls)
    dump("IP addresses", {ip for ip in ips if ip.startswith("192.168.")} |
                          {ip for ip in ips if ip.startswith(("10.", "172."))})
    dump("API-ish paths", apis)

    print("\n--- keyword context (sample strings containing each) ---")
    for k in KEYWORDS:
        if k in kw:
            samples = sorted(kw[k])[:4]
            print(f"  [{k}] ({len(kw[k])})")
            for s in samples:
                print(f"       {s}")


if __name__ == "__main__":
    main()
