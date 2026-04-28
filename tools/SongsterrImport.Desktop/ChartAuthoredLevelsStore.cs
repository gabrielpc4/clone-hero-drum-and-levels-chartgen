// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SongsterrImport.Desktop;

/// <summary>
/// Detects guitar difficulty sections in each <c>notes.chart</c> and caches all results in a single
/// <c>original/custom/chart_authored_levels.json</c> file (updated when a chart changes).
/// </summary>
public static class ChartAuthoredLevelsStore
{
    public const string IndexJsonFileName = "chart_authored_levels.json";

    private static readonly object IndexLock = new();

    private static readonly Regex RxEasy = new(@"\[\s*EasySingle\s*\]", RegexOptions.CultureInvariant);
    private static readonly Regex RxMedium = new(@"\[\s*MediumSingle\s*\]", RegexOptions.CultureInvariant);
    private static readonly Regex RxHard = new(@"\[\s*HardSingle\s*\]", RegexOptions.CultureInvariant);
    private static readonly Regex RxExpert = new(@"\[\s*ExpertSingle\s*\]", RegexOptions.CultureInvariant);

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    public sealed class EntryDto
    {
        public string ChartModifiedUtc { get; set; } = "";
        public int Count { get; set; }
        public string Letters { get; set; } = "";
        public string Detail { get; set; } = "";
    }

    private static string? TryGetCustomRoot(string customTrackFolder)
    {
        if (string.IsNullOrWhiteSpace(customTrackFolder))
        {
            return null;
        }

        string? parent = Directory.GetParent(customTrackFolder)?.FullName;
        return parent;
    }

    private static string? TryGetIndexPath(string customTrackFolder)
    {
        string? customRoot = TryGetCustomRoot(customTrackFolder);
        if (string.IsNullOrEmpty(customRoot))
        {
            return null;
        }

        return Path.Combine(customRoot, IndexJsonFileName);
    }

    private static Dictionary<string, EntryDto> ReadIndexUnlocked(string indexPath)
    {
        if (!File.Exists(indexPath))
        {
            return new Dictionary<string, EntryDto>(StringComparer.Ordinal);
        }

        try
        {
            string json = File.ReadAllText(indexPath, Encoding.UTF8);
            var doc = JsonSerializer.Deserialize<Dictionary<string, EntryDto>>(json, JsonOpts);
            return doc ?? new Dictionary<string, EntryDto>(StringComparer.Ordinal);
        }
        catch
        {
            return new Dictionary<string, EntryDto>(StringComparer.Ordinal);
        }
    }

    private static void WriteIndexUnlocked(string indexPath, Dictionary<string, EntryDto> data)
    {
        string json = JsonSerializer.Serialize(data, JsonOpts);
        string? dir = Path.GetDirectoryName(indexPath);
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }

        string temp = indexPath + ".tmp";
        File.WriteAllText(temp, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        File.Move(temp, indexPath, overwrite: true);
    }

    private static void ScanChartToEntry(string chartText, DateTime chartUtc, out EntryDto entry)
    {
        bool easy = RxEasy.IsMatch(chartText);
        bool medium = RxMedium.IsMatch(chartText);
        bool hard = RxHard.IsMatch(chartText);
        bool expert = RxExpert.IsMatch(chartText);

        if (!easy && !medium && !hard && !expert)
        {
            string lower = chartText.ToLowerInvariant();
            easy |= lower.Contains("easysingle");
            medium |= lower.Contains("mediumsingle");
            hard |= lower.Contains("hardsingle");
            expert |= lower.Contains("expertsingle");
        }

        int count = (easy ? 1 : 0) + (medium ? 1 : 0) + (hard ? 1 : 0) + (expert ? 1 : 0);

        var letters = new StringBuilder(4);
        if (easy)
        {
            letters.Append('E');
        }

        if (medium)
        {
            letters.Append('M');
        }

        if (hard)
        {
            letters.Append('H');
        }

        if (expert)
        {
            letters.Append('X');
        }

        var labels = new List<string>(4);
        if (easy)
        {
            labels.Add("Easy");
        }

        if (medium)
        {
            labels.Add("Medium");
        }

        if (hard)
        {
            labels.Add("Hard");
        }

        if (expert)
        {
            labels.Add("Expert");
        }

        string detail = labels.Count > 0 ? string.Join(", ", labels) : "No guitar single sections";

        entry = new EntryDto
        {
            ChartModifiedUtc = chartUtc.ToString("o", CultureInfo.InvariantCulture),
            Count = count,
            Letters = letters.ToString(),
            Detail = detail,
        };
    }

    /// <summary>Ensure the JSON index has a fresh entry for this song when <c>notes.chart</c> changed.</summary>
    public static void EnsureEntryCurrent(string customTrackFolder)
    {
        string? indexPath = TryGetIndexPath(customTrackFolder);
        if (string.IsNullOrEmpty(indexPath))
        {
            return;
        }

        string songKey = Path.GetFileName(customTrackFolder.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        if (string.IsNullOrEmpty(songKey))
        {
            return;
        }

        string chartPath = Path.Combine(customTrackFolder, "notes.chart");

        lock (IndexLock)
        {
            Dictionary<string, EntryDto> index = ReadIndexUnlocked(indexPath);

            if (!File.Exists(chartPath))
            {
                if (index.Remove(songKey))
                {
                    WriteIndexUnlocked(indexPath, index);
                }

                return;
            }

            DateTime chartUtc = File.GetLastWriteTimeUtc(chartPath);

            if (index.TryGetValue(songKey, out EntryDto? existing)
                && DateTime.TryParse(existing.ChartModifiedUtc, null, DateTimeStyles.RoundtripKind, out DateTime cachedUtc)
                && Math.Abs((cachedUtc - chartUtc).TotalSeconds) < 2.0)
            {
                return;
            }

            string chartText = File.ReadAllText(chartPath, Encoding.UTF8);
            ScanChartToEntry(chartText, chartUtc, out EntryDto fresh);
            index[songKey] = fresh;
            WriteIndexUnlocked(indexPath, index);
        }
    }

    /// <summary>Reads from the central index after <see cref="EnsureEntryCurrent"/>.</summary>
    public static void ReadForSongRow(string customTrackFolder, out int sortKey, out string display, out string detail)
    {
        sortKey = -1;
        display = string.Empty;
        detail = string.Empty;

        EnsureEntryCurrent(customTrackFolder);

        string chartPath = Path.Combine(customTrackFolder, "notes.chart");
        if (!File.Exists(chartPath))
        {
            return;
        }

        string? indexPath = TryGetIndexPath(customTrackFolder);
        string songKey = Path.GetFileName(customTrackFolder.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));

        if (string.IsNullOrEmpty(indexPath) || string.IsNullOrEmpty(songKey))
        {
            sortKey = 0;
            display = "?";
            return;
        }

        lock (IndexLock)
        {
            Dictionary<string, EntryDto> index = ReadIndexUnlocked(indexPath);
            if (!index.TryGetValue(songKey, out EntryDto? e))
            {
                sortKey = 0;
                display = "?";
                detail = "Missing entry in chart_authored_levels.json";
                return;
            }

            sortKey = e.Count;
            display = e.Count.ToString(CultureInfo.InvariantCulture);
            detail = e.Detail;
        }
    }
}
