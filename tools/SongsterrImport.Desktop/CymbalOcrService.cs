// Author: Gabriel Pinheiro de Carvalho
// Windows OCR (same building blocks as SubtitleVoiceCompanion: PNG → SoftwareBitmap → OcrEngine.RecognizeAsync)
using System.IO;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Text;
using System.Text.RegularExpressions;
using Windows.Globalization;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;

namespace SongsterrImport.Desktop;

internal static class CymbalOcrService
{
    private static readonly OcrEngine? WindowsOcr =
        OcrEngine.TryCreateFromUserProfileLanguages() ?? OcrEngine.TryCreateFromLanguage(new Language("en-US"));

    private static readonly Regex DigitGroupRegex = new(@"\d+", RegexOptions.Compiled);

    /// <summary>Read the first plausible tick number from a bitmap of the on-screen time/tick readout (digits, longest run wins).</summary>
    internal static async Task<long?> TryReadTickNumberFromBitmapAsync(Bitmap? regionBitmap, CancellationToken cancellationToken)
    {
        if (regionBitmap is null || regionBitmap.Width < 1 || regionBitmap.Height < 1)
        {
            return null;
        }

        if (WindowsOcr is null)
        {
            return null;
        }

        using MemoryStream pngStream = new();
        regionBitmap.Save(pngStream, ImageFormat.Png);
        pngStream.Seek(0, SeekOrigin.Begin);
        InMemoryRandomAccessStream random = new();
        await random.WriteAsync(pngStream.ToArray().AsBuffer()).AsTask(cancellationToken);
        random.Seek(0);
        BitmapDecoder decoder = await BitmapDecoder.CreateAsync(random).AsTask(cancellationToken);
        SoftwareBitmap software = await decoder
            .GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied)
            .AsTask(cancellationToken);
        OcrResult ocr = await WindowsOcr.RecognizeAsync(software).AsTask(cancellationToken);
        string? rawText = ocr.Text;

        if (string.IsNullOrWhiteSpace(rawText))
        {
            return null;
        }

        StringBuilder combinedDigits = new(32);
        foreach (char c in rawText)
        {
            if (char.IsDigit(c))
            {
                combinedDigits.Append(c);
            }
        }

        if (combinedDigits.Length > 0 && long.TryParse(combinedDigits.ToString(), out long allDigitsValue))
        {
            return allDigitsValue;
        }

        long? best = null;
        int bestLength = 0;
        foreach (Match match in DigitGroupRegex.Matches(rawText))
        {
            if (!match.Success)
            {
                continue;
            }

            if (long.TryParse(match.Value, out long parsed) && match.Length > bestLength)
            {
                best = parsed;
                bestLength = match.Length;
            }
        }

        return best;
    }
}
