from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import auth_policy as previous
import launcher as launcher_layer
import mini_url_converter as core
import runtime as runtime_layer
from version import APP_VERSION


# TEMPORARILY DISABLED FOR THE CURRENT RELEASE.
# yt-dlp cannot currently decrypt cookies from modern Chromium profiles on this
# Windows/Chrome setup (DPAPI/App-Bound encryption). Keep the automatic auth
# implementation in the codebase so it can be restored when upstream support
# improves, but do not expose it in the UI for now.
#
# core.AUTH_MODE_CHOICES = ("auto", "browser", "file", "none")
# core.YTDLP_DEFAULTS["auth_mode"] = "auto"
core.AUTH_MODE_CHOICES = ("none",)
core.YTDLP_DEFAULTS["auth_mode"] = "none"
core.YTDLP_DEFAULTS["cookies_browser"] = "firefox"


PRESETS: tuple[tuple[str, str, str], ...] = (
    ("mp4_1080", "mp4", "1080p"),
    ("mp4_720", "mp4", "720p"),
    ("mp3", "mp3", "best"),
    ("mkv", "mkv", "best"),
    ("original", "original", "best"),
)

FFMPEG_TIME_RE = re.compile(r"\btime=(?P<h>\d+):(?P<m>\d+):(?P<s>\d+(?:\.\d+)?)")

UI_TEXT = {
    "en": {
        "download": "Download",
        "quick_presets": "Quick presets",
        "preset_mp4_1080": "MP4 1080p",
        "preset_mp4_720": "MP4 720p",
        "preset_mp3": "MP3",
        "preset_mkv": "MKV",
        "preset_original": "Original",
        "overall_progress": "Overall progress — {value}",
        "details_log": "Detailed log",
        "cookies_title": "YouTube cookies",
        "cookies_missing": "Cookies are not saved. Public videos work without them.",
        "cookies_saved": "Cookies are saved and will be used automatically only when YouTube requires sign-in.",
        "cookies_invalid": "Saved cookies were rejected. Import a fresh cookies.txt.",
        "cookies_import": "Import / replace cookies.txt",
        "cookies_remove": "Remove cookies",
        "cookies_remove_confirm": "Remove the saved YouTube cookies?",
        "cookies_required": "This video requires YouTube sign-in. Select a fresh cookies.txt to continue.",
        "cookies_required_title": "YouTube sign-in required",
        "cookies_retry_failed": "YouTube rejected the selected cookies.txt. Export fresh cookies and try again.",
        "advanced": "Advanced settings",
        "service": "Application",
        "check_updates": "Check for updates",
        "open_folder": "Open downloads folder",
        "settings": "Settings",
    },
    "ru": {
        "download": "Скачать",
        "quick_presets": "Быстрые пресеты",
        "preset_mp4_1080": "MP4 1080p",
        "preset_mp4_720": "MP4 720p",
        "preset_mp3": "MP3",
        "preset_mkv": "MKV",
        "preset_original": "Оригинал",
        "overall_progress": "Общий прогресс — {value}",
        "details_log": "Подробный лог",
        "cookies_title": "Cookies YouTube",
        "cookies_missing": "Cookies не сохранены. Для обычных видео они не нужны.",
        "cookies_saved": "Cookies сохранены и будут использованы автоматически только если YouTube потребует вход.",
        "cookies_invalid": "Сохранённые cookies были отклонены. Импортируйте свежий cookies.txt.",
        "cookies_import": "Импортировать / заменить cookies.txt",
        "cookies_remove": "Удалить cookies",
        "cookies_remove_confirm": "Удалить сохранённые cookies YouTube?",
        "cookies_required": "Для этого видео требуется вход в YouTube. Выберите свежий cookies.txt, чтобы продолжить.",
        "cookies_required_title": "Требуется вход в YouTube",
        "cookies_retry_failed": "YouTube отклонил выбранный cookies.txt. Экспортируйте свежие cookies и попробуйте снова.",
        "advanced": "Расширенные настройки",
        "service": "Приложение",
        "check_updates": "Проверить обновления",
        "open_folder": "Открыть папку загрузок",
        "settings": "Настройки",
    },
}


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._preset_buttons: dict[str, tk.Button] = {}
        self._flag_canvases: dict[str, tk.Canvas] = {}
        self._log_expanded = True
        self._media_duration_seconds = 0.0
        super().__init__(root)
        self.root.geometry("820x650")
        self.root.minsize(720, 570)
        if hasattr(self, "transfer_status_label"):
            self.transfer_status_label.pack_forget()
        self._migrate_saved_cookie_path()
        self._refresh_preset_styles()
        self._refresh_flag_styles()

    def ui(self, key: str, **kwargs: object) -> str:
        language = self.language if self.language in UI_TEXT else "en"
        template = UI_TEXT[language].get(key) or UI_TEXT["en"].get(key) or key
        return template.format(**{name: str(value) for name, value in kwargs.items()})

    def load_ytdlp_settings(self, data: dict[str, object]) -> dict[str, object]:
        settings = super().load_ytdlp_settings(data)
        # The release UI no longer exposes auth modes. Public downloads always
        # run without cookies first; saved cookies.txt is an automatic fallback.
        settings["auth_mode"] = "none"
        return settings

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, padding=(18, 14, 18, 12))
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        flags = ttk.Frame(header)
        flags.grid(row=0, column=1, sticky="e")
        self._flag_canvases["ru"] = self._make_flag(flags, "ru")
        self._flag_canvases["en"] = self._make_flag(flags, "en")
        self.settings_button = ttk.Button(flags, text="⚙", width=3, command=self.open_settings_dialog)
        self.settings_button.pack(side="left", padx=(6, 0))

        self.url_label = ttk.Label(shell, font=("Segoe UI", 10, "bold"))
        self.url_label.pack(anchor="w")

        url_row = ttk.Frame(shell)
        url_row.pack(fill="x", pady=(5, 12))
        self.url_entry_border = tk.Frame(url_row, bg="#cfd8dc", bd=1, highlightthickness=0)
        self.url_entry_border.pack(side="left", fill="x", expand=True)
        self.url_entry = ttk.Entry(self.url_entry_border, textvariable=self.url_var, font=("Segoe UI", 11))
        self.url_entry.pack(fill="x", expand=True, ipady=5)
        self.url_entry.focus_set()
        self.url_entry.bind("<Return>", self.on_start)
        self.url_entry.bind("<Control-KeyPress>", self.on_url_control_keypress)
        self.url_entry.bind("<Shift-Insert>", self.on_url_paste)
        self.url_entry.bind("<Button-3>", self.show_url_context_menu)
        self.url_entry.bind("<KeyPress>", self.on_url_entry_interaction, add="+")
        self.url_entry.bind("<Button-1>", self.on_url_entry_interaction, add="+")

        self.start_button = tk.Button(
            url_row,
            command=self.on_start,
            bg="#2e9d3d",
            fg="white",
            activebackground="#278734",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            padx=22,
            pady=6,
            relief="flat",
            bd=0,
            cursor="hand2",
        )
        self.start_button.pack(side="left", padx=(10, 0))
        self.cancel_button = tk.Button(
            url_row,
            command=self.on_cancel_job,
            font=("Segoe UI", 10),
            padx=14,
            pady=6,
            relief="flat",
            bd=0,
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self._set_cancel_button_state(False)

        self.url_context_menu = tk.Menu(self.root, tearoff=False)
        self.url_context_menu.add_command(label="Paste", command=self.paste_into_url_entry)
        self.url_error_label = tk.Label(
            shell,
            textvariable=self.url_error_var,
            fg="#b71c1c",
            bg=self.root.cget("bg"),
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )

        self.download_dir_label = ttk.Label(shell, font=("Segoe UI", 10))
        self.download_dir_label.pack(anchor="w")
        folder_row = ttk.Frame(shell)
        folder_row.pack(fill="x", pady=(5, 14))
        self.download_dir_entry = ttk.Entry(folder_row, textvariable=self.download_dir_var, state="readonly", font=("Segoe UI", 10))
        self.download_dir_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.choose_folder_button = ttk.Button(folder_row, command=self.choose_folder)
        self.choose_folder_button.pack(side="left", padx=(10, 0))

        self.preset_title = ttk.Label(shell, font=("Segoe UI", 11, "bold"))
        self.preset_title.pack(anchor="w", pady=(0, 6))
        preset_row = ttk.Frame(shell)
        preset_row.pack(fill="x", pady=(0, 16))
        for index, (key, _mode, _quality) in enumerate(PRESETS):
            preset_row.columnconfigure(index, weight=1)
            button = tk.Button(
                preset_row,
                command=lambda preset=key: self.select_preset(preset),
                font=("Segoe UI", 10),
                padx=10,
                pady=8,
                relief="solid",
                bd=1,
                cursor="hand2",
            )
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0))
            self._preset_buttons[key] = button

        ttk.Separator(shell, orient="horizontal").pack(fill="x", pady=(0, 14))

        self.progress_frame = ttk.Frame(shell)
        self.progress_frame.pack(fill="x")
        self.overall_title_var = tk.StringVar(value="")
        overall_header = ttk.Frame(self.progress_frame)
        overall_header.pack(fill="x")
        ttk.Label(overall_header, textvariable=self.overall_title_var, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(overall_header, textvariable=self.progress_text_var).pack(side="right")
        self.progress_bar = tk.Canvas(self.progress_frame, height=8, bg="#dfe5eb", bd=0, highlightthickness=0)
        self.progress_bar.pack(fill="x", pady=(5, 12))
        self.progress_bar_fill = self.progress_bar.create_rectangle(0, 0, 0, 8, fill="#28a745", outline="")
        self.progress_bar.bind("<Configure>", self.on_total_progress_resize)

        stage_header = ttk.Frame(self.progress_frame)
        stage_header.pack(fill="x")
        self.stage_status_label = ttk.Label(stage_header, textvariable=self.task_status_var, font=("Segoe UI", 10))
        self.stage_status_label.pack(side="left")
        ttk.Label(stage_header, textvariable=self.task_progress_text_var).pack(side="right")
        self.task_progress_bar = tk.Canvas(self.progress_frame, height=7, bg="#dfe5eb", bd=0, highlightthickness=0)
        self.task_progress_bar.pack(fill="x", pady=(5, 8))
        self.task_progress_bar_fill = self.task_progress_bar.create_rectangle(0, 0, 0, 7, fill="#388be6", outline="")
        self.task_progress_bar.bind("<Configure>", self.on_task_progress_resize)

        self.status_line = ttk.Label(self.progress_frame, textvariable=self.status_var, anchor="w")
        self.status_line.pack(fill="x", pady=(0, 10))

        ttk.Separator(shell, orient="horizontal").pack(fill="x", pady=(0, 10))

        self.log_frame = ttk.Frame(shell)
        self.log_frame.pack(fill="both", expand=True)
        log_header = ttk.Frame(self.log_frame)
        log_header.pack(fill="x")
        self.log_toggle_button = ttk.Button(log_header, command=self.toggle_log, width=22)
        self.log_toggle_button.pack(side="left")
        self.log_body = ttk.Frame(self.log_frame)
        self.log_body.pack(fill="both", expand=True, pady=(6, 0))
        self.log_text = tk.Text(
            self.log_body,
            wrap="word",
            font=("Consolas", 9),
            height=5,
            state="disabled",
            exportselection=False,
            relief="solid",
            bd=1,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.bind("<Button-1>", self.on_log_focus, add="+")
        self.log_text.bind("<Control-KeyPress>", self.on_log_control_keypress)
        self.log_text.bind("<Button-3>", self.show_log_context_menu)
        scrollbar = ttk.Scrollbar(self.log_body, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_context_menu = tk.Menu(self.root, tearoff=False)
        self.log_context_menu.add_command(label="Copy", command=self.copy_log)
        self.log_context_menu.add_command(label="Copy all", command=self.copy_all_log)
        self.log_context_menu.add_command(label="Clear log", command=self.clear_log)

        self.footer_status = ttk.Label(shell, textvariable=self.status_var, anchor="w")
        self.footer_status.pack(fill="x", pady=(8, 0))

    def _make_flag(self, parent: ttk.Frame, language: str) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=32, height=20, bd=0, highlightthickness=2, cursor="hand2")
        canvas.pack(side="left", padx=(0, 5))
        if language == "ru":
            canvas.create_rectangle(1, 1, 31, 7, fill="#ffffff", outline="")
            canvas.create_rectangle(1, 7, 31, 13, fill="#1f57b7", outline="")
            canvas.create_rectangle(1, 13, 31, 19, fill="#d52b1e", outline="")
        else:
            canvas.create_rectangle(1, 1, 31, 19, fill="#21468b", outline="")
            canvas.create_line(2, 2, 30, 18, fill="white", width=5)
            canvas.create_line(30, 2, 2, 18, fill="white", width=5)
            canvas.create_line(2, 2, 30, 18, fill="#c8102e", width=2)
            canvas.create_line(30, 2, 2, 18, fill="#c8102e", width=2)
            canvas.create_rectangle(13, 1, 19, 19, fill="white", outline="")
            canvas.create_rectangle(1, 7, 31, 13, fill="white", outline="")
            canvas.create_rectangle(15, 1, 17, 19, fill="#c8102e", outline="")
            canvas.create_rectangle(1, 9, 31, 11, fill="#c8102e", outline="")
        canvas.bind("<Button-1>", lambda _event, lang=language: self.set_language(lang))
        return canvas

    def set_language(self, language: str) -> None:
        if language not in core.TRANSLATIONS or language == self.language:
            return
        self.language_var.set(language.upper())
        self.on_language_change()
        self._refresh_flag_styles()

    def _refresh_flag_styles(self) -> None:
        for language, canvas in self._flag_canvases.items():
            color = "#2f80ed" if language == self.language else "#c7ccd1"
            canvas.configure(highlightbackground=color, highlightcolor=color)

    def _preset_from_settings(self) -> str:
        mode = str(self.ytdlp_settings.get("output_mode", "mp4"))
        quality = str(self.ytdlp_settings.get("format_preset", "best"))
        for key, preset_mode, preset_quality in PRESETS:
            if mode == preset_mode and quality == preset_quality:
                return key
        return ""

    def select_preset(self, preset: str) -> None:
        match = next((item for item in PRESETS if item[0] == preset), None)
        if match is None:
            return
        _key, mode, quality = match
        self.ytdlp_settings["output_mode"] = mode
        self.ytdlp_settings["format_preset"] = quality
        try:
            self.save_settings()
        except Exception as exc:
            messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc))
            return
        self._refresh_preset_styles()

    def _refresh_preset_styles(self) -> None:
        active = self._preset_from_settings()
        for key, button in self._preset_buttons.items():
            if key == active:
                button.configure(bg="#e9f2ff", fg="#1769d2", activebackground="#dbeaff", relief="solid", bd=1)
            else:
                button.configure(bg="#f7f8fa", fg="#222222", activebackground="#eef1f4", relief="solid", bd=1)

    def toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self.log_body.pack(fill="both", expand=True, pady=(6, 0))
        else:
            self.log_body.pack_forget()
        self._refresh_log_toggle_text()

    def _refresh_log_toggle_text(self) -> None:
        arrow = "▼" if self._log_expanded else "▶"
        self.log_toggle_button.configure(text=f"{arrow}  {self.ui('details_log')}")

    def refresh_ui_language(self) -> None:
        self.root.title(f"{self.tr('app_title')} — v{APP_VERSION}")
        self.url_label.configure(text=self.tr("label_url"))
        self.download_dir_label.configure(text=self.tr("label_save_folder"))
        self.choose_folder_button.configure(text=self.tr("button_choose_folder"))
        self.start_button.configure(text=self.ui("download"))
        self.cancel_button.configure(text=self.tr("button_cancel_job"))
        self.preset_title.configure(text=self.ui("quick_presets"))
        for key, button in self._preset_buttons.items():
            button.configure(text=self.ui(f"preset_{key}"))
        self.settings_button.configure(text="⚙")
        self.url_context_menu.entryconfigure(0, label=self.tr("button_paste"))
        self.log_context_menu.entryconfigure(0, label=self.tr("menu_copy"))
        self.log_context_menu.entryconfigure(1, label=self.tr("menu_copy_all"))
        self.log_context_menu.entryconfigure(2, label=self.tr("menu_clear_log"))
        self._refresh_log_toggle_text()
        self._refresh_flag_styles()
        self.overall_title_var.set(self.ui("overall_progress", value=self.progress_text_var.get() or "0%"))
        if self.current_status_key:
            self.status_var.set(self.tr(self.current_status_key, **self.current_status_kwargs))

    def _apply_progress(self, value: float, label: str) -> None:
        super()._apply_progress(value, label)
        self.overall_title_var.set(self.ui("overall_progress", value=label))

    def _set_running_state_ui(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.settings_button.configure(state=state)
        self.url_entry.configure(state=state)
        self.choose_folder_button.configure(state=state)
        for button in self._preset_buttons.values():
            button.configure(state=state)
        for canvas in self._flag_canvases.values():
            canvas.configure(cursor="arrow" if running else "hand2")
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
                relief="flat",
                cursor="hand2",
            )
        else:
            self.cancel_button.configure(
                state="disabled",
                bg="#eceff2",
                fg="#777777",
                disabledforeground="#777777",
                activebackground="#eceff2",
                relief="flat",
                cursor="arrow",
            )

    def _migrate_saved_cookie_path(self) -> None:
        raw = str(self.ytdlp_settings.get("cookies_file", "")).strip()
        if not raw:
            return
        source = Path(raw).expanduser()
        if not source.is_file():
            return
        try:
            if source.resolve(strict=False) == launcher_layer.MANAGED_COOKIES_PATH.resolve(strict=False):
                return
            self.import_cookie_file(source, save=True)
        except Exception:
            return

    def _cookie_ui_status(self) -> str:
        status = self._cookie_status(launcher_layer.MANAGED_COOKIES_PATH)
        state = str(status.get("state", "missing"))
        if state == "missing":
            return self.ui("cookies_missing")
        if state in {"invalid", "expired"}:
            return self.ui("cookies_invalid")
        return self.ui("cookies_saved")

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
        dialog.title(f"{self.ui('settings')} — v{APP_VERSION}")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", lambda win=dialog: self.close_settings_dialog(win))

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        output_template_var = tk.StringVar(value=str(self.ytdlp_settings["output_template"]))
        retries_var = tk.StringVar(value=str(self.ytdlp_settings["retries"]))
        retry_sleep_var = tk.StringVar(value=str(self.ytdlp_settings["retry_sleep"]))
        restrict_var = tk.BooleanVar(value=bool(self.ytdlp_settings["restrict_filenames"]))
        windows_var = tk.BooleanVar(value=bool(self.ytdlp_settings["windows_filenames"]))
        cookie_status_var = tk.StringVar(value=self._cookie_ui_status())

        ttk.Label(body, text=self.ui("advanced"), font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(body, text=self.tr("label_output_template")).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Entry(body, textvariable=output_template_var, width=48).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(body, text=self.tr("label_retries")).grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Spinbox(body, from_=0, to=100, textvariable=retries_var, width=10).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(body, text=self.tr("label_retry_sleep")).grid(row=3, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Entry(body, textvariable=retry_sleep_var, width=10).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Checkbutton(body, text=self.tr("label_restrict_filenames"), variable=restrict_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 2))
        ttk.Checkbutton(body, text=self.tr("label_windows_filenames"), variable=windows_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Separator(body, orient="horizontal").grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        ttk.Label(body, text=self.ui("cookies_title"), font=("Segoe UI", 10, "bold")).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Label(body, textvariable=cookie_status_var, wraplength=500, justify="left").grid(row=8, column=0, columnspan=2, sticky="w", pady=(5, 8))
        cookie_buttons = ttk.Frame(body)
        cookie_buttons.grid(row=9, column=0, columnspan=2, sticky="w")

        def import_cookies() -> None:
            selected = filedialog.askopenfilename(
                parent=dialog,
                title=self.tr("dialog_select_cookies_file"),
                filetypes=[(self.tr("dialog_cookies_filter"), "*.txt"), (self.tr("dialog_all_files_filter"), "*.*")],
            )
            if not selected:
                return
            try:
                self.import_cookie_file(Path(selected), save=True)
                self.ytdlp_settings["auth_mode"] = "none"
                self.save_settings()
            except Exception as exc:
                messagebox.showerror(self.tr("app_title"), str(exc), parent=dialog)
                return
            cookie_status_var.set(self._cookie_ui_status())

        def remove_cookies() -> None:
            if not messagebox.askyesno(self.ui("cookies_title"), self.ui("cookies_remove_confirm"), parent=dialog):
                return
            try:
                if launcher_layer.MANAGED_COOKIES_PATH.exists():
                    launcher_layer.MANAGED_COOKIES_PATH.unlink()
            except OSError as exc:
                messagebox.showerror(self.tr("app_title"), str(exc), parent=dialog)
                return
            self.ytdlp_settings["cookies_file"] = ""
            self.ytdlp_settings["cookie_last_failed_at"] = 0.0
            self.ytdlp_settings["auth_mode"] = "none"
            try:
                self.save_settings()
            except Exception:
                pass
            cookie_status_var.set(self._cookie_ui_status())

        ttk.Button(cookie_buttons, text=self.ui("cookies_import"), command=import_cookies).pack(side="left")
        ttk.Button(cookie_buttons, text=self.ui("cookies_remove"), command=remove_cookies).pack(side="left", padx=(8, 0))

        ttk.Separator(body, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        ttk.Label(body, text=self.ui("service"), font=("Segoe UI", 10, "bold")).grid(row=11, column=0, columnspan=2, sticky="w")
        service_buttons = ttk.Frame(body)
        service_buttons.grid(row=12, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def close_and_check_updates() -> None:
            self.close_settings_dialog(dialog)
            self.root.after(60, self.on_check_versions)

        ttk.Button(service_buttons, text=self.ui("check_updates"), command=close_and_check_updates).pack(side="left")
        ttk.Button(service_buttons, text=self.ui("open_folder"), command=self.open_downloads).pack(side="left", padx=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(16, 0))

        def apply_defaults() -> None:
            output_template_var.set(str(core.YTDLP_DEFAULTS["output_template"]))
            retries_var.set(str(core.YTDLP_DEFAULTS["retries"]))
            retry_sleep_var.set(str(core.YTDLP_DEFAULTS["retry_sleep"]))
            restrict_var.set(bool(core.YTDLP_DEFAULTS["restrict_filenames"]))
            windows_var.set(bool(core.YTDLP_DEFAULTS["windows_filenames"]))

        def save_dialog_settings() -> None:
            output_template = output_template_var.get().strip()
            if not output_template:
                messagebox.showerror(self.tr("app_title"), self.tr("error_output_template_empty"), parent=dialog)
                return
            try:
                retries_value = int(retries_var.get().strip())
                if retries_value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(self.tr("app_title"), self.tr("error_invalid_integer", name=self.tr("label_retries")), parent=dialog)
                return
            retry_sleep = self.normalize_retry_sleep(retry_sleep_var.get())
            if retry_sleep is None:
                messagebox.showerror(self.tr("app_title"), self.tr("error_invalid_number", name=self.tr("label_retry_sleep")), parent=dialog)
                return

            updated = dict(self.ytdlp_settings)
            updated.update(
                {
                    "output_template": output_template,
                    "retries": retries_value,
                    "retry_sleep": retry_sleep,
                    "restrict_filenames": bool(restrict_var.get()),
                    "windows_filenames": bool(windows_var.get()),
                    "auth_mode": "none",
                    "cookies_file": str(launcher_layer.MANAGED_COOKIES_PATH) if launcher_layer.MANAGED_COOKIES_PATH.is_file() else "",
                }
            )
            self.ytdlp_settings = updated
            try:
                self.save_settings()
            except Exception as exc:
                messagebox.showerror(self.tr("app_title"), self.tr("error_failed_save_settings", error=exc), parent=dialog)
                return
            self.close_settings_dialog(dialog)

        ttk.Button(buttons, text=self.tr("button_reset_defaults"), command=apply_defaults).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.tr("button_cancel"), command=lambda: self.close_settings_dialog(dialog)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.tr("button_save"), command=save_dialog_settings).pack(side="left")

        dialog.update_idletasks()
        dialog.grab_set()
        dialog.focus_force()

    def _strip_auth_args(self, command: list[str]) -> list[str]:
        stripped: list[str] = []
        skip_next = False
        for arg in command:
            if skip_next:
                skip_next = False
                continue
            if arg in {"--cookies", "--cookies-from-browser"}:
                skip_next = True
                continue
            if arg.startswith("--cookies=") or arg.startswith("--cookies-from-browser="):
                continue
            stripped.append(arg)
        return stripped

    @staticmethod
    def _with_cookie_file(command: list[str], cookie_path: Path) -> list[str]:
        url = command[-1]
        authenticated = list(command[:-1])
        authenticated.extend(["--cookies", str(cookie_path), url])
        return authenticated

    def _is_auth_failure(self, exc: Exception) -> bool:
        lines = getattr(exc, "output_lines", None)
        text = "\n".join(lines) if isinstance(lines, list) else str(exc)
        lower = text.lower()
        return any(pattern in lower for pattern in core.AUTH_REQUIRED_PATTERNS)

    def _is_cookie_failure(self, exc: Exception) -> bool:
        lines = getattr(exc, "output_lines", None)
        text = "\n".join(lines) if isinstance(lines, list) else str(exc)
        lower = text.lower()
        return self._is_auth_failure(exc) or "cookie" in lower

    def _mark_saved_cookie_failed(self) -> None:
        import time

        self.ytdlp_settings["cookie_last_failed_at"] = time.time()
        try:
            self.save_settings()
        except Exception:
            pass

    def _clear_saved_cookie_failed(self) -> None:
        self.ytdlp_settings["cookie_last_failed_at"] = 0.0
        try:
            self.save_settings()
        except Exception:
            pass

    def _prompt_cookie_file_blocking(self) -> Path | None:
        done = threading.Event()
        result: dict[str, Path | None] = {"path": None}

        def prompt() -> None:
            try:
                if not messagebox.askokcancel(self.ui("cookies_required_title"), self.ui("cookies_required"), parent=self.root):
                    return
                selected = filedialog.askopenfilename(
                    parent=self.root,
                    title=self.tr("dialog_select_cookies_file"),
                    filetypes=[(self.tr("dialog_cookies_filter"), "*.txt"), (self.tr("dialog_all_files_filter"), "*.*")],
                )
                if not selected:
                    return
                try:
                    result["path"] = self.import_cookie_file(Path(selected), save=True)
                    self.ytdlp_settings["auth_mode"] = "none"
                    self.save_settings()
                except Exception as exc:
                    messagebox.showerror(self.tr("app_title"), str(exc), parent=self.root)
            finally:
                done.set()

        self._schedule(prompt)
        while not done.wait(0.2):
            if self.closing:
                return None
        return result["path"]

    def run_ytdlp_command(self, command: list[str]) -> str | None:
        if not command:
            return runtime_layer.App.run_ytdlp_command(self, command)

        unauthenticated = self._strip_auth_args(command)
        try:
            return runtime_layer.App.run_ytdlp_command(self, unauthenticated)
        except Exception as exc:
            if not self._is_auth_failure(exc):
                raise

        cookie_path: Path | None = None
        try:
            cookie_path = self._resolve_cookies_file_path()
        except Exception:
            cookie_path = None

        if cookie_path is not None:
            try:
                result = runtime_layer.App.run_ytdlp_command(self, self._with_cookie_file(unauthenticated, cookie_path))
                self._clear_saved_cookie_failed()
                return result
            except Exception as exc:
                if not self._is_cookie_failure(exc):
                    raise
                self._mark_saved_cookie_failed()

        cookie_path = self._prompt_cookie_file_blocking()
        if cookie_path is None:
            raise core.AppError(self.ui("cookies_required"))

        try:
            result = runtime_layer.App.run_ytdlp_command(self, self._with_cookie_file(unauthenticated, cookie_path))
            self._clear_saved_cookie_failed()
            return result
        except Exception as exc:
            if self._is_cookie_failure(exc):
                self._mark_saved_cookie_failed()
                raise core.AppError(self.ui("cookies_retry_failed")) from exc
            raise

    def fetch_url_analysis_info(self, url: str) -> dict[str, object]:
        info = super().fetch_url_analysis_info(url)
        duration = info.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            self._media_duration_seconds = float(duration)
        return info

    def parse_progress(self, line: str) -> str | None:
        if str(self.ytdlp_settings.get("output_mode")) == "mp3" and self._media_duration_seconds > 0:
            match = FFMPEG_TIME_RE.search(line)
            if match is not None:
                elapsed = int(match.group("h")) * 3600 + int(match.group("m")) * 60 + float(match.group("s"))
                pct = max(0.0, min(100.0, elapsed * 100.0 / self._media_duration_seconds))
                self._set_task_progress(pct, f"{pct:.0f}%", self.rt("status_converting_mp3"))
                overall = max(self.total_progress_value, 92.0 + pct * 0.06)
                self._set_progress(overall, f"{overall:.0f}%")
                self._set_status(self.rt("status_converting_mp3"))
                return None
        return super().parse_progress(line)


def self_test() -> int:
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
    if core.AUTH_MODE_CHOICES != ("none",):
        errors.append("Release UI must not expose authentication modes.")
    if core.YTDLP_DEFAULTS.get("auth_mode") != "none":
        errors.append("Release authentication default must be no authentication.")
    if len(PRESETS) != 5:
        errors.append("Expected five quick presets.")
    if FFMPEG_TIME_RE.search("frame=1 time=00:01:02.50 bitrate=192k") is None:
        errors.append("FFmpeg progress parser failed.")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("RELEASE UI SELF-TEST OK\n")
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
