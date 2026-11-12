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
                for (int xx = Math.Max(0, x); xx < Math.Min(W, x + w); xx++) { C[yy, xx].Ch = ' '; C[yy, xx].Fg = fg; C[yy, xx].Bg = bg; }
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

    // The window, taskbar and tray icon, drawn from the charger state. A J1772 handle sits inside
    // a circle made by its own cord. The tile colour is the state (grey-blue unplugged, blue plugged
    // in, green charging, red error, amber no telemetry) and the circle is a gauge: the bright part
    // of it is the amps the vehicle is drawing, out of the circuit rating. It shows load, as Task
    // Manager's icon does; the charger does not know the battery's state of charge.
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
            return kind == "error" ? "!" : kind == "stale" ? "?" : kind == "unplugged" ? "u"
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
            Color tile = kind == "charging" ? Color.FromArgb(12, 100, 34) : kind == "idle" ? Color.FromArgb(24, 132, 255)
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
                bool plugged = kind == "idle" || kind == "charging" || kind == "error";
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
                              "charging 40 A of 40", "error", "stale (no telemetry)" };
            double[] amps = { 0, 0, 6, 16, 26, 40, 0, 0 };
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
            int lx = 2, rx = 2 + ww + 4, ty = 2, th = 9;
            int fw = 2 * ww + 4, cy = 13, chh = 9, by = 24, bh = H - 26;
            int iw = ww - 4, bw = iw - 17;

            // --- Charger: every reading as a bar
            cv.Window(lx, ty, ww, th, "Charger", T.Main, T.Shadow);
            object t = J.Get(st, "telemetry");
            object f = J.Get(t, "fields");
            object lastDone = J.Get(J.Get(st, "charge"), "last_complete");
            string done = J.S(lastDone, "t", null);
            if (done != null && done.Length < 16) done = null;
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
                if (sc == "2" && J.Has(f, "E"))                 // charging: this session so far
                    Text(cv, lx, ty, 5, "Session", (J.I(f, "E", 0) / 1000.0).ToString("#,##0.000", Inv) + " kWh", iw);
                else if (done != null)                          // otherwise the last finished charge: when, how much
                {
                    string when = done.Substring(0, 10) == now.ToString("yyyy-MM-dd", Inv) ? done.Substring(11, 5) : done.Substring(5, 11).Replace('T', ' ');
                    Chip(cv, lx, ty, 5, "Finished", when, T.Ok, J.Has(lastDone, "wh") ? " " + (J.I(lastDone, "wh", 0) / 1000.0).ToString("0.0", Inv) + " kWh" : "", iw);
                }
                else Text(cv, lx, ty, 5, "Finished", "no charge seen yet", iw);
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
            Text(cv, rx, ty, 6, "Resolver", J.Has(r, "last_hijack")
                ? J.I(r, "hijacks", 0) + " answers at " + (lastAsk.Length >= 5 ? lastAsk.Substring(0, 5) : lastAsk)
                : "no requests yet", iw);

            // --- Chart: current per minute
            int nb = iw - 3, bottom = cy + 6;
            cv.Window(lx, cy, ww, chh, "Current per minute, A", T.Win, T.Shadow);
            if (hist != null)
            {
                cv.Put(lx + 2, cy + 1, circ.ToString().PadLeft(2));
                cv.Put(lx + 2, bottom, " 0");
                if (cap > 0 && cap < circ) cv.Put(lx + 2, bottom - (int)((double)cap / circ * 6), cap.ToString().PadLeft(2));
                for (int i = 0; i < nb; i++)
                {
                    string key = now.AddMinutes(-(nb - 1 - i)).ToString("yyyy-MM-dd'T'HH:mm", Inv);
                    double a;
                    if (hist.Amps.TryGetValue(key, out a))
                    {
                        if (a > 0) Column(cv, lx + 5 + i, bottom, 6, a / circ, 1, a > cap + 0.05 ? T.FillBad : T.Fill);
                        else cv.Put(lx + 5 + i, bottom, "_");
                    }
                }
                cv.Put(lx + 5, cy + 7, "-" + nb + "m");
                cv.Put(lx + 5 + nb - 3, cy + 7, "now");
                for (int i = 0; i < nb; i++)                    // mark the minute the charge finished
                    if (done != null && now.AddMinutes(-(nb - 1 - i)).ToString("yyyy-MM-dd'T'HH:mm", Inv) == done.Substring(0, 16))
                        cv.Put(lx + 5 + i, cy + 7, "▼", T.Fill, -1);
            }
            else cv.Put(lx + 2, cy + 1, Clip("no telemetry.log to chart", iw));

            // --- Chart: energy per day
            cv.Window(rx, cy, ww, chh, "Energy per day, kWh", T.Win, T.Shadow);
            if (hist != null && hist.DayKwh.Length > 0)
            {
                int n0 = hist.DayKwh.Length, first = Math.Max(0, n0 - (chh - 2));
                double top = 0;
                for (int i = first; i < n0; i++) if (!double.IsNaN(hist.DayKwh[i]) && hist.DayKwh[i] > top) top = hist.DayKwh[i];
                if (top <= 0) top = 1;
                int dbw = iw - 9;
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
                    cv.Put(rx + 6 + dbw, y, kwh.ToString("0.0", Inv).PadLeft(5));
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
            menu.Items.Add(new ToolStripMenuItem("Test chime", null, delegate { Chime(null); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Exit", null, delegate { quitting = true; Close(); }));
            menu.Opening += delegate
            {
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
            if (st == null) SetIcon("stale", 0, 40);
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
                    SetIcon(StateIcon.KindOf(s, true), J.I(f, "A", 0) / 10.0, J.I(f, "m", 40));
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

        static bool IsLine(char c)
        {
            return c == Canvas.H || c == Canvas.V || c == Canvas.TL || c == Canvas.TR || c == Canvas.BL || c == Canvas.BR || c == Canvas.SEP;
        }

        // Border characters drawn as exact pixel lines, so font smoothing cannot tint them.
        static void Line(Graphics g, Brush br, char c, int x, int y, int cw, int ch)
        {
            int mx = x + cw / 2, my = y + ch / 2, r = x + cw, b = y + ch;
            if (c == Canvas.SEP) { g.FillRectangle(br, mx, y, 1, ch); return; }
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
                        if ((c >= '\u2581' && c <= '\u258f') || IsLine(c)) c = ' ';   // blocks and borders are painted below
                        else if (c != ' ') ink = true;
                        sb.Append(c);
                        x++;
                    }
                    g.FillRectangle(Brush(brushes, bg), start * cw, y * ch, (x - start) * cw, ch);
                    if (ink) TextRenderer.DrawText(g, sb.ToString(), font, new Point(start * cw, y * ch), Pal(fg), Pal(bg), Flags);
                    for (int i = start; i < x; i++)
                    {
                        char b = cv.C[y, i].Ch;
                        if (IsLine(b)) { Line(g, Brush(brushes, fg), b, i * cw, y * ch, cw, ch); continue; }
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
                Canvas cv = Screen.Compose(st, age, T, 80, 32, "T theme", History.Load(dir));
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
