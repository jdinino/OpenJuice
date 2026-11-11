// OpenJuiceMonitor -- a small desktop window for the JuiceBox helper's status.
//
// Draws the same themed text-mode screen as `juicebox_helper.py status --watch`, in a
// WinForms window, with a tray icon and a chime when a charge completes. It only READS
// %LOCALAPPDATA%\OpenJuice\status.json; it never contacts the charger. The theme choice is
// shared with the terminal screen through ui.json in the same folder.
//
// Builds with the C# 5 compiler that ships with Windows (.NET Framework 4.x); see
// build_monitor.ps1. The layout and the theme table mirror _compose() and THEMES in
// tools/juicebox/juicebox_helper.py -- change both together.
//
//   OpenJuiceMonitor.exe                         run the monitor
//   OpenJuiceMonitor.exe --snapshot out.png [theme]   draw one frame to a PNG and exit
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Media;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace OpenJuice
{
    struct Cell { public char Ch; public int Fg, Bg; }

    class Theme
    {
        public string Name;
        public bool Pattern;
        public int[] Desk, Bar, Main, Win, Log, Shadow, Trough, Ok, Warn, Bad, Info, Idle;
        public int Key, LogTime, LogText, Fill, FillBad, Tick;

        static int[] P(int fg, int bg) { return new int[] { fg, bg }; }

        // ANSI SGR numbers, as in the Python table.
        public static readonly Theme[] All = new Theme[] {
            new Theme { Name = "turbo", Pattern = true, Desk = P(94, 44), Bar = P(30, 47), Key = 31,
                Main = P(30, 46), Win = P(30, 47), Log = P(97, 40), LogTime = 93, LogText = 37,
                Shadow = P(90, 40), Trough = P(90, 40), Fill = 92, FillBad = 91, Tick = 93,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(97, 44), Idle = P(97, 100) },
            new Theme { Name = "commander", Pattern = false, Desk = P(90, 40), Bar = P(30, 46), Key = 31,
                Main = P(97, 44), Win = P(96, 44), Log = P(96, 44), LogTime = 93, LogText = 97,
                Shadow = P(90, 40), Trough = P(94, 40), Fill = 96, FillBad = 91, Tick = 93,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(30, 46), Idle = P(30, 47) },
            new Theme { Name = "phosphor", Pattern = false, Desk = P(32, 40), Bar = P(30, 42), Key = 97,
                Main = P(92, 40), Win = P(32, 40), Log = P(32, 40), LogTime = 92, LogText = 32,
                Shadow = P(32, 40), Trough = P(32, 40), Fill = 92, FillBad = 97, Tick = 97,
                Ok = P(30, 42), Warn = P(30, 102), Bad = P(30, 107), Info = P(30, 42), Idle = P(92, 40) },
            new Theme { Name = "amber", Pattern = false, Desk = P(33, 40), Bar = P(30, 43), Key = 97,
                Main = P(93, 40), Win = P(33, 40), Log = P(33, 40), LogTime = 93, LogText = 33,
                Shadow = P(33, 40), Trough = P(33, 40), Fill = 93, FillBad = 97, Tick = 97,
                Ok = P(30, 43), Warn = P(30, 103), Bad = P(30, 107), Info = P(30, 43), Idle = P(93, 40) },
            new Theme { Name = "light", Pattern = true, Desk = P(37, 107), Bar = P(97, 44), Key = 93,
                Main = P(30, 47), Win = P(30, 47), Log = P(30, 107), LogTime = 34, LogText = 30,
                Shadow = P(37, 100), Trough = P(37, 100), Fill = 92, FillBad = 91, Tick = 93,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(97, 44), Idle = P(97, 100) },
        };

        public static int IndexOf(string name)
        {
            for (int i = 0; i < All.Length; i++) if (All[i].Name == name) return i;
            return 0;
        }
    }

    class Canvas
    {
        public const char H = '\u2550', V = '\u2551', TL = '\u2554', TR = '\u2557', BL = '\u255a', BR = '\u255d';
        public const char FULL = '\u2588', EMPTY = '\u2591', DESK = '\u2591', SEP = '\u2502';
        public readonly int W, Hgt;
        public readonly Cell[,] C;

        public Canvas(int w, int h, char ch, int fg, int bg)
        {
            W = w; Hgt = h; C = new Cell[h, w];
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++) { C[y, x].Ch = ch; C[y, x].Fg = fg; C[y, x].Bg = bg; }
        }

        // fg or bg of -1 keeps what the cell already has.
        public void Put(int x, int y, string text, int fg, int bg)
        {
            if (y < 0 || y >= Hgt || text == null) return;
            for (int i = 0; i < text.Length; i++)
            {
                int xx = x + i;
                if (xx < 0 || xx >= W) continue;
                C[y, xx].Ch = text[i];
                if (fg >= 0) C[y, xx].Fg = fg;
                if (bg >= 0) C[y, xx].Bg = bg;
            }
        }

        public void Put(int x, int y, string text) { Put(x, y, text, -1, -1); }

        public void Fill(int x, int y, int w, int h, char ch, int fg, int bg)
        {
            string s = new string(ch, Math.Max(0, w));
            for (int yy = y; yy < y + h; yy++) Put(x, yy, s, fg, bg);
        }

        public void Shade(int x, int y, int w, int h, int fg, int bg)
        {
            for (int yy = Math.Max(0, y); yy < Math.Min(Hgt, y + h); yy++)
                for (int xx = Math.Max(0, x); xx < Math.Min(W, x + w); xx++) { C[yy, xx].Fg = fg; C[yy, xx].Bg = bg; }
        }

        public void Window(int x, int y, int w, int h, string title, int[] col, int[] shadow)
        {
            Shade(x + 2, y + 1, w, h, shadow[0], shadow[1]);
            Fill(x, y, w, h, ' ', col[0], col[1]);
            string bar = new string(H, Math.Max(0, w - 2));
            Put(x, y, TL + bar + TR);
            Put(x, y + h - 1, BL + bar + BR);
            for (int yy = y + 1; yy < y + h - 1; yy++) { Put(x, yy, V.ToString()); Put(x + w - 1, yy, V.ToString()); }
            string t = " " + title + " ";
            Put(x + (w - t.Length) / 2, y, t);
        }
    }

    static class J
    {
        static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        public static object Get(object o, string k)
        {
            Dictionary<string, object> d = o as Dictionary<string, object>;
            object v;
            return (d != null && d.TryGetValue(k, out v)) ? v : null;
        }

        public static string S(object o, string k, string def)
        {
            object v = Get(o, k);
            string s = v == null ? null : Convert.ToString(v, Inv);
            return string.IsNullOrEmpty(s) ? def : s;
        }

        public static int I(object o, string k, int def)
        {
            object v = Get(o, k);
            int r;
            return (v != null && int.TryParse(Convert.ToString(v, Inv), NumberStyles.Integer, Inv, out r)) ? r : def;
        }

        public static bool Has(object o, string k) { return Get(o, k) != null; }
    }

    static class Screen
    {
        static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        static string Clip(string s, int n)
        {
            if (s == null) s = "";
            return s.Length <= n ? s : s.Substring(0, Math.Max(0, n - 3)) + "...";
        }

        public static string Hms(string iso)
        {
            DateTime dt;
            if (iso != null && DateTime.TryParse(iso, Inv, DateTimeStyles.None, out dt)) return dt.ToString("HH:mm:ss");
            return iso ?? "-";
        }

        static string Dur(double secs)
        {
            long s = Math.Max(0, (long)secs);
            long d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
            if (d > 0) return d + "d" + h + "h";
            if (h > 0) return h + "h" + m + "m";
            return m + "m" + (s % 60) + "s";
        }

        public static string StateName(string s)
        {
            switch (s) { case "0": return "unplugged"; case "1": return "plugged in"; case "2": return "charging"; case "5": return "error"; }
            return s ?? "?";
        }

        static void Text(Canvas cv, int wx, int wy, int line, string label, string value, int iw)
        {
            cv.Put(wx + 2, wy + 1 + line, label.PadRight(8));
            cv.Put(wx + 11, wy + 1 + line, Clip(value, iw - 9));
        }

        static void Chip(Canvas cv, int wx, int wy, int line, string label, string text, int[] col, string tail, int iw)
        {
            cv.Put(wx + 2, wy + 1 + line, label.PadRight(8));
            string body = " " + text + " ";
            cv.Put(wx + 11, wy + 1 + line, body, col[0], col[1]);
            cv.Put(wx + 11 + body.Length, wy + 1 + line, Clip(tail, iw - 9 - body.Length));
        }

        static void Meter(Canvas cv, Theme T, int x0, int y0, int width, double value, double maxv, double cap, bool bad)
        {
            int fill = maxv > 0 ? (int)Math.Round(Math.Max(0.0, Math.Min(value, maxv)) / maxv * width) : 0;
            int tick = (cap >= 0 && maxv > 0) ? Math.Min(width - 1, (int)Math.Round(cap / maxv * width)) : -1;
            for (int i = 0; i < width; i++)
            {
                if (i < fill) cv.Put(x0 + i, y0, Canvas.FULL.ToString(), bad ? T.FillBad : T.Fill, T.Trough[1]);
                else if (i == tick) cv.Put(x0 + i, y0, Canvas.SEP.ToString(), T.Tick, T.Trough[1]);
                else cv.Put(x0 + i, y0, Canvas.EMPTY.ToString(), T.Trough[0], T.Trough[1]);
            }
        }

        static void Bar(Canvas cv, Theme T, int wx, int wy, int line, string label, double value, double maxv,
                        string shown, double cap, bool bad, int bw)
        {
            cv.Put(wx + 2, wy + 1 + line, label.PadRight(8));
            Meter(cv, T, wx + 11, wy + 1 + line, bw, value, maxv, cap, bad);
            cv.Put(wx + 12 + bw, wy + 1 + line, Clip(shown, 7));
        }

        // A vertical bar growing up from `bottom`; returns the row of its top cell.
        static int Column(Canvas cv, int x0, int bottom, int rows, double frac, int width, int fg)
        {
            int eighths = (int)Math.Round(Math.Max(0.0, Math.Min(frac, 1.0)) * rows * 8);
            if (frac > 0 && eighths == 0) eighths = 1;
            int full = eighths / 8, part = eighths % 8;
            for (int i = 0; i < full; i++) cv.Put(x0, bottom - i, new string(Canvas.FULL, width), fg, -1);
            if (part > 0) cv.Put(x0, bottom - full, new string((char)(0x2580 + part), width), fg, -1);
            return bottom - full - (part > 0 ? 0 : -1);
        }

        public static Canvas Compose(Dictionary<string, object> st, double age, Theme T, int W, int H, string hint, History hist)
        {
            W = Math.Max(80, W); H = Math.Max(30, H);
            DateTime now = DateTime.Now;
            bool alive = age < 30;
            Canvas cv = new Canvas(W, H, T.Pattern ? Canvas.DESK : ' ', T.Desk[0], T.Desk[1]);

            cv.Fill(0, 0, W, 1, ' ', T.Bar[0], T.Bar[1]);
            cv.Put(1, 0, "OpenJuice", T.Key, -1);
            cv.Put(11, 0, Canvas.SEP + " JuiceBox Gen 1");
            string clock = now.ToString("yyyy-MM-dd HH:mm:ss");
            cv.Put(W - clock.Length - 1, 0, clock);

            cv.Fill(0, H - 1, W, 1, ' ', T.Bar[0], T.Bar[1]);
            List<string[]> items = new List<string[]>();
            items.Add(new string[] { "Theme", T.Name });
            if (!string.IsNullOrEmpty(hint)) items.Add(new string[] { "Keys", hint });
            int x = 1;
            foreach (string[] it in items)
            {
                cv.Put(x, H - 1, it[0], T.Key, -1);
                cv.Put(x + it[0].Length + 1, H - 1, it[1]);
                x += it[0].Length + it[1].Length + 2;
                cv.Put(x, H - 1, Canvas.SEP.ToString());
                x += 2;
            }

            int ww = (W - 6) / 2;
            int lx = 2, rx = 2 + ww + 2, ty = 2, th = 9;
            int fw = 2 * ww + 2, cy = 12, chh = 10, by = 23, bh = H - 25;
            int iw = ww - 4, bw = iw - 17;

            // --- Charger: every reading as a bar
            cv.Window(lx, ty, ww, th, "Charger", T.Main, T.Shadow);
            object t = J.Get(st, "telemetry");
            object f = J.Get(t, "fields");
            int cap = J.I(f, "M", 0), circ = J.I(f, "m", 40);
            if (circ == 0) circ = 40;
            if (J.Has(t, "last"))
            {
                string sc = J.S(f, "S", null);
                int[] scol = sc == "2" ? T.Ok : sc == "1" ? T.Info : sc == "5" ? T.Bad : T.Idle;
                Chip(cv, lx, ty, 0, "State", StateName(sc).ToUpperInvariant(), scol, J.Has(t, "age_s") ? " " + J.I(t, "age_s", 0) + "s ago" : "", iw);
                double a = J.I(f, "A", 0) / 10.0, v = J.I(f, "V", 0) / 10.0;
                int temp = J.I(f, "T", 0);
                Bar(cv, T, lx, ty, 1, "Current", a, circ, a.ToString("0.0", Inv) + " A", cap, a > cap + 0.05, bw);
                Bar(cv, T, lx, ty, 2, "Power", a * v / 1000.0, circ * 0.24, (a * v / 1000.0).ToString("0.00", Inv) + " kW", -1, false, bw);
                Bar(cv, T, lx, ty, 3, "Volts", v - 200, 60, v.ToString("0.0", Inv) + " V", -1, !(v >= 210 && v <= 255), bw);
                Bar(cv, T, lx, ty, 4, "Temp", temp, 80, temp + " C", -1, temp > 60, bw);
                Text(cv, lx, ty, 5, "Session", J.Has(f, "E") ? (J.I(f, "E", 0) / 1000.0).ToString("#,##0.000", Inv) + " kWh" : "-", iw);
                Text(cv, lx, ty, 6, "Lifetime", J.Has(f, "L") ? (J.I(f, "L", 0) / 1000.0).ToString("#,##0.000", Inv) + " kWh" : "-", iw);
            }
            else cv.Put(lx + 2, ty + 1, Clip("no telemetry since the helper started", iw));

            // --- Health: helper, link and the counters that have limits
            cv.Window(rx, ty, ww, th, "Health", T.Win, T.Shadow);
            object w = J.Get(st, "watchdog");
            string up = "?";
            DateTime started;
            if (DateTime.TryParse(J.S(st, "started", ""), Inv, DateTimeStyles.None, out started)) up = Dur((now - started).TotalSeconds);
            Chip(cv, rx, ty, 0, "Helper", alive ? "RUNNING" : "STOPPED", alive ? T.Ok : T.Bad, " up " + up, iw);
            string ws = J.S(w, "state", "?");
            int[] wcol = ws == "attached" ? T.Ok
                : (ws == "reattaching" || ws == "silent" || ws == "rebooting" || ws == "starting" || ws == "released") ? T.Warn : T.Bad;
            string since = Hms(J.S(w, "since", null));
            Chip(cv, rx, ty, 1, "Link", ws, wcol, " since " + (since.Length >= 5 ? since.Substring(0, 5) : since), iw);
            if (!J.Has(w, "module_faults")) Text(cv, rx, ty, 2, "Faults", "unknown", iw);
            else
            {
                int nf = J.I(w, "module_faults", 0);
                Bar(cv, T, rx, ty, 2, "Faults", nf, 8, nf + "/8", 6, nf > 5, bw);
            }
            object lim = J.Get(st, "limit");
            int nr = J.I(w, "reboots_24h", 0), nc = J.I(lim, "corrections_24h", 0);
            Bar(cv, T, rx, ty, 3, "Reboots", nr, 4, nr + "/4", -1, nr >= 4, bw);
            Bar(cv, T, rx, ty, 4, "Fixes", nc, 12, nc + "/12", -1, nc >= 12, bw);
            object rv = J.Get(J.Get(st, "beacon"), "rssi");
            if (rv is int) Bar(cv, T, rx, ty, 5, "Signal", (int)rv + 90, 50, (int)rv + " dBm", -1, (int)rv < -75, bw);
            else Text(cv, rx, ty, 5, "Signal", "no beacon", iw);
            object r = J.Get(st, "resolver");
            string lastAsk = Hms(J.S(r, "last_hijack", null));
            Text(cv, rx, ty, 6, "Resolver", J.I(r, "hijacks", 0) + " answers, last " + (lastAsk.Length >= 5 ? lastAsk.Substring(0, 5) : lastAsk), iw);

            // --- Chart: current per minute
            int nb = iw - 3, bottom = cy + 7;
            cv.Window(lx, cy, ww, chh, "Current per minute, A", T.Win, T.Shadow);
            if (hist != null)
            {
                cv.Put(lx + 2, cy + 1, circ.ToString().PadLeft(2));
                cv.Put(lx + 2, bottom, " 0");
                if (cap > 0 && cap < circ) cv.Put(lx + 2, bottom - (int)((double)cap / circ * 7), cap.ToString().PadLeft(2));
                for (int i = 0; i < nb; i++)
                {
                    string key = now.AddMinutes(-(nb - 1 - i)).ToString("yyyy-MM-dd'T'HH:mm", Inv);
                    double a;
                    if (hist.Amps.TryGetValue(key, out a))
                    {
                        if (a > 0) Column(cv, lx + 5 + i, bottom, 7, a / circ, 1, a > cap + 0.05 ? T.FillBad : T.Fill);
                        else cv.Put(lx + 5 + i, bottom, "_");
                    }
                }
                cv.Put(lx + 5, cy + 8, "-" + nb + "m");
                cv.Put(lx + 5 + nb - 3, cy + 8, "now");
            }
            else cv.Put(lx + 2, cy + 1, Clip("no telemetry.log to chart", iw));

            // --- Chart: energy per day
            cv.Window(rx, cy, ww, chh, "Energy per day, kWh", T.Win, T.Shadow);
            if (hist != null && hist.DayKwh.Length > 0)
            {
                double top = 0;
                foreach (double k in hist.DayKwh) if (!double.IsNaN(k) && k > top) top = k;
                if (top <= 0) top = 1;
                int n0 = hist.DayKwh.Length;
                int x0 = rx + 2 + Math.Max(0, (iw - 4 * n0 + 1) / 2);
                for (int i = 0; i < n0; i++)
                {
                    int xx = x0 + 4 * i;
                    double kwh = hist.DayKwh[i];
                    cv.Put(xx, cy + 8, hist.DayLabels[i].PadRight(3));
                    if (double.IsNaN(kwh)) { cv.Put(xx, bottom, " - "); continue; }
                    int row = kwh > 0 ? Column(cv, xx, bottom, 5, kwh / top, 3, T.Fill) : bottom + 1;
                    string lab = kwh >= 10 ? kwh.ToString("0", Inv) : kwh.ToString("0.0", Inv);
                    lab = lab.PadLeft((3 + lab.Length) / 2).PadRight(3);
                    cv.Put(xx, row - 1, lab);
                }
            }
            else cv.Put(rx + 2, cy + 1, Clip("no telemetry.log to chart", iw));

            // --- Event log
            cv.Window(lx, by, fw, bh, "Event log", T.Log, T.Shadow);
            IList evs = J.Get(st, "events") as IList;
            int n = evs == null ? 0 : Math.Min(evs.Count, bh - 2);
            for (int i = 0; i < n; i++)
            {
                object e = evs[evs.Count - n + i];
                string stamp = J.S(e, "t", "").Replace('T', ' ');
                cv.Put(lx + 2, by + 1 + i, stamp.Length > 19 ? stamp.Substring(0, 19) : stamp, T.LogTime, -1);
                cv.Put(lx + 22, by + 1 + i, Clip(J.S(e, "msg", ""), fw - 24), T.LogText, -1);
            }
            return cv;
        }
    }

    // Chart data from telemetry.log: peak amps per minute (recent) and kWh per day.
    // Mirrors load_history() in juicebox_helper.py.
    class History
    {
        public readonly Dictionary<string, double> Amps = new Dictionary<string, double>();
        public string[] DayLabels = new string[0];
        public double[] DayKwh = new double[0];                       // NaN = no data for that day
        static readonly Encoding Latin1 = Encoding.GetEncoding(28591);

        static int Field(string line, string key)
        {
            int tab = line.LastIndexOf('\t');
            foreach (string tok in line.Substring(tab + 1).Split(','))
            {
                if (!tok.StartsWith(key, StringComparison.Ordinal)) continue;
                string digits = tok.Substring(key.Length).Split('!')[0];
                int v;
                if (digits.Length > 0 && int.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out v)) return v;
            }
            return -1;
        }

        static string ReadLine(FileStream f)
        {
            StringBuilder sb = new StringBuilder();
            int b;
            while ((b = f.ReadByte()) >= 0 && b != '\n' && sb.Length < 8192) sb.Append((char)b);
            return (b < 0 && sb.Length == 0) ? null : sb.ToString();
        }

        static int LifetimeAt(FileStream f, long size, string stamp)
        {
            long lo = 0, hi = size;
            while (hi - lo > 8192)
            {
                long mid = (lo + hi) / 2;
                f.Position = mid;
                ReadLine(f);
                string line = ReadLine(f) ?? "";
                if (line.Length >= 19 && string.CompareOrdinal(line, 0, stamp, 0, 19) < 0) lo = mid; else hi = mid;
            }
            f.Position = lo;
            if (lo > 0) ReadLine(f);
            for (int i = 0; i < 2000; i++)
            {
                string line = ReadLine(f);
                if (line == null) return -1;
                if (line.Length >= 19 && string.CompareOrdinal(line, 0, stamp, 0, 19) >= 0)
                {
                    int v = Field(line, "L");
                    if (v >= 0) return v;
                }
            }
            return -1;
        }

        public static History Load(string dir)
        {
            try
            {
                using (FileStream f = new FileStream(Path.Combine(dir, "telemetry.log"), FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    History h = new History();
                    long size = f.Length;
                    f.Position = Math.Max(0, size - 200 * 1024);
                    byte[] buf = new byte[(int)(size - f.Position)];
                    int got = 0, n;
                    while (got < buf.Length && (n = f.Read(buf, got, buf.Length - got)) > 0) got += n;
                    string[] lines = Latin1.GetString(buf, 0, got).Split('\n');
                    int lastL = -1;
                    for (int i = 1; i < lines.Length; i++)
                    {
                        string s = lines[i];
                        if (s.Length < 16 || s.IndexOf(":v", StringComparison.Ordinal) < 0) continue;
                        double a = Math.Max(0, Field(s, "A")) / 10.0;
                        string key = s.Substring(0, 16);
                        double prev;
                        h.Amps[key] = h.Amps.TryGetValue(key, out prev) ? Math.Max(prev, a) : a;
                        int v = Field(s, "L");
                        if (v >= 0) lastL = v;
                    }
                    const int days = 7;
                    DateTime today = DateTime.Today;
                    int[] marks = new int[days + 1];
                    for (int i = 0; i < days; i++)
                        marks[i] = LifetimeAt(f, size, today.AddDays(-(days - 1 - i)).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + "T00:00:00");
                    marks[days] = lastL;
                    h.DayLabels = new string[days];
                    h.DayKwh = new double[days];
                    for (int i = 0; i < days; i++)
                    {
                        int a = marks[i], b = marks[i + 1] >= 0 ? marks[i + 1] : lastL;
                        h.DayLabels[i] = today.AddDays(-(days - 1 - i)).ToString("ddd", CultureInfo.InvariantCulture).Substring(0, 2);
                        h.DayKwh[i] = (a >= 0 && b >= a) ? (b - a) / 1000.0 : double.NaN;
                    }
                    return h;
                }
            }
            catch (Exception) { return null; }
        }
    }

    // Fires once per real charge: S2 seen, then S1 held 30 s, with >= 0.1 kWh delivered.
    // Same rules as charge_notifier.py's CompletionDetector.
    class CompletionDetector
    {
        const double Confirm = 30, Gap = 60, MinWh = 100;
        bool armed, fired;
        DateTime? s1Since, lastObs;
        int? armL, lastL;

        public double? Observe(DateTime when, string S, int? L)
        {
            double? result = null;
            if (S == null) return null;
            if (lastObs.HasValue && (when - lastObs.Value).TotalSeconds > Gap) { armed = false; s1Since = null; fired = false; armL = null; }
            lastObs = when;
            if (S == "2")
            {
                if (!armed) armL = L.HasValue ? L : lastL;
                armed = true; s1Since = null; fired = false;
            }
            else if (S == "1")
            {
                if (armed && !fired)
                {
                    if (!s1Since.HasValue) s1Since = when;
                    else if ((when - s1Since.Value).TotalSeconds >= Confirm)
                    {
                        fired = true; armed = false;
                        double wh = (lastL.HasValue && armL.HasValue) ? lastL.Value - armL.Value : -1;
                        if (wh < 0 || wh >= MinWh) result = Math.Max(0, wh);
                    }
                }
            }
            else { armed = false; s1Since = null; fired = false; armL = null; }
            if (L.HasValue) lastL = L;
            return result;
        }
    }

    class MonitorForm : Form
    {
        readonly string dataDir;
        readonly Font font;
        readonly int cw, ch;
        readonly Timer timer = new Timer();
        readonly NotifyIcon tray = new NotifyIcon();
        readonly ContextMenuStrip menu = new ContextMenuStrip();
        readonly CompletionDetector detector = new CompletionDetector();
        readonly Dictionary<int, SolidBrush> brushes = new Dictionary<int, SolidBrush>();
        ToolStripMenuItem chimeItem;
        Canvas canvas;
        int theme;
        bool quitting;

        public MonitorForm(string dataDir)
        {
            this.dataDir = dataDir;
            Text = "OpenJuice Monitor";
            font = Program.MakeFont();
            Program.Measure(font, out cw, out ch);
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            ClientSize = new Size(80 * cw, 31 * ch);
            MinimumSize = SizeFromClientSize(new Size(80 * cw, 30 * ch));
            StartPosition = FormStartPosition.CenterScreen;
            Icon = SystemIcons.Application;
            KeyPreview = true;
            theme = Theme.IndexOf(Program.LoadTheme(dataDir));

            ToolStripMenuItem themes = new ToolStripMenuItem("Theme");
            for (int i = 0; i < Theme.All.Length; i++)
            {
                int idx = i;
                themes.DropDownItems.Add(new ToolStripMenuItem(Theme.All[i].Name, null, delegate { SetTheme(idx); }));
            }
            chimeItem = new ToolStripMenuItem("Chime when a charge completes") { CheckOnClick = true, Checked = true };
            menu.Items.Add(new ToolStripMenuItem("Show", null, delegate { Restore(); }));
            menu.Items.Add(themes);
            menu.Items.Add(chimeItem);
            menu.Items.Add(new ToolStripMenuItem("Test chime", null, delegate { Chime(null); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Exit", null, delegate { quitting = true; Close(); }));
            menu.Opening += delegate
            {
                for (int i = 0; i < themes.DropDownItems.Count; i++) ((ToolStripMenuItem)themes.DropDownItems[i]).Checked = i == theme;
            };
            ContextMenuStrip = menu;

            tray.Icon = Icon;
            tray.Text = "OpenJuice";
            tray.ContextMenuStrip = menu;
            tray.Visible = true;
            tray.DoubleClick += delegate { Restore(); };

            timer.Interval = 1000;
            timer.Tick += delegate { Refresh1(); };
            timer.Start();
            Refresh1();
        }

        void Restore() { Show(); WindowState = FormWindowState.Normal; Activate(); }

        void SetTheme(int idx)
        {
            theme = idx;
            Program.SaveTheme(dataDir, Theme.All[theme].Name);
            Refresh1();
        }

        void Chime(double? wh)
        {
            try { new SoundPlayer(@"C:\Windows\Media\tada.wav").Play(); } catch (Exception) { SystemSounds.Asterisk.Play(); }
            string msg = wh.HasValue && wh.Value > 0
                ? "Charge complete: " + (wh.Value / 1000.0).ToString("0.00", CultureInfo.InvariantCulture) + " kWh delivered."
                : "Charge complete.";
            tray.ShowBalloonTip(8000, "OpenJuice", msg, ToolTipIcon.Info);
        }

        void Refresh1()
        {
            // ui.json may have been changed by the terminal screen.
            int shared = Theme.IndexOf(Program.LoadTheme(dataDir));
            if (shared != theme && File.Exists(Path.Combine(dataDir, "ui.json"))) theme = shared;

            double age;
            Dictionary<string, object> st = Program.ReadStatus(dataDir, out age);
            int cols = Math.Max(80, ClientSize.Width / cw), rows = Math.Max(30, ClientSize.Height / ch);
            if (st != null)
            {
                canvas = Screen.Compose(st, age, Theme.All[theme], cols, rows, "T theme", History.Load(dataDir));
                object t = J.Get(st, "telemetry"), f = J.Get(t, "fields");
                DateTime last;
                string s = J.S(f, "S", null);
                if (DateTime.TryParse(J.S(t, "last", ""), CultureInfo.InvariantCulture, DateTimeStyles.None, out last)
                    && (DateTime.Now - last).TotalSeconds <= 60 && s != null)
                {
                    double? wh = detector.Observe(last, s, J.Has(f, "L") ? (int?)J.I(f, "L", 0) : null);
                    if (wh.HasValue && chimeItem.Checked) Chime(wh);
                    string tip = "OpenJuice: " + Screen.StateName(s) + ", " + (J.I(f, "A", 0) / 10.0).ToString("0.0", CultureInfo.InvariantCulture) + " A";
                    tray.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;
                }
                else tray.Text = "OpenJuice: no fresh telemetry";
            }
            else if (canvas == null)
            {
                Theme T = Theme.All[theme];
                canvas = new Canvas(cols, rows, ' ', T.Desk[0], T.Desk[1]);
                canvas.Put(2, 1, "waiting for the helper to write status.json in " + dataDir, 97, -1);
            }
            Invalidate();
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.T) SetTheme((theme + 1) % Theme.All.Length);
            base.OnKeyDown(e);
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (WindowState == FormWindowState.Minimized) Hide();      // lives in the tray
            else if (timer.Enabled) Refresh1();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Theme T = Theme.All[theme];
            e.Graphics.Clear(Program.Pal(T.Desk[1]));
            if (canvas != null) Program.Draw(e.Graphics, canvas, font, cw, ch, brushes);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); return; }   // X hides to the tray
            tray.Visible = false;
            base.OnFormClosing(e);
        }
    }

    static class Program
    {
        static readonly Color[] Vga = {
            Color.FromArgb(0, 0, 0), Color.FromArgb(170, 0, 0), Color.FromArgb(0, 170, 0), Color.FromArgb(170, 85, 0),
            Color.FromArgb(0, 0, 170), Color.FromArgb(170, 0, 170), Color.FromArgb(0, 170, 170), Color.FromArgb(170, 170, 170),
            Color.FromArgb(85, 85, 85), Color.FromArgb(255, 85, 85), Color.FromArgb(85, 255, 85), Color.FromArgb(255, 255, 85),
            Color.FromArgb(85, 85, 255), Color.FromArgb(255, 85, 255), Color.FromArgb(85, 255, 255), Color.FromArgb(255, 255, 255) };

        public static Color Pal(int sgr) { return Vga[(sgr % 10) + (sgr >= 90 ? 8 : 0)]; }

        public static Font MakeFont() { return new Font("Consolas", 11f, FontStyle.Regular, GraphicsUnit.Point); }

        const TextFormatFlags Flags = TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;

        public static void Measure(Font font, out int cw, out int ch)
        {
            Size sz = TextRenderer.MeasureText("MMMMMMMMMM", font, new Size(int.MaxValue, int.MaxValue), Flags);
            cw = Math.Max(1, sz.Width / 10);
            ch = Math.Max(1, sz.Height);
        }

        public static void Draw(Graphics g, Canvas cv, Font font, int cw, int ch, Dictionary<int, SolidBrush> brushes)
        {
            StringBuilder sb = new StringBuilder();
            for (int y = 0; y < cv.Hgt; y++)
            {
                int x = 0;
                while (x < cv.W)
                {
                    int fg = cv.C[y, x].Fg, bg = cv.C[y, x].Bg, start = x;
                    sb.Length = 0;
                    bool ink = false;
                    while (x < cv.W && cv.C[y, x].Fg == fg && cv.C[y, x].Bg == bg)
                    {
                        char c = cv.C[y, x].Ch;
                        if (c >= '▁' && c <= Canvas.FULL) c = ' ';   // block characters are painted as rectangles below
                        else if (c != ' ') ink = true;
                        sb.Append(c);
                        x++;
                    }
                    g.FillRectangle(Brush(brushes, bg), start * cw, y * ch, (x - start) * cw, ch);
                    if (ink) TextRenderer.DrawText(g, sb.ToString(), font, new Point(start * cw, y * ch), Pal(fg), Pal(bg), Flags);
                    for (int i = start; i < x; i++)
                    {
                        char b = cv.C[y, i].Ch;
                        if (b < '▁' || b > Canvas.FULL) continue;
                        int hgt = ch * (b - '▀') / 8;        // eighths of a cell, from the bottom
                        g.FillRectangle(Brush(brushes, fg), i * cw, y * ch + ch - hgt, cw - 1, hgt);
                    }
                }
            }
        }

        static SolidBrush Brush(Dictionary<int, SolidBrush> cache, int sgr)
        {
            SolidBrush b;
            if (!cache.TryGetValue(sgr, out b)) { b = new SolidBrush(Pal(sgr)); cache[sgr] = b; }
            return b;
        }

        public static Dictionary<string, object> ReadStatus(string dir, out double age)
        {
            age = 9999;
            try
            {
                string text = File.ReadAllText(Path.Combine(dir, "status.json"));
                Dictionary<string, object> st = new JavaScriptSerializer().DeserializeObject(text) as Dictionary<string, object>;
                DateTime written;
                if (st != null && DateTime.TryParse(J.S(st, "written", ""), CultureInfo.InvariantCulture, DateTimeStyles.None, out written))
                    age = (DateTime.Now - written).TotalSeconds;
                return st;
            }
            catch (Exception) { return null; }                      // missing or mid-write: try again next tick
        }

        public static string LoadTheme(string dir)
        {
            try
            {
                object o = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(dir, "ui.json")));
                return J.S(o, "theme", "turbo");
            }
            catch (Exception) { return "turbo"; }
        }

        public static void SaveTheme(string dir, string name)
        {
            try { File.WriteAllText(Path.Combine(dir, "ui.json"), "{\"theme\": \"" + name + "\"}"); } catch (Exception) { }
        }

        [STAThread]
        static int Main(string[] args)
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "OpenJuice");
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (args.Length >= 2 && args[0] == "--snapshot")
            {
                double age;
                Dictionary<string, object> st = ReadStatus(dir, out age);
                if (st == null) return 1;
                Theme T = Theme.All[Theme.IndexOf(args.Length >= 3 ? args[2] : LoadTheme(dir))];
                Canvas cv = Screen.Compose(st, age, T, 80, 31, "T theme", History.Load(dir));
                using (Font font = MakeFont())
                {
                    int cw, ch;
                    Measure(font, out cw, out ch);
                    using (Bitmap bmp = new Bitmap(cv.W * cw, cv.Hgt * ch))
                    using (Graphics g = Graphics.FromImage(bmp))
                    {
                        Draw(g, cv, font, cw, ch, new Dictionary<int, SolidBrush>());
                        bmp.Save(args[1], ImageFormat.Png);
                    }
                }
                return 0;
            }
            Application.Run(new MonitorForm(dir));
            return 0;
        }
    }
}
