from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only helper
    winreg = None  # type: ignore[assignment]


APP_ID = "B56A8D1E-70F4-4FB5-9B4C-8F0BBCC4A1D3"
EXPECTED_TARGET_NAME = "YTDConverter.exe"
WAIT_TIMEOUT_SECONDS = 120
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def normalize_sha256(value: str) -> str:
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1].strip()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
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


def append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def show_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "YTD Converter Update", 0x10)
    except Exception:
        pass


def wait_for_process_exit(pid: int, timeout_seconds: int = WAIT_TIMEOUT_SECONDS) -> None:
    if pid <= 0:
        return
    if os.name != "nt":
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)
        raise TimeoutError(f"Timed out waiting for PID {pid} to exit.")

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = kernel32.WaitForSingleObject(handle, max(1, timeout_seconds) * 1000)
        if result == WAIT_TIMEOUT:
            raise TimeoutError(f"Timed out waiting for PID {pid} to exit.")
        if result != WAIT_OBJECT_0:
            raise OSError(f"WaitForSingleObject failed with result 0x{result:08X}.")
    finally:
        kernel32.CloseHandle(handle)


def safe_replace_executable(source: Path, target: Path, expected_sha256: str) -> None:
    expected = normalize_sha256(expected_sha256)
    if not expected:
        raise ValueError("A valid SHA-256 checksum is required for in-place updates.")
    if not source.is_file():
        raise FileNotFoundError(f"Downloaded update was not found: {source}")
    if not target.is_file():
        raise FileNotFoundError(f"Installed executable was not found: {target}")
    if target.name.lower() != EXPECTED_TARGET_NAME.lower():
        raise ValueError(f"Refusing to replace unexpected target: {target}")

    source_digest = sha256_file(source)
    if source_digest != expected:
        raise ValueError(f"Downloaded update checksum mismatch: expected {expected}, got {source_digest}.")

    staged = target.with_name(target.name + ".update-new")
    backup = target.with_name(target.name + ".update-old")

    for stale in (staged, backup):
        try:
            if stale.exists():
                stale.unlink()
        except OSError as exc:
            raise OSError(f"Could not remove stale updater file {stale}: {exc}") from exc

    shutil.copy2(source, staged)
    staged_digest = sha256_file(staged)
    if staged_digest != expected:
        try:
            staged.unlink()
        except OSError:
            pass
        raise ValueError(f"Staged update checksum mismatch: expected {expected}, got {staged_digest}.")

    moved_old = False
    try:
        os.replace(target, backup)
        moved_old = True
        os.replace(staged, target)
        installed_digest = sha256_file(target)
        if installed_digest != expected:
            raise ValueError(f"Installed update checksum mismatch: expected {expected}, got {installed_digest}.")
    except Exception:
        if moved_old:
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
            try:
                if backup.exists():
                    os.replace(backup, target)
            except OSError:
                pass
        try:
            if staged.exists():
                staged.unlink()
        except OSError:
            pass
        raise
    else:
        try:
            if backup.exists():
                backup.unlink()
        except OSError:
            # The update is already installed; leaving a backup is safer than
            # treating cleanup failure as an update failure.
            pass


def update_display_version(version: str, app_id: str = APP_ID) -> bool:
    if os.name != "nt" or winreg is None:
        return False
    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{app_id}}}_is1"
    access_base = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    views = [0]
    for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        flag = getattr(winreg, flag_name, 0)
        if flag and flag not in views:
            views.append(flag)

    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in views:
            try:
                with winreg.OpenKey(root, subkey, 0, access_base | view) as key:
                    winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
                    return True
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
            except OSError:
                continue
    return False


def run_elevated_and_wait(executable: Path, arguments: list[str], cwd: Path) -> int:
    if os.name != "nt":
        completed = subprocess.run([str(executable), *arguments], cwd=str(cwd), check=False)
        return int(completed.returncode)

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory = str(cwd)
    info.nShow = SW_SHOWNORMAL

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError()
    if not info.hProcess:
        raise OSError("Windows did not return a process handle for the elevated updater.")

    try:
        result = kernel32.WaitForSingleObject(info.hProcess, WAIT_TIMEOUT_SECONDS * 1000)
        if result == WAIT_TIMEOUT:
            raise TimeoutError("Timed out waiting for the elevated updater.")
        if result != WAIT_OBJECT_0:
            raise OSError(f"WaitForSingleObject failed with result 0x{result:08X}.")
        exit_code = wintypes.DWORD(1)
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError()
        return int(exit_code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


def restart_application(path: Path) -> None:
    flags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen(
        [str(path)],
        cwd=str(path.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags if os.name == "nt" else 0,
    )


def apply_update(source: Path, target: Path, expected_sha256: str, version: str, log_path: Path) -> int:
    try:
        append_log(log_path, f"Applying update {version}: {source} -> {target}")
        safe_replace_executable(source, target, expected_sha256)
        if update_display_version(version):
            append_log(log_path, f"Updated Windows Installed Apps DisplayVersion to {version}.")
        else:
            append_log(log_path, "Installed Apps registry entry was not found; executable update still succeeded.")
        append_log(log_path, "Executable replacement completed successfully.")
        return 0
    except Exception as exc:
        append_log(log_path, f"Elevated apply failed: {exc}")
        append_log(log_path, traceback.format_exc().rstrip())
        return 1


def orchestrate_update(
    pid: int,
    source: Path,
    target: Path,
    restart: Path,
    expected_sha256: str,
    version: str,
    log_path: Path,
) -> int:
    try:
        expected = normalize_sha256(expected_sha256)
        if not expected:
            raise ValueError("A valid SHA-256 checksum is required.")
        if sha256_file(source) != expected:
            raise ValueError("Downloaded update checksum mismatch before updater launch.")

        append_log(log_path, f"Updater started for version {version}; waiting for PID {pid}.")
        wait_for_process_exit(pid)
        append_log(log_path, "Main application exited; requesting elevation for replacement.")

        apply_args = [
            "--apply",
            "--source",
            str(source),
            "--target",
            str(target),
            "--sha256",
            expected,
            "--version",
            version,
            "--log",
            str(log_path),
        ]
        exit_code = run_elevated_and_wait(Path(sys.executable), apply_args, Path(sys.executable).parent)
        if exit_code != 0:
            raise RuntimeError(f"Elevated updater exited with code {exit_code}.")

        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass
        append_log(log_path, "Update succeeded; restarting YTD Converter.")
        restart_application(restart)
        return 0
    except Exception as exc:
        append_log(log_path, f"Update orchestration failed: {exc}")
        append_log(log_path, traceback.format_exc().rstrip())
        try:
            if restart.is_file():
                append_log(log_path, "Restarting the existing application after update failure.")
                restart_application(restart)
        except Exception as restart_exc:
            append_log(log_path, f"Failed to restart existing application: {restart_exc}")
        show_error(f"Не удалось обновить YTD Converter.\n\n{exc}\n\nЛог:\n{log_path}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YTD Converter in-place updater")
    parser.add_argument("--apply", action="store_true", help="Run the elevated replacement phase.")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--restart", type=Path)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def self_test() -> int:
    errors: list[str] = []
    if normalize_sha256("sha256:" + "a" * 64) != "a" * 64:
        errors.append("SHA-256 normalization failed.")
    if normalize_sha256("not-a-digest"):
        errors.append("Invalid SHA-256 value was accepted.")

    try:
        with tempfile.TemporaryDirectory(prefix="ytd-updater-test-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            source = temp_dir / "download.exe"
            target = temp_dir / EXPECTED_TARGET_NAME
            source.write_bytes(b"new executable contents")
            target.write_bytes(b"old executable contents")
            expected = sha256_file(source)
            safe_replace_executable(source, target, expected)
            if target.read_bytes() != b"new executable contents":
                errors.append("Safe replacement did not install the new executable.")
            if target.with_name(target.name + ".update-old").exists():
                errors.append("Updater backup was not cleaned after successful replacement.")

            bad_target = temp_dir / EXPECTED_TARGET_NAME
            bad_target.write_bytes(b"known-good-old")
            try:
                safe_replace_executable(source, bad_target, "0" * 64)
            except ValueError:
                pass
            else:
                errors.append("Checksum mismatch did not fail closed.")
            if bad_target.read_bytes() != b"known-good-old":
                errors.append("Checksum failure modified the existing executable.")
    except Exception as exc:
        errors.append(f"Updater safe-replacement self-test failed: {exc}")

    if errors:
        try:
            Path(tempfile.gettempdir(), "ytd-updater-self-test-error.txt").write_text("\n".join(errors), encoding="utf-8")
        except OSError:
            pass
        return 1
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    if args.source is None or args.target is None or args.log is None or not args.version:
        parser.error("--source, --target, --log and --version are required.")

    source = args.source.expanduser().resolve(strict=False)
    target = args.target.expanduser().resolve(strict=False)
    log_path = args.log.expanduser().resolve(strict=False)

    if args.apply:
        return apply_update(source, target, args.sha256, args.version, log_path)

    if args.restart is None or args.pid <= 0:
        parser.error("--pid and --restart are required for the orchestration phase.")
    restart = args.restart.expanduser().resolve(strict=False)
    return orchestrate_update(args.pid, source, target, restart, args.sha256, args.version, log_path)


if __name__ == "__main__":
    raise SystemExit(main())
