using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Windows.Forms;

namespace InterviewAssistant.Services;

public static class ScreenCaptureService
{
    // Screenshots of question text are OCR input, not photos. Two things decide
    // whether the model reads "LNUAIMMIU" correctly: how many pixels each glyph
    // survives with, and whether lossy compression smeared its edges. So: capture
    // one monitor (not the whole multi-monitor desktop), keep the resolution high,
    // and prefer PNG.
    private const int MaxImageDimension = 1600;
    private const int FallbackImageDimension = 1200;

    // Groq rejects base64 images over ~4 MB; stay under that with headroom.
    private const int MaxBase64Length = 3_500_000;

    public static string CaptureScreenToBase64()
    {
        Rectangle bounds = ActiveScreenBounds();
        using var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size, CopyPixelOperation.SourceCopy);
        }

        return EncodeBitmapToBase64DataUrl(bitmap);
    }

    /// <summary>
    /// The monitor the user is actually looking at. Capturing the full virtual
    /// screen instead means a dual-monitor setup gets downscaled roughly twice as
    /// hard, which is what turns readable question text into mush.
    /// </summary>
    private static Rectangle ActiveScreenBounds()
    {
        try
        {
            return Screen.FromPoint(Control.MousePosition).Bounds;
        }
        catch (Exception exception)
        {
            Utilities.AppLogger.Error("Could not resolve the active screen.", exception);
            return Screen.PrimaryScreen?.Bounds ?? SystemInformation.VirtualScreen;
        }
    }

    public static string? CaptureClipboardImageToBase64()
    {
        try
        {
            if (System.Windows.Clipboard.ContainsImage())
            {
                var imageSource = System.Windows.Clipboard.GetImage();
                if (imageSource != null)
                {
                    using var stream = new MemoryStream();
                    var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder();
                    encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(imageSource));
                    encoder.Save(stream);
                    using var bitmap = new Bitmap(stream);
                    return EncodeBitmapToBase64DataUrl(bitmap);
                }
            }
            else if (System.Windows.Clipboard.ContainsFileDropList())
            {
                var files = System.Windows.Clipboard.GetFileDropList();
                if (files.Count > 0 && File.Exists(files[0]))
                {
                    string filePath = files[0]!;
                    string ext = Path.GetExtension(filePath).ToLowerInvariant();
                    if (ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".webp")
                    {
                        using var bitmap = new Bitmap(filePath);
                        return EncodeBitmapToBase64DataUrl(bitmap);
                    }
                }
            }
        }
        catch (Exception exception)
        {
            Utilities.AppLogger.Error("Could not grab clipboard image.", exception);
        }

        return null;
    }

    public static string EncodeBitmapToBase64DataUrl(Bitmap bitmap)
    {
        Bitmap target = ResizeToFit(bitmap, MaxImageDimension, out bool created);

        try
        {
            // PNG is lossless, so glyph edges stay sharp. JPEG ringing around small
            // text is exactly what makes a model misread a scrambled word.
            string png = ToDataUrl(target, quality: null);
            if (png.Length <= MaxBase64Length)
            {
                return png;
            }

            string jpeg = ToDataUrl(target, quality: 92L);
            if (jpeg.Length <= MaxBase64Length)
            {
                return jpeg;
            }
        }
        finally
        {
            if (created) target.Dispose();
        }

        Bitmap smaller = ResizeToFit(bitmap, FallbackImageDimension, out bool createdSmaller);
        try
        {
            return ToDataUrl(smaller, quality: 85L);
        }
        finally
        {
            if (createdSmaller) smaller.Dispose();
        }
    }

    private static Bitmap ResizeToFit(Bitmap bitmap, int maxDimension, out bool createdNew)
    {
        double scale = Math.Min(1.0, (double)maxDimension / Math.Max(bitmap.Width, bitmap.Height));
        if (scale >= 1.0)
        {
            createdNew = false;
            return bitmap;
        }

        int newWidth = Math.Max(1, (int)(bitmap.Width * scale));
        int newHeight = Math.Max(1, (int)(bitmap.Height * scale));

        var resized = new Bitmap(newWidth, newHeight, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(resized))
        {
            // HighQualityBicubic keeps thin strokes legible; the default nearest-ish
            // scaling drops whole pixel rows out of small glyphs.
            graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
            graphics.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;
            graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.HighQuality;
            graphics.DrawImage(bitmap, 0, 0, newWidth, newHeight);
        }

        createdNew = true;
        return resized;
    }

    private static string ToDataUrl(Bitmap bitmap, long? quality)
    {
        using var stream = new MemoryStream();

        if (quality is null)
        {
            bitmap.Save(stream, ImageFormat.Png);
            return $"data:image/png;base64,{Convert.ToBase64String(stream.ToArray())}";
        }

        var jpegEncoder = ImageCodecInfo.GetImageEncoders().FirstOrDefault(c => c.FormatID == ImageFormat.Jpeg.Guid);
        if (jpegEncoder != null)
        {
            var encoderParams = new EncoderParameters(1);
            encoderParams.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, quality.Value);
            bitmap.Save(stream, jpegEncoder, encoderParams);
        }
        else
        {
            bitmap.Save(stream, ImageFormat.Jpeg);
        }

        return $"data:image/jpeg;base64,{Convert.ToBase64String(stream.ToArray())}";
    }
}
