import ctypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

ENGLISH_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
_FONTS_LOADED = False


@dataclass(frozen=True)
class ThemePalette:
    name: str
    is_dark: bool
    window_bg: str
    surface_bg: str
    card_bg: str
    card_hover_bg: str
    card_border: str
    card_glow_border: str
    rail_bg: str
    accent_primary: str
    accent_secondary: str
    accent_soft_bg: str
    text_primary: str
    text_secondary: str
    text_muted: str
    button_text_on_accent: str
    input_bg: str
    danger: str
    warning: str
    emerald: str
    verified: str
    shadow_color: QColor


DARK_PALETTE = ThemePalette(
    name="dark",
    is_dark=True,
    window_bg="#090B10",
    surface_bg="#0E121A",
    card_bg="rgba(18, 23, 33, 0.92)",
    card_hover_bg="rgba(26, 33, 46, 0.96)",
    card_border="rgba(255, 255, 255, 0.09)",
    card_glow_border="rgba(255, 208, 0, 0.30)",
    rail_bg="#0C0F16",
    accent_primary="#FFD000",
    accent_secondary="#FFFFFF",
    accent_soft_bg="rgba(255, 208, 0, 0.14)",
    text_primary="#F8FAFC",
    text_secondary="#CBD5E1",
    text_muted="#7C8BA1",
    button_text_on_accent="#090B10",
    input_bg="#0C1018",
    danger="#EF4444",
    warning="#F97316",
    emerald="#10B981",
    verified="#10B981",
    shadow_color=QColor(0, 0, 0, 185),
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    window_bg="#F8FAFC",
    surface_bg="#FFFFFF",
    card_bg="rgba(255, 255, 255, 0.96)",
    card_hover_bg="#FFFFFF",
    card_border="rgba(15, 23, 42, 0.10)",
    card_glow_border="rgba(245, 184, 0, 0.48)",
    rail_bg="#F1F5F9",
    accent_primary="#F5B800",
    accent_secondary="#0F172A",
    accent_soft_bg="rgba(245, 184, 0, 0.16)",
    text_primary="#0F172A",
    text_secondary="#334155",
    text_muted="#64748B",
    button_text_on_accent="#0F172A",
    input_bg="#F1F5F9",
    danger="#DC2626",
    warning="#EA580C",
    emerald="#059669",
    verified="#059669",
    shadow_color=QColor(15, 23, 42, 42),
)


def load_application_fonts() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    _FONTS_LOADED = True
    search_dirs = [
        Path("assets/fonts"),
        Path("assets"),
        Path("fonts"),
        Path(__file__).resolve().parent / "fonts",
        Path(__file__).resolve().parent.parent / "assets" / "fonts",
    ]
    seen: set[Path] = set()
    for folder in search_dirs:
        if not folder.is_dir():
            continue
        for ext in ("*.ttf", "*.otf"):
            for font_file in folder.glob(ext):
                resolved = font_file.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    QFontDatabase.addApplicationFont(str(resolved))


def resolve_persian_font_family() -> str:
    load_application_fonts()
    preferred = [
        "Vazirmatn",
        "Vazirmatn UI",
        "IRANSansX",
        "IRANSans",
        "Estedad",
        "Yekan Bakh",
        "Shabnam",
        "Segoe UI Variable Display",
        "Segoe UI Variable Text",
        "Segoe UI",
        "Tahoma",
    ]
    available = set(QFontDatabase.families())
    for family in preferred:
        if family in available:
            return family
    return "Segoe UI"


def resolve_mono_font_family() -> str:
    load_application_fonts()
    preferred = ["JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"]
    available = set(QFontDatabase.families())
    for family in preferred:
        if family in available:
            return family
    return "Consolas"


def make_ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    font = QFont(resolve_persian_font_family(), size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    return font


def make_mono_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont(resolve_mono_font_family(), size)
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.DemiBold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    return font


def enforce_english_ltr(widget: QWidget, mono_size: int = 10, bold: bool = False) -> None:
    widget.setLocale(ENGLISH_LOCALE)
    widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    widget.setFont(make_mono_font(mono_size, bold=bold))


def lock_widget_dimensions(widget: QWidget, width: int, height: int) -> None:
    widget.setMinimumSize(width, height)
    widget.setMaximumSize(width, height)


def make_transparent_scroll_area(content_widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll.setAutoFillBackground(False)

    viewport = scroll.viewport()
    viewport.setObjectName("ScrollViewport")
    viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    viewport.setAutoFillBackground(False)

    content_widget.setObjectName("ScrollContent")
    content_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    content_widget.setAutoFillBackground(False)

    scroll.setWidget(content_widget)
    return scroll


def sanitize_ui_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"(?i)\bbehrooz\b", "Alan-Core", str(text))
    cleaned = re.sub(r"(?i)\boob\b", "PulseSync", cleaned)
    return cleaned


def apply_windows_titlebar_theme(widget: QWidget, is_dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1 if is_dark else 0)
        for attr in (20, 19):
            res = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(dark_val),
                ctypes.sizeof(dark_val),
            )
            if res == 0:
                break
        caption_color = ctypes.c_uint(0x00100B09 if is_dark else 0x00FCFAF8)
        text_color = ctypes.c_uint(0x00FAFAF8 if is_dark else 0x002A170F)
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(35),
            ctypes.byref(caption_color),
            ctypes.sizeof(caption_color),
        )
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(36),
            ctypes.byref(text_color),
            ctypes.sizeof(text_color),
        )
    except Exception:
        pass


def build_qpalette(p: ThemePalette) -> QPalette:
    pal = QPalette()
    bg = QColor(p.window_bg)
    surface = QColor(p.surface_bg)
    fg = QColor(p.text_primary)
    accent = QColor(p.accent_primary)
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, fg)
    pal.setColor(QPalette.ColorRole.Base, surface)
    pal.setColor(QPalette.ColorRole.AlternateBase, bg)
    pal.setColor(QPalette.ColorRole.Text, fg)
    pal.setColor(QPalette.ColorRole.Button, surface)
    pal.setColor(QPalette.ColorRole.ButtonText, fg)
    pal.setColor(QPalette.ColorRole.ToolTipBase, surface)
    pal.setColor(QPalette.ColorRole.ToolTipText, fg)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p.button_text_on_accent))
    return pal


def build_stylesheet(p: ThemePalette) -> str:
    family = resolve_persian_font_family()
    mono = resolve_mono_font_family()
    badge_fg = p.accent_primary if p.is_dark else "#9A6B00"
    return f"""
    QWidget {{
        font-family: '{family}', 'Segoe UI Variable Display', 'Segoe UI', 'Tahoma';
        font-size: 12px;
        font-weight: 500;
        color: {p.text_primary};
        outline: none;
    }}
    QToolTip {{
        background-color: {p.surface_bg};
        color: {p.text_primary};
        border: 1px solid {p.card_glow_border};
        border-radius: 8px;
        padding: 5px 10px;
        font-family: '{family}', 'Segoe UI';
        font-size: 11px;
        font-weight: 600;
    }}
    QScrollArea,
    QScrollArea > QWidget,
    QScrollArea > QWidget > QWidget,
    QWidget#ScrollViewport,
    QWidget#ScrollContent {{
        background: transparent;
        background-color: transparent;
        border: none;
    }}
    QFrame#MainShell {{
        background-color: {p.window_bg};
        border: none;
        border-radius: 0px;
    }}
    QFrame#TopBrandBar {{
        background-color: {p.rail_bg};
        border-bottom: 1px solid {p.card_border};
    }}
    QFrame#NavRail {{
        background-color: {p.rail_bg};
        border-left: 1px solid {p.card_border};
        border-radius: 0px;
    }}
    QFrame#GlobalTaskBar {{
        background-color: {p.surface_bg};
        border-bottom: 1px solid {p.card_glow_border};
    }}
    QFrame#InlineTaskBar {{
        background-color: {p.card_bg};
        border: 1px solid {p.card_glow_border};
        border-radius: 12px;
    }}
    QFrame#GlassCard {{
        background-color: {p.card_bg};
        border: 1px solid {p.card_border};
        border-radius: 16px;
    }}
    QFrame#HeroCard {{
        background-color: {p.card_bg};
        border: 1px solid {p.card_glow_border};
        border-radius: 20px;
    }}
    QFrame#SubtleCard {{
        background-color: {p.input_bg};
        border: 1px solid {p.card_border};
        border-radius: 13px;
    }}
    QFrame#PillBar {{
        background-color: {p.card_bg};
        border: 1px solid {p.card_border};
        border-radius: 14px;
    }}
    QDialog#ThemedDialog {{
        background-color: {p.surface_bg};
        border: none;
        border-radius: 0px;
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel#MutedLabel {{
        color: {p.text_muted};
        font-size: 11px;
        font-weight: 500;
    }}
    QLabel#SecondaryLabel {{
        color: {p.text_secondary};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#HeadlineLabel {{
        color: {p.text_primary};
        font-size: 24px;
        font-weight: 800;
    }}
    QLabel#BadgePill {{
        background-color: {p.accent_soft_bg};
        color: {badge_fg};
        border: 1px solid {p.card_glow_border};
        border-radius: 10px;
        padding: 3px 10px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#TunActivePill {{
        background-color: rgba(16, 185, 129, 0.18);
        color: {p.emerald};
        border: 1px solid rgba(16, 185, 129, 0.50);
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#TunOffPill {{
        background-color: rgba(100, 116, 139, 0.14);
        color: {p.text_muted};
        border: 1px solid {p.card_border};
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#PhaseStandby {{
        background-color: rgba(148, 163, 184, 0.14);
        color: {badge_fg};
        border: 1px solid {p.card_glow_border};
        border-radius: 10px;
        padding: 4px 12px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#PhaseProbing {{
        background-color: rgba(249, 115, 22, 0.18);
        color: #FB923C;
        border: 1px solid rgba(249, 115, 22, 0.55);
        border-radius: 10px;
        padding: 4px 12px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#PhaseOnline {{
        background-color: rgba(16, 185, 129, 0.18);
        color: {p.emerald};
        border: 1px solid rgba(16, 185, 129, 0.55);
        border-radius: 10px;
        padding: 4px 12px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#PhaseError {{
        background-color: rgba(239, 68, 68, 0.16);
        color: {p.danger};
        border: 1px solid rgba(239, 68, 68, 0.45);
        border-radius: 10px;
        padding: 4px 12px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#RankGold {{
        background-color: rgba(255, 208, 0, 0.22);
        color: {badge_fg};
        border: 1px solid #FFD000;
        border-radius: 9px;
        padding: 2px 8px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#RankSilver {{
        background-color: rgba(203, 213, 225, 0.20);
        color: {p.text_primary};
        border: 1px solid #94A3B8;
        border-radius: 9px;
        padding: 2px 8px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#RankBronze {{
        background-color: rgba(217, 119, 6, 0.20);
        color: #F59E0B;
        border: 1px solid #D97706;
        border-radius: 9px;
        padding: 2px 8px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#RankDefault {{
        background-color: rgba(100, 116, 139, 0.14);
        color: {p.text_secondary};
        border: 1px solid {p.card_border};
        border-radius: 9px;
        padding: 2px 8px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#StatusVerified {{
        background-color: rgba(16, 185, 129, 0.15);
        color: {p.emerald};
        border: 1px solid rgba(16, 185, 129, 0.40);
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#StatusPartial {{
        background-color: rgba(245, 158, 11, 0.16);
        color: #F59E0B;
        border: 1px solid rgba(245, 158, 11, 0.42);
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#StatusDead {{
        background-color: rgba(239, 68, 68, 0.14);
        color: {p.danger};
        border: 1px solid rgba(239, 68, 68, 0.38);
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QLabel#StatusUntested {{
        background-color: rgba(100, 116, 139, 0.16);
        color: {p.text_muted};
        border: 1px solid {p.card_border};
        border-radius: 10px;
        padding: 2px 9px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit#RawUriEdit {{
        background-color: {p.input_bg};
        color: {p.text_primary};
        border: 1px solid {p.card_border};
        border-radius: 11px;
        padding: 6px 12px;
        min-height: 25px;
        font-weight: 600;
        selection-background-color: {p.accent_primary};
        selection-color: {p.button_text_on_accent};
    }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit#RawUriEdit:focus {{
        border: 1px solid {p.card_glow_border};
    }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QPlainTextEdit#RawUriEdit:disabled {{
        color: {p.text_muted};
        background-color: rgba(100, 116, 139, 0.08);
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface_bg};
        color: {p.text_primary};
        border: 1px solid {p.card_glow_border};
        border-radius: 10px;
        selection-background-color: {p.accent_soft_bg};
        selection-color: {p.text_primary};
        padding: 4px;
        font-weight: 600;
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background: transparent;
        border: none;
        width: 18px;
    }}
    QCheckBox {{
        color: {p.text_secondary};
        spacing: 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {p.card_glow_border};
        background-color: {p.input_bg};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p.accent_primary};
        border: 1px solid {p.accent_primary};
    }}
    QPushButton#GhostPillBtn {{
        background-color: {p.input_bg};
        color: {p.text_secondary};
        border: 1px solid {p.card_border};
        border-radius: 11px;
        padding: 6px 13px;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#GhostPillBtn:hover {{
        background-color: {p.accent_soft_bg};
        color: {p.text_primary};
        border: 1px solid {p.card_glow_border};
    }}
    QPushButton#AmberPillBtn {{
        background-color: rgba(255, 208, 0, 0.14);
        color: {badge_fg};
        border: 1px solid {p.card_glow_border};
        border-radius: 11px;
        padding: 6px 13px;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#AmberPillBtn:hover {{
        background-color: rgba(255, 208, 0, 0.26);
    }}
    QPushButton#SuccessPillBtn {{
        background-color: rgba(16, 185, 129, 0.16);
        color: {p.emerald};
        border: 1px solid rgba(16, 185, 129, 0.42);
        border-radius: 11px;
        padding: 6px 13px;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#SuccessPillBtn:hover {{
        background-color: rgba(16, 185, 129, 0.28);
    }}
    QPushButton#DangerPillBtn {{
        background-color: rgba(239, 68, 68, 0.14);
        color: {p.danger};
        border: 1px solid rgba(239, 68, 68, 0.36);
        border-radius: 11px;
        padding: 6px 13px;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#DangerPillBtn:hover {{
        background-color: rgba(239, 68, 68, 0.28);
    }}
    QPushButton#DangerSolidBtn {{
        background-color: {p.danger};
        color: #FFFFFF;
        border: none;
        border-radius: 11px;
        padding: 7px 15px;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#DangerSolidBtn:hover {{
        background-color: #DC2626;
    }}
    QPushButton#DangerSolidBtn:disabled {{
        background-color: rgba(100, 116, 139, 0.25);
        color: {p.text_muted};
    }}
    QPushButton#AccentBtn {{
        background-color: {p.accent_primary};
        color: {p.button_text_on_accent};
        border: none;
        border-radius: 11px;
        padding: 7px 16px;
        font-weight: 800;
        font-size: 11px;
    }}
    QPushButton#AccentBtn:hover {{
        background-color: #FFE047;
    }}
    QPushButton#AccentBtn:disabled {{
        background-color: rgba(100, 116, 139, 0.25);
        color: {p.text_muted};
    }}
    QProgressBar#GoldProgress {{
        background-color: {p.input_bg};
        border: 1px solid {p.card_border};
        border-radius: 5px;
        height: 8px;
        text-align: center;
    }}
    QProgressBar#GoldProgress::chunk {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:0.5 #FFD000, stop:1 #FFF066);
        border-radius: 4px;
    }}
    QPlainTextEdit#LogConsole {{
        background-color: {p.input_bg};
        color: {p.text_secondary};
        border: 1px solid {p.card_border};
        border-radius: 14px;
        padding: 12px;
        font-family: '{mono}', 'Consolas', monospace;
        font-size: 12px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 1px 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.card_glow_border};
        min-height: 28px;
        border-radius: 3px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0px;
    }}
    """