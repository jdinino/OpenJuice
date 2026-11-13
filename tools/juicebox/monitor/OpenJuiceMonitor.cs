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
//   OpenJuiceMonitor.exe --tray                  run it hidden in the tray (what "Start with Windows" uses)
//   OpenJuiceMonitor.exe --smooth                draw text in Consolas instead of the Windows DOS-box bitmap font
//   OpenJuiceMonitor.exe --snapshot out.png [theme [datadir]]   draw one frame to a PNG and exit
//   OpenJuiceMonitor.exe --icons out.png         draw every state icon to a PNG and exit
//   OpenJuiceMonitor.exe --file-icon out.ico     write the exe's own icon (16 to 256 px); build_monitor.ps1 embeds it
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Media;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

// Windows shows these beside the exe's icon: on notifications, in Task Manager and in Explorer.
[assembly: System.Reflection.AssemblyTitle("OpenJuice Monitor")]
[assembly: System.Reflection.AssemblyProduct("OpenJuice")]
[assembly: System.Reflection.AssemblyDescription("Status window and tray icon for the JuiceBox helper")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

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
            new Theme { Name = "pascal", Pattern = true, Desk = P(90, 47), Bar = P(30, 46), Key = 31,
                Main = P(93, 44), Win = P(97, 44), Log = P(93, 44), LogTime = 96, LogText = 97,
                Shadow = P(90, 40), Trough = P(90, 40), Fill = 93, FillBad = 91, Tick = 97,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(30, 46), Idle = P(30, 47) },
            new Theme { Name = "midnight", Pattern = true, Desk = P(90, 40), Bar = P(97, 45), Key = 93,
                Main = P(97, 100), Win = P(37, 100), Log = P(95, 40), LogTime = 95, LogText = 37,
                Shadow = P(30, 40), Trough = P(90, 40), Fill = 95, FillBad = 91, Tick = 93,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(97, 45), Idle = P(30, 47) },
            new Theme { Name = "ocean", Pattern = true, Desk = P(96, 46), Bar = P(97, 44), Key = 93,
                Main = P(30, 107), Win = P(30, 107), Log = P(97, 44), LogTime = 96, LogText = 97,
                Shadow = P(90, 40), Trough = P(37, 100), Fill = 94, FillBad = 91, Tick = 93,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(97, 44), Idle = P(97, 100) },
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
            new Theme { Name = "hotdog", Pattern = false, Desk = P(93, 41), Bar = P(97, 40), Key = 93,
                Main = P(30, 103), Win = P(30, 103), Log = P(93, 40), LogTime = 91, LogText = 93,
                Shadow = P(30, 40), Trough = P(90, 40), Fill = 91, FillBad = 97, Tick = 93,
                Ok = P(30, 42), Warn = P(97, 45), Bad = P(97, 41), Info = P(97, 44), Idle = P(97, 100) },
            new Theme { Name = "mono", Pattern = false, Desk = P(37, 40), Bar = P(30, 47), Key = 30,
                Main = P(97, 40), Win = P(37, 40), Log = P(37, 40), LogTime = 97, LogText = 37,
                Shadow = P(37, 40), Trough = P(90, 40), Fill = 37, FillBad = 97, Tick = 97,
                Ok = P(30, 47), Warn = P(30, 107), Bad = P(30, 107), Info = P(30, 47), Idle = P(97, 40) },
            // Microsoft Visual Basic for MS-DOS 1.0, after its programming environment; see the Python table.
            new Theme { Name = "vbdos", Pattern = true, Desk = P(37, 40), Bar = P(30, 47), Key = 97,
                Main = P(30, 47), Win = P(30, 47), Log = P(37, 44), LogTime = 97, LogText = 37,
                Shadow = P(90, 40), Trough = P(30, 47), Fill = 30, FillBad = 31, Tick = 97,
                Ok = P(30, 42), Warn = P(30, 43), Bad = P(97, 41), Info = P(30, 46), Idle = P(37, 40) },
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
        // Single-line corners and rule for pull-down menus; SEP is their vertical. DOT marks a choice.
        public const char SH = '\u2500', STL = '\u250c', STR = '\u2510', SBL = '\u2514', SBR = '\u2518', DOT = '\u2022';
        // A dialog's close box, and the half blocks of a button's shadow.
        public const char BOX = '\u25a0', LOWER = '\u2584', UPPER = '\u2580';
        // Tees that join a title bar to a single-line frame.
        public const char STEE = '\u251c', ETEE = '\u2524';
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

        // A drop shadow, as Turbo Vision and VBDOS cast it: the cells keep their characters and only
        // change colour.
        public void Shade(int x, int y, int w, int h, int fg, int bg)
        {
            for (int yy = Math.Max(0, y); yy < Math.Min(Hgt, y + h); yy++)
                for (int xx = Math.Max(0, x); xx < Math.Min(W, x + w); xx++) { C[yy, xx].Fg = fg; C[yy, xx].Bg = bg; }
        }

        public void Window(int x, int y, int w, int h, string title, int[] col, int[] shadow) { Window(x, y, w, h, title, col, shadow, null, false, null, false); }
        public void Window(int x, int y, int w, int h, string title, int[] col, int[] shadow, int[] frame, bool single) { Window(x, y, w, h, title, col, shadow, frame, single, null, false); }

        // A framed box with a centred title and a shadow. `frame` colours the border and title apart
        // from the body; `single` draws the one-line frame of a window that is not the main one; `bar`
        // sets the title into the frame row as a solid bar of those colours, between a control box and
        // a minimise arrow; `tight` lets the frame line touch the title.
        public void Window(int x, int y, int w, int h, string title, int[] col, int[] shadow, int[] frame, bool single, int[] titleBar, bool tight)
        {
            int[] f = frame ?? col;
            Shade(x + 2, y + 1, w, h, shadow[0], shadow[1]);
            Fill(x, y, w, h, ' ', col[0], col[1]);
            string bar = new string(single ? SH : H, Math.Max(0, w - 2));
            string side = (single ? SEP : V).ToString();
            Put(x, y, (single ? STL : TL) + bar + (single ? STR : TR), f[0], f[1]);
            Put(x, y + h - 1, (single ? SBL : BL) + bar + (single ? SBR : BR), f[0], f[1]);
            for (int yy = y + 1; yy < y + h - 1; yy++) { Put(x, yy, side, f[0], f[1]); Put(x + w - 1, yy, side, f[0], f[1]); }
            string t = tight ? title : " " + title + " ";
            if (titleBar != null)
            {
                Put(x + 1, y, ETEE.ToString() + BOX + SEP, f[0], f[1]);
                Put(x + w - 4, y, SEP.ToString() + '\u25bc' + STEE, f[0], f[1]);
                Fill(x + 4, y, w - 8, 1, ' ', titleBar[0], titleBar[1]);
                Put(x + 4 + (w - 8 - title.Length) / 2, y, title);
            }
            else Put(x + (w - t.Length) / 2, y, t, f[0], f[1]);
        }
    }

    // Every icon the monitor shows, drawn in code from the charger state. The reasoning:
    //
    // - It shows load, as Task Manager's icon does. The charger knows the amps going to the vehicle
    //   and nothing about the battery, so no icon suggests a state of charge or a percentage.
    // - The tile colour is the state, because colour is all that survives at a glance or at 16 px:
    //   grey-blue unplugged, bright blue plugged in and idle, deep green charging, red error, and
    //   amber when there is no fresh telemetry (worth noticing, but not the charger reporting a fault).
    //   Amber is drawn in dark ink because white does not read on it.
    // - The picture is a J1772 handle inside a circle made by its own cord (after the owner's sketch).
    //   Plugged in, the nose meets a wall; unplugged, the handle is free and shows its head and the
    //   latch hook. The latch, head and wall are black so they stand apart from the white handle.
    // - The cord circle is the gauge: the bright green part is the amps out of the circuit rating
    //   (40 A). The rating, not the 26 A cap, so that a normal charge does not sit at a full circle.
    //   The charging tile is a deep green so that bright arc stands out.
    // - Under 24 px (tray, title bar) the drawing is unreadable, so the tile carries one mark instead:
    //   the amps while charging, 0 idle, u unplugged, ! error, ? no telemetry.
    // - From 48 px there is room for both, so the same mark sits in the lower left corner.
    // - The exe's own file icon (Explorer, shortcuts, the notification's app icon) cannot change, so
    //   it is the charging picture with no mark.
    // - Notifications get their own picture, since by then the state has moved on: a bright green
    //   tile marked C for a finished charge, the red tile marked ! for an error.
    static class StateIcon
    {
        [DllImport("user32.dll")]
        static extern bool DestroyIcon(IntPtr h);

        public static string KindOf(string s, bool fresh)
        {
            if (!fresh) return "stale";
            return s == "0" ? "unplugged" : s == "1" ? "idle" : s == "2" ? "charging" : s == "5" ? "error" : "stale";
        }

        // Shapes are in the units of the owner's 780 x 806 sketch: circle centre (385, 400), radius 275.
        const float CX = 385, CY = 400, R = 275, START = 142, SPAN = 345;

        static PointF[] Pts(params float[] xy)
        {
            PointF[] p = new PointF[xy.Length / 2];
            for (int i = 0; i < p.Length; i++) p[i] = new PointF(xy[2 * i], xy[2 * i + 1]);
            return p;
        }

        static readonly PointF[] Body = Pts(385, 285, 512, 281, 521, 292, 521, 386, 512, 396, 462, 396, 438, 372, 405, 362,
                                            346, 424, 318, 484, 288, 490, 222, 514, 198, 440);
        static readonly PointF[] Bolt = Pts(494, 290, 450, 346, 476, 346, 462, 388, 510, 328, 484, 328);
        static readonly PointF[] Latch = Pts(352, 302, 346, 236, 358, 222, 410, 220, 426, 238, 586, 234, 594, 246,
                                             594, 292, 570, 292, 570, 268, 388, 274);
        static readonly PointF[] LatchIn = Pts(352, 302, 346, 236, 358, 222, 410, 220, 426, 238, 526, 236, 526, 270, 388, 274);
        static readonly PointF[] Cord = Pts(214, 488, 186, 512, 170, 538, 168.3f, 569.3f);

        static GraphicsPath TilePath()
        {
            GraphicsPath p = new GraphicsPath();
            float d = 14, a = 0.5f, z = 31f;
            p.AddArc(a, a, d, d, 180, 90); p.AddArc(a + z - d, a, d, d, 270, 90);
            p.AddArc(a + z - d, a + z - d, d, d, 0, 90); p.AddArc(a, a + z - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        static void Tile(Graphics g, Color c)
        {
            using (GraphicsPath p = TilePath())
            using (SolidBrush b = new SolidBrush(c))
            {
                g.FillPath(b, p);
            }
        }

        // What the number-only tray icon says: the amps, or a mark when there are none to show.
        static string SmallText(string kind, double amps)
        {
            return kind == "complete" ? "C" : kind == "error" ? "!" : kind == "stale" ? "?" : kind == "unplugged" ? "u"
                 : Math.Round(kind == "charging" ? amps : 0).ToString("0", CultureInfo.InvariantCulture);
        }

        // The same number, small, in the lower left corner, with a rim of tile colour to lift it off the ring.
        static void Corner(Graphics g, string text, Color c, Color rim)
        {
            using (GraphicsPath p = new GraphicsPath())
            using (FontFamily ff = new FontFamily("Segoe UI"))
            using (SolidBrush b = new SolidBrush(c))
            using (Pen halo = new Pen(rim, 3.2f))
            {
                p.AddString(text, ff, (int)FontStyle.Bold, 11.5f, new PointF(0, 0), StringFormat.GenericTypographic);
                RectangleF r = p.GetBounds();
                using (Matrix m = new Matrix()) { m.Translate(2.6f - r.X, 29.6f - r.Bottom); p.Transform(m); }
                halo.LineJoin = LineJoin.Round;
                g.DrawPath(halo, p);
                g.FillPath(b, p);
            }
        }

        static void Number(Graphics g, string text, Color c)
        {
            using (GraphicsPath p = new GraphicsPath())
            using (FontFamily ff = new FontFamily("Segoe UI"))
            using (SolidBrush b = new SolidBrush(c))
            {
                p.AddString(text, ff, (int)FontStyle.Bold, 25, new PointF(0, 0), StringFormat.GenericTypographic);
                RectangleF r = p.GetBounds();
                using (Matrix m = new Matrix())
                {
                    float k = Math.Min(1f, 27f / r.Width);
                    m.Translate(16 - (r.X + r.Width / 2) * k, 16 - (r.Y + r.Height / 2) * k);
                    m.Scale(k, k);
                    p.Transform(m);
                }
                g.FillPath(b, p);
            }
        }

        // Draws on a 32-unit grid scaled to `size` pixels. The gauge is amps out of the circuit rating.
        // Where there is no room for the drawing (the tray, the title bar) the tile carries the amps
        // as a number instead: pass numberOnly.
        public static void Paint(Graphics g, string kind, double amps, int rating, float size, bool numberOnly)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            GraphicsState saved = g.Save();
            g.ScaleTransform(size / 32f, size / 32f);
            Color tile = kind == "complete" ? Color.FromArgb(34, 197, 68)      // only on the charge-complete notification
                       : kind == "charging" ? Color.FromArgb(12, 100, 34) : kind == "idle" ? Color.FromArgb(24, 132, 255)
                       : kind == "error" ? Color.FromArgb(205, 44, 36) : kind == "unplugged" ? Color.FromArgb(92, 104, 120)
                       : Color.FromArgb(255, 176, 0);        // no telemetry: amber, drawn in dark ink
            Color ink = kind == "stale" ? Color.FromArgb(28, 30, 34) : Color.FromArgb(250, 251, 252);
            Tile(g, tile);
            if (numberOnly)
            {
                Number(g, SmallText(kind, amps), ink);
                g.Restore(saved);
                return;
            }
            double load = amps / (rating > 0 ? rating : 40);

            float k = 13.2f / R;                                 // sketch units to the 32 grid
            g.TranslateTransform(16, 16);
            g.ScaleTransform(k, k);
            g.TranslateTransform(-CX, -CY);
            float w = 46;
            RectangleF box = new RectangleF(CX - R, CY - R, 2 * R, 2 * R);
            using (Pen track = new Pen(Color.FromArgb(kind == "charging" ? 70 : 105, ink), w))
            using (Pen lit = new Pen(Color.FromArgb(96, 255, 112), w))      // the gauge: bright green
            using (SolidBrush b = new SolidBrush(ink))
            using (SolidBrush hole = new SolidBrush(tile))
            {
                lit.StartCap = lit.EndCap = track.StartCap = track.EndCap = LineCap.Round;
                g.DrawArc(track, box, START, -SPAN);             // the whole cord circle, dim
                if (kind == "charging")                          // the lit part: amps of the circuit rating
                {
                    g.DrawArc(lit, box, START, -SPAN * (float)Math.Max(0.04, Math.Min(load, 1.0)));
                    g.DrawBezier(lit, Cord[0], Cord[1], Cord[2], Cord[3]);
                }
                else g.DrawBezier(track, Cord[0], Cord[1], Cord[2], Cord[3]);
                g.FillPolygon(b, Body);
                bool plugged = kind == "idle" || kind == "charging" || kind == "error" || kind == "complete";
                using (SolidBrush black = new SolidBrush(Color.FromArgb(12, 14, 16)))
                {
                    if (plugged) g.FillRectangle(black, 523, 196, 36, 290);   // the wall it is plugged into
                    else g.FillRectangle(black, 531, 297, 40, 82);            // free: the head that enters the vehicle
                    g.FillPolygon(black, plugged ? LatchIn : Latch);          // thumb pad, lever, and a hook when free
                }
                if (size >= 32)
                    using (SolidBrush bolt = new SolidBrush(kind == "stale" ? Color.White : Color.FromArgb(255, 140, 0))) g.FillPolygon(bolt, Bolt);
            }
            g.Restore(saved);
            if (size >= 48 && !Plain)                            // room for the tray number in the corner
            {
                saved = g.Save();
                g.ScaleTransform(size / 32f, size / 32f);
                using (GraphicsPath edge = TilePath()) g.SetClip(edge, CombineMode.Intersect);   // its rim stays on the tile
                Corner(g, SmallText(kind, amps), ink, tile);
                g.Restore(saved);
            }
        }

        static bool Plain;       // set while drawing the exe's own file icon: no corner number

        static Bitmap Render(string kind, double amps, int rating, int size, bool numberOnly)
        {
            Bitmap bmp = new Bitmap(size, size, PixelFormat.Format32bppArgb);
            using (Graphics g = Graphics.FromImage(bmp)) { g.Clear(Color.Transparent); Paint(g, kind, amps, rating, size, numberOnly); }
            return bmp;
        }

        // The picture on a notification: the drawing, large, with its mark in the corner ("C" on bright
        // green for a finished charge, "!" on red for an error).
        public static Icon MakeToast(string kind)
        {
            using (Bitmap bmp = Render(kind, 0, 40, 64, false))
            {
                IntPtr h = bmp.GetHicon();
                try { return (Icon)Icon.FromHandle(h).Clone(); }
                finally { DestroyIcon(h); }
            }
        }

        // The tray icon: the number alone, at whatever size the tray uses.
        public static Icon MakeTray(string kind, double amps, int rating)
        {
            using (Bitmap bmp = Render(kind, amps, rating, SystemInformation.SmallIconSize.Width, true))
            {
                IntPtr h = bmp.GetHicon();
                try { return (Icon)Icon.FromHandle(h).Clone(); }
                finally { DestroyIcon(h); }
            }
        }

        // The window icon, holding every size Windows asks for: the number at 16 px (title bar),
        // the drawing from 24 px (taskbar), and the drawing with the number in its corner from 48 px up to 256 px (large icon views).
        public static Icon MakeWindow(string kind, double amps, int rating)
        {
            // WinForms hands Windows only the system's small and large sizes, so 64 px is plenty here.
            using (MemoryStream ico = new MemoryStream(IcoBytes(kind, amps, rating, new int[] { 16, 24, 32, 48, 64 }, true)))
                return new Icon(ico);
        }

        // The icon stored in the exe itself, which Explorer, shortcuts and a pinned taskbar button show
        // at up to 256 px. It cannot change, so it is the charging picture with no number on it.
        public static void SaveFileIcon(string path)
        {
            Plain = true;
            try { File.WriteAllBytes(path, IcoBytes("charging", 26, 40, new int[] { 16, 24, 32, 48, 64, 256 }, false)); }
            finally { Plain = false; }
        }

        // The same picture as a 256 px PNG, for the notification identity (see Identity).
        public static void SaveFilePng(string path)
        {
            Plain = true;
            try { using (Bitmap bmp = Render("charging", 26, 40, 256, false)) bmp.Save(path, ImageFormat.Png); }
            finally { Plain = false; }
        }

        static byte[] IcoBytes(string kind, double amps, int rating, int[] sizes, bool numberWhenSmall)
        {
            byte[][] images = new byte[sizes.Length][];
            for (int i = 0; i < sizes.Length; i++)
            {
                int n = sizes[i], maskRow = ((n + 31) / 32) * 4;
                using (Bitmap bmp = Render(kind, amps, rating, n, numberWhenSmall && n < 24))
                using (MemoryStream ms = new MemoryStream())
                using (BinaryWriter w = new BinaryWriter(ms))
                {
                    if (n >= 256) { bmp.Save(ms, ImageFormat.Png); images[i] = ms.ToArray(); continue; }   // Windows reads 256 px as PNG
                    BitmapData d = bmp.LockBits(new Rectangle(0, 0, n, n), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                    byte[] px = new byte[n * n * 4];
                    for (int y = 0; y < n; y++)                  // an icon's rows run bottom to top
                        Marshal.Copy(new IntPtr(d.Scan0.ToInt64() + (long)(n - 1 - y) * d.Stride), px, y * n * 4, n * 4);
                    bmp.UnlockBits(d);
                    w.Write(40); w.Write(n); w.Write(2 * n); w.Write((short)1); w.Write((short)32);
                    w.Write(0); w.Write(px.Length + maskRow * n); w.Write(0); w.Write(0); w.Write(0); w.Write(0);
                    w.Write(px);
                    w.Write(new byte[maskRow * n]);              // the mask; alpha does the work
                    w.Flush();
                    images[i] = ms.ToArray();
                }
            }
            using (MemoryStream ico = new MemoryStream())
            {
                BinaryWriter w = new BinaryWriter(ico);
                w.Write((short)0); w.Write((short)1); w.Write((short)sizes.Length);
                int at = 6 + 16 * sizes.Length;
                for (int i = 0; i < sizes.Length; i++)
                {
                    byte dim = (byte)(sizes[i] >= 256 ? 0 : sizes[i]);     // 0 stands for 256 in an icon directory
                    w.Write(dim); w.Write(dim); w.Write((byte)0); w.Write((byte)0);
                    w.Write((short)1); w.Write((short)32); w.Write(images[i].Length); w.Write(at);
                    at += images[i].Length;
                }
                foreach (byte[] im in images) w.Write(im);
                w.Flush();
                return ico.ToArray();
            }
        }

        // A sheet of every state at 64, 32, 24 and 16 px on a light and a dark background.
        public static void Sheet(string path)
        {
            string[] rows = { "unplugged", "idle (plugged in)", "charging 6 A of 40", "charging 16 A of 40", "charging 26 A of 40",
                              "charging 40 A of 40", "error", "stale (no telemetry)", "complete (notification only)" };
            double[] amps = { 0, 0, 6, 16, 26, 40, 0, 0, 0 };
            using (Bitmap bmp = new Bitmap(680, rows.Length * 80))
            using (Graphics g = Graphics.FromImage(bmp))
            using (Font f = new Font("Segoe UI", 10f))
            {
                for (int r = 0; r < rows.Length; r++)
                {
                    string kind = rows[r].Split(' ')[0];
                    for (int side = 0; side < 2; side++)
                    {
                        using (SolidBrush bg = new SolidBrush(side == 0 ? Color.FromArgb(243, 243, 243) : Color.FromArgb(32, 32, 32)))
                            g.FillRectangle(bg, side * 340, r * 80, 340, 80);
                        int x = side * 340 + 8;
                        foreach (int s in new int[] { 64, 32, 24, 16 })
                        {
                            GraphicsState st = g.Save();
                            g.TranslateTransform(x, r * 80 + 8);
                            Paint(g, kind, amps[r], 40, s, s < 24);
                            g.Restore(st);
                            x += s + 12;
                        }
                        g.DrawString(rows[r], f, side == 0 ? Brushes.Black : Brushes.White, side * 340 + 196, r * 80 + 30);
                    }
                }
                bmp.Save(path, ImageFormat.Png);
            }
            string[] kinds = { "unplugged", "idle", "charging", "error", "stale" };      // and each state at 256 px
            using (Bitmap big = new Bitmap(kinds.Length * 272 + 16, 288))
            using (Graphics g = Graphics.FromImage(big))
            {
                g.Clear(Color.FromArgb(32, 32, 32));
                for (int i = 0; i < kinds.Length; i++)
                {
                    GraphicsState st = g.Save();
                    g.TranslateTransform(16 + i * 272, 16);
                    Paint(g, kinds[i], 26, 40, 256, false);
                    g.Restore(st);
                }
                big.Save(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(path)), Path.GetFileNameWithoutExtension(path) + "_256.png"), ImageFormat.Png);
            }
        }
    }

    // How Windows names the monitor and which icon it puts beside that name on a notification. A
    // plain exe gets a generic icon there even when it carries its own, so the monitor registers an
    // identity for itself: a name and a picture it writes out, both produced by this exe.
    static class Identity
    {
        const string Id = "OpenJuice.Monitor";

        [DllImport("shell32.dll")]
        static extern int SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string id);

        public static void Register(string dataDir)
        {
            try
            {
                string png = Path.Combine(dataDir, "OpenJuiceMonitor.png");
                StateIcon.SaveFilePng(png);
                using (RegistryKey k = Registry.CurrentUser.CreateSubKey(@"Software\Classes\AppUserModelId\" + Id))
                {
                    k.SetValue("DisplayName", "OpenJuice Monitor");
                    k.SetValue("IconUri", png);
                }
                SetCurrentProcessExplicitAppUserModelID(Id);
            }
            catch (Exception) { }                               // cosmetic: never stop the monitor over it
        }
    }

    // "Start with Windows": a per-user Run entry that launches the monitor hidden in the tray.
    static class AutoStart
    {
        const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run", Name = "OpenJuiceMonitor";

        static string Command { get { return "\"" + Application.ExecutablePath + "\" --tray"; } }

        public static bool Enabled
        {
            get
            {
                try
                {
                    using (RegistryKey k = Registry.CurrentUser.OpenSubKey(RunKey))
                        return k != null && string.Equals(k.GetValue(Name) as string, Command, StringComparison.OrdinalIgnoreCase);
                }
                catch (Exception) { return false; }
            }
        }

        public static void Set(bool on)
        {
            try
            {
                using (RegistryKey k = Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (on) k.SetValue(Name, Command);
                    else k.DeleteValue(Name, false);
                }
            }
            catch (Exception) { }
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

            int ww = (W - 10) / 2;                               // leaves desktop around every shadow
            int lx = 2, rx = 2 + ww + 4, ty = 2, th = 10;
            int fw = 2 * ww + 4, cy = 13, chh = 10, by = 24, bh = H - 26;
            int iw = ww - 4, bw = iw - 17;

            // --- Status: everything that is said in words, charger first, then the helper
            Style S = Style.Of(T);
            cv.Window(lx, ty, ww, th, "Status", T.Main, T.Shadow, null, S.TitleBar != null, S.TitleBar, false);
            object t = J.Get(st, "telemetry");
            object f = J.Get(t, "fields");
            object w = J.Get(st, "watchdog");
            object lim = J.Get(st, "limit");
            object lastDone = J.Get(J.Get(st, "charge"), "last_complete");
            string done = J.S(lastDone, "t", null);
            if (done != null && done.Length < 16) done = null;
            int cap = J.I(f, "M", 0), circ = J.I(f, "m", 40);
            if (circ == 0) circ = 40;
            string sc = J.S(f, "S", null);
            if (J.Has(t, "last"))
            {
                int[] scol = sc == "2" ? T.Ok : sc == "1" ? T.Info : sc == "5" ? T.Bad : T.Idle;
                Chip(cv, lx, ty, 0, "State", StateName(sc).ToUpperInvariant(), scol, J.Has(t, "age_s") ? " " + J.I(t, "age_s", 0) + "s ago" : "", iw);
                // The limit is the one the charger reports, flagged while it differs from the helper's.
                if (!J.Has(f, "M")) Text(cv, lx, ty, 1, "Limit", "-", iw);
                else if (J.Has(lim, "target") && J.I(lim, "target", cap) != cap)
                    Chip(cv, lx, ty, 1, "Limit", cap + " A", T.Warn, " target " + J.I(lim, "target", cap) + " A", iw);
                else Chip(cv, lx, ty, 1, "Limit", cap + " A", T.Info, "", iw);
                if (sc == "2" && J.Has(f, "E"))                 // charging: this session so far
                    Text(cv, lx, ty, 2, "Session", (J.I(f, "E", 0) / 1000.0).ToString("#,##0.000", Inv) + " kWh", iw);
                else if (done != null)                          // otherwise the last finished charge: when, how much
                {
                    string when = done.Substring(0, 10) == now.ToString("yyyy-MM-dd", Inv) ? done.Substring(11, 5) : done.Substring(5, 11).Replace('T', ' ');
                    Chip(cv, lx, ty, 2, "Finished", when, T.Ok, J.Has(lastDone, "wh") ? " " + (J.I(lastDone, "wh", 0) / 1000.0).ToString("0.0", Inv) + " kWh" : "", iw);
                }
                else Text(cv, lx, ty, 2, "Finished", "no charge seen yet", iw);
                Text(cv, lx, ty, 3, "Lifetime", J.Has(f, "L") ? (J.I(f, "L", 0) / 1000.0).ToString("#,##0.000", Inv) + " kWh" : "-", iw);
            }
            else
            {
                cv.Put(lx + 2, ty + 1, Clip("no telemetry since the helper", iw));
                cv.Put(lx + 2, ty + 2, "started");
            }
            string up = "?";
            DateTime started;
            if (DateTime.TryParse(J.S(st, "started", ""), Inv, DateTimeStyles.None, out started)) up = Dur((now - started).TotalSeconds);
            Chip(cv, lx, ty, 5, "Helper", alive ? "RUNNING" : "STOPPED", alive ? T.Ok : T.Bad, " up " + up, iw);
            string ws = J.S(w, "state", "?");
            int[] wcol = ws == "attached" ? T.Ok
                : (ws == "reattaching" || ws == "silent" || ws == "rebooting" || ws == "starting" || ws == "released") ? T.Warn : T.Bad;
            string since = Hms(J.S(w, "since", null));
            Chip(cv, lx, ty, 6, "Link", ws, wcol, " since " + (since.Length >= 5 ? since.Substring(0, 5) : since), iw);
            object r = J.Get(st, "resolver");
            string lastAsk = Hms(J.S(r, "last_hijack", null));
            Text(cv, lx, ty, 7, "Resolver", J.Has(r, "last_hijack")
                ? J.I(r, "hijacks", 0) + " answers at " + (lastAsk.Length >= 5 ? lastAsk.Substring(0, 5) : lastAsk)
                : "no requests yet", iw);

            // --- Gauges: every reading that has a scale, charger first, then the limits
            bool single = Style.Of(T).Single;                    // every window but the main one
            cv.Window(rx, ty, ww, th, "Gauges", T.Win, T.Shadow, null, single, null, S.Tight);
            if (J.Has(t, "last"))
            {
                double a = J.I(f, "A", 0) / 10.0, v = J.I(f, "V", 0) / 10.0;
                int temp = J.I(f, "T", 0);
                Bar(cv, T, rx, ty, 0, "Current", a, circ, a.ToString("0.0", Inv) + " A", cap, a > cap + 0.05, bw);
                Bar(cv, T, rx, ty, 1, "Volts", v - 200, 60, v.ToString("0.0", Inv) + " V", -1, !(v >= 210 && v <= 255), bw);
                Bar(cv, T, rx, ty, 2, "Power", a * v / 1000.0, circ * 0.24, (a * v / 1000.0).ToString("0.00", Inv) + " kW", -1, false, bw);
                Bar(cv, T, rx, ty, 3, "Temp", temp, 80, temp + " C", -1, temp > 60, bw);
            }
            else
            {
                string[] names = { "Current", "Volts", "Power", "Temp" };
                for (int i = 0; i < names.Length; i++) Text(cv, rx, ty, i, names[i], "-", iw);
            }
            if (!J.Has(w, "module_faults")) Text(cv, rx, ty, 4, "Faults", "unknown", iw);
            else
            {
                int nf = J.I(w, "module_faults", 0);
                Bar(cv, T, rx, ty, 4, "Faults", nf, 8, nf + "/8", 6, nf > 5, bw);
            }
            int nr = J.I(w, "reboots_24h", 0), nc = J.I(lim, "corrections_24h", 0);
            Bar(cv, T, rx, ty, 5, "Reboots", nr, 4, nr + "/4", -1, nr >= 4, bw);
            Bar(cv, T, rx, ty, 6, "Fixes", nc, 12, nc + "/12", -1, nc >= 12, bw);
            object rv = J.Get(J.Get(st, "beacon"), "rssi");
            if (rv is int) Bar(cv, T, rx, ty, 7, "Signal", (int)rv + 90, 50, (int)rv + " dBm", -1, (int)rv < -75, bw);
            else Text(cv, rx, ty, 7, "Signal", "no beacon", iw);

            // --- Chart: current per minute
            int nb = iw - 6, px = lx + 8, prows = chh - 3;      // minutes shown, first plot column, plot rows
            int bottom = cy + prows;
            cv.Window(lx, cy, ww, chh, "Current per minute", T.Win, T.Shadow, null, single, null, S.Tight);
            if (hist != null)
            {
                cv.Put(lx + 2, cy + 1, circ.ToString().PadLeft(2) + " A");
                cv.Put(lx + 2, bottom, " 0 A");
                if (cap > 0 && cap < circ) cv.Put(lx + 2, bottom - (int)((double)cap / circ * prows), cap.ToString().PadLeft(2) + " A");
                for (int i = 0; i < nb; i++)
                {
                    string key = now.AddMinutes(-(nb - 1 - i)).ToString("yyyy-MM-dd'T'HH:mm", Inv);
                    double a;
                    if (hist.Amps.TryGetValue(key, out a))
                    {
                        if (a > 0) Column(cv, px + i, bottom, prows, a / circ, 1, a > cap + 0.05 ? T.FillBad : T.Fill);
                        else cv.Put(px + i, bottom, "_");
                    }
                }
                cv.Put(px, bottom + 1, "-" + nb + "m");
                cv.Put(px + nb - 3, bottom + 1, "now");
                for (int i = 0; i < nb; i++)                    // mark the minute the charge finished
                    if (done != null && now.AddMinutes(-(nb - 1 - i)).ToString("yyyy-MM-dd'T'HH:mm", Inv) == done.Substring(0, 16))
                        cv.Put(px + i, bottom + 1, "▼", T.Fill, -1);
            }
            else cv.Put(lx + 2, cy + 1, Clip("no telemetry.log to chart", iw));

            // --- Chart: energy per day
            cv.Window(rx, cy, ww, chh, "Energy per day", T.Win, T.Shadow, null, single, null, S.Tight);
            if (hist != null && hist.DayKwh.Length > 0)
            {
                int n0 = hist.DayKwh.Length, first = Math.Max(0, n0 - (chh - 2));
                double top = 0;
                for (int i = first; i < n0; i++) if (!double.IsNaN(hist.DayKwh[i]) && hist.DayKwh[i] > top) top = hist.DayKwh[i];
                if (top <= 0) top = 1;
                int dbw = iw - 13;
                for (int i = first; i < n0; i++)                 // one horizontal bar per day
                {
                    int y = cy + 1 + (i - first);
                    double kwh = hist.DayKwh[i];
                    cv.Put(rx + 2, y, hist.DayLabels[i].PadRight(2));
                    cv.Put(rx + 5, y, new string(Canvas.EMPTY, Math.Max(0, dbw)), T.Trough[0], T.Trough[1]);
                    if (double.IsNaN(kwh)) { cv.Put(rx + 6 + dbw, y, "    -"); continue; }
                    int eighths = (int)Math.Round(kwh / top * dbw * 8);
                    if (kwh > 0 && eighths == 0) eighths = 1;
                    int full = eighths / 8, part = eighths % 8;
                    cv.Put(rx + 5, y, new string(Canvas.FULL, full), T.Fill, T.Trough[1]);
                    if (part > 0) cv.Put(rx + 5 + full, y, ((char)(0x2590 - part)).ToString(), T.Fill, T.Trough[1]);
                    cv.Put(rx + 6 + dbw, y, kwh.ToString("0.0", Inv).PadLeft(5) + " kWh");
                }
            }
            else cv.Put(rx + 2, cy + 1, Clip("no telemetry.log to chart", iw));

            // --- Event log
            cv.Window(lx, by, fw, bh, "Event log", T.Log, T.Shadow, null, single, null, S.Tight);
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
                    const int days = 8;
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

    // Colours and drawing choices for menus and dialogs, derived from a theme. juicebox_helper.py
    // has the same table (_style) and explains the three period styles and their sources:
    //   tv    Borland Turbo Vision     nc    Norton Commander / FAR     mono  one-hue screens
    //   vb    Visual Basic for MS-DOS 1.0
    class Style
    {
        public string Family, Buttons, Status;
        public bool CloseBox, Single, Tight;    // Tight: frame lines touch titles and are the edge of a menu box
        public int[] StatusBar, TitleBar, BarSelHot;      // set only where a style has them
        public int[] BarHot, Menu, MenuHot, Sel, SelHot, Dlg, Frame, Icon, Err, ErrFocus, ErrHot, Btn, BtnHot, Focus, FocusHot, Input, InputSel;

        static int[] P(int fg, int bg) { return new int[] { fg, bg }; }

        public static Style Of(Theme T)
        {
            string fam = T.Name == "commander" ? "nc" : T.Name == "vbdos" ? "vb"
                : (T.Name == "phosphor" || T.Name == "amber" || T.Name == "mono") ? "mono" : "tv";
            int[] bar = T.Bar, bright = T.Main;
            if (fam == "vb")
                return new Style { Family = fam, Buttons = "vb", Status = "vb", CloseBox = false, Single = true,
                    BarHot = bar, BarSelHot = P(37, 40), Menu = bar, MenuHot = P(97, 47), Sel = P(37, 40), SelHot = P(97, 40),
                    Dlg = P(30, 47), Frame = P(30, 47),
                    Btn = P(30, 47), BtnHot = P(97, 47), Focus = P(37, 40), FocusHot = P(97, 40),
                    Input = P(30, 47), InputSel = P(37, 40),
                    StatusBar = P(30, 46), TitleBar = P(97, 45), Tight = true };
            if (fam == "tv")
            {
                int[] hot = P(T.Key, bar[1]);
                return new Style { Family = fam, Buttons = "tv", Status = "tv", CloseBox = true, Single = true,
                    BarHot = hot, Menu = bar, MenuHot = hot, Sel = P(30, 42), SelHot = P(31, 42),
                    Dlg = P(30, 47), Frame = P(97, 47), Icon = P(92, 47),
                    Btn = P(30, 42), BtnHot = P(93, 42), Focus = P(97, 42), FocusHot = P(93, 42),
                    Input = P(97, 44), InputSel = P(97, 42) };
            }
            if (fam == "nc")
                return new Style { Family = fam, Buttons = "far", Status = "fn", CloseBox = false, Single = false,
                    BarHot = P(93, bar[1]), Menu = P(97, 46), MenuHot = P(93, 46), Sel = P(97, 40), SelHot = P(93, 40),
                    Dlg = P(30, 47), Frame = P(30, 47), Err = P(97, 41), ErrFocus = P(30, 47), ErrHot = P(93, 41),
                    Btn = P(30, 47), BtnHot = P(93, 47), Focus = P(30, 46), FocusHot = P(93, 46),
                    Input = P(30, 46), InputSel = P(97, 40) };
            int[] lit = P(30, bar[1] + 60);                 // one hue: a brighter cell stands in for colour
            return new Style { Family = fam, Buttons = "cua", Status = "kv", CloseBox = false, Single = false,
                BarHot = lit, Menu = bar, MenuHot = lit, Sel = bright, SelHot = bar,
                Dlg = T.Win, Frame = P(bright[0], T.Win[1]),
                Btn = T.Win, BtnHot = P(bright[0], T.Win[1]), Focus = bar, FocusHot = lit,
                Input = bar, InputSel = bright };
        }
    }

    // The menu bar, pull-down menus and dialogs. juicebox_helper.py carries the same ones for the
    // terminal screen (class _Ui); change both together. Keys behave the same in every theme; a
    // theme changes only how things are drawn.
    //
    // The monitor never talks to the charger. A control writes one value into helper.json, which the
    // running helper re-reads: target_amps is the limit it keeps, clear_faults is a one-shot request
    // it handles once and removes. Each asks Yes or No first, with No as the default.
    class Ui
    {
        class Item { public string Label, Key = "", Action, Hint; public int Hot = -1; }

        class Menu { public string Title; public int Hot; public List<Item> Items = new List<Item>(); }

        class Dialog
        {
            public string Kind, Title, Value = "", Error = "", No, Do, Tone = "";
            public List<string> Lines = new List<string>();
            public int Focus, Default, Top, Now, Amps;
            public bool Fresh;
        }

        const int MinAmps = 6, MaxAmps = 40;
        static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        readonly string dataDir;
        readonly List<Menu> menus = new List<Menu>();
        int menu = -1, item;
        bool opened;
        Dialog dlg;
        string said;
        DateTime saidUntil;
        // Where the last Draw put things, for mouse clicks.
        readonly List<Rectangle> titleAt = new List<Rectangle>(), itemAt = new List<Rectangle>(), buttonAt = new List<Rectangle>();
        Rectangle closeAt;

        public Dictionary<string, object> St;
        public double Age = 9999;
        public int ThemeIx;
        public string HelperVersion = "1.0";
        public Action<int> ThemeChosen;

        public Ui(string dataDir)
        {
            this.dataDir = dataDir;
            Menu sys = new Menu { Title = "Help", Hot = 0 };
            sys.Items.Add(new Item { Label = "Gauges...", Hot = 0, Key = "F1", Action = "help", Hint = "What each gauge shows" });
            sys.Items.Add(new Item { Label = "About OpenJuice...", Hot = 0, Action = "about", Hint = "What this screen is" });
            Menu charger = new Menu { Title = "Charger", Hot = 0 };
            charger.Items.Add(new Item { Label = "Set current limit...", Hot = 12, Key = "F2", Action = "limit", Hint = "Change the current limit" });
            charger.Items.Add(new Item { Label = "Clear fault log...", Hot = 6, Key = "F8", Action = "faults", Hint = "Clear the module's fault log" });
            Menu themes = new Menu { Title = "Theme", Hot = 0 };
            string used = "";
            foreach (Theme t in Theme.All)
            {
                int hot = 0;
                while (used.IndexOf(t.Name[hot]) >= 0) hot++;
                used += t.Name[hot];
                themes.Items.Add(new Item { Label = t.Name, Hot = hot, Action = "theme:" + t.Name, Hint = "Switch to the " + t.Name + " theme" });
            }
            menus.Add(charger); menus.Add(themes); menus.Add(sys);
        }

        public bool Active { get { return menu >= 0 || dlg != null; } }

        void Say(string text) { said = text; saidUntil = DateTime.Now.AddSeconds(4); }

        void Close() { menu = -1; opened = false; }

        void Open(int index, bool show)
        {
            menu = (index + menus.Count) % menus.Count;
            opened = show;
            item = menus[menu].Title == "Theme" ? Math.Min(ThemeIx, menus[menu].Items.Count - 1) : 0;
        }

        int TitleFor(string letter)
        {
            for (int i = 0; i < menus.Count; i++)
                if (menus[i].Hot >= 0 && menus[i].Title.Substring(menus[i].Hot, 1).ToLowerInvariant() == letter) return i;
            return -1;
        }

        // ---- keys: names as in the terminal screen ----
        public bool Key(string k)
        {
            if (dlg != null) return DialogKey(k);
            if (menu >= 0) return MenuKey(k);
            if (k == "f10" || k == "f9" || k == "m") Open(0, false);       // highlights the first menu; Enter opens it
            else if (k.StartsWith("alt+") && TitleFor(k.Substring(4)) >= 0) Open(TitleFor(k.Substring(4)), true);
            else if (k == "t" || k == "f5") Run("theme:" + Theme.All[(ThemeIx + 1) % Theme.All.Length].Name);
            else if (k == "f1") Run("help");
            else if (k == "f2" || k == "l") Run("limit");
            else if (k == "f8" || k == "f") Run("faults");
            else return false;
            return true;
        }

        // A menu is modal: every key is used here, and letters mean this menu's own items.
        bool MenuKey(string k)
        {
            List<Item> items = menus[menu].Items;
            if (k == "esc" || k == "f10" || k == "f9") Close();
            else if (k == "left" || k == "right") Open(menu + (k == "right" ? 1 : -1), opened);
            else if (k.StartsWith("alt+") && TitleFor(k.Substring(4)) >= 0) Open(TitleFor(k.Substring(4)), true);
            else if (!opened)
            {
                if (k == "enter" || k == "down" || k == "up") opened = true;
                else if (k.Length == 1 && TitleFor(k) >= 0) Open(TitleFor(k), true);
            }
            else if (k == "up" || k == "down") item = (item + (k == "down" ? 1 : items.Count - 1)) % items.Count;
            else if (k == "home") item = 0;
            else if (k == "end") item = items.Count - 1;
            else if (k == "enter") Run(items[item].Action);
            else if (k.Length == 1)
                foreach (Item it in items)
                    if (it.Hot >= 0 && it.Label.Substring(it.Hot, 1).ToLowerInvariant() == k) { Run(it.Action); break; }
            return true;
        }

        int Target()
        {
            try
            {
                object cfg = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(dataDir, "helper.json")));
                return J.I(cfg, "target_amps", 26);
            }
            catch { return 26; }
        }

        void Info(string title, string tone, params string[] lines)
        {
            dlg = new Dialog { Kind = "info", Title = title, Tone = tone };
            dlg.Lines.AddRange(lines);
        }

        public void Run(string action)
        {
            Close();
            if (action.StartsWith("theme:"))
            {
                if (ThemeChosen != null) ThemeChosen(Theme.IndexOf(action.Substring(6)));
                return;
            }
            if (action == "help")                                // the same wording as the terminal screen's
            {
                Info("Gauges", "",
                    "Current  Amps going to the vehicle now. The scale is the circuit",
                    "         rating; the tick is the maximum charging rate in force.",
                    "Volts    Supply voltage at the charger. Red outside 210 to 255 V.",
                    "Power    Charger power in kW: amps times volts.",
                    "Temp     Temperature inside the charger. Red above 60 C.",
                    "Faults   Crashes logged by the charger's WiFi module. At 8 it",
                    "         enters Safe Mode; this helper stops taking control at 6",
                    "         (the tick). Clear the log from the Charger menu.",
                    "Reboots  Times in 24 hours this helper rebooted the WiFi module",
                    "         to recover it. The helper allows itself 4 a day.",
                    "Fixes    Times in 24 hours this helper put the maximum charging",
                    "         rate back after the charger reported a different one.",
                    "         The helper allows itself 12 a day, because each one",
                    "         is written to the charger's memory.",
                    "Signal   WiFi signal at the charger. Red below -75 dBm.");
                return;
            }
            if (action == "about")
            {
                Info("About", "", "OpenJuice status screen", "JuiceBox Gen 1 under local control", "Helper " + HelperVersion);
                return;
            }
            if (St == null || Age >= 30)
            {
                Info("Helper not running", "err", "The helper is not running,", "so nothing was sent.");
                return;
            }
            if (action == "limit")
            {
                object f = J.Get(J.Get(St, "telemetry"), "fields");
                int top = Math.Max(MinAmps, Math.Min(MaxAmps, J.I(f, "m", MaxAmps))), now = Target();
                dlg = new Dialog { Kind = "input", Title = "Set current limit", Top = top, Now = now, Value = now.ToString(Inv), Fresh = true };
                dlg.Lines.Add("Limit in amps, " + MinAmps + " to " + top + ":");
            }
            else if (action == "faults")
            {
                object w = J.Get(St, "watchdog");
                string count = J.Has(w, "module_faults") ? J.I(w, "module_faults", 0) + " of 8" : "count unknown";
                dlg = new Dialog { Kind = "confirm", Title = "Clear fault log", Focus = 1, Default = 1, Do = "clear", Tone = "err", No = "Fault log left as it is." };
                dlg.Lines.Add("Clear the charger's fault log (" + count + ")?");
                dlg.Lines.Add("It is copied to helper.log first, then");
                dlg.Lines.Add("permanently cleared on the charger.");
            }
        }

        bool DialogKey(string k)
        {
            Dialog d = dlg;
            if (d.Kind == "info")
            {
                if (k == "enter" || k == "esc" || k == " " || k == "o") dlg = null;
                return true;
            }
            int v;
            if (k == "left" || k == "right" || k == "tab" || k == "shift+tab") d.Focus = 1 - d.Focus;
            else if (k == "esc") Answer(false);
            else if (k == "enter" || k == " ") Answer(d.Focus == 0);
            else if (d.Kind == "confirm")
            {
                if (k == "y" || k == "n") Answer(k == "y");
            }
            else if (k == "o" || k == "c") Answer(k == "o");
            else if (k == "backspace") { d.Value = d.Fresh || d.Value.Length == 0 ? "" : d.Value.Substring(0, d.Value.Length - 1); d.Fresh = false; }
            else if (k == "up" || k == "down")
            {
                if (!int.TryParse(d.Value, out v)) v = d.Now;
                v += k == "up" ? 1 : -1;
                d.Value = Math.Max(MinAmps, Math.Min(d.Top, v)).ToString(Inv);
                d.Fresh = false;
            }
            else if (k.Length == 1 && k[0] >= '0' && k[0] <= '9')
            {
                d.Value = d.Fresh ? k : (d.Value + k);
                if (d.Value.Length > 2) d.Value = d.Value.Substring(0, 2);
                d.Fresh = false;
            }
            return true;
        }

        // The close box, or anything else that dismisses a dialog without an answer.
        void Cancel()
        {
            if (dlg == null) return;
            if (dlg.Kind == "info") dlg = null; else Answer(false);
        }

        void Answer(bool yes)
        {
            Dialog d = dlg;
            dlg = null;
            if (d.Kind == "input")
            {
                if (!yes) { Say("Limit left at " + d.Now + " A."); return; }
                int amps;
                if (!int.TryParse(d.Value, out amps)) amps = 0;
                if (amps < MinAmps || amps > d.Top)
                {
                    d.Error = "Enter " + MinAmps + " to " + d.Top + ".";
                    d.Fresh = true;
                    dlg = d;
                    return;
                }
                dlg = new Dialog { Kind = "confirm", Title = "Set current limit", Focus = 1, Default = 1, Do = "target", Amps = amps, No = "Limit left at " + d.Now + " A." };
                dlg.Lines.Add("Set the charger's current limit to " + amps + " A?");
                dlg.Lines.Add("It is " + d.Now + " A now.");
                return;
            }
            if (!yes) { Say(d.No); return; }
            string err = d.Do == "target"
                ? Write("target_amps", d.Amps)
                : Write("clear_faults", DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss", Inv));
            if (err != null) Say("Could not write helper.json: " + err);
            else Say(d.Do == "target" ? "Asked the helper for a " + d.Amps + " A limit." : "Asked the helper to clear the fault log.");
        }

        // Returns null, or why the setting could not be written.
        string Write(string key, object value)
        {
            string path = Path.Combine(dataDir, "helper.json"), tmp = path + ".monitor.tmp";
            try
            {
                Dictionary<string, object> cfg = null;
                if (File.Exists(path))
                {
                    // An unreadable file is left alone: writing a fresh one would drop its other settings.
                    cfg = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
                    if (cfg == null) throw new InvalidDataException("it is not a settings object");
                }
                else cfg = new Dictionary<string, object>();
                cfg[key] = value;
                File.WriteAllText(tmp, new JavaScriptSerializer().Serialize(cfg), new UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(tmp, path, null); else File.Move(tmp, path);
                return null;
            }
            catch (Exception e) { return e.Message; }
        }

        // ---- mouse: a click on a cell of the last drawing ----
        static int Hit(List<Rectangle> at, int cx, int cy)
        {
            for (int i = 0; i < at.Count; i++) if (at[i].Contains(cx, cy)) return i;
            return -1;
        }

        public bool Click(int cx, int cy)
        {
            int i;
            if (dlg != null)
            {
                if (closeAt.Contains(cx, cy)) { Cancel(); return true; }
                i = Hit(buttonAt, cx, cy);
                if (i < 0) return false;                      // a dialog is modal
                if (dlg.Kind == "info") dlg = null; else Answer(i == 0);
                return true;
            }
            i = Hit(titleAt, cx, cy);
            if (i >= 0) { if (menu == i && opened) Close(); else Open(i, true); return true; }
            if (menu < 0) return false;
            i = opened ? Hit(itemAt, cx, cy) : -1;
            if (i >= 0) Run(menus[menu].Items[i].Action); else Close();
            return true;
        }

        // ---- drawing ----
        static void Put(Canvas cv, int x, int y, string s, int[] c) { cv.Put(x, y, s, c[0], c[1]); }

        void StatusLine(Canvas cv, Style S, int[] bar)
        {
            int W = cv.W, y = cv.Hgt - 1;
            if (S.StatusBar != null) bar = S.StatusBar;
            cv.Fill(0, y, W, 1, ' ', bar[0], bar[1]);
            string note = "";                                   // the highlighted menu item's hint
            if (menu >= 0 && opened) note = menus[menu].Items[item].Hint;
            if (S.Status == "vb")                               // F1=Help | what the keys do now | clock
            {
                if (note.Length == 0 && said != null && DateTime.Now < saidUntil) note = said;
                else if (note.Length == 0 && dlg != null) note = "Enter=Execute   Esc=Cancel   Tab=Next Field";
                else if (note.Length == 0) note = "F10=Menu   L=Limit   F=Faults   T=Theme";
                int room = Math.Max(0, W - 34);
                cv.Put(1, y, "F1=Help");
                cv.Put(9, y, Canvas.SEP.ToString());
                cv.Put(11, y, note.Length > room ? note.Substring(0, Math.Max(0, room - 3)) + "..." : note);
                cv.Put(W - 22, y, Canvas.SEP.ToString());
                cv.Put(W - 20, y, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", Inv));
                return;
            }
            if (note.Length == 0 && said != null && DateTime.Now < saidUntil)
            {
                cv.Put(1, y, said.Length > W - 2 ? said.Substring(0, W - 2) : said);   // a result takes the whole line
                return;
            }
            if (S.Status == "fn")                               // ten numbered cells; unbound keys stay blank
            {
                if (note.Length > 0) { cv.Put(1, y, note); return; }
                string[] labels = { "Help", "Limit", "", "", "Theme", "", "", "Faults", "Menu", "Menu" };
                int cell = W / 10;
                for (int i = 0; i < 10; i++)
                {
                    cv.Put(i * cell, y, (i + 1).ToString(Inv).PadLeft(2), 37, 40);
                    cv.Put(i * cell + 2, y, labels[i].PadRight(cell - 2).Substring(0, cell - 2), 30, 46);
                }
                cv.Fill(10 * cell, y, W - 10 * cell, 1, ' ', 30, 46);
                return;
            }
            string[][] keys = { new string[] { "F10", "Menu" }, new string[] { "L", "Limit" }, new string[] { "F", "Faults" }, new string[] { "T", "Theme" } };
            int x = 1;
            foreach (string[] k in keys)
            {
                if (S.Status == "kv") cv.Put(x, y, k[0].Replace("-", "+") + "=" + k[1]);       // Key=Action
                else { Put(cv, x, y, k[0], S.BarHot); cv.Put(x + k[0].Length + 1, y, k[1]); }
                x += k[0].Length + k[1].Length + 3;
            }
            if (note.Length > 0)
            {
                int room = Math.Max(0, W - x - 3);
                cv.Put(x, y, Canvas.SEP + " " + (note.Length > room ? note.Substring(0, room) : note));
            }
        }

        public void Draw(Canvas cv, Theme T)
        {
            Style S = Style.Of(T);
            int[] bar = T.Bar;
            int W = cv.W, H = cv.Hgt;
            titleAt.Clear(); itemAt.Clear(); buttonAt.Clear(); closeAt = Rectangle.Empty;
            bool clockBelow = S.Status == "vb";                 // that style keeps the clock on the status line
            cv.Fill(0, 0, clockBelow ? W : Math.Max(0, W - 21), 1, ' ', bar[0], bar[1]);          // menu bar, left of the clock
            int x = 1;
            int[] xs = new int[menus.Count];
            for (int i = 0; i < menus.Count; i++)
            {
                Menu m = menus[i];
                string name = m.Title;
                xs[i] = x;
                if (i == menu)
                {
                    Put(cv, x, 0, " " + name + " ", S.Sel);
                    if (m.Hot >= 0) Put(cv, x + 1 + m.Hot, 0, name.Substring(m.Hot, 1), S.BarSelHot ?? S.SelHot);
                }
                else
                {
                    cv.Put(x + 1, 0, name);
                    if (m.Hot >= 0) Put(cv, x + 1 + m.Hot, 0, name.Substring(m.Hot, 1), S.BarHot);
                }
                titleAt.Add(new Rectangle(x, 0, name.Length + 2, 1));
                x += name.Length + 2;
            }
            StatusLine(cv, S, bar);

            if (menu >= 0 && opened)
            {
                List<Item> items = menus[menu].Items;
                bool mark = menus[menu].Title == "Theme";
                int inner = 0;
                foreach (Item it in items) inner = Math.Max(inner, it.Label.Length + (it.Key.Length > 0 ? it.Key.Length + 2 : 0));
                inner += 2 + (mark ? 2 : 0);
                int mx = xs[menu] - 1, my = 1, mw = inner + 4, mh = items.Count + 2;     // a blank column outside the frame
                string rule = new string(Canvas.SH, inner);
                int edge = S.Tight ? 1 : 0;                     // ...except where the frame is the edge of the box
                cv.Shade(mx + 2 + edge, my + 1, mw - 2 * edge, mh, T.Shadow[0], T.Shadow[1]);
                cv.Fill(mx + edge, my, mw - 2 * edge, mh, ' ', S.Menu[0], S.Menu[1]);
                cv.Put(mx + 1, my, Canvas.STL + rule + Canvas.STR);
                cv.Put(mx + 1, my + mh - 1, Canvas.SBL + rule + Canvas.SBR);
                for (int i = 0; i < items.Count; i++)
                {
                    Item it = items[i];
                    int y = my + 1 + i;
                    cv.Put(mx + 1, y, Canvas.SEP.ToString());
                    cv.Put(mx + mw - 2, y, Canvas.SEP.ToString());
                    string lead = mark ? (i == ThemeIx ? Canvas.DOT + " " : "  ") : "";
                    string row = (" " + lead + it.Label).PadRight(inner);
                    if (it.Key.Length > 0) row = row.Substring(0, inner - 1 - it.Key.Length) + it.Key + " ";
                    bool chosen = i == item;
                    Put(cv, mx + 2, y, row, chosen ? S.Sel : S.Menu);
                    if (it.Hot >= 0) Put(cv, mx + 3 + lead.Length + it.Hot, y, it.Label.Substring(it.Hot, 1), chosen ? S.SelHot : S.MenuHot);
                    itemAt.Add(new Rectangle(mx + 2, y, inner, 1));
                }
            }

            Dialog d = dlg;
            if (d == null) return;
            if (S.Buttons == "vb") { DialogVb(cv, T, S, d); return; }
            bool err = d.Tone == "err" && S.Err != null;
            int[] body = err ? S.Err : S.Dlg, frame = err ? S.Err : S.Frame;
            int[] btn = err ? body : S.Btn, btnhot = err ? S.ErrHot : S.BtnHot;
            int[] focus = err ? S.ErrFocus : S.Focus, focushot = err ? S.ErrFocus : S.FocusHot;
            string[] buttons = d.Kind == "confirm" ? new string[] { "Yes", "No" } : d.Kind == "input" ? new string[] { "OK", "Cancel" } : new string[] { "OK" };
            bool tv = S.Buttons == "tv";
            int dw = Math.Max(30, d.Title.Length + 4);
            foreach (string s in d.Lines) dw = Math.Max(dw, s.Length);
            dw += 6;
            int dh = d.Lines.Count + (d.Kind == "input" ? 7 : 5) + (tv ? 1 : 0);
            int dx = (W - dw) / 2, dy = Math.Max(2, (H - dh) / 2 - 2);
            cv.Window(dx, dy, dw, dh, d.Title, body, T.Shadow, frame, false);
            if (S.CloseBox)
            {
                Put(cv, dx + 2, dy, "[" + Canvas.BOX + "]", frame);
                Put(cv, dx + 3, dy, Canvas.BOX.ToString(), S.Icon);
                closeAt = new Rectangle(dx + 2, dy, 3, 1);
            }
            for (int i = 0; i < d.Lines.Count; i++) Put(cv, dx + 3, dy + 2 + i, d.Lines[i], body);
            int by = dy + 2 + d.Lines.Count;
            if (d.Kind == "input")
            {
                Put(cv, dx + 3, by, new string(' ', 6), S.Input);
                Put(cv, dx + 4, by, d.Value, d.Fresh ? S.InputSel : S.Input);
                if (!d.Fresh) cv.Put(dx + 4 + d.Value.Length, by, " ", S.Input[1] - 10, S.Input[0] + 10);   // a block cursor
                Put(cv, dx + 11, by, d.Error, body);
                by += 2;
            }
            else by += 1;
            string[] shown = new string[buttons.Length];
            int width = 2 * (buttons.Length - 1);
            for (int i = 0; i < buttons.Length; i++)
            {
                string b = buttons[i];
                if (tv) shown[i] = new string(' ', (10 - b.Length) / 2) + b + new string(' ', 10 - b.Length - (10 - b.Length) / 2);
                else if (S.Buttons == "far") shown[i] = (i == d.Default ? "{ " : "[ ") + b + (i == d.Default ? " }" : " ]");   // FAR marks the default with braces
                else shown[i] = "< " + b + " >";
                width += shown[i].Length;
            }
            x = dx + (dw - width) / 2;
            for (int i = 0; i < buttons.Length; i++)
            {
                string text = shown[i];
                bool on = i == d.Focus;
                int hot = text.IndexOf(buttons[i]);
                Put(cv, x, by, text, on ? focus : btn);
                Put(cv, x + hot, by, text.Substring(hot, 1), on ? focushot : btnhot);
                if (tv)                                         // half-block shadow to the right and below
                {
                    cv.Put(x + text.Length, by, Canvas.LOWER.ToString(), 30, body[1]);
                    cv.Put(x + 1, by + 1, new string(Canvas.UPPER, text.Length), 30, body[1]);
                }
                else if (S.Buttons == "cua" && i == d.Default && !on)
                {
                    Put(cv, x, by, "<", S.BtnHot);              // the default button's brackets are bright
                    Put(cv, x + text.Length - 1, by, ">", S.BtnHot);
                }
                buttonAt.Add(new Rectangle(x, by, text.Length, 1));
                x += text.Length + 2;
            }
        }

        // A 3-row box whose top and left edges are one colour and its bottom and right another.
        static void Box(Canvas cv, int x, int y, int w, int lit, int dark, int bg, bool dbl)
        {
            char hz = dbl ? Canvas.H : Canvas.SH, vt = dbl ? Canvas.V : Canvas.SEP;
            char tl = dbl ? Canvas.TL : Canvas.STL, tr = dbl ? Canvas.TR : Canvas.STR, bl = dbl ? Canvas.BL : Canvas.SBL, br = dbl ? Canvas.BR : Canvas.SBR;
            string rule = new string(hz, w - 2);
            cv.Put(x, y, tl + rule, lit, bg);
            cv.Put(x + w - 1, y, tr.ToString(), dark, bg);
            cv.Put(x, y + 1, vt.ToString(), lit, bg);
            cv.Put(x + 1, y + 1, new string(' ', w - 2), dark, bg);
            cv.Put(x + w - 1, y + 1, vt.ToString(), dark, bg);
            cv.Put(x, y + 2, bl.ToString(), lit, bg);
            cv.Put(x + 1, y + 2, rule + br, dark, bg);
        }

        // A VBDOS dialog: a frameless panel under a title strip, 3-D buttons, a sunken input box.
        void DialogVb(Canvas cv, Theme T, Style S, Dialog d)
        {
            int W = cv.W, H = cv.Hgt;
            int[] body = S.Dlg;
            string[] names = d.Kind == "confirm" ? new string[] { "Yes", "No" } : d.Kind == "input" ? new string[] { "OK", "Cancel" } : new string[] { "OK" };
            int dw = Math.Max(30, d.Title.Length + 4);
            foreach (string line in d.Lines) dw = Math.Max(dw, line.Length);
            dw += 6;
            int dh = d.Lines.Count + (d.Kind == "input" ? 11 : 7);
            int dx = (W - dw) / 2, dy = Math.Max(2, (H - dh) / 2 - 2);
            cv.Shade(dx + 2, dy + 1, dw, dh, T.Shadow[0], T.Shadow[1]);
            cv.Fill(dx, dy, dw, dh, ' ', body[0], body[1]);
            cv.Fill(dx, dy, dw, 1, ' ', S.TitleBar[0], S.TitleBar[1]);
            cv.Put(dx + (dw - d.Title.Length) / 2, dy, d.Title);
            for (int i = 0; i < d.Lines.Count; i++) cv.Put(dx + 3, dy + 2 + i, d.Lines[i]);
            int y = dy + 2 + d.Lines.Count;
            if (d.Kind == "input")
            {
                Box(cv, dx + 3, y, 8, body[0], 97, body[1], false);          // sunken: dark top and left
                Put(cv, dx + 5, y + 1, d.Value, d.Fresh ? S.InputSel : body);
                if (!d.Fresh) Put(cv, dx + 5 + d.Value.Length, y + 1, " ", S.InputSel);     // a block cursor
                cv.Put(dx + 13, y + 1, d.Error);
                y += 4;
            }
            else y += 1;
            int total = 2 * (names.Length - 1);
            int[] widths = new int[names.Length];
            for (int i = 0; i < names.Length; i++) { widths[i] = Math.Max(names[i].Length + 4, 8); total += widths[i]; }
            int x = dx + (dw - total) / 2;
            for (int i = 0; i < names.Length; i++)
            {
                bool on = i == d.Focus;
                Box(cv, x, y, widths[i], 97, body[0], body[1], on);          // raised; double-lined with focus
                int at = x + 1 + (widths[i] - 2 - names[i].Length) / 2;
                Put(cv, at, y + 1, names[i], on ? S.Focus : body);
                Put(cv, at, y + 1, names[i].Substring(0, 1), on ? S.FocusHot : S.BtnHot);
                buttonAt.Add(new Rectangle(x, y, widths[i], 3));
                x += widths[i] + 2;
            }
        }

        // For --snapshot and --dump: press these keys first (never ones that answer Yes).
        public void Pose(string what)
        {
            foreach (string k in what.Split(',')) if (k.Length > 0) Key(k == "space" ? " " : k);
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
        readonly Dictionary<int, SolidBrush> brushes = new Dictionary<int, SolidBrush>();
        ToolStripMenuItem chimeItem;
        Canvas canvas;
        int theme;
        bool quitting, startHidden;
        ToolStripMenuItem startupItem;
        readonly Ui ui;

        public MonitorForm(string dataDir, bool startHidden)
        {
            this.dataDir = dataDir;
            ui = new Ui(dataDir);
            ui.ThemeChosen = delegate(int idx) { SetTheme(idx); };
            this.startHidden = startHidden;
            Text = "OpenJuice Monitor";
            font = Program.MakeFont();
            Program.Measure(font, out cw, out ch);
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            ClientSize = new Size(80 * cw, 32 * ch);
            MinimumSize = SizeFromClientSize(new Size(80 * cw, 30 * ch));
            StartPosition = FormStartPosition.CenterScreen;
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
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Set current limit...", null, delegate { Control("limit"); }));
            menu.Items.Add(new ToolStripMenuItem("Clear fault log...", null, delegate { Control("faults"); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Test chime", null, delegate { Chime(null, null); }));
            menu.Items.Add(new ToolStripMenuItem("Test error notification", null, delegate { lastKind = null; Watch("error"); }));
            startupItem = new ToolStripMenuItem("Start with Windows, in the tray") { CheckOnClick = true, Checked = AutoStart.Enabled };
            startupItem.Click += delegate { AutoStart.Set(startupItem.Checked); startupItem.Checked = AutoStart.Enabled; };
            menu.Items.Add(startupItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Exit", null, delegate { quitting = true; Close(); }));
            menu.Opening += delegate
            {
                startupItem.Checked = AutoStart.Enabled;
                for (int i = 0; i < themes.DropDownItems.Count; i++) ((ToolStripMenuItem)themes.DropDownItems[i]).Checked = i == theme;
            };
            ContextMenuStrip = menu;

            SetIcon("stale", 0, 40);
            tray.Text = "OpenJuice";
            tray.ContextMenuStrip = menu;
            tray.Visible = true;
            tray.DoubleClick += delegate { Restore(); };

            timer.Interval = 1000;
            timer.Tick += delegate { Refresh1(); };
            timer.Start();
            Refresh1();
        }

        string iconKey;
        Icon windowIcon, trayIcon;

        // Redraw the window, taskbar and tray icon when the charger state or current changes.
        void SetIcon(string kind, double amps, int rating)
        {
            string key = kind + (kind == "charging" ? Math.Round(amps).ToString() : "");
            if (key == iconKey) return;
            iconKey = key;
            Icon oldWindow = windowIcon, oldTray = trayIcon;
            Icon = windowIcon = StateIcon.MakeWindow(kind, amps, rating);
            tray.Icon = trayIcon = StateIcon.MakeTray(kind, amps, rating);
            if (oldWindow != null) oldWindow.Dispose();           // only ever the ones made here
            if (oldTray != null) oldTray.Dispose();
        }

        // Launched with --tray: stay hidden until the tray icon is used.
        protected override void SetVisibleCore(bool value)
        {
            if (startHidden)
            {
                startHidden = false;
                if (!IsHandleCreated) CreateHandle();
                value = false;
            }
            base.SetVisibleCore(value);
        }

        void Restore() { Show(); WindowState = FormWindowState.Normal; Activate(); }

        void SetTheme(int idx)
        {
            theme = idx;
            Program.SaveTheme(dataDir, Theme.All[theme].Name);
            Refresh1();
        }

        [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
        static extern bool PlaySound(string sound, IntPtr module, uint flags);

        // The helper decides when a charge has finished and records it in status.json; the monitor
        // announces each record once. The last one announced is kept in monitor.json, so a charge that
        // finished while the monitor was not running is announced when it next starts, and a restart
        // does not announce the same charge twice.
        string notified;
        bool notifiedLoaded;

        void Completed(object record)
        {
            string path = Path.Combine(dataDir, "monitor.json");
            bool firstRun = false;
            if (!notifiedLoaded)
            {
                notifiedLoaded = true;
                try
                {
                    Dictionary<string, object> m = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
                    notified = J.S(m, "notified", null);
                }
                catch (Exception) { firstRun = !File.Exists(path); }
            }
            string t = J.S(record, "t", null);
            if (t == null || (notified != null && string.CompareOrdinal(t, notified) <= 0)) return;
            notified = t;
            try { File.WriteAllText(path, "{\"notified\": \"" + t + "\"}"); } catch (Exception) { }
            if (firstRun) return;                               // nothing to compare with yet
            if (!J.Has(record, "wh"))
            {
                // The helper could not measure the charge: the charger sent neither energy counter. That is
                // not a normal finish, so it is an alert, not the charge-complete chime.
                SystemSounds.Exclamation.Play();
                Toast("Charging stopped, energy unknown",
                      "The charger sent no energy reading.\nThis may not have been a real charge. Check helper.log.", "stale");
                return;
            }
            if (chimeItem.Checked) Chime(J.I(record, "wh", 0), t);
        }

        void Chime(double? wh, string when)
        {
            // Windows' "Print Complete" sound: whatever is assigned to that event in Sound settings, else
            // the stock file (the event ships with nothing assigned), else the notification sound.
            const uint SND_ASYNC = 0x1, SND_NODEFAULT = 0x2, SND_ALIAS = 0x10000, SND_FILENAME = 0x20000;
            string stock = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), @"Media\Windows Print complete.wav");
            bool played = false;
            try
            {
                played = PlaySound("PrintComplete", IntPtr.Zero, SND_ALIAS | SND_ASYNC | SND_NODEFAULT)
                      || (File.Exists(stock) && PlaySound(stock, IntPtr.Zero, SND_FILENAME | SND_ASYNC | SND_NODEFAULT))
                      || PlaySound("Notification.Default", IntPtr.Zero, SND_ALIAS | SND_ASYNC | SND_NODEFAULT);
            }
            catch (Exception) { }
            if (!played) SystemSounds.Asterisk.Play();
            // One fact per line: the notification slides in and out, so it has to read at a glance.
            List<string> lines = new List<string>();
            DateTime at;
            if (when != null && DateTime.TryParse(when, CultureInfo.InvariantCulture, DateTimeStyles.None, out at)
                && (DateTime.Now - at).TotalMinutes > 3)        // announced late: say when it actually finished
                lines.Add("Finished " + at.ToString(at.Date == DateTime.Today ? "'at 'h:mm tt" : "ddd' at 'h:mm tt", CultureInfo.InvariantCulture));
            if (wh.HasValue && wh.Value > 0)
                lines.Add((wh.Value / 1000.0).ToString("0.00", CultureInfo.InvariantCulture) + " kWh delivered");
            if (when == null)                                   // the menu's test: the same layout, with stand-in values
            {
                lines.Clear();
                lines.Add("Finished at XX:XX");
                lines.Add("X.XX kWh delivered");
            }
            string msg = string.Join("\n", lines.ToArray());
            Toast(when == null ? "Charge complete (test)" : "Charge complete", msg, "complete");
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct NOTIFYICONDATA
        {
            public int cbSize; public IntPtr hWnd; public int uID, uFlags, uCallbackMessage; public IntPtr hIcon;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string szTip;
            public int dwState, dwStateMask;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string szInfo;
            public int uVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string szInfoTitle;
            public int dwInfoFlags; public Guid guidItem; public IntPtr hBalloonIcon;
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        static extern bool Shell_NotifyIcon(int message, ref NOTIFYICONDATA data);

        Icon toastIcon;

        // A notification carrying the state picture, not a stock "i" icon. WinForms cannot pass a custom
        // picture, so this talks to the shell directly, and falls back to WinForms if that fails.
        void Toast(string title, string msg, string kind)
        {
            try
            {
                System.Reflection.BindingFlags priv = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
                NativeWindow win = (NativeWindow)typeof(NotifyIcon).GetField("window", priv).GetValue(tray);
                int id = (int)typeof(NotifyIcon).GetField("id", priv).GetValue(tray);
                Icon old = toastIcon;
                toastIcon = StateIcon.MakeToast(kind);
                NOTIFYICONDATA d = new NOTIFYICONDATA();
                d.cbSize = Marshal.SizeOf(typeof(NOTIFYICONDATA));
                d.hWnd = win.Handle; d.uID = id;
                d.uFlags = 0x10;                                 // NIF_INFO
                d.szInfoTitle = title; d.szInfo = msg; d.szTip = "";
                d.dwInfoFlags = 0x4 | 0x10 | 0x20;               // our picture, our own sound, large
                d.hBalloonIcon = toastIcon.Handle;
                bool ok = Shell_NotifyIcon(1, ref d);            // NIM_MODIFY
                if (old != null) old.Dispose();
                if (ok) return;
            }
            catch (Exception) { }
            tray.ShowBalloonTip(8000, title, msg, ToolTipIcon.None);
        }

        string lastKind;

        // Called with each fresh state: say so once when the charger goes into its error state.
        void Watch(string kind)
        {
            if (kind == "error" && lastKind != "error")
            {
                SystemSounds.Hand.Play();
                Toast("Charger error", "The JuiceBox reports an error state and is not charging.", "error");
            }
            lastKind = kind;
        }

        // A tray-menu control: bring the window up and open the same dialog the menu bar would.
        void Control(string action) { Restore(); ui.Run(action); Refresh1(); }

        void Refresh1()
        {
            // ui.json may have been changed by the terminal screen.
            int shared = Theme.IndexOf(Program.LoadTheme(dataDir));
            if (shared != theme && File.Exists(Path.Combine(dataDir, "ui.json"))) theme = shared;

            double age;
            Dictionary<string, object> st = Program.ReadStatus(dataDir, out age);
            ui.St = st; ui.Age = age; ui.ThemeIx = theme;
            int cols = Math.Max(80, ClientSize.Width / cw), rows = Math.Max(30, ClientSize.Height / ch);
            if (st == null) SetIcon("stale", 0, 40);
            if (st != null)
            {
                canvas = Screen.Compose(st, age, Theme.All[theme], cols, rows, "", History.Load(dataDir));
                ui.Draw(canvas, Theme.All[theme]);
                Completed(J.Get(J.Get(st, "charge"), "last_complete"));
                object t = J.Get(st, "telemetry"), f = J.Get(t, "fields");
                DateTime last;
                string s = J.S(f, "S", null);
                if (DateTime.TryParse(J.S(t, "last", ""), CultureInfo.InvariantCulture, DateTimeStyles.None, out last)
                    && (DateTime.Now - last).TotalSeconds <= 60 && s != null)
                {
                    string tip = "OpenJuice: " + Screen.StateName(s) + ", " + (J.I(f, "A", 0) / 10.0).ToString("0.0", CultureInfo.InvariantCulture) + " A";
                    tray.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;
                    SetIcon(StateIcon.KindOf(s, true), J.I(f, "A", 0) / 10.0, J.I(f, "m", 40));
                    Watch(StateIcon.KindOf(s, true));
                }
                else { tray.Text = "OpenJuice: no fresh telemetry"; SetIcon("stale", 0, 40); }
            }
            else if (canvas == null)
            {
                Theme T = Theme.All[theme];
                canvas = new Canvas(cols, rows, ' ', T.Desk[0], T.Desk[1]);
                canvas.Put(2, 1, "waiting for the helper to write status.json in " + dataDir, 97, -1);
            }
            Invalidate();
        }

        // Keys go to the menus and dialogs under the same names the terminal screen uses.
        static string KeyName(Keys data)
        {
            Keys code = data & Keys.KeyCode, mods = data & Keys.Modifiers;
            if (mods == Keys.Alt) return code >= Keys.A && code <= Keys.Z ? "alt+" + (char)('a' + (code - Keys.A)) : null;
            if (mods != Keys.None && mods != Keys.Shift) return null;
            if (code == Keys.Tab) return mods == Keys.Shift ? "shift+tab" : "tab";
            switch (code)
            {
                case Keys.F1: return "f1";
                case Keys.F2: return "f2";
                case Keys.F5: return "f5";
                case Keys.F8: return "f8";
                case Keys.F9: return "f9";
                case Keys.F10: return "f10";
                case Keys.Home: return "home";
                case Keys.End: return "end";
                case Keys.Up: return "up";
                case Keys.Down: return "down";
                case Keys.Left: return "left";
                case Keys.Right: return "right";
                case Keys.Enter: return "enter";
                case Keys.Escape: return "esc";
                case Keys.Back: return "backspace";
                case Keys.Space: return " ";
            }
            if (code >= Keys.A && code <= Keys.Z) return ((char)('a' + (code - Keys.A))).ToString();
            if (code >= Keys.D0 && code <= Keys.D9) return ((char)('0' + (code - Keys.D0))).ToString();
            if (code >= Keys.NumPad0 && code <= Keys.NumPad9) return ((char)('0' + (code - Keys.NumPad0))).ToString();
            return null;
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            string k = KeyName(keyData);
            if (k != null && ui.Key(k)) { Refresh1(); return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left && ui.Click(e.X / cw, e.Y / ch)) Refresh1();
            base.OnMouseDown(e);
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

    // Text drawn from a Windows bitmap font file instead of a scalable font, for the look of a DOS text
    // screen: one-bit glyphs with no smoothing. The glyphs are read at run time from the "Terminal"
    // font this PC already has (dosapp.fon, 10 by 18, in the OEM code page), the font Windows used for
    // DOS programs in a window. Nothing is shipped with the monitor; if the file is missing or
    // unreadable, or the monitor is started with --smooth, text is drawn in Consolas as before.
    class BitFont
    {
        public readonly int W, H;
        readonly ushort[][] glyphs = new ushort[256][];          // per character, one word per row, leftmost pixel in bit 15
        readonly Dictionary<int, Bitmap> cache = new Dictionary<int, Bitmap>();
        readonly Dictionary<char, int> codes = new Dictionary<char, int>();
        readonly Encoding oem;

        BitFont(int w, int h)
        {
            W = w; H = h;
            try { oem = Encoding.GetEncoding(CultureInfo.CurrentCulture.TextInfo.OEMCodePage); }
            catch { oem = Encoding.GetEncoding(437); }
            // Symbols the OEM code page keeps in its control-character positions.
            string low = "\u25bc\u25b2\u2022\u2191\u2193\u2192\u2190\u25ba\u25c4";
            int[] at = { 0x1F, 0x1E, 0x07, 0x18, 0x19, 0x1A, 0x1B, 0x10, 0x11 };
            for (int i = 0; i < low.Length; i++) codes[low[i]] = at[i];
        }

        public static BitFont Load()
        {
            try
            {
                string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Fonts), "dosapp.fon");
                return Load(File.ReadAllBytes(path), 10, 18);
            }
            catch { return null; }
        }

        // A .FON file is a 16-bit Windows module whose resources are .FNT bitmap fonts of several sizes.
        static BitFont Load(byte[] d, int w, int h)
        {
            if (d[0] != 'M' || d[1] != 'Z') return null;
            int ne = BitConverter.ToInt32(d, 0x3C);
            if (d[ne] != 'N' || d[ne + 1] != 'E') return null;
            int rt = ne + BitConverter.ToUInt16(d, ne + 0x24);
            int shift = BitConverter.ToUInt16(d, rt), p = rt + 2;
            while (true)
            {
                int type = BitConverter.ToUInt16(d, p), count = BitConverter.ToUInt16(d, p + 2);
                if (type == 0) return null;
                p += 8;
                for (int i = 0; i < count; i++, p += 12)
                {
                    if (type != 0x8008) continue;                               // RT_FONT
                    int o = BitConverter.ToUInt16(d, p) << shift;
                    if (BitConverter.ToUInt16(d, o + 86) != w || BitConverter.ToUInt16(d, o + 88) != h) continue;
                    bool v3 = BitConverter.ToUInt16(d, o) != 0x200;
                    int first = d[o + 95], last = d[o + 96];
                    BitFont f = new BitFont(w, h);
                    for (int c = first; c <= last; c++)
                    {
                        int e = o + (v3 ? 148 : 118) + (c - first) * (v3 ? 6 : 4);
                        int gw = BitConverter.ToUInt16(d, e);
                        int bits = o + (v3 ? BitConverter.ToInt32(d, e + 2) : BitConverter.ToUInt16(d, e + 2));
                        ushort[] rows = new ushort[h];
                        for (int y = 0; y < h; y++)                              // stored a byte-wide column at a time
                        {
                            int v = d[bits + y] << 8;
                            if (gw > 8) v |= d[bits + h + y];
                            rows[y] = (ushort)v;
                        }
                        f.glyphs[c] = rows;
                    }
                    return f;
                }
            }
        }

        int Code(char c)
        {
            if (c < 0x80) return c;
            int code;
            if (codes.TryGetValue(c, out code)) return code;
            byte[] b = oem.GetBytes(new char[] { c });
            code = b.Length == 1 && b[0] != '?' ? (int)b[0] : (int)'?';
            codes[c] = code;
            return code;
        }

        // The glyph for a character in one colour, on a transparent background.
        public Bitmap Glyph(char c, int fg)
        {
            int code = Code(c), key = code * 1000 + fg;
            Bitmap bmp;
            if (cache.TryGetValue(key, out bmp)) return bmp;
            bmp = new Bitmap(W, H, PixelFormat.Format32bppPArgb);
            ushort[] rows = glyphs[code] ?? glyphs['?'];
            Color ink = Program.Pal(fg);
            if (rows != null)
                for (int y = 0; y < H; y++)
                    for (int x = 0; x < W; x++)
                        if ((rows[y] & (0x8000 >> x)) != 0) bmp.SetPixel(x, y, ink);
            cache[key] = bmp;
            return bmp;
        }
    }

    static class Program
    {
        public static BitFont Bits;             // null: draw text with the scalable font

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
            if (Bits != null) { cw = Bits.W; ch = Bits.H; return; }
            Size sz = TextRenderer.MeasureText("MMMMMMMMMM", font, new Size(int.MaxValue, int.MaxValue), Flags);
            cw = Math.Max(1, sz.Width / 10);
            ch = Math.Max(1, sz.Height);
        }

        static bool IsLine(char c)
        {
            return c == Canvas.H || c == Canvas.V || c == Canvas.TL || c == Canvas.TR || c == Canvas.BL || c == Canvas.BR || c == Canvas.SEP
                || c == Canvas.SH || c == Canvas.STL || c == Canvas.STR || c == Canvas.SBL || c == Canvas.SBR
                || c == Canvas.STEE || c == Canvas.ETEE;
        }

        // Border characters drawn as exact pixel lines, so font smoothing cannot tint them.
        static void Line(Graphics g, Brush br, char c, int x, int y, int cw, int ch)
        {
            int mx = x + cw / 2, my = y + ch / 2, r = x + cw, b = y + ch;
            if (c == Canvas.SEP) { g.FillRectangle(br, mx, y, 1, ch); return; }
            if (c == Canvas.SH) { g.FillRectangle(br, x, my, cw, 1); return; }
            if (c == Canvas.STEE || c == Canvas.ETEE)
            {
                g.FillRectangle(br, mx, y, 1, ch);
                g.FillRectangle(br, c == Canvas.STEE ? mx : x, my, c == Canvas.STEE ? r - mx : mx - x + 1, 1);
                return;
            }
            if (c == Canvas.STL || c == Canvas.STR || c == Canvas.SBL || c == Canvas.SBR)
            {
                bool toRight = c == Canvas.STL || c == Canvas.SBL, toBottom = c == Canvas.STL || c == Canvas.STR;
                g.FillRectangle(br, toRight ? mx : x, my, toRight ? r - mx : mx - x + 1, 1);
                g.FillRectangle(br, mx, toBottom ? my : y, 1, toBottom ? b - my : my - y + 1);
                return;
            }
            if (c == Canvas.H) { g.FillRectangle(br, x, my - 1, cw, 1); g.FillRectangle(br, x, my + 1, cw, 1); return; }
            if (c == Canvas.V) { g.FillRectangle(br, mx - 1, y, 1, ch); g.FillRectangle(br, mx + 1, y, 1, ch); return; }
            bool right = c == Canvas.TL || c == Canvas.BL;       // the arm runs to the right edge
            bool down = c == Canvas.TL || c == Canvas.TR;        // the leg runs to the bottom edge
            int ox = right ? mx - 1 : mx + 1, ix = right ? mx + 1 : mx - 1;    // outer and inner verticals
            int oy = down ? my - 1 : my + 1, iy = down ? my + 1 : my - 1;      // outer and inner horizontals
            g.FillRectangle(br, right ? ox : x, oy, right ? r - ox : ox - x + 1, 1);
            g.FillRectangle(br, right ? ix : x, iy, right ? r - ix : ix - x + 1, 1);
            g.FillRectangle(br, ox, down ? oy : y, 1, down ? b - oy : oy - y + 1);
            g.FillRectangle(br, ix, down ? iy : y, 1, down ? b - iy : iy - y + 1);
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
                        if ((c >= '\u2580' && c <= '\u258f') || c == Canvas.EMPTY || IsLine(c)) c = ' ';   // blocks, shade and borders are painted below
                        else if (c != ' ') ink = true;
                        sb.Append(c);
                        x++;
                    }
                    g.FillRectangle(Brush(brushes, bg), start * cw, y * ch, (x - start) * cw, ch);
                    if (ink && Bits != null)
                    {
                        for (int k = 0; k < sb.Length; k++)
                            if (sb[k] != ' ') g.DrawImageUnscaled(Bits.Glyph(sb[k], fg), (start + k) * cw, y * ch);
                    }
                    else if (ink) TextRenderer.DrawText(g, sb.ToString(), font, new Point(start * cw, y * ch), Pal(fg), Pal(bg), Flags);
                    for (int i = start; i < x; i++)
                    {
                        char b = cv.C[y, i].Ch;
                        if (IsLine(b)) { Line(g, Brush(brushes, fg), b, i * cw, y * ch, cw, ch); continue; }
                        if (b == Canvas.EMPTY) { g.FillRectangle(Dither(fg, bg), i * cw, y * ch, cw, ch); continue; }
                        if (b == Canvas.UPPER) { g.FillRectangle(Brush(brushes, fg), i * cw, y * ch, cw, ch / 2); continue; }
                        if (b == Canvas.LOWER) { g.FillRectangle(Brush(brushes, fg), i * cw, y * ch + ch - ch / 2, cw, ch / 2); continue; }
                        if (b < '\u2581' || b > '\u258f') continue;
                        if (b > Canvas.FULL)                         // left-aligned eighths: a horizontal bar's tip
                            g.FillRectangle(Brush(brushes, fg), i * cw, y * ch, cw * ('\u2590' - b) / 8, ch);
                        else
                        {
                            int hgt = ch * (b - '\u2580') / 8;    // eighths of a cell, from the bottom
                            g.FillRectangle(Brush(brushes, fg), i * cw, y * ch + ch - hgt, cw - 1, hgt);
                        }
                    }
                }
            }
        }

        // The light shade character as a VGA text screen shows it: one dot in four, staggered row by row.
        // Drawn from the bit pattern, so font smoothing cannot blur or tint it.
        static readonly Dictionary<int, TextureBrush> dithers = new Dictionary<int, TextureBrush>();

        static TextureBrush Dither(int fg, int bg)
        {
            TextureBrush b;
            if (dithers.TryGetValue(fg * 1000 + bg, out b)) return b;
            Bitmap tile = new Bitmap(4, 2);
            for (int yy = 0; yy < 2; yy++)
                for (int xx = 0; xx < 4; xx++) tile.SetPixel(xx, yy, Pal(xx == (yy == 0 ? 3 : 1) ? fg : bg));
            b = new TextureBrush(tile);
            dithers[fg * 1000 + bg] = b;
            return b;
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
            if (Array.IndexOf(args, "--smooth") < 0) Bits = BitFont.Load();       // the DOS-box bitmap font, when this PC has it
            if (args.Length >= 2 && args[0] == "--icons")
            {
                StateIcon.Sheet(args[1]);
                return 0;
            }
            if (args.Length >= 2 && args[0] == "--file-icon")   // regenerate OpenJuiceMonitor.ico for the build
            {
                StateIcon.SaveFileIcon(args[1]);
                return 0;
            }
            if (args.Length >= 2 && args[0] == "--snapshot")
            {
                double age;
                if (args.Length >= 4) dir = args[3];            // a data folder other than the live one
                Dictionary<string, object> st = ReadStatus(dir, out age);
                if (st == null) return 1;
                Theme T = Theme.All[Theme.IndexOf(args.Length >= 3 ? args[2] : LoadTheme(dir))];
                Canvas cv = Screen.Compose(st, age, T, 80, 32, "", History.Load(dir));
                Ui shot = new Ui(dir) { St = st, Age = age, ThemeIx = Theme.IndexOf(T.Name) };
                if (args.Length >= 5) shot.Pose(args[4]);       // e.g. "f10,enter" or "l,4,1,enter": keys to press first
                shot.Draw(cv, T);
                if (args[1].EndsWith(".txt"))                   // the cell grid as text, to compare with the terminal screen
                {
                    StringBuilder sb = new StringBuilder();
                    for (int y = 0; y < cv.Hgt; y++)
                        for (int x = 0; x < cv.W; x++)
                            sb.Append(y).Append(' ').Append(x).Append(' ').Append((int)cv.C[y, x].Ch).Append(' ')
                              .Append(cv.C[y, x].Fg).Append(' ').Append(cv.C[y, x].Bg).Append('\n');
                    File.WriteAllText(args[1], sb.ToString());
                    return 0;
                }
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
            bool created;
            using (System.Threading.Mutex one = new System.Threading.Mutex(true, "OpenJuiceMonitor.single", out created))
            {
                if (!created) return 0;                         // already running: its icon is in the tray
                Identity.Register(dir);
                Application.Run(new MonitorForm(dir, Array.IndexOf(args, "--tray") >= 0));
            }
            return 0;
        }
    }
}
