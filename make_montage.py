#!/usr/bin/env python3
"""
make_montage.py — Build a silent, looping montage from a source video.

Reads a JSON config describing which segments to pull from the source
episode, extracts each clip, joins them (crossfade or hard cut), strips
audio, and writes a web-optimized MP4 suitable for a looping thumbnail.

Usage:
    python3 make_montage.py --input episode.mp4 --config clips.json --output montage.mp4
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd):
    """Run a command, raising with stderr if it fails."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"\nCommand failed: {' '.join(cmd)}\n{result.stderr}\n")
        raise SystemExit(1)
    return result


def probe_duration(path):
    """Return the duration of a media file in seconds (float)."""
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(result.stdout.strip())


def hms_to_seconds(value):
    """Accept either a number (seconds) or 'HH:MM:SS' / 'MM:SS' string."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    parts = [float(p) for p in parts]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def extract_clip(source, start, duration, out_path, width, height, fps):
    """Extract one normalized clip. Re-encodes so all clips share a format,
    which is required for reliable concatenation and crossfades."""
    run([
        "ffmpeg", "-y",
        "-ss", str(start),          # seek to start (before -i = fast seek)
        "-i", str(source),
        "-t", str(duration),        # clip length
        "-an",                      # drop audio now; we want silent output
        "-vf", (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={fps}"
        ),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-crf", "20",
        str(out_path),
    ])


def final_output_args(crf, preset, profile, level):
    """Shared output flags for the final web-delivery encode.

    This is the ONE place file size is controlled, so all three output
    paths (cut / single / transitions) stay identical. CRF is the main
    quality-vs-size dial (higher = smaller); a slower preset squeezes more
    out of each bit for free (just more CPU, which is fine for one short
    daily render); main@3.1 + yuv420p + faststart keep it broadly playable
    and quick to start streaming in a browser.
    """
    return [
        "-an",                      # silent output — the montage has no audio
        "-c:v", "libx264",
        "-profile:v", profile,      # "main" = wide device compatibility
        "-level", str(level),       # 3.1 caps at 720p30, plenty for a thumbnail
        "-pix_fmt", "yuv420p",      # required for Safari / iOS playback
        "-preset", preset,          # slower = smaller file at the same CRF
        "-crf", str(crf),           # <-- raise this for smaller files
        "-movflags", "+faststart",  # lets playback start before full download
    ]


def build_transition_filter(clip_paths, clip_durations, xfade, xfade_type,
                            seamless, dip_color):
    """Build an ffmpeg filter_complex that chains transitions across all clips.

    xfade_type is the xfade transition name ("fade", "fadeblack", "fadewhite").
    If seamless is True, the whole montage also fades up from the dip color at
    the very start and down to it at the very end — so when the video loops,
    the end and start meet on the same solid color and the seam is invisible.

    Returns (filter_string, final_label, total_duration).
    """
    filters = []
    prev_label = "0:v"
    running = clip_durations[0]
    for i in range(1, len(clip_paths)):
        offset = running - xfade
        out_label = f"x{i}"
        filters.append(
            f"[{prev_label}][{i}:v]"
            f"xfade=transition={xfade_type}:duration={xfade}:offset={offset:.3f}"
            f"[{out_label}]"
        )
        prev_label = out_label
        running = running + clip_durations[i] - xfade

    if seamless:
        # Fade in at the head and out at the tail, both on the dip color and
        # both the same length as the between-clip dips, so the loop wraps
        # through matching color with no visible jump.
        total = running
        color = "white" if dip_color == "white" else "black"
        filters.append(
            f"[{prev_label}]"
            f"fade=t=in:st=0:d={xfade}:c={color},"
            f"fade=t=out:st={total - xfade:.3f}:d={xfade}:c={color}"
            f"[out]"
        )
        prev_label = "out"

    return ";".join(filters), prev_label, running


def build_clip_specs_fixed(source, clips_cfg, src_duration):
    """Legacy mode: one source file, explicit start/duration list from
    clips.json. Skips (with a warning) any clip that runs past the
    source's duration instead of failing the whole build."""
    specs = []
    for i, c in enumerate(clips_cfg):
        start = hms_to_seconds(c["start"])
        dur = float(c["duration"])
        if start + dur > src_duration:
            print(
                f"WARNING: skipping clip {i+1} (start {start}s + {dur}s "
                f"runs past the {src_duration:.1f}s source). Check clips.json."
            )
            continue
        specs.append({"source": source, "start": start, "duration": dur})

    skipped = len(clips_cfg) - len(specs)
    if skipped:
        print(f"WARNING: {skipped} of {len(clips_cfg)} clip(s) skipped due to out-of-range timestamps.")
    return specs


def build_clip_specs_auto(sources, position_pct, clip_len):
    """Multi-file mode: one clip per input file, taken at a fixed relative
    position (e.g. 20% through) rather than an absolute timestamp. Built
    for the daily pipeline where each input is one guest's segment and
    segment lengths vary day to day. Skips (with a warning) any segment
    too short to yield a usable clip at that offset."""
    specs = []
    for s in sources:
        dur = probe_duration(s)
        start = dur * position_pct
        this_len = min(clip_len, dur - start)
        if this_len <= 0.1:
            print(
                f"WARNING: skipping {s.name} — too short ({dur:.1f}s) for a "
                f"{position_pct * 100:.0f}% offset clip."
            )
            continue
        specs.append({"source": s, "start": start, "duration": this_len})

    skipped = len(sources) - len(specs)
    if skipped:
        print(f"WARNING: {skipped} of {len(sources)} segment(s) skipped as too short.")
    return specs


def main():
    ap = argparse.ArgumentParser(description="Build a looping silent montage.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="Single source video file (uses clips.json's fixed 'clips' list)")
    group.add_argument(
        "--inputs", nargs="+",
        help="Multiple source segment files — one auto-selected clip per file, "
             "positioned via clips.json's 'clip_position_pct' (default 20%%)"
    )
    ap.add_argument("--config", required=True, help="JSON clip config")
    ap.add_argument("--output", required=True, help="Output MP4 path")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    width = int(cfg.get("width", 1280))
    height = int(cfg.get("height", 720))
    fps = int(cfg.get("fps", 30))
    # "dip" (through a color, seamless loop), "fade" (crossfade), or "cut"
    transition = cfg.get("transition", "dip")
    xfade = float(cfg.get("transition_seconds", cfg.get("crossfade_seconds", 0.3)))
    dip_color = cfg.get("dip_color", "black")   # "black" or "white"
    seamless = bool(cfg.get("seamless_loop", transition == "dip"))

    # --- final web-delivery encode: this is what actually controls size ---
    crf = int(cfg.get("crf", 28))               # 28 is a good small-but-clean
                                                 # default for a muted loop;
                                                 # 30-32 = smaller, 23 = crisper
    preset = cfg.get("preset", "slow")           # slow = better compression
    h264_profile = cfg.get("h264_profile", "main")
    h264_level = cfg.get("h264_level", "3.1")
    final_args = final_output_args(crf, preset, h264_profile, h264_level)
    print(f"Output target: {width}x{height} @ {fps}fps, crf {crf}, preset "
          f"{preset}  (H.264 {h264_profile}@{h264_level}, silent)")

    if args.inputs:
        sources = [Path(p) for p in args.inputs]
        for s in sources:
            if not s.exists():
                raise SystemExit(f"Input not found: {s}")
        position_pct = float(cfg.get("clip_position_pct", 0.20))
        clip_len = float(cfg.get("clip_duration", 4))
        print(f"{len(sources)} input segment(s); auto-selecting one clip each at "
              f"{position_pct * 100:.0f}% offset, {clip_len:.1f}s long.")
        clip_specs = build_clip_specs_auto(sources, position_pct, clip_len)
    else:
        source = Path(args.input)
        if not source.exists():
            raise SystemExit(f"Input not found: {source}")
        src_duration = probe_duration(source)
        clips_cfg = cfg["clips"]
        print(f"Source duration: {src_duration:.1f}s  ({len(clips_cfg)} clips requested)")
        clip_specs = build_clip_specs_fixed(source, clips_cfg, src_duration)

    if not clip_specs:
        raise SystemExit(
            "No usable clips remain after validation — nothing to build. "
            "Check your source(s) and config."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clip_paths = []
        clip_durations = []

        for i, spec in enumerate(clip_specs):
            out = tmp / f"clip_{i:02d}.mp4"
            print(f"  Clip {i+1}: {spec['source'].name} @ {spec['start']:.1f}s for {spec['duration']:.1f}s")
            extract_clip(spec["source"], spec["start"], spec["duration"], out, width, height, fps)
            clip_paths.append(out)
            clip_durations.append(spec["duration"])

        single = len(clip_paths) == 1

        if transition == "cut":
            # Hard cuts via the concat demuxer — no transitions at all.
            list_file = tmp / "list.txt"
            list_file.write_text(
                "".join(f"file '{p}'\n" for p in clip_paths)
            )
            run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                *final_args,
                str(args.output),
            ])
        elif single:
            # One clip: just fade it in/out on the dip color for a clean loop.
            color = "white" if dip_color == "white" else "black"
            total = clip_durations[0]
            vf = (
                f"fade=t=in:st=0:d={xfade}:c={color},"
                f"fade=t=out:st={total - xfade:.3f}:d={xfade}:c={color}"
            ) if seamless else "null"
            run([
                "ffmpeg", "-y", "-i", str(clip_paths[0]),
                "-vf", vf,
                *final_args,
                str(args.output),
            ])
        else:
            # "dip" -> fadeblack/fadewhite (seamless loop by default).
            # "fade" -> plain crossfade.
            if transition == "dip":
                xfade_type = "fadewhite" if dip_color == "white" else "fadeblack"
            else:
                xfade_type = "fade"
            filter_str, final, _ = build_transition_filter(
                clip_paths, clip_durations, xfade, xfade_type,
                seamless, dip_color
            )
            inputs = []
            for p in clip_paths:
                inputs += ["-i", str(p)]
            run([
                "ffmpeg", "-y", *inputs,
                "-filter_complex", filter_str,
                "-map", f"[{final}]",
                *final_args,
                str(args.output),
            ])

    final_dur = probe_duration(args.output)
    size_mb = Path(args.output).stat().st_size / 1_000_000
    print(f"\nDone → {args.output}")
    print(f"  Duration: {final_dur:.1f}s   Size: {size_mb:.1f} MB   {width}x{height} silent")


if __name__ == "__main__":
    main()
