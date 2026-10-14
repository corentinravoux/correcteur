"""Colours, fonts and the Qt style sheet, in a light and a dark variant.

The window is a desk with a sheet of paper on it. The four issue colours are the
only saturated colours, so an underline is the first thing the eye finds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

ICON = Path(__file__).parent / "resources" / "correcteur.svg"
SERIF = ["Charter", "Bitstream Charter", "Source Serif 4", "Noto Serif", "DejaVu Serif"]


@dataclass(frozen=True)
class Theme:
    name: str
    desk: str       # window background
    paper: str      # the sheet, menus, buttons
    ink: str        # text
    muted: str      # secondary text
    rule: str       # borders and separators
    hover: str
    selection: str
    focus: str
    kinds: dict[str, str]
    tint: int       # alpha of the background behind underlined text


LIGHT = Theme(
    name="light", desk="#E8EAED", paper="#FFFFFF", ink="#1E2227", muted="#646B75", rule="#D3D8DE",
    hover="#F1F3F5", selection="#CDDDF5", focus="#2563B8",
    kinds={"spelling": "#C4302B", "grammar": "#2563B8", "style": "#2F7D4E", "typography": "#9A5B00"},
    tint=26,
)
DARK = Theme(
    name="dark", desk="#141619", paper="#1E2125", ink="#E4E6E9", muted="#969CA5", rule="#30353B",
    hover="#272B30", selection="#2C4466", focus="#6FA3F0",
    kinds={"spelling": "#F2736B", "grammar": "#6FA3F0", "style": "#6CC28F", "typography": "#E3A64A"},
    tint=40,
)


def current() -> Theme:
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def serif(points: float) -> QFont:
    font = QFont()
    font.setFamilies(SERIF)
    font.setStyleHint(QFont.StyleHint.Serif)
    font.setPointSizeF(points)
    return font


def palette(t: Theme) -> QPalette:
    p = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, t.desk), (QPalette.ColorRole.WindowText, t.ink),
        (QPalette.ColorRole.Base, t.paper), (QPalette.ColorRole.AlternateBase, t.hover),
        (QPalette.ColorRole.Text, t.ink), (QPalette.ColorRole.PlaceholderText, t.muted),
        (QPalette.ColorRole.Button, t.paper), (QPalette.ColorRole.ButtonText, t.ink),
        (QPalette.ColorRole.Highlight, t.selection), (QPalette.ColorRole.HighlightedText, t.ink),
        (QPalette.ColorRole.ToolTipBase, t.paper), (QPalette.ColorRole.ToolTipText, t.ink),
        (QPalette.ColorRole.Link, t.focus),
    ):
        p.setColor(role, QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.muted))
    return p


def stylesheet(t: Theme) -> str:
    return f"""
    QWidget#desk {{ background: {t.desk}; }}
    QLabel {{ color: {t.ink}; }}
    QLabel[muted="true"] {{ color: {t.muted}; }}

    QPlainTextEdit#sheet {{
        background: {t.paper}; color: {t.ink};
        border: 1px solid {t.rule}; border-radius: 6px;
        selection-background-color: {t.selection}; selection-color: {t.ink};
    }}
    QPlainTextEdit#sheet:focus {{ border-color: {t.focus}; }}

    QPushButton {{
        background: {t.paper}; color: {t.ink};
        border: 1px solid {t.rule}; border-radius: 5px; padding: 6px 14px;
    }}
    QPushButton:hover {{ border-color: {t.muted}; }}
    QPushButton:pressed {{ background: {t.hover}; }}
    QPushButton:focus {{ border-color: {t.focus}; }}
    QPushButton:disabled {{ color: {t.muted}; background: transparent; border-color: {t.rule}; }}
    QPushButton#primary {{ background: {t.ink}; color: {t.paper}; border-color: {t.ink}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t.muted}; border-color: {t.muted}; }}
    QPushButton#primary:focus {{ border: 2px solid {t.focus}; padding: 5px 13px; }}
    QPushButton#chip {{ padding: 3px 9px; font-weight: 600; }}
    QPushButton#link {{ background: transparent; border: none; color: {t.muted}; padding: 2px 0; }}
    QPushButton#link:hover, QPushButton#link:focus {{ color: {t.ink}; text-decoration: underline; }}

    QComboBox {{
        background: {t.paper}; color: {t.ink};
        border: 1px solid {t.rule}; border-radius: 5px; padding: 5px 10px;
    }}
    QComboBox:hover {{ border-color: {t.muted}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url({(ICON.parent / f"chevron-{t.name}.svg").as_posix()}); width: 12px; height: 12px; }}
    QComboBox:focus {{ border-color: {t.focus}; }}
    QComboBox QAbstractItemView {{
        background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule};
        selection-background-color: {t.hover}; selection-color: {t.ink}; outline: none;
    }}
    QLineEdit {{
        background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule}; border-radius: 5px; padding: 5px 8px;
        selection-background-color: {t.selection}; selection-color: {t.ink};
    }}
    QLineEdit:focus {{ border-color: {t.focus}; }}
    QTreeWidget {{
        background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule}; border-radius: 6px;
        alternate-background-color: {t.hover}; outline: none;
    }}
    QTreeWidget::item {{ padding: 4px 2px; }}
    QTreeWidget::item:selected {{ background: {t.selection}; color: {t.ink}; }}
    QHeaderView::section {{
        background: {t.paper}; color: {t.muted}; border: none; border-bottom: 1px solid {t.rule};
        padding: 5px 6px;
    }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {t.rule}; }}
    QTabBar::tab {{
        background: transparent; color: {t.muted}; padding: 7px 14px; border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {t.ink}; border-bottom-color: {t.ink}; }}
    QTabBar::tab:hover {{ color: {t.ink}; }}
    QDialog {{ background: {t.desk}; }}
    QCheckBox {{ color: {t.ink}; spacing: 7px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {t.muted}; border-radius: 3px; background: {t.paper};
    }}
    QCheckBox::indicator:hover, QCheckBox::indicator:focus {{ border-color: {t.focus}; }}
    QCheckBox::indicator:checked {{
        background: {t.ink}; border-color: {t.ink};
        image: url({(ICON.parent / f"check-{t.name}.svg").as_posix()});
    }}

    QScrollArea#margin, QWidget#marginInner {{ background: transparent; border: none; }}
    QFrame#note {{ background: transparent; border: none; border-bottom: 1px solid {t.rule}; }}
    QFrame#note:hover {{ background: {t.hover}; }}
    QFrame#note[current="true"] {{ background: {t.hover}; border-bottom: 1px solid {t.focus}; }}

    QMenu {{ background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule}; padding: 4px; }}
    QMenu::item {{ padding: 5px 20px 5px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QMenu::separator {{ height: 1px; background: {t.rule}; margin: 4px 6px; }}
    QToolTip {{ background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule}; padding: 6px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.rule}; border-radius: 3px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: none; }}
    """
