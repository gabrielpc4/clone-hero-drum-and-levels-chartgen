# Songsterr Perfect Sync Findings

This document captures the key findings and nuances that made the Songsterr drum import line up perfectly with the real song audio.

## Core discovery

The exported Songsterr MIDI is not the full timing truth used by the Songsterr web player.

The site exposes an extra timing layer through:

- `https://www.songsterr.com/api/meta/<songId>`
- `https://www.songsterr.com/api/video-points/<songId>/<revisionId>/list`

For `Lonely Day`:

- `songId = 443`
- `revisionId = 6378315`
- main linked video `videoId = DnGdoEa1tPg`
- `101` timing points

Those `101` points behave like real-time anchors for Songsterr playback.

The crucial consequence is:

- the Songsterr MIDI by itself is not enough
- the Songsterr web player is effectively using a time warp on top of the MIDI

## Why the old approaches drifted

The main reason for drift was not just "wrong BPM".

It was a combination of:

1. Songsterr MIDI notation time and real media time are different.
2. The Songsterr page uses `video-points` to warp playback.
3. The Clone Hero custom chart has its own tempo map with many micro BPM adjustments.
4. The same musical section can be notated under different meters.

For `Lonely Day`, this was especially important because:

- Songsterr is mostly in `6/8`
- the custom `notes.chart` is in `4/4`
- Songsterr has about `102` theoretical measure starts
- the custom chart has `52` measures

This means both sides describe the same song structure, but with different measure grids.

The useful mental model is:

- roughly two Songsterr measures map to one custom chart measure

## Critical timing nuance

There are three different timelines involved:

1. Songsterr MIDI tick time
2. Songsterr web playback time from `video-points`
3. Real custom song audio time from `song.opus`

Perfect sync only happened after treating them as separate layers.

## What finally worked

### 1. Use Songsterr `video-points` as the primary sync source

The successful path was:

- source Songsterr MIDI tick
- source Songsterr measure anchors
- Songsterr `video-points`
- target custom chart tempo map
- final Clone Hero ticks

That gave the correct large-scale timing shape across the song.

### 2. Apply a fixed audio offset after the Songsterr warp

Even after the Songsterr warp, the first mapped drum note landed too early for `Lonely Day`.

Observed values:

- warped Songsterr first note landed around `39.541s`
- real desired drum entry was `41.440s`

So the real audio still needed a fixed offset relative to the Songsterr video timeline.

This was solved by:

- detecting the true first dramatic rise in `song.opus`
- measuring the first mapped drum time after the Songsterr warp
- applying a constant audio offset on top of the entire warped result

That kept the full Songsterr timing shape, while moving the whole result onto the real audio start.

### 3. Snap Songsterr anchors onto the target chart grid

After the large-scale sync was correct, there were still light local deviations.

These were caused by:

- the custom chart using many micro BPM adjustments
- the Songsterr warp producing times that were musically right, but not always perfectly sitting on the strongest visible fretboard grid lines

The cleanup that fixed this was:

- convert each Songsterr anchor into a target tick
- snap those anchor ticks onto the custom chart half-measure grid
- rebuild the tick interpolation using the snapped anchor ticks

This acted as a post-process cleanup pass.

It did not change the overall section placement.

It only cleaned local drift.

## Why half-measure grid worked

The strongest useful visual grid for this song was not every tiny subdivision.

Snapping to a half-measure grid worked well because:

- it was strong enough to stabilize the chart
- it respected the custom chart phrasing
- it did not over-quantize fills or finer drum placements

Snapping directly to overly dense subdivisions would risk forcing bad timing.

## Validation result

Once the full process was in place, `Lonely Day` became effectively locked.

The successful sequence was:

1. Songsterr `video-points` warp
2. fixed audio offset to the real `song.opus`
3. post-process snapping of anchors to the target chart half-measure grid

After that:

- first note landed at `41.441s`
- target audio rise was `41.440s`
- all `101` anchors were snapped to the chart grid
- mean absolute alignment to nearby audio peaks was about `10.2ms`
- p95 absolute alignment was about `37.5ms`

That was the first state that felt perfectly synchronized in practice.

## Important implementation lessons

### Songsterr URL alone is enough to resolve timing

The importer can derive:

- `songId` from the page URL
- `revisionId` from `meta`
- the correct timing series from `video-points`

This means the Songsterr page is the key external input, not just the downloaded MIDI.

### The video choice matters

Different Songsterr videos for the same revision can have different offsets.

So the implementation should:

- pin to a specific `videoId` when needed
- otherwise choose the main page video

### Fail loudly

If `meta` or `video-points` are missing, the importer should not silently pretend it is doing a perfect sync.

This is not a safe place for silent fallback behavior.

### The custom chart remains the target truth

Even when Songsterr provides the warp shape, the final target must still be the custom chart tempo map.

That is what keeps the generated drums aligned with:

- the actual `song.opus`
- the Clone Hero note highway
- the visible fretboard measure lines

## Best-practice sync recipe

For songs similar to `Lonely Day`, the recommended order is:

1. Load the Songsterr MIDI.
2. Resolve Songsterr `meta` and `video-points`.
3. Build source measure anchors from the Songsterr MIDI.
4. Warp those anchors into real media time using `video-points`.
5. Convert warped anchor times into target chart ticks.
6. Detect the real first audio rise in `song.opus`.
7. Apply the fixed audio offset so the first drum entry lands on the real audio.
8. Snap the warped anchors onto the target chart half-measure grid.
9. Rebuild the final tick mapper from those snapped anchors.
10. Write `PART DRUMS` using the final mapper.

## Short version

The key was realizing that perfect sync required all three of these at the same time:

- Songsterr web timing anchors
- real audio offset correction
- post-process anchor cleanup against the Clone Hero chart grid

Any one of those missing was enough to leave audible drift.
