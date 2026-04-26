// Author: Gabriel Pinheiro de Carvalho
using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;

namespace SongsterrImport.Desktop;

/// <summary>P/Invoke helpers for full-client bitmap capture and window enumeration (same idea as SVC <see href="..."/>WindowCaptureService).</summary>
internal static class CymbalWindowInterop
{
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool EnumWindows(EnumWindowsProc callback, nint lParam);

    internal delegate bool EnumWindowsProc(nint hWnd, nint lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsWindowVisible(nint hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    internal static extern int GetWindowText(nint hWnd, StringBuilder stringBuilder, int maxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    internal static extern int GetWindowTextLength(nint hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetClientRect(nint hWnd, out NativeRect clientRect);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool ClientToScreen(nint hWnd, ref NativePoint point);

    [DllImport("user32.dll")]
    internal static extern nint GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern uint GetWindowThreadProcessId(nint hWnd, out uint processId);

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeRect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativePoint
    {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsWindow(nint hWnd);
}

/// <summary>One visible top-level window we can offer for capture + OCR.</summary>
internal readonly record struct CymbalWindowOption(nint Handle, string Title, string? ProcessName)
{
    /// <summary>Shown in the combo box (process + title when available).</summary>
    public string ListLabel
    {
        get
        {
            if (string.IsNullOrWhiteSpace(ProcessName))
            {
                return Title;
            }

            return ProcessName + " \u2014 " + Title;
        }
    }
}

internal static class CymbalWindowEnumerator
{
    internal static IReadOnlyList<CymbalWindowOption> GetVisibleTopLevelOptions(nint? excludeWindowHandle, int maximumCount = 400)
    {
        var buffer = new List<CymbalWindowOption>(128);
        nint self = nint.Zero;
        if (excludeWindowHandle is { } exclude && exclude != nint.Zero)
        {
            self = exclude;
        }

        _ = CymbalWindowInterop.EnumWindows(
            (hWnd, _) =>
            {
                if (hWnd == nint.Zero || hWnd == self)
                {
                    return true;
                }

                if (!CymbalWindowInterop.IsWindow(hWnd) || !CymbalWindowInterop.IsWindowVisible(hWnd))
                {
                    return true;
                }

                int textLength = CymbalWindowInterop.GetWindowTextLength(hWnd);
                if (textLength <= 0)
                {
                    return true;
                }

                StringBuilder stringBuilder = new(textLength + 1);
                _ = CymbalWindowInterop.GetWindowText(hWnd, stringBuilder, stringBuilder.Capacity);
                string title = stringBuilder.ToString().Trim();
                if (title.Length == 0)
                {
                    return true;
                }

                if (!CymbalWindowInterop.GetClientRect(hWnd, out CymbalWindowInterop.NativeRect clientRect))
                {
                    return true;
                }

                int widthPx = clientRect.Right - clientRect.Left;
                int heightPx = clientRect.Bottom - clientRect.Top;
                if (widthPx < 4 || heightPx < 4)
                {
                    return true;
                }

                string? processName = null;
                CymbalWindowInterop.GetWindowThreadProcessId(hWnd, out uint processId);
                if (processId > 0)
                {
                    try
                    {
                        using System.Diagnostics.Process p = System.Diagnostics.Process.GetProcessById((int)processId);
                        processName = p.ProcessName;
                    }
                    catch
                    {
                    }
                }

                buffer.Add(new CymbalWindowOption(hWnd, title, processName));
                if (buffer.Count >= maximumCount)
                {
                    return false;
                }

                return true;
            },
            nint.Zero
        );

        return buffer
            .OrderByDescending(c => c.Title, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    /// <summary>Re-match a window by <paramref name="savedTitle"/> and optionally <paramref name="processName"/>.</summary>
    internal static CymbalWindowOption? FindOptionByTitle(IReadOnlyList<CymbalWindowOption> all, string savedTitle, string? processName = null)
    {
        if (string.IsNullOrWhiteSpace(savedTitle))
        {
            return null;
        }

        if (!string.IsNullOrWhiteSpace(processName))
        {
            foreach (CymbalWindowOption candidate in all)
            {
                if (candidate.Handle == nint.Zero)
                {
                    continue;
                }

                if (candidate.Title != savedTitle)
                {
                    continue;
                }

                if (candidate.ProcessName is not null &&
                    string.Equals(candidate.ProcessName, processName, StringComparison.OrdinalIgnoreCase))
                {
                    return candidate;
                }
            }
        }

        foreach (CymbalWindowOption candidate in all)
        {
            if (candidate.Handle != nint.Zero && candidate.Title == savedTitle)
            {
                return candidate;
            }
        }

        foreach (CymbalWindowOption candidate in all)
        {
            if (candidate.Handle != nint.Zero && candidate.Title.Contains(savedTitle, StringComparison.OrdinalIgnoreCase))
            {
                return candidate;
            }
        }

        return null;
    }
}

internal static class CymbalClientBitmapCapture
{
    internal static Bitmap? TryCaptureClientBitmap(nint windowHandle)
    {
        if (!CymbalWindowInterop.IsWindow(windowHandle))
        {
            return null;
        }

        if (!CymbalWindowInterop.GetClientRect(windowHandle, out CymbalWindowInterop.NativeRect clientRect))
        {
            return null;
        }

        int clientWidth = Math.Max(1, clientRect.Right - clientRect.Left);
        int clientHeight = Math.Max(1, clientRect.Bottom - clientRect.Top);

        CymbalWindowInterop.NativePoint origin = default;
        if (!CymbalWindowInterop.ClientToScreen(windowHandle, ref origin))
        {
            return null;
        }

        Bitmap clientBitmap = new(clientWidth, clientHeight, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using Graphics graphics = Graphics.FromImage(clientBitmap);
        graphics.CopyFromScreen(
            origin.X,
            origin.Y,
            0,
            0,
            new System.Drawing.Size(clientWidth, clientHeight),
            System.Drawing.CopyPixelOperation.SourceCopy
        );

        return clientBitmap;
    }
}

/// <summary>Crop a <see cref="Rectangle"/> from a client-capture <see cref="Bitmap"/>; clamps to image bounds (same as SVC <c>CropRegion</c> idea).</summary>
internal static class CymbalBitmapCrop
{
    internal static Bitmap? CropToRegion(Bitmap clientBitmap, Rectangle clientRegion)
    {
        int left = Math.Clamp(clientRegion.Left, 0, Math.Max(0, clientBitmap.Width - 1));
        int top = Math.Clamp(clientRegion.Top, 0, Math.Max(0, clientBitmap.Height - 1));
        int cropW = Math.Clamp(clientRegion.Width, 1, Math.Max(1, clientBitmap.Width - left));
        int cropH = Math.Clamp(clientRegion.Height, 1, Math.Max(1, clientBitmap.Height - top));

        Bitmap outBitmap = new(cropW, cropH, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(outBitmap))
        {
            g.DrawImage(
                clientBitmap,
                new Rectangle(0, 0, cropW, cropH),
                new Rectangle(left, top, cropW, cropH),
                GraphicsUnit.Pixel
            );
        }

        return outBitmap;
    }
}
