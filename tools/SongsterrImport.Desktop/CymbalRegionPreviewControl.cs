// Author: Gabriel Pinheiro de Carvalho
// Single-rectangle live preview of where OCR is taken from (simplified from SubtitleVoiceCompanion's CapturePreviewControl: one region only).
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace SongsterrImport.Desktop;

internal sealed class CymbalOcrRegionChangedEventArgs : EventArgs
{
    public CymbalOcrRegionChangedEventArgs(Rectangle clientRegion)
    {
        ClientRegion = clientRegion;
    }

    public Rectangle ClientRegion { get; }
}

internal enum CymbalOcrEditMode
{
    None,
    Draw
}

/// <summary>One drawable rectangle over a still of the target window’s client area (letterboxed fit).</summary>
internal sealed class CymbalRegionPreviewControl : Control
{
    private const int MinRegion = 4;

    private Bitmap? _preview;
    private Rectangle _clientRegion;
    private bool _isDragging;
    private Point _dragStartBitmap;
    private Rectangle _dragPreview;
    private CymbalOcrEditMode _editMode = CymbalOcrEditMode.None;

    public CymbalRegionPreviewControl()
    {
        DoubleBuffered = true;
        BackColor = Color.FromArgb(28, 28, 32);
    }

    public event EventHandler<CymbalOcrRegionChangedEventArgs>? ClientRegionChanged;

    public Bitmap? PreviewBitmap
    {
        get => _preview;
        set
        {
            _preview?.Dispose();
            _preview = value is null ? null : new Bitmap(value);
            Invalidate();
        }
    }

    public Rectangle OcrClientRegion
    {
        get => _clientRegion;
        set
        {
            _clientRegion = value;
            Invalidate();
        }
    }

    public CymbalOcrEditMode EditMode
    {
        get => _editMode;
        set
        {
            _editMode = value;
            _isDragging = false;
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using (SolidBrush backgroundBrush = new(BackColor))
        {
            g.FillRectangle(backgroundBrush, ClientRectangle);
        }

        RectangleF imageRect = GetImageRect();
        if (_preview is null)
        {
            using StringFormat f = new() { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
            g.DrawString("No preview. Pick a window and press Refresh.", Font, Brushes.Gray, ClientRectangle, f);
            return;
        }

        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.DrawImage(_preview, imageRect);
        if (_clientRegion.Width >= MinRegion && _clientRegion.Height >= MinRegion)
        {
            RectangleF cr = ToControlRect(imageRect, _clientRegion);
            using Pen pen = new(Color.Lime, 2);
            g.DrawRectangle(pen, cr.X, cr.Y, cr.Width, cr.Height);
            using Font font = new(Font.FontFamily, 9, FontStyle.Bold);
            g.DrawString("OCR (tick#)", font, Brushes.Lime, new PointF(cr.X, MathF.Max(0, cr.Y - 16)));
        }

        if (_isDragging)
        {
            Rectangle normalized = NormalizeRect(_dragPreview);
            if (normalized.Width > 0 && normalized.Height > 0)
            {
                RectangleF cr2 = ToControlRect(imageRect, normalized);
                using Pen dash = new(Color.Yellow, 1) { DashStyle = DashStyle.Dash };
                g.DrawRectangle(dash, cr2.X, cr2.Y, cr2.Width, cr2.Height);
            }
        }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (EditMode != CymbalOcrEditMode.Draw || e.Button != MouseButtons.Left || _preview is null)
        {
            return;
        }

        if (ToBitmap(e.Location) is not { } p)
        {
            return;
        }

        _isDragging = true;
        _dragStartBitmap = p;
        _dragPreview = new Rectangle(p.X, p.Y, 1, 1);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (!_isDragging || _preview is null)
        {
            return;
        }

        if (ToBitmap(e.Location) is not { } p)
        {
            return;
        }

        _dragPreview = FromTwoPoints(_dragStartBitmap, p);
        Invalidate();
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        if (_isDragging && e.Button == MouseButtons.Left)
        {
            _isDragging = false;
            Rectangle r = NormalizeRect(_dragPreview);
            if (r.Width >= MinRegion && r.Height >= MinRegion)
            {
                OcrClientRegion = r;
                ClientRegionChanged?.Invoke(this, new CymbalOcrRegionChangedEventArgs(r));
            }
        }
    }

    private static Rectangle FromTwoPoints(Point a, Point b) =>
        Rectangle.FromLTRB(
            Math.Min(a.X, b.X),
            Math.Min(a.Y, b.Y),
            Math.Max(a.X, b.X),
            Math.Max(a.Y, b.Y)
        );

    private static Rectangle NormalizeRect(Rectangle r) => FromTwoPoints(
        new Point(r.Left, r.Top),
        new Point(r.Right, r.Bottom)
    );

    private Point? ToBitmap(Point control)
    {
        if (_preview is null)
        {
            return null;
        }

        RectangleF imageR = GetImageRect();
        if (imageR.Width < 1 || imageR.Height < 1)
        {
            return null;
        }

        if (!new Rectangle(0, 0, Width, Height).Contains(control))
        {
            return null;
        }

        double u = (control.X - imageR.Left) / imageR.Width;
        double v = (control.Y - imageR.Top) / imageR.Height;
        int x = (int)Math.Round(u * _preview.Width);
        int y = (int)Math.Round(v * _preview.Height);
        return new Point(
            Math.Clamp(x, 0, _preview.Width - 1),
            Math.Clamp(y, 0, _preview.Height - 1)
        );
    }

    private RectangleF GetImageRect()
    {
        if (_preview is null)
        {
            return RectangleF.Empty;
        }

        double sx = (double)Width / _preview.Width;
        double sy = (double)Height / _preview.Height;
        double s = Math.Min(sx, sy);
        double w = _preview.Width * s;
        double h = _preview.Height * s;
        double ox = (Width - w) / 2d;
        double oy = (Height - h) / 2d;
        return new RectangleF((float)ox, (float)oy, (float)w, (float)h);
    }

    private RectangleF ToControlRect(RectangleF imageRect, Rectangle r)
    {
        if (_preview is null)
        {
            return RectangleF.Empty;
        }

        float scaleX = imageRect.Width / _preview.Width;
        float scaleY = imageRect.Height / _preview.Height;
        return new RectangleF(
            imageRect.Left + r.X * scaleX,
            imageRect.Top + r.Y * scaleY,
            r.Width * scaleX,
            r.Height * scaleY
        );
    }
}
