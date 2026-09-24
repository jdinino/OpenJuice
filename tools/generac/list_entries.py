#!/usr/bin/env python3
"""Locate the Xamarin .NET assemblies inside the 2.x APK and check how they're
stored (plain PE 'MZ' vs Xamarin LZ4 'XALZ' vs a single assemblies.blob)."""
import zipfile, sys, os

APK = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
z = zipfile.ZipFile(APK)
infos = z.infolist()

print("=== entries related to assemblies / native libs ===")
buckets = {"assemblies": [], "dll": [], "blob": [], "lib": [], "mono": []}
for i in infos:
    n = i.filename
    low = n.lower()
    if "assembl" in low: buckets["assemblies"].append(i)
    elif low.endswith(".dll") or ".dll" in low: buckets["dll"].append(i)
    elif low.endswith(".blob"): buckets["blob"].append(i)
    elif low.endswith("libmonodroid.so") or "mono" in low: buckets["mono"].append(i)
    elif low.startswith("lib/"): buckets["lib"].append(i)

for k, items in buckets.items():
    print(f"\n[{k}] {len(items)} entries")
    for i in items[:40]:
        print(f"   {i.file_size:>10,}  {i.filename}")

# find a Generac assembly and peek at its header (after zip decompression)
def peek(entry):
    b = z.read(entry)
    head = b[:16]
    kind = ("PE/.dll(MZ)" if head[:2] == b"MZ"
            else "Xamarin-LZ4(XALZ)" if head[:4] == b"XALZ"
            else "BundledAssemblies(XABA)" if head[:4] == b"XABA"
            else "assembly-store(blob)" if head[:3] == b"XAB" or head[:4] == b"BUND"
            else "?")
    print(f"   {entry.filename}: {len(b):,}B  first16={head.hex()}  -> {kind}")

print("\n=== header peek at Generac / candidate assemblies ===")
cands = [i for i in infos if "generac" in i.filename.lower()
         or "apiclient" in i.filename.lower()
         or i.filename.lower().endswith("apparatus.dll")
         or "assemblies.blob" in i.filename.lower()]
if not cands:
    # maybe assemblies live under assemblies/ generically
    cands = [i for i in infos if i.filename.lower().startswith("assemblies/")][:6]
for c in cands[:8]:
    try:
        peek(c)
    except Exception as e:
        print(f"   {c.filename}: peek error {e}")

print(f"\ntotal entries in apk: {len(infos)}")
