# TITV Montage

Builds a silent, looping montage from a TITV episode — for use as a
looping video thumbnail on the website. Pulls short clips from configured
timestamps, crossfades them, strips audio, and outputs a web-optimized MP4.

## Repo layout

```
make_montage.py              the montage engine
clips.json                   which moments to grab (edit this per episode)
.github/workflows/montage.yml   the GitHub Action
```

> Note: put `montage.yml` at `.github/workflows/montage.yml` in the repo.
> It ships here at the top level just so it's easy to find.

## Run it locally

Requires FFmpeg and Python 3.

```bash
python3 make_montage.py --input episode.mp4 --config clips.json --output montage.mp4
```

## Editing clips.json

```json
{
  "width": 1280,              // output size
  "height": 720,
  "fps": 30,
  "transition": "dip",        // "dip", "fade" (crossfade), or "cut"
  "dip_color": "black",       // "black" or "white" (dip mode only)
  "seamless_loop": true,      // fade ends on dip_color so the loop wraps invisibly
  "transition_seconds": 0.3,  // length of each transition
  "clips": [
    { "start": "00:05", "duration": 4 },   // start = seconds or MM:SS or HH:MM:SS
    { "start": "01:30", "duration": 4 }
  ]
}
```

Total montage length = sum of durations − (number of transitions × transition_seconds).

### Transition modes

- `dip` (default) — each clip blinks through black (or white) into the next.
  With `seamless_loop` on, the montage also fades up from the dip color at
  the start and down to it at the end, so when the player loops, the seam is
  invisible. Best choice for a looping thumbnail.
- `fade` — a plain crossfade between clips (no dip color).
- `cut` — hard cuts, no transitions.

The script validates every clip fits inside the source video before it
starts, so a bad timestamp fails fast with a clear message.

## Running via GitHub Actions (manual, for now)

1. Push this repo to GitHub.
2. Go to the **Actions** tab → **TITV Montage** → **Run workflow**.
3. Paste a direct download URL for the episode and run.
4. Download the finished `montage.mp4` from the run's artifacts.

## Later: automating the fetch

Once Frame.io API access is set up, uncomment the `schedule` block in
the workflow and add a fetch step that pulls the day's episode from
Frame.io before the montage step. The engine itself doesn't change.
