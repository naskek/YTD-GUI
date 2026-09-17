from __future__ import annotations

import ctypes
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

APP_TITLE = "Mini URL Converter"
DEV_PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_INSTALL_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else DEV_PROJECT_ROOT
PROJECT_ROOT = APP_INSTALL_DIR

# Store writable data in user space so the app can update itself/tools without re-running setup.
# For smoke-tests and portable scenarios, allow overriding via env var.
_DATA_DIR_OVERRIDE = os.environ.get("MINI_URL_CONVERTER_DATA_DIR")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")
if _DATA_DIR_OVERRIDE:
    APP_DATA_DIR = Path(_DATA_DIR_OVERRIDE).expanduser()
else:
    APP_DATA_DIR = (Path(_LOCALAPPDATA) if _LOCALAPPDATA else (Path.home() / "AppData" / "Local")) / "Mini URL Converter"
TOOLS_DIR = APP_DATA_DIR / "tools"
YT_DLP_PATH = TOOLS_DIR / "yt-dlp.exe"
FFMPEG_PATH = TOOLS_DIR / "ffmpeg.exe"
FFPROBE_PATH = TOOLS_DIR / "ffprobe.exe"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads" / "Mini URL Converter"

# Back-compat: older builds wrote settings next to the executable.
LEGACY_SETTINGS_FILE = APP_INSTALL_DIR / ".mini_url_converter.settings.json"
SETTINGS_FILE = APP_DATA_DIR / "mini_url_converter.settings.json"
RECENT_LOG_LIMIT = 20
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
MAX_URL_TEXT_LENGTH = 4096
NETWORK_TIMEOUT_SECONDS = 120
LATEST_VERSION_TIMEOUT_SECONDS = 5
DOWNLOAD_CHUNK_SIZE = 1024 * 256
URL_ANALYSIS_TIMEOUT_SECONDS = 20
AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
YTDLP_LATEST_RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_LATEST_RELEASE_PAGE = "https://github.com/yt-dlp/yt-dlp/releases/latest"
YTDLP_WINDOWS_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_WINDOWS_BUILD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
# MP4 is downloaded directly as H.264/AVC + AAC whenever YouTube offers it.
# Do not pass codec arguments through the generic ``ffmpeg:`` postprocessor
# prefix: that prefix also applies to the Merger and turns a fast stream-copy
# merge into a full CPU re-encode with no visible ffmpeg progress in the GUI.
MP4_FORMAT_SELECTORS = {
    "best": (
        "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/"
        "b[vcodec^=avc1][acodec^=mp4a]/b[ext=mp4]/b"
    ),
    "1080p": (
        "bv*[height<=?1080][vcodec^=avc1]+ba[acodec^=mp4a]/"
        "b[height<=?1080][vcodec^=avc1][acodec^=mp4a]/b[height<=?1080][ext=mp4]/b[height<=?1080]"
    ),
    "720p": (
        "bv*[height<=?720][vcodec^=avc1]+ba[acodec^=mp4a]/"
        "b[height<=?720][vcodec^=avc1][acodec^=mp4a]/b[height<=?720][ext=mp4]/b[height<=?720]"
    ),
    "480p": (
        "bv*[height<=?480][vcodec^=avc1]+ba[acodec^=mp4a]/"
        "b[height<=?480][vcodec^=avc1][acodec^=mp4a]/b[height<=?480][ext=mp4]/b[height<=?480]"
    ),
}
MP3_AUDIO_QUALITY = "192K"
LEGACY_OUTPUT_TEMPLATE = "%(title)s.%(ext)s"
FORMAT_PRESET_CHOICES = ("best", "1080p", "720p", "480p")
OUTPUT_MODE_CHOICES = ("mp4", "mkv", "original", "mp3")
FORMAT_SELECTORS = {
    "best": "bv*+ba/b",
    "1080p": "bv*[height<=?1080]+ba/b[height<=?1080]",
    "720p": "bv*[height<=?720]+ba/b[height<=?720]",
    "480p": "bv*[height<=?480]+ba/b[height<=?480]",
}
YTDLP_DEFAULTS: dict[str, object] = {
    "format_preset": "best",
    "output_mode": "mp4",
    "output_template": "%(title)s_%(id)s.%(ext)s",
    "retries": 3,
    "retry_sleep": "2",
    "restrict_filenames": True,
    "windows_filenames": True,
    "auth_mode": "none",
    "cookies_browser": "firefox",
    "cookies_file": "",
}
AUTH_MODE_CHOICES = ("none", "browser", "file")
COOKIE_BROWSER_CHOICES = (
    "firefox",
    "chrome",
    "edge",
    "brave",
    "opera",
    "vivaldi",
    "chromium",
)

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)
DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(?P<path>.+)$", re.IGNORECASE)
MERGE_RE = re.compile(r"\[(?:Merger|ffmpeg)\].*?into\s+\"?(?P<path>.+?)\"?$", re.IGNORECASE)
RECODE_RE = re.compile(r"\[(?:VideoConvertor|ffmpeg)\].*?\"(?P<path>.+?)\"", re.IGNORECASE)
ALREADY_RE = re.compile(r"\[download\]\s+(?P<path>.+?)\s+has already been downloaded", re.IGNORECASE)
FINAL_PATH_RE = re.compile(r"^__MUC_OUTPUT__:(?P<path>.+)$")
URL_TEXT_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)

# YouTube authentication errors recognised in the full yt-dlp output (matched as
# lowercase substrings). Both the straight and curly apostrophe variants are listed.
AUTH_REQUIRED_PATTERNS = (
    "sign in to confirm your age",
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "use --cookies-from-browser or --cookies",
    "this video is age-restricted",
)
# Typical failures while reading cookies from a browser.
BROWSER_COOKIE_PATTERNS = (
    "could not copy",
    "cookie database",
    "failed to decrypt with dpapi",
    "permission denied",
    "unsupported browser specified for cookies",
    "could not find",
    "cookies database",
    "failed to load cookies",
)


class AppError(Exception):
    pass


class JobCancelledError(AppError):
    pass


class CommandExecutionError(AppError):
    """Carries the full process output so error handlers can inspect it."""

    def __init__(self, message: str, exit_code: int, output_lines: list[str]) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.output_lines = list(output_lines)


TRANSLATIONS = {
    "en": {
        "app_title": "Mini URL Converter",
        "label_url": "URL",
        "label_language": "Language",
        "label_save_folder": "Save folder",
        "button_paste": "Paste",
        "button_choose_folder": "Choose folder",
        "button_start": "Start",
        "button_cancel_job": "Cancel",
        "button_check_versions": "Check for updates",
        "button_update": "Update",
        "button_settings": "Settings",
        "button_open_downloads": "Open downloads",
        "button_copy_log": "Copy log",
        "button_clear_log": "Clear log",
        "group_progress": "Progress",
        "group_log": "Log",
        "label_total_progress": "Total",
        "label_task_progress": "Current task",
        "menu_copy": "Copy",
        "menu_copy_all": "Copy all",
        "menu_clear_log": "Clear log",
        "footer_text": "Project directory: {project_dir}\nTools directory: {tools_dir}\nSettings file: {settings_file}",
        "status_idle": "Idle",
        "status_preparing": "Preparing...",
        "status_preparing_versions": "Preparing version check...",
        "status_preparing_update": "Preparing update...",
        "status_checking_versions": "Checking versions...",
        "status_checking_latest_version": "Checking latest yt-dlp release...",
        "status_log_copied": "Log copied",
        "status_save_folder_updated": "Save folder updated",
        "status_settings_save_failed": "Settings save failed",
        "status_language_updated": "Language updated",
        "status_settings_updated": "Settings updated",
        "status_running_ytdlp": "Running yt-dlp...",
        "status_completed": "Completed",
        "status_cancelling": "Cancelling...",
        "status_cancelled": "Cancelled",
        "status_error": "Error",
        "status_updating": "Updating...",
        "status_updating_ytdlp": "Updating yt-dlp...",
        "status_ytdlp_updated": "yt-dlp updated",
        "status_update_complete": "Update complete",
        "status_checking_version": "Checking yt-dlp version...",
        "status_already_up_to_date": "Already up to date",
        "status_update_failed": "Update failed",
        "status_downloading": "Downloading...",
        "status_writing_file": "Writing file...",
        "status_merging_streams": "Merging streams...",
        "status_converting_mp4": "Converting to MP4...",
        "status_already_downloaded": "Already downloaded",
        "status_cleaning_up": "Cleaning up...",
        "status_ytdlp_version": "yt-dlp version: {version}",
        "warning_enter_url": "Enter a URL first.",
        "popup_url_too_long": "Text is too long to paste into the URL field.",
        "popup_invalid_url": "URL format is invalid.",
        "info_job_running": "A job is already running.",
        "info_already_up_to_date": "yt-dlp is already up to date. Update was skipped.",
        "ask_update_now": "Update available.\n\nCurrent yt-dlp: {current}\nLatest yt-dlp: {latest}\n\nUpdate now?",
        "ask_close_running": "A job is still running. Close the application and stop the current process?",
        "dialog_choose_folder": "Choose folder",
        "dialog_settings_title": "yt-dlp settings",
        "info_completed_output": "Completed.\n\nOutput:\n{path}",
        "error_failed_open_downloads": "Failed to open downloads folder.\n\n{error}",
        "error_failed_create_save_folder": "Failed to create save folder.\n\n{error}",
        "error_failed_save_settings": "Failed to save settings.\n\n{error}",
        "error_failed_copy_log": "Failed to copy log.\n\n{error}",
        "log_warning_failed_load_settings": "Failed to load settings from {settings_file}. Using defaults. {error}",
        "log_warning_settings_not_object": "Settings file {settings_file} does not contain a JSON object. Using defaults.",
        "log_warning_settings_invalid_download_dir": "Settings file {settings_file} has an invalid download_dir value. Using default save folder.",
        "log_warning_settings_invalid_language": "Settings file {settings_file} has an invalid language value. Using system language.",
        "log_warning_failed_save_settings": "WARNING: Failed to save settings: {error}",
        "log_settings_updated": "yt-dlp settings updated.",
        "log_save_folder": "Save folder: {path}",
        "log_url": "URL: {url}",
        "log_updating_ytdlp": "Updating yt-dlp binary: {path}",
        "log_binary_path": "{label}: {path}",
        "log_update_started": "Update started.",
        "log_update_complete": "Update complete.",
        "log_update_skipped_up_to_date": "Update skipped: yt-dlp is already up to date.",
        "log_no_update_needed": "Version is up to date, no update needed.",
        "log_update_cancelled": "Update cancelled by user.",
        "log_cancel_requested": "Cancel requested. Stopping current process...",
        "log_download_cancelled": "Download cancelled by user.",
        "log_cancel_removed_file": "Removed file: {path}",
        "log_cancel_no_files": "No downloaded files were found to clean up.",
        "log_cancel_cleanup_failed": "WARNING: Failed to remove {path}: {error}",
        "log_actual_output_size": "Output file size: {size_mb} MB",
        "log_estimated_output_size": "Estimated output size: {size_mb} MB",
        "log_failed_estimate_output_size": "Could not estimate output size: {error}",
        "log_checking_latest_version": "yt-dlp: checking latest release...",
        "log_latest_ytdlp_version": "yt-dlp: latest release: {version}",
        "log_ytdlp_up_to_date": "yt-dlp: up to date",
        "log_ytdlp_update_available": "yt-dlp: update available ({version})",
        "log_latest_version_api_timeout_fallback": "yt-dlp: GitHub API timed out, trying releases page...",
        "log_latest_version_check_skipped": "yt-dlp: latest version check skipped: {error}",
        "log_error": "ERROR: {error}",
        "error_project_root_missing": "Project directory does not exist:\n{path}",
        "error_project_root_not_folder": "Project directory is not a folder:\n{path}",
        "error_tools_dir_missing": "Tools directory does not exist:\n{path}",
        "error_tools_dir_not_folder": "Tools directory is not a folder:\n{path}",
        "error_create_downloads_folder": "Failed to create downloads folder:\n{path}\n\n{error}",
        "error_required_binary_missing": "{label} was not found:\n{path}",
        "error_required_binary_not_file": "{label} is not a file:\n{path}",
        "error_failed_start_command": "Failed to start {label}.\n\n{error}",
        "error_command_exit_code": "{label} exited with code {code}.",
        "error_invalid_integer": "{name} must be a non-negative integer.",
        "error_invalid_number": "{name} must be a non-negative number.",
        "error_output_template_empty": "Output template cannot be empty.",
        "error_last_log_lines": "{summary}\n\nLast {count} log lines:\n{lines}",
        "label_format_preset": "Format preset",
        "label_output_mode": "Output mode",
        "label_output_template": "Output template",
        "label_retries": "Retries",
        "label_retry_sleep": "Retry sleep (s)",
        "label_restrict_filenames": "Restrict filenames",
        "label_windows_filenames": "Windows filenames",
        "button_save": "Save",
        "button_cancel": "Cancel",
        "button_reset_defaults": "Reset defaults",
        "option_format_best": "Best available",
        "option_format_1080p": "Up to 1080p",
        "option_format_720p": "Up to 720p",
        "option_format_480p": "Up to 480p",
        "option_output_mp4": "Compatible MP4",
        "option_output_mkv": "MKV",
        "option_output_original": "Keep original",
        "option_output_mp3": "MP3 audio only",
        "label_youtube_auth": "YouTube authentication",
        "label_auth_mode": "Authentication method",
        "label_cookies_browser": "Browser",
        "label_cookies_file": "cookies.txt file",
        "button_select_cookies_file": "Select file...",
        "option_auth_none": "No authentication",
        "option_auth_browser": "Cookies from a browser",
        "option_auth_file": "cookies.txt file",
        "option_browser_firefox": "Firefox",
        "option_browser_chrome": "Chrome",
        "option_browser_edge": "Microsoft Edge",
        "option_browser_brave": "Brave",
        "option_browser_opera": "Opera",
        "option_browser_vivaldi": "Vivaldi",
        "option_browser_chromium": "Chromium",
        "dialog_cookies_filter": "Cookies (*.txt)",
        "dialog_all_files_filter": "All files (*.*)",
        "dialog_select_cookies_file": "Select cookies.txt file",
        "error_cookies_file_empty": "Select a cookies.txt file path.",
        "error_cookies_file_missing": "The cookies.txt file was not found:\n{path}",
        "error_youtube_auth_required": (
            "YouTube requires authentication.\n\n"
            "Open Settings and select cookies from a browser\n"
            "or a cookies.txt file.\n\n"
            "The selected YouTube account must have age verification."
        ),
        "error_browser_cookies_failed": (
            "Could not read cookies from the selected browser.\n\n"
            "Close the browser and try again.\n"
            "If the error persists, select another browser\n"
            "or use a cookies.txt file."
        ),
    },
    "ru": {
        "app_title": "Мини конвертер URL",
        "label_url": "Ссылка",
        "label_language": "Язык",
        "label_save_folder": "Папка сохранения",
        "button_paste": "Вставить",
        "button_choose_folder": "Выбрать папку",
        "button_start": "Старт",
        "button_cancel_job": "Отмена",
        "button_check_versions": "Проверить обновления",
        "button_update": "Обновить",
        "button_settings": "Настройки",
        "button_open_downloads": "Открыть папку",
        "button_copy_log": "Копировать лог",
        "button_clear_log": "Очистить лог",
        "group_progress": "Прогресс",
        "group_log": "Лог",
        "label_total_progress": "Общий прогресс",
        "label_task_progress": "Текущая задача",
        "menu_copy": "Копировать",
        "menu_copy_all": "Копировать всё",
        "menu_clear_log": "Очистить лог",
        "footer_text": "Папка проекта: {project_dir}\nПапка tools: {tools_dir}\nФайл настроек: {settings_file}",
        "status_idle": "Готово",
        "status_preparing": "Подготовка...",
        "status_preparing_versions": "Подготовка проверки версий...",
        "status_preparing_update": "Подготовка обновления...",
        "status_checking_versions": "Проверяю версии...",
        "status_checking_latest_version": "Проверяю последний релиз yt-dlp...",
        "status_log_copied": "Лог скопирован",
        "status_save_folder_updated": "Папка сохранения обновлена",
        "status_settings_save_failed": "Не удалось сохранить настройки",
        "status_language_updated": "Язык обновлён",
        "status_settings_updated": "Настройки обновлены",
        "status_running_ytdlp": "Запускаю yt-dlp...",
        "status_completed": "Готово",
        "status_cancelling": "Отмена...",
        "status_cancelled": "Отменено",
        "status_error": "Ошибка",
        "status_updating": "Обновляю...",
        "status_updating_ytdlp": "Обновляю yt-dlp...",
        "status_ytdlp_updated": "yt-dlp обновлён",
        "status_update_complete": "Обновление завершено",
        "status_checking_version": "Проверяю версию yt-dlp...",
        "status_already_up_to_date": "Уже актуально",
        "status_update_failed": "Ошибка обновления",
        "status_downloading": "Идёт загрузка...",
        "status_writing_file": "Записываю файл...",
        "status_merging_streams": "Объединяю дорожки...",
        "status_converting_mp4": "Конвертирую в MP4...",
        "status_already_downloaded": "Уже скачано",
        "status_cleaning_up": "Очистка...",
        "status_ytdlp_version": "Версия yt-dlp: {version}",
        "warning_enter_url": "Сначала вставьте ссылку.",
        "popup_url_too_long": "Слишком длинный текст для поля ссылки.",
        "popup_invalid_url": "Некорректный формат ссылки.",
        "info_job_running": "Сейчас уже выполняется задача.",
        "info_already_up_to_date": "yt-dlp уже актуален. Обновление пропущено.",
        "ask_update_now": "Доступно обновление.\n\nТекущий yt-dlp: {current}\nПоследний yt-dlp: {latest}\n\nОбновить сейчас?",
        "ask_close_running": "Сейчас выполняется задача. Закрыть приложение и остановить текущий процесс?",
        "dialog_choose_folder": "Выберите папку",
        "dialog_settings_title": "Настройки yt-dlp",
        "info_completed_output": "Готово.\n\nРезультат:\n{path}",
        "error_failed_open_downloads": "Не удалось открыть папку сохранения.\n\n{error}",
        "error_failed_create_save_folder": "Не удалось создать папку сохранения.\n\n{error}",
        "error_failed_save_settings": "Не удалось сохранить настройки.\n\n{error}",
        "error_failed_copy_log": "Не удалось скопировать лог.\n\n{error}",
        "log_warning_failed_load_settings": "Не удалось загрузить настройки из {settings_file}. Используются значения по умолчанию. {error}",
        "log_warning_settings_not_object": "Файл настроек {settings_file} не содержит JSON-объект. Используются значения по умолчанию.",
        "log_warning_settings_invalid_download_dir": "В файле настроек {settings_file} некорректное значение download_dir. Используется папка по умолчанию.",
        "log_warning_settings_invalid_language": "В файле настроек {settings_file} некорректное значение language. Используется язык системы.",
        "log_warning_failed_save_settings": "ПРЕДУПРЕЖДЕНИЕ: не удалось сохранить настройки: {error}",
        "log_settings_updated": "Настройки yt-dlp обновлены.",
        "log_save_folder": "Папка сохранения: {path}",
        "log_url": "Ссылка: {url}",
        "log_updating_ytdlp": "Обновляю бинарник yt-dlp: {path}",
        "log_binary_path": "{label}: {path}",
        "log_update_started": "Обновление запущено.",
        "log_update_complete": "Обновление завершено.",
        "log_update_skipped_up_to_date": "Обновление пропущено: yt-dlp уже актуален.",
        "log_no_update_needed": "Версия актуальная, обновление не требуется.",
        "log_update_cancelled": "Обновление отменено пользователем.",
        "log_cancel_requested": "Запрошена отмена. Останавливаю текущий процесс...",
        "log_download_cancelled": "Загрузка отменена пользователем.",
        "log_cancel_removed_file": "Удалён файл: {path}",
        "log_cancel_no_files": "Удалять нечего, файлов текущей загрузки не найдено.",
        "log_cancel_cleanup_failed": "ПРЕДУПРЕЖДЕНИЕ: не удалось удалить {path}: {error}",
        "log_actual_output_size": "Размер выходного файла: {size_mb} МБ",
        "log_estimated_output_size": "Примерный размер выходного файла: {size_mb} МБ",
        "log_failed_estimate_output_size": "Не удалось определить размер выходного файла: {error}",
        "log_checking_latest_version": "yt-dlp: проверяю последний релиз...",
        "log_latest_ytdlp_version": "yt-dlp: последний релиз: {version}",
        "log_ytdlp_up_to_date": "yt-dlp: актуальная версия",
        "log_ytdlp_update_available": "yt-dlp: доступно обновление ({version})",
        "log_latest_version_api_timeout_fallback": "yt-dlp: GitHub API не ответил вовремя, пробую страницу релизов...",
        "log_latest_version_check_skipped": "yt-dlp: проверка последней версии пропущена: {error}",
        "log_error": "ОШИБКА: {error}",
        "error_project_root_missing": "Папка проекта не найдена:\n{path}",
        "error_project_root_not_folder": "Путь проекта не является папкой:\n{path}",
        "error_tools_dir_missing": "Папка tools не найдена:\n{path}",
        "error_tools_dir_not_folder": "Путь tools не является папкой:\n{path}",
        "error_create_downloads_folder": "Не удалось создать папку сохранения:\n{path}\n\n{error}",
        "error_required_binary_missing": "{label} не найден:\n{path}",
        "error_required_binary_not_file": "{label} существует, но это не файл:\n{path}",
        "error_failed_start_command": "Не удалось запустить {label}.\n\n{error}",
        "error_command_exit_code": "{label} завершился с кодом {code}.",
        "error_invalid_integer": "Поле «{name}» должно быть неотрицательным целым числом.",
        "error_invalid_number": "Поле «{name}» должно быть неотрицательным числом.",
        "error_output_template_empty": "Шаблон имени файла не может быть пустым.",
        "error_last_log_lines": "{summary}\n\nПоследние {count} строк лога:\n{lines}",
        "label_format_preset": "Профиль качества",
        "label_output_mode": "Формат результата",
        "label_output_template": "Шаблон имени файла",
        "label_retries": "Повторы",
        "label_retry_sleep": "Пауза между повторами (с)",
        "label_restrict_filenames": "Упрощать имена файлов",
        "label_windows_filenames": "Имена файлов для Windows",
        "button_save": "Сохранить",
        "button_cancel": "Отмена",
        "button_reset_defaults": "Сбросить по умолчанию",
        "option_format_best": "Лучшее доступное",
        "option_format_1080p": "До 1080p",
        "option_format_720p": "До 720p",
        "option_format_480p": "До 480p",
        "option_output_mp4": "Совместимый MP4",
        "option_output_mkv": "MKV",
        "option_output_original": "Оставить как есть",
        "option_output_mp3": "Только звук MP3",
        "label_youtube_auth": "Авторизация YouTube",
        "label_auth_mode": "Способ авторизации",
        "label_cookies_browser": "Браузер",
        "label_cookies_file": "Файл cookies.txt",
        "button_select_cookies_file": "Выбрать файл...",
        "option_auth_none": "Без авторизации",
        "option_auth_browser": "Cookies из браузера",
        "option_auth_file": "Файл cookies.txt",
        "option_browser_firefox": "Firefox",
        "option_browser_chrome": "Chrome",
        "option_browser_edge": "Microsoft Edge",
        "option_browser_brave": "Brave",
        "option_browser_opera": "Opera",
        "option_browser_vivaldi": "Vivaldi",
        "option_browser_chromium": "Chromium",
        "dialog_cookies_filter": "Cookies (*.txt)",
        "dialog_all_files_filter": "Все файлы (*.*)",
        "dialog_select_cookies_file": "Выберите файл cookies.txt",
        "error_cookies_file_empty": "Укажите путь к файлу cookies.txt.",
        "error_cookies_file_missing": "Файл cookies.txt не найден:\n{path}",
        "error_youtube_auth_required": (
            "YouTube требует авторизацию.\n\n"
            "Откройте «Настройки» и выберите cookies из браузера\n"
            "или файл cookies.txt.\n\n"
            "В выбранном аккаунте YouTube должен быть подтверждён возраст."
        ),
        "error_browser_cookies_failed": (
            "Не удалось прочитать cookies выбранного браузера.\n\n"
            "Закройте браузер и повторите попытку.\n"
            "Если ошибка сохраняется, выберите другой браузер\n"
            "или используйте файл cookies.txt."
        ),
    },
}


def detect_system_language() -> str:
    candidates: list[str] = []
    try:
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        locale_name = locale.windows_locale.get(language_id)
        if locale_name:
            candidates.append(locale_name)
    except Exception:
        pass

    try:
        locale_name = locale.getlocale()[0]
        if locale_name:
            candidates.append(locale_name)
    except Exception:
        pass

    lang_env = os.environ.get("LANG")
    if lang_env:
        candidates.append(lang_env)

    for candidate in candidates:
        normalized = candidate.lower()
        if normalized.startswith("ru"):
            return "ru"
        if normalized.startswith("en"):
            return "en"

    return "en"


def translate(language: str, key: str, **kwargs: object) -> str:
    language_map = TRANSLATIONS.get(language, TRANSLATIONS["en"])
    template = language_map.get(key) or TRANSLATIONS["en"].get(key) or key
    values = {name: str(value) for name, value in kwargs.items()}
    return template.format(**values)


def normalize_path(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = APP_INSTALL_DIR / candidate
    return candidate.resolve(strict=False)


def load_settings_payload() -> dict[str, object]:
    """Load settings from the new location, falling back to the legacy location."""
    for candidate in (SETTINGS_FILE, LEGACY_SETTINGS_FILE):
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _write_self_test_diagnostic(message: str, *, is_error: bool = False) -> None:
    """Best-effort diagnostics that are safe in a PyInstaller windowed process."""
    stream = sys.stderr if is_error else sys.stdout
    if stream is not None:
        try:
            stream.write(message)
            stream.flush()
            return
        except (AttributeError, OSError, ValueError):
            pass

    if not is_error:
        return

    try:
        log_path = Path(tempfile.gettempdir()) / f"mini-url-converter-self-test-{os.getpid()}.log"
        log_path.write_text(message, encoding="utf-8", errors="replace")
    except Exception:
        # The exit code remains authoritative even if diagnostics cannot be saved.
        pass


def self_test() -> int:
    """Headless validation for installer smoke-tests; the exit code is authoritative."""
    errors: list[str] = []
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        errors.append(f"Failed to create app data directories: {exc}")

    def download_file_simple(url: str, destination: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": f"{APP_TITLE}/1.0"})
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output_file:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    output_file.write(chunk)

    def extract_binary_from_zip_simple(archive_path: Path, binary_name: str, temp_dir: Path) -> Path:
        binary_name_lower = binary_name.lower()
        with zipfile.ZipFile(archive_path) as archive:
            member_name = next(
                (
                    name
                    for name in archive.namelist()
                    if name.lower().endswith(f"/bin/{binary_name_lower}") or name.lower().endswith(f"/{binary_name_lower}")
                ),
                None,
            )
            if member_name is None:
                raise AppError(f"{binary_name} was not found in {archive_path.name}.")
            target_path = temp_dir / binary_name
            with archive.open(member_name) as source, target_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            return target_path

    def replace_binary_simple(source_path: Path, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target_path.with_suffix(target_path.suffix + ".new")
        shutil.copyfile(source_path, temp_target)
        os.replace(temp_target, target_path)

    missing = []
    for label, path in (("yt-dlp.exe", YT_DLP_PATH), ("ffmpeg.exe", FFMPEG_PATH), ("ffprobe.exe", FFPROBE_PATH)):
        if not path.exists():
            missing.append(label)
        elif not path.is_file():
            errors.append(f"Not a file {label}: {path}")

    # On a clean install, tools may not be present yet; fetch them to validate the install.
    if not errors and missing:
        try:
            with tempfile.TemporaryDirectory(prefix="mini-url-converter-selftest-") as temp_dir_text:
                temp_dir = Path(temp_dir_text)
                if "yt-dlp.exe" in missing:
                    yt_tmp = temp_dir / "yt-dlp.exe"
                    download_file_simple(YTDLP_WINDOWS_DOWNLOAD_URL, yt_tmp)
                    replace_binary_simple(yt_tmp, YT_DLP_PATH)
                if "ffmpeg.exe" in missing or "ffprobe.exe" in missing:
                    archive_path = temp_dir / "ffmpeg.zip"
                    download_file_simple(FFMPEG_WINDOWS_BUILD_URL, archive_path)
                    ffmpeg_source = extract_binary_from_zip_simple(archive_path, "ffmpeg.exe", temp_dir)
                    ffprobe_source = extract_binary_from_zip_simple(archive_path, "ffprobe.exe", temp_dir)
                    replace_binary_simple(ffmpeg_source, FFMPEG_PATH)
                    replace_binary_simple(ffprobe_source, FFPROBE_PATH)
        except Exception as exc:
            errors.append(f"Failed to download tools: {exc}")

    def run_first_line(command: list[str]) -> None:
        result = subprocess.run(
            command,
            cwd=str(APP_INSTALL_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise AppError(f"Command failed ({result.returncode}): {subprocess.list2cmdline(command)}")

    try:
        if YT_DLP_PATH.exists():
            run_first_line([str(YT_DLP_PATH), "--version"])
        if FFMPEG_PATH.exists():
            run_first_line([str(FFMPEG_PATH), "-version"])
        if FFPROBE_PATH.exists():
            run_first_line([str(FFPROBE_PATH), "-version"])
    except Exception as exc:
        errors.append(str(exc))

    try:
        probe = App.__new__(App)
        probe.download_dir = APP_DATA_DIR / "Тестовая папка"
        probe.ytdlp_settings = dict(YTDLP_DEFAULTS)
        command = probe.build_command("https://example.invalid/video")
        command_text = subprocess.list2cmdline(command)
        if "--recode-video" in command or "--postprocessor-args" in command:
            errors.append(f"MP4 command unexpectedly enables global transcoding: {command_text}")
        if "--merge-output-format" not in command or "mp4" not in command:
            errors.append(f"MP4 command does not request an MP4 merge: {command_text}")
        selector = command[command.index("-f") + 1]
        if "vcodec^=avc1" not in selector or "acodec^=mp4a" not in selector:
            errors.append(f"MP4 selector does not prefer H.264/AAC: {selector}")
        if str(probe.download_dir) not in command:
            errors.append("Unicode download path was not preserved in the yt-dlp argument list.")
    except Exception as exc:
        errors.append(f"Failed to validate yt-dlp command construction: {exc}")

    if errors:
        _write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1

    _write_self_test_diagnostic("SELF-TEST OK\n")
    return 0


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.geometry("560x500")
        self.root.minsize(520, 450)

        self.startup_messages: list[tuple[str, dict[str, object]]] = []
        self.settings_data = load_settings_payload()
        self.language = self.load_language_setting(self.settings_data)
        self.download_dir = self.load_download_dir_setting(self.settings_data)
        self.ytdlp_settings = self.load_ytdlp_settings(self.settings_data)
        self.last_auto_update_check = self.load_last_auto_update_check(self.settings_data)

        self.url_var = tk.StringVar()
        self.language_var = tk.StringVar(value=self.language.upper())
        self.download_dir_var = tk.StringVar(value=str(self.download_dir))
        self.url_error_var = tk.StringVar(value="")
        self.current_status_key = "status_idle"
        self.current_status_kwargs: dict[str, object] = {}
        self.status_var = tk.StringVar(value=self.tr(self.current_status_key))
        self.progress_text_var = tk.StringVar(value="0%")
        self.task_progress_text_var = tk.StringVar(value="0%")
        self.task_status_var = tk.StringVar(value="")
        self.settings_need_save = False

        self.worker_thread: threading.Thread | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self.current_job_kind: str | None = None
        self.cancel_requested = False
        self.settings_window: tk.Toplevel | None = None
        self.last_local_versions: dict[str, str] | None = None
        self.last_latest_ytdlp_version: str | None = None
        self.last_ytdlp_up_to_date: bool | None = None
        self.url_analysis_request_id = 0
        self.current_job_started_at = 0.0
        self.total_progress_value = 0.0
        self.task_progress_value = 0.0
        self.task_progress_mode = "determinate"
        self.task_progress_busy_job: str | None = None
        self.task_progress_busy_offset = 0
        self.download_destinations: list[str] = []
        self.current_download_destination: str | None = None
        self.run_artifacts: dict[str, bool] = {}
        self.last_output_file: str | None = None
        self.recent_log_lines: deque[str] = deque(maxlen=RECENT_LOG_LIMIT)
        self.closing = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.refresh_ui_language()
        if self.settings_need_save:
            try:
                self.save_settings()
            except Exception as exc:
                self.startup_messages.append(("log_warning_failed_save_settings", {"error": exc}))
        for key, params in self.startup_messages:
            self._append_log(self.tr(key, **params) + "\n")
        self._append_log(self.tr("log_save_folder", path=self.download_dir) + "\n")
        self.start_background_auto_update_check()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        top = ttk.Frame(main)
        top.pack(fill="x")

        header_row = ttk.Frame(top)
        header_row.pack(fill="x")

        self.url_label = ttk.Label(header_row)
        self.url_label.pack(side="left", anchor="w")

        language_row = ttk.Frame(header_row)
        language_row.pack(side="right")

        self.language_label = ttk.Label(language_row)
        self.language_label.pack(side="left", padx=(0, 6))

        self.language_combo = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            values=("EN", "RU"),
            state="readonly",
            width=5,
        )
        self.language_combo.pack(side="left")
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language_change)

        entry_row = ttk.Frame(top)
        entry_row.pack(fill="x", pady=(4, 2))

        self.url_entry_border = tk.Frame(entry_row, bg="#cfd8dc", bd=1, highlightthickness=0)
        self.url_entry_border.pack(side="left", fill="x", expand=True)

        self.url_entry = ttk.Entry(self.url_entry_border, textvariable=self.url_var, font=("Segoe UI", 11))
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.url_entry.focus_set()
        self.url_entry.bind("<Return>", self.on_start)
        self.url_entry.bind("<Control-KeyPress>", self.on_url_control_keypress)
        self.url_entry.bind("<Shift-Insert>", self.on_url_paste)
        self.url_entry.bind("<Button-3>", self.show_url_context_menu)
        self.url_entry.bind("<KeyPress>", self.on_url_entry_interaction, add="+")
        self.url_entry.bind("<Button-1>", self.on_url_entry_interaction, add="+")

        action_button_column = ttk.Frame(entry_row)
        action_button_column.pack(side="left", padx=(8, 0))

        self.start_button = tk.Button(
            action_button_column,
            command=self.on_start,
            bg="#2e7d32",
            fg="white",
            activebackground="#256628",
            activeforeground="white",
            disabledforeground="#e0e0e0",
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=2,
            relief="raised",
            bd=1,
        )
        self.start_button.pack(fill="x")

        self.cancel_button = tk.Button(
            action_button_column,
            command=self.on_cancel_job,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=1,
            relief="flat",
            bd=0,
            state="disabled",
        )
        self.cancel_button.pack(fill="x", pady=(4, 0))

        self.url_context_menu = tk.Menu(self.root, tearoff=False)
        self.url_context_menu.add_command(label="Paste", command=self.paste_into_url_entry)

        self.url_error_label = tk.Label(
            top,
            textvariable=self.url_error_var,
            fg="#b71c1c",
            bg=self.root.cget("bg"),
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )

        self.download_dir_label = ttk.Label(top)
        self.download_dir_label.pack(anchor="w")

        folder_row = ttk.Frame(top)
        folder_row.pack(fill="x", pady=(4, 10))

        self.download_dir_entry = ttk.Entry(
            folder_row,
            textvariable=self.download_dir_var,
            state="readonly",
            font=("Segoe UI", 10),
        )
        self.download_dir_entry.pack(side="left", fill="x", expand=True)

        self.choose_folder_button = ttk.Button(folder_row, command=self.choose_folder)
        self.choose_folder_button.pack(side="left", padx=(8, 0))

        button_row = ttk.Frame(top)
        button_row.pack(fill="x")

        self.check_versions_button = ttk.Button(button_row, command=self.on_check_versions)
        self.check_versions_button.pack(side="left")

        self.settings_button = ttk.Button(button_row, command=self.open_settings_dialog)
        self.settings_button.pack(side="left", padx=(8, 0))

        self.open_button = ttk.Button(button_row, command=self.open_downloads)
        self.open_button.pack(side="left", padx=(8, 0))
        self._set_cancel_button_state(False)

        self.progress_frame = ttk.LabelFrame(main, padding=8)
        self.progress_frame.pack(fill="x", pady=(10, 10))

        self.progress_bar = tk.Canvas(
            self.progress_frame,
            height=6,
            bg="#dde3ea",
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar_fill = self.progress_bar.create_rectangle(0, 0, 0, 6, fill="#5b9cf0", outline="")
        self.progress_bar.bind("<Configure>", self.on_total_progress_resize)

        progress_info = ttk.Frame(self.progress_frame)
        progress_info.pack(fill="x", pady=(4, 0))

        ttk.Label(progress_info, textvariable=self.progress_text_var).pack(side="left")

        self.task_progress_bar = tk.Canvas(
            self.progress_frame,
            height=6,
            bg="#dde3ea",
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.task_progress_bar.pack(fill="x", pady=(8, 0))
        self.task_progress_bar_fill = self.task_progress_bar.create_rectangle(0, 0, 0, 6, fill="#2e7d32", outline="")
        self.task_progress_bar.bind("<Configure>", self.on_task_progress_resize)

        task_progress_info = ttk.Frame(self.progress_frame)
        task_progress_info.pack(fill="x", pady=(4, 0))

        ttk.Label(task_progress_info, textvariable=self.task_progress_text_var).pack(side="left")

        self.log_frame = ttk.LabelFrame(main, padding=10)
        self.log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            self.log_frame,
            wrap="word",
            font=("Consolas", 10),
            height=5,
            state="disabled",
            exportselection=False,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.bind("<Button-1>", self.on_log_focus, add="+")
        self.log_text.bind("<Control-KeyPress>", self.on_log_control_keypress)
        self.log_text.bind("<Button-3>", self.show_log_context_menu)

        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_context_menu = tk.Menu(self.root, tearoff=False)
        self.log_context_menu.add_command(label="Copy", command=self.copy_log)
        self.log_context_menu.add_command(label="Copy all", command=self.copy_all_log)
        self.log_context_menu.add_command(label="Clear log", command=self.clear_log)

    def tr(self, key: str, **kwargs: object) -> str:
        return translate(self.language, key, **kwargs)

    def load_settings_data(self) -> dict[str, object]:
        # Kept for older call-sites; main loading happens via load_settings_payload().
        return load_settings_payload()

    def load_language_setting(self, data: dict[str, object]) -> str:
        raw_language = data.get("language")
        if isinstance(raw_language, str):
            candidate = raw_language.strip().lower()
            if candidate in TRANSLATIONS:
                return candidate
            if candidate:
                self.startup_messages.append(
                    ("log_warning_settings_invalid_language", {"settings_file": SETTINGS_FILE})
                )
        return detect_system_language()

    def load_download_dir_setting(self, data: dict[str, object]) -> Path:
        raw_download_dir = data.get("download_dir")
        if isinstance(raw_download_dir, str) and raw_download_dir.strip():
            return normalize_path(Path(raw_download_dir.strip()))

        if "download_dir" in data:
            self.startup_messages.append(
                ("log_warning_settings_invalid_download_dir", {"settings_file": SETTINGS_FILE})
            )

        return DEFAULT_DOWNLOADS_DIR

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = dict(YTDLP_DEFAULTS)
        raw_settings = data.get("ytdlp")
        if not isinstance(raw_settings, dict):
            return settings

        format_preset = raw_settings.get("format_preset")
        if isinstance(format_preset, str) and format_preset in FORMAT_PRESET_CHOICES:
            settings["format_preset"] = format_preset

        output_mode = raw_settings.get("output_mode")
        if isinstance(output_mode, str) and output_mode in OUTPUT_MODE_CHOICES:
            settings["output_mode"] = output_mode

        output_template = raw_settings.get("output_template")
        if isinstance(output_template, str) and output_template.strip():
            normalized_output_template = output_template.strip()
            if normalized_output_template == LEGACY_OUTPUT_TEMPLATE:
                settings["output_template"] = str(YTDLP_DEFAULTS["output_template"])
                self.settings_need_save = True
            else:
                settings["output_template"] = normalized_output_template

        retries = raw_settings.get("retries")
        if isinstance(retries, int) and retries >= 0:
            settings["retries"] = retries

        retry_sleep = raw_settings.get("retry_sleep")
        normalized_retry_sleep = self.normalize_retry_sleep(retry_sleep)
        if normalized_retry_sleep is not None:
            settings["retry_sleep"] = normalized_retry_sleep

        restrict_filenames = raw_settings.get("restrict_filenames")
        if isinstance(restrict_filenames, bool):
            settings["restrict_filenames"] = restrict_filenames

        windows_filenames = raw_settings.get("windows_filenames")
        if isinstance(windows_filenames, bool):
            settings["windows_filenames"] = windows_filenames

        auth_mode = raw_settings.get("auth_mode")
        if isinstance(auth_mode, str) and auth_mode in AUTH_MODE_CHOICES:
            settings["auth_mode"] = auth_mode

        cookies_browser = raw_settings.get("cookies_browser")
        if isinstance(cookies_browser, str) and cookies_browser in COOKIE_BROWSER_CHOICES:
            settings["cookies_browser"] = cookies_browser

        cookies_file = raw_settings.get("cookies_file")
        if isinstance(cookies_file, str):
            settings["cookies_file"] = cookies_file.strip()

        return settings

    def load_last_auto_update_check(self, data: dict[str, object]) -> float:
        raw = data.get("last_auto_update_check")
        value = _as_float(raw)
        if value is None or value < 0:
            return 0.0
        return value

    def save_settings(self) -> None:
        payload = {
            "download_dir": str(self.download_dir),
            "language": self.language,
            "ytdlp": dict(self.ytdlp_settings),
            "last_auto_update_check": float(self.last_auto_update_check or 0.0),
        }
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            if LEGACY_SETTINGS_FILE.exists():
                LEGACY_SETTINGS_FILE.unlink()
        except Exception:
            pass

    def apply_download_dir(self, download_dir: Path) -> None:
        self.download_dir = normalize_path(download_dir)
        self.download_dir_var.set(str(self.download_dir))

    def normalize_retry_sleep(self, value: object) -> str | None:
        if isinstance(value, (int, float)) and value >= 0:
            return self.format_retry_sleep_value(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                number = float(text)
            except ValueError:
                return None
            if number < 0:
                return None
            return self.format_retry_sleep_value(number)
        return None

    def format_retry_sleep_value(self, value: object) -> str:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:g}"

    def format_preset_label(self, key: str) -> str:
        return self.tr(f"option_format_{key}")

    def output_mode_label(self, key: str) -> str:
        return self.tr(f"option_output_{key}")

    def auth_mode_label(self, key: str) -> str:
        return self.tr(f"option_auth_{key}")

    def cookies_browser_label(self, key: str) -> str:
        return self.tr(f"option_browser_{key}")

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
        dialog.title(self.tr("dialog_settings_title"))
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
        auth_mode_var = tk.StringVar(value=str(self.ytdlp_settings["auth_mode"]))
        cookies_browser_var = tk.StringVar(value=str(self.ytdlp_settings["cookies_browser"]))
        cookies_file_var = tk.StringVar(value=str(self.ytdlp_settings["cookies_file"]))

        format_combo = ttk.Combobox(
            body,
            state="readonly",
            values=[self.format_preset_label(key) for key in FORMAT_PRESET_CHOICES],
            width=24,
        )
        format_combo.set(self.format_preset_label(format_var.get()))

        output_combo = ttk.Combobox(
            body,
            state="readonly",
            values=[self.output_mode_label(key) for key in OUTPUT_MODE_CHOICES],
            width=24,
        )
        output_combo.set(self.output_mode_label(output_mode_var.get()))

        fields = [
            (self.tr("label_format_preset"), format_combo),
            (self.tr("label_output_mode"), output_combo),
            (self.tr("label_output_template"), ttk.Entry(body, textvariable=output_template_var, width=42)),
            (self.tr("label_retries"), ttk.Spinbox(body, from_=0, to=100, textvariable=retries_var, width=10)),
            (self.tr("label_retry_sleep"), ttk.Entry(body, textvariable=retry_sleep_var, width=10)),
        ]

        for row_index, (label_text, widget) in enumerate(fields):
            ttk.Label(body, text=label_text).grid(row=row_index, column=0, sticky="w", padx=(0, 12), pady=4)
            widget.grid(row=row_index, column=1, sticky="ew", pady=4)

        ttk.Checkbutton(body, text=self.tr("label_restrict_filenames"), variable=restrict_var).grid(
            row=len(fields),
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 2),
        )
        ttk.Checkbutton(body, text=self.tr("label_windows_filenames"), variable=windows_var).grid(
            row=len(fields) + 1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=2,
        )

        auth_row = len(fields) + 2
        ttk.Separator(body, orient="horizontal").grid(
            row=auth_row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        ttk.Label(body, text=self.tr("label_youtube_auth"), font=("Segoe UI", 9, "bold")).grid(
            row=auth_row + 1, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )

        auth_combo = ttk.Combobox(
            body,
            state="readonly",
            values=[self.auth_mode_label(key) for key in AUTH_MODE_CHOICES],
            width=24,
        )
        auth_combo.set(self.auth_mode_label(auth_mode_var.get()))
        ttk.Label(body, text=self.tr("label_auth_mode")).grid(
            row=auth_row + 2, column=0, sticky="w", padx=(0, 12), pady=4
        )
        auth_combo.grid(row=auth_row + 2, column=1, sticky="ew", pady=4)

        browser_combo = ttk.Combobox(
            body,
            state="readonly",
            values=[self.cookies_browser_label(key) for key in COOKIE_BROWSER_CHOICES],
            width=24,
        )
        browser_combo.set(self.cookies_browser_label(cookies_browser_var.get()))
        ttk.Label(body, text=self.tr("label_cookies_browser")).grid(
            row=auth_row + 3, column=0, sticky="w", padx=(0, 12), pady=4
        )
        browser_combo.grid(row=auth_row + 3, column=1, sticky="ew", pady=4)

        ttk.Label(body, text=self.tr("label_cookies_file")).grid(
            row=auth_row + 4, column=0, sticky="w", padx=(0, 12), pady=4
        )
        cookies_file_frame = ttk.Frame(body)
        cookies_file_frame.grid(row=auth_row + 4, column=1, sticky="ew", pady=4)
        cookies_file_frame.columnconfigure(0, weight=1)
        cookies_file_entry = ttk.Entry(cookies_file_frame, textvariable=cookies_file_var)
        cookies_file_entry.grid(row=0, column=0, sticky="ew")
        select_cookies_button = ttk.Button(cookies_file_frame, text=self.tr("button_select_cookies_file"))
        select_cookies_button.grid(row=0, column=1, padx=(8, 0))

        def current_auth_mode() -> str:
            return next(
                (key for key in AUTH_MODE_CHOICES if self.auth_mode_label(key) == auth_combo.get()),
                str(YTDLP_DEFAULTS["auth_mode"]),
            )

        def update_auth_state(event: tk.Event[tk.Misc] | None = None) -> None:
            del event
            mode = current_auth_mode()
            browser_combo.configure(state="readonly" if mode == "browser" else "disabled")
            file_state = "normal" if mode == "file" else "disabled"
            cookies_file_entry.configure(state=file_state)
            select_cookies_button.configure(state=file_state)

        def select_cookies_file() -> None:
            selected = filedialog.askopenfilename(
                parent=dialog,
                title=self.tr("dialog_select_cookies_file"),
                filetypes=[
                    (self.tr("dialog_cookies_filter"), "*.txt"),
                    (self.tr("dialog_all_files_filter"), "*.*"),
                ],
            )
            if selected:
                cookies_file_var.set(selected)

        auth_combo.bind("<<ComboboxSelected>>", update_auth_state)
        select_cookies_button.configure(command=select_cookies_file)
        update_auth_state()

        buttons = ttk.Frame(body)
        buttons.grid(row=auth_row + 5, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def apply_defaults() -> None:
            format_var.set(str(YTDLP_DEFAULTS["format_preset"]))
            output_mode_var.set(str(YTDLP_DEFAULTS["output_mode"]))
            output_template_var.set(str(YTDLP_DEFAULTS["output_template"]))
            retries_var.set(str(YTDLP_DEFAULTS["retries"]))
            retry_sleep_var.set(str(YTDLP_DEFAULTS["retry_sleep"]))
            restrict_var.set(bool(YTDLP_DEFAULTS["restrict_filenames"]))
            windows_var.set(bool(YTDLP_DEFAULTS["windows_filenames"]))
            auth_mode_var.set(str(YTDLP_DEFAULTS["auth_mode"]))
            cookies_browser_var.set(str(YTDLP_DEFAULTS["cookies_browser"]))
            cookies_file_var.set(str(YTDLP_DEFAULTS["cookies_file"]))
            format_combo.set(self.format_preset_label(format_var.get()))
            output_combo.set(self.output_mode_label(output_mode_var.get()))
            auth_combo.set(self.auth_mode_label(auth_mode_var.get()))
            browser_combo.set(self.cookies_browser_label(cookies_browser_var.get()))
            update_auth_state()

        def save_dialog_settings() -> None:
            selected_format = next(
                (key for key in FORMAT_PRESET_CHOICES if self.format_preset_label(key) == format_combo.get()),
                str(YTDLP_DEFAULTS["format_preset"]),
            )
            selected_output = next(
                (key for key in OUTPUT_MODE_CHOICES if self.output_mode_label(key) == output_combo.get()),
                str(YTDLP_DEFAULTS["output_mode"]),
            )

            output_template = output_template_var.get().strip()
            if not output_template:
                messagebox.showerror(self.tr("app_title"), self.tr("error_output_template_empty"), parent=dialog)
                return

            try:
                retries_value = int(retries_var.get().strip())
                if retries_value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    self.tr("app_title"),
                    self.tr("error_invalid_integer", name=self.tr("label_retries")),
                    parent=dialog,
                )
                return

            normalized_retry_sleep = self.normalize_retry_sleep(retry_sleep_var.get())
            if normalized_retry_sleep is None:
                messagebox.showerror(
                    self.tr("app_title"),
                    self.tr("error_invalid_number", name=self.tr("label_retry_sleep")),
                    parent=dialog,
                )
                return

            selected_auth = next(
                (key for key in AUTH_MODE_CHOICES if self.auth_mode_label(key) == auth_combo.get()),
                str(YTDLP_DEFAULTS["auth_mode"]),
            )
            selected_browser = next(
                (key for key in COOKIE_BROWSER_CHOICES if self.cookies_browser_label(key) == browser_combo.get()),
                str(YTDLP_DEFAULTS["cookies_browser"]),
            )

            cookies_file_value = cookies_file_var.get().strip()
            if selected_auth == "file":
                if not cookies_file_value:
                    messagebox.showerror(self.tr("app_title"), self.tr("error_cookies_file_empty"), parent=dialog)
                    return
                candidate = Path(cookies_file_value).expanduser().resolve(strict=False)
                if not candidate.is_file():
                    messagebox.showerror(
                        self.tr("app_title"),
                        self.tr("error_cookies_file_missing", path=candidate),
                        parent=dialog,
                    )
                    return
                cookies_file_value = str(candidate)

            self.ytdlp_settings = {
                "format_preset": selected_format,
                "output_mode": selected_output,
                "output_template": output_template,
                "retries": retries_value,
                "retry_sleep": normalized_retry_sleep,
                "restrict_filenames": bool(restrict_var.get()),
                "windows_filenames": bool(windows_var.get()),
                "auth_mode": selected_auth,
                "cookies_browser": selected_browser,
                "cookies_file": cookies_file_value,
            }

            try:
                self.save_settings()
            except Exception as exc:
                self._append_log(self.tr("log_warning_failed_save_settings", error=exc) + "\n")
                self._set_status("status_settings_save_failed")
                messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc), parent=dialog)
                return

            self._append_log(self.tr("log_settings_updated") + "\n")
            self._set_status("status_settings_updated")
            self.close_settings_dialog(dialog)

        ttk.Button(buttons, text=self.tr("button_reset_defaults"), command=apply_defaults).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.tr("button_cancel"), command=lambda win=dialog: self.close_settings_dialog(win)).pack(
            side="left",
            padx=(0, 8),
        )
        ttk.Button(buttons, text=self.tr("button_save"), command=save_dialog_settings).pack(side="left")

        dialog.update_idletasks()
        dialog.grab_set()
        dialog.focus_force()

    def close_settings_dialog(self, dialog: tk.Toplevel) -> None:
        if self.settings_window is dialog:
            self.settings_window = None
        dialog.destroy()

    def refresh_ui_language(self) -> None:
        self.root.title(self.tr("app_title"))
        self.language_var.set(self.language.upper())
        self.url_label.configure(text=self.tr("label_url"))
        self.language_label.configure(text=self.tr("label_language"))
        self.url_context_menu.entryconfigure(0, label=self.tr("button_paste"))
        self.download_dir_label.configure(text=self.tr("label_save_folder"))
        self.choose_folder_button.configure(text=self.tr("button_choose_folder"))
        self.start_button.configure(text=self.tr("button_start"))
        self.check_versions_button.configure(text=self.tr("button_check_versions"))
        self.settings_button.configure(text=self.tr("button_settings"))
        self.open_button.configure(text=self.tr("button_open_downloads"))
        self.cancel_button.configure(text=self.tr("button_cancel_job"))
        self.progress_frame.configure(text=self.tr("group_progress"))
        self.log_frame.configure(text=self.tr("group_log"))
        self.log_context_menu.entryconfigure(0, label=self.tr("menu_copy"))
        self.log_context_menu.entryconfigure(1, label=self.tr("menu_copy_all"))
        self.log_context_menu.entryconfigure(2, label=self.tr("menu_clear_log"))
        if self.current_status_key:
            self.status_var.set(self.tr(self.current_status_key, **self.current_status_kwargs))

    def on_language_change(self, event: tk.Event[tk.Misc] | None = None) -> None:
        del event
        selected = self.language_var.get().strip().lower()
        if selected not in TRANSLATIONS or selected == self.language:
            return

        self.language = selected
        self.refresh_ui_language()
        try:
            self.save_settings()
        except Exception as exc:
            self._append_log(self.tr("log_warning_failed_save_settings", error=exc) + "\n")
            self._set_status("status_settings_save_failed")
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc))
            return

        self._set_status("status_language_updated")

    def paste_from_clipboard(self) -> None:
        self.paste_into_url_entry()

    def paste_into_url_entry(self) -> None:
        try:
            clipboard_text = self.root.clipboard_get()
        except Exception:
            return

        candidate_text = self.build_url_entry_candidate_text(clipboard_text)
        validation_error = self.validate_url_text(candidate_text)
        if validation_error:
            self.url_entry.focus_set()
            self.show_url_entry_popup(validation_error)
            return

        self.hide_url_entry_popup()
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, candidate_text)
        self.url_entry.icursor("end")
        self.start_url_analysis(candidate_text)

    def on_url_paste(self, event: tk.Event[tk.Misc]) -> str:
        del event
        self.paste_into_url_entry()
        return "break"

    def on_url_entry_interaction(self, event: tk.Event[tk.Misc]) -> None:
        del event
        self.hide_url_entry_popup()

    def on_url_control_keypress(self, event: tk.Event[tk.Misc]) -> str | None:
        if getattr(event, "keycode", None) == 86:
            return self.on_url_paste(event)
        return None

    def validate_url_text(self, text: str) -> str | None:
        normalized_text = text.strip()
        if not normalized_text:
            return self.tr("warning_enter_url")
        if len(normalized_text) > MAX_URL_TEXT_LENGTH:
            return self.tr("popup_url_too_long")
        if not URL_TEXT_RE.match(normalized_text):
            return self.tr("popup_invalid_url")
        lower_text = normalized_text.lower()
        first_scheme_end = lower_text.find("://")
        if first_scheme_end == -1:
            return self.tr("popup_invalid_url")
        if "http://" in lower_text[first_scheme_end + 3:] or "https://" in lower_text[first_scheme_end + 3:]:
            return self.tr("popup_invalid_url")

        parsed = urllib.parse.urlparse(normalized_text)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return self.tr("popup_invalid_url")
        return None

    def build_url_entry_candidate_text(self, clipboard_text: str) -> str:
        insert_text = clipboard_text.strip()
        current_text = self.url_entry.get()
        if not current_text:
            return insert_text

        try:
            selection_start = self.url_entry.index("sel.first")
            selection_end = self.url_entry.index("sel.last")
            return current_text[:selection_start] + insert_text + current_text[selection_end:]
        except tk.TclError:
            insert_index = self.url_entry.index("insert")
            return current_text[:insert_index] + insert_text + current_text[insert_index:]

    def show_url_entry_popup(self, message: str) -> None:
        self.hide_url_entry_popup()
        self.url_error_var.set(message)
        self.url_entry_border.configure(bg="#d32f2f")
        if not self.url_error_label.winfo_manager():
            self.url_error_label.pack(fill="x", pady=(2, 6), before=self.download_dir_label)

    def hide_url_entry_popup(self) -> None:
        self.url_error_var.set("")
        self.url_entry_border.configure(bg="#cfd8dc")
        if self.url_error_label.winfo_manager():
            self.url_error_label.pack_forget()

    def start_url_analysis(self, url: str) -> None:
        normalized_url = url.strip()
        if not normalized_url:
            return

        self.url_analysis_request_id += 1
        request_id = self.url_analysis_request_id
        thread = threading.Thread(target=self.run_url_analysis_job, args=(request_id, normalized_url), daemon=True)
        thread.start()

    def run_url_analysis_job(self, request_id: int, url: str) -> None:
        try:
            self.ensure_required_binary("yt-dlp.exe", YT_DLP_PATH)
            info = self.fetch_url_analysis_info(url)
            output_path = self.resolve_analysis_output_path(info)
            if output_path is not None and output_path.exists() and output_path.is_file():
                size_bytes = float(output_path.stat().st_size)
                log_text = self.tr("log_actual_output_size", size_mb=self.format_size_mb(size_bytes))
            else:
                size_bytes = self.estimate_output_size_bytes(info)
                if size_bytes is None:
                    raise AppError("No filesize metadata returned by yt-dlp.")
                log_text = self.tr("log_estimated_output_size", size_mb=self.format_size_mb(size_bytes))
            if request_id != self.url_analysis_request_id or self.closing:
                return
            self._append_log(log_text + "\n")
        except Exception as exc:
            if request_id != self.url_analysis_request_id or self.closing:
                return
            self._append_log(self.tr("log_failed_estimate_output_size", error=self._stringify_error(exc)) + "\n")

    def fetch_url_analysis_info(self, url: str) -> dict[str, object]:
        command = [part for part in self.build_command(url) if part not in ("--progress", "--newline")]
        command.insert(1, "--no-warnings")
        command.insert(2, "--no-playlist")
        command.insert(-1, "--skip-download")
        command.insert(-1, "--dump-single-json")

        try:
            result = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=URL_ANALYSIS_TIMEOUT_SECONDS,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError(f"Analysis timed out after {URL_ANALYSIS_TIMEOUT_SECONDS} seconds.") from exc
        except Exception as exc:
            raise AppError(f"Failed to analyze URL: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if detail:
                raise AppError(detail)
            raise AppError(f"yt-dlp metadata analysis exited with code {result.returncode}.")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppError(f"Invalid metadata response: {exc}") from exc

        if not isinstance(data, dict):
            raise AppError("Unexpected metadata response from yt-dlp.")
        return data

    def estimate_output_size_bytes(self, info: dict[str, object]) -> float | None:
        if str(self.ytdlp_settings["output_mode"]) == "mp3":
            duration = self.extract_duration_value(info)
            if duration is not None:
                return duration * 192000 / 8

        requested_downloads = info.get("requested_downloads")
        if isinstance(requested_downloads, list) and requested_downloads:
            first_download = requested_downloads[0]
            if isinstance(first_download, dict):
                size = self.extract_size_value(first_download)
                if size is not None:
                    return size

        requested_formats = info.get("requested_formats")
        if isinstance(requested_formats, list) and requested_formats:
            total_size = 0.0
            found_any_size = False
            total_bitrate = 0.0
            for item in requested_formats:
                if not isinstance(item, dict):
                    continue
                size = self.extract_size_value(item)
                if size is not None:
                    total_size += size
                    found_any_size = True
                    continue
                bitrate = self.extract_bitrate_value(item)
                if bitrate is not None:
                    total_bitrate += bitrate
            if found_any_size and total_size > 0:
                return total_size
            duration = self.extract_duration_value(info)
            if duration is not None and total_bitrate > 0:
                return duration * total_bitrate * 1000 / 8

        top_level_size = self.extract_size_value(info)
        if top_level_size is not None:
            return top_level_size

        duration = self.extract_duration_value(info)
        bitrate = self.extract_bitrate_value(info)
        if duration is not None and bitrate is not None and bitrate > 0:
            return duration * bitrate * 1000 / 8

        return None

    def resolve_analysis_output_path(self, info: dict[str, object]) -> Path | None:
        requested_downloads = info.get("requested_downloads")
        if not isinstance(requested_downloads, list) or not requested_downloads:
            return None

        first_download = requested_downloads[0]
        if not isinstance(first_download, dict):
            return None

        for key in ("filename", "_filename", "filepath"):
            value = first_download.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value)

        return None

    def extract_size_value(self, info: dict[str, object]) -> float | None:
        for key in ("filesize", "filesize_approx"):
            value = info.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    def extract_bitrate_value(self, info: dict[str, object]) -> float | None:
        value = info.get("tbr")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None

    def extract_duration_value(self, info: dict[str, object]) -> float | None:
        value = info.get("duration")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None

    def format_size_mb(self, size_bytes: float) -> str:
        return f"{size_bytes / (1024 * 1024):.2f}"

    def show_url_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        event.widget.focus_set()
        try:
            event.widget.icursor(f"@{event.x}")
        except tk.TclError:
            pass
        try:
            self.url_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.url_context_menu.grab_release()
        return "break"

    def choose_folder(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return

        initial_dir = self.download_dir if self.download_dir.exists() else DEFAULT_DOWNLOADS_DIR
        selected = filedialog.askdirectory(
            parent=self.root,
            title=self.tr("dialog_choose_folder"),
            initialdir=str(initial_dir),
            mustexist=False,
        )
        if not selected:
            return

        candidate = normalize_path(Path(selected))
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_create_save_folder", error=exc))
            return

        self.apply_download_dir(candidate)
        try:
            self.save_settings()
        except Exception as exc:
            self._append_log(self.tr("log_warning_failed_save_settings", error=exc) + "\n")
            self._set_status("status_settings_save_failed")
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc))
            return

        self._append_log(self.tr("log_save_folder", path=self.download_dir) + "\n")
        self._set_status("status_save_folder_updated")

    def open_downloads(self) -> None:
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.download_dir))
        except Exception as exc:
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_open_downloads", error=exc))

    def clear_log(self) -> None:
        self.recent_log_lines.clear()
        self._set_log_ui("")
        self._reset_progress_state()
        self._set_status("status_idle")

    def copy_log(self) -> None:
        self.copy_log_text(force_all=False)

    def copy_all_log(self) -> None:
        self.copy_log_text(force_all=True)

    def copy_log_text(self, force_all: bool) -> None:
        try:
            text = self.get_log_text(force_all=force_all)
            self.root.clipboard_clear()
            if text:
                self.root.clipboard_append(text)
            self.root.update_idletasks()
            self._set_status("status_log_copied")
        except Exception as exc:
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_copy_log", error=exc))

    def get_log_text(self, force_all: bool) -> str:
        if not force_all:
            try:
                return self.log_text.get("sel.first", "sel.last")
            except tk.TclError:
                pass
        return self.log_text.get("1.0", "end-1c")

    def on_copy_log_shortcut(self, event: tk.Event[tk.Misc]) -> str:
        del event
        self.copy_log()
        return "break"

    def on_log_control_keypress(self, event: tk.Event[tk.Misc]) -> str | None:
        if getattr(event, "keycode", None) == 67:
            return self.on_copy_log_shortcut(event)
        return None

    def on_log_focus(self, event: tk.Event[tk.Misc]) -> None:
        event.widget.focus_set()

    def show_log_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        event.widget.focus_set()
        try:
            self.log_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_context_menu.grab_release()
        return "break"

    def on_start(self, event: tk.Event[tk.Misc] | None = None) -> None:
        del event
        url = self.url_var.get().strip()
        validation_error = self.validate_url_text(url)
        if validation_error:
            self.url_entry.focus_set()
            self.show_url_entry_popup(validation_error)
            return

        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return

        self.url_analysis_request_id += 1
        self.recent_log_lines.clear()
        self.current_job_kind = "download"
        self.cancel_requested = False
        self.current_job_started_at = time.time()
        self.last_output_file = None
        self._reset_progress_state()
        self._set_status("status_preparing")
        self._set_running_state_ui(True)
        self._append_log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        self._append_log(self.tr("log_url", url=url) + "\n")
        self._append_log(self.tr("log_save_folder", path=self.download_dir) + "\n")

        self.worker_thread = threading.Thread(target=self.run_job, args=(url,), daemon=True)
        self.worker_thread.start()

    def on_check_versions(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return

        self.url_analysis_request_id += 1
        self.recent_log_lines.clear()
        self.current_job_kind = "check_versions"
        self.cancel_requested = False
        self.current_job_started_at = 0.0
        self.last_output_file = None
        self._reset_progress_state()
        self._set_status("status_preparing_versions")
        self._set_running_state_ui(True)
        self._append_log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

        self.worker_thread = threading.Thread(target=self.run_check_versions_job, daemon=True)
        self.worker_thread.start()

    def begin_update_job(self, clear_log: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo(self.tr("app_title"), self.tr("info_job_running"))
            return

        self.url_analysis_request_id += 1
        if self.last_ytdlp_up_to_date is True:
            self._set_status("status_already_up_to_date")
            self._append_log(self.tr("log_update_skipped_up_to_date") + "\n")
            return

        if clear_log:
            self.recent_log_lines.clear()
        self.current_job_kind = "update"
        self.cancel_requested = False
        self.current_job_started_at = 0.0
        self.last_output_file = None
        self._reset_progress_state()
        self._set_status("status_preparing_update")
        self._set_running_state_ui(True)
        self._append_log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        self._append_log(self.tr("log_update_started") + "\n")

        self.worker_thread = threading.Thread(target=self.run_update_job, daemon=True)
        self.worker_thread.start()

    def prompt_update_after_check(self, current_version: str, latest_version: str) -> None:
        should_update = messagebox.askyesno(
            self.tr("app_title"),
            self.tr("ask_update_now", current=current_version, latest=latest_version),
        )
        if should_update:
            self.begin_update_job(clear_log=False)
            return

        self._append_log(self.tr("log_update_cancelled") + "\n")

    def on_cancel_job(self) -> None:
        process = self.current_process
        if self.current_job_kind != "download" or process is None or process.poll() is not None:
            return

        self.cancel_requested = True
        self._append_log(self.tr("log_cancel_requested") + "\n")
        self._set_status("status_cancelling")
        self.cancel_button.configure(state="disabled")
        threading.Thread(target=self._stop_current_process, daemon=True).start()

    def on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            should_close = messagebox.askyesno(
                self.tr("app_title"),
                self.tr("ask_close_running"),
            )
            if not should_close:
                return
            self._stop_current_process()

        self.hide_url_entry_popup()
        self._stop_task_busy_animation()
        self.closing = True
        self.root.destroy()

    def start_background_auto_update_check(self) -> None:
        """Best-effort tool update so installs stay current without reinstalling the app."""
        thread = threading.Thread(target=self._run_background_auto_update_check, daemon=True)
        thread.start()

    def _run_background_auto_update_check(self) -> None:
        # Silent by design: avoids surprising dialogs at startup.
        try:
            if self.closing:
                return
            self.ensure_environment()
            now = time.time()
            last = float(self.last_auto_update_check or 0.0)
            if last > 0 and now - last < AUTO_UPDATE_CHECK_INTERVAL_SECONDS:
                return
            self.last_auto_update_check = now
            try:
                self.save_settings()
            except Exception:
                pass
            self.maybe_update_ytdlp_silent()
        except Exception:
            return

    def maybe_update_ytdlp_silent(self) -> None:
        """Update yt-dlp.exe from GitHub if a newer release exists."""
        if not YT_DLP_PATH.exists() or not YT_DLP_PATH.is_file():
            return

        try:
            current_version = self.get_command_version("yt-dlp", [str(YT_DLP_PATH), "--version"])
        except Exception:
            return

        latest_version = self.try_fetch_latest_ytdlp_version(timeout_seconds=LATEST_VERSION_TIMEOUT_SECONDS)
        if not latest_version:
            return

        if self.normalize_version_text(current_version) == self.normalize_version_text(latest_version):
            return

        with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            yt_tmp = temp_dir / "yt-dlp.exe"
            self.download_file(YTDLP_WINDOWS_DOWNLOAD_URL, yt_tmp, "yt-dlp")
            self.replace_binary(yt_tmp, YT_DLP_PATH)

    def run_job(self, url: str) -> None:
        try:
            self.ensure_environment()
            self._set_task_progress(0.0, "0%", self.tr("status_running_ytdlp"))
            command = self.build_command(url)

            self._set_status("status_running_ytdlp")
            self._append_log(self.tr("log_binary_path", label="yt-dlp.exe", path=YT_DLP_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffmpeg.exe", path=FFMPEG_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffprobe.exe", path=FFPROBE_PATH) + "\n")
            self._append_log(f"Command: {subprocess.list2cmdline(command)}\n")

            output_file = self.run_ytdlp_command(command)

            self._set_status("status_completed")
            self._set_progress(100.0, "100%")

            final_path = output_file or self.last_output_file or str(self.download_dir)
            task_label = Path(final_path).name if final_path else self.tr("status_completed")
            self._set_task_progress(100.0, "100%", task_label)
            success_text = self.tr("info_completed_output", path=final_path)
            self._schedule(messagebox.showinfo, self.tr("app_title"), success_text)
        except JobCancelledError:
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

    def _detect_auth_error_message(self, output_lines: list[str]) -> str | None:
        joined = "\n".join(output_lines).lower()
        if any(pattern in joined for pattern in AUTH_REQUIRED_PATTERNS):
            return self.tr("error_youtube_auth_required")
        if any(pattern in joined for pattern in BROWSER_COOKIE_PATTERNS):
            return self.tr("error_browser_cookies_failed")
        return None

    def run_check_versions_job(self) -> None:
        current_ytdlp_version = ""
        latest_version_for_prompt: str | None = None
        try:
            self.ensure_environment()
            self._set_task_busy("...", self.tr("status_checking_versions"))
            self._set_status("status_checking_versions")
            self._append_log(self.tr("log_binary_path", label="yt-dlp.exe", path=YT_DLP_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffmpeg.exe", path=FFMPEG_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffprobe.exe", path=FFPROBE_PATH) + "\n")

            versions = self.collect_local_versions()
            current_ytdlp_version = versions["yt-dlp"]
            self._append_log(f"yt-dlp: {versions['yt-dlp']}\n")
            self._append_log(f"ffmpeg: {versions['ffmpeg']}\n")
            self._append_log(f"ffprobe: {versions['ffprobe']}\n")
            self.last_local_versions = dict(versions)
            self.last_latest_ytdlp_version = None
            self.last_ytdlp_up_to_date = None
            self._set_progress(70.0, "70%")
            self._set_task_progress(70.0, "70%", self.tr("status_checking_versions"))

            self._set_status("status_checking_latest_version")
            self._set_task_busy("...", self.tr("status_checking_latest_version"))
            self._append_log(self.tr("log_checking_latest_version") + "\n")
            latest_version = self.try_fetch_latest_ytdlp_version(timeout_seconds=LATEST_VERSION_TIMEOUT_SECONDS)
            if latest_version:
                self.last_latest_ytdlp_version = latest_version
                self._append_log(self.tr("log_latest_ytdlp_version", version=latest_version) + "\n")
                if self.normalize_version_text(versions["yt-dlp"]) == self.normalize_version_text(latest_version):
                    self.last_ytdlp_up_to_date = True
                    self._append_log(self.tr("log_ytdlp_up_to_date") + "\n")
                    self._append_log(self.tr("log_no_update_needed") + "\n")
                    self._set_task_progress(100.0, "100%", self.tr("status_already_up_to_date"))
                    self._set_status("status_already_up_to_date")
                else:
                    self.last_ytdlp_up_to_date = False
                    self._append_log(self.tr("log_ytdlp_update_available", version=latest_version) + "\n")
                    self._set_task_progress(100.0, "100%", self.tr("status_completed"))
                    latest_version_for_prompt = latest_version

            self._set_progress(100.0, "100%")
            if self.last_ytdlp_up_to_date is not True:
                self._set_status("status_completed")
        except Exception as exc:
            summary = self._stringify_error(exc)
            self._append_log(self.tr("log_error", error=summary) + "\n")
            self._set_status("status_error")
        finally:
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)
            if latest_version_for_prompt is not None:
                self._schedule(self.prompt_update_after_check, current_ytdlp_version, latest_version_for_prompt)

    def run_update_job(self) -> None:
        try:
            self.ensure_environment()
            if self.last_ytdlp_up_to_date is True and self.last_latest_ytdlp_version:
                self._append_log(self.tr("log_update_skipped_up_to_date") + "\n")
                self._set_progress(100.0, "100%")
                self._set_task_progress(100.0, "100%", self.tr("status_already_up_to_date"))
                self._set_status("status_already_up_to_date")
                return

            self._set_status("status_updating")
            self._set_progress(5.0, "5%")
            self._set_task_progress(5.0, "5%", self.tr("status_updating_ytdlp"))

            update_command = [str(YT_DLP_PATH), "-U"]
            self._append_log(self.tr("log_binary_path", label="yt-dlp.exe", path=YT_DLP_PATH) + "\n")
            self._append_log(f"Command: {subprocess.list2cmdline(update_command)}\n")
            self.run_logged_command(update_command, PROJECT_ROOT, "yt-dlp -U")
            self._set_progress(35.0, "35%")
            self._set_task_progress(35.0, "35%", self.tr("status_updating_ytdlp"))

            self._append_log(self.tr("log_binary_path", label="ffmpeg.exe", path=FFMPEG_PATH) + "\n")
            self._append_log(self.tr("log_binary_path", label="ffprobe.exe", path=FFPROBE_PATH) + "\n")
            self._set_task_busy("...", "ffmpeg")
            self.update_ffmpeg_binaries()
            self._set_progress(90.0, "90%")
            self._set_task_progress(90.0, "90%", "ffmpeg")

            versions = self.collect_local_versions()
            self.last_local_versions = dict(versions)
            self._append_log(f"yt-dlp: {versions['yt-dlp']}\n")
            self._append_log(f"ffmpeg: {versions['ffmpeg']}\n")
            self._append_log(f"ffprobe: {versions['ffprobe']}\n")
            if self.last_latest_ytdlp_version:
                self.last_ytdlp_up_to_date = (
                    self.normalize_version_text(versions["yt-dlp"])
                    == self.normalize_version_text(self.last_latest_ytdlp_version)
                )
            self._append_log(self.tr("log_update_complete") + "\n")
            self._set_progress(100.0, "100%")
            self._set_task_progress(100.0, "100%", self.tr("status_update_complete"))
            self._set_status("status_update_complete")
        except Exception as exc:
            summary = self._stringify_error(exc)
            self._append_log(self.tr("log_error", error=summary) + "\n")
            self._set_status("status_update_failed")
        finally:
            self.current_process = None
            self.current_job_kind = None
            self.cancel_requested = False
            self.current_job_started_at = 0.0
            self._schedule(self._set_running_state_ui, False)

    def collect_local_versions(self) -> dict[str, str]:
        versions = {
            "yt-dlp": self.get_command_version("yt-dlp", [str(YT_DLP_PATH), "--version"]),
            "ffmpeg": self.get_command_version("ffmpeg", [str(FFMPEG_PATH), "-version"]),
            "ffprobe": self.get_command_version("ffprobe", [str(FFPROBE_PATH), "-version"]),
        }
        return versions

    def get_command_version(self, label: str, command: list[str]) -> str:
        lines = self.run_logged_command(command, PROJECT_ROOT, f"{label} version", log_output=False)
        version = self.extract_tool_version(label, lines)
        if version:
            return version
        raise AppError(f"Failed to detect {label} version.")

    def extract_tool_version(self, label: str, lines: list[str]) -> str | None:
        for line in lines:
            candidate = line.strip()
            if not candidate:
                continue
            if label == "yt-dlp":
                return self.normalize_version_text(candidate)

            prefix = f"{label} version "
            if candidate.lower().startswith(prefix):
                version_text = candidate[len(prefix):].split(maxsplit=1)[0]
                return self.normalize_version_text(version_text)
        return None

    def normalize_version_text(self, version_text: str) -> str:
        normalized = version_text.strip().lstrip("v")
        for marker in ("-full_build", "-essentials_build", "-www.gyan.dev"):
            if marker in normalized:
                normalized = normalized.split(marker, 1)[0]
        return normalized

    def try_fetch_latest_ytdlp_version(self, timeout_seconds: int = LATEST_VERSION_TIMEOUT_SECONDS) -> str | None:
        try:
            return self.fetch_latest_ytdlp_version(timeout_seconds=timeout_seconds)
        except Exception as exc:
            if self.is_timeout_error(exc):
                self._append_log(self.tr("log_latest_version_api_timeout_fallback") + "\n")
                try:
                    return self.fetch_latest_ytdlp_version_from_release_page(timeout_seconds=timeout_seconds)
                except Exception as fallback_exc:
                    self._append_log(
                        self.tr("log_latest_version_check_skipped", error=self._stringify_error(fallback_exc)) + "\n"
                    )
                    return None
            self._append_log(self.tr("log_latest_version_check_skipped", error=self._stringify_error(exc)) + "\n")
            return None

    def fetch_latest_ytdlp_version(self, timeout_seconds: int = LATEST_VERSION_TIMEOUT_SECONDS) -> str:
        payload = self.fetch_json(YTDLP_LATEST_RELEASE_API, timeout_seconds=timeout_seconds)
        latest = payload.get("tag_name")
        if not isinstance(latest, str) or not latest.strip():
            raise AppError("GitHub API did not return tag_name for yt-dlp.")
        return self.normalize_version_text(latest)

    def fetch_latest_ytdlp_version_from_release_page(
        self,
        timeout_seconds: int = LATEST_VERSION_TIMEOUT_SECONDS,
    ) -> str:
        final_url = self.fetch_final_url(YTDLP_LATEST_RELEASE_PAGE, timeout_seconds=timeout_seconds)
        match = re.search(r"/releases/tag/(?P<tag>[^/?#]+)", final_url)
        if not match:
            raise AppError(f"GitHub releases page did not redirect to a release tag: {final_url}")
        return self.normalize_version_text(urllib.parse.unquote(match.group("tag")))

    def is_timeout_error(self, exc: BaseException) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if isinstance(current, TimeoutError):
                return True
            message = str(current).lower()
            if "timed out" in message or "timeout" in message:
                return True
            current = current.__cause__ or current.__context__
        return False

    def update_ffmpeg_binaries(self) -> None:
        asset_name = "ffmpeg-release-essentials.zip"
        asset_url = FFMPEG_WINDOWS_BUILD_URL
        self._append_log(f"ffmpeg: downloading {asset_name}\n")

        with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            archive_path = temp_dir / asset_name
            self.download_file(asset_url, archive_path, "ffmpeg")
            self._set_progress(70.0, "70%")

            ffmpeg_source = self.extract_binary_from_zip(archive_path, "ffmpeg.exe", temp_dir)
            ffprobe_source = self.extract_binary_from_zip(archive_path, "ffprobe.exe", temp_dir)
            self.replace_binary(ffmpeg_source, FFMPEG_PATH)
            self.replace_binary(ffprobe_source, FFPROBE_PATH)

    def fetch_json(self, url: str, timeout_seconds: int = NETWORK_TIMEOUT_SECONDS) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{APP_TITLE}/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise AppError(f"Request failed for {url}: {exc}") from exc
        except Exception as exc:
            raise AppError(f"Failed to fetch {url}: {exc}") from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AppError(f"Invalid JSON from {url}: {exc}") from exc

        if not isinstance(data, dict):
            raise AppError(f"Unexpected API response from {url}.")
        return data

    def fetch_final_url(self, url: str, timeout_seconds: int = NETWORK_TIMEOUT_SECONDS) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"{APP_TITLE}/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.geturl()
        except urllib.error.URLError as exc:
            raise AppError(f"Request failed for {url}: {exc}") from exc
        except Exception as exc:
            raise AppError(f"Failed to fetch {url}: {exc}") from exc

    def download_file(self, url: str, destination: Path, label: str) -> None:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"{APP_TITLE}/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                total = int(response.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                last_reported = -10
                with destination.open("wb") as output_file:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            percent = int(downloaded * 100 / total)
                            if percent >= last_reported + 10:
                                last_reported = percent
                                self._append_log(f"{label}: {percent}%\n")
        except urllib.error.URLError as exc:
            raise AppError(f"Failed to download {label}: {exc}") from exc
        except Exception as exc:
            raise AppError(f"Failed to write {destination}: {exc}") from exc

        self._append_log(f"{label}: downloaded {destination}\n")

    def extract_binary_from_zip(self, archive_path: Path, binary_name: str, temp_dir: Path) -> Path:
        binary_name_lower = binary_name.lower()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                member_name = next(
                    (
                        name
                        for name in archive.namelist()
                        if name.lower().endswith(f"/bin/{binary_name_lower}") or name.lower().endswith(f"/{binary_name_lower}")
                    ),
                    None,
                )
                if member_name is None:
                    raise AppError(f"{binary_name} was not found in {archive_path.name}.")

                target_path = temp_dir / binary_name
                with archive.open(member_name) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        except zipfile.BadZipFile as exc:
            raise AppError(f"Invalid zip archive: {archive_path}") from exc
        except Exception as exc:
            if isinstance(exc, AppError):
                raise
            raise AppError(f"Failed to extract {binary_name} from {archive_path.name}: {exc}") from exc

        self._append_log(f"{binary_name}: extracted\n")
        return target_path

    def replace_binary(self, source_path: Path, target_path: Path) -> None:
        temp_target = target_path.with_suffix(target_path.suffix + ".new")
        try:
            shutil.copyfile(source_path, temp_target)
            os.replace(temp_target, target_path)
        except Exception as exc:
            try:
                if temp_target.exists():
                    temp_target.unlink()
            except Exception:
                pass
            raise AppError(f"Failed to replace {target_path.name}: {exc}") from exc

        self._append_log(f"{target_path.name}: updated\n")

    def ensure_environment(self) -> None:
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise AppError(self.tr("error_tools_dir_missing", path=TOOLS_DIR)) from exc

        if not TOOLS_DIR.is_dir():
            raise AppError(self.tr("error_tools_dir_not_folder", path=TOOLS_DIR))

        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise AppError(self.tr("error_create_downloads_folder", path=self.download_dir, error=exc)) from exc

        self.ensure_tools_present()

    def ensure_tools_present(self) -> None:
        missing: list[str] = []
        for label, path in (("yt-dlp.exe", YT_DLP_PATH), ("ffmpeg.exe", FFMPEG_PATH), ("ffprobe.exe", FFPROBE_PATH)):
            if not path.exists():
                missing.append(label)
                continue
            if not path.is_file():
                raise AppError(self.tr("error_required_binary_not_file", label=label, path=path))

        if not missing:
            return

        if "yt-dlp.exe" in missing:
            with tempfile.TemporaryDirectory(prefix="mini-url-converter-") as temp_dir_text:
                temp_dir = Path(temp_dir_text)
                yt_tmp = temp_dir / "yt-dlp.exe"
                self._append_log("yt-dlp: downloading latest binary...\n")
                self.download_file(YTDLP_WINDOWS_DOWNLOAD_URL, yt_tmp, "yt-dlp")
                self.replace_binary(yt_tmp, YT_DLP_PATH)

        if "ffmpeg.exe" in missing or "ffprobe.exe" in missing:
            self.update_ffmpeg_binaries()

    def ensure_required_binary(self, label: str, path: Path) -> None:
        if not path.exists():
            raise AppError(self.tr("error_required_binary_missing", label=label, path=path))
        if not path.is_file():
            raise AppError(self.tr("error_required_binary_not_file", label=label, path=path))

    def build_command(self, url: str) -> list[str]:
        command = [
            str(YT_DLP_PATH),
            "--ffmpeg-location",
            str(TOOLS_DIR),
            "--force-overwrites",
            # yt-dlp.exe may otherwise use the active Windows code page when
            # stdout is redirected to a pipe. The parent decodes as UTF-8.
            "--encoding",
            "utf-8",
        ]

        if bool(self.ytdlp_settings["restrict_filenames"]):
            command.append("--restrict-filenames")
        if bool(self.ytdlp_settings["windows_filenames"]):
            command.append("--windows-filenames")

        command.extend(
            [
            "-P",
            str(self.download_dir),
            "-o",
            str(self.ytdlp_settings["output_template"]),
            "--progress",
            "--newline",
            "--print",
            "after_move:__MUC_OUTPUT__:%(filepath)s",
            ]
        )

        command.extend(["-R", str(self.ytdlp_settings["retries"])])
        command.extend(["--retry-sleep", str(self.ytdlp_settings["retry_sleep"])])

        output_mode = str(self.ytdlp_settings["output_mode"])
        if output_mode == "mp3":
            command.extend(["-f", "bestaudio/best"])
            command.extend(["--extract-audio", "--audio-format", "mp3", "--audio-quality", MP3_AUDIO_QUALITY])
        else:
            preset = str(self.ytdlp_settings["format_preset"])
            selector_table = MP4_FORMAT_SELECTORS if output_mode == "mp4" else FORMAT_SELECTORS
            format_selector = selector_table.get(preset)
            if format_selector:
                command.extend(["-f", format_selector])

        if output_mode == "mp4":
            # Streams are already selected as AVC/H.264 + M4A/AAC. ffmpeg only
            # remuxes them into MP4 (normally a few seconds, without quality loss).
            command.extend(["--merge-output-format", "mp4", "--remux-video", "mp4"])
        elif output_mode == "mkv":
            command.extend(["--merge-output-format", "mkv", "--remux-video", "mkv"])

        self._append_auth_arguments(command)
        command.append(url)
        return command

    def _append_auth_arguments(self, command: list[str]) -> None:
        auth_mode = str(self.ytdlp_settings.get("auth_mode", "none"))
        if auth_mode == "browser":
            command.extend(["--cookies-from-browser", str(self.ytdlp_settings["cookies_browser"])])
        elif auth_mode == "file":
            command.extend(["--cookies", str(self._resolve_cookies_file_path())])

    def _resolve_cookies_file_path(self) -> Path:
        raw = str(self.ytdlp_settings.get("cookies_file", "")).strip()
        if not raw:
            raise AppError(self.tr("error_cookies_file_empty"))
        candidate = Path(raw).expanduser()
        if not candidate.is_file():
            raise AppError(self.tr("error_cookies_file_missing", path=candidate))
        return candidate

    def run_logged_command(
        self,
        command: list[str],
        cwd: Path,
        command_label: str,
        line_handler: Callable[[str], None] | None = None,
        log_output: bool = True,
        allow_cancel: bool = False,
    ) -> list[str]:
        try:
            creationflags = CREATE_NO_WINDOW | (CREATE_NEW_PROCESS_GROUP if allow_cancel else 0)
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            executable_path = Path(command[0]) if command else Path(command_label)
            raise AppError(
                self.tr(
                    "error_required_binary_missing",
                    label=executable_path.name or command_label,
                    path=executable_path,
                )
            ) from exc
        except Exception as exc:
            raise AppError(self.tr("error_failed_start_command", label=command_label, error=exc)) from exc

        self.current_process = process
        if allow_cancel:
            self._schedule(self._set_cancel_button_state, True)
        lines: list[str] = []

        try:
            output_stream = process.stdout
            if output_stream is None:
                raise AppError(f"{command_label} stdout pipe was not created.")
            for raw_line in output_stream:
                line = self.clean_output_line(raw_line)
                if not line:
                    continue
                lines.append(line)
                if log_output:
                    self._append_log(line + "\n")
                if line_handler is not None:
                    line_handler(line)

            return_code = process.wait()
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if self.current_process is process:
                self.current_process = None

        if return_code != 0:
            if allow_cancel and self.cancel_requested:
                raise JobCancelledError(self.tr("log_download_cancelled"))
            raise CommandExecutionError(
                self.tr("error_command_exit_code", label=command_label, code=return_code),
                return_code,
                lines,
            )

        return lines

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        output_file: str | None = None

        def handle_line(line: str) -> None:
            nonlocal output_file
            detected_output = self.parse_progress(line)
            if detected_output:
                output_file = detected_output

        self.run_logged_command(command, PROJECT_ROOT, "yt-dlp", handle_line, allow_cancel=True)
        return output_file

    def extract_version_text(self, lines: list[str]) -> str | None:
        for line in reversed(lines):
            candidate = line.strip()
            if candidate:
                return candidate
        return None

    def parse_progress(self, line: str) -> str | None:
        match = FINAL_PATH_RE.match(line)
        if match:
            self.last_output_file = self.resolve_output_path(match.group("path"))
            self._track_run_artifact(self.last_output_file)
            return self.last_output_file

        match = PROGRESS_RE.search(line)
        if match:
            pct = float(match.group("pct"))
            task_label = (
                Path(self.current_download_destination).name
                if self.current_download_destination
                else self.tr("status_downloading")
            )
            self._set_task_progress(pct, f"{pct:.1f}%", task_label)
            download_index = max(0, len(self.download_destinations) - 1)
            if download_index == 0:
                total_value = pct * 0.45
            elif download_index == 1:
                total_value = 45.0 + (pct * 0.45)
            else:
                total_value = 90.0
            total_value = max(self.total_progress_value, min(90.0, total_value))
            self._set_progress(total_value, f"{total_value:.0f}%")
            self._set_status("status_downloading")
            return None

        match = DEST_RE.search(line)
        if match:
            self.last_output_file = self.resolve_output_path(match.group("path"))
            if not self.download_destinations or self.download_destinations[-1] != self.last_output_file:
                self.download_destinations.append(self.last_output_file)
            self.current_download_destination = self.last_output_file
            self._track_run_artifact(self.last_output_file, include_temp_files=True)
            task_label = Path(self.last_output_file).name
            total_value = min(90.0, max(self.total_progress_value, (len(self.download_destinations) - 1) * 45.0))
            self._set_progress(total_value, f"{total_value:.0f}%")
            self._set_task_progress(0.0, "0%", task_label)
            self._set_status("status_writing_file")
            return self.last_output_file

        match = MERGE_RE.search(line)
        if match:
            self.last_output_file = self.resolve_output_path(match.group("path"))
            self._track_run_artifact(self.last_output_file)
            task_label = Path(self.last_output_file).name
            self._set_progress(max(self.total_progress_value, 92.0), "92%")
            self._set_task_busy("...", task_label)
            self._set_status("status_merging_streams")
            return self.last_output_file

        match = RECODE_RE.search(line)
        if match:
            candidate = self.resolve_output_path(match.group("path"))
            if candidate.lower().endswith(".mp4"):
                self.last_output_file = candidate
                self._track_run_artifact(self.last_output_file)
            task_label = Path(self.last_output_file).name if self.last_output_file else self.tr("status_converting_mp4")
            if "not converting media file" in line.lower():
                self._set_progress(max(self.total_progress_value, 98.0), "98%")
                self._set_task_progress(100.0, "100%", task_label)
            else:
                self._set_progress(max(self.total_progress_value, 97.0), "97%")
                self._set_task_busy("...", task_label)
            self._set_status("status_converting_mp4")
            return self.last_output_file

        match = ALREADY_RE.search(line)
        if match:
            self.last_output_file = self.resolve_output_path(match.group("path"))
            self._track_run_artifact(self.last_output_file)
            task_label = Path(self.last_output_file).name
            self._set_progress(100.0, "100%")
            self._set_task_progress(100.0, "100%", task_label)
            self._set_status("status_already_downloaded")
            return self.last_output_file

        lower_line = line.lower()
        if "[download]" in line:
            self._set_status("status_downloading")
        elif "[merger]" in lower_line:
            task_label = Path(self.last_output_file).name if self.last_output_file else self.tr("status_merging_streams")
            self._set_progress(max(self.total_progress_value, 92.0), "92%")
            self._set_task_busy("...", task_label)
            self._set_status("status_merging_streams")
        elif "[videoconvertor]" in lower_line or "video conversion" in lower_line:
            task_label = Path(self.last_output_file).name if self.last_output_file else self.tr("status_converting_mp4")
            self._set_progress(max(self.total_progress_value, 97.0), "97%")
            self._set_task_busy("...", task_label)
            self._set_status("status_converting_mp4")
        elif "deleting original file" in lower_line:
            task_label = Path(self.last_output_file).name if self.last_output_file else self.tr("status_cleaning_up")
            self._set_progress(max(self.total_progress_value, 99.0), "99%")
            self._set_task_busy("...", task_label)
            self._set_status("status_cleaning_up")

        return None

    def clean_output_line(self, raw_line: str) -> str:
        line = raw_line.replace("\r", "").replace("\x00", "")
        line = ANSI_RE.sub("", line)
        return line.rstrip("\n")

    def resolve_output_path(self, raw_path: str) -> str:
        path_text = raw_path.strip().strip('"')
        if not path_text:
            return str(self.download_dir)

        candidate = Path(path_text)
        if candidate.is_absolute():
            return str(candidate)

        if path_text.startswith(".\\") or path_text.startswith("./"):
            candidate = Path(path_text[2:])
        elif path_text.startswith("\\") or path_text.startswith("/"):
            return path_text

        return str((self.download_dir / candidate).resolve(strict=False))

    def build_error_dialog(self, summary: str) -> str:
        recent = "\n".join(self.recent_log_lines).strip()
        if recent:
            return self.tr("error_last_log_lines", summary=summary, count=len(self.recent_log_lines), lines=recent)
        return summary

    def _append_log(self, text: str) -> None:
        for line in text.splitlines():
            if line.strip():
                self.recent_log_lines.append(line)
        self._schedule(self._append_log_ui, text)

    def _append_log_now(self, text: str) -> None:
        for line in text.splitlines():
            if line.strip():
                self.recent_log_lines.append(line)
        try:
            self._append_log_ui(text)
            self.root.update_idletasks()
        except tk.TclError:
            pass

    def _append_log_ui(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_log_ui(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")

    def _set_status(self, value: str, **kwargs: object) -> None:
        if value in TRANSLATIONS["en"]:
            self.current_status_key = value
            self.current_status_kwargs = kwargs
            text = self.tr(value, **kwargs)
        else:
            self.current_status_key = ""
            self.current_status_kwargs = {}
            text = value
        self._schedule(self.status_var.set, text)

    def _set_progress(self, value: float, label: str) -> None:
        self._schedule(self._apply_progress, value, label)

    def _apply_progress(self, value: float, label: str) -> None:
        clamped = max(0.0, min(100.0, value))
        self.total_progress_value = clamped
        self._render_progress_canvas(self.progress_bar, self.progress_bar_fill, clamped)
        self.progress_text_var.set(label)

    def _set_task_progress(self, value: float, label: str, task_label: str = "") -> None:
        self._schedule(self._apply_task_progress, value, label, task_label)

    def _apply_task_progress(self, value: float, label: str, task_label: str = "") -> None:
        clamped = max(0.0, min(100.0, value))
        self._stop_task_busy_animation()
        self.task_progress_mode = "determinate"
        self.task_progress_value = clamped
        self._render_progress_canvas(self.task_progress_bar, self.task_progress_bar_fill, clamped)
        self.task_progress_text_var.set(label)
        self.task_status_var.set(task_label)

    def _set_task_busy(self, label: str, task_label: str = "") -> None:
        self._schedule(self._apply_task_busy, label, task_label)

    def _apply_task_busy(self, label: str, task_label: str = "") -> None:
        self.task_progress_mode = "indeterminate"
        self.task_progress_value = 0.0
        self.task_progress_text_var.set(label)
        self.task_status_var.set(task_label)
        self.task_progress_busy_offset = 0
        self._render_task_busy_frame()
        if self.task_progress_busy_job is None:
            self.task_progress_busy_job = self.root.after(60, self._animate_task_progress_busy)

    def _reset_progress_state(self) -> None:
        self.download_destinations.clear()
        self.current_download_destination = None
        self.run_artifacts.clear()
        self._stop_task_busy_animation()
        self._apply_progress(0.0, "0%")
        self._apply_task_progress(0.0, "0%", "")

    def _track_run_artifact(self, path_text: str, include_temp_files: bool = False) -> None:
        normalized_path = str(Path(path_text).resolve(strict=False))
        if normalized_path not in self.run_artifacts:
            self.run_artifacts[normalized_path] = Path(normalized_path).exists()
        if include_temp_files:
            for suffix in (".part", ".ytdl"):
                temp_path = normalized_path + suffix
                if temp_path not in self.run_artifacts:
                    self.run_artifacts[temp_path] = Path(temp_path).exists()

    def _is_temporary_download_file(self, path: Path) -> bool:
        name = path.name.lower()
        return name.endswith(".part") or ".part-" in name or name.endswith(".ytdl")

    def _artifact_belongs_to_current_job(self, path: Path) -> bool:
        started_at = self.current_job_started_at
        if started_at <= 0:
            return False
        try:
            return path.stat().st_mtime >= started_at - 2.0
        except OSError:
            return False

    def cleanup_cancelled_downloads(self) -> None:
        removed_any = False
        removed_paths: set[str] = set()
        for path_text, existed_before in sorted(self.run_artifacts.items(), key=lambda item: len(item[0]), reverse=True):
            candidate = Path(path_text)
            should_remove_existing = (
                not existed_before
                or (self._is_temporary_download_file(candidate) and self._artifact_belongs_to_current_job(candidate))
            )
            try:
                if should_remove_existing and candidate.exists() and candidate.is_file():
                    candidate.unlink()
                    removed_any = True
                    removed_paths.add(str(candidate.resolve(strict=False)))
                    self._append_log(self.tr("log_cancel_removed_file", path=candidate) + "\n")
            except Exception as exc:
                self._append_log(self.tr("log_cancel_cleanup_failed", path=candidate, error=exc) + "\n")

        try:
            download_dir_entries = list(self.download_dir.iterdir())
        except Exception:
            download_dir_entries = []

        for candidate in download_dir_entries:
            normalized_candidate = str(candidate.resolve(strict=False))
            if normalized_candidate in removed_paths:
                continue
            if not candidate.is_file():
                continue
            if not self._is_temporary_download_file(candidate):
                continue
            if not self._artifact_belongs_to_current_job(candidate):
                continue
            try:
                candidate.unlink()
                removed_any = True
                removed_paths.add(normalized_candidate)
                self._append_log(self.tr("log_cancel_removed_file", path=candidate) + "\n")
            except Exception as exc:
                self._append_log(self.tr("log_cancel_cleanup_failed", path=candidate, error=exc) + "\n")

        if not removed_any:
            self._append_log(self.tr("log_cancel_no_files") + "\n")

    def on_total_progress_resize(self, event: tk.Event[tk.Misc]) -> None:
        del event
        self._render_progress_canvas(self.progress_bar, self.progress_bar_fill, self.total_progress_value)

    def on_task_progress_resize(self, event: tk.Event[tk.Misc]) -> None:
        del event
        if self.task_progress_mode == "indeterminate":
            self._render_task_busy_frame()
        else:
            self._render_progress_canvas(self.task_progress_bar, self.task_progress_bar_fill, self.task_progress_value)

    def _render_progress_canvas(self, canvas: tk.Canvas, fill_id: int, value: float) -> None:
        width = max(0, canvas.winfo_width())
        height = max(0, canvas.winfo_height())
        if width <= 1 or height <= 1:
            return
        fill_width = width * max(0.0, min(100.0, value)) / 100.0
        canvas.coords(fill_id, 0, 0, fill_width, height)

    def _render_task_busy_frame(self) -> None:
        width = max(0, self.task_progress_bar.winfo_width())
        height = max(0, self.task_progress_bar.winfo_height())
        if width <= 1 or height <= 1:
            return
        segment_width = max(24, width // 5)
        offset = self.task_progress_busy_offset
        start = max(0, offset - segment_width)
        end = min(width, offset)
        self.task_progress_bar.coords(self.task_progress_bar_fill, start, 0, end, height)

    def _animate_task_progress_busy(self) -> None:
        self.task_progress_busy_job = None
        if self.closing or self.task_progress_mode != "indeterminate":
            return
        width = max(1, self.task_progress_bar.winfo_width())
        segment_width = max(24, width // 5)
        max_offset = width + segment_width
        step = max(8, width // 18)
        self.task_progress_busy_offset = (self.task_progress_busy_offset + step) % max_offset
        self._render_task_busy_frame()
        self.task_progress_busy_job = self.root.after(60, self._animate_task_progress_busy)

    def _stop_task_busy_animation(self) -> None:
        job = self.task_progress_busy_job
        self.task_progress_busy_job = None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _set_running_state_ui(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.check_versions_button.configure(state=state)
        self.settings_button.configure(state=state)
        self.url_entry.configure(state=state)
        self.choose_folder_button.configure(state=state)
        if not running:
            self._set_cancel_button_state(False)

    def _set_cancel_button_state(self, enabled: bool) -> None:
        if enabled:
            self.cancel_button.configure(
                state="normal",
                bg="#c62828",
                fg="white",
                activebackground="#a61f1f",
                activeforeground="white",
                disabledforeground="#e0e0e0",
                relief="raised",
                bd=1,
                cursor="hand2",
            )
            return

        neutral_bg = self.root.cget("bg")
        self.cancel_button.configure(
            state="disabled",
            bg=neutral_bg,
            fg="#6f6f6f",
            activebackground=neutral_bg,
            activeforeground="#6f6f6f",
            disabledforeground="#6f6f6f",
            relief="flat",
            bd=0,
            cursor="arrow",
        )

    def _schedule(self, callback, *args) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, callback, *args)
        except tk.TclError:
            pass

    def _stop_current_process(self) -> None:
        process = self.current_process
        if process is None:
            return
        pid = process.pid
        try:
            if process.poll() is not None:
                return
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                check=False,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass

    def _stringify_error(self, exc: Exception) -> str:
        text = str(exc).strip()
        if text:
            return text
        return exc.__class__.__name__


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
