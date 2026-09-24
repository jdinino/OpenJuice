#!/usr/bin/env python3
"""Is there a LOCAL Bluetooth telemetry path that bypasses the cloud? Inspect the
readable Xamarin BLE service in the 2.x assemblies: what device it targets, what
characteristics it reads, and whether it pulls generator telemetry."""
import zipfile, struct, re

APK = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
z = zipfile.ZipFile(APK)
blob = z.read("assemblies/assemblies.blob")
manifest = z.read("assemblies/assemblies.manifest").decode("latin1", "replace")
n2i = {}
for ln in manifest.splitlines():
    p = ln.split()
    if len(p) >= 5 and p[-2].isdigit():
        n2i[p[-1]] = int(p[-2])

def lz4d(src):
    out = bytearray(); i = 0; n = len(src)
    while i < n:
        tok = src[i]; i += 1
        ll = tok >> 4
        if ll == 15:
            while True:
                b = src[i]; i += 1; ll += b
                if b != 255: break
        out += src[i:i + ll]; i += ll
        if i >= n: break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = (tok & 15) + 4
        if (tok & 15) == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        st = len(out) - off
        for j in range(ml):
            out.append(out[st + j])
    return bytes(out)

def asm(name):
    o = 20 + n2i[name] * 24
    do, ds = struct.unpack("<6I", blob[o:o + 24])[:2]
    c = blob[do:do + ds]
    return lz4d(c[12:]) if c[:4] == b"XALZ" else c

def strs(d):
    s = set()
    for m in re.finditer(rb"[\x20-\x7e]{3,}", d): s.add(m.group().decode("latin1"))
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){3,}", d): s.add(m.group().decode("utf-16-le"))
    return s

alls = set()
for nm in [k for k in n2i if k.startswith("Generac")]:
    alls |= strs(asm(nm))

# BLE service/type names and what they touch
ble = sorted({s for s in alls if re.search(r"(Bluetooth|\bBle\b|Gatt|Characteristic|Peripheral|Advertis|RSSI|ScanResult)", s, re.I)
              and "<" not in s and len(s) < 70})
print("=== BLE-related type/method names ===")
for s in ble:
    print("  ", s)

# GATT UUIDs (128-bit or 16-bit)
uuids = sorted({s for s in alls if re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}", s)})
print("\n=== UUID-looking strings (GATT services/characteristics?) ===")
for s in uuids[:40]:
    print("  ", s)

# what device does BLE target? name filters / product association
print("\n=== BLE device targeting / product context ===")
for s in sorted(alls):
    if re.search(r"(CO\b|Carbon|Portable|Detector|PWRcell|PWRview|setup|provision|onboarding|ScanForDevices|DeviceNameFilter|namePrefix|MLG|Tether)", s) \
       and re.search(r"(ble|bluetooth|device|scan|characteristic|connect)", s, re.I) and len(s) < 80 and "<" not in s:
        print("  ", s)

# does BLE read TELEMETRY (battery/fuel/runhours)?
print("\n=== BLE + telemetry co-occurrence (any characteristic that reads gen data)? ===")
for s in sorted(alls):
    if re.search(r"(battery|fuel|runhour|voltage|telemetry|status)", s, re.I) \
       and re.search(r"(ble|bluetooth|gatt|characteristic|read)", s, re.I) and len(s) < 90 and "<" not in s:
        print("  ", s)
print("   (empty above = no BLE path to generator telemetry)")
