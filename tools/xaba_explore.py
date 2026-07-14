#!/usr/bin/env python3
"""Explore the Xamarin XABA assembly-store to confirm its layout before extracting."""
import zipfile, struct, sys

APK = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
z = zipfile.ZipFile(APK)
manifest = z.read("assemblies/assemblies.manifest").decode("latin1", "replace")
blob = z.read("assemblies/assemblies.blob")

print(f"blob size: {len(blob):,}")
print("first 64 bytes:", blob[:64].hex())

# header: magic, version, local_count, global_count, store_id  (5 x uint32)
magic, version, local_cnt, global_cnt, store_id = struct.unpack("<5I", blob[:20])
print(f"magic={magic:#x} ('{blob[:4].decode('latin1')}')  version={version}  "
      f"local={local_cnt}  global={global_cnt}  store_id={store_id}")

# descriptors: 6 x uint32 each (data_off, data_size, debug_off, debug_size, cfg_off, cfg_size)
desc_base = 20
print("\nfirst 6 descriptors (data_offset, data_size):")
for i in range(min(6, local_cnt)):
    off = desc_base + i * 24
    do, ds, dbo, dbs, co, cs = struct.unpack("<6I", blob[off:off + 24])
    inrange = "ok" if 0 < do < len(blob) and do + ds <= len(blob) else "OOR"
    magic4 = blob[do:do + 4] if inrange == "ok" else b""
    print(f"  [{i}] data_off={do:,} size={ds:,} [{inrange}] head={magic4.hex()} "
          f"({'XALZ' if magic4 == b'XALZ' else 'MZ/PE' if magic4[:2]==b'MZ' else '?'})")

print("\n--- manifest header + Generac / Api / Apparatus rows ---")
for ln in manifest.splitlines():
    low = ln.lower()
    if ("hash" in low and "idx" in low) or "generac" in low or "apiclient" in low \
       or "apparatus" in low or ln.strip().endswith("Mobile") or ".Common" in ln:
        print("  " + ln.rstrip())
