#!/usr/bin/env python3
"""Re-test the load-bearing claims: (A) no local deep-telemetry path on the device,
(B) telemetry requires the cloud. Look hard for a MISSED local path — BLE, a local
device status API, or telemetry served off 192.168.51.1."""
import zipfile, re, sys

APK3 = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_3.16.0_APKPure.apk"
z = zipfile.ZipFile(APK3)

# --- (0) Network Security Config: what cleartext is allowed, and to whom ---
print("=== Network Security Config (res/8G.xml) ===")
nsc = z.read("res/8G.xml")
# binary AXML; pull the readable string-pool bits
for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}|[\x20-\x7e]{4,}", nsc):
    s = m.group().decode("utf-16-le" if b"\x00" in m.group() else "latin1", "replace")
    if any(k in s.lower() for k in ("192.168", "cleartext", "domain", "http", "config", "base", "trust")):
        print("   ", s)

bundle = z.read("assets/index.android.bundle")
U8 = re.compile(rb"[\x20-\x7e]{4,}")
strings = [m.group().decode("latin1") for m in U8.finditer(bundle)]
blob = "\n".join(strings)

def near(term, window=60, cap=12):
    """print unique substrings containing term with context, from the string list."""
    hits, seen = [], set()
    for s in strings:
        if term.lower() in s.lower():
            frag = s.strip()
            key = frag[:100]
            if key not in seen:
                seen.add(key); hits.append(frag[:140])
    print(f"\n--- '{term}' ({len(hits)}) ---")
    for h in hits[:cap]:
        print("   ", h)

print("\n=== (A) any LOCAL device data path? ===")
for t in ["192.168.51.1", "192.168.", "localhost", "127.0.0.1",
          "getConfig", "gainspan", "local", "offline", "directConnect", "lan"]:
    near(t)

print("\n=== BLE / Bluetooth path (could be a non-cloud telemetry source) ===")
for t in ["bluetooth", "gatt", "characteristic", "BleManager", "peripheral", "0000", "serviceUUID"]:
    near(t)

print("\n=== where does telemetry come from? (cloud markers vs local) ===")
for t in ["Apparatus/details", "batteryVoltage", "fuelLevel", "runHours",
          "getTelemetry", "signalStrength", "apparatusStatus"]:
    near(t)

print("\n=== 'registered' / enrollment gating ===")
for t in ["registered", "enroll", "activation", "isRegistered", "notEnrolled"]:
    near(t)
