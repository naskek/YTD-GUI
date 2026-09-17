from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import auto_auth as auto_layer
import browser_auth as previous
import launcher
import mini_url_converter as core
import runtime as runtime_layer


DECRYPT_CACHE_TTL_SECONDS = 6 * 60 * 60
CHROMIUM_BROWSERS = {"chrome", "edge", "brave", "opera", "vivaldi", "chromium"}

POLICY_TEXT = {
    "en": {
        "auto_skip_decrypt_cached": (
            "YouTube authentication: skipping direct cookie reading from {browser}; Windows recently rejected "
            "decryption. It will be retried automatically later."
        ),
        "auto_try_saved_cookies": "YouTube authentication: checking saved cookies.txt...",
        "auto_saved_cookies_selected": "YouTube authentication: using saved cookies.txt.",
        "auto_saved_cookies_missing": "YouTube authentication: no usable saved cookies.txt fallback is available.",
        "auto_saved_cookies_rejected": "YouTube authentication: YouTube rejected the saved cookies.txt.",
        "auto_saved_cookies_error": "YouTube authentication: saved cookies.txt could not be checked ({reason}).",
    },
    "ru": {
        "auto_skip_decrypt_cached": (
            "Авторизация YouTube: прямое чтение cookies из {browser} временно пропускаю — Windows недавно уже "
            "отказал в расшифровке. Проверю снова автоматически позже."
        ),
        "auto_try_saved_cookies": "Авторизация YouTube: проверяю сохранённые cookies.txt...",
        "auto_saved_cookies_selected": "Авторизация YouTube: использую сохранённые cookies.txt.",
        "auto_saved_cookies_missing": "Авторизация YouTube: пригодных сохранённых cookies.txt для резерва нет.",
        "auto_saved_cookies_rejected": "Авторизация YouTube: YouTube отклонил сохранённые cookies.txt.",
        "auto_saved_cookies_error": "Авторизация YouTube: не удалось проверить сохранённые cookies.txt ({reason}).",
    },
}


def _normalize_decrypt_cache(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for browser, raw_timestamp in value.items():
        if not isinstance(browser, str) or browser not in core.COOKIE_BROWSER_CHOICES:
            continue
        if isinstance(raw_timestamp, (int, float)) and raw_timestamp > 0:
            result[browser] = float(raw_timestamp)
    return result


def _candidate_groups(specs: list[str], remembered_spec: str) -> tuple[list[str], list[str]]:
    early: list[str] = []
    late: list[str] = []
    seen: set[str] = set()

    if remembered_spec and remembered_spec in specs:
        early.append(remembered_spec)
        seen.add(remembered_spec)

    for spec in specs:
        if spec in seen:
            continue
        browser = previous._browser_from_spec(spec)
        if browser == "firefox":
            early.append(spec)
            seen.add(spec)

    for spec in specs:
        if spec not in seen:
            late.append(spec)
            seen.add(spec)

    return early, late


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._auto_problem_priority = 0
        self._logged_cached_browsers: set[str] = set()
        super().__init__(root)

    def policy(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in POLICY_TEXT else "en"
        template = POLICY_TEXT[language].get(key) or POLICY_TEXT["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = super().load_ytdlp_settings(data)
        raw_settings = data.get("ytdlp")
        cache: dict[str, float] = {}
        if isinstance(raw_settings, dict):
            cache = _normalize_decrypt_cache(raw_settings.get("auto_decrypt_failures"))
        settings["auto_decrypt_failures"] = cache
        return settings

    def _save_settings_quietly(self) -> None:
        try:
            self.save_settings()
        except Exception:
            pass

    def _decrypt_cache(self) -> dict[str, float]:
        cache = _normalize_decrypt_cache(self.ytdlp_settings.get("auto_decrypt_failures"))
        self.ytdlp_settings["auto_decrypt_failures"] = cache
        return cache

    def _browser_decrypt_is_cached(self, browser: str) -> bool:
        cache = self._decrypt_cache()
        failed_at = float(cache.get(browser, 0.0) or 0.0)
        if failed_at <= 0:
            return False
        if time.time() - failed_at < DECRYPT_CACHE_TTL_SECONDS:
            return True
        cache.pop(browser, None)
        self._save_settings_quietly()
        return False

    def _remember_decrypt_failure(self, browser: str) -> None:
        if browser not in CHROMIUM_BROWSERS:
            return
        cache = self._decrypt_cache()
        cache[browser] = time.time()
        self.ytdlp_settings["auto_decrypt_failures"] = cache
        self._save_settings_quietly()

    def _clear_decrypt_failure(self, browser: str) -> None:
        cache = self._decrypt_cache()
        if browser in cache:
            cache.pop(browser, None)
            self.ytdlp_settings["auto_decrypt_failures"] = cache
            self._save_settings_quietly()

    def _remember_problem(self, kind: str, browser_spec: str) -> None:
        priority = {"auth": 1, "decrypt": 2, "locked": 3}.get(kind, 0)
        if priority <= self._auto_problem_priority:
            return
        self._auto_problem_priority = priority
        self._auto_cookie_problem_kind = kind
        self._auto_cookie_problem_browser = browser_spec

    def _run_probe(self, command: list[str]) -> tuple[str, str]:
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
        return auto_layer._classify_probe_output(combined), combined

    def _try_browser_specs(self, url: str, specs: list[str]) -> str | None:
        blocked_this_run: set[str] = set()
        for browser_spec in specs:
            browser = previous._browser_from_spec(browser_spec)
            if browser in blocked_this_run:
                continue
            browser_name = self._browser_name(browser_spec)

            if browser in CHROMIUM_BROWSERS and self._browser_decrypt_is_cached(browser):
                if browser not in self._logged_cached_browsers:
                    self._logged_cached_browsers.add(browser)
                    self._append_log(self.policy("auto_skip_decrypt_cached", browser=self.cookies_browser_label(browser)) + "\n")
                continue

            self._append_log(self.auto("auto_try", browser=browser_name) + "\n")
            result_kind, detail = self._probe_browser_for_url(browser_spec, url)
            if result_kind == "ok":
                self._auto_cookie_problem_kind = ""
                self._auto_cookie_problem_browser = ""
                self._auto_problem_priority = 0
                self._clear_decrypt_failure(browser)
                self.ytdlp_settings["auto_browser_spec"] = browser_spec
                self.ytdlp_settings["auto_browser"] = browser
                self.ytdlp_settings["cookies_browser"] = browser
                self._save_settings_quietly()
                self._append_log(self.auto("auto_selected", browser=browser_name) + "\n")
                return browser_spec

            if result_kind == "locked":
                self._remember_problem("locked", browser_spec)
                blocked_this_run.add(browser)
                self._append_log(self.auto("auto_locked_log", browser=browser_name) + "\n")
            elif result_kind == "decrypt":
                self._remember_problem("decrypt", browser_spec)
                self._remember_decrypt_failure(browser)
                blocked_this_run.add(browser)
                self._append_log(self.auto("auto_decrypt_log", browser=browser_name) + "\n")
            elif result_kind == "auth":
                self._remember_problem("auth", browser_spec)
                self._append_log(self.auto("auto_auth_missing_log", browser=browser_name) + "\n")
            else:
                reason = detail.splitlines()[-1] if detail else result_kind
                self._append_log(self.auto("auto_probe_error", browser=browser_name, reason=reason) + "\n")
        return None

    def _mark_auto_cookie_failed(self) -> None:
        self.ytdlp_settings["cookie_last_failed_at"] = time.time()
        self._save_settings_quietly()

    def _clear_auto_cookie_failed(self) -> None:
        if float(self.ytdlp_settings.get("cookie_last_failed_at", 0.0) or 0.0) <= 0:
            return
        self.ytdlp_settings["cookie_last_failed_at"] = 0.0
        self._save_settings_quietly()

    def _try_saved_cookie_file(self, url: str) -> Path | None:
        try:
            cookie_path = self._resolve_cookies_file_path()
        except Exception:
            self._append_log(self.policy("auto_saved_cookies_missing") + "\n")
            return None

        self._append_log(self.policy("auto_try_saved_cookies") + "\n")
        command = [
            str(core.YT_DLP_PATH),
            "--encoding",
            "utf-8",
            "--no-warnings",
            "--no-playlist",
            "--skip-download",
            "--no-cookies-from-browser",
            "--cookies",
            str(cookie_path),
            "--print",
            "%(id)s",
            url,
        ]
        result_kind, detail = self._run_probe(command)
        if result_kind == "ok":
            self._clear_auto_cookie_failed()
            self._append_log(self.policy("auto_saved_cookies_selected") + "\n")
            return cookie_path
        if result_kind == "auth":
            self._mark_auto_cookie_failed()
            self._append_log(self.policy("auto_saved_cookies_rejected") + "\n")
            return None
        reason = detail.splitlines()[-1] if detail else result_kind
        self._append_log(self.policy("auto_saved_cookies_error", reason=reason) + "\n")
        return None

    @staticmethod
    def _with_browser_auth(command: list[str], browser_spec: str) -> list[str]:
        url = command[-1]
        authenticated = list(command[:-1])
        authenticated.extend(["--cookies-from-browser", browser_spec, url])
        return authenticated

    @staticmethod
    def _with_cookie_file(command: list[str], cookie_path: Path) -> list[str]:
        url = command[-1]
        authenticated = list(command[:-1])
        authenticated.extend(["--cookies", str(cookie_path), url])
        return authenticated

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto" or not command:
            return previous.App.run_ytdlp_command(self, command)

        self._auto_cookie_problem_kind = ""
        self._auto_cookie_problem_browser = ""
        self._auto_problem_priority = 0
        self._logged_cached_browsers.clear()

        url = command[-1]
        unauth_kind, _detail = self._probe_without_auth(url)
        if unauth_kind == "ok":
            self._append_log(self.auto("auto_no_auth_needed") + "\n")
            return runtime_layer.App.run_ytdlp_command(self, command)
        if unauth_kind != "auth":
            return runtime_layer.App.run_ytdlp_command(self, command)

        specs = self._detected_browser_candidates()
        remembered_spec = str(self.ytdlp_settings.get("auto_browser_spec", "")).strip()
        early_specs, late_specs = _candidate_groups(specs, remembered_spec)

        browser_spec = self._try_browser_specs(url, early_specs)
        if browser_spec is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_browser_auth(command, browser_spec))

        cookie_path = self._try_saved_cookie_file(url)
        if cookie_path is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_cookie_file(command, cookie_path))

        browser_spec = self._try_browser_specs(url, late_specs)
        if browser_spec is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_browser_auth(command, browser_spec))

        self._append_log(self.auto("auto_no_browser_required") + "\n")
        raise core.AppError(self.rt("cookie_compact"))


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors: list[str] = []
    if DECRYPT_CACHE_TTL_SECONDS <= 0:
        errors.append("Decrypt cache TTL must be positive.")
    normalized = _normalize_decrypt_cache({"chrome": 123.0, "invalid": 456.0, "edge": "bad"})
    if normalized != {"chrome": 123.0}:
        errors.append("Decrypt cache normalization failed.")
    early, late = _candidate_groups(
        ["chrome:Default", "firefox:test.default", "edge:Default"],
        "chrome:Default",
    )
    if early != ["chrome:Default", "firefox:test.default"] or late != ["edge:Default"]:
        errors.append("Automatic auth candidate ordering failed.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("AUTH POLICY SELF-TEST OK\n")
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
