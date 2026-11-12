#!/usr/bin/env python3
"""juicebox_helper.py -- keep a JuiceBox Gen 1 under local control, unattended.

Replaces the manual interim procedure in docs/STATUS.md section 4 with one long-running
process. install_helper.ps1 registers it as a Windows scheduled task that starts at boot,
runs whether or not anyone is logged on, and is restarted if it dies. This is the fix for
issue #1: the charger must never sit pointed at a resolver that is not running, and a hung
WiFi module has to be noticed and recovered without a person watching.

One process runs four parts:
  resolver   UDP 53. Answers the JuiceNet hostnames with this PC's address, for the charger only.
  listener   UDP 8042. Receives telemetry, logs it, and corrects the current limit if it drifts.
  beacon     UDP 55555. The module's discovery broadcast: its current address and signal.
  watchdog   Decides from the telemetry gap whether the module rebooted, hung, or went away.

What the watchdog does when telemetry stops for more than a minute (one HTTP request per probe):
  module answers, DHCP on       it rebooted onto the vendor cloud: check the saved static
                                settings, then switch DHCP off for this boot and restart WiFi
  connects but sends nothing    the issue #1 hang: after 3 such probes, reboot the module
  answers, DHCP off, silent     wait; after 15 minutes of silence, reboot the module
  no connection                 powered off, rebooting or out of range: do nothing
Commanded reboots are rate limited, and never count toward the module's fault limit.

Subcommands:
  run          the service loop; what the scheduled task starts
  status       what the service last saw and did
  target N     change the current limit it keeps, whole amps
  release      hand the charger back to the vendor cloud and stop reattaching
  attach       resume local control after a release

  python juicebox_helper.py status
  python juicebox_helper.py target 24
"""
import argparse
import collections
import datetime
import http.client
import json
import logging
import logging.handlers
import math
import os
import re
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from juicebox_collector import OneShot, parse  # noqa: E402
from juicebox_dns import DEFAULT_HOSTS, build_a_response, parse_question  # noqa: E402

VERSION = "1.0"
log = logging.getLogger("juicebox_helper")

DEFAULTS = {
    "charger_host": "192.168.1.63",   # the charger's saved wlan.static.ip
    "charger_mac": "",                # pins the beacon to one module; empty = any JuiceBox
    "gateway": "192.168.1.1",         # expected wlan.static.gateway: the router, never this PC
    "upstream_dns": "192.168.1.1",    # where every other lookup is forwarded
    "target_amps": 26,                # online and offline current limit to keep
    "mode": "local",                  # "local" keeps the charger here; "released" leaves it on the cloud
    "release_on_exit": True,          # hand the charger back on Ctrl-C or console close (see run())
}
J1772_MIN, HARD_MAX = 6, 40


def default_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "OpenJuice")


def wall():
    return datetime.datetime.now().isoformat(timespec="seconds")


def local_ip_for(host):
    """This PC's address on the route to host, or None when there is no route yet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 53))
        ip = s.getsockname()[0]
        return None if ip.startswith("0.") else ip
    except OSError:
        return None
    finally:
        s.close()


# --------------------------------- config ------------------------------------ #
def _validate(data):
    out = dict(DEFAULTS)
    out.update(data)
    t = int(out["target_amps"])
    if not J1772_MIN <= t <= HARD_MAX:
        raise ValueError("target_amps must be %d-%d" % (J1772_MIN, HARD_MAX))
    out["target_amps"] = t
    if out["mode"] not in ("local", "released"):
        raise ValueError("mode must be 'local' or 'released'")
    return out


class Config:
    """helper.json in the data directory. Re-read whenever the file changes."""

    def __init__(self, path):
        self.path = path
        self._mtime = "unread"
        self.data = dict(DEFAULTS)

    def get(self):
        try:
            mtime = os.stat(self.path).st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            try:
                raw = {}
                if mtime is not None:
                    with open(self.path, encoding="utf-8") as f:
                        raw = json.load(f)
                self.data = _validate(raw)
            except (OSError, ValueError, TypeError) as e:
                log.error("config %s unusable, keeping the previous settings: %s", self.path, e)
        return self.data

    @staticmethod
    def update(path, **changes):
        raw = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        raw.update(changes)
        _validate(raw)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def drop(path, key):
        """Remove one key, used to forget a one-shot request once it has been handled."""
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        if key in raw:
            del raw[key]
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)
            os.replace(tmp, path)


# ------------------------------ module interface ----------------------------- #
OK, EMPTY, DOWN, ERROR = "ok", "empty", "down", "error"
Reply = collections.namedtuple("Reply", "kind code text")

# The only commands this program can send to the module. Anything else, in particular
# `save`, any `zap.` variable and `set wlan.static.*`, is refused here so that no later
# edit can send it by accident. Never add port 2000 or `save`. `faults_reset` is sent only
# on an owner request (Watchdog.clear_faults), never on the helper's own initiative.
ALLOWED_COMMANDS = [re.compile(p) for p in (
    r"get [a-z0-9_.]+",
    r"faults_print",
    r"faults_reset",                  # owner request only; see Watchdog.clear_faults
    r"set wlan\.dhcp\.enabled 0",     # live only; the module reverts it on reboot
    r"network_restart",
    r"reboot",                        # takes effect even when the reply is empty
)]


class Module:
    """The WiFi module's web command interface on port 80.

    One request at a time, at least a second apart: the module shares one command parser
    with its serial link to the charging controller.
    """
    SPACING = 1.0

    def __init__(self, host_fn, timeout=8.0, port=80):
        self.host_fn = host_fn
        self.timeout = timeout
        self.port = port
        self._lock = threading.Lock()
        self._last = 0.0

    def command(self, cmd, timeout=None):
        if not any(p.fullmatch(cmd) for p in ALLOWED_COMMANDS):
            raise ValueError("refusing module command %r" % cmd)
        if not self._lock.acquire(timeout=20):
            return Reply(ERROR, None, "another request is still in flight")
        try:
            wait = self._last + self.SPACING - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            return self._request(self.host_fn(), self.port, cmd, timeout or self.timeout)
        finally:
            self._last = time.monotonic()
            self._lock.release()

    @staticmethod
    def _request(host, port, cmd, timeout):
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            try:
                conn.connect()
            except OSError as e:
                return Reply(DOWN, None, "%s: %s" % (type(e).__name__, e))
            try:
                conn.request("GET", "/command/" + cmd.replace(" ", "%20"))
                body = conn.getresponse().read()
            except (http.client.HTTPException, OSError) as e:
                # Issue #1 signature: the connection is accepted, then closed with no bytes.
                return Reply(EMPTY, None, "%s: %s" % (type(e).__name__, e))
            if not body:
                return Reply(EMPTY, None, "empty body")
            try:
                j = json.loads(body)
            except ValueError:
                return Reply(ERROR, None, body[:80].decode("latin1"))
            return Reply(OK, j.get("code"), str(j.get("response", "")).strip())
        finally:
            conn.close()


def fault_count(text):
    return sum(1 for line in text.splitlines() if "Exception" in line)


# ------------------------------- shared state -------------------------------- #
class Shared:
    """What the socket threads have seen, read by the watchdog and the status writer."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.started = clock()
        self.frame_t = None
        self.frame_wall = None
        self.frame_src = None
        self.fields = {}
        self.frames = 0
        self.dns_t = None
        self.dns_wall = None
        self.dns_hijacks = 0
        self.dns_ignored = 0
        self.beacon_t = None
        self.beacon = {}
        self.events = collections.deque(maxlen=40)
        self.last_complete = None      # {"t": iso, "wh": int or None}: the last finished charge

    def note(self, msg, level=logging.INFO):
        log.log(level, msg)
        with self.lock:
            self.events.append({"t": wall(), "msg": msg})

    def telemetry_age(self, now):
        return math.inf if self.frame_t is None else now - self.frame_t

    def module_host(self, now, default):
        """The module's current address: a fresh beacon, else the last telemetry source."""
        with self.lock:
            if self.beacon_t is not None and now - self.beacon_t < 60 and self.beacon.get("ip"):
                return self.beacon["ip"]
            if self.frame_src:
                return self.frame_src[0]
        return default


# ------------------------------ current limit -------------------------------- #
class LimitKeeper:
    """Keep the charger's online limit (telemetry M) at the configured target.

    A correction is one OneShot: send once, confirm by the echoed sequence number, resend
    only if unacknowledged. Each accepted command rewrites the offline limit in the
    charging controller's EEPROM, so corrections are spaced and capped per day.
    """
    SPACING = 60          # s between corrections for the same target
    DAILY_CAP = 12        # corrections per rolling 24 h

    def __init__(self, note, clock=time.monotonic):
        self.note = note
        self.clock = clock
        self.shot = None
        self.last_target = None
        self.last_start = -math.inf
        self.starts = collections.deque()
        self.outcome = None
        self._warned = None

    def corrections_24h(self):
        return len(self.starts)

    def on_frame(self, fields, target, enabled):
        """Returns a command string to send to the frame's source, or None."""
        now = self.clock()
        if self.shot is not None and self.shot.state == "sent":
            cmd = self.shot.on_frame(fields)
            if self.shot.state in ("done", "failed"):
                self.outcome = self.shot.describe()
                self.note("limit %d A: %s" % (self.shot.online, self.outcome),
                          logging.INFO if self.shot.state == "done" else logging.ERROR)
            return cmd
        if not enabled or "M" not in fields:
            return None
        rating = int(fields["m"]) if "m" in fields else HARD_MAX
        if not J1772_MIN <= target <= rating:
            self._warn_once("target %d A is outside %d-%d A; not sending" % (target, J1772_MIN, rating))
            return None
        if int(fields["M"]) == target:
            return None
        while self.starts and now - self.starts[0] > 86400:
            self.starts.popleft()
        if target == self.last_target and now - self.last_start < self.SPACING:
            return None
        if len(self.starts) >= self.DAILY_CAP:
            self._warn_once("limit is %s A, target %d A, but %d corrections were already sent in 24 h; "
                            "waiting" % (fields["M"], target, self.DAILY_CAP))
            return None
        self.note("limit is %s A, target %d A: sending a correction" % (fields["M"], target))
        self.shot = OneShot(target, target)
        self.last_target, self.last_start = target, now
        self.starts.append(now)
        return self.shot.on_frame(fields)

    def _warn_once(self, msg):
        if msg != self._warned:
            self._warned = msg
            self.note(msg, logging.WARNING)


# --------------------------------- watchdog ---------------------------------- #
class Watchdog:
    STALE = 60                # s without telemetry before the module is probed
    PROBE_EVERY = 30          # s between probes while telemetry is missing
    FAST_PROBE = 5            # s between probes right after a commanded reboot
    FAST_WINDOW = 180         # s
    HUNG_AFTER = 3            # consecutive empty or garbled replies that mean "hung"
    WEDGED_AFTER = 900        # s silent while the module answers with DHCP off
    SETTLE = 90               # s to wait for telemetry after switching the module to local
    REBOOT_SPACING = 1200     # s between commanded reboots
    REBOOTS_PER_DAY = 4
    REATTACHES_PER_HOUR = 3
    BLOCK_BACKOFF = 3600      # s before retrying after a failed precheck
    FAULT_GUARD = 6           # stop reattaching at this many module faults (Safe Mode at 8)
    REQUEST_MAX_AGE = 300     # s; an older one-shot request is dropped unhandled

    def __init__(self, module, shared, config, clock=time.monotonic, our_ip=local_ip_for, forget=None):
        self.forget = forget          # callable(key): removes a handled request from helper.json
        self.last_request = None
        self.module = module
        self.shared = shared
        self.config = config          # callable returning the current settings
        self.clock = clock
        self.our_ip = our_ip
        self.started = clock()
        self.state = "starting"
        self.detail = ""
        self.since = wall()
        self.next_probe = 0.0
        self.fast_until = -math.inf
        self.last_action = -math.inf
        self.empty_count = 0
        self.reboots = collections.deque()
        self.reattaches = collections.deque()
        self.blocked_until = -math.inf
        self.blocked_cfg = None
        self.release_sent = -math.inf
        self.faults = None
        self.faults_checked = False

    # -- helpers --
    def _set(self, state, detail, level=logging.INFO):
        if state != self.state or detail != self.detail:
            if state != self.state:
                self.since = wall()
                self.shared.note("%s: %s" % (state, detail), level)
            self.state, self.detail = state, detail

    def _get(self, var):
        r = self.module.command("get " + var)
        return r.text if r.kind == OK and r.code == 0 else None

    def _read_faults(self):
        r = self.module.command("faults_print")
        if r.kind != OK or r.code != 0:
            return None
        n = fault_count(r.text)
        if self.faults is not None and n > self.faults:
            self.shared.note("module fault count rose from %d to %d of 8: a new watchdog crash"
                             % (self.faults, n), logging.WARNING)
        self.faults = n
        return n

    def clear_faults(self, requested):
        """Clear the module's fault log because the owner asked (monitor or `clear-faults`).

        `requested` is the local time of the request. It is handled once and then forgotten,
        whether or not it worked, and ignored when stale, so a request left in helper.json can
        never fire later or repeat. The log is copied to helper.log before it is cleared.
        """
        self.last_request = requested
        if self.forget:
            try:
                self.forget("clear_faults")
            except OSError as e:
                log.warning("could not remove the handled request from helper.json: %s", e)
        try:
            age = (datetime.datetime.now() - datetime.datetime.fromisoformat(str(requested))).total_seconds()
        except ValueError:
            age = None
        if age is None or not -60 <= age <= self.REQUEST_MAX_AGE:
            self.shared.note("ignored a request to clear the fault log: it is not recent (%s)" % requested,
                             logging.WARNING)
            return
        r = self.module.command("faults_print")
        if r.kind != OK or r.code != 0:
            self.shared.note("fault log not cleared: could not read it first (%s)" % r.kind, logging.WARNING)
            return
        before = fault_count(r.text)
        for line in r.text.splitlines():
            if line.strip():
                log.info("fault log before clearing: %s", line.strip())
        r = self.module.command("faults_reset")
        after = self._read_faults()
        if after == 0:
            self.shared.note("fault log cleared at the owner's request: %d to 0 of 8" % before)
            self.blocked_until = -math.inf          # a fault block no longer applies
        else:
            self.shared.note("fault log not cleared: faults_reset replied %s %s; the log now reads %s"
                             % (r.kind, r.text, "unknown" if after is None else "%d of 8" % after),
                             logging.WARNING)

    def silent_for(self, now):
        return min(self.shared.telemetry_age(now), now - self.started, now - self.last_action)

    # -- the decision loop --
    def tick(self, now=None):
        now = self.clock() if now is None else now
        cfg = self.config()
        age = self.shared.telemetry_age(now)

        req = cfg.get("clear_faults")
        if req and req != self.last_request:
            self.clear_faults(req)

        if cfg["mode"] == "released":
            if age <= self.STALE and now - self.release_sent > 300:
                self.release("released by the operator")
            elif age > self.STALE:
                self._set("released", "local control is off; the charger is left on the vendor cloud")
            return

        if age <= self.STALE:
            self.empty_count = 0
            self._set("attached", "telemetry arriving")
            if not self.faults_checked:
                self.faults_checked = True
                self._read_faults()
            return

        if now < self.next_probe:
            return
        fast = now < self.fast_until          # just after a commanded reboot: probe at once
        if not fast and self.silent_for(now) <= self.STALE:
            return
        if now < self.blocked_until and cfg == self.blocked_cfg:
            return                            # blocked; a config change lifts the block early
        self.next_probe = now + (self.FAST_PROBE if fast else self.PROBE_EVERY)
        r = self.module.command("get wlan.dhcp.enabled")
        silent = self.silent_for(now)

        if r.kind == OK and r.code == 0 and r.text in ("0", "1"):
            self.empty_count = 0
            if r.text == "1":
                if not self.reattach(now):
                    self._set("detached", "the module is on DHCP and the vendor cloud")
            elif not (silent >= self.WEDGED_AFTER and self.reboot(
                    now, "no telemetry for %d min while the module answers" % (silent // 60))):
                self._set("silent", "the module answers with DHCP off but sends no telemetry")
        elif r.kind in (EMPTY, ERROR):
            self.empty_count += 1
            if not (self.empty_count >= self.HUNG_AFTER and self.reboot(
                    now, "hung: %d probes in a row returned nothing (issue #1)" % self.empty_count)):
                self._set("unresponsive", "the web interface accepts connections but returns nothing",
                          logging.WARNING)
        else:
            self.empty_count = 0
            self._set("unreachable", "no connection to the module (off, rebooting or out of range)")

    def precheck(self):
        """Refuse to switch DHCP off unless the saved static settings lead back to us."""
        cfg = self.config()
        ours = self.our_ip(cfg["charger_host"])
        want = {"wlan.static.ip": cfg["charger_host"], "wlan.static.gateway": cfg["gateway"],
                "wlan.static.dns": ours}
        if ours is None:
            return "this PC has no route to %s" % cfg["charger_host"]
        if cfg["gateway"] == ours:
            return "the configured gateway is this PC; it must be the router"
        for var, expected in want.items():
            got = self._get(var)
            if got is None:
                return "could not read %s" % var
            if got != expected:
                hint = (" This PC's address changed; give it a DHCP reservation on the router."
                        if var == "wlan.static.dns" else "")
                return "the charger's saved %s is %s, expected %s.%s" % (var, got, expected, hint)
        mask = self._get("wlan.static.netmask")
        if not mask or mask == "0.0.0.0":
            return "the charger's saved wlan.static.netmask is %r" % mask
        n = self._read_faults()
        if n is None:
            return "could not read the module's fault log"
        if n >= self.FAULT_GUARD:
            return ("the module has %d of 8 faults; at 8 it enters Safe Mode, so local control is "
                    "paused. Clearing the log is the owner's decision" % n)
        return None

    def _block(self, now, why):
        self.blocked_until = now + self.BLOCK_BACKOFF
        self.blocked_cfg = dict(self.config())
        self._set("blocked", why, logging.ERROR)
        return True

    def reattach(self, now):
        """Switch a module that is on DHCP back to us. True if the state was set here."""
        while self.reattaches and now - self.reattaches[0] > 3600:
            self.reattaches.popleft()
        if len(self.reattaches) >= self.REATTACHES_PER_HOUR:
            return self._block(now, "%d reattach attempts in an hour did not bring telemetry back"
                               % len(self.reattaches))
        why = self.precheck()
        if why:
            return self._block(now, why)
        r = self.module.command("set wlan.dhcp.enabled 0")
        if r.kind != OK or r.code != 0:
            self.shared.note("could not switch DHCP off: %s %s" % (r.kind, r.text), logging.WARNING)
            return False
        self.module.command("network_restart")      # the reply may be cut off by the restart
        self.reattaches.append(now)
        self.last_action = now
        self.next_probe = now + self.SETTLE
        self._set("reattaching", "found on DHCP and the cloud; switched DHCP off for this boot and "
                  "restarted WiFi; waiting for telemetry")
        return True

    def reboot(self, now, why):
        """Reboot the module, within the rate limits. True if the state was set here."""
        while self.reboots and now - self.reboots[0] > 86400:
            self.reboots.popleft()
        if self.reboots and now - self.reboots[-1] < self.REBOOT_SPACING:
            return False
        if len(self.reboots) >= self.REBOOTS_PER_DAY:
            self._set("gave_up", "%d reboots in 24 h did not help; not rebooting again until one ages "
                      "out" % len(self.reboots), logging.ERROR)
            return True
        r = self.module.command("reboot")
        self.reboots.append(now)
        self.last_action = now
        self.empty_count = 0
        self.fast_until = now + self.FAST_WINDOW
        self.next_probe = now + 20
        self._set("rebooting", "%s; reboot sent (reply: %s)" % (why, r.kind), logging.WARNING)
        return True

    def release(self, why):
        """Hand the charger back to the cloud: a reboot reverts the unsaved DHCP change."""
        r = self.module.command("reboot", timeout=4)
        self.release_sent = self.clock()
        self.last_action = self.release_sent
        self._set("released", "%s; reboot sent (reply: %s)" % (why, r.kind))


# ------------------------------ socket threads ------------------------------- #
def bind_udp(port, stop, exclusive=True, name=""):
    """Bind 0.0.0.0:port, retrying until it succeeds or the helper stops.

    Exclusive on Windows, so a second copy of this helper or a manually started collector
    fails loudly instead of silently sharing the port.
    """
    warned = False
    while not stop.is_set():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if exclusive and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif not exclusive:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            s.settimeout(1.0)
            if warned:
                log.info("%s: bound udp/%d", name, port)
            return s
        except OSError as e:
            s.close()
            if not warned:
                log.error("%s: cannot bind udp/%d (%s); retrying every 10 s", name, port, e)
                warned = True
            stop.wait(10)
    return None


class TelemetryLog:
    """Same line format as juicebox_collector.py --log, rotated at 100 MB."""
    MAX = 100 * 1024 * 1024

    def __init__(self, path):
        self.path = path
        self.f = None
        self.n = 0

    def write(self, src, raw):
        if self.f is None:
            self.f = open(self.path, "a", encoding="utf-8")
        self.f.write("%s\t%s\t%s\n" % (datetime.datetime.now().isoformat(), src, raw))
        self.f.flush()
        self.n += 1
        if self.n % 500 == 0 and os.path.getsize(self.path) > self.MAX:
            self.f.close()
            stem, ext = os.path.splitext(self.path)
            os.replace(self.path, "%s-%s%s" % (stem, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), ext))
            self.f = None

    def close(self):
        if self.f is not None:
            self.f.close()
            self.f = None


class ChargeWatch:
    """Notices a finished charge: charging (S2), then idle (S1) held for CONFIRM seconds.

    Same rules as charge_notifier.py, which cannot be imported here because only this file and
    its two imports are installed. Under MIN_WH delivered is a blip, not a charge; a GAP in the
    frames means the charge was not watched through, so nothing is claimed about it.
    """
    CONFIRM, GAP, MIN_WH = 30, 60, 100

    def __init__(self):
        self.armed = False
        self.s1_since = self.last_t = self.arm_l = self.last_l = self.last_e = None
        self.last = None

    def observe(self, when, state, lifetime, session=None):
        """Feed one frame. Returns {"t", "wh"} when a completion has just been confirmed.

        The energy is the charger's own session counter (E, sent while charging) when it was
        seen, else the rise in lifetime energy since this watch first saw the charge.
        """
        done = None
        if self.last_t is not None and (when - self.last_t).total_seconds() > self.GAP:
            self.armed, self.s1_since = False, None
        self.last_t = when
        if state == "2":
            if not self.armed:
                self.arm_l = lifetime if lifetime is not None else self.last_l
                self.last_e = None
            if session is not None:
                self.last_e = session
            self.armed, self.s1_since = True, None
        elif state == "1":
            if self.armed and self.s1_since is None:
                self.s1_since = when
            elif self.armed and (when - self.s1_since).total_seconds() >= self.CONFIRM:
                wh = self.last_e
                if wh is None and None not in (self.last_l, self.arm_l):
                    wh = self.last_l - self.arm_l
                if wh is None or wh >= self.MIN_WH:
                    done = self.last = {"t": self.s1_since.isoformat(timespec="seconds"), "wh": wh}
                self.armed, self.s1_since = False, None
        else:
            self.armed, self.s1_since = False, None
        if lifetime is not None:
            self.last_l = lifetime
        return done

    def seed(self, path, tail=4 * 1024 * 1024):
        """Replay the end of telemetry.log, so a restart keeps the last completion and a charge
        in progress stays armed with the energy it started at."""
        try:
            with open(path, "rb") as f:
                f.seek(max(0, f.seek(0, 2) - tail))
                lines = f.read().decode("latin1").split("\n")[1:]
        except OSError:
            return
        for s in lines:
            if ":v" not in s:
                continue
            try:
                when = datetime.datetime.fromisoformat(s[:19])
            except ValueError:
                continue
            state = _field(s, "S")
            self.observe(when, None if state is None else str(state), _field(s, "L"), _field(s, "E"))


def listener_loop(shared, config, keeper, tlog, stop, port=8042, watch=None):
    s = bind_udp(port, stop, name="listener")
    if s is None:
        return
    quiet_since = None
    try:
        while not stop.is_set():
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:     # Windows: ICMP port-unreachable from an old reply
                continue
            try:
                raw = data.decode("latin1", "replace")
                tlog.write(addr[0], raw)
                r = parse(raw)
                if not r:
                    continue
                with shared.lock:
                    shared.frame_t = shared.clock()
                    shared.frame_wall = wall()
                    shared.frame_src = addr
                    shared.fields = dict(r[2])
                    shared.frames += 1
                cfg = config()
                cmd = keeper.on_frame(r[2], cfg["target_amps"], cfg["mode"] == "local")
                if cmd:
                    s.sendto(cmd.encode(), addr)
                    shared.note("sent to %s:%d: %s" % (addr[0], addr[1], cmd))
                done = watch and watch.observe(datetime.datetime.now(), r[2].get("S"),
                                               _ival(r[2], "L", None), _ival(r[2], "E", None))
                if done:
                    with shared.lock:
                        shared.last_complete = done
                    if done["wh"] is None:      # neither energy counter in any frame: not a normal charge
                        shared.note("charging stopped at %s, but the charger sent no energy counters; "
                                    "cannot confirm a real charge" % done["t"][11:], logging.WARNING)
                    else:
                        shared.note("charge complete at %s, %.1f kWh delivered"
                                    % (done["t"][11:], done["wh"] / 1000.0))
            except Exception:                # one bad frame must not kill telemetry + correction
                if quiet_since is None or time.monotonic() - quiet_since > 600:
                    quiet_since = time.monotonic()
                    log.exception("listener: dropped a frame from %s it could not process", addr[0])
    finally:
        s.close()
        tlog.close()


def _forward(up, data, upstream, port=53):
    up.sendto(data, (upstream, port))
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        resp, _ = up.recvfrom(2048)
        if resp[:2] == data[:2]:           # skip a late answer to an earlier query
            return resp
    raise socket.timeout("no upstream answer")


def resolver_loop(shared, config, stop, port=53, upstream_port=53):
    s = bind_udp(port, stop, name="resolver")
    if s is None:
        return
    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    up.settimeout(3.0)
    hijack = set(DEFAULT_HOSTS)
    quiet_since = None
    try:
        while not stop.is_set():
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue
            cfg = config()
            src = addr[0]
            module_ip = shared.module_host(shared.clock(), cfg["charger_host"])
            if src not in (cfg["charger_host"], module_ip, "127.0.0.1"):
                with shared.lock:
                    shared.dns_ignored += 1
                continue
            try:
                qname, qtype, qend = parse_question(data)
            except (IndexError, struct.error, UnicodeDecodeError):
                continue
            if qname in hijack and qtype == 1:
                ip = local_ip_for(cfg["charger_host"] if src == "127.0.0.1" else src)
                if ip is None:
                    continue
                s.sendto(build_a_response(data, qend, ip), addr)
                if src != "127.0.0.1":
                    now = shared.clock()
                    with shared.lock:
                        gap = None if shared.dns_t is None else now - shared.dns_t
                        shared.dns_t, shared.dns_wall = now, wall()
                        shared.dns_hijacks += 1
                    if gap is None or gap > 300:
                        shared.note("resolver: %s asked for %s, answered %s" % (src, qname, ip))
                continue
            try:
                s.sendto(_forward(up, data, cfg["upstream_dns"], upstream_port), addr)
            except OSError as e:
                if quiet_since is None or time.monotonic() - quiet_since > 600:
                    quiet_since = time.monotonic()
                    log.warning("resolver: forwarding %s to %s failed: %s", qname, cfg["upstream_dns"], e)
    finally:
        s.close()
        up.close()


def beacon_loop(shared, config, stop, port=55555):
    s = bind_udp(port, stop, exclusive=False, name="beacon")
    if s is None:
        return
    try:
        while not stop.is_set():
            try:
                data, addr = s.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                continue
            try:
                j = json.loads(data)
            except ValueError:
                continue
            if not isinstance(j, dict):
                continue
            mac = config()["charger_mac"].upper()
            if mac:
                if str(j.get("mac", "")).upper() != mac:
                    continue
            elif not str(j.get("version", "")).startswith("EMWERK-JB"):
                continue
            ip = j.get("ip") or addr[0]
            with shared.lock:
                moved = shared.beacon.get("ip") not in (None, ip)
                shared.beacon_t = shared.clock()
                shared.beacon = {"ip": ip, "rssi": j.get("rssi"), "mac": j.get("mac"), "t": wall()}
            if moved:
                shared.note("beacon: the module is now at %s" % ip)
    finally:
        s.close()


def resolver_selftest(port=53, attempts=3, timeout=1.0):
    """Ask our own resolver for a hijacked name over loopback.

    Sends up to `attempts` probes over ONE socket (so a late answer to an earlier
    probe still counts), each waiting `timeout` seconds -- same ~3 s total budget as
    before, split into tries. Returns True on the first valid answer. The resolver is
    single-threaded, so while it is briefly blocked forwarding an upstream query it
    cannot answer a probe; retrying means a healthy-but-busy resolver still passes,
    and only a genuinely dead one (nothing bound on 53, crashed thread) fails them all.
    """
    q = struct.pack("!HHHHHH", 0x4F4A, 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(p)]) + p.encode() for p in DEFAULT_HOSTS[0].split(".")) + b"\x00"
    q += struct.pack("!HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        for _ in range(attempts):
            try:
                s.sendto(q, ("127.0.0.1", port))
                resp, _ = s.recvfrom(512)
                if resp[:2] == q[:2] and len(resp) >= len(q) + 16:
                    return True
            except socket.timeout:
                continue                       # resolver busy this try; probe again
            except OSError:
                return False                   # nothing listening / socket gone: dead
        return False
    finally:
        s.close()


# ------------------------------ Windows plumbing ----------------------------- #
def single_instance(data_dir):
    """Hold a lock file for the life of the process. None if another copy holds it."""
    path = os.path.join(data_dir, "helper.lock")
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def install_console_handler(on_stop):
    """Run on_stop on Ctrl-C, Ctrl-Break or when the console window is closed.

    Not on Windows shutdown or logoff: Windows withholds those events from any process that has
    loaded user32.dll, and both ctypes and the ssl module behind http.client load it. A shutdown
    therefore leaves the charger pointed at this PC; the helper recovers it at the next boot.
    """
    if os.name != "nt":
        return None
    import ctypes
    CTRL_LOGOFF_EVENT = 5
    handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

    def handler(event):
        if event == CTRL_LOGOFF_EVENT:     # someone logging off; keep running
            return 1
        on_stop(event)
        return 1

    cb = handler_type(handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(cb, True)
    return cb                              # caller keeps the reference alive


# ---------------------------------- service ---------------------------------- #
def setup_logging(data_dir, console):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(os.path.join(data_dir, "helper.log"),
                                              maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


def write_status(path, shared, wd, keeper, config, started_wall):
    now = shared.clock()
    cfg = config()
    with shared.lock:
        age = shared.telemetry_age(now)
        st = {
            "written": wall(), "pid": os.getpid(), "version": VERSION, "started": started_wall,
            "mode": cfg["mode"], "target_amps": cfg["target_amps"],
            "watchdog": {"state": wd.state, "detail": wd.detail, "since": wd.since,
                         "reboots_24h": len(wd.reboots), "module_faults": wd.faults},
            "telemetry": {"last": shared.frame_wall, "age_s": None if age == math.inf else round(age),
                          "frames": shared.frames,
                          "from": "%s:%d" % shared.frame_src if shared.frame_src else None,
                          "fields": shared.fields},
            "resolver": {"last_hijack": shared.dns_wall, "hijacks": shared.dns_hijacks,
                         "ignored": shared.dns_ignored},
            "beacon": shared.beacon,
            "limit": {"target": config()["target_amps"], "outcome": keeper.outcome,
                      "corrections_24h": keeper.corrections_24h()},
            "charge": {"last_complete": shared.last_complete},
            "events": list(shared.events),
        }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass                                # a reader had it open; next write will land


def run(args):
    data_dir = args.data_dir
    os.makedirs(data_dir, exist_ok=True)
    setup_logging(data_dir, console=bool(sys.stderr and sys.stderr.isatty()))
    lock = single_instance(data_dir)
    if lock is None:
        log.info("another copy of the helper is running; exiting")
        return 0
    config = Config(os.path.join(data_dir, "helper.json")).get
    shared = Shared()
    module = Module(lambda: shared.module_host(time.monotonic(), config()["charger_host"]))
    keeper = LimitKeeper(shared.note)
    cfg_path = os.path.join(data_dir, "helper.json")
    wd = Watchdog(module, shared, config, forget=lambda key: Config.drop(cfg_path, key))
    previous, _ = read_status(data_dir)
    if previous:                       # so a crash while the helper was down is still noticed
        wd.faults = previous.get("watchdog", {}).get("module_faults")
    threading.excepthook = lambda a: log.error(
        "thread %s crashed", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    stop = threading.Event()
    watch = ChargeWatch()
    watch.seed(os.path.join(data_dir, "telemetry.log"))
    shared.last_complete = watch.last
    tlog = TelemetryLog(os.path.join(data_dir, "telemetry.log"))
    started_wall = wall()
    shared.note("helper %s starting (pid %d); mode %s, target %d A"
                % (VERSION, os.getpid(), config()["mode"], config()["target_amps"]))

    def on_stop(event):
        cfg = config()
        attached = shared.telemetry_age(time.monotonic()) <= Watchdog.STALE
        if cfg["release_on_exit"] and cfg["mode"] == "local" and attached:
            wd.release("helper stopping (console event %d)" % event)
        else:
            shared.note("helper stopping (console event %d); charger not attached, nothing to hand back"
                        % event)
        stop.set()

    handler_ref = install_console_handler(on_stop)  # noqa: F841  (kept alive on purpose)
    threads = {
        "resolver": threading.Thread(target=resolver_loop, args=(shared, config, stop), daemon=True),
        "listener": threading.Thread(target=listener_loop, args=(shared, config, keeper, tlog, stop),
                                     kwargs={"watch": watch}, daemon=True),
        "beacon": threading.Thread(target=beacon_loop, args=(shared, config, stop), daemon=True),
    }
    for t in threads.values():
        t.start()

    status_path = os.path.join(data_dir, "status.json")
    next_status = next_selftest = time.monotonic() + 30
    selftest_failures = 0
    try:
        while not stop.is_set():
            now = time.monotonic()
            for name in ("resolver", "listener"):
                if not threads[name].is_alive():
                    shared.note("%s thread died; exiting so the scheduled task restarts the helper"
                                % name, logging.ERROR)
                    write_status(status_path, shared, wd, keeper, config, started_wall)
                    return 3
            try:
                wd.tick(now)
            except Exception:
                log.exception("watchdog tick failed")
            if now >= next_selftest:
                next_selftest = now + 300
                if resolver_selftest():
                    selftest_failures = 0
                else:
                    selftest_failures += 1
                    shared.note("resolver self-test failed (%d in a row)" % selftest_failures,
                                logging.WARNING)
                    if selftest_failures >= 3:
                        shared.note("resolver is not answering; exiting so the task restarts it",
                                    logging.ERROR)
                        return 4
            if now >= next_status:
                next_status = now + 10
                write_status(status_path, shared, wd, keeper, config, started_wall)
            stop.wait(2.0)
    except KeyboardInterrupt:
        on_stop(0)
    write_status(status_path, shared, wd, keeper, config, started_wall)
    shared.note("helper stopped")
    return 0


# ------------------------------------ CLI ------------------------------------ #
STATE_NAMES = {"0": "unplugged", "1": "plugged in", "2": "charging", "5": "error"}


def read_status(data_dir):
    path = os.path.join(data_dir, "status.json")
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None, None
    written = datetime.datetime.fromisoformat(st["written"])
    return st, (datetime.datetime.now() - written).total_seconds()


def _dur(secs):
    secs = max(0, int(secs))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return "%dd%dh" % (d, h)
    if h:
        return "%dh%dm" % (h, m)
    return "%dm%ds" % (m, s)


def _hhmmss(iso):
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return str(iso)


# ---- status TUI: a cell canvas themed after Turbo Vision / TuiCss ----
_UNI = {"h": "═", "v": "║", "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
        "full": "█", "empty": "░", "desk": "░", "sep": "│", "mark": "▼",
        "part": "\u2581\u2582\u2583\u2584\u2585\u2586\u2587",
        "hpart": "\u258f\u258e\u258d\u258c\u258b\u258a\u2589",
        "sh": "─", "sv": "│", "stl": "┌", "str": "┐", "sbl": "└", "sbr": "┘",
        "stee": "├", "etee": "┤", "dot": "•",
        "sys": "≡", "box": "■", "lower": "▄", "upper": "▀"}
_ASC = {"h": "=", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+",
        "full": "#", "empty": ".", "desk": " ", "sep": "|", "mark": "v",
        "part": "", "hpart": "",
        "sh": "-", "sv": "|", "stl": "+", "str": "+", "sbl": "+", "sbr": "+",
        "stee": "+", "etee": "+", "dot": "*",
        "sys": "=", "box": "x", "lower": " ", "upper": " "}

# Colours are ANSI SGR numbers: (fg, bg) pairs, or a lone fg. tools/juicebox/monitor/
# OpenJuiceMonitor.cs carries the same table; change both together.
THEMES = {
    "turbo": dict(pattern=True, desk=(94, 44), bar=(30, 47), key=31, main=(30, 46), win=(30, 47),
                  log=(97, 40), logtime=93, logtext=37, shadow=(90, 40), trough=(90, 40),
                  fill=92, fillbad=91, tick=93,
                  ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(97, 44), idle=(97, 100)),
    "commander": dict(pattern=False, desk=(90, 40), bar=(30, 46), key=31, main=(97, 44), win=(96, 44),
                      log=(96, 44), logtime=93, logtext=97, shadow=(90, 40), trough=(94, 40),
                      fill=96, fillbad=91, tick=93,
                      ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(30, 46), idle=(30, 47)),
    "phosphor": dict(pattern=False, desk=(32, 40), bar=(30, 42), key=97, main=(92, 40), win=(32, 40),
                     log=(32, 40), logtime=92, logtext=32, shadow=(32, 40), trough=(32, 40),
                     fill=92, fillbad=97, tick=97,
                     ok=(30, 42), warn=(30, 102), bad=(30, 107), info=(30, 42), idle=(92, 40)),
    "amber": dict(pattern=False, desk=(33, 40), bar=(30, 43), key=97, main=(93, 40), win=(33, 40),
                  log=(33, 40), logtime=93, logtext=33, shadow=(33, 40), trough=(33, 40),
                  fill=93, fillbad=97, tick=97,
                  ok=(30, 43), warn=(30, 103), bad=(30, 107), info=(30, 43), idle=(93, 40)),
    "light": dict(pattern=True, desk=(37, 107), bar=(97, 44), key=93, main=(30, 47), win=(30, 47),
                  log=(30, 107), logtime=34, logtext=30, shadow=(37, 100), trough=(37, 100),
                  fill=92, fillbad=91, tick=93,
                  ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(97, 44), idle=(97, 100)),
}
THEMES.update({
    "pascal": dict(pattern=True, desk=(90, 47), bar=(30, 46), key=31, main=(93, 44), win=(97, 44),
                   log=(93, 44), logtime=96, logtext=97, shadow=(90, 40), trough=(90, 40),
                   fill=93, fillbad=91, tick=97,
                   ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(30, 46), idle=(30, 47)),
    "midnight": dict(pattern=True, desk=(90, 40), bar=(97, 45), key=93, main=(97, 100), win=(37, 100),
                     log=(95, 40), logtime=95, logtext=37, shadow=(30, 40), trough=(90, 40),
                     fill=95, fillbad=91, tick=93,
                     ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(97, 45), idle=(30, 47)),
    "ocean": dict(pattern=True, desk=(96, 46), bar=(97, 44), key=93, main=(30, 107), win=(30, 107),
                  log=(97, 44), logtime=96, logtext=97, shadow=(90, 40), trough=(37, 100),
                  fill=94, fillbad=91, tick=93,
                  ok=(30, 42), warn=(30, 43), bad=(97, 41), info=(97, 44), idle=(97, 100)),
    "hotdog": dict(pattern=False, desk=(93, 41), bar=(97, 40), key=93, main=(30, 103), win=(30, 103),
                   log=(93, 40), logtime=91, logtext=93, shadow=(30, 40), trough=(90, 40),
                   fill=91, fillbad=97, tick=93,
                   ok=(30, 42), warn=(97, 45), bad=(97, 41), info=(97, 44), idle=(97, 100)),
    "mono": dict(pattern=False, desk=(37, 40), bar=(30, 47), key=30, main=(97, 40), win=(37, 40),
                 log=(37, 40), logtime=97, logtext=37, shadow=(37, 40), trough=(90, 40),
                 fill=37, fillbad=97, tick=97,
                 ok=(30, 47), warn=(30, 107), bad=(30, 107), info=(30, 47), idle=(97, 40)),
})
THEME_ORDER = ["turbo", "commander", "pascal", "midnight", "ocean", "phosphor", "amber", "light",
               "hotdog", "mono"]


def load_theme(data_dir):
    """The theme last chosen here or in the desktop monitor (ui.json), else turbo."""
    try:
        with open(os.path.join(data_dir, "ui.json"), encoding="utf-8") as f:
            name = json.load(f).get("theme")
    except (OSError, ValueError, AttributeError):
        name = None
    return name if name in THEMES else "turbo"


def save_theme(data_dir, name):
    path = os.path.join(data_dir, "ui.json")
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"theme": name}, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


class _Canvas:
    """A grid of (char, fg, bg) cells; fg/bg are ANSI SGR numbers (30-37/90-97, 40-47/100-107)."""

    def __init__(self, w, h, ch, fg, bg):
        self.w, self.h = w, h
        self.cells = [[(ch, fg, bg)] * w for _ in range(h)]

    def put(self, x, y, text, fg=None, bg=None):
        if not 0 <= y < self.h:
            return
        row = self.cells[y]
        for i, ch in enumerate(text):
            if 0 <= x + i < self.w:
                _, f0, b0 = row[x + i]
                row[x + i] = (ch, f0 if fg is None else fg, b0 if bg is None else bg)

    def fill(self, x, y, w, h, ch, fg, bg):
        for yy in range(y, y + h):
            self.put(x, yy, ch * w, fg, bg)

    def shade(self, x, y, w, h, fg, bg):
        """A drop shadow, as Turbo Vision casts it: the cells keep their characters and only
        change colour. Dark grey on black would vanish on a black cell, so that one is reversed."""
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                ch, _, b0 = self.cells[yy][xx]
                self.cells[yy][xx] = (ch, 30, 100) if (fg, bg, b0) == (90, 40, 40) else (ch, fg, bg)

    def window(self, x, y, w, h, title, colors, shadow, g, frame=None, single=False):
        """A framed box with a centred title and a shadow. `frame` colours the border and title
        apart from the body; `single` draws the one-line frame of a window that is not the main one."""
        fg, bg = colors
        ffg, fbg = frame or colors
        hz, vt = (g["sh"], g["sv"]) if single else (g["h"], g["v"])
        tl, tr, bl, br = ((g["stl"], g["str"], g["sbl"], g["sbr"]) if single
                          else (g["tl"], g["tr"], g["bl"], g["br"]))
        self.shade(x + 2, y + 1, w, h, *shadow)             # drop shadow
        self.fill(x, y, w, h, " ", fg, bg)
        self.put(x, y, tl + hz * (w - 2) + tr, ffg, fbg)
        self.put(x, y + h - 1, bl + hz * (w - 2) + br, ffg, fbg)
        for yy in range(y + 1, y + h - 1):
            self.put(x, yy, vt, ffg, fbg)
            self.put(x + w - 1, yy, vt, ffg, fbg)
        t = " %s " % title
        self.put(x + (w - len(t)) // 2, y, t, ffg, fbg)

    def render(self, color):
        lines = []
        for row in self.cells:
            if not color:
                lines.append("".join(c for c, _, _ in row).rstrip())
                continue
            out, cur = [], None
            for ch, f, b in row:
                if (f, b) != cur:
                    out.append("\x1b[%d;%dm" % (f, b))
                    cur = (f, b)
                out.append(ch)
            out.append("\x1b[0m")
            lines.append("".join(out))
        return "\n".join(lines)


def _enable_vt():
    """Turn on ANSI handling in a Windows console; no-op elsewhere or on failure."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _use_color(args):
    if getattr(args, "no_color", False):
        return False
    if getattr(args, "color", False):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _ival(f, k, d=0):
    try:
        return int(f[k])
    except (KeyError, ValueError, TypeError):
        return d


def _clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[:max(0, n - 3)] + "..."


def _field(line, key):
    """Integer value of one telemetry field (e.g. 'A', 'L') in a telemetry.log line, or None."""
    for tok in line.rsplit("\t", 1)[-1].split(","):
        if tok.startswith(key):
            digits = tok[len(key):].split("!")[0]
            if digits.isdigit():
                return int(digits)
    return None


def _log_lifetime_at(f, size, stamp):
    """Lifetime Wh in the first frame at or after an ISO timestamp, by bisecting the log."""
    lo, hi = 0, size
    while hi - lo > 8192:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()
        ts = f.readline()[:19].decode("latin1")
        if len(ts) == 19 and ts < stamp:
            lo = mid
        else:
            hi = mid
    f.seek(lo)
    if lo:
        f.readline()
    for _ in range(2000):
        line = f.readline()
        if not line:
            return None
        s = line.decode("latin1")
        if s[:19] >= stamp:
            v = _field(s, "L")
            if v is not None:
                return v
    return None


def load_history(data_dir, days=7):
    """Chart data from telemetry.log: peak amps per minute (recent) and kWh per day.

    Returns {"amps": {"YYYY-MM-DDTHH:MM": amps}, "days": [(label, kWh or None), ...]} or None.
    """
    try:
        with open(os.path.join(data_dir, "telemetry.log"), "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - 200 * 1024))
            amps, last_l = {}, None
            for s in f.read().decode("latin1").split("\n")[1:]:
                if ":v" not in s:
                    continue
                a = (_field(s, "A") or 0) / 10.0
                amps[s[:16]] = max(a, amps.get(s[:16], 0.0))
                v = _field(s, "L")
                if v is not None:
                    last_l = v
            today = datetime.date.today()
            dates = [today - datetime.timedelta(days=days - 1 - i) for i in range(days)]
            marks = [_log_lifetime_at(f, size, d.isoformat() + "T00:00:00") for d in dates] + [last_l]
            daily = []
            for i, d in enumerate(dates):
                a, b = marks[i], marks[i + 1] if marks[i + 1] is not None else last_l
                daily.append((d.strftime("%a")[:2], (b - a) / 1000.0 if a is not None and b is not None and b >= a else None))
            return {"amps": amps, "days": daily}
    except OSError:
        return None


def _compose(st, age, events, g, size=(80, 32), hint="", theme="turbo", hist=None):
    """Lay the status snapshot out as windows on a desktop. Returns a _Canvas."""
    T = THEMES.get(theme, THEMES["turbo"])
    W, H = max(80, size[0]), max(30, size[1])
    now = datetime.datetime.now()
    alive = age < 30
    cv = _Canvas(W, H, g["desk"] if T["pattern"] else " ", *T["desk"])

    cv.fill(0, 0, W, 1, " ", *T["bar"])                     # title bar
    cv.put(1, 0, "OpenJuice", T["key"])
    cv.put(11, 0, "%s JuiceBox Gen 1" % g["sep"])
    clock = now.strftime("%Y-%m-%d %H:%M:%S")
    cv.put(W - len(clock) - 1, 0, clock)

    cv.fill(0, H - 1, W, 1, " ", *T["bar"])                 # status bar
    items = [("Theme", theme)]
    if hint:
        items.append(("Keys", hint))
    x = 1
    for key, text in items:
        cv.put(x, H - 1, key, T["key"])
        cv.put(x + len(key) + 1, H - 1, text)
        x += len(key) + len(text) + 2
        cv.put(x, H - 1, g["sep"])
        x += 2

    ww = (W - 10) // 2                                      # leaves desktop around every shadow
    lx, rx, ty, th = 2, 2 + ww + 4, 2, 10
    fw, cy, chh, by, bh = 2 * ww + 4, 13, 9, 24, H - 26     # charts row, then the Event log
    iw = ww - 4                                             # text columns inside a window
    bw = iw - 17                                            # bar cells in a "label bar value" row

    def text(wx, wy, line, label, value):
        cv.put(wx + 2, wy + 1 + line, "%-8s" % label)
        cv.put(wx + 11, wy + 1 + line, _clip(value, iw - 9))

    def chip(wx, wy, line, label, body, colors, tail=""):
        cv.put(wx + 2, wy + 1 + line, "%-8s" % label)
        body = " %s " % body
        cv.put(wx + 11, wy + 1 + line, body, *colors)
        cv.put(wx + 11 + len(body), wy + 1 + line, _clip(tail, iw - 9 - len(body)))

    def meter(x0, y0, width, value, maxv, cap=None, bad=False):
        fill = int(round(max(0.0, min(value, maxv)) / maxv * width)) if maxv else 0
        tick = min(width - 1, int(round(cap / maxv * width))) if (cap is not None and maxv) else -1
        tbg = T["trough"][1]
        for i in range(width):
            if i < fill:
                cv.put(x0 + i, y0, g["full"], T["fillbad"] if bad else T["fill"], tbg)
            elif i == tick:
                cv.put(x0 + i, y0, g["sep"], T["tick"], tbg)
            else:
                cv.put(x0 + i, y0, g["empty"], T["trough"][0], tbg)

    def bar(wx, wy, line, label, value, maxv, shown, cap=None, bad=False):
        cv.put(wx + 2, wy + 1 + line, "%-8s" % label)
        meter(wx + 11, wy + 1 + line, bw, value, maxv, cap, bad)
        cv.put(wx + 12 + bw, wy + 1 + line, _clip(shown, 7))

    def column(x0, bottom, rows, frac, width, fg):
        """A vertical bar growing up from `bottom`; returns the row of its top cell."""
        eighths = int(round(max(0.0, min(frac, 1.0)) * rows * 8))
        if frac > 0 and eighths == 0:
            eighths = 1
        full, part = divmod(eighths, 8)
        for i in range(full):
            cv.put(x0, bottom - i, g["full"] * width, fg)
        if part and g["part"]:
            cv.put(x0, bottom - full, g["part"][part - 1] * width, fg)
        elif part >= 4:
            cv.put(x0, bottom - full, g["full"] * width, fg)
        return bottom - full - (0 if part else -1)

    # --- Charger: every reading as a bar ----------------------------------------
    cv.window(lx, ty, ww, th, "Charger", T["main"], T["shadow"], g)
    t = st["telemetry"]
    f = t["fields"]
    done = (st.get("charge") or {}).get("last_complete")
    if not (isinstance(done, dict) and isinstance(done.get("t"), str) and len(done["t"]) >= 16):
        done = None
    cap, circ = _ival(f, "M"), _ival(f, "m", 40) or 40
    if t["last"]:
        sc = f.get("S")
        sname = STATE_NAMES.get(sc, sc or "?").upper()
        scol = T[{"2": "ok", "1": "info", "0": "idle", "5": "bad"}.get(sc, "idle")]
        chip(lx, ty, 0, "State", sname, scol, " %ds ago" % t["age_s"] if t["age_s"] is not None else "")
        a, v, temp = _ival(f, "A") / 10.0, _ival(f, "V") / 10.0, _ival(f, "T")
        # Three bands, the same as the Health window beside it, so the two read across: status
        # chips, then every gauge, then plain figures.
        # The limit is the one the charger reports, flagged while it differs from the helper's.
        target = (st.get("limit") or {}).get("target")
        if "M" not in f:
            text(lx, ty, 1, "Limit", "-")
        elif target is not None and target != cap:
            chip(lx, ty, 1, "Limit", "%d A" % cap, T["warn"], " target %d A" % target)
        else:
            chip(lx, ty, 1, "Limit", "%d A" % cap, T["info"])
        bar(lx, ty, 2, "Current", a, circ, "%.1f A" % a, cap, bad=a > cap + 0.05)
        bar(lx, ty, 4, "Power", a * v / 1000.0, circ * 0.24, "%.2f kW" % (a * v / 1000.0))
        bar(lx, ty, 3, "Volts", v - 200, 60, "%.1f V" % v, bad=not 210 <= v <= 255)
        bar(lx, ty, 5, "Temp", temp, 80, "%d C" % temp, bad=temp > 60)
        if sc == "2" and "E" in f:                  # charging: this session so far
            text(lx, ty, 6, "Session", "{:,.3f} kWh".format(_ival(f, "E") / 1000.0))
        elif done:                                  # otherwise the last finished charge: when, how much
            when = done["t"][11:16] if done["t"][:10] == now.strftime("%Y-%m-%d") else done["t"][5:16]
            chip(lx, ty, 6, "Finished", when.replace("T", " "), T["ok"],
                 "" if done.get("wh") is None else " %.1f kWh" % (done["wh"] / 1000.0))
        else:
            text(lx, ty, 6, "Finished", "no charge seen yet")
        text(lx, ty, 7, "Lifetime", "{:,.3f} kWh".format(_ival(f, "L") / 1000.0) if "L" in f else "-")
    else:
        cv.put(lx + 2, ty + 1, _clip("no telemetry since the helper started", iw))

    # --- Health: helper, link and the counters that have limits -------------------
    single = _style(theme)["single"]
    cv.window(rx, ty, ww, th, "Health", T["win"], T["shadow"], g, single=single)
    w = st["watchdog"]
    try:
        up = _dur((now - datetime.datetime.fromisoformat(st["started"])).total_seconds())
    except (ValueError, TypeError, KeyError):
        up = "?"
    chip(rx, ty, 0, "Helper", "RUNNING" if alive else "STOPPED", T["ok"] if alive else T["bad"],
         " up %s" % up)
    ws = w["state"]
    wcol = (T["ok"] if ws == "attached" else
            T["warn"] if ws in ("reattaching", "silent", "rebooting", "starting", "released") else T["bad"])
    chip(rx, ty, 1, "Link", ws, wcol, " since %s" % _hhmmss(w["since"])[:5])
    nf = w["module_faults"]
    if nf is None:
        text(rx, ty, 2, "Faults", "unknown")
    else:
        bar(rx, ty, 2, "Faults", int(nf), 8, "%d/8" % int(nf), cap=Watchdog.FAULT_GUARD, bad=int(nf) > 5)
    nr, nc = w["reboots_24h"], st["limit"]["corrections_24h"]
    bar(rx, ty, 3, "Reboots", nr, Watchdog.REBOOTS_PER_DAY, "%d/%d" % (nr, Watchdog.REBOOTS_PER_DAY),
        bad=nr >= Watchdog.REBOOTS_PER_DAY)
    bar(rx, ty, 4, "Fixes", nc, LimitKeeper.DAILY_CAP, "%d/%d" % (nc, LimitKeeper.DAILY_CAP),
        bad=nc >= LimitKeeper.DAILY_CAP)
    rssi = (st["beacon"] or {}).get("rssi")
    if isinstance(rssi, int):
        bar(rx, ty, 5, "Signal", rssi + 90, 50, "%d dBm" % rssi, bad=rssi < -75)
    else:
        text(rx, ty, 5, "Signal", "no beacon")
    r = st["resolver"]
    text(rx, ty, 6, "Resolver", "%d answers at %s" % (r["hijacks"], _hhmmss(r["last_hijack"])[:5])
         if r.get("last_hijack") else "no requests yet")

    # --- Chart: current per minute --------------------------------------------------
    nb = iw - 3
    cv.window(lx, cy, ww, chh, "Current per minute, A", T["win"], T["shadow"], g, single=single)
    bottom = cy + 6
    if hist:
        cv.put(lx + 2, cy + 1, "%2d" % circ)
        cv.put(lx + 2, bottom, " 0")
        if 0 < cap < circ:
            cv.put(lx + 2, bottom - int(cap / circ * 6), "%2d" % cap)
        for i in range(nb):
            key = (now - datetime.timedelta(minutes=nb - 1 - i)).strftime("%Y-%m-%dT%H:%M")
            a = hist["amps"].get(key)
            if a:
                column(lx + 5 + i, bottom, 6, a / circ, 1, T["fillbad"] if a > cap + 0.05 else T["fill"])
            else:
                cv.put(lx + 5 + i, bottom, "_" if a is not None else " ")
        cv.put(lx + 5, cy + 7, "-%dm" % nb)
        cv.put(lx + 5 + nb - 3, cy + 7, "now")
        for i in range(nb):                         # mark the minute the charge finished
            if done and (now - datetime.timedelta(minutes=nb - 1 - i)).strftime("%Y-%m-%dT%H:%M") == done["t"][:16]:
                cv.put(lx + 5 + i, cy + 7, g["mark"], T["fill"])
    else:
        cv.put(lx + 2, cy + 1, _clip("no telemetry.log to chart", iw))

    # --- Chart: energy per day ------------------------------------------------------
    cv.window(rx, cy, ww, chh, "Energy per day, kWh", T["win"], T["shadow"], g, single=single)
    if hist and hist["days"]:
        days = hist["days"][-(chh - 2):]
        top = max([k for _, k in days if k] or [1.0])
        dbw, tbg = iw - 9, T["trough"][1]
        for i, (label, kwh) in enumerate(days):                 # one horizontal bar per day
            y = cy + 1 + i
            cv.put(rx + 2, y, "%-2s" % label)
            cv.put(rx + 5, y, g["empty"] * dbw, T["trough"][0], tbg)
            if kwh is None:
                cv.put(rx + 6 + dbw, y, "    -")
                continue
            eighths = int(round(kwh / top * dbw * 8))
            if kwh > 0 and eighths == 0:
                eighths = 1
            full, part = divmod(eighths, 8)
            cv.put(rx + 5, y, g["full"] * full, T["fill"], tbg)
            if part and g["hpart"]:
                cv.put(rx + 5 + full, y, g["hpart"][part - 1], T["fill"], tbg)
            elif part >= 4:
                cv.put(rx + 5 + full, y, g["full"], T["fill"], tbg)
            cv.put(rx + 6 + dbw, y, "%5.1f" % kwh)
    else:
        cv.put(rx + 2, cy + 1, _clip("no telemetry.log to chart", iw))

    # --- Event log ------------------------------------------------------------------
    cv.window(lx, by, fw, bh, "Event log", T["log"], T["shadow"], g, single=single)
    n = max(0, min(events, bh - 2)) if events else 0
    for i, e in enumerate(st["events"][-n:] if n else []):
        cv.put(lx + 2, by + 1 + i, str(e["t"])[:19].replace("T", " "), T["logtime"])
        cv.put(lx + 22, by + 1 + i, _clip(e["msg"], fw - 24), T["logtext"])
    return cv


def _dashboard(st, age, events, color=False, size=(80, 32), ascii_only=False, hint="", theme="turbo",
               hist=None):
    """The status screen as text: themed and full-colour, or plain ASCII when color is off."""
    glyphs = _ASC if (ascii_only or not color) else _UNI
    return _compose(st, age, events, glyphs, size, hint, theme, hist).render(color)


# ---- status TUI: menu bar, pull-down menus and dialogs ----
# The desktop monitor carries the same menus and dialogs (class Ui in OpenJuiceMonitor.cs); change
# both together. Like the monitor, the screen never contacts the charger: a control writes one
# value to helper.json for the running helper to act on, and asks Yes or No first.
#
# Keys behave the same in every theme; a theme changes only how things are drawn. Each theme
# follows one of three period styles (sources: the Turbo Vision 2.0 source as kept in
# magiblot/tvision, FAR Manager's palette and Midnight Commander's default skin, and Microsoft's
# QuickBASIC manual for monochrome screens):
#   tv    Borland Turbo Vision: grey dialogs with a close box, green buttons with a half-block
#         shadow, a green selection bar, "F10 Menu" status items, single frames on all but the
#         main window.
#   nc    Norton Commander / FAR: cyan menus with a black selection bar and yellow hot letters,
#         "{ No }" as the default button, red boxes for irreversible actions, a numbered
#         function-key bar.
#   mono  one-hue screens: reverse video for selection, a brighter cell for hot letters,
#         "< OK >" buttons, "F10=Menu" status items.
_FAMILY = {"commander": "nc", "phosphor": "mono", "amber": "mono", "mono": "mono"}      # others: tv


def _style(name):
    """Colours and drawing choices for menus and dialogs, derived from a theme."""
    T = THEMES.get(name, THEMES["turbo"])
    fam = _FAMILY.get(name, "tv")
    bar, bright = T["bar"], T["main"]
    if fam == "tv":
        hot = (T["key"], bar[1])
        return dict(family=fam, buttons="tv", status="tv", closebox=True, single=True,
                    barhot=hot, menu=bar, menuhot=hot, sel=(30, 42), selhot=(31, 42),
                    dlg=(30, 47), frame=(97, 47), icon=(92, 47), err=None, errfocus=None, errhot=None,
                    btn=(30, 42), btnhot=(93, 42), focus=(97, 42), focushot=(93, 42),
                    input=(97, 44), inputsel=(97, 42))
    if fam == "nc":
        return dict(family=fam, buttons="far", status="fn", closebox=False, single=False,
                    barhot=(93, bar[1]), menu=(97, 46), menuhot=(93, 46), sel=(97, 40), selhot=(93, 40),
                    dlg=(30, 47), frame=(30, 47), icon=None, err=(97, 41), errfocus=(30, 47), errhot=(93, 41),
                    btn=(30, 47), btnhot=(93, 47), focus=(30, 46), focushot=(93, 46),
                    input=(30, 46), inputsel=(97, 40))
    lit = (30, bar[1] + 60)                         # one hue: a brighter cell stands in for colour
    return dict(family=fam, buttons="cua", status="kv", closebox=False, single=False,
                barhot=lit, menu=bar, menuhot=lit, sel=bright, selhot=bar,
                dlg=T["win"], frame=(bright[0], T["win"][1]), icon=None, err=None, errfocus=None, errhot=None,
                btn=T["win"], btnhot=(bright[0], T["win"][1]), focus=bar, focushot=lit,
                input=bar, inputsel=bright)


# -- keys: one name per key, the same names in the monitor --
_VK = {0x70: "f1", 0x71: "f2", 0x74: "f5", 0x77: "f8", 0x78: "f9", 0x79: "f10",
       0x26: "up", 0x28: "down", 0x25: "left", 0x27: "right", 0x24: "home", 0x23: "end",
       0x0D: "enter", 0x1B: "esc", 0x08: "backspace", 0x20: " "}


def _key_name(vk, char, state):
    """Name of a console key-down event: virtual key, character, control-key state. None to ignore."""
    alt = bool(state & 0x3) and not state & 0xC      # either Alt, and not AltGr (which sets Ctrl too)
    if vk == 0x09:
        return "shift+tab" if state & 0x10 else "tab"
    if alt:
        return "alt+" + chr(vk).lower() if 0x41 <= vk <= 0x5A else None
    if vk in _VK:
        return _VK[vk]
    if state & 0xC:                                  # Ctrl combinations are not ours
        return None
    return char.lower() if char and char.isprintable() else None


_SPECIAL_KEYS = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end",
                 ";": "f1", "<": "f2", "?": "f5", "B": "f8", "C": "f9", "D": "f10", "\x0f": "shift+tab"}
_PLAIN_KEYS = {"\r": "enter", "\x1b": "esc", "\t": "tab", "\b": "backspace"}


def _read_keys_msvcrt():
    """Fallback reader. It cannot see Alt: Alt+letter arrives as the plain letter."""
    import msvcrt
    out = []
    while msvcrt.kbhit():
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):                  # arrows and function keys arrive as two codes
            name = _SPECIAL_KEYS.get(msvcrt.getwch())
            if name:
                out.append(name)
        else:
            out.append(_PLAIN_KEYS.get(ch, ch.lower()))
    return out


def _read_keys():
    """Keys pressed since the last call, as names (Windows console only).

    Reads console input records, because the C runtime's getwch hands Alt+letter over as the
    bare letter. Falls back to msvcrt when stdin is not a console.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class KeyEvent(ctypes.Structure):
            _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD), ("vk", wintypes.WORD),
                        ("scan", wintypes.WORD), ("char", wintypes.WCHAR), ("state", wintypes.DWORD)]

        class Record(ctypes.Structure):
            _fields_ = [("type", wintypes.WORD), ("key", KeyEvent)]      # the union's largest member

        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = wintypes.HANDLE
        h = k.GetStdHandle(-10)
        n = wintypes.DWORD()
        if not k.GetNumberOfConsoleInputEvents(wintypes.HANDLE(h), ctypes.byref(n)):
            return _read_keys_msvcrt()
        out = []
        while n.value:
            recs = (Record * n.value)()
            got = wintypes.DWORD()
            if not k.ReadConsoleInputW(wintypes.HANDLE(h), recs, n.value, ctypes.byref(got)):
                break
            for r in recs[:got.value]:
                if r.type == 1 and r.key.down:       # KEY_EVENT, key going down
                    name = _key_name(r.key.vk, r.key.char, r.key.state)
                    if name:
                        out.append(name)
            if not k.GetNumberOfConsoleInputEvents(wintypes.HANDLE(h), ctypes.byref(n)):
                break
        return out
    except Exception:
        return _read_keys_msvcrt()


class _Ui:
    """State of the menu bar, the open menu and the open dialog; draws them over a _Canvas."""
    SAY_FOR = 4.0             # s a result stays on the status line
    FN = {"f1": "about", "f2": "limit", "f8": "faults"}       # function keys, as the nc key bar shows

    def __init__(self, data_dir, theme, can_quit=True, clock=time.monotonic):
        self.data_dir, self.theme, self.clock, self.can_quit = data_dir, theme, clock, can_quit
        # Items: (label, index of its hot letter, key shown at the right, action, status-line hint)
        system = [("About OpenJuice...", 0, "F1", "about", "What this screen is")]
        if can_quit:
            system += [None, ("Exit", 1, "Alt-X", "quit", "Leave the status screen")]
        charger = [("Set current limit...", 12, "F2", "limit", "Change the current limit"),
                   ("Clear fault log...", 6, "F8", "faults", "Clear the module's fault log")]
        themes, used = [], set()
        for n in THEME_ORDER:
            hot = next(i for i, c in enumerate(n) if c not in used)
            used.add(n[hot])
            themes.append((n, hot, "", "theme:" + n, "Switch to the %s theme" % n))
        self.menus = [("≡", -1, system), ("Charger", 0, charger), ("Theme", 0, themes)]
        self.menu = None          # index of the highlighted menu title
        self.opened = False       # whether its pull-down is showing
        self.item = 0
        self.dialog = None
        self.said, self.said_until = "", 0.0
        self.st, self.age = None, math.inf
        self.quit = False

    # -- state --
    @property
    def active(self):
        return self.menu is not None or self.dialog is not None

    def say(self, text):
        self.said, self.said_until = text, self.clock() + self.SAY_FOR

    def _close(self):
        self.menu, self.opened = None, False

    def _open(self, index, show=True):
        self.menu, self.opened = index % len(self.menus), show
        title, _, items = self.menus[self.menu]
        self.item = min(THEME_ORDER.index(self.theme), len(items) - 1) if title == "Theme" else 0

    def _move(self, step):
        items = self.menus[self.menu][2]
        while True:
            self.item = (self.item + step) % len(items)
            if items[self.item] is not None:
                return

    def key(self, k):
        """Handle one key name. True when it was used."""
        if self.dialog:
            return self._dialog_key(k)
        if self.menu is not None:
            return self._menu_key(k)
        if k in ("f10", "f9", "m"):
            self._open(1, show=False)                 # highlights the first named menu; Enter opens it
        elif k.startswith("alt+") and self._title(k[4:]) is not None:
            self._open(self._title(k[4:]))
        elif k == "alt+x" or k == "q":
            if not self.can_quit:
                return False
            self.run("quit")
        elif k in ("t", "f5"):
            self.run("theme:" + THEME_ORDER[(THEME_ORDER.index(self.theme) + 1) % len(THEME_ORDER)])
        elif k in self.FN:
            self.run(self.FN[k])
        elif k in ("l", "f"):
            self.run("limit" if k == "l" else "faults")
        else:
            return False
        return True

    def _title(self, letter):
        for i, (title, hot, _) in enumerate(self.menus):
            if hot >= 0 and title[hot].lower() == letter:
                return i
        return None

    def _menu_key(self, k):
        """A menu is modal: every key is used here, and letters mean this menu's own items."""
        items = self.menus[self.menu][2]
        if k in ("esc", "f10", "f9"):
            self._close()
        elif k in ("left", "right"):
            self._open(self.menu + (1 if k == "right" else -1), self.opened)
        elif k.startswith("alt+") and self._title(k[4:]) is not None:
            self._open(self._title(k[4:]))
        elif not self.opened:
            if k in ("enter", "down", "up"):
                self.opened = True
            elif len(k) == 1 and self._title(k) is not None:
                self._open(self._title(k))
        elif k in ("up", "down"):
            self._move(1 if k == "down" else -1)
        elif k in ("home", "end"):
            self.item = -1 if k == "home" else len(items)
            self._move(1 if k == "home" else -1)
        elif k == "enter":
            self.run(items[self.item][3])
        elif len(k) == 1:
            for it in items:
                if it and it[1] >= 0 and it[0][it[1]].lower() == k:
                    self.run(it[3])
                    break
        return True

    def _limits(self):
        try:
            top = max(J1772_MIN, min(HARD_MAX, int(self.st["telemetry"]["fields"].get("m", HARD_MAX))))
        except (ValueError, TypeError, KeyError):
            top = HARD_MAX
        now = Config(os.path.join(self.data_dir, "helper.json")).get()["target_amps"]
        return top, now

    def _info(self, title, lines, tone=""):
        self.dialog = dict(kind="info", title=title, lines=lines, focus=0, default=0, tone=tone)

    def run(self, action):
        self._close()
        if action == "quit":
            self.quit = True
        elif action.startswith("theme:"):
            self.theme = action[6:]
            save_theme(self.data_dir, self.theme)
        elif action == "about":
            self._info("About", ["OpenJuice status screen", "JuiceBox Gen 1 under local control",
                                 "Helper %s" % VERSION])
        elif self.st is None or self.age >= 30:
            self._info("Helper not running", ["The helper is not running,", "so nothing was sent."], "err")
        elif action == "limit":
            top, now = self._limits()
            self.dialog = dict(kind="input", title="Set current limit", top=top, now=now, tone="",
                               lines=["Limit in amps, %d to %d:" % (J1772_MIN, top)],
                               value=str(now), fresh=True, focus=0, default=0, error="")
        elif action == "faults":
            n = self.st["watchdog"].get("module_faults")
            self.dialog = dict(kind="confirm", title="Clear fault log", focus=1, default=1, do=("clear",),
                               tone="err",
                               lines=["Clear the charger's fault log (%s)?"
                                      % ("count unknown" if n is None else "%d of 8" % n),
                                      "It is copied to helper.log first, then",
                                      "permanently cleared on the charger."],
                               no="Fault log left as it is.")

    def _dialog_key(self, k):
        d = self.dialog
        if d["kind"] == "info":
            if k in ("enter", "esc", " ", "o"):
                self.dialog = None
            return True
        if k in ("left", "right", "tab", "shift+tab"):
            d["focus"] = 1 - d["focus"]
        elif k == "esc":
            self._answer(False)
        elif k in ("enter", " "):
            self._answer(d["focus"] == 0)
        elif d["kind"] == "confirm":
            if k in ("y", "n"):
                self._answer(k == "y")
        elif k in ("o", "c"):
            self._answer(k == "o")
        elif k == "backspace":
            d["value"], d["fresh"] = ("" if d["fresh"] else d["value"][:-1]), False
        elif k in ("up", "down"):
            v = int(d["value"] or d["now"]) + (1 if k == "up" else -1)
            d["value"], d["fresh"] = str(max(J1772_MIN, min(d["top"], v))), False
        elif len(k) == 1 and k.isdigit():
            d["value"] = k if d["fresh"] else (d["value"] + k)[:2]
            d["fresh"] = False
        return True

    def cancel(self):
        """The close box, or anything else that dismisses a dialog without an answer."""
        if self.dialog:
            if self.dialog["kind"] == "info":
                self.dialog = None
            else:
                self._answer(False)

    def _answer(self, yes):
        d, self.dialog = self.dialog, None
        if d["kind"] == "input":
            if not yes:
                self.say("Limit left at %d A." % d["now"])
                return
            amps = int(d["value"]) if d["value"] else 0
            if not J1772_MIN <= amps <= d["top"]:
                d["error"], d["fresh"] = "Enter %d to %d." % (J1772_MIN, d["top"]), True
                self.dialog = d
                return
            self.dialog = dict(kind="confirm", title="Set current limit", focus=1, default=1, tone="",
                               do=("target", amps),
                               lines=["Set the charger's current limit to %d A?" % amps,
                                      "It is %d A now." % d["now"]],
                               no="Limit left at %d A." % d["now"])
            return
        if not yes:
            self.say(d["no"])
            return
        path = os.path.join(self.data_dir, "helper.json")
        try:
            if d["do"][0] == "target":
                Config.update(path, target_amps=d["do"][1])
                self.say("Asked the helper for a %d A limit." % d["do"][1])
            else:
                Config.update(path, clear_faults=wall())
                self.say("Asked the helper to clear the fault log.")
        except (OSError, ValueError) as e:
            self.say("Could not write helper.json: %s" % e)

    # -- drawing --
    def _status(self, cv, g, S, bar):
        W, y = cv.w, cv.h - 1
        cv.fill(0, y, W, 1, " ", *bar)
        note = ""                                   # the highlighted menu item's hint
        if self.menu is not None and self.opened and self.menus[self.menu][2][self.item]:
            note = self.menus[self.menu][2][self.item][4]
        elif self.said and self.clock() < self.said_until:
            cv.put(1, y, _clip(self.said, W - 2))    # a result takes the whole line for a few seconds
            return
        if S["status"] == "fn":                      # ten numbered cells; unbound keys stay blank
            if note:
                cv.put(1, y, _clip(note, W - 2))
                return
            labels = {1: "About", 2: "Limit", 5: "Theme", 8: "Faults", 9: "Menu", 10: "Menu"}
            cell = W // 10
            for i in range(10):
                cv.put(i * cell, y, "%2d" % (i + 1), 37, 40)
                cv.put(i * cell + 2, y, ("%-*s" % (cell - 2, labels.get(i + 1, "")))[:cell - 2], 30, 46)
            cv.fill(10 * cell, y, W - 10 * cell, 1, " ", 30, 46)
            return
        keys = [("F10", "Menu"), ("L", "Limit"), ("F", "Faults"), ("T", "Theme")]
        if self.can_quit:
            keys.append(("Alt-X", "Exit"))
        x = 1
        for k, text in keys:
            if S["status"] == "kv":                  # Key=Action
                cv.put(x, y, "%s=%s" % (k.replace("-", "+"), text))
                x += len(k) + len(text) + 3
            else:
                cv.put(x, y, k, *S["barhot"])
                cv.put(x + len(k) + 1, y, text)
                x += len(k) + len(text) + 3
        if note:
            cv.put(x, y, g["sep"] + " " + _clip(note, W - x - 3))

    def draw(self, cv, g):
        T = THEMES.get(self.theme, THEMES["turbo"])
        S = _style(self.theme)
        bar = T["bar"]
        W, H = cv.w, cv.h
        cv.fill(0, 0, max(0, W - 21), 1, " ", *bar)             # menu bar, left of the clock
        x, xs = 1, []
        for i, (title, hot, _) in enumerate(self.menus):
            shown = g["sys"] if hot < 0 else title
            xs.append(x)
            if i == self.menu:
                cv.put(x, 0, " %s " % shown, *S["sel"])
                if hot >= 0:
                    cv.put(x + 1 + hot, 0, shown[hot], *S["selhot"])
            else:
                cv.put(x + 1, 0, shown)
                if hot >= 0:
                    cv.put(x + 1 + hot, 0, shown[hot], *S["barhot"])
            x += len(shown) + 2
        self._status(cv, g, S, bar)

        if self.menu is not None and self.opened:
            items = self.menus[self.menu][2]
            mark = self.menus[self.menu][0] == "Theme"
            inner = max(len(it[0]) + (len(it[2]) + 2 if it[2] else 0) for it in items if it) + 2 + (2 if mark else 0)
            mx, my, mw, mh = xs[self.menu] - 1, 1, inner + 4, len(items) + 2     # a blank column outside the frame
            cv.shade(mx + 2, my + 1, mw, mh, *T["shadow"])
            cv.fill(mx, my, mw, mh, " ", *S["menu"])
            cv.put(mx + 1, my, g["stl"] + g["sh"] * inner + g["str"])
            cv.put(mx + 1, my + mh - 1, g["sbl"] + g["sh"] * inner + g["sbr"])
            for i, it in enumerate(items):
                y = my + 1 + i
                if it is None:
                    cv.put(mx + 1, y, g["stee"] + g["sh"] * inner + g["etee"])
                    continue
                cv.put(mx + 1, y, g["sv"])
                cv.put(mx + mw - 2, y, g["sv"])
                lead = (((g["dot"] if it[0] == self.theme else " ") + " ") if mark else "")
                row = " " + lead + it[0]
                row += " " * (inner - len(row))
                if it[2]:
                    row = row[:inner - 1 - len(it[2])] + it[2] + " "
                chosen = i == self.item
                cv.put(mx + 2, y, row, *(S["sel"] if chosen else S["menu"]))
                if it[1] >= 0:
                    cv.put(mx + 3 + len(lead) + it[1], y, it[0][it[1]], *(S["selhot"] if chosen else S["menuhot"]))

        d = self.dialog
        if d:
            err = d["tone"] == "err" and S["err"]
            body = S["err"] if err else S["dlg"]
            frame = S["err"] if err else S["frame"]
            btn, btnhot = (body, S["errhot"]) if err else (S["btn"], S["btnhot"])
            focus, focushot = (S["errfocus"], S["errfocus"]) if err else (S["focus"], S["focushot"])
            buttons = {"confirm": [("Yes", 0), ("No", 0)], "input": [("OK", 0), ("Cancel", 0)],
                       "info": [("OK", 0)]}[d["kind"]]
            tv = S["buttons"] == "tv"
            lines = list(d["lines"])
            dw = max([len(s) for s in lines] + [len(d["title"]) + 4, 30]) + 6
            dh = len(lines) + (7 if d["kind"] == "input" else 5) + (1 if tv else 0)
            dx, dy = (W - dw) // 2, max(2, (H - dh) // 2 - 2)
            cv.window(dx, dy, dw, dh, d["title"], body, T["shadow"], g, frame=frame)
            if S["closebox"]:
                cv.put(dx + 2, dy, "[" + g["box"] + "]", *frame)
                cv.put(dx + 3, dy, g["box"], *S["icon"])
            for i, s in enumerate(lines):
                cv.put(dx + 3, dy + 2 + i, s, *body)
            y = dy + 2 + len(lines)
            if d["kind"] == "input":
                cv.put(dx + 3, y, " " * 6, *S["input"])
                cv.put(dx + 4, y, d["value"], *(S["inputsel"] if d["fresh"] else S["input"]))
                if not d["fresh"]:                  # a block cursor after the typed text
                    cv.put(dx + 4 + len(d["value"]), y, " ", S["input"][1] - 10, S["input"][0] + 10)
                cv.put(dx + 11, y, _clip(d["error"], dw - 14), *body)
                y += 2
            else:
                y += 1
            shown = []
            for i, (label, hot) in enumerate(buttons):
                if tv:
                    text = label.center(10)
                elif S["buttons"] == "far":         # FAR marks the default button with braces
                    text = ("{ %s }" if i == d["default"] else "[ %s ]") % label
                else:
                    text = "< %s >" % label
                shown.append((text, text.index(label) + hot))
            x = dx + (dw - sum(len(t) for t, _ in shown) - 2 * (len(shown) - 1)) // 2
            for i, (text, hot) in enumerate(shown):
                on = i == d["focus"]
                cv.put(x, y, text, *(focus if on else btn))
                cv.put(x + hot, y, text[hot], *(focushot if on else btnhot))
                if tv:                              # half-block shadow to the right and below
                    cv.put(x + len(text), y, g["lower"], 30, body[1])
                    cv.put(x + 1, y + 1, g["upper"] * len(text), 30, body[1])
                elif S["buttons"] == "cua" and i == d["default"] and not on:
                    cv.put(x, y, "<", *S["btnhot"])        # the default button's brackets are bright
                    cv.put(x + len(text) - 1, y, ">", *S["btnhot"])
                x += len(text) + 2


def _watch(args, color, theme):
    import shutil
    _enable_vt()
    glyphs = _ASC if (args.ascii or not color) else _UNI
    ui = _Ui(args.data_dir, theme)
    hist, hist_at = None, -math.inf
    sys.stdout.write("\x1b[?1049h\x1b[?25l")               # alternate screen, hide cursor
    try:
        while not ui.quit:
            st, age = read_status(args.data_dir)
            ui.st, ui.age = st, age
            size = shutil.get_terminal_size((80, 30))
            if st is None:
                frame = "\x1b[2Jwaiting for the helper to write status..."
            else:
                if time.monotonic() - hist_at > 5:          # the charts need not be re-read on every key
                    hist, hist_at = load_history(args.data_dir), time.monotonic()
                cv = _compose(st, age, size[1], glyphs, size, "", ui.theme, hist)
                ui.draw(cv, glyphs)
                frame = cv.render(color)
            sys.stdout.write("\x1b[H" + frame)
            sys.stdout.flush()
            deadline = time.monotonic() + args.watch
            used = False
            while time.monotonic() < deadline and not used:
                for k in _read_keys():
                    used = ui.key(k) or used
                if not used:
                    time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")     # restore cursor and screen
        sys.stdout.flush()
    return 0


def cmd_status(args):
    color = _use_color(args)
    try:
        sys.stdout.reconfigure(encoding="utf-8" if color else None, errors="replace")
    except Exception:
        pass
    theme = args.theme or load_theme(args.data_dir)
    if args.theme:
        save_theme(args.data_dir, theme)                   # an explicit choice becomes the default
    if getattr(args, "watch", 0):
        return _watch(args, color, theme)
    st, age = read_status(args.data_dir)
    if st is None:
        print("no status file in %s; the helper has not run" % args.data_dir)
        return 1
    if color:
        _enable_vt()
    print(_dashboard(st, age, args.events, color, ascii_only=args.ascii, theme=theme,
                     hist=load_history(args.data_dir)))
    return 0 if age < 30 else 1


def _wait_for(data_dir, pred, seconds):
    end = time.time() + seconds
    while time.time() < end:
        st, age = read_status(data_dir)
        if st is not None and age < 30 and pred(st):
            return st
        time.sleep(3)
    return None


def cmd_target(args):
    path = os.path.join(args.data_dir, "helper.json")
    Config.update(path, target_amps=args.amps)
    print("target set to %d A in %s" % (args.amps, path))
    st, age = read_status(args.data_dir)
    if st is None or age >= 30:
        print("the helper is not running; it will apply the target when it starts")
        return 0
    print("waiting for the charger to report it (up to 90 s)...")
    ok = _wait_for(args.data_dir, lambda s: s["telemetry"]["fields"].get("M") == str(args.amps), 90)
    print("confirmed: limit %d A" % args.amps if ok else "not confirmed yet; check `status`")
    return 0 if ok else 1


def cmd_release(args):
    path = os.path.join(args.data_dir, "helper.json")
    Config.update(path, mode="released")
    print("mode set to released in %s" % path)
    st, age = read_status(args.data_dir)
    if st is not None and age < 30:
        print("the running helper will reboot the charger back to the cloud (up to 60 s)...")
        ok = _wait_for(args.data_dir, lambda s: s["watchdog"]["state"] == "released", 60)
        print("done: %s" % ok["watchdog"]["detail"] if ok else "not confirmed; check `status`")
        return 0 if ok else 1
    cfg = Config(path).get()
    m = Module(lambda: cfg["charger_host"])
    r = m.command("get wlan.dhcp.enabled")
    if r.kind == OK and r.text == "1":
        print("the charger is already on DHCP and the cloud; nothing to do")
        return 0
    r = m.command("reboot")
    print("reboot sent to %s (reply: %s); the charger returns on DHCP and the cloud in about 45 s"
          % (cfg["charger_host"], r.kind))
    return 0


def cmd_attach(args):
    path = os.path.join(args.data_dir, "helper.json")
    Config.update(path, mode="local")
    print("mode set to local in %s" % path)
    st, age = read_status(args.data_dir)
    if st is None or age >= 30:
        print("the helper is not running; start the scheduled task to reattach")
        return 0
    print("waiting for telemetry (up to 3 min)...")
    ok = _wait_for(args.data_dir, lambda s: s["watchdog"]["state"] == "attached", 180)
    print("attached" if ok else "not attached yet; check `status`")
    return 0 if ok else 1


def cmd_clear_faults(args):
    st, age = read_status(args.data_dir)
    if st is None or age >= 30:
        print("the helper is not running; nothing was sent")
        return 1
    n = st["watchdog"].get("module_faults")
    if not args.yes:
        ask = "Clear the charger's fault log (%s of 8)? [y/N] " % ("?" if n is None else n)
        if input(ask).strip().lower() not in ("y", "yes"):
            print("left as it is")
            return 0
    path = os.path.join(args.data_dir, "helper.json")
    Config.update(path, clear_faults=wall())
    print("asked the running helper to clear it (up to 30 s)...")
    end = time.time() + 30                      # the helper removes the request once it has handled it
    while time.time() < end and "clear_faults" in Config(path).get():
        time.sleep(1)
    if "clear_faults" in Config(path).get():
        Config.drop(path, "clear_faults")
        print("the running helper did not pick the request up (an older copy?); request withdrawn")
        return 1
    ok = _wait_for(args.data_dir, lambda s: s["watchdog"].get("module_faults") == 0, 20)
    print("cleared: 0 of 8" if ok else "not cleared; see helper.log")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=default_data_dir(),
                    help="config, logs and status (default: %%LOCALAPPDATA%%\\OpenJuice)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the service loop")
    p = sub.add_parser("status", help="show what the helper last saw and did")
    p.add_argument("--events", type=int, default=8)
    p.add_argument("--ascii", action="store_true", help="ASCII borders and meters instead of box-drawing")
    p.add_argument("--theme", choices=THEME_ORDER,
                   help="colour theme; remembered as the default (T cycles themes in --watch)")
    p.add_argument("--watch", nargs="?", type=float, const=2.0, default=0.0, metavar="SECONDS",
                   help="live full-screen dashboard, refreshed every SECONDS (default 2); Ctrl-C to quit")
    p.add_argument("--color", action="store_true", help="force ANSI color even when not a TTY")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p = sub.add_parser("target", help="change the current limit the helper keeps")
    p.add_argument("amps", type=int, choices=range(J1772_MIN, HARD_MAX + 1), metavar="AMPS")
    sub.add_parser("release", help="hand the charger back to the cloud and stop reattaching")
    sub.add_parser("attach", help="resume local control")
    p = sub.add_parser("clear-faults", help="clear the module's fault log (asks first)")
    p.add_argument("--yes", action="store_true", help="do not ask")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        try:
            return run(args)
        except Exception:
            log.exception("helper crashed")
            raise
    return {"status": cmd_status, "target": cmd_target, "release": cmd_release,
            "attach": cmd_attach, "clear-faults": cmd_clear_faults}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
