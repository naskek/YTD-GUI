from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

import release_app as previous
import mini_url_converter as core
from version import APP_VERSION


BG = "#f4f7fb"
CARD = "#ffffff"
TEXT = "#172033"
MUTED = "#667085"
BORDER = "#d8e0e8"
BORDER_ACTIVE = "#2f80ed"
PRIMARY = "#27a844"
PRIMARY_HOVER = "#218f3a"
DANGER = "#c83b3b"
DANGER_HOVER = "#ad2f2f"
BLUE = "#2f80ed"
BLUE_SOFT = "#edf5ff"
BLUE_SOFT_HOVER = "#e2efff"
BAR_BG = "#e6edf4"


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)
        self.root.geometry("900x650")
        self.root.minsize(780, 560)
        self._log_expanded = False
        if hasattr(self, "log_body"):
            self.log_body.pack_forget()
        self._refresh_log_toggle_text()
        self._refresh_preset_styles()
        self._refresh_flag_styles()

    def _configure_styles(self) -> None:
        self.root.configure(bg=BG)
        style = ttk.Style(self.root)
        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure(
            "TButton",
            font=("Segoe UI", 10),
            padding=(12, 7),
            background=CARD,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", "#edf1f5"), ("disabled", "#f3f5f7")],
            foreground=[("disabled", "#9aa3ad")],
        )
        style.configure(
            "Tool.TButton",
            font=("Segoe UI Symbol", 11),
            padding=(8, 5),
            background=CARD,
            foreground=TEXT,
            bordercolor=BORDER,
        )
        style.configure(
            "Folder.TButton",
            padding=(12, 6),
            background=CARD,
            foreground=TEXT,
            bordercolor=BORDER,
        )
        style.configure("TEntry", fieldbackground=CARD, foreground=TEXT, bordercolor=BORDER, padding=6)
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TSeparator", background="#dfe5ec")
        style.configure("Vertical.TScrollbar", background="#c8d0d9", troughcolor="#eef2f6", bordercolor="#eef2f6")

    def _build_ui(self) -> None:
        self._configure_styles()

        shell = tk.Frame(self.root, bg=BG, padx=24, pady=18)
        shell.pack(fill="both", expand=True)

        toolbar = tk.Frame(shell, bg=BG)
        toolbar.pack(fill="x", pady=(0, 10))
        toolbar_spacer = tk.Frame(toolbar, bg=BG)
        toolbar_spacer.pack(side="left", fill="x", expand=True)

        self._flag_canvases["ru"] = self._make_flag(toolbar, "ru")
        self._flag_canvases["en"] = self._make_flag(toolbar, "en")
        self.settings_button = ttk.Button(toolbar, text="⚙", width=3, style="Tool.TButton", command=self.open_settings_dialog)
        self.settings_button.pack(side="left", padx=(6, 0))

        self.url_label = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold"), anchor="w")
        self.url_label.pack(fill="x")

        url_row = tk.Frame(shell, bg=BG)
        url_row.pack(fill="x", pady=(6, 15))

        self.url_entry_border = tk.Frame(url_row, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.url_entry_border.pack(side="left", fill="x", expand=True)
        self.url_entry = tk.Entry(
            self.url_entry_border,
            textvariable=self.url_var,
            font=("Segoe UI", 12),
            relief="flat",
            bd=0,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=0,
        )
        self.url_entry.pack(fill="x", expand=True, padx=12, pady=10)
        self.url_entry.bind("<FocusIn>", lambda _event: self.url_entry_border.configure(highlightbackground=BORDER_ACTIVE))
        self.url_entry.bind("<FocusOut>", lambda _event: self.url_entry_border.configure(highlightbackground=BORDER))
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
            bg=PRIMARY,
            fg="white",
            activebackground=PRIMARY_HOVER,
            activeforeground="white",
            disabledforeground="#e5e7eb",
            font=("Segoe UI", 11, "bold"),
            padx=22,
            pady=9,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.start_button.pack(side="left", padx=(12, 0))

        self.cancel_button = tk.Button(
            url_row,
            command=self.on_cancel_job,
            font=("Segoe UI", 10),
            padx=16,
            pady=9,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self._set_cancel_button_state(False)

        self.url_context_menu = tk.Menu(self.root, tearoff=False)
        self.url_context_menu.add_command(label="Paste", command=self.paste_into_url_entry)
        self.url_error_label = tk.Label(
            shell,
            textvariable=self.url_error_var,
            fg="#b42318",
            bg=BG,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )

        self.download_dir_label = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 10), anchor="w")
        self.download_dir_label.pack(fill="x")
        folder_row = tk.Frame(shell, bg=BG)
        folder_row.pack(fill="x", pady=(6, 18))

        folder_border = tk.Frame(folder_row, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        folder_border.pack(side="left", fill="x", expand=True)
        self.download_dir_entry = tk.Entry(
            folder_border,
            textvariable=self.download_dir_var,
            state="readonly",
            font=("Segoe UI", 10),
            relief="flat",
            bd=0,
            readonlybackground=CARD,
            fg=TEXT,
            highlightthickness=0,
        )
        self.download_dir_entry.pack(fill="x", expand=True, padx=10, pady=7)
        self.choose_folder_button = ttk.Button(folder_row, style="Folder.TButton", command=self.choose_folder)
        self.choose_folder_button.pack(side="left", padx=(10, 0))

        self.preset_title = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold"), anchor="w")
        self.preset_title.pack(fill="x", pady=(0, 8))
        preset_row = tk.Frame(shell, bg=BG)
        preset_row.pack(fill="x", pady=(0, 18))
        for index, (key, _mode, _quality) in enumerate(previous.PRESETS):
            preset_row.columnconfigure(index, weight=1, uniform="preset")
            button = tk.Button(
                preset_row,
                command=lambda preset=key: self.select_preset(preset),
                font=("Segoe UI", 10),
                padx=12,
                pady=11,
                relief="flat",
                bd=0,
                highlightthickness=1,
                cursor="hand2",
            )
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            self._preset_buttons[key] = button

        progress_card = tk.Frame(shell, bg=CARD, highlightthickness=1, highlightbackground="#e1e7ee", padx=16, pady=14)
        progress_card.pack(fill="x", pady=(0, 14))
        self.progress_frame = progress_card
        self.overall_title_var = tk.StringVar(value="")

        overall_header = tk.Frame(progress_card, bg=CARD)
        overall_header.pack(fill="x")
        tk.Label(overall_header, textvariable=self.overall_title_var, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(overall_header, textvariable=self.progress_text_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="right")
        self.progress_bar = tk.Canvas(progress_card, height=10, bg=BAR_BG, bd=0, highlightthickness=0)
        self.progress_bar.pack(fill="x", pady=(7, 14))
        self.progress_bar_fill = self.progress_bar.create_rectangle(0, 0, 0, 10, fill=PRIMARY, outline="")
        self.progress_bar.bind("<Configure>", self.on_total_progress_resize)

        stage_header = tk.Frame(progress_card, bg=CARD)
        stage_header.pack(fill="x")
        self.stage_status_label = tk.Label(stage_header, textvariable=self.task_status_var, bg=CARD, fg=TEXT, font=("Segoe UI", 10))
        self.stage_status_label.pack(side="left")
        tk.Label(stage_header, textvariable=self.task_progress_text_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="right")
        self.task_progress_bar = tk.Canvas(progress_card, height=8, bg=BAR_BG, bd=0, highlightthickness=0)
        self.task_progress_bar.pack(fill="x", pady=(7, 10))
        self.task_progress_bar_fill = self.task_progress_bar.create_rectangle(0, 0, 0, 8, fill=BLUE, outline="")
        self.task_progress_bar.bind("<Configure>", self.on_task_progress_resize)

        self.status_line = tk.Label(progress_card, textvariable=self.status_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.status_line.pack(fill="x")

        self.log_frame = tk.Frame(shell, bg=BG)
        self.log_frame.pack(fill="both", expand=True)
        log_header = tk.Frame(self.log_frame, bg=BG)
        log_header.pack(fill="x")
        self.log_toggle_button = tk.Button(
            log_header,
            command=self.toggle_log,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            activeforeground=BLUE,
            font=("Segoe UI", 10),
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=2,
            cursor="hand2",
            anchor="w",
        )
        self.log_toggle_button.pack(side="left")

        self.log_body = tk.Frame(self.log_frame, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.log_body.pack(fill="both", expand=True, pady=(7, 0))
        self.log_text = tk.Text(
            self.log_body,
            wrap="word",
            font=("Cascadia Mono", 9),
            height=5,
            state="disabled",
            exportselection=False,
            relief="flat",
            bd=0,
            bg="#fbfcfe",
            fg="#344054",
            padx=10,
            pady=8,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.bind("<Button-1>", self.on_log_focus, add="+")
        self.log_text.bind("<Control-KeyPress>", self.on_log_control_keypress)
        self.log_text.bind("<Button-3>", self.show_log_context_menu)
        scrollbar = ttk.Scrollbar(self.log_body, orient="vertical", style="Vertical.TScrollbar", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_context_menu = tk.Menu(self.root, tearoff=False)
        self.log_context_menu.add_command(label="Copy", command=self.copy_log)
        self.log_context_menu.add_command(label="Copy all", command=self.copy_all_log)
        self.log_context_menu.add_command(label="Clear log", command=self.clear_log)

    def _make_flag(self, parent: tk.Widget, language: str) -> tk.Canvas:
        canvas = tk.Canvas(
            parent,
            width=38,
            height=26,
            bd=0,
            bg=CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
            cursor="hand2",
        )
        canvas.pack(side="left", padx=(0, 6))
        x0, y0, x1, y1 = 6, 5, 32, 21
        if language == "ru":
            canvas.create_rectangle(x0, y0, x1, y0 + 5, fill="#ffffff", outline="")
            canvas.create_rectangle(x0, y0 + 5, x1, y0 + 11, fill="#1f57b7", outline="")
            canvas.create_rectangle(x0, y0 + 11, x1, y1, fill="#d52b1e", outline="")
            canvas.create_rectangle(x0, y0, x1, y1, outline="#c6ccd3")
        else:
            canvas.create_rectangle(x0, y0, x1, y1, fill="#21468b", outline="")
            canvas.create_line(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill="white", width=4)
            canvas.create_line(x1 - 1, y0 + 1, x0 + 1, y1 - 1, fill="white", width=4)
            canvas.create_line(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill="#c8102e", width=1)
            canvas.create_line(x1 - 1, y0 + 1, x0 + 1, y1 - 1, fill="#c8102e", width=1)
            canvas.create_rectangle(16, y0, 22, y1, fill="white", outline="")
            canvas.create_rectangle(x0, 10, x1, 16, fill="white", outline="")
            canvas.create_rectangle(18, y0, 20, y1, fill="#c8102e", outline="")
            canvas.create_rectangle(x0, 12, x1, 14, fill="#c8102e", outline="")
            canvas.create_rectangle(x0, y0, x1, y1, outline="#c6ccd3")
        canvas.bind("<Button-1>", lambda _event, lang=language: self.set_language(lang))
        return canvas

    def _refresh_flag_styles(self) -> None:
        for language, canvas in self._flag_canvases.items():
            border = BLUE if language == self.language else BORDER
            canvas.configure(highlightbackground=border, highlightcolor=border, bg=CARD)

    def _refresh_preset_styles(self) -> None:
        active = self._preset_from_settings()
        for key, button in self._preset_buttons.items():
            if key == active:
                button.configure(
                    bg=BLUE_SOFT,
                    fg="#1769d2",
                    activebackground=BLUE_SOFT_HOVER,
                    activeforeground="#1769d2",
                    highlightbackground=BLUE,
                    highlightcolor=BLUE,
                )
            else:
                button.configure(
                    bg=CARD,
                    fg=TEXT,
                    activebackground="#f2f5f8",
                    activeforeground=TEXT,
                    highlightbackground=BORDER,
                    highlightcolor=BORDER,
                )

    def _set_cancel_button_state(self, enabled: bool) -> None:
        if enabled:
            self.cancel_button.configure(
                state="normal",
                bg=DANGER,
                fg="white",
                activebackground=DANGER_HOVER,
                activeforeground="white",
                disabledforeground="#e5e7eb",
                cursor="hand2",
            )
        else:
            self.cancel_button.configure(
                state="disabled",
                bg="#eef1f4",
                fg="#8b95a1",
                disabledforeground="#8b95a1",
                activebackground="#eef1f4",
                activeforeground="#8b95a1",
                cursor="arrow",
            )

    def refresh_ui_language(self) -> None:
        super().refresh_ui_language()
        self.start_button.configure(text=f"↓  {self.ui('download')}")
        self.cancel_button.configure(text=f"⊘  {self.tr('button_cancel_job')}")
        labels = {
            "mp4_1080": "▶  MP4 1080p",
            "mp4_720": "▶  MP4 720p",
            "mp3": "♫  MP3",
            "mkv": "▣  MKV",
            "original": f"▤  {self.ui('preset_original')}",
        }
        for key, button in self._preset_buttons.items():
            button.configure(text=labels.get(key, button.cget("text")))

    def open_settings_dialog(self) -> None:
        super().open_settings_dialog()
        dialog = self.settings_window
        if dialog is None or not dialog.winfo_exists():
            return
        dialog.configure(bg=BG)
        dialog.update_idletasks()
        width = max(560, dialog.winfo_reqwidth())
        height = max(430, dialog.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    if BG == CARD or not PRIMARY.startswith("#") or not BLUE.startswith("#"):
        core._write_self_test_diagnostic("UI POLISH SELF-TEST FAILED\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("UI POLISH SELF-TEST OK\n")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
