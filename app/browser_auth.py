from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import auto_auth as previous
import mini_url_converter as core


PROFILE_BROWSERS = {"chrome", "edge", "brave", "vivaldi", "chromium"}

previous.AUTO_TEXT["en"].update(
    {
        "auto_no_auth_needed": "YouTube authentication: this URL is available without signing in; browser cookies are not needed.",
        "auto_no_browser_required": "YouTube authentication: this URL requires sign-in, but no usable browser profile was found.",
        "auto_probe_error": "YouTube authentication: {browser} could not be checked ({reason}).",
    }
)
previous.AUTO_TEXT["ru"].update(
    {
        "auto_no_auth_needed": "Авторизация YouTube: этот URL доступен без входа; cookies браузера не нужны.",
        "auto_no_browser_required": "Авторизация YouTube: для этого URL требуется вход, но рабочий профиль браузера не найден.",
        "auto_probe_error": "Авторизация YouTube: не удалось проверить {browser} ({reason}).",
    }
)


def _browser_from_spec(spec: str) -> str:
    head = spec.split("::", 1)[0]
    head = head.split(":", 1)[0]
    return head.split("+", 1)[0].strip().lower()


def _profile_from_spec(spec: str) -> str:
    head = spec.split("::", 1)[0]
    if ":" not in head:
        return ""
    return head.split(":", 1)[1].strip()


def _browser_root(browser: str) -> Path | None:
    for parts in previous.BROWSER_PROFILE_LOCATIONS.get(browser, ()):
        root = os.environ.get(parts[0])
        if not root:
            continue
        candidate = Path(root).joinpath(*parts[1:])
        if candidate.exists():
            return candidate
    return None


def _read_local_state(root: Path) -> tuple[str, dict[str, str]]:
    last_used = ""
    labels: dict[str, str] = {}
    try:
        payload = json.loads((root / "Local State").read_text(encoding="utf-8"))
        profile = payload.get("profile")
        if isinstance(profile, dict):
            raw_last_used = profile.get("last_used")
            if isinstance(raw_last_used, str):
                last_used = raw_last_used
            info_cache = profile.get("info_cache")
            if isinstance(info_cache, dict):
                for key, value in info_cache.items():
                    if not isinstance(key, str) or not isinstance(value, dict):
                        continue
                    display_name = value.get("name")
                    labels[key] = display_name if isinstance(display_name, str) and display_name.strip() else key
    except Exception:
        pass
    return last_used, labels


def _chromium_profile_specs(browser: str) -> list[tuple[str, str]]:
    root = _browser_root(browser)
    if root is None:
        return []
    if browser == "opera":
        return [(browser, "")]

    last_used, labels = _read_local_state(root)
    profile_names: list[str] = []
    if last_used:
        profile_names.append(last_used)
    profile_names.extend(labels)
    try:
        profile_names.extend(
            child.name
            for child in root.iterdir()
            if child.is_dir() and (child.name == "Default" or child.name.startswith("Profile "))
        )
    except OSError:
        pass

    result: list[tuple[str, str]] = []
    for profile in previous._dedupe(profile_names):
        profile_dir = root / profile
        if not profile_dir.is_dir():
            continue
        display_name = labels.get(profile, profile)
        result.append((f"{browser}:{profile}", display_name))
    if result:
        result.append((browser, ""))
    else:
        result.append((browser, ""))
    return result


def _firefox_profile_specs() -> list[tuple[str, str]]:
    root = _browser_root("firefox")
    if root is None:
        return []
    entries: list[tuple[float, str]] = []
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            cookie_db = child / "cookies.sqlite"
            if cookie_db.is_file():
                try:
                    modified = cookie_db.stat().st_mtime
                except OSError:
                    modified = 0.0
                entries.append((modified, child.name))
    except OSError:
        return [("firefox", "")]

    entries.sort(reverse=True)
    result = [(f"firefox:{name}", name) for _, name in entries]
    result.append(("firefox", ""))
    return result


def _specs_for_browser(browser: str) -> list[tuple[str, str]]:
    if browser == "firefox":
        return _firefox_profile_specs()
    if browser in PROFILE_BROWSERS or browser == "opera":
        return _chromium_profile_specs(browser)
    if previous._browser_profile_exists(browser):
        return [(browser, "")]
    return []


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._browser_spec_labels: dict[str, str] = {}
        super().__init__(root)

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = super().load_ytdlp_settings(data)
        raw_settings = data.get("ytdlp")
        if isinstance(raw_settings, dict):
            auto_browser_spec = raw_settings.get("auto_browser_spec")
            if isinstance(auto_browser_spec, str) and _browser_from_spec(auto_browser_spec) in core.COOKIE_BROWSER_CHOICES:
                settings["auto_browser_spec"] = auto_browser_spec
        settings.setdefault("auto_browser_spec", "")
        return settings

    def _browser_name(self, browser_spec: str) -> str:
        if browser_spec in self._browser_spec_labels:
            return self._browser_spec_labels[browser_spec]
        browser = _browser_from_spec(browser_spec)
        try:
            browser_name = self.cookies_browser_label(browser)
        except Exception:
            browser_name = browser
        profile = _profile_from_spec(browser_spec)
        return f"{browser_name} — {profile}" if profile else browser_name

    def _detected_browser_candidates(self) -> list[str]:
        self._browser_spec_labels.clear()
        remembered_spec = str(self.ytdlp_settings.get("auto_browser_spec", "")).strip()
        remembered_browser = _browser_from_spec(remembered_spec) if remembered_spec else ""
        default_browser = previous._default_windows_browser() or ""
        selected_browser = str(self.ytdlp_settings.get("cookies_browser", "")).strip()
        legacy_browser = str(self.ytdlp_settings.get("auto_browser", "")).strip()
        installed = [browser for browser in core.COOKIE_BROWSER_CHOICES if previous._browser_profile_exists(browser)]
        browser_order = previous._dedupe(
            [remembered_browser, default_browser, selected_browser, legacy_browser, *installed]
        )

        specs: list[str] = []
        if remembered_spec and remembered_browser in core.COOKIE_BROWSER_CHOICES:
            specs.append(remembered_spec)

        for browser in browser_order:
            if browser not in core.COOKIE_BROWSER_CHOICES:
                continue
            for spec, profile_label in _specs_for_browser(browser):
                base_name = self.cookies_browser_label(browser)
                label = f"{base_name} — {profile_label}" if profile_label else base_name
                self._browser_spec_labels[spec] = label
                specs.append(spec)

        return previous._dedupe(specs)

    def _cookie_status_text(self, path: Path | None = None) -> str:
        mode = str(self.ytdlp_settings.get("auth_mode", "auto"))
        if mode != "auto":
            return super()._cookie_status_text(path)
        specs = self._detected_browser_candidates()
        browsers = previous._dedupe([_browser_from_spec(spec) for spec in specs])
        default_browser = previous._default_windows_browser()
        if default_browser and default_browser in browsers:
            return self.auto("auto_status_default", browser=self.cookies_browser_label(default_browser))
        if browsers:
            names = ", ".join(self.cookies_browser_label(browser) for browser in browsers)
            return self.auto("auto_status_detected", browsers=names)
        return self.auto("auto_status_none")

    def _probe_without_auth(self, url: str) -> tuple[str, str]:
        command = [
            str(core.YT_DLP_PATH),
            "--encoding",
            "utf-8",
            "--no-warnings",
            "--no-playlist",
            "--skip-download",
            "--no-cookies",
            "--no-cookies-from-browser",
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
        return previous._classify_probe_output(combined), combined

    def _select_auto_browser(self, url: str, *, auth_required: bool = False) -> str | None:
        self._auto_cookie_problem_kind = ""
        self._auto_cookie_problem_browser = ""
        candidates = self._detected_browser_candidates()
        if not candidates:
            fallback = str(self.ytdlp_settings.get("cookies_browser", "chrome"))
            if fallback in core.COOKIE_BROWSER_CHOICES:
                candidates = [fallback]

        first_locked = ""
        first_decrypt = ""
        first_auth = ""
        for browser_spec in candidates:
            browser_name = self._browser_name(browser_spec)
            self._append_log(self.auto("auto_try", browser=browser_name) + "\n")
            result_kind, detail = self._probe_browser_for_url(browser_spec, url)
            if result_kind == "ok":
                browser = _browser_from_spec(browser_spec)
                self._auto_cookie_problem_kind = ""
                self._auto_cookie_problem_browser = ""
                self.ytdlp_settings["auto_browser_spec"] = browser_spec
                self.ytdlp_settings["auto_browser"] = browser
                self.ytdlp_settings["cookies_browser"] = browser
                try:
                    self.save_settings()
                except Exception:
                    pass
                self._append_log(self.auto("auto_selected", browser=browser_name) + "\n")
                return browser_spec
            if result_kind == "locked":
                first_locked = first_locked or browser_spec
                self._append_log(self.auto("auto_locked_log", browser=browser_name) + "\n")
            elif result_kind == "decrypt":
                first_decrypt = first_decrypt or browser_spec
                self._append_log(self.auto("auto_decrypt_log", browser=browser_name) + "\n")
            elif result_kind == "auth":
                first_auth = first_auth or browser_spec
                self._append_log(self.auto("auto_auth_missing_log", browser=browser_name) + "\n")
            else:
                reason = detail.splitlines()[-1] if detail else result_kind
                self._append_log(self.auto("auto_probe_error", browser=browser_name, reason=reason) + "\n")

        if first_locked:
            self._auto_cookie_problem_kind = "locked"
            self._auto_cookie_problem_browser = first_locked
        elif first_decrypt:
            self._auto_cookie_problem_kind = "decrypt"
            self._auto_cookie_problem_browser = first_decrypt
        elif first_auth:
            self._auto_cookie_problem_kind = "auth"
            self._auto_cookie_problem_browser = first_auth

        if auth_required:
            self._append_log(self.auto("auto_no_browser_required") + "\n")
        else:
            self._append_log(self.auto("auto_no_browser") + "\n")
        return None

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto" or not command:
            return super().run_ytdlp_command(command)

        url = command[-1]
        unauth_kind, _detail = self._probe_without_auth(url)
        if unauth_kind == "ok":
            self._append_log(self.auto("auto_no_auth_needed") + "\n")
            return super().run_ytdlp_command(command)

        auth_required = unauth_kind == "auth"
        browser_spec = self._select_auto_browser(url, auth_required=auth_required)
        if browser_spec is None:
            if auth_required:
                raise core.AppError(self.rt("cookie_compact"))
            return super().run_ytdlp_command(command)

        authenticated = list(command[:-1])
        authenticated.extend(["--cookies-from-browser", browser_spec, url])
        return super().run_ytdlp_command(authenticated)


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors: list[str] = []
    if _browser_from_spec("chrome:Profile 1") != "chrome":
        errors.append("Browser spec parser failed for Chromium profile.")
    if _profile_from_spec("chrome:Profile 1") != "Profile 1":
        errors.append("Profile parser failed for Chromium profile.")
    if _browser_from_spec("firefox:abcd.default-release::none") != "firefox":
        errors.append("Browser spec parser failed for Firefox container syntax.")
    if _profile_from_spec("firefox:abcd.default-release::none") != "abcd.default-release":
        errors.append("Profile parser failed for Firefox container syntax.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("PROFILE-AWARE AUTH SELF-TEST OK\n")
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
