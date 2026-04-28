// Author: Gabriel Pinheiro de Carvalho
using System.Collections.Generic;
using System.IO;

namespace SongsterrImport.Desktop;

public sealed class SongEntry
{
    public required string DisplayName { get; init; }

    /// <summary>Absolute path to the custom track folder (under <c>original/custom/…</c>).</summary>
    public required string FullPath { get; init; }

    /// <summary>Path of <see cref="FullPath"/> as displayed from the repository root (slash-separated).</summary>
    public required string PathFromRepositoryRoot { get; init; }

    /// <summary>Whether a folder with the same name exists under <c>Songs/</c> (sync already published).</summary>
    public required string InSongsStatus { get; init; }

    /// <summary>Last-write timestamp of <c>Songs/&lt;name&gt;/notes.mid</c>, formatted as <c>yyyy-MM-dd HH:mm</c>, or empty when not present.</summary>
    public string NotesMidModifiedDisplay { get; init; } = string.Empty;

    /// <summary>Timestamp written by the difficulty generator to <c>Songs/&lt;name&gt;/.difficulties_ts</c>, or empty when not yet generated.</summary>
    public string DifficultiesGeneratedDisplay { get; init; } = string.Empty;

    /// <summary>Count of guitar single sections in <c>notes.chart</c> (Easy/Medium/Hard/Expert), from <c>original/custom/chart_authored_levels.json</c>. -1 = no chart file.</summary>
    public int ChartAuthoredLevelsSortKey { get; init; } = -1;

    /// <summary>Display of <see cref="ChartAuthoredLevelsSortKey"/> (e.g. <c>4</c> or empty).</summary>
    public string ChartAuthoredLevelsDisplay { get; init; } = string.Empty;

    /// <summary>Tooltip: which sections were found (e.g. <c>Easy, Medium, Hard, Expert</c>).</summary>
    public string ChartAuthoredLevelsDetail { get; init; } = string.Empty;

    // song.ini [song] (Clone Hero) — same names as in the file where applicable
    public string SongIniArtist { get; init; } = string.Empty;
    public string SongIniTitle { get; init; } = string.Empty;
    public string SongIniAlbum { get; init; } = string.Empty;
    public string SongIniYear { get; init; } = string.Empty;
    public string SongIniGenre { get; init; } = string.Empty;
    public string SongIniCharter { get; init; } = string.Empty;
    public string SongIniDiffDrums { get; init; } = string.Empty;
    public string SongIniDiffDrumsReal { get; init; } = string.Empty;
    public string SongIniDiffGuitar { get; init; } = string.Empty;
    public string SongIniDiffBass { get; init; } = string.Empty;
    public string SongIniDiffKeys { get; init; } = string.Empty;
    public string SongIniDiffBand { get; init; } = string.Empty;
    public string SongIniDiffRhythm { get; init; } = string.Empty;
    public string SongIniDiffGuitarGhl { get; init; } = string.Empty;
    public string SongIniDiffBassGhl { get; init; } = string.Empty;
    public string SongIniDiffVocals { get; init; } = string.Empty;
    public string SongIniLengthDisplay { get; init; } = string.Empty;
    public string SongIniPreviewDisplay { get; init; } = string.Empty;
    public string SongIniAlbumTrack { get; init; } = string.Empty;
    public string SongIniPlaylistTrack { get; init; } = string.Empty;
    public string SongIniIcon { get; init; } = string.Empty;
    public string SongIniModchart { get; init; } = string.Empty;
    public string SongIniCount { get; init; } = string.Empty;
    public string SongIniLoadingShort { get; init; } = string.Empty;
    public string SongIniLoadingFull { get; init; } = string.Empty;
    public string SongIniMore { get; init; } = string.Empty;

    public bool SongIniEndEventsOn { get; init; }
    public bool SongIniFiveLaneDrumsOn { get; init; }
    public bool SongIniProDrumsOn { get; init; }

    internal string BuildSearchableText()
    {
        return
            DisplayName
            + " " + PathFromRepositoryRoot
            + " " + FullPath
            + " " + SongIniArtist
            + " " + SongIniTitle
            + " " + SongIniAlbum
            + " " + SongIniYear
            + " " + SongIniGenre
            + " " + SongIniCharter
            + " " + SongIniDiffDrums
            + " " + SongIniDiffDrumsReal
            + " " + SongIniDiffGuitar
            + " " + SongIniDiffBass
            + " " + SongIniDiffKeys
            + " " + SongIniDiffBand
            + " " + SongIniDiffRhythm
            + " " + SongIniDiffGuitarGhl
            + " " + SongIniDiffBassGhl
            + " " + SongIniDiffVocals
            + " " + SongIniLengthDisplay
            + " " + SongIniPreviewDisplay
            + " " + SongIniAlbumTrack
            + " " + SongIniPlaylistTrack
            + " " + SongIniIcon
            + " " + SongIniModchart
            + " " + SongIniCount
            + " " + SongIniLoadingFull
            + " " + SongIniMore
            + " " + (SongIniEndEventsOn ? "end_events" : string.Empty)
            + " " + (SongIniFiveLaneDrumsOn ? "five_lane_drums" : string.Empty)
            + " " + (SongIniProDrumsOn ? "pro_drums" : string.Empty)
            + " " + ChartAuthoredLevelsDisplay
            + " " + ChartAuthoredLevelsDetail;
    }

    /// <summary>Builds a row from a custom track folder, reading <c>song.ini</c> if present. Column order in the UI matches the list below (identity and charting first, then the rest, then remaining keys in <see cref="SongIniMore"/>).</summary>
    public static SongEntry FromCustomFolder(
        string customFolderFullPath,
        string displayName,
        string pathFromRepositoryRoot,
        string inSongsStatus,
        string? songsFolderPath = null)
    {
        IReadOnlyDictionary<string, string> ini = SongIniReader.ReadSongKeys(customFolderFullPath);

        string notesMidModified = string.Empty;
        string difficultiesGenerated = string.Empty;
        if (songsFolderPath != null && Directory.Exists(songsFolderPath))
        {
            string drumChartSidecar = Path.Combine(songsFolderPath, ".drum_chart_ts");
            if (File.Exists(drumChartSidecar))
            {
                notesMidModified = (File.ReadAllText(drumChartSidecar, System.Text.Encoding.UTF8) ?? string.Empty).Trim();
            }

            string difficultiesSidecar = Path.Combine(songsFolderPath, ".difficulties_ts");
            if (File.Exists(difficultiesSidecar))
            {
                difficultiesGenerated = (File.ReadAllText(difficultiesSidecar, System.Text.Encoding.UTF8) ?? string.Empty).Trim();
            }
        }

        // Central original/custom/chart_authored_levels.json updated when notes.chart is newer than cached mtime.
        ChartAuthoredLevelsStore.ReadForSongRow(
            customFolderFullPath,
            out int chartAuthoredSortKey,
            out string chartAuthoredDisplay,
            out string chartAuthoredDetail);

        string g(string k) => SongIniReader.Get(ini, k);
        string load = g("loading_phrase");
        return new SongEntry
        {
            DisplayName = displayName,
            FullPath = customFolderFullPath,
            PathFromRepositoryRoot = pathFromRepositoryRoot,
            InSongsStatus = inSongsStatus,
            NotesMidModifiedDisplay = notesMidModified,
            DifficultiesGeneratedDisplay = difficultiesGenerated,
            ChartAuthoredLevelsSortKey = chartAuthoredSortKey,
            ChartAuthoredLevelsDisplay = chartAuthoredDisplay,
            ChartAuthoredLevelsDetail = chartAuthoredDetail,
            SongIniArtist = g("artist"),
            SongIniTitle = g("name"),
            SongIniAlbum = g("album"),
            SongIniYear = g("year"),
            SongIniGenre = g("genre"),
            SongIniCharter = g("charter"),
            SongIniDiffDrums = g("diff_drums"),
            SongIniDiffDrumsReal = g("diff_drums_real"),
            SongIniDiffGuitar = g("diff_guitar"),
            SongIniDiffBass = g("diff_bass"),
            SongIniDiffKeys = g("diff_keys"),
            SongIniDiffBand = g("diff_band"),
            SongIniDiffRhythm = g("diff_rhythm"),
            SongIniDiffGuitarGhl = g("diff_guitarghl"),
            SongIniDiffBassGhl = g("diff_bassghl"),
            SongIniDiffVocals = g("diff_vocals"),
            SongIniLengthDisplay = SongIniReader.FormatSongLengthDisplay(ini),
            SongIniPreviewDisplay = SongIniReader.FormatPreviewDisplay(ini),
            SongIniAlbumTrack = g("album_track"),
            SongIniPlaylistTrack = g("playlist_track"),
            SongIniIcon = g("icon"),
            SongIniModchart = g("modchart"),
            SongIniCount = g("count"),
            SongIniLoadingFull = load,
            SongIniLoadingShort = SongIniReader.TruncateForCell(load, 72),
            SongIniMore = SongIniReader.BuildRemainingFromIni(ini),
            SongIniEndEventsOn = SongIniReader.ParseBoolFlag(g("end_events")),
            SongIniFiveLaneDrumsOn = SongIniReader.ParseBoolFlag(g("five_lane_drums")),
            SongIniProDrumsOn = SongIniReader.ParseBoolFlag(g("pro_drums")),
        };
    }
}
