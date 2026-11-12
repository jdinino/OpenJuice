#!/usr/bin/env python3
"""charge_notifier.py -- play a Windows sound when the JuiceBox finishes charging.

Passive companion to juicebox_helper.py. It watches the helper's status.json for
the charging-complete edge -- JuiceNet state S2 ("charging") -> S1 ("plugged in,
idle"), i.e. the car stopped drawing current but is still plugged in -- and plays
a sound. It only READS status.json (and telemetry.log for replay); it never binds
a port, never contacts the module, and never changes anything.

Run it in your own terminal (foreground). Because the helper runs as a session-0
scheduled task it cannot make sound on your desktop -- this script does, by running
in your interactive session.

A real charge is told apart from a brief "charging" blip (handshake / pilot test /
battery-maintenance sip that reports S2 for a few seconds and ~0 Wh) by requiring
the session to have delivered at least --min-kwh (default 0.1) of energy, measured
from the lifetime-energy (L) delta across the S2 run. Without this, ~60% of edges
in real data are sub-second zero-energy blips.

Usage:
  python charge_notifier.py watch                 # poll status.json, chime on completion
  python charge_notifier.py test-sound            # play the sound once and exit
  python charge_notifier.py replay telemetry.log  # scan a log, print detected completions

Options (watch):
  --sound PATH      wav to play           (default Windows' Print complete sound)
  --repeat N        play it N times        (default 1)
  --poll SEC        status.json poll gap   (default 5)
  --confirm SEC     how long S1 must hold  (default 30)
  --stale SEC       telemetry older than this -> state unknown (default 60)
  --min-kwh K       ignore sessions that delivered less than this (default 0.1)
  --data-dir DIR    OpenJuice data dir     (default %LOCALAPPDATA%\\OpenJuice)

Only a direct charging->idle (S2->S1) transition chimes; unplug (S2->S0) and
error (S2->S5) stay silent. Completion is undetectable while the module is on the
vendor cloud / the helper watchdog is blocked / the PC is asleep -- no frames
arrive in those windows.
"""
import argparse
import datetime
import json
import os
import sys
import time

DEFAULT_SOUND = r"C:\Windows\Media\Windows Print complete.wav"   # as the desktop monitor
STATE_NAMES = {"0": "unplugged", "1": "plugged in", "2": "charging", "5": "error"}


def default_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "OpenJuice")


def _ensure_local_imports():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def amps_of(fields):
    a = fields.get("A")
    try:
        return float(a) * 0.1 if a is not None else None
    except (ValueError, TypeError):
        return None


def read_status(path):
    """Return the parsed status.json dict, or None (missing / mid-write / unreadable)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        # ValueError covers a partial/torn write (JSONDecodeError); just retry next tick.
        return None


def play_sound(path, repeat=1):
    """Play a wav synchronously, repeat times. Falls back to a system beep."""
    try:
        import winsound
    except ImportError:
        for _ in range(max(1, repeat)):
            sys.stdout.write("\a")
            sys.stdout.flush()
        return
    use_file = bool(path) and os.path.isfile(path)
    for _ in range(max(1, repeat)):
        try:
            if use_file:
                winsound.PlaySound(path, winsound.SND_FILENAME)
            else:
                winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            try:
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass


class CompletionDetector:
    """Fires once per real charging->idle (S2 -> S1) edge.

    An edge counts only when: a fresh S2 was seen (armed), the following S1 persists
    >= confirm_s, and the session delivered >= min_wh (lifetime-L delta from the first
    S2 to the edge). Time is driven by the frame timestamps passed to observe(), so the
    identical logic runs live (status.json telemetry.last) and in replay (telemetry.log).
    A gap longer than gap_s between consecutive observations is a discontinuity and
    disarms the machine, so a charge is never "completed" across a standby / cloud outage
    we never actually watched through.

    on_complete(edge_time, wh) is called with the S2->S1 edge time and the session Wh
    (or None if L was unavailable).
    """

    def __init__(self, confirm_s, gap_s, min_wh, on_complete):
        self.confirm = confirm_s
        self.gap = gap_s
        self.min_wh = min_wh
        self.on_complete = on_complete
        self.armed = False        # saw a fresh S2 since the last fire
        self.s1_since = None      # frame time S1 began (after S2)
        self.fired = False        # already resolved this S1 run
        self.last_obs = None      # time of the previous observation
        self.arm_L = None         # lifetime L at the first S2 of this run
        self.last_L = None        # most recent lifetime L seen

    @staticmethod
    def _lifetime(fields):
        v = fields.get("L")
        try:
            return int(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    def observe(self, when, S, fields):
        if S is None:
            return
        # Discontinuity: too long since the last frame -> can't trust continuity.
        if self.last_obs is not None and (when - self.last_obs).total_seconds() > self.gap:
            self.armed = False
            self.s1_since = None
            self.fired = False
            self.arm_L = None
        self.last_obs = when
        L = self._lifetime(fields)

        if S == "2":                      # charging -> arm (remember L at run start)
            if not self.armed:
                self.arm_L = L if L is not None else self.last_L
            self.armed = True
            self.s1_since = None
            self.fired = False
        elif S == "1":                    # plugged-idle
            if self.armed and not self.fired:
                if self.s1_since is None:
                    self.s1_since = when
                elif (when - self.s1_since).total_seconds() >= self.confirm:
                    self.fired = True
                    self.armed = False
                    wh = None
                    if self.last_L is not None and self.arm_L is not None:
                        wh = self.last_L - self.arm_L
                    if wh is None or wh >= self.min_wh:
                        self.on_complete(self.s1_since, wh)
                    # else: real transition but sub-threshold blip -> suppressed
            # if not armed we started up already idle -> never fire
        else:                             # S0 unplugged / S5 error -> not a completion
            self.armed = False
            self.s1_since = None
            self.fired = False
            self.arm_L = None

        if L is not None:
            self.last_L = L


def _kwh_suffix(wh):
    return ("  session %.2f kWh" % (wh / 1000.0)) if wh is not None else ""


def cmd_test_sound(args):
    where = args.sound if os.path.isfile(args.sound) else "(file missing -> system beep)"
    print("playing: %s" % where)
    play_sound(args.sound, args.repeat)
    return 0


def cmd_watch(args):
    status_path = os.path.join(args.data_dir, "status.json")
    min_wh = args.min_kwh * 1000.0
    print("charge-notifier: watching %s" % status_path)
    print("  sound=%s  poll=%ds  confirm=%ds  stale=%ds  min=%.2f kWh  (Ctrl-C to stop)"
          % (args.sound, args.poll, args.confirm, args.stale, args.min_kwh))

    def on_complete(when, wh):
        print("[%s] *** CHARGE COMPLETE ***%s -- playing sound"
              % (when.strftime("%Y-%m-%d %H:%M:%S"), _kwh_suffix(wh)))
        play_sound(args.sound, args.repeat)

    det = CompletionDetector(args.confirm, args.stale, min_wh, on_complete)
    last_label = None
    while True:
        st = read_status(status_path)
        now = datetime.datetime.now()
        if st is not None:
            tel = st.get("telemetry") or {}
            fields = tel.get("fields") or {}
            S = fields.get("S")
            last_dt = parse_iso(tel.get("last"))
            fresh = last_dt is not None and (now - last_dt).total_seconds() <= args.stale
            if fresh and S is not None:
                det.observe(last_dt, S, fields)
                label = STATE_NAMES.get(S, "S" + str(S))
                if label != last_label:
                    amps = amps_of(fields)
                    extra = ("  %.1f A" % amps) if amps is not None else ""
                    print("[%s] %s%s" % (now.strftime("%H:%M:%S"), label, extra))
                    last_label = label
            else:
                if last_label != "(stale)":
                    age = "%ds old" % int((now - last_dt).total_seconds()) if last_dt else "no telemetry yet"
                    print("[%s] state unknown -- telemetry %s" % (now.strftime("%H:%M:%S"), age))
                    last_label = "(stale)"
        time.sleep(args.poll)


def cmd_replay(args):
    _ensure_local_imports()
    try:
        from juicebox_collector import parse
    except ImportError as e:
        print("cannot import juicebox_collector.parse: %s" % e, file=sys.stderr)
        return 2

    min_wh = args.min_kwh * 1000.0
    completions = []
    det = CompletionDetector(
        args.confirm, args.stale, min_wh,
        lambda when, wh: completions.append((when, wh)),
    )
    frames = 0
    with open(args.file, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            when = parse_iso(parts[0])
            if when is None:
                continue
            r = parse(parts[2])
            if not r:
                continue
            S = r[2].get("S")
            if S is None:
                continue
            det.observe(when, S, r[2])
            frames += 1

    print("scanned %d telemetry frame(s); %d charge completion(s) >= %.2f kWh:"
          % (frames, len(completions), args.min_kwh))
    for when, wh in completions:
        print("  %s%s" % (when.strftime("%Y-%m-%d %H:%M:%S"), _kwh_suffix(wh)))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="charge_notifier.py",
        description="Play a Windows sound when the JuiceBox finishes charging (S2 -> S1).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="poll status.json and chime on each completion")
    w.add_argument("--data-dir", default=default_data_dir())
    w.add_argument("--sound", default=DEFAULT_SOUND)
    w.add_argument("--repeat", type=int, default=1)
    w.add_argument("--poll", type=float, default=5.0)
    w.add_argument("--confirm", type=float, default=30.0)
    w.add_argument("--stale", type=float, default=60.0)
    w.add_argument("--min-kwh", type=float, default=0.1)
    w.set_defaults(func=cmd_watch)

    t = sub.add_parser("test-sound", help="play the sound once and exit")
    t.add_argument("--sound", default=DEFAULT_SOUND)
    t.add_argument("--repeat", type=int, default=1)
    t.set_defaults(func=cmd_test_sound)

    r = sub.add_parser("replay", help="scan a telemetry.log and print detected completions")
    r.add_argument("file")
    r.add_argument("--confirm", type=float, default=30.0)
    r.add_argument("--stale", type=float, default=60.0)
    r.add_argument("--min-kwh", type=float, default=0.1)
    r.set_defaults(func=cmd_replay)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
