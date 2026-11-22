"""Tray icon: the gold 7Hills "7" with a small bind mark. Minimize/close hide the window here."""

from __future__ import annotations

from typing import Callable

GOLD = (240, 180, 67, 255)
LOGO = [(65, 91), (446, 91), (256, 421), (214, 349), (325, 157), (103, 157)]


def icon_image(size: int = 64):
    from PIL import Image, ImageDraw

    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, x1, y0, y1 = 65, 446, 91, 421
    scale = big * 0.96 / max(x1 - x0, y1 - y0)
    ox = (big - (x1 - x0) * scale) / 2
    oy = (big - (y1 - y0) * scale) / 2
    d.polygon([(ox + (x - x0) * scale, oy + (y - y0) * scale) for x, y in LOGO], fill=GOLD)
    # Small white square bottom-right: tells 7Bind apart from 7Hills Link in the tray.
    s = big * 0.30
    d.rounded_rectangle([big - s, big - s, big - 2, big - 2], radius=big * 0.05, fill=(232, 232, 232, 255))
    return img.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, on_open: Callable[[], None], on_backup: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.icon = None
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem("Open 7Bind", lambda *_: on_open(), default=True),
                pystray.MenuItem("Back up now", lambda *_: on_backup()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: on_quit()),
            )
            self.icon = pystray.Icon("7Bind", icon_image(), "7Bind", menu)
        except Exception:
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def start(self) -> None:
        if self.icon:
            try:
                self.icon.run_detached()
            except Exception:
                self.icon = None

    def set_title(self, text: str) -> None:
        if self.icon:
            try:
                self.icon.title = text[:120]
            except Exception:
                pass

    def stop(self) -> None:
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
