from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk

import mini_url_converter as core
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


def _load_icon(master: tk.Misc, icon_key: str, target_size: int) -> tk.PhotoImage:
    source = tk.PhotoImage(master=master, file=str(icon_path(icon_key)))
    longest = max(source.width(), source.height())
    if longest <= target_size:
        return source
    factor = max(1, longest // target_size)
    return source.subsample(factor, factor)


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
        except (tk.TclError, OSError, KeyError):
            return
        cache[icon_key] = image
    self.create_image(cx, cy, image=image, anchor="center")


# RoundedButton remains responsible for hover/disabled states and rounded
# geometry; only its hand-drawn icon layer is replaced with real PNG assets.
previous.RoundedButton._draw_icon = _draw_asset_icon  # type: ignore[method-assign]


class App(previous.App):
    def _refresh_log_toggle_text(self) -> None:
        button = getattr(self, "log_toggle_button", None)
        if button is None:
            return
        button._icon = "chevron-down" if self._log_expanded else "chevron-right"  # type: ignore[attr-defined]
        button.configure(text=self.ui("details_log"))

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
        except (tk.TclError, OSError, KeyError):
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
