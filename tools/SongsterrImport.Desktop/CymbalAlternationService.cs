using Melanchall.DryWetMidi.Core;
using Melanchall.DryWetMidi.Interaction;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace SongsterrImport.Desktop;

internal sealed class CymbalAlternationResult
{
    internal int IntervalCount { get; init; }

    internal int CandidateCount { get; init; }

    internal int RemovedCount { get; init; }

    internal long StartTick { get; init; }

    internal long EndTick { get; init; }

    internal string MidiPath { get; init; } = string.Empty;

    internal string BackupFilePath { get; init; } = string.Empty;
}

internal static class CymbalAlternationService
{
    /// <summary>Expert ride cymbals: yellow, blue, green (not tom-colored).</summary>
    private static readonly int[] ExpertCymbalPitches = { 98, 99, 100 };

    private static int TomMarkerForCymbalPitch(int cymbalPitch)
    {
        if (cymbalPitch == 98)
        {
            return 110;
        }

        if (cymbalPitch == 99)
        {
            return 111;
        }

        if (cymbalPitch == 100)
        {
            return 112;
        }

        return -1;
    }

    /// <summary>Alternation over every expert cymbal in each tick range, one combined timeline (all colors mixed).</summary>
    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        IReadOnlyList<(long start, long end)> intervals
    )
    {
        if (!File.Exists(midiPath))
        {
            throw new InvalidOperationException("MIDI file does not exist.");
        }

        if (intervals.Count == 0)
        {
            throw new InvalidOperationException("Please add at least one interval.");
        }

        foreach ((long start, long end) in intervals)
        {
            if (start < 0)
            {
                throw new InvalidOperationException("Start tick must be >= 0.");
            }

            if (end < start)
            {
                throw new InvalidOperationException("End tick must be >= start tick.");
            }
        }

        string backupFilePath = CreateTimestampedBackupOfMidi(midiPath);
        MidiFile midiFile = ReadMidiFileRelaxed(midiPath);
        TrackChunk targetTrack = ResolvePartDrumsTrack(midiFile);

        IReadOnlyList<(long start, long end)>[] tomByCymbalPitch = new IReadOnlyList<(long start, long end)>[128];
        foreach (int pitch in ExpertCymbalPitches)
        {
            int marker = TomMarkerForCymbalPitch(pitch);
            tomByCymbalPitch[pitch] = BuildTomIntervals(targetTrack, marker);
        }

        List<(long start, long end)> tickRanges = intervals
            .OrderBy(r => r.start)
            .ThenBy(r => r.end)
            .ToList();

        int intervalCount = intervals.Count;
        long minStart = intervals.Min(x => x.start);
        long maxEnd = intervals.Max(x => x.end);

        // NotesManager applies note edits to the track chunk on Dispose. Writing the MidiFile must happen
        // after the manager is disposed, otherwise the file on disk can still contain the unedited events.
        int candidateCount;
        int totalRemovedLocal;
        using (var notesManager = targetTrack.ManageNotes())
        {
            HashSet<Note> notesUsedInARange = new();
            List<Note> allNotesToRemove = new();
            candidateCount = 0;
            foreach ((long rangeStart, long rangeEnd) in tickRanges)
            {
                List<Note> candidateNotes = notesManager.Objects
                    .Where(note => IsExpertCymbalPitch((int)note.NoteNumber))
                    .Where(note => rangeStart <= note.Time && note.Time <= rangeEnd)
                    .Where(note => !IsCymbalCountingAsTom(note, tomByCymbalPitch))
                    .Where(note => !notesUsedInARange.Contains(note))
                    .OrderBy(note => note.Time)
                    .ThenBy(note => (int)note.NoteNumber)
                    .ToList();
                if (candidateNotes.Count == 0)
                {
                    continue;
                }

                notesUsedInARange.UnionWith(candidateNotes);
                candidateCount += candidateNotes.Count;
                IReadOnlyList<Note> removalsInRange = SelectNotesToRemoveForAlternationInRange(
                    candidateNotes,
                    rangeStart
                );
                allNotesToRemove.AddRange(removalsInRange);
            }

            foreach (Note note in allNotesToRemove)
            {
                notesManager.Objects.Remove(note);
            }

            totalRemovedLocal = allNotesToRemove.Count;
        }

        int totalRemoved = totalRemovedLocal;
        int totalCandidates = candidateCount;
        midiFile.Write(midiPath, overwriteFile: true);

        return new CymbalAlternationResult
        {
            MidiPath = midiPath,
            StartTick = minStart,
            EndTick = maxEnd,
            IntervalCount = intervalCount,
            CandidateCount = totalCandidates,
            RemovedCount = totalRemoved,
            BackupFilePath = backupFilePath
        };
    }

    private static string CreateTimestampedBackupOfMidi(string sourceMidiPath)
    {
        string? directory = Path.GetDirectoryName(sourceMidiPath);
        if (string.IsNullOrEmpty(directory))
        {
            throw new InvalidOperationException("MIDI path has no directory.");
        }

        string nameWithout = Path.GetFileNameWithoutExtension(sourceMidiPath);
        string ext = Path.GetExtension(sourceMidiPath);
        string timestamp = DateTime.Now.ToString("yyyy-MM-dd-HH-mm", CultureInfo.InvariantCulture);
        string fileName = nameWithout + "." + timestamp + ".backup" + ext;
        string destPath = Path.Combine(directory, fileName);
        if (File.Exists(destPath))
        {
            fileName = nameWithout + "." + timestamp + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".backup" + ext;
            destPath = Path.Combine(directory, fileName);
        }

        try
        {
            File.Copy(sourceMidiPath, destPath, overwrite: false);
        }
        catch (IOException ex)
        {
            throw new InvalidOperationException("Could not create backup copy of the MIDI: " + ex.Message, ex);
        }

        return destPath;
    }

    private static bool IsExpertCymbalPitch(int noteNumber)
    {
        for (int index = 0; index < ExpertCymbalPitches.Length; index++)
        {
            if (ExpertCymbalPitches[index] == noteNumber)
            {
                return true;
            }
        }

        return false;
    }

    private static bool IsCymbalCountingAsTom(Note note, IReadOnlyList<(long start, long end)>[] tomByCymbalPitch)
    {
        int key = (int)note.NoteNumber;
        IReadOnlyList<(long start, long end)>? toms = null;
        if (key >= 0 && key < tomByCymbalPitch.Length)
        {
            toms = tomByCymbalPitch[key];
        }

        if (toms is null)
        {
            return false;
        }

        return IsTickInsideTomInterval(note.Time, toms);
    }

    private static MidiFile ReadMidiFileRelaxed(string midiPath)
    {
        byte[] fileBytes = File.ReadAllBytes(midiPath);
        if (fileBytes.Length < 4)
        {
            throw new InvalidOperationException("MIDI file is too small to be a valid file.");
        }

        ReadingSettings readingSettings = new()
        {
            InvalidChannelEventParameterValuePolicy = InvalidChannelEventParameterValuePolicy.ReadValid,
            InvalidChunkSizePolicy = InvalidChunkSizePolicy.Ignore,
            InvalidMetaEventParameterValuePolicy = InvalidMetaEventParameterValuePolicy.SnapToLimits,
            MissedEndOfTrackPolicy = MissedEndOfTrackPolicy.Ignore,
            NoHeaderChunkPolicy = NoHeaderChunkPolicy.Ignore,
            NotEnoughBytesPolicy = NotEnoughBytesPolicy.Ignore,
            UnexpectedTrackChunksCountPolicy = UnexpectedTrackChunksCountPolicy.Ignore,
            UnknownChannelEventPolicy = UnknownChannelEventPolicy.SkipStatusByteAndOneDataByte,
            UnknownChunkIdPolicy = UnknownChunkIdPolicy.ReadAsUnknownChunk,
            UnknownFileFormatPolicy = UnknownFileFormatPolicy.Ignore
        };

        using var stream = new MemoryStream(fileBytes, writable: false);
        return MidiFile.Read(stream, readingSettings);
    }

    private static IReadOnlyList<Note> SelectNotesToRemoveForAlternationInRange(
        IReadOnlyList<Note> candidateNotes,
        long rangeStart
    )
    {
        if (candidateNotes.Count == 0)
        {
            return Array.Empty<Note>();
        }

        bool hasVirtualKeptAtAnchor = candidateNotes[0].Time > rangeStart;
        var notesToRemove = new List<Note>();
        for (int realIndex = 0; realIndex < candidateNotes.Count; realIndex++)
        {
            bool isRemove;
            if (hasVirtualKeptAtAnchor)
            {
                isRemove = (realIndex % 2 == 0);
            }
            else
            {
                isRemove = (realIndex % 2 == 1);
            }

            if (isRemove)
            {
                notesToRemove.Add(candidateNotes[realIndex]);
            }
        }

        return notesToRemove;
    }

    private static TrackChunk ResolvePartDrumsTrack(MidiFile midiFile)
    {
        List<TrackChunk> trackChunks = midiFile.GetTrackChunks().ToList();
        if (trackChunks.Count == 0)
        {
            throw new InvalidOperationException("MIDI does not contain track chunks.");
        }

        TrackChunk? partDrumsTrack = trackChunks
            .FirstOrDefault(trackChunk => string.Equals(GetTrackName(trackChunk), "PART DRUMS", StringComparison.OrdinalIgnoreCase));
        if (partDrumsTrack is not null)
        {
            return partDrumsTrack;
        }

        foreach (int pitch in ExpertCymbalPitches)
        {
            TrackChunk? t = trackChunks
                .FirstOrDefault(chunk => chunk.GetNotes().Any(n => (int)n.NoteNumber == pitch));
            if (t is not null)
            {
                return t;
            }
        }

        throw new InvalidOperationException("PART DRUMS track was not found.");
    }

    private static string GetTrackName(TrackChunk trackChunk)
    {
        SequenceTrackNameEvent? trackNameEvent = trackChunk.Events
            .OfType<SequenceTrackNameEvent>()
            .FirstOrDefault();
        if (trackNameEvent is null)
        {
            return string.Empty;
        }

        return trackNameEvent.Text ?? string.Empty;
    }

    private static List<(long start, long end)> BuildTomIntervals(TrackChunk trackChunk, int markerPitch)
    {
        List<(long start, long end)> intervals = new();
        bool isMarkerActive = false;
        long markerStartTick = 0;

        foreach (TimedEvent timedEvent in trackChunk.GetTimedEvents().OrderBy(eventValue => eventValue.Time))
        {
            MidiEvent midiEvent = timedEvent.Event;
            if (midiEvent is NoteOnEvent noteOnEvent && (int)noteOnEvent.NoteNumber == markerPitch)
            {
                if (noteOnEvent.Velocity > 0)
                {
                    if (!isMarkerActive)
                    {
                        isMarkerActive = true;
                        markerStartTick = timedEvent.Time;
                    }
                }
                else
                {
                    if (isMarkerActive)
                    {
                        intervals.Add((markerStartTick, timedEvent.Time));
                        isMarkerActive = false;
                    }
                }
            }
            else if (midiEvent is NoteOffEvent noteOffEvent && (int)noteOffEvent.NoteNumber == markerPitch)
            {
                if (isMarkerActive)
                {
                    intervals.Add((markerStartTick, timedEvent.Time));
                    isMarkerActive = false;
                }
            }
        }

        if (isMarkerActive)
        {
            intervals.Add((markerStartTick, long.MaxValue));
        }

        return intervals;
    }

    private static bool IsTickInsideTomInterval(long tick, IReadOnlyList<(long start, long end)> intervals)
    {
        for (int index = 0; index < intervals.Count; index++)
        {
            (long start, long end) = intervals[index];
            if (tick >= start && tick < end)
            {
                return true;
            }
        }

        return false;
    }
}
