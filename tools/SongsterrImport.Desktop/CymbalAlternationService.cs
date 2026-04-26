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

    internal CymbalType CymbalType { get; init; }
}

internal static class CymbalAlternationService
{
    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        CymbalType cymbalType,
        long startTick,
        long endTick
    )
    {
        return ApplyAlternation(
            midiPath,
            cymbalType,
            new List<(long start, long end)>
            {
                (startTick, endTick)
            }
        );
    }

    internal static CymbalAlternationResult ApplyAlternation(
        string midiPath,
        CymbalType cymbalType,
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

        foreach ((long start, long end) intervalValue in intervals)
        {
            if (intervalValue.start < 0)
            {
                throw new InvalidOperationException("Start tick must be >= 0.");
            }

            if (intervalValue.end < intervalValue.start)
            {
                throw new InvalidOperationException("End tick must be >= start tick.");
            }
        }

        MidiFile midiFile = MidiFile.Read(midiPath);
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
            .Where(note => IsInsideAnyInterval(note.Time, intervals))
            .Where(note => !IsTickInsideTomInterval(note.Time, tomIntervals))
            .OrderBy(note => note.Time)
            .ToList();

        List<Note> notesToRemove = new();
        for (int index = 1; index < candidateNotes.Count; index += 2)
        {
            notesToRemove.Add(candidateNotes[index]);
        }

        foreach (Note note in notesToRemove)
        {
            notesManager.Objects.Remove(note);
        }

        midiFile.Write(midiPath, overwriteFile: true);

        return new CymbalAlternationResult
        {
            MidiPath = midiPath,
            CymbalType = cymbalType,
            StartTick = intervals.Min(interval => interval.start),
            EndTick = intervals.Max(interval => interval.end),
            IntervalCount = intervals.Count,
            CandidateCount = candidateNotes.Count,
            RemovedCount = notesToRemove.Count
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
