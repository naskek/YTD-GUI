from __future__ import annotations

import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import auth_policy as previous
import chrome_bridge
import mini_url_converter as core
import runtime as runtime_layer


BRIDGE_TEXT = {
    "en": {
        "bridge_try": "YouTube authentication: requesting live cookies from Chrome...",
        "bridge_selected": "YouTube authentication: using live Chrome cookies ({count} cookies).",
        "bridge_unavailable": "YouTube authentication: the Chrome bridge is not connected.",
        "bridge_rejected": "YouTube authentication: YouTube rejected the live Chrome session.",
        "bridge_error": "YouTube authentication: Chrome bridge failed ({reason}).",
        "bridge_setup_title": "Connect Chrome",
        "bridge_setup_message": (
            "Chrome protects its cookies with Windows App-Bound Encryption, so yt-dlp cannot read them directly. "
            "Mini URL Converter can ask Chrome itself for the YouTube session through a local extension.\n\n"
            "1. Click Connect Chrome.\n"
            "2. On chrome://extensions enable Developer mode.\n"
            "3. Click Load unpacked and choose the folder that opens.\n"
            "4. Return here and click Retry.\n\n"
            "This is a one-time setup. The bridge only requests YouTube/Google cookies and runs locally on this PC."
        ),
        "bridge_connect_button": "Connect Chrome",
        "bridge_setup_opened": "Chrome extensions and the local extension folder were opened.",
    },
    "ru": {
        "bridge_try": "Авторизация YouTube: запрашиваю актуальные cookies напрямую из Chrome...",
        "bridge_selected": "Авторизация YouTube: использую актуальные cookies из Chrome ({count} шт.).",
        "bridge_unavailable": "Авторизация YouTube: Chrome bridge не подключён.",
        "bridge_rejected": "Авторизация YouTube: YouTube отклонил текущую сессию Chrome.",
        "bridge_error": "Авторизация YouTube: ошибка Chrome bridge ({reason}).",
        "bridge_setup_title": "Подключить Chrome",
        "bridge_setup_message": (
            "Chrome защищает cookies через Windows App-Bound Encryption, поэтому yt-dlp не может прочитать их напрямую. "
            "Mini URL Converter может попросить сам Chrome передать текущую сессию YouTube через локальное расширение.\n\n"
            "1. Нажмите «Подключить Chrome».\n"
            "2. На chrome://extensions включите «Режим разработчика».\n"
            "3. Нажмите «Загрузить распакованное расширение» и выберите открывшуюся папку.\n"
            "4. Вернитесь сюда и нажмите «Повторить».\n\n"
            "Это одноразовая настройка. Bridge запрашивает только cookies YouTube/Google и работает локально на этом ПК."
        ),
        "bridge_connect_button": "Подключить Chrome",
        "bridge_setup_opened": "Открыты настройки расширений Chrome и папка локального расширения.",
    },
}


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._bridge_setup_needed = False
        self._bridge_register_error = ""
        super().__init__(root)
        ok, detail = chrome_bridge.register_native_host()
        if not ok:
            self._bridge_register_error = detail

    def bridge(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in BRIDGE_TEXT else "en"
        template = BRIDGE_TEXT[language].get(key) or BRIDGE_TEXT["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def _try_chrome_bridge(self, url: str) -> Path | None:
        self._append_log(self.bridge("bridge_try") + "\n")
        ok, detail = chrome_bridge.register_native_host()
        if not ok:
            self._bridge_setup_needed = True
            reason = detail or self._bridge_register_error or "native host registration failed"
            self._append_log(self.bridge("bridge_error", reason=reason) + "\n")
            return None

        if not chrome_bridge.bridge_health():
            self._bridge_setup_needed = True
            self._append_log(self.bridge("bridge_unavailable") + "\n")
            return None

        try:
            cookie_path, count = chrome_bridge.request_live_chrome_cookies()
        except Exception as exc:
            self._bridge_setup_needed = True
            self._append_log(self.bridge("bridge_error", reason=str(exc)) + "\n")
            return None

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
            self._bridge_setup_needed = False
            self._append_log(self.bridge("bridge_selected", count=count) + "\n")
            return cookie_path
        if result_kind == "auth":
            self._append_log(self.bridge("bridge_rejected") + "\n")
            return None
        reason = detail.splitlines()[-1] if detail else result_kind
        self._append_log(self.bridge("bridge_error", reason=reason) + "\n")
        return None

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto" or not command:
            return previous.App.run_ytdlp_command(self, command)

        self._auto_cookie_problem_kind = ""
        self._auto_cookie_problem_browser = ""
        self._auto_problem_priority = 0
        self._logged_cached_browsers.clear()
        self._bridge_setup_needed = False

        url = command[-1]
        unauth_kind, _detail = self._probe_without_auth(url)
        if unauth_kind == "ok":
            self._append_log(self.auto("auto_no_auth_needed") + "\n")
            return runtime_layer.App.run_ytdlp_command(self, command)
        if unauth_kind != "auth":
            return runtime_layer.App.run_ytdlp_command(self, command)

        specs = self._detected_browser_candidates()
        remembered_spec = str(self.ytdlp_settings.get("auto_browser_spec", "")).strip()
        early_specs, late_specs = previous._candidate_groups(specs, remembered_spec)

        browser_spec = self._try_browser_specs(url, early_specs)
        if browser_spec is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_browser_auth(command, browser_spec))

        cookie_path = self._try_saved_cookie_file(url)
        if cookie_path is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_cookie_file(command, cookie_path))

        chromium_present = any(
            previous.previous._browser_from_spec(spec) in previous.CHROMIUM_BROWSERS for spec in specs
        )
        if chromium_present and os.name == "nt":
            bridge_path = self._try_chrome_bridge(url)
            if bridge_path is not None:
                return runtime_layer.App.run_ytdlp_command(self, self._with_cookie_file(command, bridge_path))

        browser_spec = self._try_browser_specs(url, late_specs)
        if browser_spec is not None:
            return runtime_layer.App.run_ytdlp_command(self, self._with_browser_auth(command, browser_spec))

        self._append_log(self.auto("auto_no_browser_required") + "\n")
        if self._bridge_setup_needed:
            raise core.AppError(self.bridge("bridge_setup_message"))
        raise core.AppError(self.rt("cookie_compact"))

    def _show_cookie_dialog(self) -> None:
        if str(self.ytdlp_settings.get("auth_mode", "auto")) != "auto" or not self._bridge_setup_needed:
            super()._show_cookie_dialog()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(self.bridge("bridge_setup_title"))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=self.bridge("bridge_setup_message"),
            wraplength=500,
            justify="left",
        ).pack(fill="x")

        status_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=status_var, wraplength=500, justify="left").pack(fill="x", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))

        def wait_until_idle(callback: object) -> None:
            if self.worker_thread and self.worker_thread.is_alive():
                self.root.after(100, lambda: wait_until_idle(callback))
                return
            callback()  # type: ignore[operator]

        def connect_chrome() -> None:
            ok, detail = chrome_bridge.register_native_host()
            if not ok:
                status_var.set(detail)
                return
            opened, open_detail = chrome_bridge.open_extension_setup()
            status_var.set(self.bridge("bridge_setup_opened") if opened else open_detail)

        def retry_download() -> None:
            if dialog.winfo_exists():
                dialog.destroy()
            self._bridge_setup_needed = False
            self.root.after(50, lambda: wait_until_idle(self.on_start))

        ttk.Button(buttons, text=self.rt("button_close"), command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text=self.auto("button_retry"), command=retry_download).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text=self.bridge("bridge_connect_button"), command=connect_chrome).pack(
            side="right", padx=(0, 8)
        )

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.focus_force()


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors = chrome_bridge.self_test()
    if chrome_bridge.EXTENSION_ID != "blibefgifoccgdhbhahjapmffhmamjma":
        errors.append("Chrome extension ID changed unexpectedly.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("CHROME BRIDGE AUTH SELF-TEST OK\n")
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
