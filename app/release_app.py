from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

import auth_policy as previous
import mini_url_converter as core


# TEMPORARILY DISABLED FOR THE CURRENT RELEASE.
# yt-dlp cannot currently decrypt cookies from modern Chromium profiles on this
# Windows/Chrome setup (DPAPI/App-Bound encryption). Keep the automatic auth
# implementation in the codebase so it can be restored when upstream support
# improves, but do not expose it in the Settings combobox for now.
#
# core.AUTH_MODE_CHOICES = ("auto", "browser", "file", "none")
# core.YTDLP_DEFAULTS["auth_mode"] = "auto"
core.AUTH_MODE_CHOICES = ("browser", "file", "none")
core.YTDLP_DEFAULTS["auth_mode"] = "none"
core.YTDLP_DEFAULTS["cookies_browser"] = "firefox"


class App(previous.App):
    pass


def self_test() -> int:
    # The existing automatic-auth self-tests intentionally expect auto mode to
    # be enabled. Run that chain under its original configuration, then restore
    # the release-facing configuration and verify that auto stays hidden.
    release_choices = core.AUTH_MODE_CHOICES
    release_default = core.YTDLP_DEFAULTS.get("auth_mode")
    release_browser = core.YTDLP_DEFAULTS.get("cookies_browser")
    try:
        core.AUTH_MODE_CHOICES = ("auto", "browser", "file", "none")
        core.YTDLP_DEFAULTS["auth_mode"] = "auto"
        core.YTDLP_DEFAULTS["cookies_browser"] = "chrome"
        if previous.self_test() != 0:
            return 1
    finally:
        core.AUTH_MODE_CHOICES = release_choices
        core.YTDLP_DEFAULTS["auth_mode"] = release_default
        core.YTDLP_DEFAULTS["cookies_browser"] = release_browser

    errors: list[str] = []
    if "auto" in core.AUTH_MODE_CHOICES:
        errors.append("Automatic authentication must be hidden in this release.")
    if core.YTDLP_DEFAULTS.get("auth_mode") != "none":
        errors.append("Release authentication default must be no authentication.")
    if core.YTDLP_DEFAULTS.get("cookies_browser") != "firefox":
        errors.append("Release browser default must be Firefox.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("RELEASE AUTH SELF-TEST OK\n")
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
