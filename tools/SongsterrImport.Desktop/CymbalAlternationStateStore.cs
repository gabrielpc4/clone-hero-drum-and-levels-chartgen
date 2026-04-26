using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SongsterrImport.Desktop;

/// <summary>
/// Persists cymbal-tool UI state (MIDI path and tick intervals) under ApplicationData.
/// </summary>
internal static class CymbalAlternationStateStore
{
    private const string StateFileName = "cymbal_alternation_state.json";

    private static string StateFilePath
    {
        get
        {
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string folder = Path.Combine(appData, "SongsterrImport");
            return Path.Combine(folder, StateFileName);
        }
    }

    internal static void Save(CymbalAlternationStateDto state)
    {
        string directory = Path.GetDirectoryName(StateFilePath) ?? string.Empty;
        if (directory.Length > 0)
        {
            Directory.CreateDirectory(directory);
        }

        JsonSerializerOptions options = new()
        {
            WriteIndented = true
        };
        string json = JsonSerializer.Serialize(state, options);
        File.WriteAllText(StateFilePath, json);
    }

    /// <summary>
    /// Returns null state when the file is missing. When the file exists but is invalid, returns a diagnostic message.
    /// </summary>
    internal static (CymbalAlternationStateDto? State, string? ErrorMessage) Load()
    {
        if (!File.Exists(StateFilePath))
        {
            return (null, null);
        }

        try
        {
            string json = File.ReadAllText(StateFilePath);
            CymbalAlternationStateDto? state = JsonSerializer.Deserialize<CymbalAlternationStateDto>(json);
            if (state is null)
            {
                return (null, "Saved session file was empty or invalid JSON.");
            }

            return (state, null);
        }
        catch (Exception ex)
        {
            return (null, "Could not read saved session: " + ex.Message);
        }
    }
}

internal sealed class CymbalAlternationStateDto
{
    [JsonPropertyName("midiPath")]
    public string? MidiPath { get; set; }

    [JsonPropertyName("startTickText")]
    public string? StartTickText { get; set; }

    [JsonPropertyName("endTickText")]
    public string? EndTickText { get; set; }

    [JsonPropertyName("intervals")]
    public List<CymbalIntervalDto>? Intervals { get; set; }
}

internal sealed class CymbalIntervalDto
{
    [JsonPropertyName("cymbal")]
    public string? Cymbal { get; set; }

    [JsonPropertyName("start")]
    public long Start { get; set; }

    [JsonPropertyName("end")]
    public long End { get; set; }
}
