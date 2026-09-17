from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import launcher
import mini_url_converter as core
import runtime as previous


# Make automatic browser authentication the default for new/reset settings while
# preserving explicit settings already saved by existing users.
core.AUTH_MODE_CHOICES = ("auto", "browser", "file", "none")
core.YTDLP_DEFAULTS["auth_mode"] = "auto"
core.YTDLP_DEFAULTS["cookies_browser"] = "chrome"
core.TRANSLATIONS["en"]["option_auth_auto"] = "Automatic (recommended)"
core.TRANSLATIONS["ru"]["option_auth_auto"] = "Автоматически (рекомендуется)"
launcher.EXTRA_TRANSLATIONS["en"]["label_cookie_status"] = "Authentication status"
launcher.EXTRA_TRANSLATIONS["ru"]["label_cookie_status"] = "Статус авторизации"


AUTO_TEXT = {
    "en": {
        "auto_status_default": (
            "Automatic mode. System browser: {browser}. Cookies are read directly from the browser for each download; "
            "no cookies.txt export is needed."
        ),
        "auto_status_detected": (
            "Automatic mode. Detected browsers: {browsers}. The app will try them automatically; no cookies.txt export is needed."
        ),
        "auto_status_none": (
            "Automatic mode. No supported browser profile was detected. The app will try the saved preferred browser and then continue without authentication if possible."
        ),
        "browser_status": "Cookies are read directly from {browser} for each download.",
        "none_status": "YouTube authentication is disabled.",
        "auto_try": "YouTube authentication: checking {browser}...",
        "auto_selected": "YouTube authentication: {browser} (automatic)",
        "auto_locked_log": "YouTube authentication: {browser} is open and is locking its cookie database.",
        "auto_auth_missing_log": "YouTube authentication: {browser} did not provide a usable YouTube session.",
        "auto_decrypt_log": "YouTube authentication: could not decrypt cookies from {browser}.",
        "auto_no_browser": "YouTube authentication: no working browser session was found; trying without authentication.",
        "auto_cookie_error": (
            "The app could not obtain a working YouTube session automatically.\n\n"
            "Make sure you are signed in to YouTube in a supported browser. You can also choose a browser manually or import cookies.txt in Settings."
        ),
        "browser_locked_title": "Browser cookies are locked",
        "browser_locked_message": (
            "{browser} is open and Windows will not allow yt-dlp to read its cookie database.\n\n"
            "Close {browser} completely, then click Retry. You do not need to paste the URL again."
        ),
        "browser_decrypt_message": (
            "The app found {browser}, but Windows could not decrypt its cookies.\n\n"
            "Try another browser in Settings or use cookies.txt."
        ),
        "button_retry": "Retry",
        "preflight_auth_skipped": (
            "Media preflight could not authenticate with YouTube; the main download will try automatic browser authentication."
        ),
    },
    "ru": {
        "auto_status_default": (
            "Автоматический режим. Системный браузер: {browser}. Cookies читаются прямо из браузера при каждой загрузке; "
            "экспортировать cookies.txt не нужно."
        ),
        "auto_status_detected": (
            "Автоматический режим. Найдены браузеры: {browsers}. Программа попробует их сама; экспортировать cookies.txt не нужно."
        ),
        "auto_status_none": (
            "Автоматический режим. Поддерживаемый профиль браузера не найден. Программа попробует сохранённый браузер, а затем — загрузку без авторизации, если это возможно."
        ),
        "browser_status": "Cookies читаются прямо из {browser} при каждой загрузке.",
        "none_status": "Авторизация YouTube отключена.",
        "auto_try": "Авторизация YouTube: проверяю {browser}...",
        "auto_selected": "Авторизация YouTube: {browser} (автоматически)",
        "auto_locked_log": "Авторизация YouTube: {browser} открыт и блокирует базу cookies.",
        "auto_auth_missing_log": "Авторизация YouTube: в {browser} не найдена подходящая сессия YouTube.",
        "auto_decrypt_log": "Авторизация YouTube: не удалось расшифровать cookies из {browser}.",
        "auto_no_browser": "Авторизация YouTube: рабочая браузерная сессия не найдена, пробую без авторизации.",
        "auto_cookie_error": (
            "Не удалось автоматически получить рабочую авторизацию YouTube.\n\n"
            "Убедитесь, что вы вошли в YouTube в поддерживаемом браузере. В настройках также можно выбрать браузер вручную или импортировать cookies.txt."
        ),
        "browser_locked_title": "Cookies браузера заблокированы",
        "browser_locked_message": (
            "{browser} открыт, и Windows не даёт yt-dlp прочитать его базу cookies.\n\n"
            "Полностью закройте {browser}, затем нажмите «Повторить». Ссылку вставлять заново не нужно."
        ),
        "browser_decrypt_message": (
            "Программа нашла {browser}, но Windows не смогла расшифровать его cookies.\n\n"
            "Попробуйте другой браузер в настройках или используйте cookies.txt."
        ),
        "button_retry": "Повторить",
        "preflight_auth_skipped": (
            "Предварительный анализ не смог авторизоваться в YouTube; основная загрузка попробует автоматическую авторизацию через браузер."
        ),
    },
}


BROWSER_PROFILE_LOCATIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "chrome": (("LOCALAPPDATA", "Google", "Chrome", "User Data"),),
    "edge": (("LOCALAPPDATA", "Microsoft", "Edge", "User Data"),),
    "firefox": (("APPDATA", "Mozilla", "Firefox", "Profiles"),),
    "brave": (("LOCALAPPDATA", "BraveSoftware", "Brave-Browser", "User Data"),),
    "vivaldi": (("LOCALAPPDATA", "Vivaldi", "User Data"),),
    "opera": (
        ("APPDATA", "Opera Software", "Opera Stable"),
        ("LOCALAPPDATA", "Programs", "Opera"),
    ),
    "chromium": (("LOCALAPPDATA", "Chromium", "User Data"),),
}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _browser_profile_exists(browser: str) -> bool:
    for parts in BROWSER_PROFILE_LOCATIONS.get(browser, ()):
        root = os.environ.get(parts[0])
        if not root:
            continue
        candidate = Path(root).joinpath(*parts[1:])
        if candidate.exists():
            return True
    return False


def _default_windows_browser() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0]).lower()
    except Exception:
        return None

    mapping = (
        ("chromehtml", "chrome"),
        ("msedgehtm", "edge"),
        ("firefoxurl", "firefox"),
        ("bravehtml", "brave"),
        ("vivaldi", "vivaldi"),
        ("opera", "opera"),
        ("chromium", "chromium"),
    )
    for marker, browser in mapping:
        if marker in prog_id:
            return browser
    return None


def _classify_probe_output(output: str) -> str:
    lower = output.lower()
    if (
        ("could not copy" in lower and "cookie database" in lower)
        or ("permissionerror" in lower and "network\\cookies" in lower)
        or ("permission denied" in lower and "cookie" in lower and "database" in lower)
    ):
        return "locked"
    if "failed to decrypt" in lower or "app-bound encryption" in lower or "dpapi" in lower and "decrypt" in lower:
        return "decrypt"
    if any(pattern in lower for pattern in core.AUTH_REQUIRED_PATTERNS):
        return "auth"
    return "error"


def _looks_like_auth_problem(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in core.AUTH_REQUIRED_PATTERNS) or _classify_probe_output(text) in {
        "locked",
        "decrypt",
        "auth",
    }


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._auto_cookie_problem_kind = ""
        self._auto_cookie_problem_browser = ""
        super().__init__(root)

    def auto(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in AUTO_TEXT else "en"
        template = AUTO_TEXT[language].get(key) or AUTO_TEXT["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = super().load_ytdlp_settings(data)
        raw_settings = data.get("ytdlp")
        if isinstance(raw_settings, dict):
            auto_browser = raw_settings.get("auto_browser")
            if isinstance(auto_browser, str) and auto_browser in core.COOKIE_BROWSER_CHOICES:
                settings["auto_browser"] = auto_browser
        settings.setdefault("auto_browser", "")
        return settings

    def _browser_name(self, browser: str) -> str:
        try:
            return self.cookies_browser_label(browser)
        except Exception:
            return browser

    def _detected_browser_candidates(self) -> list[str]:
        default_browser = _default_windows_browser()
        remembered = str(self.ytdlp_settings.get("auto_browser", "")).strip()
        selected = str(self.ytdlp_settings.get("cookies_browser", "")).strip()
        installed = [browser for browser in core.COOKIE_BROWSER_CHOICES if _browser_profile_exists(browser)]
        candidates = [default_browser or "", remembered, selected, *installed]
        return [browser for browser in _dedupe(candidates) if browser in core.COOKIE_BROWSER_CHOICES]

    def _cookie_status_text(self, path: Path | None = None) -> str:
        mode = str(self.ytdlp_settings.get("auth_mode", "auto"))
        if mode == "auto":
            candidates = self._detected_browser_candidates()
            default_browser = _default_windows_browser()
            if default_browser and default_browser in candidates:
                return self.auto("auto_status_default", browser=self._browser_name(default_browser))
            if candidates:
                names = ", ".join(self._browser_name(browser) for browser in candidates)
                return self.auto("auto_status_detected", browsers=names)
            return self.auto("auto_status_none")
        if mode == "browser":
            browser = str(self.ytdlp_settings.get("cookies_browser", "chrome"))
            return self.auto("browser_status", browser=self._browser_name(browser))
        if mode == "none":
            return self.auto("none_status")
        return super()._cookie_status_text(path)

    def rt(self, key: str, **kwargs: object) -> str:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) == "auto":
            if key == "preflight_auth_skipped":
                return self.auto("preflight_auth_skipped")
            if key == "cookie_compact":
                browser_name = self._browser_name(self._auto_cookie_problem_browser or "chrome")
                if self._auto_cookie_problem_kind == "locked":
                    return self.auto("browser_locked_message", browser=browser_name)
                if self._auto_cookie_problem_kind == "decrypt":
                    return self.auto("browser_decrypt_message", browser=browser_name)
                return self.auto("auto_cookie_error")
        return super().rt(key, **kwargs)

    def _probe_browser_for_url(self, browser: str, url: str) -> tuple[str, str]:
        command = [
            str(core.YT_DLP_PATH),
            "--encoding",
            "utf-8",
            "--no-warnings",
            "--no-playlist",
            "--skip-download",
            "--cookies-from-browser",
            browser,
            "--print",
            "%(id)s",
            url,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=str(core.PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=18,
                check=False,
                creationflags=core.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            return "error", str(exc)
        except Exception as exc:
            return "error", str(exc)

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if result.returncode == 0 and stdout.strip():
            return "ok", combined
        return _classify_probe_output(combined), combined

    def _select_auto_browser(self, url: str) -> str | None:
        self._auto_cookie_problem_kind = ""
        self._auto_cookie_problem_browser = ""
        candidates = self._detected_browser_candidates()
        # If detection found nothing, try the user's saved preference once. This
        # also covers portable/custom browser installs that are outside our known paths.
        if not candidates:
            fallback = str(self.ytdlp_settings.get("cookies_browser", "chrome"))
            if fallback in core.COOKIE_BROWSER_CHOICES:
                candidates = [fallback]

        first_locked = ""
        first_decrypt = ""
        for browser in candidates:
            browser_name = self._browser_name(browser)
            self._append_log(self.auto("auto_try", browser=browser_name) + "\n")
            result_kind, _detail = self._probe_browser_for_url(browser, url)
            if result_kind == "ok":
                self._auto_cookie_problem_kind = ""
                self._auto_cookie_problem_browser = ""
                self.ytdlp_settings["auto_browser"] = browser
                self.ytdlp_settings["cookies_browser"] = browser
                try:
                    self.save_settings()
                except Exception:
                    pass
                self._append_log(self.auto("auto_selected", browser=browser_name) + "\n")
                return browser
            if result_kind == "locked":
                if not first_locked:
                    first_locked = browser
                self._append_log(self.auto("auto_locked_log", browser=browser_name) + "\n")
                continue
            if result_kind == "decrypt":
                if not first_decrypt:
                    first_decrypt = browser
                self._append_log(self.auto("auto_decrypt_log", browser=browser_name) + "\n")
                continue
            if result_kind == "auth":
                self._append_log(self.auto("auto_auth_missing_log", browser=browser_name) + "\n")

        if first_locked:
            self._auto_cookie_problem_kind = "locked"
            self._auto_cookie_problem_browser = first_locked
        elif first_decrypt:
            self._auto_cookie_problem_kind = "decrypt"
            self._auto_cookie_problem_browser = first_decrypt

        self._append_log(self.auto("auto_no_browser") + "\n")
        return None

    def run_url_analysis_job(self, request_id: int, url: str) -> None:
        try:
            self.ensure_required_binary("yt-dlp.exe", core.YT_DLP_PATH)
            info = self.fetch_url_analysis_info(url)
            output_path = self.resolve_analysis_output_path(info)
            if output_path is not None and output_path.exists() and output_path.is_file():
                size_bytes = float(output_path.stat().st_size)
                log_text = self.tr("log_actual_output_size", size_mb=self.format_size_mb(size_bytes))
            else:
                size_bytes = self.estimate_output_size_bytes(info)
                if size_bytes is None:
                    raise core.AppError("No filesize metadata returned by yt-dlp.")
                log_text = self.tr("log_estimated_output_size", size_mb=self.format_size_mb(size_bytes))
            if request_id != self.url_analysis_request_id or self.closing:
                return
            self._append_log(log_text + "\n")
        except Exception as exc:
            if request_id != self.url_analysis_request_id or self.closing:
                return
            detail = self._stringify_error(exc)
            if str(self.ytdlp_settings.get("auth_mode", "auto")) == "auto" and _looks_like_auth_problem(detail):
                return
            self._append_log(self.tr("log_failed_estimate_output_size", error=detail) + "\n")

    def _show_cookie_dialog(self) -> None:
        if (
            str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto"
            or self._auto_cookie_problem_kind != "locked"
        ):
            super()._show_cookie_dialog()
            return

        browser = self._auto_cookie_problem_browser or "chrome"
        browser_name = self._browser_name(browser)
        dialog = tk.Toplevel(self.root)
        dialog.title(self.auto("browser_locked_title"))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=self.auto("browser_locked_message", browser=browser_name),
            wraplength=430,
            justify="left",
        ).pack(fill="x")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))

        def wait_until_idle(callback: object) -> None:
            if self.worker_thread and self.worker_thread.is_alive():
                self.root.after(100, lambda: wait_until_idle(callback))
                return
            callback()  # type: ignore[operator]

        def retry_download() -> None:
            if dialog.winfo_exists():
                dialog.destroy()
            self._auto_cookie_problem_kind = ""
            self._auto_cookie_problem_browser = ""
            self.root.after(50, lambda: wait_until_idle(self.on_start))

        def open_settings_when_ready() -> None:
            if dialog.winfo_exists():
                dialog.destroy()
            self.root.after(50, lambda: wait_until_idle(self.open_settings_dialog))

        ttk.Button(buttons, text=self.rt("button_close"), command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text=self.rt("button_open_settings"), command=open_settings_when_ready).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(buttons, text=self.auto("button_retry"), command=retry_download).pack(
            side="right", padx=(0, 8)
        )

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.focus_force()

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto":
            return super().run_ytdlp_command(command)
        if not command:
            return super().run_ytdlp_command(command)

        url = command[-1]
        browser = self._select_auto_browser(url)
        if browser is None:
            return super().run_ytdlp_command(command)

        authenticated = list(command[:-1])
        authenticated.extend(["--cookies-from-browser", browser, url])
        return super().run_ytdlp_command(authenticated)


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors: list[str] = []
    if core.YTDLP_DEFAULTS.get("auth_mode") != "auto":
        errors.append("Automatic authentication is not the default.")
    if not core.AUTH_MODE_CHOICES or core.AUTH_MODE_CHOICES[0] != "auto":
        errors.append("Automatic authentication is not the first auth mode.")
    if _dedupe(["chrome", "chrome", "edge", "chrome"]) != ["chrome", "edge"]:
        errors.append("Browser candidate deduplication failed.")
    locked_sample = (
        "ERROR: Could not copy Chrome cookie database.\n"
        "PermissionError: [Errno 13] Permission denied: C:\\Users\\x\\Chrome\\Default\\Network\\Cookies"
    )
    if _classify_probe_output(locked_sample) != "locked":
        errors.append("Locked browser cookie database was not classified correctly.")
    auth_sample = "ERROR: Sign in to confirm your age. Use --cookies-from-browser or --cookies"
    if _classify_probe_output(auth_sample) != "auth":
        errors.append("YouTube authentication failure was not classified correctly.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("AUTO AUTH SELF-TEST OK\n")
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
