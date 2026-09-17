from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk

import launcher as launcher_layer
import mini_url_converter as core
import self_update as previous


UPDATER_EXE_NAME = "YTDUpdater.exe"
INPLACE_UPDATE_LOG_NAME = "inplace-update.log"

launcher_layer.EXTRA_TRANSLATIONS["en"]["update_app_launching"] = "Applying application update..."
launcher_layer.EXTRA_TRANSLATIONS["ru"]["update_app_launching"] = "Применение обновления приложения..."


def normalize_release_digest(value: str) -> str:
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return ""
    return digest


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _asset_details(payload: dict[str, object], version: str) -> dict[str, str]:
    result = {
        "portable_url": "",
        "portable_sha256": "",
        "installer_url": "",
    }
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return result

    portable_name = f"YTDConverter-{version}.exe".lower()
    installer_names = (
        f"YTDConverterSetup-{version}.exe".lower(),
        f"MiniURLConverterSetup-{version}.exe".lower(),
    )

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "")).strip()
        url = str(asset.get("browser_download_url", "")).strip()
        if name.lower() == portable_name and url:
            result["portable_url"] = url
            result["portable_sha256"] = normalize_release_digest(str(asset.get("digest", "")))
            break

    for preferred in installer_names:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            url = str(asset.get("browser_download_url", "")).strip()
            if name.lower() == preferred and url:
                result["installer_url"] = url
                return result

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "")).lower()
        url = str(asset.get("browser_download_url", "")).strip()
        if name.endswith("setup.exe") and url:
            result["installer_url"] = url
            break
    return result


def build_updater_arguments(
    *,
    pid: int,
    source: Path,
    target: Path,
    expected_sha256: str,
    version: str,
    log_path: Path,
) -> list[str]:
    return [
        "--pid",
        str(pid),
        "--source",
        str(source),
        "--target",
        str(target),
        "--restart",
        str(target),
        "--sha256",
        expected_sha256,
        "--version",
        version,
        "--log",
        str(log_path),
    ]


class App(previous.App):
    def fetch_latest_app_release(self) -> dict[str, str]:
        payload = self.fetch_json(launcher_layer.APP_RELEASE_API, timeout_seconds=core.NETWORK_TIMEOUT_SECONDS)
        tag = payload.get("tag_name")
        if not isinstance(tag, str) or not tag.strip():
            raise core.AppError("GitHub API did not return an application release tag.")
        version = launcher_layer.normalize_version(tag)
        details = _asset_details(payload, version)
        return {
            "version": version,
            "portable_url": details["portable_url"],
            "portable_sha256": details["portable_sha256"],
            "installer_url": details["installer_url"],
            "html_url": str(payload.get("html_url", launcher_layer.APP_RELEASE_PAGE)),
        }

    def _release_for_update(self, latest: str) -> dict[str, str]:
        release = self.last_app_release
        if release and release.get("version") == latest:
            return release
        release = self.fetch_latest_app_release()
        self.last_app_release = release
        return release

    def _updater_path(self) -> Path:
        return Path(sys.executable).resolve(strict=False).with_name(UPDATER_EXE_NAME)

    def _download_verified_portable(self, release: dict[str, str], latest: str) -> tuple[Path, str]:
        portable_url = str(release.get("portable_url", "")).strip()
        expected = normalize_release_digest(str(release.get("portable_sha256", "")))
        if not portable_url:
            raise core.AppError("The latest GitHub Release does not contain a YTDConverter portable asset.")
        if not expected:
            raise core.AppError("The latest portable release asset does not provide a valid SHA-256 digest.")

        launcher_layer.UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        final_path = launcher_layer.UPDATES_DIR / f"YTDConverter-{latest}.exe"
        partial_path = final_path.with_suffix(final_path.suffix + ".download")
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass

        self.download_file(portable_url, partial_path, self.ext("update_app_downloading"))
        actual = sha256_file(partial_path)
        if actual != expected:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise core.AppError(f"Application update checksum mismatch: expected {expected}, got {actual}.")
        os.replace(partial_path, final_path)
        self._append_log(f"Updater: verified SHA-256 {actual}\n")
        return final_path, expected

    def _launch_inplace_updater(self, package: Path, expected_sha256: str, latest: str) -> None:
        updater = self._updater_path()
        target = Path(sys.executable).resolve(strict=False)
        if not updater.is_file():
            messagebox.showerror(
                self.ext("update_check_title"),
                f"Updater not found:\n{updater}",
                parent=self.root,
            )
            return
        if not package.is_file():
            messagebox.showerror(
                self.ext("update_check_title"),
                f"Downloaded update not found:\n{package}",
                parent=self.root,
            )
            return

        log_path = launcher_layer.UPDATES_DIR / INPLACE_UPDATE_LOG_NAME
        arguments = build_updater_arguments(
            pid=os.getpid(),
            source=package,
            target=target,
            expected_sha256=expected_sha256,
            version=latest,
            log_path=log_path,
        )
        flags = core.CREATE_NO_WINDOW | core.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        try:
            self._append_log(f"Updater: launching helper: {updater}\n")
            self._append_log(f"Updater: persistent log: {log_path}\n")
            subprocess.Popen(
                [str(updater), *arguments],
                cwd=str(updater.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
            )
        except Exception as exc:
            self._append_log(f"Updater: failed to launch helper: {exc}\n")
            messagebox.showerror(
                self.ext("update_check_title"),
                f"Не удалось запустить модуль обновления.\n\n{exc}\n\nФайл:\n{updater}",
                parent=self.root,
            )
            return

        self.closing = True
        self.root.after(300, self.root.destroy)

    def run_update_job(self) -> None:
        app_package: Path | None = None
        app_package_sha256 = ""
        app_latest = ""
        app_installer: Path | None = None
        try:
            self.ensure_environment()
            pending = [key for key, item in self.last_update_plan.items() if bool(item.get("update"))]
            total_items = max(1, len(pending))
            completed = 0

            if "yt-dlp" in pending:
                self._set_status("status_updating_ytdlp")
                with tempfile.TemporaryDirectory(prefix="ytd-converter-") as temp_dir_text:
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
                    app_latest = str(item.get("latest", "")).strip()
                    release = self._release_for_update(app_latest)
                    updater = self._updater_path()
                    portable_url = str(release.get("portable_url", "")).strip()
                    portable_sha256 = normalize_release_digest(str(release.get("portable_sha256", "")))

                    if updater.is_file() and portable_url and portable_sha256:
                        self._set_status("status_updating")
                        app_package, app_package_sha256 = self._download_verified_portable(release, app_latest)
                        self._append_log("Updater: in-place update package is ready.\n")
                    else:
                        reasons: list[str] = []
                        if not updater.is_file():
                            reasons.append("YTDUpdater.exe is not installed")
                        if not portable_url:
                            reasons.append("portable release asset is missing")
                        if not portable_sha256:
                            reasons.append("portable SHA-256 digest is missing")
                        reason_text = ", ".join(reasons) or "in-place prerequisites are unavailable"
                        self._append_log(f"Updater: {reason_text}; using installer fallback.\n")
                        installer_url = str(release.get("installer_url", "")).strip()
                        if not installer_url:
                            raise core.AppError("The latest GitHub Release contains neither a safe in-place package nor an installer fallback.")
                        launcher_layer.UPDATES_DIR.mkdir(parents=True, exist_ok=True)
                        app_installer = launcher_layer.UPDATES_DIR / f"YTDConverterSetup-{app_latest}.exe"
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

            if app_package is not None:
                self._append_log(self.ext("update_app_launching") + "\n")
                self._schedule(self._launch_inplace_updater, app_package, app_package_sha256, app_latest)
            elif app_installer is not None:
                self._append_log("Updater: launching installer fallback.\n")
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


def self_test() -> int:
    if previous.self_test() != 0:
        return 1

    errors: list[str] = []
    digest = "a" * 64
    if normalize_release_digest("sha256:" + digest) != digest:
        errors.append("Release digest normalization failed.")
    if normalize_release_digest("invalid"):
        errors.append("Invalid release digest was accepted.")

    payload: dict[str, object] = {
        "assets": [
            {
                "name": "YTDConverter-9.9.9.exe",
                "browser_download_url": "https://example.invalid/YTDConverter-9.9.9.exe",
                "digest": "sha256:" + digest,
            },
            {
                "name": "YTDConverterSetup-9.9.9.exe",
                "browser_download_url": "https://example.invalid/YTDConverterSetup-9.9.9.exe",
            },
        ]
    }
    details = _asset_details(payload, "9.9.9")
    if not details["portable_url"] or details["portable_sha256"] != digest:
        errors.append("Portable release asset discovery failed.")
    if not details["installer_url"].endswith("YTDConverterSetup-9.9.9.exe"):
        errors.append("Installer fallback discovery failed.")

    args = build_updater_arguments(
        pid=1234,
        source=Path(r"C:\Users\test\update.exe"),
        target=Path(r"C:\Program Files\YTD Converter\YTDConverter.exe"),
        expected_sha256=digest,
        version="9.9.9",
        log_path=Path(r"C:\Users\test\update.log"),
    )
    for required in ("--pid", "--source", "--target", "--restart", "--sha256", "--version", "--log"):
        if required not in args:
            errors.append(f"Updater argument construction is missing {required}.")

    try:
        with tempfile.TemporaryDirectory(prefix="ytd-inplace-self-test-") as temp_dir_text:
            sample = Path(temp_dir_text) / "sample.exe"
            sample.write_bytes(b"checksum-test")
            expected = hashlib.sha256(b"checksum-test").hexdigest()
            if sha256_file(sample) != expected:
                errors.append("SHA-256 file verification failed.")
    except Exception as exc:
        errors.append(f"In-place checksum self-test failed: {exc}")

    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("IN-PLACE UPDATE SELF-TEST OK\n")
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
