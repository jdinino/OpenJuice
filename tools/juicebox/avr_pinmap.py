#!/usr/bin/env python3
"""
avr_pinmap.py -- recover an ATmega328P pin map from a firmware image, no toolchain needed.

WHY THIS EXISTS
  eMotorWerks never published a schematic for any JuiceBox PCB, and released source only up to
  revision 8.10. This unit is PCB 8.14+, so its pin assignments are not documented anywhere and
  must be recovered from the firmware itself before OpenEVSE can safely be flashed onto it
  (see docs/juicebox/OpenJuice-FSD.md risk R8 -- a wrong relay or GFI pin on a 40 A circuit is the failure
  mode that matters).

HOW IT WORKS
  No disassembler is required to find pin usage. AVR's bit-level I/O instructions encode both the
  I/O register address and the bit number directly in a single 16-bit opcode:

      SBI   1001 1010 AAAAAbbb    set bit b in I/O register A
      CBI   1001 1000 AAAAAbbb    clear bit
      SBIC  1001 1001 AAAAAbbb    skip if bit clear
      SBIS  1001 1011 AAAAAbbb    skip if bit set

  DDRx / PORTx / PINx all sit in the low I/O space those instructions can reach, so scanning the
  image for them yields, per pin: configured as output (SBI DDRx), driven high/low (SBI/CBI PORTx),
  and read or tested (SBIC/SBIS PINx). That is enough to tell an output (relay, pilot, GFI test,
  latch reset) from an input (GFI sense, buttons).

  Whole-port writes (`OUT DDRx, r`) are also counted, since they indicate bulk configuration the
  bit-level scan would otherwise miss.

*** KNOWN LIMITATION -- READ BEFORE TRUSTING ANY OUTPUT ***

  This is a LINEAR scan: it walks the image two bytes at a time and cannot distinguish code from
  data. AVR flash interleaves both (PROGMEM strings, jump tables, constants), and any 16-bit value
  can coincidentally match an opcode. The tool therefore produces HINTS, not facts.

  Calibration against firmware_8.9.hex (whose source IS published) demonstrated this concretely:
  the scan reported SBI EIMSK for all eight bits, exactly once each -- but the ATmega328P only has
  INT0 and INT1, so bits 2-7 cannot exist. Eight consecutive matches is a lookup table being read
  as instructions.

  It also showed the second limitation: the stock firmware drives most pins through Arduino's
  digitalWrite()/pinMode() with a variable pin number, which compiles to indirect register access,
  not SBI/CBI. Those pins are invisible here. The 8.9 calibration recovered the Timer1/pilot pins
  and the aggregate peripheral configuration, but NOT the relay, GFI sense, GFI test or latch reset.

  USE THIS TO: narrow the search, confirm which peripherals are configured at all, and corroborate
  a hypothesis you already hold.
  DO NOT USE IT TO: establish a safety-critical pin assignment. That requires either a real
  disassembler following control flow from the reset vector (Ghidra with the AVR loader), or
  electrical verification on the bench -- and for a 40 A circuit, preferably both.

Usage:
  python avr_pinmap.py firmware_8.9.hex
  python avr_pinmap.py stock_flash.hex --min-hits 2
  python avr_pinmap.py dump.bin --raw
"""
import argparse
import collections
import sys

# ATmega328P low-I/O addresses as seen by SBI/CBI/SBIC/SBIS.
IO = {
    0x03: ("PINB", "B"), 0x04: ("DDRB", "B"), 0x05: ("PORTB", "B"),
    0x06: ("PINC", "C"), 0x07: ("DDRC", "C"), 0x08: ("PORTC", "C"),
    0x09: ("PIND", "D"), 0x0A: ("DDRD", "D"), 0x0B: ("PORTD", "D"),
}

# SBI/CBI-reachable control registers whose BITS name a specific pin or function.
# EIMSK is the important one: bit 0 = INT0 (PD2/D2), bit 1 = INT1 (PD3/D3), so it
# identifies which pin carries the GFI interrupt without any disassembly.
CTRL = {
    0x1C: ("EIFR",  {0: "INTF0 (D2)", 1: "INTF1 (D3)"}),
    0x1D: ("EIMSK", {0: "INT0 enable (D2)", 1: "INT1 enable (D3)"}),
}

# Extended I/O registers, only reachable via STS <addr>,Rr -- scanned separately.
STS_REGS = {
    0x69: "EICRA (INT0/INT1 edge select)",
    0x6F: "TIMSK1 (Timer1 interrupts)",
    0x80: "TCCR1A (Timer1 mode, COM1A/COM1B output enable)",
    0x81: "TCCR1B (Timer1 clock/prescaler)",
    0x88: "OCR1AL (pilot duty, OC1A/D9)",
    0x89: "OCR1AH",
    0x8A: "OCR1BL (pilot duty, OC1B/D10)",
    0x8B: "OCR1BH",
    0x7A: "ADCSRA (ADC enable/start)",
    0x7C: "ADMUX  (ADC channel select)",
}

# Port/bit -> Arduino pin label on the ATmega328P.
def arduino_name(port, bit):
    if port == "D":
        return "D%d" % bit
    if port == "B":
        return "D%d" % (8 + bit) if bit <= 5 else "PB%d" % bit
    if port == "C":
        return "A%d" % bit
    return "P%s%d" % (port, bit)


def parse_intel_hex(text):
    """Return a flat bytearray of program memory from Intel HEX."""
    mem = bytearray()
    base = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count, addr_hi, addr_lo, rectype = raw[0], raw[1], raw[2], raw[3]
        addr = (addr_hi << 8) | addr_lo
        data = raw[4:4 + count]
        if rectype == 0x00:
            off = base + addr
            if off + len(data) > len(mem):
                mem.extend(b"\xff" * (off + len(data) - len(mem)))
            mem[off:off + len(data)] = data
        elif rectype == 0x02:                       # extended segment
            base = ((data[0] << 8) | data[1]) * 16
        elif rectype == 0x04:                       # extended linear
            base = ((data[0] << 8) | data[1]) << 16
        elif rectype == 0x01:                       # EOF
            break
    return mem


def scan(mem):
    """Walk 16-bit little-endian words, tallying bit-level I/O ops and whole-port OUTs."""
    hits = collections.defaultdict(lambda: collections.Counter())
    port_writes = collections.Counter()
    ctrl_hits = collections.Counter()
    sts_hits = collections.Counter()
    i = 0
    while i < len(mem) - 1:
        w = mem[i] | (mem[i + 1] << 8)
        top = w >> 8
        if top in (0x98, 0x99, 0x9A, 0x9B):         # CBI / SBIC / SBI / SBIS
            addr = (w >> 3) & 0x1F
            bit = w & 0x07
            op = {0x9A: "SBI", 0x98: "CBI", 0x99: "SBIC", 0x9B: "SBIS"}[top]
            if addr in IO:
                reg, port = IO[addr]
                hits[(port, bit)]["%s %s" % (op, reg)] += 1
            elif addr in CTRL:
                reg, bits = CTRL[addr]
                ctrl_hits["%-5s %-5s bit%d  %s" % (op, reg, bit, bits.get(bit, ""))] += 1
        elif (w >> 11) == 0b10111:                  # OUT A, Rr
            addr = ((w >> 5) & 0x30) | (w & 0x0F)
            if addr in IO:
                port_writes[IO[addr][0]] += 1
        elif (w & 0xFE0F) == 0x9200 and i + 3 < len(mem):   # STS <addr>, Rr
            target = mem[i + 2] | (mem[i + 3] << 8)
            if target in STS_REGS:
                sts_hits["0x%02X %s" % (target, STS_REGS[target])] += 1
            i += 2                                   # STS is a 2-word instruction
        i += 2
    return hits, port_writes, ctrl_hits, sts_hits


def classify(counter):
    """Summarise what the firmware does with one pin."""
    out_cfg = sum(v for k, v in counter.items() if k.startswith("SBI DDR"))
    in_cfg = sum(v for k, v in counter.items() if k.startswith("CBI DDR"))
    drive = sum(v for k, v in counter.items() if k.endswith(("PORTB", "PORTC", "PORTD"))
                and k.startswith(("SBI", "CBI")))
    read = sum(v for k, v in counter.items() if k.startswith(("SBIC", "SBIS")))
    tags = []
    if out_cfg:
        tags.append("OUTPUT")
    if in_cfg and not out_cfg:
        tags.append("input")
    if drive:
        tags.append("driven x%d" % drive)
    if read:
        tags.append("read/tested x%d" % read)
    return ", ".join(tags) or "referenced"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="Intel HEX (default) or raw binary with --raw")
    ap.add_argument("--raw", action="store_true", help="treat input as a raw flash binary")
    ap.add_argument("--min-hits", type=int, default=1,
                    help="hide pins with fewer than N total references (default 1)")
    args = ap.parse_args()

    if args.raw:
        mem = bytearray(open(args.image, "rb").read())
    else:
        mem = parse_intel_hex(open(args.image, "r", errors="replace").read())

    print("image        : %s" % args.image)
    print("program bytes: %d  (%.1f%% of 32 KB)" % (len(mem), 100.0 * len(mem) / 32768))
    hits, port_writes, ctrl_hits, sts_hits = scan(mem)
    print("pins touched : %d" % len(hits))
    if port_writes:
        print("whole-port writes (OUT): %s"
              % ", ".join("%s x%d" % (k, v) for k, v in sorted(port_writes.items())))
    print()
    print("%-6s %-6s %-9s %s" % ("PIN", "PORT", "REFS", "USAGE"))
    print("-" * 74)
    for (port, bit), counter in sorted(hits.items(),
                                       key=lambda kv: (kv[0][0], kv[0][1])):
        total = sum(counter.values())
        if total < args.min_hits:
            continue
        detail = " ".join("%s:%d" % (k.split()[0] + "/" + k.split()[1], v)
                          for k, v in sorted(counter.items()))
        print("%-6s P%s%-4d %-9d %s" % (arduino_name(port, bit), port, bit, total,
                                        classify(counter)))
        print("%-6s %-6s %-9s   %s" % ("", "", "", detail))
    if ctrl_hits:
        print("External interrupt config (candidate GFI sense pin):")
        for k, v in sorted(ctrl_hits.items()):
            print("   %s   x%d" % (k, v))
        # A control register showing every bit exactly once is a lookup table read as code,
        # not real instructions -- ATmega328P EIMSK has only bits 0 and 1.
        for reg in ("EIMSK", "EIFR"):
            n = sum(1 for k in ctrl_hits if reg in k)
            if n >= 8 and all(v == 1 for k, v in ctrl_hits.items() if reg in k):
                print("   !! %s shows all 8 bits exactly once -- that is a DATA TABLE misread as"
                      % reg)
                print("      code, not interrupt setup. Only bits 0/1 exist. Disregard these.")
        print()
    if sts_hits:
        print("Timer / ADC / interrupt registers written (STS):")
        for k, v in sorted(sts_hits.items()):
            print("   %-46s x%d" % (k, v))
        print()
    print("Reminder: this shows how the firmware USES each pin, not what it is wired to.")
    print("Confirm electrically before flashing -- see docs/juicebox/OpenJuice-FSD.md R8.")


if __name__ == "__main__":
    main()
