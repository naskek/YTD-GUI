from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import launcher as base
import mini_url_converter as core
from version import APP_VERSION


POLISH_TRANSLATIONS = {
    "en": {
        "update_none": "No updates are required.",
        "update_ahead": "{name}: {current} (newer than published {latest})",
        "log_cookie_migrated": "cookies.txt: migrated into application data",
        "log_cookie_migration_skipped": "cookies.txt: migration skipped: {error}",
        "log_tool_downloading": "{label}: downloading {name}",
        "log_tool_downloaded": "{label}: downloaded to {path}",
        "log_tool_extracted": "{name}: extracted",
        "log_tool_updated": "{name}: updated",
        "error_download": "Failed to download {label}: {error}",
        "error_write": "Failed to write {path}: {error}",
        "error_extract": "Failed to extract {name}: {error}",
        "error_replace": "Failed to replace {name}: {error}",
    },
    "ru": {
        "update_none": "Обновление не требуется.",
        "update_ahead": "{name}: {current} (новее опубликованной {latest})",
        "log_cookie_migrated": "cookies.txt: перенесён в папку данных приложения",
        "log_cookie_migration_skipped": "cookies.txt: перенос пропущен: {error}",
        "log_tool_downloading": "{label}: скачивание {name}",
        "log_tool_downloaded": "{label}: скачано в {path}",
        "log_tool_extracted": "{name}: распакован",
        "log_tool_updated": "{name}: обновлён",
        "error_download": "Не удалось скачать {label}: {error}",
        "error_write": "Не удалось записать {path}: {error}",
        "error_extract": "Не удалось распаковать {name}: {error}",
        "error_replace": "Не удалось заменить {name}: {error}",
    },
}


def version_relation(current: str, latest: str) -> str:
    if not latest:
        return "unknown"
    if base.is_newer_version(latest, current):
        return "update"
    if base.is_newer_version(current, latest):
        return "ahead"
    return "current"


class App(base.EnhancedApp):
    def __init__(self, root: tk.Tk) -> None:
        self._update_total_items = 0
        self._update_completed_items = 0
        super().__init__(root)

    def ext(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in POLISH_TRANSLATIONS else "en"
        template = POLISH_TRANSLATIONS[language].get(key)
        if template is not None:
            return template.format(**{name: str(value) for name, value in kwargs.items()})
        if key == "update_none":
            return POLISH_TRANSLATIONS[language]["update_none"]
        return super().ext(key, **kwargs)

    def _migrate_external_cookie_file(self) -> None:
        if str(self.ytdlp_settings.get("auth_mode", "none")) != "file":
            return
        raw = str(self.ytdlp_settings.get("cookies_file", "")).strip()
        if not raw:
            return
        source = Path(raw).expanduser()
        try:
            if source.resolve(strict=False) == base.MANAGED_COOKIES_PATH.resolve(strict=False):
                return
        except OSError:
            pass
        if not source.is_file():
            return
        try:
            self.import_cookie_file(source, save=True)
            self._append_log(self.ext("log_cookie_migrated") + "\n")
        except Exception as exc:
            self._append_log(self.ext("log_cookie_migration_skipped", error=self._stringify_error(exc)) + "\n")

    def _set_update_component_fraction(self, fraction: float) -> None:
        if self.current_job_kind != "update" or self._update_total_items <= 0:
            return
        fraction = max(0.0, min(1.0, fraction))
        overall = (self._update_completed_items + fraction) * 90.0 / self._update_total_items
        overall = max(self.total_progress_value, min(90.0, overall))
        self._set_progress(overall, f"{overall:.0f}%")

    def download_file(self, url: str, destination: Path, label: str) -> None:
        if self._silent_download:
            return core.App.download_file(self, url, destination, label)

        request = urllib.request.Request(url, headers={"User-Agent": f"{core.APP_TITLE}/{APP_VERSION}"})
        try:
            with urllib.request.urlopen(request, timeout=core.NETWORK_TIMEOUT_SECONDS) as response:
                total = int(response.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                if total <= 0:
                    self._set_task_busy("...", label)
                    self._set_update_component_fraction(0.05)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output_file:
                    while True:
                        chunk = response.read(core.DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(100.0, downloaded * 100.0 / total)
                            self._set_task_progress(pct, f"{pct:.0f}%", label)
                            # Reserve the tail of each component slot for extraction/replacement.
                            self._set_update_component_fraction((pct / 100.0) * 0.85)
        except urllib.error.URLError as exc:
            raise core.AppError(self.ext("error_download", label=label, error=exc)) from exc
        except Exception as exc:
            if isinstance(exc, core.AppError):
                raise
            raise core.AppError(self.ext("error_write", path=destination, error=exc)) from exc

        self._set_task_progress(100.0, "100%", label)
        self._append_log(self.ext("log_tool_downloaded", label=label, path=destination) + "\n")

    def extract_binary_from_zip(self, archive_path: Path, binary_name: str, temp_dir: Path) -> Path:
        binary_name_lower = binary_name.lower()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                member_name = next(
                    (
                        name
                        for name in archive.namelist()
                        if name.lower().endswith(f"/bin/{binary_name_lower}")
                        or name.lower().endswith(f"/{binary_name_lower}")
                    ),
                    None,
                )
                if member_name is None:
                    raise core.AppError(f"{binary_name} was not found in {archive_path.name}.")
                target_path = temp_dir / binary_name
                with archive.open(member_name) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        except zipfile.BadZipFile as exc:
            raise core.AppError(self.ext("error_extract", name=binary_name, error=exc)) from exc
        except Exception as exc:
            if isinstance(exc, core.AppError):
                raise
            raise core.AppError(self.ext("error_extract", name=binary_name, error=exc)) from exc

        self._append_log(self.ext("log_tool_extracted", name=binary_name) + "\n")
        if binary_name.lower() == "ffmpeg.exe":
            self._set_update_component_fraction(0.90)
        elif binary_name.lower() == "ffprobe.exe":
            self._set_update_component_fraction(0.94)
        return target_path

    def replace_binary(self, source_path: Path, target_path: Path) -> None:
        temp_target = target_path.with_suffix(target_path.suffix + ".new")
        try:
            shutil.copyfile(source_path, temp_target)
            os.replace(temp_target, target_path)
        except Exception as exc:
            try:
                if temp_target.exists():
                    temp_target.unlink()
            except Exception:
                pass
            raise core.AppError(self.ext("error_replace", name=target_path.name, error=exc)) from exc

        self._append_log(self.ext("log_tool_updated", name=target_path.name) + "\n")
        if target_path.name.lower() == "ffmpeg.exe":
            self._set_update_component_fraction(0.97)
        else:
            self._set_update_component_fraction(1.0)

    def update_ffmpeg_binaries(self) -> None:
        asset_name = "ffmpeg-release-essentials.zip"
        self._append_log(self.ext("log_tool_downloading", label="ffmpeg", name=asset_name) + "\n")
        with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            archive_path = temp_dir / asset_name
            self.download_file(core.FFMPEG_WINDOWS_BUILD_URL, archive_path, "ffmpeg")
            ffmpeg_source = self.extract_binary_from_zip(archive_path, "ffmpeg.exe", temp_dir)
            ffprobe_source = self.extract_binary_from_zip(archive_path, "ffprobe.exe", temp_dir)
            self.replace_binary(ffmpeg_source, core.FFMPEG_PATH)
            self.replace_binary(ffprobe_source, core.FFPROBE_PATH)

    def _format_version_line(self, item: dict[str, object]) -> str:
        name = str(item["name"])
        current = str(item["current"])
        latest = str(item.get("latest") or "")
        relation = version_relation(current, latest)
        if relation == "update":
            return self.ext("update_line", name=name, current=current, latest=latest)
        if relation == "ahead":
            return self.ext("update_ahead", name=name, current=current, latest=latest)
        if relation == "current":
            return self.ext("update_same", name=name, current=current)
        return f"{name}: {current}"

    def run_check_versions_job(self) -> None:
        summary_lines: list[str] = []
        try:
            self.ensure_environment()
            self._set_task_busy("...", self.tr("status_checking_versions"))
            self._set_status("status_checking_versions")
            local = self.collect_local_versions()
            self.last_local_versions = dict(local)
            self._set_progress(25.0, "25%")

            latest_app = ""
            app_release: dict[str, str] | None = None
            try:
                app_release = self.fetch_latest_app_release()
                latest_app = app_release["version"]
                self.last_app_release = app_release
            except Exception as exc:
                summary_lines.append(self.ext("update_failed", name=core.APP_TITLE, error=self._stringify_error(exc)))
            self._set_progress(45.0, "45%")

            latest_ytdlp = ""
            try:
                latest_ytdlp = self.fetch_latest_ytdlp_version(timeout_seconds=core.NETWORK_TIMEOUT_SECONDS)
            except Exception as exc:
                summary_lines.append(self.ext("update_failed", name="yt-dlp", error=self._stringify_error(exc)))
            self._set_progress(65.0, "65%")

            latest_ffmpeg = ""
            try:
                latest_ffmpeg = self.fetch_latest_ffmpeg_version()
            except Exception as exc:
                summary_lines.append(self.ext("update_failed", name="FFmpeg/FFprobe", error=self._stringify_error(exc)))
            self._set_progress(85.0, "85%")

            plan: dict[str, dict[str, object]] = {
                "app": {
                    "name": core.APP_TITLE,
                    "current": APP_VERSION,
                    "latest": latest_app,
                    "update": version_relation(APP_VERSION, latest_app) == "update",
                    "installer_url": app_release.get("installer_url", "") if app_release else "",
                },
                "yt-dlp": {
                    "name": "yt-dlp",
                    "current": local["yt-dlp"],
                    "latest": latest_ytdlp,
                    "update": version_relation(local["yt-dlp"], latest_ytdlp) == "update",
                },
                "ffmpeg": {
                    "name": "FFmpeg/FFprobe",
                    "current": local["ffmpeg"],
                    "latest": latest_ffmpeg,
                    "update": version_relation(local["ffmpeg"], latest_ffmpeg) == "update",
                },
            }
            self.last_update_plan = plan
            self.last_latest_ytdlp_version = latest_ytdlp or None
            self.last_ytdlp_up_to_date = not bool(plan["yt-dlp"]["update"]) if latest_ytdlp else None

            for item in plan.values():
                line = self._format_version_line(item)
                summary_lines.append(line)
                self._append_log(line + "\n")

            self._set_progress(100.0, "100%")
            self._set_task_progress(100.0, "100%", self.ext("update_check_title"))
            updates = any(bool(item["update"]) for item in plan.values())
            self._set_status("status_completed" if updates else "status_already_up_to_date")
            summary = "\n".join(summary_lines)
            if updates:
                self._schedule(self._prompt_update_plan, summary)
            else:
                self._schedule(
                    messagebox.showinfo,
                    self.ext("update_check_title"),
                    summary + "\n\n" + self.ext("update_none"),
                )
        except Exception as exc:
            summary = self._stringify_error(exc)
            self._append_log(self.tr("log_error", error=summary) + "\n")
            self._set_status("status_error")
            self._schedule(messagebox.showerror, self.ext("update_check_title"), summary)
        finally:
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)

    def run_update_job(self) -> None:
        app_installer: Path | None = None
        try:
            self.ensure_environment()
            pending = [key for key, item in self.last_update_plan.items() if bool(item.get("update"))]
            total_items = max(1, len(pending))
            completed = 0
            self._update_total_items = total_items
            self._update_completed_items = 0

            if "yt-dlp" in pending:
                self._set_status("status_updating_ytdlp")
                self._update_completed_items = completed
                with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
                    yt_tmp = Path(temp_dir_text) / "yt-dlp.exe"
                    self._append_log(self.ext("log_tool_downloading", label="yt-dlp", name="yt-dlp.exe") + "\n")
                    self.download_file(core.YTDLP_WINDOWS_DOWNLOAD_URL, yt_tmp, "yt-dlp")
                    self.replace_binary(yt_tmp, core.YT_DLP_PATH)
                completed += 1
                self._update_completed_items = completed
                self._set_update_component_fraction(0.0)

            if "ffmpeg" in pending:
                self._set_status("status_updating")
                self._update_completed_items = completed
                self.update_ffmpeg_binaries()
                completed += 1
                self._update_completed_items = completed
                self._set_update_component_fraction(0.0)

            if "app" in pending:
                self._update_completed_items = completed
                if not getattr(sys, "frozen", False):
                    self._append_log(self.ext("update_app_requires_installed") + "\n")
                else:
                    item = self.last_update_plan["app"]
                    installer_url = str(item.get("installer_url", ""))
                    latest = str(item.get("latest", ""))
                    if not installer_url:
                        raise core.AppError("The latest GitHub Release does not contain a MiniURLConverterSetup asset.")
                    base.UPDATES_DIR.mkdir(parents=True, exist_ok=True)
                    app_installer = base.UPDATES_DIR / f"MiniURLConverterSetup-{latest}.exe"
                    self._set_status("status_updating")
                    self._append_log(self.ext("log_tool_downloading", label=core.APP_TITLE, name=app_installer.name) + "\n")
                    self.download_file(installer_url, app_installer, core.APP_TITLE)
                completed += 1
                self._update_completed_items = completed
                self._set_update_component_fraction(0.0)

            # Put the overall bar at the end of the component phase before version validation.
            self._set_progress(90.0, "90%")
            versions = self.collect_local_versions()
            self.last_local_versions = dict(versions)
            self._append_log(f"yt-dlp: {versions['yt-dlp']}\n")
            self._append_log(f"ffmpeg: {versions['ffmpeg']}\n")
            self._append_log(f"ffprobe: {versions['ffprobe']}\n")
            self._append_log(self.tr("log_update_complete") + "\n")
            self._set_progress(100.0, "100%")
            self._set_task_progress(100.0, "100%", self.tr("status_update_complete"))
            self._set_status("status_update_complete")

            if app_installer is not None:
                self._append_log(self.ext("update_app_launching") + "\n")
                self._schedule(self._launch_update_after_exit, app_installer)
        except Exception as exc:
            summary = self._stringify_error(exc)
            self._append_log(self.tr("log_error", error=summary) + "\n")
            self._set_status("status_update_failed")
            self._schedule(messagebox.showerror, self.ext("update_check_title"), summary)
        finally:
            self._update_total_items = 0
            self._update_completed_items = 0
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)


def self_test() -> int:
    if base.enhanced_self_test() != 0:
        return 1
    errors: list[str] = []
    if version_relation("1.2.0", "1.1.0") != "ahead":
        errors.append("Published-version relation failed for local-ahead case.")
    if version_relation("1.1.0", "1.2.0") != "update":
        errors.append("Published-version relation failed for update case.")
    if version_relation("1.2.0", "1.2.0") != "current":
        errors.append("Published-version relation failed for current case.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("POLISH SELF-TEST OK\n")
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
