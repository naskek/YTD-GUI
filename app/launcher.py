from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import mini_url_converter as core
from version import APP_VERSION


APP_RELEASE_API = "https://api.github.com/repos/naskek/YTD-GUI/releases/latest"
APP_RELEASE_PAGE = "https://github.com/naskek/YTD-GUI/releases/latest"
FFMPEG_RELEASE_VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/release-version"
COOKIES_DIR = core.APP_DATA_DIR / "cookies"
MANAGED_COOKIES_PATH = COOKIES_DIR / "youtube-cookies.txt"
UPDATES_DIR = core.APP_DATA_DIR / "updates"
COOKIE_EXPIRY_WARNING_SECONDS = 7 * 24 * 60 * 60

AUTH_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LOGIN_INFO",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
}

EXTRA_TRANSLATIONS = {
    "en": {
        "settings_title": "Settings",
        "cookie_import": "Import / replace cookies.txt",
        "cookie_status_missing": "Cookies: not imported.",
        "cookie_status_invalid": "Cookies: the last YouTube authentication attempt failed. Import a fresh cookies.txt.",
        "cookie_status_expired": "Cookies: expired. Import a fresh cookies.txt.",
        "cookie_status_session": "Cookies: imported. Expiration is not present in the file; validity will be confirmed by YouTube when used.",
        "cookie_status_valid": "Cookies: valid until approximately {date} ({remaining}). YouTube can revoke cookies earlier.",
        "cookie_status_expiring": "Cookies: expire approximately {date} ({remaining}). Consider importing fresh cookies soon.",
        "cookie_days": "{days} d",
        "cookie_hours": "{hours} h",
        "cookie_imported": "Cookies were copied into the application data folder.",
        "cookie_warning_title": "YouTube cookies",
        "cookie_warning": "The saved YouTube cookies are no longer usable. Open Settings and import a fresh cookies.txt.",
        "cookie_rejected": "YouTube rejected the saved cookies. Import a fresh cookies.txt in Settings.",
        "update_check_title": "Updates",
        "update_none": "Everything is up to date.",
        "update_available": "Updates are available:\n\n{summary}\n\nUpdate now?",
        "update_unknown": "unknown",
        "update_line": "{name}: {current} -> {latest}",
        "update_same": "{name}: {current} (current)",
        "update_failed": "{name}: could not check latest version ({error})",
        "update_app_requires_installed": "Application self-update is available only for the installed EXE build.",
        "update_app_downloading": "Downloading application update...",
        "update_app_launching": "The update installer will start after the application closes.",
        "status_analyzing_streams": "Analyzing media streams...",
        "log_expected_streams": "Expected media streams: {count}",
        "label_cookie_status": "Cookie status",
        "label_cookie_storage": "Stored copy",
    },
    "ru": {
        "settings_title": "Настройки",
        "cookie_import": "Импортировать / заменить cookies.txt",
        "cookie_status_missing": "Cookies: файл не импортирован.",
        "cookie_status_invalid": "Cookies: последняя авторизация YouTube завершилась ошибкой. Импортируйте свежий cookies.txt.",
        "cookie_status_expired": "Cookies: срок действия истёк. Импортируйте свежий cookies.txt.",
        "cookie_status_session": "Cookies: импортированы. Срок действия в файле не указан; действительность будет подтверждена YouTube при использовании.",
        "cookie_status_valid": "Cookies: ориентировочно действуют до {date} ({remaining}). YouTube может отозвать их раньше.",
        "cookie_status_expiring": "Cookies: ориентировочно истекают {date} ({remaining}). Лучше импортировать свежий файл.",
        "cookie_days": "{days} дн.",
        "cookie_hours": "{hours} ч.",
        "cookie_imported": "Cookies скопированы в папку данных приложения.",
        "cookie_warning_title": "Cookies YouTube",
        "cookie_warning": "Сохранённые cookies YouTube больше нельзя использовать. Откройте настройки и импортируйте свежий cookies.txt.",
        "cookie_rejected": "YouTube отклонил сохранённые cookies. Импортируйте свежий cookies.txt в настройках.",
        "update_check_title": "Обновления",
        "update_none": "Все компоненты актуальны.",
        "update_available": "Доступны обновления:\n\n{summary}\n\nОбновить сейчас?",
        "update_unknown": "неизвестно",
        "update_line": "{name}: {current} -> {latest}",
        "update_same": "{name}: {current} (актуально)",
        "update_failed": "{name}: не удалось проверить свежую версию ({error})",
        "update_app_requires_installed": "Самообновление приложения доступно только для установленной EXE-версии.",
        "update_app_downloading": "Скачивание обновления приложения...",
        "update_app_launching": "Установщик обновления запустится после закрытия приложения.",
        "status_analyzing_streams": "Анализ медиапотоков...",
        "log_expected_streams": "Ожидаемых медиапотоков: {count}",
        "label_cookie_status": "Статус cookies",
        "label_cookie_storage": "Сохранённая копия",
    },
}


def normalize_version(value: str) -> str:
    return value.strip().lstrip("vV")


def version_key(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", normalize_version(value))
    return tuple(int(part) for part in parts[:6]) if parts else (0,)


def is_newer_version(latest: str, current: str) -> bool:
    return version_key(latest) > version_key(current)


def compute_download_total(download_index: int, percent: float, expected_count: int) -> float:
    count = max(1, expected_count, download_index + 1)
    progress = (max(0, download_index) + max(0.0, min(100.0, percent)) / 100.0) / count
    return max(0.0, min(90.0, progress * 90.0))


def parse_netscape_cookie_status(path: Path, *, failed_at: float = 0.0) -> dict[str, object]:
    result: dict[str, object] = {
        "state": "missing",
        "expires_at": None,
        "persistent_count": 0,
        "session_count": 0,
        "auth_cookie_count": 0,
        "failed_at": float(failed_at or 0.0),
    }
    if not path.is_file():
        return result

    now = int(time.time())
    auth_expiries: list[int] = []
    fallback_expiries: list[int] = []
    auth_session_count = 0
    fallback_session_count = 0

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        result["state"] = "missing"
        return result

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue

        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain = fields[0].lower().lstrip(".")
        if not (domain.endswith("youtube.com") or domain.endswith("google.com")):
            continue
        try:
            expiry = int(float(fields[4]))
        except ValueError:
            expiry = 0
        name = fields[5]
        is_auth = name in AUTH_COOKIE_NAMES

        if is_auth:
            result["auth_cookie_count"] = int(result["auth_cookie_count"]) + 1
        if expiry <= 0:
            result["session_count"] = int(result["session_count"]) + 1
            if is_auth:
                auth_session_count += 1
            else:
                fallback_session_count += 1
            continue

        result["persistent_count"] = int(result["persistent_count"]) + 1
        if is_auth:
            auth_expiries.append(expiry)
        else:
            fallback_expiries.append(expiry)

    if float(failed_at or 0.0) > 0:
        result["state"] = "invalid"
        return result

    relevant = auth_expiries if auth_expiries else fallback_expiries
    future = sorted(expiry for expiry in relevant if expiry > now)
    if future:
        result["state"] = "valid"
        result["expires_at"] = future[0]
        return result

    if relevant:
        result["state"] = "expired"
        result["expires_at"] = max(relevant)
        return result

    if auth_session_count or fallback_session_count:
        result["state"] = "session"
        return result

    result["state"] = "invalid"
    return result


class EnhancedApp(core.App):
    def __init__(self, root: tk.Tk) -> None:
        self.expected_download_count = 1
        self.last_update_plan: dict[str, dict[str, object]] = {}
        self.last_app_release: dict[str, str] | None = None
        self._silent_download = False
        super().__init__(root)
        self._migrate_external_cookie_file()
        self._append_log(f"{core.APP_TITLE} {APP_VERSION}\n")
        self.root.after(700, self._notify_cookie_problem)

    def ext(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in EXTRA_TRANSLATIONS else "en"
        template = EXTRA_TRANSLATIONS[language].get(key) or EXTRA_TRANSLATIONS["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def refresh_ui_language(self) -> None:
        super().refresh_ui_language()
        self.root.title(f"{self.tr('app_title')} — v{APP_VERSION}")

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = super().load_ytdlp_settings(data)
        raw_settings = data.get("ytdlp")
        if isinstance(raw_settings, dict):
            failed_at = raw_settings.get("cookie_last_failed_at")
            if isinstance(failed_at, (int, float)) and failed_at >= 0:
                settings["cookie_last_failed_at"] = float(failed_at)
        settings.setdefault("cookie_last_failed_at", 0.0)
        return settings

    def _migrate_external_cookie_file(self) -> None:
        if str(self.ytdlp_settings.get("auth_mode", "none")) != "file":
            return
        raw = str(self.ytdlp_settings.get("cookies_file", "")).strip()
        if not raw:
            return
        source = Path(raw).expanduser()
        try:
            if source.resolve(strict=False) == MANAGED_COOKIES_PATH.resolve(strict=False):
                return
        except OSError:
            pass
        if not source.is_file():
            return
        try:
            self.import_cookie_file(source, save=True)
            self._append_log("cookies.txt: migrated into application data\n")
        except Exception as exc:
            self._append_log(f"cookies.txt: migration skipped: {exc}\n")

    def import_cookie_file(self, source: Path, *, save: bool = True) -> Path:
        source = source.expanduser().resolve(strict=True)
        if not source.is_file():
            raise core.AppError(f"cookies.txt was not found: {source}")
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        temp_target = MANAGED_COOKIES_PATH.with_suffix(".txt.new")
        shutil.copyfile(source, temp_target)
        os.replace(temp_target, MANAGED_COOKIES_PATH)
        self.ytdlp_settings["cookies_file"] = str(MANAGED_COOKIES_PATH)
        self.ytdlp_settings["cookie_last_failed_at"] = 0.0
        if save:
            self.save_settings()
        return MANAGED_COOKIES_PATH

    def _cookie_status(self, path: Path | None = None) -> dict[str, object]:
        candidate = path or MANAGED_COOKIES_PATH
        failed_at = float(self.ytdlp_settings.get("cookie_last_failed_at", 0.0) or 0.0)
        return parse_netscape_cookie_status(candidate, failed_at=failed_at)

    def _cookie_status_text(self, path: Path | None = None) -> str:
        status = self._cookie_status(path)
        state = str(status["state"])
        if state == "missing":
            return self.ext("cookie_status_missing")
        if state == "invalid":
            return self.ext("cookie_status_invalid")
        if state == "expired":
            return self.ext("cookie_status_expired")
        if state == "session":
            return self.ext("cookie_status_session")

        expires_at = int(status.get("expires_at") or 0)
        remaining_seconds = max(0, expires_at - int(time.time()))
        if remaining_seconds >= 24 * 60 * 60:
            remaining = self.ext("cookie_days", days=max(1, remaining_seconds // (24 * 60 * 60)))
        else:
            remaining = self.ext("cookie_hours", hours=max(1, remaining_seconds // (60 * 60)))
        date_text = time.strftime("%d.%m.%Y %H:%M", time.localtime(expires_at))
        key = "cookie_status_expiring" if remaining_seconds <= COOKIE_EXPIRY_WARNING_SECONDS else "cookie_status_valid"
        return self.ext(key, date=date_text, remaining=remaining)

    def _notify_cookie_problem(self) -> None:
        if self.closing or str(self.ytdlp_settings.get("auth_mode", "none")) != "file":
            return
        state = str(self._cookie_status()["state"])
        if state in {"missing", "invalid", "expired"}:
            messagebox.showwarning(self.ext("cookie_warning_title"), self.ext("cookie_warning"), parent=self.root)

    def _mark_cookie_failed(self) -> None:
        if str(self.ytdlp_settings.get("auth_mode", "none")) != "file":
            return
        self.ytdlp_settings["cookie_last_failed_at"] = time.time()
        try:
            self.save_settings()
        except Exception:
            pass

    def _clear_cookie_failed(self) -> None:
        if str(self.ytdlp_settings.get("auth_mode", "none")) != "file":
            return
        if float(self.ytdlp_settings.get("cookie_last_failed_at", 0.0) or 0.0) <= 0:
            return
        self.ytdlp_settings["cookie_last_failed_at"] = 0.0
        try:
            self.save_settings()
        except Exception:
            pass

    def _resolve_cookies_file_path(self) -> Path:
        raw = str(self.ytdlp_settings.get("cookies_file", "")).strip()
        candidate = Path(raw).expanduser() if raw else MANAGED_COOKIES_PATH
        if candidate.is_file() and candidate.resolve(strict=False) != MANAGED_COOKIES_PATH.resolve(strict=False):
            candidate = self.import_cookie_file(candidate, save=True)
        if not candidate.is_file() and MANAGED_COOKIES_PATH.is_file():
            candidate = MANAGED_COOKIES_PATH
            self.ytdlp_settings["cookies_file"] = str(candidate)
        if not candidate.is_file():
            raise core.AppError(self.ext("cookie_status_missing"))
        state = str(self._cookie_status(candidate)["state"])
        if state in {"expired", "invalid"}:
            raise core.AppError(self.ext("cookie_warning"))
        return candidate

    def _detect_auth_error_message(self, output_lines: list[str]) -> str | None:
        message = super()._detect_auth_error_message(output_lines)
        if message and str(self.ytdlp_settings.get("auth_mode", "none")) == "file":
            self._mark_cookie_failed()
            return self.ext("cookie_rejected")
        return message

    def open_settings_dialog(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.settings_window = dialog
        dialog.title(f"{self.ext('settings_title')} — v{APP_VERSION}")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", lambda win=dialog: self.close_settings_dialog(win))

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        format_var = tk.StringVar(value=str(self.ytdlp_settings["format_preset"]))
        output_mode_var = tk.StringVar(value=str(self.ytdlp_settings["output_mode"]))
        output_template_var = tk.StringVar(value=str(self.ytdlp_settings["output_template"]))
        retries_var = tk.StringVar(value=str(self.ytdlp_settings["retries"]))
        retry_sleep_var = tk.StringVar(value=str(self.ytdlp_settings["retry_sleep"]))
        restrict_var = tk.BooleanVar(value=bool(self.ytdlp_settings["restrict_filenames"]))
        windows_var = tk.BooleanVar(value=bool(self.ytdlp_settings["windows_filenames"]))
        auth_var = tk.StringVar(value=str(self.ytdlp_settings["auth_mode"]))
        browser_var = tk.StringVar(value=str(self.ytdlp_settings["cookies_browser"]))
        cookie_path_var = tk.StringVar(value=str(self.ytdlp_settings.get("cookies_file", "")))
        cookie_status_var = tk.StringVar(value=self._cookie_status_text())

        def add_row(row: int, label: str, widget: tk.Widget) -> None:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            widget.grid(row=row, column=1, sticky="ew", pady=4)

        format_combo = ttk.Combobox(body, state="readonly", values=[self.format_preset_label(k) for k in core.FORMAT_PRESET_CHOICES], width=28)
        format_combo.set(self.format_preset_label(format_var.get()))
        output_combo = ttk.Combobox(body, state="readonly", values=[self.output_mode_label(k) for k in core.OUTPUT_MODE_CHOICES], width=28)
        output_combo.set(self.output_mode_label(output_mode_var.get()))

        add_row(0, self.tr("label_format_preset"), format_combo)
        add_row(1, self.tr("label_output_mode"), output_combo)
        add_row(2, self.tr("label_output_template"), ttk.Entry(body, textvariable=output_template_var, width=46))
        add_row(3, self.tr("label_retries"), ttk.Spinbox(body, from_=0, to=100, textvariable=retries_var, width=10))
        add_row(4, self.tr("label_retry_sleep"), ttk.Entry(body, textvariable=retry_sleep_var, width=10))

        ttk.Checkbutton(body, text=self.tr("label_restrict_filenames"), variable=restrict_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 2))
        ttk.Checkbutton(body, text=self.tr("label_windows_filenames"), variable=windows_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Separator(body, orient="horizontal").grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 6))
        ttk.Label(body, text=self.tr("label_youtube_auth"), font=("Segoe UI", 9, "bold")).grid(row=8, column=0, columnspan=2, sticky="w")

        auth_combo = ttk.Combobox(body, state="readonly", values=[self.auth_mode_label(k) for k in core.AUTH_MODE_CHOICES], width=28)
        auth_combo.set(self.auth_mode_label(auth_var.get()))
        add_row(9, self.tr("label_auth_mode"), auth_combo)

        browser_combo = ttk.Combobox(body, state="readonly", values=[self.cookies_browser_label(k) for k in core.COOKIE_BROWSER_CHOICES], width=28)
        browser_combo.set(self.cookies_browser_label(browser_var.get()))
        add_row(10, self.tr("label_cookies_browser"), browser_combo)

        cookie_frame = ttk.Frame(body)
        cookie_frame.columnconfigure(0, weight=1)
        cookie_entry = ttk.Entry(cookie_frame, textvariable=cookie_path_var, state="readonly")
        cookie_entry.grid(row=0, column=0, sticky="ew")
        import_button = ttk.Button(cookie_frame, text=self.ext("cookie_import"))
        import_button.grid(row=0, column=1, padx=(8, 0))
        add_row(11, self.ext("label_cookie_storage"), cookie_frame)

        ttk.Label(body, text=self.ext("label_cookie_status")).grid(row=12, column=0, sticky="nw", padx=(0, 12), pady=4)
        cookie_status_label = ttk.Label(body, textvariable=cookie_status_var, wraplength=430, justify="left")
        cookie_status_label.grid(row=12, column=1, sticky="w", pady=4)

        def current_auth_mode() -> str:
            return next((k for k in core.AUTH_MODE_CHOICES if self.auth_mode_label(k) == auth_combo.get()), "none")

        def update_auth_state(event: tk.Event[tk.Misc] | None = None) -> None:
            del event
            mode = current_auth_mode()
            browser_combo.configure(state="readonly" if mode == "browser" else "disabled")
            import_button.configure(state="normal" if mode == "file" else "disabled")

        def import_cookies() -> None:
            selected = filedialog.askopenfilename(
                parent=dialog,
                title=self.tr("dialog_select_cookies_file"),
                filetypes=[(self.tr("dialog_cookies_filter"), "*.txt"), (self.tr("dialog_all_files_filter"), "*.*")],
            )
            if not selected:
                return
            try:
                managed = self.import_cookie_file(Path(selected), save=False)
            except Exception as exc:
                messagebox.showerror(self.tr("app_title"), str(exc), parent=dialog)
                return
            cookie_path_var.set(str(managed))
            cookie_status_var.set(self._cookie_status_text(managed))
            messagebox.showinfo(self.tr("app_title"), self.ext("cookie_imported"), parent=dialog)

        auth_combo.bind("<<ComboboxSelected>>", update_auth_state)
        import_button.configure(command=import_cookies)
        update_auth_state()

        buttons = ttk.Frame(body)
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(14, 0))

        def apply_defaults() -> None:
            format_var.set(str(core.YTDLP_DEFAULTS["format_preset"]))
            output_mode_var.set(str(core.YTDLP_DEFAULTS["output_mode"]))
            output_template_var.set(str(core.YTDLP_DEFAULTS["output_template"]))
            retries_var.set(str(core.YTDLP_DEFAULTS["retries"]))
            retry_sleep_var.set(str(core.YTDLP_DEFAULTS["retry_sleep"]))
            restrict_var.set(bool(core.YTDLP_DEFAULTS["restrict_filenames"]))
            windows_var.set(bool(core.YTDLP_DEFAULTS["windows_filenames"]))
            auth_var.set("none")
            browser_var.set(str(core.YTDLP_DEFAULTS["cookies_browser"]))
            format_combo.set(self.format_preset_label(format_var.get()))
            output_combo.set(self.output_mode_label(output_mode_var.get()))
            auth_combo.set(self.auth_mode_label("none"))
            browser_combo.set(self.cookies_browser_label(browser_var.get()))
            update_auth_state()

        def save_dialog_settings() -> None:
            selected_format = next((k for k in core.FORMAT_PRESET_CHOICES if self.format_preset_label(k) == format_combo.get()), "best")
            selected_output = next((k for k in core.OUTPUT_MODE_CHOICES if self.output_mode_label(k) == output_combo.get()), "mp4")
            selected_auth = current_auth_mode()
            selected_browser = next((k for k in core.COOKIE_BROWSER_CHOICES if self.cookies_browser_label(k) == browser_combo.get()), "firefox")
            output_template = output_template_var.get().strip()
            if not output_template:
                messagebox.showerror(self.tr("app_title"), self.tr("error_output_template_empty"), parent=dialog)
                return
            try:
                retries = int(retries_var.get())
                if retries < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(self.tr("app_title"), self.tr("error_invalid_integer", name=self.tr("label_retries")), parent=dialog)
                return
            retry_sleep = self.normalize_retry_sleep(retry_sleep_var.get())
            if retry_sleep is None:
                messagebox.showerror(self.tr("app_title"), self.tr("error_invalid_number", name=self.tr("label_retry_sleep")), parent=dialog)
                return
            if selected_auth == "file" and not MANAGED_COOKIES_PATH.is_file():
                messagebox.showerror(self.tr("app_title"), self.ext("cookie_status_missing"), parent=dialog)
                return

            self.ytdlp_settings = {
                "format_preset": selected_format,
                "output_mode": selected_output,
                "output_template": output_template,
                "retries": retries,
                "retry_sleep": retry_sleep,
                "restrict_filenames": bool(restrict_var.get()),
                "windows_filenames": bool(windows_var.get()),
                "auth_mode": selected_auth,
                "cookies_browser": selected_browser,
                "cookies_file": str(MANAGED_COOKIES_PATH) if MANAGED_COOKIES_PATH.is_file() else "",
                "cookie_last_failed_at": float(self.ytdlp_settings.get("cookie_last_failed_at", 0.0) or 0.0),
            }
            try:
                self.save_settings()
            except Exception as exc:
                messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc), parent=dialog)
                return
            self._append_log(self.tr("log_settings_updated") + "\n")
            self._set_status("status_settings_updated")
            self.close_settings_dialog(dialog)

        ttk.Button(buttons, text=self.tr("button_reset_defaults"), command=apply_defaults).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.tr("button_cancel"), command=lambda: self.close_settings_dialog(dialog)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.tr("button_save"), command=save_dialog_settings).pack(side="left")

        dialog.update_idletasks()
        dialog.grab_set()
        dialog.focus_force()

    def _determine_expected_download_count(self, info: dict[str, object]) -> int:
        requested_formats = info.get("requested_formats")
        if isinstance(requested_formats, list):
            media_formats = [item for item in requested_formats if isinstance(item, dict)]
            if media_formats:
                return max(1, len(media_formats))
        requested_downloads = info.get("requested_downloads")
        if isinstance(requested_downloads, list) and requested_downloads:
            return max(1, len([item for item in requested_downloads if isinstance(item, dict)]))
        return 1

    def run_job(self, url: str) -> None:
        try:
            self.ensure_environment()
            self._set_task_busy("...", self.ext("status_analyzing_streams"))
            try:
                info = self.fetch_url_analysis_info(url)
                self.expected_download_count = self._determine_expected_download_count(info)
            except Exception as exc:
                self.expected_download_count = 1
                self._append_log(f"Progress preflight skipped: {self._stringify_error(exc)}\n")
            self._append_log(self.ext("log_expected_streams", count=self.expected_download_count) + "\n")
            self._set_progress(0.0, "0%")
            self._set_task_progress(0.0, "0%", self.tr("status_running_ytdlp"))
            command = self.build_command(url)

            self._set_status("status_running_ytdlp")
            self._append_log(self.tr("log_binary_path", label="yt-dlp.exe", path=core.YT_DLP_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffmpeg.exe", path=core.FFMPEG_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffprobe.exe", path=core.FFPROBE_PATH) + "\n")
            self._append_log(f"Command: {subprocess.list2cmdline(command)}\n")
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
            self._schedule(messagebox.showerror, self.tr("app_title"), self.build_error_dialog(auth_message or summary))
        finally:
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)

    def parse_progress(self, line: str) -> str | None:
        match = core.PROGRESS_RE.search(line)
        if match:
            pct = float(match.group("pct"))
            task_label = Path(self.current_download_destination).name if self.current_download_destination else self.tr("status_downloading")
            self._set_task_progress(pct, f"{pct:.1f}%", task_label)
            index = max(0, len(self.download_destinations) - 1)
            total = compute_download_total(index, pct, self.expected_download_count)
            total = max(self.total_progress_value, total)
            self._set_progress(total, f"{total:.0f}%")
            self._set_status("status_downloading")
            return None

        result = super().parse_progress(line)
        if core.DEST_RE.search(line):
            index = max(0, len(self.download_destinations) - 1)
            total = compute_download_total(index, 0.0, self.expected_download_count)
            total = max(self.total_progress_value, total)
            self._set_progress(total, f"{total:.0f}%")
        return result

    def fetch_latest_app_release(self) -> dict[str, str]:
        payload = self.fetch_json(APP_RELEASE_API, timeout_seconds=core.NETWORK_TIMEOUT_SECONDS)
        tag = payload.get("tag_name")
        if not isinstance(tag, str) or not tag.strip():
            raise core.AppError("GitHub API did not return an application release tag.")
        version = normalize_version(tag)
        installer_url = ""
        assets = payload.get("assets")
        if isinstance(assets, list):
            preferred = f"MiniURLConverterSetup-{version}.exe".lower()
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name", ""))
                url = str(asset.get("browser_download_url", ""))
                if name.lower() == preferred and url:
                    installer_url = url
                    break
            if not installer_url:
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    name = str(asset.get("name", ""))
                    url = str(asset.get("browser_download_url", ""))
                    if name.lower().startswith("miniurlconvertersetup") and name.lower().endswith(".exe") and url:
                        installer_url = url
                        break
        html_url = str(payload.get("html_url", APP_RELEASE_PAGE))
        return {"version": version, "installer_url": installer_url, "html_url": html_url}

    def fetch_latest_ffmpeg_version(self) -> str:
        request = urllib.request.Request(
            FFMPEG_RELEASE_VERSION_URL,
            headers={"User-Agent": f"{core.APP_TITLE}/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=core.NETWORK_TIMEOUT_SECONDS) as response:
                value = response.read(256).decode("utf-8", errors="replace").strip()
        except urllib.error.URLError as exc:
            raise core.AppError(f"Failed to check FFmpeg release: {exc}") from exc
        if not value:
            raise core.AppError("FFmpeg release version endpoint returned an empty response.")
        return normalize_version(value.splitlines()[0])

    def on_check_versions(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return
        self.url_analysis_request_id += 1
        self.recent_log_lines.clear()
        self.current_job_kind = "check_versions"
        self.cancel_requested = False
        self.last_output_file = None
        self._reset_progress_state()
        self._set_status("status_preparing_versions")
        self._set_running_state_ui(True)
        self._append_log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        self.worker_thread = threading.Thread(target=self.run_check_versions_job, daemon=True)
        self.worker_thread.start()

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
                    "update": bool(latest_app and is_newer_version(latest_app, APP_VERSION)),
                    "installer_url": app_release.get("installer_url", "") if app_release else "",
                },
                "yt-dlp": {
                    "name": "yt-dlp",
                    "current": local["yt-dlp"],
                    "latest": latest_ytdlp,
                    "update": bool(latest_ytdlp and is_newer_version(latest_ytdlp, local["yt-dlp"])),
                },
                "ffmpeg": {
                    "name": "FFmpeg/FFprobe",
                    "current": local["ffmpeg"],
                    "latest": latest_ffmpeg,
                    "update": bool(latest_ffmpeg and is_newer_version(latest_ffmpeg, local["ffmpeg"])),
                },
            }
            self.last_update_plan = plan
            self.last_latest_ytdlp_version = latest_ytdlp or None
            self.last_ytdlp_up_to_date = not bool(plan["yt-dlp"]["update"]) if latest_ytdlp else None

            for item in plan.values():
                current = str(item["current"])
                latest = str(item["latest"] or self.ext("update_unknown"))
                if bool(item["update"]):
                    line = self.ext("update_line", name=item["name"], current=current, latest=latest)
                else:
                    line = self.ext("update_same", name=item["name"], current=current) if item["latest"] else f"{item['name']}: {current}"
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
                self._schedule(messagebox.showinfo, self.ext("update_check_title"), summary + "\n\n" + self.ext("update_none"))
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

    def _prompt_update_plan(self, summary: str) -> None:
        if messagebox.askyesno(self.ext("update_check_title"), self.ext("update_available", summary=summary), parent=self.root):
            self.begin_update_job(clear_log=False)

    def begin_update_job(self, clear_log: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return
        if not self.last_update_plan or not any(bool(item.get("update")) for item in self.last_update_plan.values()):
            self._set_status("status_already_up_to_date")
            return
        if clear_log:
            self.recent_log_lines.clear()
        self.current_job_kind = "update"
        self.cancel_requested = False
        self.last_output_file = None
        self._reset_progress_state()
        self._set_status("status_preparing_update")
        self._set_running_state_ui(True)
        self._append_log(self.tr("log_update_started") + "\n")
        self.worker_thread = threading.Thread(target=self.run_update_job, daemon=True)
        self.worker_thread.start()

    def download_file(self, url: str, destination: Path, label: str) -> None:
        if self._silent_download:
            return super().download_file(url, destination, label)
        request = urllib.request.Request(url, headers={"User-Agent": f"{core.APP_TITLE}/{APP_VERSION}"})
        try:
            with urllib.request.urlopen(request, timeout=core.NETWORK_TIMEOUT_SECONDS) as response:
                total = int(response.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                if total <= 0:
                    self._set_task_busy("...", label)
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
        except urllib.error.URLError as exc:
            raise core.AppError(f"Failed to download {label}: {exc}") from exc
        except Exception as exc:
            raise core.AppError(f"Failed to write {destination}: {exc}") from exc
        self._set_task_progress(100.0, "100%", label)
        self._append_log(f"{label}: downloaded {destination}\n")

    def update_ffmpeg_binaries(self) -> None:
        asset_name = "ffmpeg-release-essentials.zip"
        self._append_log(f"ffmpeg: downloading {asset_name}\n")
        with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            archive_path = temp_dir / asset_name
            self.download_file(core.FFMPEG_WINDOWS_BUILD_URL, archive_path, "ffmpeg")
            ffmpeg_source = self.extract_binary_from_zip(archive_path, "ffmpeg.exe", temp_dir)
            ffprobe_source = self.extract_binary_from_zip(archive_path, "ffprobe.exe", temp_dir)
            self.replace_binary(ffmpeg_source, core.FFMPEG_PATH)
            self.replace_binary(ffprobe_source, core.FFPROBE_PATH)

    def maybe_update_ytdlp_silent(self) -> None:
        self._silent_download = True
        try:
            super().maybe_update_ytdlp_silent()
        finally:
            self._silent_download = False

    def run_update_job(self) -> None:
        app_installer: Path | None = None
        try:
            self.ensure_environment()
            pending = [key for key, item in self.last_update_plan.items() if bool(item.get("update"))]
            total_items = max(1, len(pending))
            completed = 0

            if "yt-dlp" in pending:
                self._set_status("status_updating_ytdlp")
                with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
                    yt_tmp = Path(temp_dir_text) / "yt-dlp.exe"
                    self.download_file(core.YTDLP_WINDOWS_DOWNLOAD_URL, yt_tmp, "yt-dlp")
                    self.replace_binary(yt_tmp, core.YT_DLP_PATH)
                completed += 1
                progress = completed * 90.0 / total_items
                self._set_progress(progress, f"{progress:.0f}%")

            if "ffmpeg" in pending:
                self._set_status("status_updating")
                self.update_ffmpeg_binaries()
                completed += 1
                progress = completed * 90.0 / total_items
                self._set_progress(progress, f"{progress:.0f}%")

            if "app" in pending:
                if not getattr(sys, "frozen", False):
                    self._append_log(self.ext("update_app_requires_installed") + "\n")
                else:
                    item = self.last_update_plan["app"]
                    installer_url = str(item.get("installer_url", ""))
                    latest = str(item.get("latest", ""))
                    if not installer_url:
                        raise core.AppError("The latest GitHub Release does not contain a MiniURLConverterSetup asset.")
                    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
                    app_installer = UPDATES_DIR / f"MiniURLConverterSetup-{latest}.exe"
                    self._set_status("status_updating")
                    self.download_file(installer_url, app_installer, self.ext("update_app_downloading"))
                completed += 1
                progress = completed * 90.0 / total_items
                self._set_progress(progress, f"{progress:.0f}%")

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
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)

    def _launch_update_after_exit(self, installer: Path) -> None:
        if not installer.is_file():
            messagebox.showerror(self.ext("update_check_title"), f"Installer not found:\n{installer}")
            return
        pid = os.getpid()
        escaped = str(installer).replace("'", "''")
        command = f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; Start-Process -FilePath '{escaped}'"
        flags = core.CREATE_NO_WINDOW | core.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except Exception as exc:
            messagebox.showerror(self.ext("update_check_title"), str(exc))
            return
        self.closing = True
        self.root.after(150, self.root.destroy)


def enhanced_self_test() -> int:
    if core.self_test() != 0:
        return 1
    errors: list[str] = []
    if not is_newer_version("1.2.0", "1.1.9"):
        errors.append("Version comparison failed.")
    if abs(compute_download_total(0, 50.0, 1) - 45.0) > 0.001:
        errors.append("Single-stream progress calculation failed.")
    if abs(compute_download_total(0, 100.0, 2) - 45.0) > 0.001:
        errors.append("Two-stream progress calculation failed.")
    if abs(compute_download_total(1, 100.0, 2) - 90.0) > 0.001:
        errors.append("Second-stream progress calculation failed.")

    try:
        with tempfile.TemporaryDirectory(prefix="mini-url-converter-cookie-test-") as temp_dir:
            cookie_file = Path(temp_dir) / "cookies.txt"
            future = int(time.time()) + 2 * 24 * 60 * 60
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n"
                f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSAPISID\ttest\n",
                encoding="utf-8",
            )
            status = parse_netscape_cookie_status(cookie_file)
            if status.get("state") != "valid":
                errors.append(f"Cookie expiry parser failed: {status}")
    except Exception as exc:
        errors.append(f"Cookie self-test failed: {exc}")

    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("ENHANCED SELF-TEST OK\n")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        raise SystemExit(enhanced_self_test())

    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    EnhancedApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
