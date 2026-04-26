// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace SongsterrImport.Desktop;

/// <summary>Reads the <c>[song]</c> section of a Clone Hero <c>song.ini</c> file.</summary>
internal static class SongIniReader
{
    private static readonly HashSet<string> s_keysWithDedicatedColumn = new(StringComparer.OrdinalIgnoreCase)
    {
        "name", "artist", "album", "genre", "year", "charter", "icon", "loading_phrase", "count", "modchart",
        "song_length", "preview_start_time", "album_track", "playlist_track",
        "diff_band", "diff_guitar", "diff_bass", "diff_drums", "diff_drums_real", "diff_rhythm", "diff_keys",
        "diff_guitarghl", "diff_bassghl", "diff_vocals",
        "end_events", "five_lane_drums", "pro_drums",
    };

    internal static IReadOnlyDictionary<string, string> ReadSongKeys(string trackFolderPath)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string filePath = Path.Combine(trackFolderPath, "song.ini");
        if (!File.Exists(filePath))
        {
            return result;
        }

        string[] lines;
        try
        {
            lines = File.ReadAllLines(filePath);
        }
        catch
        {
            return result;
        }

        bool inSong = false;
        foreach (string raw in lines)
        {
            string line = raw.Trim();
            if (line.Length == 0)
            {
                continue;
            }

            if (line[0] == ';')
            {
                continue;
            }

            if (line[0] == '[')
            {
                inSong = string.Equals(line, "[song]", StringComparison.OrdinalIgnoreCase);
                continue;
            }

            if (!inSong)
            {
                continue;
            }

            int indexEquals = line.IndexOf('=');
            if (indexEquals < 0)
            {
                continue;
            }

            string key = line[..indexEquals].Trim();
            if (key.Length == 0)
            {
                continue;
            }

            string value = line[(indexEquals + 1)..].Trim();
            result[key] = value;
        }

        return result;
    }

    internal static string Get(IReadOnlyDictionary<string, string> ini, string key) =>
        ini.TryGetValue(key, out string? v) ? v : string.Empty;

    internal static string FormatSongLengthDisplay(IReadOnlyDictionary<string, string> ini)
    {
        string raw = Get(ini, "song_length");
        if (raw.Length == 0)
        {
            return string.Empty;
        }

        if (!double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out double ms))
        {
            return raw;
        }

        double totalSeconds = ms / 1000.0;
        if (totalSeconds < 0)
        {
            return raw;
        }

        int total = (int)Math.Floor(totalSeconds);
        int minutes = total / 60;
        int seconds = total % 60;
        return minutes + ":" + seconds.ToString("00", System.Globalization.CultureInfo.InvariantCulture);
    }

    internal static string FormatPreviewDisplay(IReadOnlyDictionary<string, string> ini)
    {
        string raw = Get(ini, "preview_start_time");
        if (raw.Length == 0)
        {
            return string.Empty;
        }

        if (!long.TryParse(raw, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out long ms))
        {
            return raw;
        }

        if (ms < 0)
        {
            return raw;
        }

        double s = ms / 1000.0;
        return s.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "s";
    }

    internal static string TruncateForCell(string? text, int maxChars)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        if (text.Length <= maxChars)
        {
            return text;
        }

        return text[..(maxChars - 1)] + "…";
    }

    /// <summary>Key=value for every key in the ini that is not shown in its own column. Sorted for stable order.</summary>
    internal static string BuildRemainingFromIni(IReadOnlyDictionary<string, string> ini)
    {
        if (ini.Count == 0)
        {
            return string.Empty;
        }

        var list = new List<string>();
        foreach (KeyValuePair<string, string> item in ini)
        {
            if (s_keysWithDedicatedColumn.Contains(item.Key))
            {
                continue;
            }

            if (string.IsNullOrEmpty(item.Value))
            {
                continue;
            }

            list.Add(item.Key + "=" + item.Value);
        }

        list.Sort(StringComparer.OrdinalIgnoreCase);
        if (list.Count == 0)
        {
            return string.Empty;
        }

        var result = new StringBuilder();
        for (int i = 0; i < list.Count; i++)
        {
            if (i > 0)
            {
                result.Append("  ");
            }

            result.Append(list[i]);
        }

        return result.ToString();
    }

    /// <summary>Parses Clone Hero 0/1, true/false, yes/no (case-insensitive) song.ini values.</summary>
    internal static bool ParseBoolFlag(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return false;
        }

        string t = raw.Trim();
        if (t.Length == 0)
        {
            return false;
        }

        if (string.Equals(t, "1", StringComparison.Ordinal))
        {
            return true;
        }

        if (string.Equals(t, "0", StringComparison.Ordinal))
        {
            return false;
        }

        if (string.Equals(t, "true", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (string.Equals(t, "false", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (string.Equals(t, "yes", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (string.Equals(t, "no", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return false;
    }
}
