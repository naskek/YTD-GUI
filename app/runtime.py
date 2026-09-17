from __future__ import annotations

import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import main as previous
import mini_url_converter as core


DOWNLOAD_DETAIL_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%\s+of\s+(?:~\s*)?(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)",
    re.IGNORECASE,
)
DOWNLOAD_FINISHED_RE = re.compile(
    r"\[download\]\s+100%\s+of\s+(?:~\s*)?(?P<size>\d+(?:\.\d+)?\s*[KMGT]?i?B)\s+in\s+(?P<elapsed>\S+)(?:\s+at\s+(?P<speed>.+))?",
    re.IGNORECASE,
)

RUNTIME_TEXT = {
    "en": {
        "cookie_compact": "YouTube cookies are missing or no longer accepted. Import a fresh cookies.txt in Settings.",
        "cookie_title": "YouTube cookies",
        "button_open_settings": "Open Settings",
        "button_close": "Close",
        "status_downloading_eta": "Downloading • {speed} • ETA {eta}",
        "status_downloading": "Downloading…",
        "status_converting_mp3": "Converting to MP3…",
        "status_finalizing": "Finalizing file…",
        "download_complete": "Download complete: {size} in {elapsed}{speed}",
        "preflight_auth_skipped": "Media preflight could not use the saved YouTube cookies; download will try the normal command.",
    },
    "ru": {
        "cookie_compact": "Cookies YouTube отсутствуют или больше не принимаются. Импортируйте свежий cookies.txt в настройках.",
        "cookie_title": "Cookies YouTube",
        "button_open_settings": "Открыть настройки",
        "button_close": "Закрыть",
        "status_downloading_eta": "Скачивание • {speed} • осталось {eta}",
        "status_downloading": "Скачивание…",
        "status_converting_mp3": "Конвертация в MP3…",
        "status_finalizing": "Финальная обработка файла…",
        "download_complete": "Скачивание завершено: {size} за {elapsed}{speed}",
        "preflight_auth_skipped": "Предварительный анализ не принял сохранённые cookies YouTube; загрузка будет запущена обычной командой.",
    },
}


def _size_to_bytes(value: float, unit: str) -> float:
    factors = {
        "b": 1.0,
        "kib": 1024.0,
        "mib": 1024.0**2,
        "gib": 1024.0**3,
        "tib": 1024.0**4,
        "kb": 1000.0,
        "mb": 1000.0**2,
        "gb": 1000.0**3,
        "tb": 1000.0**4,
    }
    return value * factors.get(unit.lower(), 1.0)


def _format_eta(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_speed(bytes_per_second: float) -> str:
    if bytes_per_second >= 1024.0**2:
        return f"{bytes_per_second / (1024.0**2):.1f} MiB/s"
    if bytes_per_second >= 1024.0:
        return f"{bytes_per_second / 1024.0:.0f} KiB/s"
    return f"{bytes_per_second:.0f} B/s"


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._eta_samples: deque[tuple[float, float]] = deque(maxlen=120)
        self._eta_total_bytes = 0.0
        self._eta_last_pct = 0.0
        self._eta_speed = 0.0
        self._download_summary_logged = False
        super().__init__(root)
        self.transfer_status_label = ttk.Label(
            self.progress_frame,
            textvariable=self.task_status_var,
            anchor="w",
            justify="left",
        )
        self.transfer_status_label.pack(fill="x", pady=(3, 0))

    def rt(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in RUNTIME_TEXT else "en"
        template = RUNTIME_TEXT[language].get(key) or RUNTIME_TEXT["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def _reset_eta_state(self) -> None:
        self._eta_samples.clear()
        self._eta_total_bytes = 0.0
        self._eta_last_pct = 0.0
        self._eta_speed = 0.0
        self._download_summary_logged = False

    def _reset_progress_state(self) -> None:
        self._reset_eta_state()
        super()._reset_progress_state()

    def build_error_dialog(self, summary: str) -> str:
        lower = summary.lower()
        if "cookie" in lower or "cookies" in lower or "youtube отклонил" in lower:
            return self.rt("cookie_compact")
        return super().build_error_dialog(summary)

    def _show_cookie_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(self.rt("cookie_title"))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=self.rt("cookie_compact"),
            wraplength=390,
            justify="left",
        ).pack(fill="x")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))

        def open_settings_when_ready() -> None:
            if dialog.winfo_exists():
                dialog.destroy()

            def try_open() -> None:
                if self.worker_thread and self.worker_thread.is_alive():
                    self.root.after(100, try_open)
                    return
                self.open_settings_dialog()

            self.root.after(50, try_open)

        ttk.Button(buttons, text=self.rt("button_close"), command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text=self.rt("button_open_settings"), command=open_settings_when_ready).pack(
            side="right", padx=(0, 8)
        )

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.focus_force()

    def _update_eta(self, line: str, pct: float) -> str:
        match = DOWNLOAD_DETAIL_RE.search(line)
        if match is None:
            return self.rt("status_downloading")

        total_bytes = _size_to_bytes(float(match.group("size")), match.group("unit"))
        now = time.monotonic()
        if (
            self._eta_total_bytes <= 0
            or abs(total_bytes - self._eta_total_bytes) > max(1024.0**2, self._eta_total_bytes * 0.05)
            or pct + 2.0 < self._eta_last_pct
        ):
            self._eta_samples.clear()
            self._eta_speed = 0.0

        self._eta_total_bytes = total_bytes
        self._eta_last_pct = pct
        downloaded_bytes = total_bytes * max(0.0, min(100.0, pct)) / 100.0
        self._eta_samples.append((now, downloaded_bytes))

        while len(self._eta_samples) > 2 and now - self._eta_samples[0][0] > 6.0:
            self._eta_samples.popleft()

        if len(self._eta_samples) >= 2:
            start_time, start_bytes = self._eta_samples[0]
            elapsed = now - start_time
            delta_bytes = downloaded_bytes - start_bytes
            if elapsed >= 0.35 and delta_bytes > 0:
                window_speed = delta_bytes / elapsed
                if self._eta_speed <= 0:
                    self._eta_speed = window_speed
                else:
                    self._eta_speed = (self._eta_speed * 0.72) + (window_speed * 0.28)

        if self._eta_speed <= 0:
            return self.rt("status_downloading")

        remaining = max(0.0, total_bytes - downloaded_bytes)
        eta = remaining / self._eta_speed if self._eta_speed > 0 else 0.0
        return self.rt(
            "status_downloading_eta",
            speed=_format_speed(self._eta_speed),
            eta=_format_eta(eta),
        )

    def _download_summary(self, line: str) -> str:
        match = DOWNLOAD_FINISHED_RE.search(line)
        if match is None:
            return line
        speed_text = match.group("speed")
        speed_suffix = f", {speed_text}" if speed_text else ""
        return self.rt(
            "download_complete",
            size=match.group("size").strip(),
            elapsed=match.group("elapsed"),
            speed=speed_suffix,
        )

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        output_file: str | None = None
        self._reset_eta_state()

        def handle_line(line: str) -> None:
            nonlocal output_file
            detected_output = self.parse_progress(line)
            if detected_output:
                output_file = detected_output

            if core.PROGRESS_RE.search(line):
                if not self._download_summary_logged and DOWNLOAD_FINISHED_RE.search(line):
                    self._download_summary_logged = True
                    self._append_log(self._download_summary(line) + "\n")
                return

            self._append_log(line + "\n")

        self.run_logged_command(
            command,
            core.PROJECT_ROOT,
            "yt-dlp",
            handle_line,
            log_output=False,
            allow_cancel=True,
        )
        return output_file

    def parse_progress(self, line: str) -> str | None:
        match = core.PROGRESS_RE.search(line)
        if match:
            pct = float(match.group("pct"))
            task_text = self._update_eta(line, pct)
            self._set_task_progress(pct, f"{pct:.1f}%", task_text)
            index = max(0, len(self.download_destinations) - 1)
            total = previous.base.compute_download_total(index, pct, self.expected_download_count)
            total = max(self.total_progress_value, total)
            self._set_progress(total, f"{total:.0f}%")
            self._set_status("status_downloading")
            return None

        lower = line.lower()
        if "[extractaudio]" in lower:
            self._set_progress(max(self.total_progress_value, 94.0), "94%")
            self._set_task_busy("...", self.rt("status_converting_mp3"))
            self._set_status(self.rt("status_converting_mp3"))
        elif "deleting original file" in lower or "[metadata]" in lower or "[embedthumbnail]" in lower:
            self._set_progress(max(self.total_progress_value, 98.0), "98%")
            self._set_task_busy("...", self.rt("status_finalizing"))
            self._set_status(self.rt("status_finalizing"))

        result = super().parse_progress(line)
        return result

    def run_job(self, url: str) -> None:
        try:
            self.ensure_environment()
            self._set_task_busy("...", self.ext("status_analyzing_streams"))
            try:
                info = self.fetch_url_analysis_info(url)
                self.expected_download_count = self._determine_expected_download_count(info)
            except Exception as exc:
                self.expected_download_count = 1
                detail = self._stringify_error(exc)
                if "cookie" in detail.lower() or "sign in to confirm" in detail.lower():
                    self._append_log(self.rt("preflight_auth_skipped") + "\n")
                else:
                    self._append_log(f"Progress preflight skipped: {detail}\n")

            self._append_log(self.ext("log_expected_streams", count=self.expected_download_count) + "\n")
            self._set_progress(0.0, "0%")
            self._set_task_progress(0.0, "0%", self.tr("status_running_ytdlp"))
            command = self.build_command(url)

            self._set_status("status_running_ytdlp")
            self._append_log(self.tr("log_binary_path", label="yt-dlp.exe", path=core.YT_DLP_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffmpeg.exe", path=core.FFMPEG_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffprobe.exe", path=core.FFPROBE_PATH) + "\n")
            output_file = self.run_ytdlp_command(command)

            self._clear_cookie_failed()
            self._set_status("status_completed")
            self._set_progress(100.0, "100%")
            final_path = output_file or self.last_output_file or str(self.download_dir)
            task_label = Path(final_path).name if final_path else self.tr("status_completed")
            self._set_task_progress(100.0, "100%", task_label)
            self._schedule(messagebox.showinfo, self.tr("app_title"), self.tr("info_completed_output", path=final_path))
        except core.JobCancelledError:
            self.cleanup_cancelled_downloads()
            self._append_log(self.tr("log_download_cancelled") + "\n")
            self._set_progress(0.0, "0%")
            self._set_task_progress(0.0, "0%", "")
            self._set_status("status_cancelled")
        except Exception as exc:
            summary = self._stringify_error(exc)
            self._append_log(self.tr("log_error", error=summary) + "\n")
            self._set_status("status_error")
            output_lines = getattr(exc, "output_lines", None)
            auth_message = self._detect_auth_error_message(output_lines) if output_lines else None
            if auth_message or "cookie" in summary.lower():
                self._schedule(lambda: self.root.after(80, self._show_cookie_dialog))
            else:
                self._schedule(messagebox.showerror, self.tr("app_title"), self.build_error_dialog(summary))
        finally:
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors: list[str] = []
    if _size_to_bytes(1.0, "MiB") != 1024.0**2:
        errors.append("MiB parser failed.")
    if _format_eta(65) != "01:05":
        errors.append("ETA formatter failed.")
    sample = "[download]  50.0% of  100.00MiB at 10.00MiB/s ETA 00:05"
    match = DOWNLOAD_DETAIL_RE.search(sample)
    if not match or match.group("pct") != "50.0" or match.group("unit") != "MiB":
        errors.append("Download detail parser failed.")
    final_sample = "[download] 100% of 100.00MiB in 00:00:10 at 10.00MiB/s"
    if DOWNLOAD_FINISHED_RE.search(final_sample) is None:
        errors.append("Download completion parser failed.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("RUNTIME SELF-TEST OK\n")
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
