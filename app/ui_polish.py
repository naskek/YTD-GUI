from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

import release_app as previous
import mini_url_converter as core
from version import APP_VERSION


BG = "#f7f9fc"
CARD = "#ffffff"
CARD_ALT = "#fbfcfe"
TEXT = "#243147"
MUTED = "#7a8699"
BORDER = "#e4e9f0"
BORDER_ACTIVE = "#6b93e6"
PRIMARY = "#3aaa68"
PRIMARY_HOVER = "#31965a"
PRIMARY_DISABLED = "#b9dec8"
DANGER = "#d86a6a"
DANGER_HOVER = "#c25757"
BLUE = "#5b86df"
BLUE_HOVER = "#4d76c9"
BLUE_SOFT = "#eef4ff"
BLUE_SOFT_HOVER = "#e4eeff"
BAR_BG = "#edf1f6"
SOFT_BUTTON = "#f3f6fa"
SOFT_BUTTON_HOVER = "#eaf0f6"


def _rounded_rectangle(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs: object,
) -> int:
    radius = max(0.0, min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class RoundedButton(tk.Canvas):
    """Canvas button with predictable rounded corners and small vector icons."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str = "",
        command=None,
        icon: str = "",
        height: int = 40,
        min_width: int = 96,
        radius: int = 10,
        bg: str = CARD,
        fg: str = TEXT,
        hover_bg: str | None = None,
        border: str = BORDER,
        active_border: str | None = None,
        font: tuple[str, int] | tuple[str, int, str] = ("Segoe UI", 10),
        cursor: str = "hand2",
    ) -> None:
        parent_bg = str(parent.cget("bg")) if "bg" in parent.keys() else BG
        super().__init__(
            parent,
            height=height,
            width=min_width,
            bg=parent_bg,
            bd=0,
            highlightthickness=0,
            takefocus=1,
            cursor=cursor,
        )
        self._text = text
        self._command = command
        self._icon = icon
        self._height = height
        self._min_width = min_width
        self._radius = radius
        self._normal_bg = bg
        self._hover_bg = hover_bg or bg
        self._fg = fg
        self._border = border
        self._active_border = active_border or border
        self._font = font
        self._state = "normal"
        self._hover = False
        self._cursor_enabled = cursor
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)
        self.bind("<space>", self._on_keyboard)
        self.bind("<Return>", self._on_keyboard)
        self._draw()

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if cnf:
            kwargs.update(cnf)
        mapping = {
            "text": "_text",
            "command": "_command",
            "bg": "_normal_bg",
            "background": "_normal_bg",
            "fg": "_fg",
            "foreground": "_fg",
            "activebackground": "_hover_bg",
            "highlightbackground": "_border",
            "highlightcolor": "_active_border",
            "font": "_font",
            "state": "_state",
            "cursor": "_cursor_enabled",
        }
        redraw = False
        for key in list(kwargs):
            attr = mapping.get(key)
            if attr is not None:
                setattr(self, attr, kwargs.pop(key))
                redraw = True
        # Tk buttons are sometimes configured with options that are purely
        # cosmetic for this custom control. Accept them instead of failing.
        for ignored in (
            "activeforeground",
            "disabledforeground",
            "relief",
            "bd",
            "borderwidth",
            "padx",
            "pady",
            "width",
        ):
            kwargs.pop(ignored, None)
        if kwargs:
            super().configure(**kwargs)
        if redraw:
            super().configure(cursor="arrow" if self._state == "disabled" else self._cursor_enabled)
            self._draw()
        return None

    config = configure

    def cget(self, key: str):  # type: ignore[override]
        values = {
            "text": self._text,
            "state": self._state,
            "bg": self._normal_bg,
            "background": self._normal_bg,
            "fg": self._fg,
            "foreground": self._fg,
        }
        if key in values:
            return values[key]
        return super().cget(key)

    def _on_enter(self, _event: tk.Event[tk.Misc]) -> None:
        if self._state != "disabled":
            self._hover = True
            self._draw()

    def _on_leave(self, _event: tk.Event[tk.Misc]) -> None:
        self._hover = False
        self._draw()

    def _on_click(self, _event: tk.Event[tk.Misc]) -> None:
        if self._state != "disabled" and self._command is not None:
            self._command()

    def _on_keyboard(self, _event: tk.Event[tk.Misc]) -> str:
        if self._state != "disabled" and self._command is not None:
            self._command()
        return "break"

    def _draw_icon(self, cx: float, cy: float, color: str) -> None:
        icon = self._icon
        if not icon:
            return
        if icon == "download":
            self.create_line(cx, cy - 6, cx, cy + 3, fill=color, width=2.2, capstyle="round")
            self.create_line(cx - 4, cy, cx, cy + 4, cx + 4, cy, fill=color, width=2.2, capstyle="round", joinstyle="round")
            self.create_line(cx - 6, cy + 7, cx + 6, cy + 7, fill=color, width=2.0, capstyle="round")
        elif icon == "cancel":
            self.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline=color, width=1.8)
            self.create_line(cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5, fill=color, width=1.8, capstyle="round")
            self.create_line(cx + 3.5, cy - 3.5, cx - 3.5, cy + 3.5, fill=color, width=1.8, capstyle="round")
        elif icon == "folder":
            self.create_polygon(
                cx - 8,
                cy - 5,
                cx - 2,
                cy - 5,
                cx,
                cy - 2,
                cx + 8,
                cy - 2,
                cx + 8,
                cy + 6,
                cx - 8,
                cy + 6,
                fill="",
                outline=color,
                width=1.8,
                joinstyle="round",
            )
        elif icon == "settings":
            self.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, outline=color, width=1.8)
            self.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, outline=color, width=1.6)
            for dx, dy in ((0, -9), (0, 9), (-9, 0), (9, 0), (-6, -6), (6, 6), (6, -6), (-6, 6)):
                self.create_line(cx + dx * 0.65, cy + dy * 0.65, cx + dx, cy + dy, fill=color, width=1.8, capstyle="round")
        elif icon == "video":
            self.create_rectangle(cx - 8, cy - 6, cx + 7, cy + 6, outline=color, width=1.7)
            self.create_polygon(cx - 2, cy - 3.5, cx + 4, cy, cx - 2, cy + 3.5, fill=color, outline="")
        elif icon == "music":
            self.create_line(cx + 3, cy - 7, cx + 3, cy + 4, fill=color, width=2)
            self.create_line(cx + 3, cy - 7, cx + 8, cy - 5, fill=color, width=2)
            self.create_oval(cx - 2, cy + 1, cx + 4, cy + 7, fill=color, outline="")
        elif icon == "box":
            self.create_rectangle(cx - 7, cy - 6, cx + 7, cy + 6, outline=color, width=1.7)
            self.create_line(cx - 7, cy - 1, cx + 7, cy - 1, fill=color, width=1.4)
        elif icon == "document":
            self.create_rectangle(cx - 6, cy - 8, cx + 6, cy + 8, outline=color, width=1.6)
            self.create_line(cx - 3, cy - 3, cx + 3, cy - 3, fill=color, width=1.4)
            self.create_line(cx - 3, cy + 1, cx + 3, cy + 1, fill=color, width=1.4)
            self.create_line(cx - 3, cy + 5, cx + 1, cy + 5, fill=color, width=1.4)

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        width = max(self._min_width, self.winfo_width())
        height = max(28, self.winfo_height() or self._height)
        self.delete("all")
        disabled = self._state == "disabled"
        bg = "#f3f5f8" if disabled else (self._hover_bg if self._hover else self._normal_bg)
        fg = "#9ba5b3" if disabled else self._fg
        border = "#e7ebf0" if disabled else (self._active_border if self._hover else self._border)
        _rounded_rectangle(self, 1, 1, width - 1, height - 1, self._radius, fill=bg, outline=border, width=1)

        has_icon = bool(self._icon)
        text_width = max(0, len(str(self._text))) * 6.5
        group_width = text_width + (23 if has_icon else 0)
        left = max(12.0, (width - group_width) / 2.0)
        if has_icon:
            self._draw_icon(left + 8, height / 2.0, fg)
            text_x = left + 23
        else:
            text_x = width / 2.0
        self.create_text(
            text_x,
            height / 2.0,
            text=str(self._text),
            fill=fg,
            font=self._font,
            anchor="w" if has_icon else "center",
        )


class RoundedField(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        *,
        variable: tk.StringVar,
        readonly: bool = False,
        height: int = 42,
        font: tuple[str, int] = ("Segoe UI", 10),
    ) -> None:
        parent_bg = str(parent.cget("bg")) if "bg" in parent.keys() else BG
        super().__init__(parent, height=height, bg=parent_bg, bd=0, highlightthickness=0)
        self._height = height
        self._border_color = BORDER
        self._readonly = readonly
        self.entry = tk.Entry(
            self,
            textvariable=variable,
            state="readonly" if readonly else "normal",
            font=font,
            relief="flat",
            bd=0,
            bg=CARD,
            readonlybackground=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=0,
        )
        self._window = self.create_window(13, height / 2, window=self.entry, anchor="w")
        self.bind("<Configure>", self._redraw)
        self._redraw(None)

    def set_border(self, color: str) -> None:
        self._border_color = color
        self._redraw(None)

    def _redraw(self, _event) -> None:
        width = max(40, self.winfo_width())
        height = max(30, self.winfo_height() or self._height)
        self.delete("field-bg")
        _rounded_rectangle(
            self,
            1,
            1,
            width - 1,
            height - 1,
            10,
            fill=CARD,
            outline=self._border_color,
            width=1,
            tags="field-bg",
        )
        self.tag_lower("field-bg")
        self.coords(self._window, 13, height / 2)
        self.itemconfigure(self._window, width=max(10, width - 26), height=max(18, height - 12))


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)
        self.root.geometry("900x610")
        self.root.minsize(800, 560)
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
        style.configure("TEntry", fieldbackground=CARD, foreground=TEXT, bordercolor=BORDER, padding=6)
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TSeparator", background=BORDER)
        style.configure("Vertical.TScrollbar", background="#cbd4df", troughcolor="#eef2f6", bordercolor="#eef2f6")

    def _build_ui(self) -> None:
        self._configure_styles()

        shell = tk.Frame(self.root, bg=BG, padx=26, pady=20)
        shell.pack(fill="both", expand=True)

        toolbar = tk.Frame(shell, bg=BG)
        toolbar.pack(fill="x", pady=(0, 10))
        tk.Frame(toolbar, bg=BG).pack(side="left", fill="x", expand=True)
        self._flag_canvases["ru"] = self._make_flag(toolbar, "ru")
        self._flag_canvases["en"] = self._make_flag(toolbar, "en")
        self.settings_button = RoundedButton(
            toolbar,
            text="",
            icon="settings",
            command=self.open_settings_dialog,
            height=34,
            min_width=42,
            radius=10,
            bg=CARD,
            hover_bg=SOFT_BUTTON,
            border=BORDER,
            active_border="#d5dde7",
        )
        self.settings_button.pack(side="left", padx=(6, 0))

        self.url_label = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold"), anchor="w")
        self.url_label.pack(fill="x")

        url_row = tk.Frame(shell, bg=BG)
        url_row.pack(fill="x", pady=(7, 15))
        self.url_field = RoundedField(url_row, variable=self.url_var, readonly=False, height=44, font=("Segoe UI", 12))
        self.url_field.pack(side="left", fill="x", expand=True)
        self.url_entry_border = self.url_field
        self.url_entry = self.url_field.entry
        self.url_entry.bind("<FocusIn>", lambda _event: self.url_field.set_border(BORDER_ACTIVE))
        self.url_entry.bind("<FocusOut>", lambda _event: self.url_field.set_border(BORDER))
        self.url_entry.focus_set()
        self.url_entry.bind("<Return>", self.on_start)
        self.url_entry.bind("<Control-KeyPress>", self.on_url_control_keypress)
        self.url_entry.bind("<Shift-Insert>", self.on_url_paste)
        self.url_entry.bind("<Button-3>", self.show_url_context_menu)
        self.url_entry.bind("<KeyPress>", self.on_url_entry_interaction, add="+")
        self.url_entry.bind("<Button-1>", self.on_url_entry_interaction, add="+")

        self.start_button = RoundedButton(
            url_row,
            text="",
            icon="download",
            command=self.on_start,
            height=44,
            min_width=132,
            radius=11,
            bg=PRIMARY,
            hover_bg=PRIMARY_HOVER,
            fg="white",
            border=PRIMARY,
            active_border=PRIMARY_HOVER,
            font=("Segoe UI", 11, "bold"),
        )
        self.start_button.pack(side="left", padx=(12, 0))
        self.cancel_button = RoundedButton(
            url_row,
            text="",
            icon="cancel",
            command=self.on_cancel_job,
            height=44,
            min_width=110,
            radius=11,
            bg=SOFT_BUTTON,
            hover_bg="#fdeeee",
            fg=DANGER,
            border="#edf0f4",
            active_border="#f2d2d2",
            font=("Segoe UI", 10),
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self._set_cancel_button_state(False)

        self.url_context_menu = tk.Menu(self.root, tearoff=False)
        self.url_context_menu.add_command(label="Paste", command=self.paste_into_url_entry)
        self.url_error_label = tk.Label(
            shell,
            textvariable=self.url_error_var,
            fg="#b94a48",
            bg=BG,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )

        self.download_dir_label = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 10), anchor="w")
        self.download_dir_label.pack(fill="x")
        folder_row = tk.Frame(shell, bg=BG)
        folder_row.pack(fill="x", pady=(7, 18))
        self.folder_field = RoundedField(folder_row, variable=self.download_dir_var, readonly=True, height=38, font=("Segoe UI", 10))
        self.folder_field.pack(side="left", fill="x", expand=True)
        self.download_dir_entry = self.folder_field.entry
        self.choose_folder_button = RoundedButton(
            folder_row,
            text="",
            icon="folder",
            command=self.choose_folder,
            height=38,
            min_width=150,
            radius=10,
            bg=CARD,
            hover_bg=SOFT_BUTTON,
            border=BORDER,
            active_border="#d4dde7",
            font=("Segoe UI", 10),
        )
        self.choose_folder_button.pack(side="left", padx=(10, 0))

        self.preset_title = tk.Label(shell, bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold"), anchor="w")
        self.preset_title.pack(fill="x", pady=(0, 9))
        preset_row = tk.Frame(shell, bg=BG)
        preset_row.pack(fill="x", pady=(0, 18))
        icons = {
            "mp4_1080": "video",
            "mp4_720": "video",
            "mp3": "music",
            "mkv": "box",
            "original": "document",
        }
        for index, (key, _mode, _quality) in enumerate(previous.PRESETS):
            preset_row.columnconfigure(index, weight=1, uniform="preset")
            button = RoundedButton(
                preset_row,
                text="",
                icon=icons[key],
                command=lambda preset=key: self.select_preset(preset),
                height=44,
                min_width=120,
                radius=11,
                bg=CARD,
                hover_bg=SOFT_BUTTON,
                fg=TEXT,
                border=BORDER,
                active_border="#d4dde7",
                font=("Segoe UI", 10),
            )
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 7, 0))
            self._preset_buttons[key] = button

        progress_card = tk.Canvas(shell, height=154, bg=BG, bd=0, highlightthickness=0)
        progress_card.pack(fill="x", pady=(0, 14))
        progress_content = tk.Frame(progress_card, bg=CARD)
        progress_window = progress_card.create_window(18, 14, window=progress_content, anchor="nw")

        def resize_progress_card(_event: tk.Event[tk.Misc]) -> None:
            width = max(100, progress_card.winfo_width())
            height = max(100, progress_card.winfo_height())
            progress_card.delete("card-bg")
            _rounded_rectangle(
                progress_card,
                1,
                1,
                width - 1,
                height - 1,
                14,
                fill=CARD,
                outline=BORDER,
                width=1,
                tags="card-bg",
            )
            progress_card.tag_lower("card-bg")
            progress_card.coords(progress_window, 18, 14)
            progress_card.itemconfigure(progress_window, width=max(30, width - 36), height=max(30, height - 28))

        progress_card.bind("<Configure>", resize_progress_card)
        self.progress_frame = progress_content
        self.overall_title_var = tk.StringVar(value="")

        overall_header = tk.Frame(progress_content, bg=CARD)
        overall_header.pack(fill="x")
        tk.Label(overall_header, textvariable=self.overall_title_var, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(overall_header, textvariable=self.progress_text_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="right")
        self.progress_bar = tk.Canvas(progress_content, height=10, bg=CARD, bd=0, highlightthickness=0)
        self.progress_bar._fill_color = PRIMARY  # type: ignore[attr-defined]
        self.progress_bar.pack(fill="x", pady=(8, 15))
        self.progress_bar_fill = 0
        self.progress_bar.bind("<Configure>", self.on_total_progress_resize)

        stage_header = tk.Frame(progress_content, bg=CARD)
        stage_header.pack(fill="x")
        self.stage_status_label = tk.Label(stage_header, textvariable=self.task_status_var, bg=CARD, fg=TEXT, font=("Segoe UI", 10))
        self.stage_status_label.pack(side="left")
        tk.Label(stage_header, textvariable=self.task_progress_text_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="right")
        self.task_progress_bar = tk.Canvas(progress_content, height=8, bg=CARD, bd=0, highlightthickness=0)
        self.task_progress_bar._fill_color = BLUE  # type: ignore[attr-defined]
        self.task_progress_bar.pack(fill="x", pady=(8, 10))
        self.task_progress_bar_fill = 0
        self.task_progress_bar.bind("<Configure>", self.on_task_progress_resize)

        self.status_line = tk.Label(progress_content, textvariable=self.status_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.status_line.pack(fill="x")

        self.log_frame = tk.Frame(shell, bg=BG)
        self.log_frame.pack(fill="both", expand=True)
        log_header = tk.Frame(self.log_frame, bg=BG)
        log_header.pack(fill="x")
        self.log_toggle_button = RoundedButton(
            log_header,
            text="",
            command=self.toggle_log,
            height=34,
            min_width=165,
            radius=9,
            bg=SOFT_BUTTON,
            hover_bg=SOFT_BUTTON_HOVER,
            fg=TEXT,
            border="#edf0f4",
            active_border="#e1e6ec",
            font=("Segoe UI", 10),
        )
        self.log_toggle_button.pack(side="left")

        self.log_body = tk.Frame(self.log_frame, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.log_body.pack(fill="both", expand=True, pady=(9, 0))
        self.log_text = tk.Text(
            self.log_body,
            wrap="word",
            font=("Cascadia Mono", 9),
            height=5,
            state="disabled",
            exportselection=False,
            relief="flat",
            bd=0,
            bg=CARD_ALT,
            fg="#3e4b61",
            padx=12,
            pady=10,
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
        canvas = tk.Canvas(parent, width=42, height=32, bd=0, bg=BG, highlightthickness=0, cursor="hand2")
        canvas.pack(side="left", padx=(0, 6))
        canvas._language = language  # type: ignore[attr-defined]
        canvas.bind("<Configure>", lambda _event, c=canvas: self._draw_flag(c))
        canvas.bind("<Button-1>", lambda _event, lang=language: self.set_language(lang))
        self.root.after_idle(lambda c=canvas: self._draw_flag(c))
        return canvas

    def _draw_flag(self, canvas: tk.Canvas) -> None:
        language = str(getattr(canvas, "_language", "ru"))
        selected = language == self.language
        canvas.delete("all")
        width = max(42, canvas.winfo_width())
        height = max(32, canvas.winfo_height())
        _rounded_rectangle(
            canvas,
            1,
            1,
            width - 1,
            height - 1,
            9,
            fill=BLUE_SOFT if selected else CARD,
            outline="#b7caf2" if selected else BORDER,
            width=1,
        )
        x0, y0, x1, y1 = 9, 8, 33, 24
        if language == "ru":
            canvas.create_rectangle(x0, y0, x1, y0 + 5, fill="#ffffff", outline="")
            canvas.create_rectangle(x0, y0 + 5, x1, y0 + 11, fill="#4169b5", outline="")
            canvas.create_rectangle(x0, y0 + 11, x1, y1, fill="#d65a52", outline="")
            canvas.create_rectangle(x0, y0, x1, y1, outline="#cbd2dc")
        else:
            canvas.create_rectangle(x0, y0, x1, y1, fill="#29467c", outline="")
            canvas.create_line(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill="white", width=4)
            canvas.create_line(x1 - 1, y0 + 1, x0 + 1, y1 - 1, fill="white", width=4)
            canvas.create_line(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill="#bd5260", width=1)
            canvas.create_line(x1 - 1, y0 + 1, x0 + 1, y1 - 1, fill="#bd5260", width=1)
            canvas.create_rectangle(17, y0, 25, y1, fill="white", outline="")
            canvas.create_rectangle(x0, 12, x1, 20, fill="white", outline="")
            canvas.create_rectangle(20, y0, 22, y1, fill="#bd5260", outline="")
            canvas.create_rectangle(x0, 15, x1, 17, fill="#bd5260", outline="")
            canvas.create_rectangle(x0, y0, x1, y1, outline="#cbd2dc")

    def _refresh_flag_styles(self) -> None:
        for canvas in self._flag_canvases.values():
            self._draw_flag(canvas)

    def _refresh_preset_styles(self) -> None:
        active = self._preset_from_settings()
        for key, button in self._preset_buttons.items():
            if key == active:
                button.configure(
                    bg=BLUE_SOFT,
                    fg=BLUE,
                    activebackground=BLUE_SOFT_HOVER,
                    highlightbackground="#b9cdf5",
                    highlightcolor=BLUE,
                )
            else:
                button.configure(
                    bg=CARD,
                    fg=TEXT,
                    activebackground=SOFT_BUTTON,
                    highlightbackground=BORDER,
                    highlightcolor="#d5dde7",
                )

    def _set_cancel_button_state(self, enabled: bool) -> None:
        if enabled:
            self.cancel_button.configure(
                state="normal",
                bg="#fff3f3",
                fg=DANGER,
                activebackground="#fde7e7",
                highlightbackground="#f0caca",
                highlightcolor="#e6b7b7",
                cursor="hand2",
            )
        else:
            self.cancel_button.configure(
                state="disabled",
                bg="#f5f7f9",
                fg="#a0a9b5",
                activebackground="#f5f7f9",
                highlightbackground="#edf0f3",
                highlightcolor="#edf0f3",
                cursor="arrow",
            )

    def _render_progress_canvas(self, canvas: tk.Canvas, fill_id: int, value: float) -> None:
        del fill_id
        width = max(0, canvas.winfo_width())
        height = max(0, canvas.winfo_height())
        if width <= 1 or height <= 1:
            return
        canvas.delete("progress-shape")
        _rounded_rectangle(canvas, 0, 0, width, height, height / 2, fill=BAR_BG, outline="", tags="progress-shape")
        fill_width = width * max(0.0, min(100.0, value)) / 100.0
        if fill_width > 0.5:
            color = str(getattr(canvas, "_fill_color", BLUE))
            _rounded_rectangle(
                canvas,
                0,
                0,
                fill_width,
                height,
                min(height / 2, fill_width / 2),
                fill=color,
                outline="",
                tags="progress-shape",
            )

    def _render_task_busy_frame(self) -> None:
        width = max(0, self.task_progress_bar.winfo_width())
        height = max(0, self.task_progress_bar.winfo_height())
        if width <= 1 or height <= 1:
            return
        self.task_progress_bar.delete("progress-shape")
        _rounded_rectangle(
            self.task_progress_bar,
            0,
            0,
            width,
            height,
            height / 2,
            fill=BAR_BG,
            outline="",
            tags="progress-shape",
        )
        segment_width = max(30, width // 5)
        offset = self.task_progress_busy_offset
        start = max(0, offset - segment_width)
        end = min(width, offset)
        if end > start:
            _rounded_rectangle(
                self.task_progress_bar,
                start,
                0,
                end,
                height,
                min(height / 2, (end - start) / 2),
                fill=BLUE,
                outline="",
                tags="progress-shape",
            )

    def refresh_ui_language(self) -> None:
        super().refresh_ui_language()
        self.start_button.configure(text=self.ui("download"))
        self.cancel_button.configure(text=self.tr("button_cancel_job"))
        self.choose_folder_button.configure(text=self.tr("button_choose_folder"))
        labels = {
            "mp4_1080": "MP4 1080p",
            "mp4_720": "MP4 720p",
            "mp3": "MP3",
            "mkv": "MKV",
            "original": self.ui("preset_original"),
        }
        for key, button in self._preset_buttons.items():
            button.configure(text=labels.get(key, ""))

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
    errors: list[str] = []
    if BG == CARD or not PRIMARY.startswith("#") or not BLUE.startswith("#"):
        errors.append("UI palette is invalid.")
    probe = tk.Tcl()
    del probe
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
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
