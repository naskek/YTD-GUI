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
        "auto_no_browser": "YouTube authentication: no working browser session was found; trying without authentication.",
        "auto_cookie_error": (
            "The app could not obtain a working YouTube session automatically.\n\n"
            "Make sure you are signed in to YouTube in a supported browser. You can also choose a browser manually or import cookies.txt in Settings."
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
        "auto_no_browser": "Авторизация YouTube: рабочая браузерная сессия не найдена, пробую без авторизации.",
        "auto_cookie_error": (
            "Не удалось автоматически получить рабочую авторизацию YouTube.\n\n"
            "Убедитесь, что вы вошли в YouTube в поддерживаемом браузере. В настройках также можно выбрать браузер вручную или импортировать cookies.txt."
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


class App(previous.App):
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
        if key == "cookie_compact" and str(self.ytdlp_settings.get("auth_mode", "auto")) == "auto":
            return self.auto("auto_cookie_error")
        return super().rt(key, **kwargs)

    def _probe_browser_for_url(self, browser: str, url: str) -> bool:
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
        except Exception:
            return False
        return result.returncode == 0 and bool((result.stdout or "").strip())

    def _select_auto_browser(self, url: str) -> str | None:
        candidates = self._detected_browser_candidates()
        # If detection found nothing, try the user's saved preference once. This
        # also covers portable/custom browser installs that are outside our known paths.
        if not candidates:
            fallback = str(self.ytdlp_settings.get("cookies_browser", "chrome"))
            if fallback in core.COOKIE_BROWSER_CHOICES:
                candidates = [fallback]

        for browser in candidates:
            self._append_log(self.auto("auto_try", browser=self._browser_name(browser)) + "\n")
            if not self._probe_browser_for_url(browser, url):
                continue
            self.ytdlp_settings["auto_browser"] = browser
            self.ytdlp_settings["cookies_browser"] = browser
            try:
                self.save_settings()
            except Exception:
                pass
            self._append_log(self.auto("auto_selected", browser=self._browser_name(browser)) + "\n")
            return browser

        self._append_log(self.auto("auto_no_browser") + "\n")
        return None

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
