#!/usr/bin/env python3
"""Tests for juicebox_helper.py. No charger needed: the module, the clock and the network
are faked or run on loopback.

  python -m unittest tools/juicebox/test_juicebox_helper.py -v
"""
import http.server
import logging
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import juicebox_helper as h  # noqa: E402

logging.disable(logging.CRITICAL)

PC = "192.168.1.74"


def ok(text):
    return h.Reply(h.OK, 0, text)


EMPTY = h.Reply(h.EMPTY, None, "RemoteDisconnected")
DOWN = h.Reply(h.DOWN, None, "ConnectionRefusedError")
FAULTS3 = ok("0: Watchdog Exception, A\r\n1: Watchdog Exception, B\r\n2: Watchdog Exception, C")
STATIC_OK = {
    "get wlan.static.ip": ok("192.168.1.63"),
    "get wlan.static.gateway": ok("192.168.1.1"),
    "get wlan.static.dns": ok(PC),
    "get wlan.static.netmask": ok("255.255.255.0"),
    "faults_print": FAULTS3,
    "set wlan.dhcp.enabled 0": ok("Set OK"),
    "network_restart": ok("Success"),
}


class Clock:
    def __init__(self):
        self.t = 10000.0

    def __call__(self):
        return self.t


class FakeModule:
    """Scripted replies per command. Enforces the same allowlist as the real client."""

    def __init__(self, replies=None, default=DOWN):
        self.replies = dict(replies or {})
        self.default = default
        self.calls = []

    def command(self, cmd, timeout=None):
        if not any(p.fullmatch(cmd) for p in h.ALLOWED_COMMANDS):
            raise ValueError("refusing module command %r" % cmd)
        self.calls.append(cmd)
        return self.replies.get(cmd, self.default)

    def count(self, cmd):
        return self.calls.count(cmd)


class WatchdogCase(unittest.TestCase):
    def make(self, replies=None, default=DOWN, **cfg):
        self.clock = Clock()
        self.shared = h.Shared(clock=self.clock)
        self.m = FakeModule(replies, default)
        self.cfg = dict(h.DEFAULTS, **cfg)
        self.wd = h.Watchdog(self.m, self.shared, lambda: self.cfg, clock=self.clock,
                             our_ip=lambda host: PC)

    def run_for(self, seconds, telemetry=False, step=2.0):
        end = self.clock.t + seconds
        while self.clock.t < end:
            if telemetry:
                self.shared.frame_t = self.clock.t
            self.wd.tick()
            self.clock.t += step

    def assertNeverUnsafe(self):
        for c in self.m.calls:
            self.assertNotIn("save", c)
            self.assertNotIn("zap", c)
            self.assertFalse(c.startswith("set ") and c != "set wlan.dhcp.enabled 0", c)


class TestWatchdog(WatchdogCase):
    def test_flowing_telemetry_never_probes(self):
        self.make(STATIC_OK)
        self.run_for(3600, telemetry=True)
        self.assertEqual(self.m.calls, ["faults_print"])      # one read for the status page
        self.assertEqual(self.wd.state, "attached")
        self.assertEqual(self.wd.faults, 3)

    def test_startup_grace_before_first_probe(self):
        self.make()
        self.run_for(58)
        self.assertEqual(self.m.calls, [])
        self.run_for(10)
        self.assertEqual(self.m.calls, ["get wlan.dhcp.enabled"])

    def test_rebooted_module_is_reattached(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1")}))
        self.run_for(70)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 1)
        self.assertEqual(self.m.count("network_restart"), 1)
        self.assertLess(self.m.calls.index("get wlan.static.dns"),
                        self.m.calls.index("set wlan.dhcp.enabled 0"))
        self.assertEqual(self.wd.state, "reattaching")
        self.assertNeverUnsafe()

    def test_reattach_then_telemetry_means_attached(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1")}))
        self.run_for(70)
        self.run_for(30, telemetry=True)
        self.assertEqual(self.wd.state, "attached")

    def test_changed_pc_address_blocks_reattach(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1"),
                                     "get wlan.static.dns": ok("192.168.1.99")}))
        self.run_for(70)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 0)
        self.assertEqual(self.wd.state, "blocked")
        self.assertIn("DHCP reservation", self.wd.detail)
        probes = self.m.count("get wlan.dhcp.enabled")
        self.run_for(3000)                                     # blocked: no probing for an hour
        self.assertEqual(self.m.count("get wlan.dhcp.enabled"), probes)
        self.run_for(700)
        self.assertGreater(self.m.count("get wlan.dhcp.enabled"), probes)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 0)

    def test_config_change_lifts_block(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1"),
                                     "get wlan.static.gateway": ok(PC)}))
        self.run_for(70)
        self.assertEqual(self.wd.state, "blocked")
        self.m.replies["get wlan.static.gateway"] = ok("192.168.1.1")
        self.cfg["upstream_dns"] = "192.168.1.2"               # any edit to helper.json
        self.run_for(40)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 1)

    def test_gateway_pointing_at_pc_blocks(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1"),
                                     "get wlan.static.gateway": ok(PC)}))
        self.run_for(70)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 0)
        self.assertIn("wlan.static.gateway", self.wd.detail)

    def test_fault_guard_blocks_reattach(self):
        six = ok("\r\n".join("%d: Watchdog Exception" % i for i in range(6)))
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1"), "faults_print": six}))
        self.run_for(70)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 0)
        self.assertIn("Safe Mode", self.wd.detail)

    def test_hang_rebooted_after_three_empty_probes(self):
        self.make(default=EMPTY)
        self.run_for(115)
        self.assertEqual(self.m.count("reboot"), 0)
        self.assertEqual(self.m.count("get wlan.dhcp.enabled"), 2)
        self.run_for(40)
        self.assertEqual(self.m.count("reboot"), 1)
        before = self.m.calls[:self.m.calls.index("reboot")]
        self.assertEqual(before, ["get wlan.dhcp.enabled"] * 3)
        self.assertEqual(self.wd.state, "unresponsive")         # fast probes after the reboot

    def test_hang_recovery_reattaches_quickly(self):
        self.make(default=EMPTY)
        self.run_for(125)
        self.assertEqual(self.m.count("reboot"), 1)
        rebooted_at = self.clock.t
        self.m.default = DOWN                                  # module restarting
        self.run_for(35)
        self.m.replies = dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1")})  # back on DHCP
        while self.m.count("network_restart") == 0 and self.clock.t < rebooted_at + 300:
            self.run_for(2)
        self.assertEqual(self.m.count("network_restart"), 1)
        self.assertLess(self.clock.t - rebooted_at, 50)        # fast probing, not the 60 s gap

    def test_reboots_are_rate_limited(self):
        self.make(default=EMPTY)
        self.run_for(86400, step=5)
        self.assertLessEqual(self.m.count("reboot"), h.Watchdog.REBOOTS_PER_DAY)
        self.assertEqual(self.wd.state, "gave_up")
        self.run_for(86400, step=5)                            # a day later it may try again
        self.assertLessEqual(self.m.count("reboot"), 2 * h.Watchdog.REBOOTS_PER_DAY)

    def test_silent_module_rebooted_after_fifteen_minutes(self):
        self.make({"get wlan.dhcp.enabled": ok("0")})
        self.run_for(14 * 60)
        self.assertEqual(self.m.count("reboot"), 0)
        self.assertEqual(self.wd.state, "silent")
        self.run_for(2 * 60)
        self.assertEqual(self.m.count("reboot"), 1)

    def test_unreachable_module_is_left_alone(self):
        self.make(default=DOWN)
        self.run_for(4 * 3600, step=5)
        self.assertEqual(self.m.count("reboot"), 0)
        self.assertEqual(self.m.count("set wlan.dhcp.enabled 0"), 0)
        self.assertEqual(self.wd.state, "unreachable")

    def test_released_mode_hands_back_once(self):
        self.make(mode="released")
        self.run_for(200, telemetry=True)
        self.assertEqual(self.m.count("reboot"), 1)
        self.run_for(200, telemetry=True)                      # reboot did not take: retry at 300 s
        self.assertEqual(self.m.count("reboot"), 2)

    def test_released_mode_never_reattaches(self):
        self.make(dict(STATIC_OK, **{"get wlan.dhcp.enabled": ok("1")}), mode="released")
        self.run_for(3600)
        self.assertEqual(self.m.calls, [])
        self.assertEqual(self.wd.state, "released")


class TestLimitKeeper(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.notes = []
        self.k = h.LimitKeeper(lambda msg, level=None: self.notes.append(msg), clock=self.clock)

    @staticmethod
    def frame(M, s="0681", m="40"):
        return {"M": str(M), "s": s, "m": m, "S": "1"}

    def test_corrects_drift_once_and_confirms(self):
        cmd = self.k.on_frame(self.frame(40), 26, True)
        self.assertIsNotNone(cmd)
        self.assertIn("A26M26", cmd)
        self.assertIn("S682", cmd)
        self.assertIsNone(self.k.on_frame(self.frame(26, s="0682"), 26, True))
        self.assertEqual(self.k.shot.state, "done")
        for _ in range(50):
            self.assertIsNone(self.k.on_frame(self.frame(26, s="0682"), 26, True))
        self.assertEqual(self.k.corrections_24h(), 1)

    def test_nothing_sent_at_target_or_when_disabled(self):
        self.assertIsNone(self.k.on_frame(self.frame(26), 26, True))
        self.assertIsNone(self.k.on_frame(self.frame(40), 26, False))

    def test_refuses_target_above_circuit_rating(self):
        self.assertIsNone(self.k.on_frame(self.frame(16, m="20"), 26, True))

    def test_spacing_and_daily_cap(self):
        sent = 0
        for i in range(2000):                                  # cloud keeps pushing 40 A back
            self.clock.t += 9
            cmd = self.k.on_frame(self.frame(40, s="%04d" % (i % 9000)), 26, True)
            sent += cmd is not None
        self.assertLessEqual(self.k.corrections_24h(), h.LimitKeeper.DAILY_CAP)
        self.assertLessEqual(sent, h.LimitKeeper.DAILY_CAP * 3)   # up to 3 attempts each

    def test_new_target_is_sent_immediately(self):
        self.k.on_frame(self.frame(40), 26, True)
        self.k.on_frame(self.frame(26, s="0682"), 26, True)
        self.clock.t += 5
        cmd = self.k.on_frame(self.frame(26, s="0682"), 24, True)
        self.assertIn("A24M24", cmd)


class TestModuleClient(unittest.TestCase):
    def test_refuses_unsafe_commands(self):
        m = h.Module(lambda: "127.0.0.1", port=9)
        for bad in ("save", "set wlan.static.dns 1.2.3.4", "set zap.auto_run 0",
                    "set wlan.dhcp.enabled 1", "factory_reset", "get wlan.dhcp.enabled; save",
                    "reboot\nsave"):
            with self.assertRaises(ValueError, msg=bad):
                m.command(bad)

    def _serve(self, handler_fn):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        port = srv.getsockname()[1]

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                handler_fn(c)

        threading.Thread(target=loop, daemon=True).start()
        self.addCleanup(srv.close)
        return port

    def test_json_reply_is_ok(self):
        def reply(c):
            c.recv(1024)
            body = b'{"id":1,"code":0,"flags":0,"response":"1\\r\\n"}'
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            c.close()
        m = h.Module(lambda: "127.0.0.1", port=self._serve(reply))
        m.SPACING = 0
        self.assertEqual(m.command("get wlan.dhcp.enabled"), h.Reply(h.OK, 0, "1"))

    def test_accept_then_close_is_empty(self):
        def hang(c):                                           # issue #1: accepted, 0 bytes
            c.recv(1024)
            time.sleep(0.2)
            c.close()
        m = h.Module(lambda: "127.0.0.1", port=self._serve(hang))
        m.SPACING = 0
        self.assertEqual(m.command("get wlan.dhcp.enabled").kind, h.EMPTY)

    def test_refused_is_down(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                              # nothing listening now
        m = h.Module(lambda: "127.0.0.1", port=port, timeout=2)
        m.SPACING = 0
        self.assertEqual(m.command("get wlan.dhcp.enabled").kind, h.DOWN)


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestSockets(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)
        self.shared = h.Shared()
        self.cfg = dict(h.DEFAULTS)

    def test_resolver_hijacks_and_ignores_strangers(self):
        port = free_udp_port()
        threading.Thread(target=h.resolver_loop, args=(self.shared, lambda: self.cfg, self.stop),
                         kwargs={"port": port}, daemon=True).start()
        time.sleep(0.3)
        self.assertTrue(h.resolver_selftest(port))            # loopback is allowed
        stranger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(stranger.close)
        try:
            stranger.bind(("127.0.0.2", 0))
        except OSError:
            self.skipTest("cannot bind 127.0.0.2 here")
        stranger.settimeout(1.5)
        q = struct.pack("!HHHHHH", 1, 0x0100, 1, 0, 0, 0) + b"\x04jbv1\x0bemotorwerks\x03com\x00" \
            + struct.pack("!HH", 1, 1)
        stranger.sendto(q, ("127.0.0.1", port))
        with self.assertRaises(socket.timeout):
            stranger.recvfrom(512)                             # not the charger: no answer
        self.assertEqual(self.shared.dns_ignored, 1)

    def test_listener_logs_and_corrects_limit(self):
        port = free_udp_port()
        tmp = tempfile.mkdtemp()
        tlog = h.TelemetryLog(os.path.join(tmp, "telemetry.log"))
        keeper = h.LimitKeeper(self.shared.note)
        threading.Thread(target=h.listener_loop,
                         args=(self.shared, lambda: self.cfg, keeper, tlog, self.stop),
                         kwargs={"port": port}, daemon=True).start()
        time.sleep(0.3)
        charger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        charger.settimeout(2)
        self.addCleanup(charger.close)
        frame = ("0817081001070449032218248303:v07,s0681,u28588,V2408,L0028676564,S1,T15,"
                 "M40,m40,t09,i62,e0000,f5998,X0,Y0!YEP:")
        charger.sendto(frame.encode(), ("127.0.0.1", port))
        cmd = charger.recvfrom(512)[0].decode()
        self.assertRegex(cmd, r"^CMD\d{5}A26M26C006S682!\w+\$$")
        charger.sendto(frame.replace("s0681", "s0682").replace("M40", "M26").encode(),
                       ("127.0.0.1", port))
        with self.assertRaises(socket.timeout):
            charger.recvfrom(512)                              # acknowledged: nothing more
        self.assertEqual(self.shared.frames, 2)
        self.assertEqual(self.shared.fields["M"], "26")
        with open(os.path.join(tmp, "telemetry.log"), encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 2)

    def test_listener_survives_a_malformed_frame(self):
        port = free_udp_port()
        tmp = tempfile.mkdtemp()
        tlog = h.TelemetryLog(os.path.join(tmp, "telemetry.log"))
        keeper = h.LimitKeeper(self.shared.note)
        threading.Thread(target=h.listener_loop,
                         args=(self.shared, lambda: self.cfg, keeper, tlog, self.stop),
                         kwargs={"port": port}, daemon=True).start()
        time.sleep(0.3)
        charger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        charger.settimeout(2)
        self.addCleanup(charger.close)
        bad = ("0817081001070449032218248303:v07,s0681,u28588,V2408,L0028676564,S1,T15,"
               "M40u,m40,t09,i62,e0000,f5998,X0,Y0!YEP:")     # M value breaks int(); used to kill the thread
        good = bad.replace("M40u", "M40")
        charger.sendto(bad.encode(), ("127.0.0.1", port))
        charger.sendto(good.encode(), ("127.0.0.1", port))
        cmd = charger.recvfrom(512)[0].decode()               # reply to the good frame
        self.assertRegex(cmd, r"^CMD\d{5}A26M26C006S682!\w+\$$")  # listener survived and still corrects
        self.assertEqual(self.shared.frames, 2)               # both frames counted, neither crashed it

    def test_listener_notes_a_finished_charge(self):
        port = free_udp_port()
        tlog = h.TelemetryLog(os.path.join(tempfile.mkdtemp(), "telemetry.log"))
        watch = h.ChargeWatch()
        watch.CONFIRM = 0.2                                    # seconds of idle that confirm it
        threading.Thread(target=h.listener_loop,
                         args=(self.shared, lambda: self.cfg, h.LimitKeeper(self.shared.note), tlog, self.stop),
                         kwargs={"port": port, "watch": watch}, daemon=True).start()
        time.sleep(0.3)
        charger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(charger.close)
        frame = "0817081001070449032218248303:v07,s0001,u1,V2400,L%010d,S%s,T15,M26,m40%s!XYZ:"
        for state, extra in (("2", ",E004200,A0257"), ("1", ""), ("1", ""), ("1", "")):
            charger.sendto((frame % (5200, state, extra)).encode(), ("127.0.0.1", port))
            time.sleep(0.25)
        self.assertEqual(self.shared.last_complete["wh"], 4200)       # the charger's own session counter
        notes = [e["msg"] for e in self.shared.events if "charge complete" in e["msg"]]
        self.assertEqual(len(notes), 1)
        self.assertIn("4.2 kWh delivered", notes[0])


class TestConfig(unittest.TestCase):
    def test_update_validates_and_reloads(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "helper.json")
        c = h.Config(path)
        self.assertEqual(c.get()["target_amps"], 26)
        h.Config.update(path, target_amps=24)
        os.utime(path, (time.time() + 5, time.time() + 5))    # coarse mtime on some filesystems
        self.assertEqual(c.get()["target_amps"], 24)
        with self.assertRaises(ValueError):
            h.Config.update(path, target_amps=48)
        with self.assertRaises(ValueError):
            h.Config.update(path, mode="cloud")


class TestResolverSelftest(unittest.TestCase):
    """The loopback self-test must tolerate a briefly-busy (single-threaded) resolver by
    retrying, yet still fail for a genuinely dead one."""

    def _responder(self, answer_on):
        """UDP loopback stand-in for the resolver: ignores the first answer_on-1 probes
        (as if blocked forwarding), then answers the next one like the real resolver."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(5.0)
        port = s.getsockname()[1]
        self.addCleanup(s.close)

        def serve():
            seen = 0
            while True:
                try:
                    data, addr = s.recvfrom(2048)
                except OSError:
                    return
                seen += 1
                if seen < answer_on:
                    continue                       # "busy": drop this probe
                try:
                    _, _, qend = h.parse_question(data)
                    s.sendto(h.build_a_response(data, qend, PC), addr)
                except OSError:
                    pass
                return

        threading.Thread(target=serve, daemon=True).start()
        return port

    def test_passes_on_the_first_try(self):
        self.assertTrue(h.resolver_selftest(port=self._responder(1), attempts=3, timeout=0.5))

    def test_passes_on_a_retry_when_resolver_is_busy(self):
        self.assertTrue(h.resolver_selftest(port=self._responder(2), attempts=3, timeout=0.5))

    def test_fails_when_resolver_never_answers(self):
        self.assertFalse(h.resolver_selftest(port=self._responder(99), attempts=3, timeout=0.2))

    def test_fails_when_nothing_is_listening(self):
        self.assertFalse(h.resolver_selftest(port=free_udp_port(), attempts=3, timeout=0.2))


class TestStatusScreen(unittest.TestCase):
    """The status TUI: plain ASCII when colour is off, themed when on, never crashing on gaps."""

    def snapshot(self, **over):
        st = {"pid": 1, "started": "2026-01-01T00:00:00", "mode": "local", "target_amps": 26,
              "watchdog": {"state": "attached", "detail": "telemetry arriving",
                           "since": "2026-01-01T00:00:05", "reboots_24h": 0, "module_faults": 3},
              "telemetry": {"last": "2026-01-01T00:10:00", "age_s": 2, "frames": 9,
                            "from": "192.168.1.63:5000",
                            "fields": {"S": "2", "A": "0257", "M": "26", "m": "40", "V": "2361",
                                       "T": "20", "E": "012785", "L": "0029163065"}},
              "resolver": {"last_hijack": "2026-01-01T00:09:00", "hijacks": 4},
              "beacon": {"ip": "192.168.1.63", "rssi": -71, "mac": "AA:BB", "t": "2026-01-01T00:09:30"},
              "limit": {"outcome": None, "corrections_24h": 0},
              "events": [{"t": "2026-01-01T00:00:05", "msg": "attached: telemetry arriving " + "x" * 90}]}
        st.update(over)
        return st

    def test_plain_is_ascii_and_fixed_height(self):
        text = h._dashboard(self.snapshot(), 2, 8, color=False)
        self.assertNotIn("\x1b", text)
        text.encode("ascii")                                   # no box-drawing when colour is off
        self.assertEqual(len(text.split("\n")), 32)
        for needle in ("CHARGING", "25.7 A", "3/8", "RUNNING", "12.785 kWh", "-71 dBm"):
            self.assertIn(needle, text)

    def test_themed_fills_every_cell(self):
        text = h._dashboard(self.snapshot(), 2, 8, color=True, size=(100, 40))
        lines = text.split("\n")
        self.assertEqual(len(lines), 40)
        self.assertTrue(all(ln.startswith("\x1b[") and ln.endswith("\x1b[0m") for ln in lines))

    def test_gaps_do_not_crash(self):
        st = self.snapshot(beacon=None, events=[])
        st["watchdog"]["module_faults"] = None
        st["telemetry"] = {"last": None, "age_s": None, "frames": 0, "from": None, "fields": {}}
        self.assertIn("no telemetry", h._dashboard(st, 99, 8))
        self.assertIn("STOPPED", h._dashboard(st, 99, 8))

    def test_history_feeds_the_charts(self):
        import datetime
        tmp = tempfile.mkdtemp()
        now = datetime.datetime.now().replace(second=5, microsecond=0)
        yesterday = now - datetime.timedelta(days=1)
        frame = "%s\t192.168.1.63\t0817:v07,s0001,V2400,L%010d,S2,M26,m40,A%04d!XYZ:\n"
        with open(os.path.join(tmp, "telemetry.log"), "w", encoding="utf-8", newline="\n") as f:
            f.write(frame % (yesterday.isoformat(), 1000000, 100))
            f.write(frame % (yesterday.replace(second=30).isoformat(), 1004000, 257))
            f.write(frame % (now.isoformat(), 1010000, 317))
        hist = h.load_history(tmp)
        self.assertEqual(hist["amps"][now.strftime("%Y-%m-%dT%H:%M")], 31.7)
        self.assertEqual(hist["amps"][yesterday.strftime("%Y-%m-%dT%H:%M")], 25.7)   # peak of the minute
        self.assertEqual(len(hist["days"]), 7)
        self.assertAlmostEqual(hist["days"][-2][1], 10.0)          # yesterday's first frame to today's first
        self.assertAlmostEqual(hist["days"][-1][1], 0.0)           # today: nothing after its first frame
        text = h._dashboard(self.snapshot(), 2, 8, hist=hist)
        self.assertIn("Energy per day", text)
        self.assertIn("#", text.split("Current per minute")[1])        # a column was drawn
        self.assertIsNone(h.load_history(os.path.join(tmp, "missing")))

    def test_finished_charge_is_marked(self):
        import datetime
        now = datetime.datetime.now()
        done = {"t": now.isoformat(timespec="seconds"), "wh": 12345}
        idle = {"telemetry": {"last": "2026-01-01T00:10:00", "age_s": 2, "frames": 9, "from": "192.168.1.63:5000",
                              "fields": {"S": "1", "M": "26", "m": "40", "V": "2440", "T": "15", "L": "0029163065"}}}
        text = h._dashboard(self.snapshot(charge={"last_complete": done}, **idle), 2, 8, hist={"amps": {}, "days": []})
        self.assertIn("Session", h._dashboard(self.snapshot(charge={"last_complete": done}), 2, 8))   # while charging
        self.assertIn("Finished  %s  12.3 kWh" % now.strftime("%H:%M"), text)
        self.assertIn("v", text.split("Current per minute")[1].split("\n")[7])     # marker on the time axis
        old = h._dashboard(self.snapshot(charge={"last_complete": {"t": "2026-01-01T07:42:10", "wh": None}}, **idle), 2, 8)
        self.assertIn("Finished  01-01 07:42", old)
        for st in (self.snapshot(**idle), self.snapshot(charge=None, **idle),
                   self.snapshot(charge={"last_complete": "x"}, **idle)):
            self.assertIn("no charge seen yet", h._dashboard(st, 2, 8))


class TestChargeWatch(unittest.TestCase):
    def feed(self, w, frames):
        import datetime
        t0 = datetime.datetime(2026, 1, 1, 22, 0, 0)
        return [d for d in (w.observe(t0 + datetime.timedelta(seconds=s), state, l)
                            for s, state, l in frames) if d]

    def test_charge_then_idle_completes_once(self):
        w = h.ChargeWatch()
        got = self.feed(w, [(0, "2", 1000), (9, "2", 5000), (18, "1", 5200), (27, "1", 5200),
                            (36, "1", 5200), (48, "1", 5200), (57, "1", 5200)])
        self.assertEqual(got, [{"t": "2026-01-01T22:00:18", "wh": 4200}])
        self.assertEqual(w.last, got[0])

    def test_blip_unplug_gap_and_cold_start_do_not(self):
        self.assertEqual(self.feed(h.ChargeWatch(), [(0, "2", 1000), (9, "1", 1010), (50, "1", 1010)]), [])
        self.assertEqual(self.feed(h.ChargeWatch(), [(0, "2", 1000), (9, "0", 9000), (18, "1", 9000),
                                                     (60, "1", 9000)]), [])
        self.assertEqual(self.feed(h.ChargeWatch(), [(0, "2", 1000), (300, "1", 9000), (340, "1", 9000)]), [])
        self.assertEqual(self.feed(h.ChargeWatch(), [(0, "1", 1000), (40, "1", 1000)]), [])

    def test_seed_replays_the_log(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "telemetry.log")
        frame = "2026-01-01T22:00:%02d.5\t192.168.1.63\t0817:v07,s0001,V2400,L%010d,S%s,M26,m40,A0000!XYZ:\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("a line cut in half by the tail seek\n")
            for s, state, l in [(0, "2", 1000), (9, "2", 5000), (18, "1", 5200), (27, "1", 5200), (50, "1", 5200)]:
                f.write(frame % (s, l, state))
        w = h.ChargeWatch()
        w.seed(path)
        self.assertEqual(w.last, {"t": "2026-01-01T22:00:18", "wh": 4200})
        w.seed(os.path.join(tmp, "missing"))                       # no log yet: nothing to do


if __name__ == "__main__":
    unittest.main()
