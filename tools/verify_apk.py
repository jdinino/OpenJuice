#!/usr/bin/env python3
"""Verify the freshly-downloaded Mobile Link APK matches the build we analyzed
before, by cracking it open (it's a zip) and checking the fingerprints we
documented: package/version, the Hermes bundle + its endpoint strings, and the
network-security-config cleartext rule for 192.168.51.1."""
import zipfile, hashlib, sys, os

APK = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_3.16.0_APKPure.apk"
ORIG_SIZE = 142712707  # bytes, from the originally-analyzed file

def find_bytes(blob, needle):
    """Search for an ASCII needle as UTF-8 and as UTF-16LE."""
    u8 = needle.encode("utf-8")
    u16 = needle.encode("utf-16-le")
    return (u8 in blob), (u16 in blob)

print(f"file: {os.path.basename(APK)}")
size = os.path.getsize(APK)
print(f"size: {size:,} bytes   (original analyzed: {ORIG_SIZE:,})   "
      f"{'MATCH' if size == ORIG_SIZE else 'DIFFERENT'}")

# SHA-256 (streamed)
h = hashlib.sha256()
with open(APK, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(f"sha256: {h.hexdigest()}")

print("\n--- zip integrity ---")
try:
    z = zipfile.ZipFile(APK)
    bad = z.testzip()
    names = z.namelist()
    print(f"valid zip: yes   entries: {len(names)}   first-bad: {bad}")
except Exception as e:
    print(f"NOT a valid zip/apk: {e}")
    sys.exit(1)

# --- AndroidManifest: package + version ---
print("\n--- AndroidManifest.xml (package / version) ---")
try:
    mani = z.read("AndroidManifest.xml")
    for s in ("com.generac.standbystatus", "3.16.0"):
        u8, u16 = find_bytes(mani, s)
        print(f"  {'FOUND' if (u8 or u16) else 'missing':7s}  {s!r}  (utf8={u8} utf16={u16})")
except KeyError:
    print("  AndroidManifest.xml not found")

# --- Hermes bundle + endpoint strings ---
print("\n--- Hermes bundle ---")
bundles = [n for n in names if n.endswith("index.android.bundle")] or \
          [n for n in names if n.endswith(".bundle")]
if not bundles:
    print("  no *.bundle entry found")
else:
    bn = bundles[0]
    data = z.read(bn)
    print(f"  entry: {bn}   size: {len(data):,} bytes")
    # Hermes bytecode magic = 0x1F1903C103BC1FC6 (LE on disk: c6 1f bc 03 c1 03 19 1f)
    print(f"  first 8 bytes: {data[:8].hex()}  "
          f"({'Hermes bytecode' if data[:8] == bytes.fromhex('c61fbc03c103191f') else 'other'})")
    markers = [
        "192.168.51.1",
        "/Generac/api/getConfig",
        "initializeSystemConfig",
        "wifi_enable",
        "app.mobilelinkgen.com",
        "/Apparatus/details/",
        "/Apparatus/enrollment/validate/serialNumber/",
        "generacconnectivity",
        "B2C_1A_MobileLink_SignIn",
    ]
    for m in markers:
        u8, _ = find_bytes(data, m)
        print(f"  {'FOUND' if u8 else 'MISSING':7s}  {m}")

# --- network security config: cleartext to 192.168.51.1 ---
print("\n--- network security config (cleartext -> 192.168.51.1) ---")
xmls = [n for n in names if n.startswith("res/") and n.endswith(".xml")]
hits = []
for n in xmls:
    try:
        b = z.read(n)
    except Exception:
        continue
    u8, u16 = find_bytes(b, "192.168.51.1")
    if u8 or u16:
        hits.append(n)
print(f"  res/*.xml scanned: {len(xmls)}   files containing 192.168.51.1: {hits or 'NONE'}")

print("\n=== verdict ===")
same_size = size == ORIG_SIZE
print("byte-identical size:", same_size)
print("If size matches AND the bundle markers + 192.168.51.1 rule are present,")
print("this is the same 3.16.0 build we analyzed and the hash above is authoritative.")
