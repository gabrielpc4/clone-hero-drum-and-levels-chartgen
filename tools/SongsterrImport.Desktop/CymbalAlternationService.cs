using Melanchall.DryWetMidi.Core;
using Melanchall.DryWetMidi.Interaction;
using System.IO;
using System.Linq;

namespace SongsterrImport.Desktop;

internal enum CymbalType
{
    Yellow = 2,
    Blue = 3,
    Green = 4
}

internal sealed class CymbalAlternationResult
{
    internal int IntervalCount { get; init; }

    internal int CandidateCount { get; init; }

    internal int RemovedCount { get; init; }

    internal long StartTick { get; init; }

    internal long EndTick { get; init; }

    internal string MidiPath { get; init; } = string.Empty;
}

internal static class CymbalAlternationService
{
    /// <summary>Single cymbal, single [start, end] tick range.</summary>
    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        CymbalType cymbalType,
        long startTick,
        long endTick
    )
    {
        return ApplyAlternation(
            midiPath,
            new List<(CymbalType Cymbal, long Start, long End)>
            {
                (cymbalType, startTick, endTick)
            }
        );
    }

    /// <summary>One cymbal, many tick ranges (same as before, but named intervals).</summary>
    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        CymbalType cymbalType,
        IReadOnlyList<(long start, long end)> intervals
    )
    {
        IReadOnlyList<(CymbalType Cymbal, long Start, long End)> withCymbal = intervals
            .Select(interval => (cymbalType, interval.start, interval.end))
            .ToList();
        return ApplyAlternation(midiPath, withCymbal);
    }

    /// <summary>Many intervals, each with its own cymbal (yellow/blue/green) for the same MIDI file.</summary>
    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        IReadOnlyList<(CymbalType Cymbal, long Start, long End)> intervals
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

        foreach ((CymbalType cymbalType, long start, long end) in intervals)
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

        MidiFile midiFile = MidiFile.Read(midiPath);
        int totalRemoved = 0;
        int totalCandidates = 0;
        int intervalCount = intervals.Count;
        long minStart = intervals.Min(x => x.Start);
        long maxEnd = intervals.Max(x => x.End);
        List<IGrouping<CymbalType, (CymbalType Cymbal, long Start, long End)>> byCymbal = intervals
            .GroupBy(x => x.Cymbal)
            .ToList();

        foreach (IGrouping<CymbalType, (CymbalType Cymbal, long Start, long End)> group in byCymbal)
        {
            CymbalType cymbalType = group.Key;
            List<(long start, long end)> tickRanges = group.Select(x => (x.Start, x.End)).ToList();

            TrackChunk targetTrack = ResolvePartDrumsTrack(midiFile, cymbalType);

            int cymbalPitch = 96 + (int)cymbalType;
            int tomMarkerPitch = cymbalType switch
            {
                CymbalType.Yellow => 110,
                CymbalType.Blue => 111,
                CymbalType.Green => 112,
                _ => throw new InvalidOperationException("Unknown cymbal type.")
            };

            List<(long start, long end)> tomIntervals = BuildTomIntervals(targetTrack, tomMarkerPitch);

            using var notesManager = targetTrack.ManageNotes();
            List<Note> candidateNotes = notesManager.Objects
                .Where(note => (int)note.NoteNumber == cymbalPitch)
                .Where(note => IsInsideAnyInterval(note.Time, tickRanges))
                .Where(note => !IsTickInsideTomInterval(note.Time, tomIntervals))
                .OrderBy(note => note.Time)
                .ToList();

            totalCandidates += candidateNotes.Count;

            List<Note> notesToRemove = new();
            for (int index = 1; index < candidateNotes.Count; index += 2)
            {
                notesToRemove.Add(candidateNotes[index]);
            }

            foreach (Note note in notesToRemove)
            {
                notesManager.Objects.Remove(note);
            }

            totalRemoved += notesToRemove.Count;
        }

        midiFile.Write(midiPath, overwriteFile: true);

        return new CymbalAlternationResult
        {
            MidiPath = midiPath,
            StartTick = minStart,
            EndTick = maxEnd,
            IntervalCount = intervalCount,
            CandidateCount = totalCandidates,
            RemovedCount = totalRemoved
        };
    }

    private static bool IsInsideAnyInterval(long tick, IReadOnlyList<(long start, long end)> intervals)
    {
        foreach ((long start, long end) intervalValue in intervals)
        {
            if (tick >= intervalValue.start && tick <= intervalValue.end)
            {
                return true;
            }
        }

        return false;
    }

    private static TrackChunk ResolvePartDrumsTrack(MidiFile midiFile, CymbalType cymbalType)
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

        int cymbalPitch = 96 + (int)cymbalType;
        TrackChunk? fallbackTrack = trackChunks
            .FirstOrDefault(trackChunk => trackChunk.GetNotes().Any(note => (int)note.NoteNumber == cymbalPitch));
        if (fallbackTrack is not null)
        {
            return fallbackTrack;
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
        foreach ((long start, long end) intervalValue in intervals)
        {
            if (tick >= intervalValue.start && tick < intervalValue.end)
            {
                return true;
            }
        }

        return false;
    }
}
