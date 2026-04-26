// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.IO;

namespace SongsterrImport.Desktop;

internal static class AppServices
{
    private const string IncludeSoftNotesKey = "include_soft_notes";
    private const string ExpertCymbalAlternationWholeKey = "expert_cymbal_alternation_whole_chart";

    internal static string LastSelectedTrackPathFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SongsterrImport",
        "last_selected_track_path.txt"
    );

    internal static string UserOptionsFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SongsterrImport",
        "ui_options.txt"
    );

    internal static string ReadLastSelectedTrackPathFromRepository()
    {
        if (!File.Exists(LastSelectedTrackPathFilePath))
        {
            return string.Empty;
        }

        return (File.ReadAllText(LastSelectedTrackPathFilePath) ?? string.Empty).Trim();
    }

    internal static void WriteLastSelectedTrackPathFromRepository(string? pathFromRepositoryRoot)
    {
        string dir = Path.GetDirectoryName(LastSelectedTrackPathFilePath) ?? string.Empty;
        if (dir.Length == 0)
        {
            return;
        }

        Directory.CreateDirectory(dir);
        string line = (pathFromRepositoryRoot ?? string.Empty)
            .Replace("\r", string.Empty)
            .Replace("\n", string.Empty);
        File.WriteAllText(LastSelectedTrackPathFilePath, line, System.Text.Encoding.UTF8);
    }

    private static Dictionary<string, string> ReadUserOptions()
    {
        var options = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(UserOptionsFilePath))
        {
            return options;
        }

        foreach (string rawLine in File.ReadAllLines(UserOptionsFilePath))
        {
            string line = rawLine.Trim();
            if (line.Length == 0)
            {
                continue;
            }

            int separatorIndex = line.IndexOf('=');
            if (separatorIndex <= 0 || separatorIndex >= line.Length - 1)
            {
                continue;
            }

            string key = line[..separatorIndex].Trim();
            string value = line[(separatorIndex + 1)..].Trim();
            if (key.Length == 0)
            {
                continue;
            }

            options[key] = value;
        }

        return options;
    }

    private static void WriteUserOptions(Dictionary<string, string> options)
    {
        string dir = Path.GetDirectoryName(UserOptionsFilePath) ?? string.Empty;
        if (dir.Length == 0)
        {
            return;
        }

        Directory.CreateDirectory(dir);
        var lines = new List<string>();
        foreach (KeyValuePair<string, string> pair in options)
        {
            lines.Add(pair.Key + "=" + pair.Value);
        }

        File.WriteAllLines(UserOptionsFilePath, lines, System.Text.Encoding.UTF8);
    }

    private static bool ParseBooleanOption(string value, bool defaultValue)
    {
        if (value == "1" || value.Equals("true", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (value == "0" || value.Equals("false", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return defaultValue;
    }

    private static bool ReadBooleanOption(string key, bool defaultValue)
    {
        Dictionary<string, string> options = ReadUserOptions();
        if (!options.TryGetValue(key, out string? value))
        {
            return defaultValue;
        }

        return ParseBooleanOption(value, defaultValue);
    }

    private static void WriteBooleanOption(string key, bool value)
    {
        Dictionary<string, string> options = ReadUserOptions();
        options[key] = value ? "1" : "0";
        WriteUserOptions(options);
    }

    internal static bool ReadIncludeSoftNotesEnabled(bool defaultValue = true)
    {
        return ReadBooleanOption(IncludeSoftNotesKey, defaultValue);
    }

    internal static void WriteIncludeSoftNotesEnabled(bool enabled)
    {
        WriteBooleanOption(IncludeSoftNotesKey, enabled);
    }

    internal static bool ReadExpertCymbalAlternationWholeEnabled(bool defaultValue = false)
    {
        return ReadBooleanOption(ExpertCymbalAlternationWholeKey, defaultValue);
    }

    internal static void WriteExpertCymbalAlternationWholeEnabled(bool enabled)
    {
        WriteBooleanOption(ExpertCymbalAlternationWholeKey, enabled);
    }
}
