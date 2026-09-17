from __future__ import annotations

import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import launcher as launcher_layer
import mini_url_converter as core
import mp3_progress as previous


launcher_layer.EXTRA_TRANSLATIONS["en"]["update_app_launching"] = "Opening the update installer..."
launcher_layer.EXTRA_TRANSLATIONS["ru"]["update_app_launching"] = "Запуск установщика обновления..."


def _installer_arguments(log_path: Path) -> str:
    return f'/CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /LOG="{log_path}"'


class App(previous.App):
    def _launch_update_after_exit(self, installer: Path) -> None:
        """Launch Inno Setup directly through ShellExecute and then close the app.

        The previous implementation started a hidden detached PowerShell process,
        waited for the current PID to disappear, and only then called Start-Process.
        On some Windows systems that helper vanished with the parent application,
        leaving a downloaded installer but no visible update.  ShellExecute via
        os.startfile is the native Windows path for launching an elevated setup
        executable and does not depend on a helper process surviving our exit.
        """
        if not installer.is_file():
            messagebox.showerror(
                self.ext("update_check_title"),
                f"Installer not found:\n{installer}",
                parent=self.root,
            )
            return

        try:
            launcher_layer.UPDATES_DIR.mkdir(parents=True, exist_ok=True)
            log_path = launcher_layer.UPDATES_DIR / "installer-update.log"
            arguments = _installer_arguments(log_path)
            self._append_log(f"Updater: launching installer: {installer}\n")
            self._append_log(f"Updater: installer log: {log_path}\n")
            os.startfile(
                str(installer),
                "runas",
                arguments=arguments,
                cwd=str(installer.parent),
                show_cmd=1,
            )
        except Exception as exc:
            self._append_log(f"Updater: failed to launch installer: {exc}\n")
            messagebox.showerror(
                self.ext("update_check_title"),
                f"Не удалось запустить установщик обновления.\n\n{exc}\n\nФайл:\n{installer}",
                parent=self.root,
            )
            return

        self.closing = True
        # Give ShellExecute/UAC a moment to own the installer before the PyInstaller
        # process exits and releases the installed executable.
        self.root.after(400, self.root.destroy)


def self_test() -> int:
    if previous.self_test() != 0:
        return 1

    errors: list[str] = []
    sample = Path(r"C:\Users\test user\AppData\Local\YTD Converter\updates\installer-update.log")
    arguments = _installer_arguments(sample)
    if "/CLOSEAPPLICATIONS" not in arguments:
        errors.append("Updater launch arguments must close running application files.")
    if "/RESTARTAPPLICATIONS" not in arguments:
        errors.append("Updater launch arguments must allow application restart.")
    if f'/LOG="{sample}"' not in arguments:
        errors.append("Updater launch arguments must include a persistent installer log.")

    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("SELF-UPDATE SELF-TEST OK\n")
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
