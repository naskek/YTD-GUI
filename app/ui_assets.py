from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageOps, ImageTk

import mini_url_converter as core
import release_app as release_layer
import ui_polish as previous


ICON_FILES = {
    "download": "download.png",
    "cancel": "cancel.png",
    "folder": "folder.png",
    "settings": "settings.png",
    "video": "video.png",
    "music": "music.png",
    "box": "film.png",
    "document": "document.png",
    "chevron-right": "chevron-right.png",
    "chevron-down": "chevron-down.png",
    "flag-ru": "flag-ru.png",
    "flag-en": "flag-en.png",
}

ICON_SIZES = {
    "chevron-right": 18,
    "chevron-down": 18,
    "flag-ru": 30,
    "flag-en": 30,
}


# Keep the lower auth layers generic, but explain the practical cookies.txt
# export path in the release UI when YouTube requires an authenticated session.
release_layer.UI_TEXT["ru"]["cookies_required"] = (
    "Для этого видео требуется вход в YouTube. Выберите свежий cookies.txt, чтобы продолжить.\n\n"
    "Подсказка: cookies.txt можно экспортировать из Chrome расширением «Get cookies.txt LOCALLY» "
    "(формат Netscape). Файл содержит данные вашей сессии — не передавайте его другим."
)
release_layer.UI_TEXT["ru"]["cookies_retry_failed"] = (
    "YouTube отклонил выбранный cookies.txt. Экспортируйте свежий файл и попробуйте снова.\n\n"
    "Для Chrome можно использовать расширение «Get cookies.txt LOCALLY» и экспорт в формате Netscape."
)
release_layer.UI_TEXT["en"]["cookies_required"] = (
    "This video requires YouTube sign-in. Select a fresh cookies.txt to continue.\n\n"
    "Tip: you can export cookies.txt from Chrome with the “Get cookies.txt LOCALLY” extension "
    "using Netscape format. The file contains session data, so do not share it."
)
release_layer.UI_TEXT["en"]["cookies_retry_failed"] = (
    "YouTube rejected the selected cookies.txt. Export a fresh file and try again.\n\n"
    "For Chrome, you can use the “Get cookies.txt LOCALLY” extension and export in Netscape format."
)


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def icon_path(icon_key: str) -> Path:
    filename = ICON_FILES[icon_key]
    return resource_root() / "assets" / "icons" / filename


def _load_icon(master: tk.Misc, icon_key: str, target_size: int) -> ImageTk.PhotoImage:
    """Load, crop by alpha, center, and resize with high-quality filtering."""
    size = ICON_SIZES.get(icon_key, target_size)
    path = icon_path(icon_key)
    with Image.open(path) as source:
        image = source.convert("RGBA")

    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        image = image.crop(bbox)

    # Preserve the original aspect ratio and center the visible artwork on a
    # square transparent canvas. This removes uneven manual crop margins from
    # the source PNGs without modifying the source assets themselves.
    contained = ImageOps.contain(image, (size, size), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - contained.width) // 2
    y = (size - contained.height) // 2
    canvas.alpha_composite(contained, (x, y))
    return ImageTk.PhotoImage(canvas, master=master)


def _draw_asset_icon(self: previous.RoundedButton, cx: float, cy: float, color: str) -> None:
    del color
    icon_key = str(getattr(self, "_icon", ""))
    if not icon_key:
        return
    cache = getattr(self, "_asset_icon_cache", None)
    if cache is None:
        cache = {}
        self._asset_icon_cache = cache  # type: ignore[attr-defined]
    image = cache.get(icon_key)
    if image is None:
        try:
            image = _load_icon(self, icon_key, 24)
        except (OSError, KeyError, tk.TclError):
            return
        cache[icon_key] = image
    self.create_image(cx, cy, image=image, anchor="center")


# RoundedButton remains responsible for hover/disabled states and rounded
# geometry; only its hand-drawn icon layer is replaced with real PNG assets.
previous.RoundedButton._draw_icon = _draw_asset_icon  # type: ignore[method-assign]


class App(previous.App):
    def __init__(self, root: tk.Tk) -> None:
        self._log_restore_height: int | None = None
        super().__init__(root)

    def _refresh_log_toggle_text(self) -> None:
        button = getattr(self, "log_toggle_button", None)
        if button is None:
            return
        button._icon = "chevron-down" if self._log_expanded else "chevron-right"  # type: ignore[attr-defined]
        button.configure(text=self.ui("details_log"))

    def refresh_ui_language(self) -> None:
        super().refresh_ui_language()
        # release_app sets the settings button text to the gear glyph. The
        # polished UI already has a PNG gear icon, so keeping that glyph creates
        # the small duplicate gear visible at the right edge of the button.
        self.settings_button.configure(text="")

    def toggle_log(self) -> None:
        expanding = not self._log_expanded
        if expanding:
            self._log_restore_height = max(1, self.root.winfo_height())
            self._log_expanded = True
            self.log_body.pack(fill="both", expand=True, pady=(9, 0))
            self.log_text.configure(height=8)
            self._refresh_log_toggle_text()
            self.root.update_idletasks()

            width = self.root.winfo_width()
            current_height = self.root.winfo_height()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            available_height = max(current_height, self.root.winfo_screenheight() - y - 60)
            target_height = min(max(current_height, 760), available_height)
            if target_height > current_height:
                self.root.geometry(f"{width}x{target_height}+{x}+{y}")
        else:
            self._log_expanded = False
            self.log_body.pack_forget()
            self._refresh_log_toggle_text()
            restore_height = self._log_restore_height
            self._log_restore_height = None
            if restore_height:
                width = self.root.winfo_width()
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                self.root.geometry(f"{width}x{restore_height}+{x}+{y}")

    def _draw_flag(self, canvas: tk.Canvas) -> None:
        language = str(getattr(canvas, "_language", "ru"))
        selected = language == self.language
        canvas.delete("all")
        width = max(42, canvas.winfo_width())
        height = max(32, canvas.winfo_height())
        previous._rounded_rectangle(
            canvas,
            1,
            1,
            width - 1,
            height - 1,
            9,
            fill=previous.BLUE_SOFT if selected else previous.CARD,
            outline="#b7caf2" if selected else previous.BORDER,
            width=1,
        )
        icon_key = "flag-ru" if language == "ru" else "flag-en"
        try:
            image = _load_icon(canvas, icon_key, 30)
        except (OSError, KeyError, tk.TclError):
            return
        canvas._asset_flag_image = image  # type: ignore[attr-defined]
        canvas.create_image(width / 2.0, height / 2.0, image=image, anchor="center")


def self_test() -> int:
    if previous.self_test() != 0:
        return 1
    errors: list[str] = []
    for icon_key, filename in ICON_FILES.items():
        path = icon_path(icon_key)
        if not path.is_file():
            errors.append(f"Missing UI icon asset: {filename}")
    if errors:
        core._write_self_test_diagnostic("\n".join(errors) + "\n", is_error=True)
        return 1
    core._write_self_test_diagnostic("UI ASSET SELF-TEST OK\n")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
