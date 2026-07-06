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


def main():
    ap = argparse.ArgumentParser(description="Build a looping silent montage.")
    ap.add_argument("--input", required=True, help="Source video file")
    ap.add_argument("--config", required=True, help="JSON clip config")
    ap.add_argument("--output", required=True, help="Output MP4 path")
    args = ap.parse_args()

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input not found: {source}")

    cfg = json.loads(Path(args.config).read_text())
    width = int(cfg.get("width", 1280))
    height = int(cfg.get("height", 720))
    fps = int(cfg.get("fps", 30))
    # "dip" (through a color, seamless loop), "fade" (crossfade), or "cut"
    transition = cfg.get("transition", "dip")
    xfade = float(cfg.get("transition_seconds", cfg.get("crossfade_seconds", 0.3)))
    dip_color = cfg.get("dip_color", "black")   # "black" or "white"
    seamless = bool(cfg.get("seamless_loop", transition == "dip"))
    clips_cfg = cfg["clips"]

    src_duration = probe_duration(source)
    print(f"Source duration: {src_duration:.1f}s  ({len(clips_cfg)} clips requested)")

    # Validate every requested clip fits inside the source. Instead of
    # hard-failing the whole build over one bad timestamp, skip the
    # offending clip with a loud warning and keep going — a stale or
    # mistyped clips.json shouldn't take down the day's thumbnail.
    valid_clips_cfg = []
    for i, c in enumerate(clips_cfg):
        start = hms_to_seconds(c["start"])
        dur = float(c["duration"])
        if start + dur > src_duration:
            print(
                f"WARNING: skipping clip {i+1} (start {start}s + {dur}s "
                f"runs past the {src_duration:.1f}s source). Check clips.json."
            )
            continue
        valid_clips_cfg.append(c)

    skipped = len(clips_cfg) - len(valid_clips_cfg)
    if skipped:
        print(f"WARNING: {skipped} of {len(clips_cfg)} clip(s) skipped due to out-of-range timestamps.")

    if not valid_clips_cfg:
        raise SystemExit(
            "No valid clips remain after validation — every requested clip "
            "ran past the source duration. Fix clips.json."
        )

    clips_cfg = valid_clips_cfg

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clip_paths = []
        clip_durations = []

        for i, c in enumerate(clips_cfg):
            start = hms_to_seconds(c["start"])
            dur = float(c["duration"])
            out = tmp / f"clip_{i:02d}.mp4"
            print(f"  Clip {i+1}: {start:.1f}s for {dur:.1f}s")
            extract_clip(source, start, dur, out, width, height, fps)
            clip_paths.append(out)
            clip_durations.append(dur)

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
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "20", "-movflags", "+faststart",
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
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "20", "-movflags", "+faststart",
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
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "20", "-movflags", "+faststart",
                str(args.output),
            ])

    final_dur = probe_duration(args.output)
    size_mb = Path(args.output).stat().st_size / 1_000_000
    print(f"\nDone → {args.output}")
    print(f"  Duration: {final_dur:.1f}s   Size: {size_mb:.1f} MB   {width}x{height} silent")


if __name__ == "__main__":
    main()
