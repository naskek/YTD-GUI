from __future__ import annotations

import os
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import mini_url_converter as core
import ui_assets as previous


FFMPEG_OUT_TIME_RE = re.compile(
    r"^out_time=(?P<h>\d+):(?P<m>\d+):(?P<s>\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)


def _strip_mp3_postprocessor_args(command: list[str]) -> list[str]:
    """Keep yt-dlp as the downloader; MP3 conversion is handled directly by ffmpeg."""
    stripped: list[str] = []
    index = 0
    while index < len(command):
        arg = command[index]
        if arg == "--extract-audio":
            index += 1
            continue
        if arg in {"--audio-format", "--audio-quality"}:
            index += 2
            continue
        stripped.append(arg)
        index += 1
    return stripped


def _ffmpeg_out_time_seconds(line: str) -> float | None:
    match = FFMPEG_OUT_TIME_RE.match(line.strip())
    if match is None:
        return None
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + float(match.group("s"))
    )


class App(previous.App):
    def build_command(self, url: str) -> list[str]:
        command = super().build_command(url)
        if str(self.ytdlp_settings.get("output_mode")) == "mp3":
            command = _strip_mp3_postprocessor_args(command)
        return command

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        output_file = super().run_ytdlp_command(command)
        if str(self.ytdlp_settings.get("output_mode")) != "mp3":
            return output_file
        return self._convert_downloaded_audio_to_mp3(output_file)

    def _probe_audio_duration(self, source: Path) -> float:
        if self._media_duration_seconds > 0:
            return self._media_duration_seconds

        command = [
            str(core.FFPROBE_PATH),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ]
        try:
            lines = self.run_logged_command(
                command,
                source.parent,
                "ffprobe duration",
                log_output=False,
            )
        except Exception:
            return 0.0

        for line in reversed(lines):
            try:
                duration = float(line.strip())
            except ValueError:
                continue
            if duration > 0:
                self._media_duration_seconds = duration
                return duration
        return 0.0

    def _convert_downloaded_audio_to_mp3(self, output_file: str | None) -> str | None:
        source_text = output_file or self.last_output_file
        if not source_text:
            raise core.AppError("yt-dlp did not report the downloaded audio file path.")

        source = Path(source_text)
        if not source.is_absolute():
            source = Path(self.resolve_output_path(str(source)))
        if not source.is_file():
            raise core.AppError(f"Downloaded audio file was not found: {source}")

        if source.suffix.lower() == ".mp3":
            self.last_output_file = str(source)
            self._set_task_progress(100.0, "100%", self.rt("status_converting_mp3"))
            return str(source)

        target = source.with_suffix(".mp3")
        temp_target = target.with_suffix(".ytd-converting.mp3")
        duration = self._probe_audio_duration(source)

        self._track_run_artifact(str(target))
        self._track_run_artifact(str(temp_target))
        self._set_progress(max(self.total_progress_value, 92.0), "92%")
        if duration > 0:
            self._set_task_progress(0.0, "0%", self.rt("status_converting_mp3"))
        else:
            self._set_task_busy("...", self.rt("status_converting_mp3"))
        self._set_status(self.rt("status_converting_mp3"))

        try:
            if temp_target.exists():
                temp_target.unlink()
        except OSError:
            pass

        command = [
            str(core.FFMPEG_PATH),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            core.MP3_AUDIO_QUALITY,
            "-map_metadata",
            "0",
            "-progress",
            "pipe:1",
            "-nostats",
            str(temp_target),
        ]

        def handle_progress(line: str) -> None:
            if line.strip().lower() == "progress=end":
                self._set_task_progress(100.0, "100%", self.rt("status_converting_mp3"))
                self._set_progress(max(self.total_progress_value, 99.0), "99%")
                return

            elapsed = _ffmpeg_out_time_seconds(line)
            if elapsed is None or duration <= 0:
                return
            pct = max(0.0, min(100.0, elapsed * 100.0 / duration))
            self._set_task_progress(pct, f"{pct:.0f}%", self.rt("status_converting_mp3"))
            overall = max(self.total_progress_value, 92.0 + pct * 0.07)
            self._set_progress(overall, f"{overall:.0f}%")

        try:
            self.run_logged_command(
                command,
                source.parent,
                "ffmpeg MP3 conversion",
                handle_progress,
                log_output=False,
                allow_cancel=True,
            )
            if not temp_target.is_file():
                raise core.AppError(f"FFmpeg did not create the MP3 file: {temp_target}")
            os.replace(temp_target, target)
        except Exception:
            try:
                if temp_target.exists():
                    temp_target.unlink()
            except OSError:
                pass
            raise

        try:
            source.unlink()
        except OSError as exc:
            self._append_log(f"WARNING: could not remove source audio file {source}: {exc}\n")

        self.last_output_file = str(target)
        self._set_task_progress(100.0, "100%", self.rt("status_converting_mp3"))
        self._set_progress(max(self.total_progress_value, 99.0), "99%")
        return str(target)


def self_test() -> int:
    if previous.self_test() != 0:
        return 1

    errors: list[str] = []
    sample = [
        "yt-dlp.exe",
        "-f",
        "bestaudio/best",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "https://example.invalid/video",
    ]
    stripped = _strip_mp3_postprocessor_args(sample)
    if "--extract-audio" in stripped or "--audio-format" in stripped or "--audio-quality" in stripped:
        errors.append("MP3 yt-dlp postprocessor stripping failed.")
    if "bestaudio/best" not in stripped or stripped[-1] != "https://example.invalid/video":
        errors.append("MP3 downloader command was damaged while stripping postprocessor arguments.")

    parsed = _ffmpeg_out_time_seconds("out_time=00:01:02.500000")
    if parsed is None or abs(parsed - 62.5) > 0.001:
        errors.append("FFmpeg -progress out_time parser failed.")

    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("MP3 PROGRESS SELF-TEST OK\n")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())

    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
