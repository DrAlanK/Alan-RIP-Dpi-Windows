import os
import random
import math
import re
from collections import deque
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRect, QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QCheckBox,
    QLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .flag_icons import GeoFlagResolver, VectorFlagRenderer
from .theme import (
    DARK_PALETTE,
    I18N,
    ThemePalette,
    enforce_english_ltr,
    lock_widget_dimensions,
    make_mono_font,
    make_ui_font,
    strip_emojis,
)
from .vector_icons import VectorIconPainter

_RGBA_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)",
    re.IGNORECASE,
)


def parse_css_color(value: str, fallback: str = "#181F2C") -> QColor:
    raw = str(value or "").strip()
    if not raw:
        return QColor(fallback)
    m = _RGBA_RE.match(raw)
    if m:
        r = max(0, min(255, int(m.group(1))))
        g = max(0, min(255, int(m.group(2))))
        b = max(0, min(255, int(m.group(3))))
        a_str = m.group(4)
        if a_str is None:
            a = 255
        else:
            af = float(a_str)
            a = int(round(af * 255.0)) if af <= 1.0 else int(round(af))
        return QColor(r, g, b, max(0, min(255, a)))
    col = QColor(raw)
    return col if col.isValid() else QColor(fallback)


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    k = max(0.0, min(1.0, float(t)))
    return QColor(
        int(a.red() + (b.red() - a.red()) * k),
        int(a.green() + (b.green() - a.green()) * k),
        int(a.blue() + (b.blue() - a.blue()) * k),
        int(a.alpha() + (b.alpha() - a.alpha()) * k),
    )


def draw_neu_raised(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    palette: ThemePalette,
    depth: float = 5.5,
    hovered: bool = False,
    accent_tint: QColor | None = None,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)

    dark_base = parse_css_color(palette.neu_shadow_dark)
    light_base = parse_css_color(palette.neu_shadow_light)

    layers = 4
    for step in range(layers, 0, -1):
        ratio = step / layers
        shift = depth * ratio
        spread = shift * 0.40

        d_col = QColor(dark_base)
        d_col.setAlpha(max(4, int(palette.neu_dark_alpha * (1.0 - ratio * 0.70) * 0.46)))
        painter.setBrush(d_col)
        painter.drawRoundedRect(
            rect.adjusted(shift - spread, shift - spread, shift + spread, shift + spread),
            radius + spread,
            radius + spread,
        )

        l_col = QColor(light_base)
        l_col.setAlpha(max(4, int(palette.neu_light_alpha * (1.0 - ratio * 0.68) * 0.48)))
        painter.setBrush(l_col)
        painter.drawRoundedRect(
            rect.adjusted(-shift - spread, -shift - spread, -shift + spread, -shift + spread),
            radius + spread,
            radius + spread,
        )

    surf = QLinearGradient(rect.topLeft(), rect.bottomRight())
    hi_c = parse_css_color(palette.card_hover_bg if hovered else palette.surface_hi)
    mid_c = parse_css_color(palette.card_bg)
    lo_c = parse_css_color(palette.surface_lo)
    if accent_tint is not None:
        hi_c = _lerp_color(hi_c, accent_tint, 0.11 if palette.is_dark else 0.07)
        mid_c = _lerp_color(mid_c, accent_tint, 0.05 if palette.is_dark else 0.03)

    surf.setColorAt(0.0, hi_c)
    surf.setColorAt(0.52, mid_c)
    surf.setColorAt(1.0, lo_c)

    bevel = QLinearGradient(rect.topLeft(), rect.bottomRight())
    bv_l = parse_css_color(palette.neu_bevel_light)
    bv_d = parse_css_color(palette.neu_bevel_dark)
    if accent_tint is not None:
        bv_l = _lerp_color(bv_l, accent_tint, 0.45 if hovered else 0.24)
    bevel.setColorAt(0.0, bv_l)
    bevel.setColorAt(0.55, QColor(bv_l.red(), bv_l.green(), bv_l.blue(), 16))
    bevel.setColorAt(1.0, bv_d)

    painter.setBrush(surf)
    painter.setPen(QPen(bevel, 1.15))
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def draw_neu_inset(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    palette: ThemePalette,
    depth: float = 4.2,
    glow_tint: QColor | None = None,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    well_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    c_top = parse_css_color(palette.input_bg)
    c_bot = parse_css_color(palette.subtle_bg)
    if glow_tint is not None:
        c_top = _lerp_color(c_top, glow_tint, 0.20 if palette.is_dark else 0.14)
        c_bot = _lerp_color(c_bot, glow_tint, 0.12 if palette.is_dark else 0.08)
    well_grad.setColorAt(0.0, c_top)
    well_grad.setColorAt(1.0, c_bot)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(well_grad)
    painter.drawRoundedRect(rect, radius, radius)

    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    dark_col = parse_css_color(palette.neu_shadow_dark)
    light_col = parse_css_color(palette.neu_shadow_light)

    for i in range(3):
        w_pen = (3 - i) * (depth * 0.50)
        off = (i + 1) * 1.0

        dc = QColor(dark_col)
        dc.setAlpha(int(palette.neu_dark_alpha * (0.46 - i * 0.11)))
        painter.setPen(QPen(dc, w_pen))
        painter.drawRoundedRect(
            rect.adjusted(-1.0 + off, -1.0 + off, 6.0 + off, 6.0 + off),
            radius,
            radius,
        )

        lc = QColor(light_col)
        lc.setAlpha(int(palette.neu_light_alpha * (0.46 - i * 0.11)))
        painter.setPen(QPen(lc, w_pen))
        painter.drawRoundedRect(
            rect.adjusted(-6.0 - off, -6.0 - off, 1.0 - off, 1.0 - off),
            radius,
            radius,
        )

    painter.setClipping(False)
    rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
    rim.setColorAt(0.0, parse_css_color(palette.neu_bevel_dark))
    rim.setColorAt(1.0, parse_css_color(palette.neu_bevel_light))
    painter.setPen(QPen(rim, 1.05))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


_VIBRANT_FLAG_TRIADS: dict[str, tuple[str, str, str]] = {
    "IR": ("#10B981", "#FFD000", "#EF4444"),
    "DE": ("#FFD000", "#EF4444", "#F59E0B"),
    "NL": ("#3B82F6", "#94A3B8", "#F43F5E"),
    "US": ("#3B82F6", "#EF4444", "#38BDF8"),
    "GB": ("#2563EB", "#EF4444", "#38BDF8"),
    "FR": ("#3B82F6", "#60A5FA", "#EF4444"),
    "FI": ("#38BDF8", "#0284C7", "#60A5FA"),
    "SE": ("#0EA5E9", "#FACC15", "#38BDF8"),
    "CH": ("#EF4444", "#FB7185", "#DC2626"),
    "TR": ("#EF4444", "#F87171", "#DC2626"),
    "AE": ("#10B981", "#EF4444", "#34D399"),
    "SG": ("#EF4444", "#FB7185", "#F43F5E"),
    "JP": ("#F43F5E", "#FB7185", "#E11D48"),
    "CA": ("#EF4444", "#F87171", "#DC2626"),
    "PL": ("#E11D48", "#FB7185", "#F43F5E"),
    "AT": ("#EF4444", "#F87171", "#DC2626"),
    "IT": ("#10B981", "#34D399", "#EF4444"),
    "ES": ("#FACC15", "#EF4444", "#F59E0B"),
    "RU": ("#3B82F6", "#EF4444", "#60A5FA"),
    "UA": ("#0EA5E9", "#FFD000", "#38BDF8"),
    "RO": ("#3B82F6", "#FACC15", "#EF4444"),
    "KR": ("#3B82F6", "#EF4444", "#60A5FA"),
    "IN": ("#FB923C", "#10B981", "#F59E0B"),
    "GLOBAL": ("#FFD000", "#38BDF8", "#10B981"),
}


def get_flag_neon_triad(code: str) -> tuple[QColor, QColor, QColor]:
    norm = str(code or "GLOBAL").strip().upper()
    if norm == "UK":
        norm = "GB"
    if norm in _VIBRANT_FLAG_TRIADS:
        h1, h2, h3 = _VIBRANT_FLAG_TRIADS[norm]
        return QColor(h1), QColor(h2), QColor(h3)
    spec = GeoFlagResolver.get_spec(norm)
    return QColor(spec.c1), QColor(spec.c2), QColor(spec.c3)


class NeuCard(QFrame):
    def __init__(
        self,
        mode: str = "raised",
        radius: float = 18.0,
        depth: float = 5.2,
        pad: float = 6.5,
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._radius = float(radius)
        self._depth = float(depth)
        self._pad = float(pad)
        self._palette: ThemePalette = DARK_PALETTE
        self.setAutoFillBackground(False)

    def set_neu_mode(self, mode: str) -> None:
        if mode != self._mode:
            self._mode = mode
            self.update()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, _event) -> None:
        w, h = float(self.width()), float(self.height())
        if w < 12.0 or h < 12.0:
            return
        painter = QPainter(self)
        p = self._pad
        inner = QRectF(p, p, w - 2.0 * p, h - 2.0 * p)
        if self._mode == "inset":
            draw_neu_inset(painter, inner, self._radius, self._palette, depth=self._depth)
        elif self._mode == "dock":
            draw_neu_raised(
                painter,
                inner,
                self._radius,
                self._palette,
                depth=self._depth,
                accent_tint=QColor(self._palette.accent_primary),
            )
        else:
            draw_neu_raised(painter, inner, self._radius, self._palette, depth=self._depth)


class VectorIconButton(QAbstractButton):
    def __init__(self, icon_name: str, size: int = 34, danger_hover: bool = False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._danger_hover = danger_hover
        self._hovered = False
        self._palette: ThemePalette = DARK_PALETTE
        self._dim = size
        lock_widget_dimensions(self, size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._dim, self._dim)

    def set_icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.update()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3.5, 3.5, self.width() - 7.0, self.height() - 7.0)
        radius = rect.height() * 0.36

        tint = QColor("#EF4444") if (self._hovered and self._danger_hover) else (
            QColor(self._palette.accent_primary) if self._hovered else None
        )
        if self.isDown():
            draw_neu_inset(painter, rect, radius, self._palette, depth=3.2, glow_tint=tint)
        else:
            draw_neu_raised(painter, rect, radius, self._palette, depth=3.2, hovered=self._hovered, accent_tint=tint)

        col = (
            QColor("#EF4444")
            if (self._hovered and self._danger_hover)
            else (
                QColor(self._palette.accent_primary)
                if (self._hovered and self._palette.is_dark)
                else (QColor("#B45309") if self._hovered else QColor(self._palette.text_secondary))
            )
        )
        shift = 0.8 if self.isDown() else 0.0
        pad = self.width() * 0.27
        icon_rect = QRectF(pad + shift, pad + shift, self.width() - 2.0 * pad, self.height() - 2.0 * pad)
        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, col, stroke=1.75)


class ActionPillButton(QPushButton):
    def __init__(self, icon_name: str, text: str = "", variant: str = "gold", parent=None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._variant = variant
        self._hovered = False
        self._palette: ThemePalette = DARK_PALETTE
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setMaximumHeight(40)
        self._recalc_width()
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def set_label_text(self, text: str) -> None:
        self.setText(text)
        self._recalc_width()
        self.update()
        self.updateGeometry()

    def _recalc_width(self) -> None:
        self.setFont(make_ui_font(9, QFont.Weight.Bold))
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(fm.horizontalAdvance(self.text()) + 54)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._recalc_width()
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3.5, 3.5, self.width() - 7.0, self.height() - 7.0)
        radius = 12.0
        pressed = self.isDown()

        if not self.isEnabled():
            draw_neu_inset(painter, rect, radius, self._palette, depth=2.5)
            fg = QColor(self._palette.text_muted)
        elif self._variant == "gold":
            draw_neu_raised(painter, rect, radius, self._palette, depth=2.0 if pressed else 3.8)
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            if pressed:
                grad.setColorAt(0.0, QColor("#EAB308"))
                grad.setColorAt(1.0, QColor("#CA8A04"))
            else:
                grad.setColorAt(0.0, QColor("#FFE866") if self._hovered else QColor("#FFD60A"))
                grad.setColorAt(1.0, QColor("#F59E0B"))
            painter.setPen(QPen(QColor(255, 255, 255, 110 if not pressed else 45), 1.1))
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, radius, radius)
            fg = QColor("#10151F")
        elif self._variant == "emerald":
            em = QColor(self._palette.emerald)
            if pressed:
                draw_neu_inset(painter, rect, radius, self._palette, depth=3.2, glow_tint=em)
            else:
                draw_neu_raised(painter, rect, radius, self._palette, depth=3.6, hovered=self._hovered, accent_tint=em)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(em.red(), em.green(), em.blue(), 125 if self._hovered else 72), 1.1))
                painter.drawRoundedRect(rect, radius, radius)
            fg = em
        else:
            acc = QColor(self._palette.accent_primary) if self._hovered else None
            if pressed:
                draw_neu_inset(painter, rect, radius, self._palette, depth=3.2)
            else:
                draw_neu_raised(painter, rect, radius, self._palette, depth=3.6, hovered=self._hovered, accent_tint=acc)
            fg = QColor(self._palette.text_primary) if self._hovered else QColor(self._palette.text_secondary)

        shift = 0.8 if (pressed and self.isEnabled()) else 0.0
        rtl = I18N.is_rtl()
        if rtl:
            icon_rect = QRectF(rect.right() - 25.0 + shift, rect.center().y() - 8.0 + shift, 16.0, 16.0)
            txt_rect = QRectF(rect.left() + 8.0 + shift, rect.top() + shift, rect.width() - 36.0, rect.height())
        else:
            icon_rect = QRectF(rect.left() + 10.0 + shift, rect.center().y() - 8.0 + shift, 16.0, 16.0)
            txt_rect = QRectF(rect.left() + 28.0 + shift, rect.top() + shift, rect.width() - 36.0, rect.height())

        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, fg, stroke=1.7)
        painter.setPen(fg)
        painter.setFont(self.font())
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, self.text())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(max(base.width(), _compute_safe_pill_min_width(self)), max(base.height(), 36))


class NavRailButton(QAbstractButton):
    def __init__(self, icon_name: str, i18n_key: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._i18n_key = i18n_key
        self._badge_count = 0
        self._palette: ThemePalette = DARK_PALETTE
        self._hovered = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lock_widget_dimensions(self, 82, 66)

    def sizeHint(self) -> QSize:
        return QSize(82, 66)

    def set_badge_count(self, count: int) -> None:
        val = max(0, int(count))
        if val != self._badge_count:
            self._badge_count = val
            self.update()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(6.0, 4.5, self.width() - 12.0, self.height() - 9.0)

        active = self.isChecked()
        accent = QColor(self._palette.accent_primary)

        if active:
            draw_neu_inset(painter, rect, 15.0, self._palette, depth=4.2, glow_tint=accent)
            pill_x = (rect.right() - 4.2) if I18N.is_rtl() else (rect.left() + 1.4)
            pill = QRectF(pill_x, rect.top() + 13.0, 3.0, rect.height() - 26.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(pill, 1.5, 1.5)
        elif self._hovered:
            draw_neu_raised(painter, rect, 15.0, self._palette, depth=3.4, hovered=True)

        icon_col = (
            accent
            if (active and self._palette.is_dark)
            else (QColor("#A16207") if active else QColor(self._palette.text_muted))
        )
        if self._hovered and (not active):
            icon_col = QColor(self._palette.text_primary)

        icon_rect = QRectF((self.width() - 22.0) / 2.0, 10.0, 22.0, 22.0)
        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, icon_col, stroke=1.85)

        if self._badge_count > 0:
            b_txt = str(self._badge_count) if self._badge_count < 100 else "99+"
            painter.setFont(make_mono_font(7, bold=True))
            bw = max(16.0, QFontMetrics(painter.font()).horizontalAdvance(b_txt) + 8.0)
            b_rect = QRectF(self.width() / 2.0 + 3.0, 6.5, bw, 14.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(b_rect, 7.0, 7.0)
            painter.setPen(QColor("#10151F"))
            painter.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, b_txt)

        painter.setPen(icon_col)
        painter.setFont(make_ui_font(8, QFont.Weight.ExtraBold if active else QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(4.0, 35.0, self.width() - 8.0, 23.0),
            Qt.AlignmentFlag.AlignCenter,
            I18N.t(self._i18n_key),
        )


class AnimatedToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lock_widget_dimensions(self, 50, 28)
        self._palette: ThemePalette = DARK_PALETTE
        self._offset = 1.0 if checked else 0.0

        self._anim = QPropertyAnimation(self, b"knobOffset", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_state)

    def get_knob_offset(self) -> float:
        return self._offset

    def set_knob_offset(self, val: float) -> None:
        self._offset = float(val)
        self.update()

    knobOffset = Property(float, get_knob_offset, set_knob_offset)

    def set_checked_silent(self, checked: bool) -> None:
        state = bool(checked)
        self.blockSignals(True)
        self._anim.stop()
        self.setChecked(state)
        self._offset = 1.0 if state else 0.0
        self.blockSignals(False)
        self.update()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def _animate_state(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(50, 28)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(2.5, 3.0, self.width() - 5.0, self.height() - 6.0)
        radius = track.height() / 2.0
        accent = QColor(self._palette.accent_primary)

        tint = QColor(accent.red(), accent.green(), accent.blue(), int(255 * self._offset)) if self._offset > 0.05 else None
        draw_neu_inset(painter, track, radius, self._palette, depth=3.5, glow_tint=tint)

        if self._offset > 0.05:
            glow_fill = QColor(accent)
            glow_fill.setAlpha(int((75 if self._palette.is_dark else 92) * self._offset))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow_fill)
            painter.drawRoundedRect(track.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1.5, radius - 1.5)

        knob_d = track.height() - 4.0
        min_x = track.left() + 2.0
        max_x = track.right() - knob_d - 2.0
        knob_x = min_x + (max_x - min_x) * self._offset
        knob_rect = QRectF(knob_x, track.top() + 2.0, knob_d, knob_d)

        shadow_c = parse_css_color(self._palette.neu_shadow_dark)
        shadow_c.setAlpha(135)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow_c)
        painter.drawEllipse(knob_rect.translated(1.4, 1.6))

        knob_grad = QLinearGradient(knob_rect.topLeft(), knob_rect.bottomRight())
        if self._offset > 0.5:
            knob_grad.setColorAt(0.0, QColor("#FFE866"))
            knob_grad.setColorAt(1.0, QColor("#F59E0B"))
            dot_col = QColor("#10151F")
        else:
            knob_grad.setColorAt(0.0, parse_css_color(self._palette.surface_hi).lighter(112))
            knob_grad.setColorAt(1.0, parse_css_color(self._palette.surface_lo))
            dot_col = QColor(self._palette.text_muted)

        painter.setBrush(knob_grad)
        painter.setPen(QPen(QColor(255, 255, 255, 110 if not self._palette.is_dark else 55), 1.0))
        painter.drawEllipse(knob_rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        painter.drawEllipse(knob_rect.center(), 2.3, 2.3)


class _NeuSegmentTabBtn(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._hovered = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3.0, 2.5, self.width() - 6.0, self.height() - 5.0)
        active = self.isChecked()
        accent = QColor(self._palette.accent_primary)

        if active:
            draw_neu_raised(painter, rect, 10.0, self._palette, depth=3.2, accent_tint=accent)
            bar_w = min(28.0, rect.width() * 0.35)
            bar_rect = QRectF(rect.center().x() - bar_w / 2.0, rect.bottom() - 3.2, bar_w, 2.2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(bar_rect, 1.1, 1.1)
            fg = accent if self._palette.is_dark else QColor("#9A6700")
            painter.setFont(make_ui_font(10, QFont.Weight.ExtraBold))
        else:
            if self._hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 18))
                painter.drawRoundedRect(rect, 10.0, 10.0)
            fg = QColor(self._palette.text_primary) if self._hovered else QColor(self._palette.text_muted)
            painter.setFont(make_ui_font(10, QFont.Weight.DemiBold))

        painter.setPen(fg)
        painter.drawText(rect.adjusted(4.0, 0.0, -4.0, -1.0), Qt.AlignmentFlag.AlignCenter, self.text())


class SegmentedControl(QFrame):
    current_changed = Signal(int)

    def __init__(self, labels: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._buttons: list[_NeuSegmentTabBtn] = []
        self._current_index = 0

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 5, 6, 5)
        self._layout.setSpacing(4)

        if labels:
            self.set_items(labels)

    def set_items(self, labels: list[str], keep_index: bool = True) -> None:
        prev = self._current_index if keep_index else 0
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        for idx, text in enumerate(labels):
            btn = _NeuSegmentTabBtn(text, self)
            btn.set_palette_theme(self._palette)
            btn.clicked.connect(lambda _chk=False, i=idx: self.set_current_index(i, emit_signal=True))
            self._buttons.append(btn)
            self._layout.addWidget(btn, 1)

        if self._buttons:
            self._current_index = max(0, min(prev, len(self._buttons) - 1))
            self._buttons[self._current_index].setChecked(True)
        else:
            self._current_index = 0
        self.update()

    def update_labels(self, labels: list[str]) -> None:
        if len(labels) != len(self._buttons):
            self.set_items(labels, keep_index=True)
            return
        for btn, txt in zip(self._buttons, labels):
            btn.setText(txt)
            btn.update()

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int, emit_signal: bool = False) -> None:
        if not (0 <= index < len(self._buttons)):
            return
        self._current_index = index
        for i, btn in enumerate(self._buttons):
            btn.blockSignals(True)
            btn.setChecked(i == index)
            btn.blockSignals(False)
            btn.update()
        if emit_signal:
            self.current_changed.emit(index)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        for btn in self._buttons:
            btn.set_palette_theme(palette)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        trough = QRectF(2.0, 2.0, self.width() - 4.0, self.height() - 4.0)
        draw_neu_inset(painter, trough, 13.0, self._palette, depth=4.0)


class GlobalTaskStrip(QFrame):
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._active = False
        self._angle = 0.0
        self._target_h = 44
        self.setMaximumHeight(0)
        self.hide()

        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(16)
        self._spin_timer.timeout.connect(self._tick_spin)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(380)
        self._hide_timer.timeout.connect(self._collapse)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 6, 20, 6)
        row.setSpacing(12)

        self.spin_canvas = QWidget()
        lock_widget_dimensions(self.spin_canvas, 18, 18)
        self.spin_canvas.paintEvent = self._paint_spinner

        self.msg_lbl = QLabel("")
        self.msg_lbl.setObjectName("SecondaryLabel")

        self.bar = QProgressBar()
        self.bar.setObjectName("GoldProgress")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(210)
        self.bar.setFixedHeight(9)
        enforce_english_ltr(self.bar, mono_size=9)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setObjectName("BadgePill")
        enforce_english_ltr(self.pct_lbl, mono_size=10, bold=True)

        self.stop_btn = QPushButton(I18N.t("stop"))
        self.stop_btn.setObjectName("DangerBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        row.addWidget(self.spin_canvas)
        row.addWidget(self.msg_lbl, 1)
        row.addWidget(self.bar)
        row.addWidget(self.pct_lbl)
        row.addWidget(self.stop_btn)

    def paintEvent(self, _event) -> None:
        if self.height() < 8:
            return
        painter = QPainter(self)
        well = QRectF(12.0, 2.0, self.width() - 24.0, self.height() - 4.0)
        draw_neu_inset(painter, well, 11.0, self._palette, depth=3.2)

    def retranslate_ui(self) -> None:
        self.stop_btn.setText(I18N.t("stop"))

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.spin_canvas.update()
        self.update()

    def _tick_spin(self) -> None:
        self._angle = (self._angle + 12.0) % 360.0
        self.spin_canvas.update()

    def _paint_spinner(self, _event) -> None:
        painter = QPainter(self.spin_canvas)
        VectorIconPainter.draw_icon(
            painter,
            "spinner",
            QRectF(1.0, 1.0, 16.0, 16.0),
            QColor(self._palette.accent_primary),
            stroke=1.8,
            angle=self._angle,
        )

    def update_task_state(self, active: bool, percent: int, message: str) -> None:
        pct = max(0, min(100, int(percent or 0)))
        self.bar.setValue(pct)
        self.pct_lbl.setText(f"{pct}%")
        if message:
            self.msg_lbl.setText(strip_emojis(message))

        if active:
            self._hide_timer.stop()
            self._active = True
            if not self._spin_timer.isActive():
                self._spin_timer.start()
            if (not self.isVisible()) or (self.maximumHeight() < self._target_h):
                self.show()
                self._anim.stop()
                self._anim.setStartValue(self.maximumHeight())
                self._anim.setEndValue(self._target_h)
                self._anim.start()
        else:
            self._active = False
            self._spin_timer.stop()
            if self.isVisible():
                self._hide_timer.start()

    def _collapse(self) -> None:
        if self._active:
            return
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(0)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if (not self._active) and (self.maximumHeight() == 0):
            self.hide()


class NeuHeroStageBackdrop(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._country_code = ""

        c1, c2, c3 = get_flag_neon_triad("GLOBAL")
        self._cur_c1 = QColor(c1)
        self._cur_c2 = QColor(c2)
        self._cur_c3 = QColor(c3)
        self._tgt_c1 = QColor(c1)
        self._tgt_c2 = QColor(c2)
        self._tgt_c3 = QColor(c3)
        self._wave_t = 0.0
        self._orbs: list[dict] = []

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_stage_context(self, country_code: str, phase: str) -> None:
        norm_c = str(country_code or "").strip().upper()
        if norm_c == "UK":
            norm_c = "GB"
        self._country_code = norm_c
        self._tgt_c1, self._tgt_c2, self._tgt_c3 = get_flag_neon_triad(norm_c or "GLOBAL")
        self._phase = str(phase or "IDLE").upper()

    def _spawn_orb(self, w: float, h: float, from_bottom: bool = False) -> dict:
        base_r = random.uniform(9.5, 16.5)
        pad_x = 34.0
        x = random.uniform(pad_x, max(pad_x + 20.0, w - pad_x))
        y = (h - 24.0) if from_bottom else random.uniform(34.0, max(54.0, h - 42.0))
        return {
            "x": x,
            "y": y,
            "vx": random.uniform(-0.72, 0.72),
            "vy": random.uniform(-1.15, -0.55) if from_bottom else random.uniform(-0.55, 0.55),
            "base_r": base_r,
            "r": 2.8 if from_bottom else base_r,
            "max_r": base_r * random.uniform(1.75, 2.15),
            "state": "REFORM" if from_bottom else "WANDER",
            "timer": random.randint(95, 230),
            "color_idx": random.randint(0, 2),
            "ring_r": 0.0,
            "ring_alpha": 0.0,
            "droplets": [],
            "wobble": random.uniform(0.0, math.pi * 2.0),
        }

    def _ensure_orbs(self, w: float, h: float) -> None:
        if len(self._orbs) < 7 and w > 180.0 and h > 140.0:
            while len(self._orbs) < 7:
                self._orbs.append(self._spawn_orb(w, h, from_bottom=False))

    def _step_orbs(self) -> None:
        w, h = float(self.width()), float(self.height())
        if w < 140.0 or h < 120.0:
            return
        self._ensure_orbs(w, h)

        left_b, right_b = 26.0, w - 26.0
        top_b, bot_b = 24.0, h - 22.0
        speed_mult = 1.32 if self._phase == "CONNECTING" else (1.12 if self._phase == "CONNECTED" else 0.85)

        for idx, orb in enumerate(self._orbs):
            orb["wobble"] = (orb["wobble"] + 0.07) % (2.0 * math.pi)
            st = orb["state"]

            if st == "REFORM":
                orb["r"] += (orb["base_r"] - orb["r"]) * 0.09
                orb["y"] += orb["vy"] * speed_mult
                orb["x"] += math.sin(orb["wobble"]) * 0.45
                if orb["r"] >= orb["base_r"] * 0.94:
                    orb["r"] = orb["base_r"]
                    orb["state"] = "WANDER"
                    orb["vy"] = random.uniform(-0.62, 0.62)
                    orb["timer"] = random.randint(90, 220)

            elif st == "WANDER":
                orb["vx"] += random.uniform(-0.04, 0.04)
                orb["vy"] += random.uniform(-0.04, 0.04)
                orb["vx"] = max(-0.95, min(0.95, orb["vx"]))
                orb["vy"] = max(-0.85, min(0.85, orb["vy"]))
                orb["x"] += orb["vx"] * speed_mult
                orb["y"] += orb["vy"] * speed_mult

                r_cur = orb["r"]
                if orb["x"] - r_cur < left_b:
                    orb["x"] = left_b + r_cur
                    orb["vx"] = abs(orb["vx"])
                elif orb["x"] + r_cur > right_b:
                    orb["x"] = right_b - r_cur
                    orb["vx"] = -abs(orb["vx"])
                if orb["y"] - r_cur < top_b:
                    orb["y"] = top_b + r_cur
                    orb["vy"] = abs(orb["vy"])
                elif orb["y"] + r_cur > bot_b:
                    orb["y"] = bot_b - r_cur
                    orb["vy"] = -abs(orb["vy"])

                orb["timer"] -= 1
                if orb["timer"] <= 0:
                    orb["state"] = "SWELL"

            elif st == "SWELL":
                orb["vx"] *= 0.94
                orb["vy"] *= 0.94
                orb["x"] += orb["vx"] + math.sin(orb["wobble"] * 2.2) * 0.25
                orb["y"] += orb["vy"] - 0.10
                orb["r"] += 0.22 * speed_mult
                if orb["r"] >= orb["max_r"]:
                    orb["state"] = "BURST_FALL"
                    orb["ring_r"] = orb["r"] * 0.85
                    orb["ring_alpha"] = 215.0
                    drops = []
                    n_drops = random.randint(6, 9)
                    for d_i in range(n_drops):
                        ang = (2.0 * math.pi * d_i / n_drops) + random.uniform(-0.28, 0.28)
                        spd = random.uniform(1.6, 3.6)
                        drops.append(
                            {
                                "x": orb["x"] + math.cos(ang) * (orb["r"] * 0.42),
                                "y": orb["y"] + math.sin(ang) * (orb["r"] * 0.42),
                                "vx": math.cos(ang) * spd,
                                "vy": math.sin(ang) * spd - random.uniform(0.9, 2.0),
                                "r": random.uniform(3.0, 5.8),
                                "alpha": 235.0,
                                "bounced": False,
                            }
                        )
                    orb["droplets"] = drops

            elif st == "BURST_FALL":
                if orb["ring_alpha"] > 0.0:
                    orb["ring_r"] += 1.65
                    orb["ring_alpha"] = max(0.0, orb["ring_alpha"] - 10.5)

                alive_drops = 0
                avg_x = 0.0
                for dr in orb["droplets"]:
                    dr["vy"] += 0.22
                    dr["vx"] *= 0.985
                    dr["x"] += dr["vx"]
                    dr["y"] += dr["vy"]
                    if dr["x"] < left_b:
                        dr["x"] = left_b
                        dr["vx"] = abs(dr["vx"]) * 0.6
                    elif dr["x"] > right_b:
                        dr["x"] = right_b
                        dr["vx"] = -abs(dr["vx"]) * 0.6

                    if dr["y"] >= bot_b - dr["r"]:
                        dr["y"] = bot_b - dr["r"]
                        if not dr["bounced"]:
                            dr["vy"] = -abs(dr["vy"]) * 0.36
                            dr["bounced"] = True
                        else:
                            dr["vy"] = 0.0
                            dr["vx"] *= 0.82
                            dr["alpha"] = max(0.0, dr["alpha"] - 11.0)
                    else:
                        dr["alpha"] = max(0.0, dr["alpha"] - 1.2)

                    if dr["alpha"] > 4.0:
                        alive_drops += 1
                        avg_x += dr["x"]

                if alive_drops == 0 and orb["ring_alpha"] <= 1.0:
                    re_x = max(left_b + 16.0, min(right_b - 16.0, orb["x"] + random.uniform(-45.0, 45.0)))
                    new_orb = self._spawn_orb(w, h, from_bottom=True)
                    new_orb["x"] = re_x
                    new_orb["y"] = bot_b - 6.0
                    self._orbs[idx] = new_orb

    def _draw_neu_sphere(self, painter: QPainter, cx: float, cy: float, r: float, tint: QColor, alpha_scale: float = 1.0, swell_ratio: float = 0.0) -> None:
        if r < 1.5 or alpha_scale <= 0.02:
            return
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, alpha_scale)))

        sh_d = parse_css_color(self._palette.neu_shadow_dark)
        sh_d.setAlpha(int((118 if self._palette.is_dark else 88) * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sh_d)
        painter.drawEllipse(QPointF(cx + r * 0.24, cy + r * 0.26), r * 1.02, r * 1.02)

        sh_l = parse_css_color(self._palette.neu_shadow_light)
        sh_l.setAlpha(int((55 if self._palette.is_dark else 135) * alpha_scale))
        painter.setBrush(sh_l)
        painter.drawEllipse(QPointF(cx - r * 0.20, cy - r * 0.20), r * 0.96, r * 0.96)

        hi = _lerp_color(parse_css_color(self._palette.surface_hi), tint, 0.22 + 0.26 * swell_ratio)
        mid = _lerp_color(parse_css_color(self._palette.card_bg), tint, 0.14 + 0.20 * swell_ratio)
        lo = _lerp_color(parse_css_color(self._palette.surface_lo), tint, 0.08)

        grad = QRadialGradient(QPointF(cx - r * 0.32, cy - r * 0.32), r * 1.45)
        grad.setColorAt(0.0, hi.lighter(118 if self._palette.is_dark else 106))
        grad.setColorAt(0.55, mid)
        grad.setColorAt(1.0, lo)

        rim = QColor(tint)
        rim.setAlpha(int((78 + 115 * swell_ratio) * alpha_scale))
        painter.setBrush(grad)
        painter.setPen(QPen(rim, 1.0 + 0.7 * swell_ratio))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        spec_c = QColor(255, 255, 255, int((115 if self._palette.is_dark else 175) * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(spec_c)
        painter.drawEllipse(QPointF(cx - r * 0.32, cy - r * 0.32), max(1.1, r * 0.22), max(1.1, r * 0.17))
        painter.restore()

    def advance_frame(self) -> None:
        mult = 2.0 if self._phase == "CONNECTING" else (1.35 if self._phase == "CONNECTED" else 0.65)
        self._wave_t = (self._wave_t + 0.032 * mult) % (2.0 * math.pi * 20.0)
        self._cur_c1 = _lerp_color(self._cur_c1, self._tgt_c1, 0.10)
        self._cur_c2 = _lerp_color(self._cur_c2, self._tgt_c2, 0.10)
        self._cur_c3 = _lerp_color(self._cur_c3, self._tgt_c3, 0.10)
        self._step_orbs()
        self.update()

    def paintEvent(self, _event) -> None:
        w, h = float(self.width()), float(self.height())
        if w < 100.0 or h < 100.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = 9.0
        card = QRectF(pad, pad, w - 2.0 * pad, h - 2.0 * pad)
        radius = 24.0

        ambient_tint = (
            QColor("#10B981")
            if self._phase == "CONNECTED"
            else (QColor("#F97316") if self._phase == "CONNECTING" else self._cur_c1)
        )
        draw_neu_raised(painter, card, radius, self._palette, depth=7.0, accent_tint=ambient_tint)

        clip = QPainterPath()
        clip.addRoundedRect(card, radius, radius)
        painter.save()
        painter.setClipPath(clip)

        dot_col = QColor(255, 255, 255, 11) if self._palette.is_dark else QColor(15, 23, 42, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        for gx in range(int(card.left()) + 20, int(card.right()) - 14, 28):
            for gy in range(int(card.top()) + 20, int(card.bottom()) - 14, 28):
                painter.drawEllipse(QPointF(float(gx), float(gy)), 1.05, 1.05)

        rtl = I18N.is_rtl()
        dest_x = card.left() + card.width() * 0.24 if rtl else card.right() - card.width() * 0.24
        aura = QRadialGradient(QPointF(dest_x, card.top() + card.height() * 0.42), card.width() * 0.48)
        aura_c = QColor(self._cur_c1 if self._phase == "CONNECTED" else ambient_tint)
        aura_c.setAlpha(44 if self._palette.is_dark else 30)
        aura.setColorAt(0.0, aura_c)
        aura.setColorAt(0.6, QColor(self._cur_c3.red(), self._cur_c3.green(), self._cur_c3.blue(), 18))
        aura.setColorAt(1.0, QColor(aura_c.red(), aura_c.green(), aura_c.blue(), 0))
        painter.setBrush(aura)
        painter.drawRect(card)

        # Prominent & Larger Neumorphic Flag Showcase Box behind HeroCard
        if self._country_code:
            painter.save()
            wm_w = min(350.0, max(250.0, card.width() * 0.36))
            wm_h = wm_w * 0.62
            wm_cx = (card.left() + wm_w * 0.56 + 18.0) if rtl else (card.right() - wm_w * 0.56 - 18.0)
            wm_cy = card.top() + card.height() * 0.42 + math.sin(self._wave_t * 0.55) * 4.5
            painter.translate(wm_cx, wm_cy)
            painter.rotate(-5.0 if rtl else 5.0)

            frame_rect = QRectF(-wm_w / 2.0 - 10.0, -wm_h / 2.0 - 10.0, wm_w + 20.0, wm_h + 20.0)
            flag_rect = QRectF(-wm_w / 2.0, -wm_h / 2.0, wm_w, wm_h)

            is_conn = self._phase == "CONNECTED"
            box_opacity = 0.85 if is_conn else 0.45
            painter.setOpacity(box_opacity)
            draw_neu_inset(
                painter,
                frame_rect,
                22.0,
                self._palette,
                depth=5.0,
                glow_tint=self._cur_c1 if is_conn else None,
            )

            flag_op = (0.36 if self._palette.is_dark else 0.28) if is_conn else (0.14 if self._palette.is_dark else 0.11)
            VectorFlagRenderer.draw_flag(
                painter,
                self._country_code,
                flag_rect,
                radius=15.0,
                opacity=flag_op,
                with_border=True,
            )

            rim_col = QColor(self._cur_c1)
            rim_col.setAlpha(110 if is_conn else 45)
            painter.setOpacity(1.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(rim_col, 1.4))
            painter.drawRoundedRect(frame_rect, 22.0, 22.0)
            painter.restore()
            painter.setClipPath(clip)

        # Neumorphic Floating, Swelling, Bursting & Cascading Orbs
        triad = (self._cur_c1, self._cur_c2, self._cur_c3)
        for orb in self._orbs:
            o_col = triad[orb["color_idx"] % 3]
            st = orb["state"]
            if st in ("WANDER", "REFORM", "SWELL"):
                swell_r = 0.0
                if st == "SWELL":
                    span = max(1.0, orb["max_r"] - orb["base_r"])
                    swell_r = max(0.0, min(1.0, (orb["r"] - orb["base_r"]) / span))
                alpha_sc = min(1.0, orb["r"] / max(1.0, orb["base_r"])) if st == "REFORM" else 0.88
                self._draw_neu_sphere(painter, orb["x"], orb["y"], orb["r"], o_col, alpha_scale=alpha_sc, swell_ratio=swell_r)
            elif st == "BURST_FALL":
                if orb["ring_alpha"] > 2.0:
                    rc = QColor(o_col)
                    rc.setAlpha(int(orb["ring_alpha"]))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(rc, 2.0))
                    painter.drawEllipse(QPointF(orb["x"], orb["y"]), orb["ring_r"], orb["ring_r"])
                for dr in orb["droplets"]:
                    if dr["alpha"] > 4.0:
                        self._draw_neu_sphere(
                            painter,
                            dr["x"],
                            dr["y"],
                            dr["r"],
                            o_col,
                            alpha_scale=(dr["alpha"] / 255.0),
                            swell_ratio=0.5,
                        )

        for idx, w_col in enumerate(triad):
            ribbon = QPainterPath()
            base_y = card.bottom() - (26.0 + idx * 17.0)
            ribbon.moveTo(card.left(), card.bottom())
            ribbon.lineTo(card.left(), base_y)
            segs = 20
            for s in range(segs + 1):
                sx = card.left() + (s / segs) * card.width()
                sy = base_y + math.sin(s * 0.46 + self._wave_t * (0.8 + idx * 0.22) + idx * 1.3) * (10.0 + idx * 3.5)
                ribbon.lineTo(sx, sy)
            ribbon.lineTo(card.right(), card.bottom())
            ribbon.closeSubpath()

            fc = QColor(w_col)
            fc.setAlpha(20 - idx * 4 if self._palette.is_dark else 16 - idx * 3)
            ec = QColor(w_col)
            ec.setAlpha(62 if self._phase == "CONNECTED" else 36)
            painter.setBrush(fc)
            painter.setPen(QPen(ec, 1.05))
            painter.drawPath(ribbon)

        painter.restore()


class FlagOrbitalHudWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(256, 192)
        self.setMaximumSize(292, 212)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._palette: ThemePalette = DARK_PALETTE
        self._country_code = ""
        self._phase = "IDLE"
        self._proto_text = "VLESS"
        self._vec_text = "AUTO"
        self._ping_ms = 0
        self._wave_phase = 0.0
        self._bars = [0.20] * 18

        c1, c2, c3 = get_flag_neon_triad("GLOBAL")
        self._c1 = QColor(c1)
        self._c2 = QColor(c2)
        self._c3 = QColor(c3)

    def sizeHint(self) -> QSize:
        return QSize(272, 198)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def update_hud_state(
        self,
        country_code: str,
        phase: str,
        proto: str,
        vector_id: str,
        ping_ms: int,
        activity_boost: float = 0.0,
    ) -> None:
        norm = str(country_code or "").strip().upper()
        if norm == "UK":
            norm = "GB"
        self._country_code = norm
        self._phase = str(phase or "IDLE").upper()
        self._proto_text = str(proto or "VLESS").upper()[:10]
        self._vec_text = str(vector_id or "AUTO").upper()[:10]
        self._ping_ms = int(ping_ms or 0)

        t1, t2, t3 = get_flag_neon_triad(norm or "GLOBAL")
        self._c1 = _lerp_color(self._c1, t1, 0.15)
        self._c2 = _lerp_color(self._c2, t2, 0.15)
        self._c3 = _lerp_color(self._c3, t3, 0.15)

        spd = 0.22 if self._phase == "CONNECTING" else (0.15 if self._phase == "CONNECTED" else 0.05)
        self._wave_phase = (self._wave_phase + spd) % (2.0 * math.pi * 10.0)

        amp_base = (
            min(1.0, 0.48 + activity_boost * 0.45)
            if self._phase == "CONNECTED"
            else (0.70 if self._phase == "CONNECTING" else 0.22)
        )
        for i in range(len(self._bars)):
            w1 = 0.5 + 0.5 * math.sin(self._wave_phase * 1.3 + i * 0.48)
            w2 = 0.5 + 0.5 * math.cos(self._wave_phase * 0.85 - i * 0.32)
            target_h = 0.14 + amp_base * (0.58 * w1 + 0.42 * w2)
            self._bars[i] = self._bars[i] * 0.70 + target_h * 0.30
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        card = QRectF(5.5, 5.5, w - 11.0, h - 11.0)
        is_conn = self._phase == "CONNECTED"
        spec = GeoFlagResolver.get_spec(self._country_code if is_conn else "")

        draw_neu_raised(painter, card, 18.0, self._palette, depth=4.6, accent_tint=self._c1 if is_conn else None)

        rtl = I18N.is_rtl()
        fw, fh = 64.0, 42.0
        fy = card.top() + 13.0
        fx = (card.right() - 14.0 - fw) if rtl else (card.left() + 14.0)
        flag_well = QRectF(fx - 3.0, fy - 3.0, fw + 6.0, fh + 6.0)
        draw_neu_inset(painter, flag_well, 9.0, self._palette, depth=2.8)
        VectorFlagRenderer.draw_flag(painter, spec.code, QRectF(fx, fy, fw, fh), radius=6.0, with_border=False)

        if rtl:
            txt_x = card.left() + 14.0
            txt_w = flag_well.left() - txt_x - 10.0
            align_flag = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            txt_x = flag_well.right() + 10.0
            txt_w = card.right() - 14.0 - txt_x
            align_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        painter.setFont(make_ui_font(8, QFont.Weight.Bold))
        painter.setPen(QColor(self._palette.text_muted))
        painter.drawText(QRectF(txt_x, fy - 1.0, txt_w, 15.0), align_flag, I18N.t("hud_node_target"))

        painter.setFont(make_ui_font(12, QFont.Weight.ExtraBold))
        painter.setPen(QColor(self._palette.text_primary))
        painter.drawText(QRectF(txt_x, fy + 14.0, txt_w, 20.0), align_flag, spec.localized_name())

        status_tag = (
            f"ONLINE // {spec.code}"
            if (is_conn and spec.code)
            else ("PROBING..." if self._phase == "CONNECTING" else "STANDBY")
        )
        painter.setFont(make_mono_font(8, bold=True))
        painter.setPen(QColor(self._palette.emerald) if is_conn else self._c1)
        painter.drawText(QRectF(txt_x, fy + 33.0, txt_w, 14.0), align_flag, status_tag)

        spec_lbl_y = fy + fh + 11.0
        painter.setFont(make_mono_font(7, bold=True))
        painter.setPen(QColor(self._palette.text_muted))
        painter.drawText(
            QRectF(card.left() + 14.0, spec_lbl_y, card.width() - 28.0, 12.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            I18N.t("hud_live_spectrum"),
        )

        eq_well = QRectF(card.left() + 12.0, spec_lbl_y + 14.0, card.width() - 24.0, 44.0)
        draw_neu_inset(painter, eq_well, 10.0, self._palette, depth=3.2)

        eq_left = eq_well.left() + 7.0
        eq_top = eq_well.top() + 6.0
        eq_h = eq_well.height() - 12.0
        eq_w = eq_well.width() - 14.0
        n_bars = len(self._bars)
        gap = 3.5
        bar_w = (eq_w - gap * (n_bars - 1)) / n_bars

        painter.setPen(Qt.PenStyle.NoPen)
        for idx, norm_val in enumerate(self._bars):
            bh = max(4.0, eq_h * min(1.0, norm_val))
            bx = eq_left + idx * (bar_w + gap)
            by = eq_top + (eq_h - bh)
            b_col = _lerp_color(self._c1, self._c3, idx / max(1, n_bars - 1))
            b_col.setAlpha(125 if self._phase == "IDLE" else 235)
            painter.setBrush(b_col)
            painter.drawRoundedRect(QRectF(bx, by, bar_w, bh), 2.0, 2.0)

        pills_y = card.bottom() - 32.0
        pills_h = 21.0
        pw = (eq_well.width() - 12.0) / 3.0
        ping_label = f"{self._ping_ms} ms" if (is_conn and self._ping_ms > 0) else (spec.code or "---")
        items = [
            (self._proto_text, self._c1),
            (self._vec_text, QColor(self._palette.accent_primary)),
            (ping_label, QColor(self._palette.emerald) if is_conn else QColor(self._palette.text_muted)),
        ]
        painter.setFont(make_mono_font(8, bold=True))
        for p_idx, (p_txt, p_col) in enumerate(items):
            px = eq_well.left() + p_idx * (pw + 6.0)
            p_rect = QRectF(px, pills_y, pw, pills_h)
            draw_neu_inset(painter, p_rect, 7.0, self._palette, depth=2.2)
            painter.setPen(p_col if self._palette.is_dark else QColor("#1E293B"))
            painter.drawText(p_rect, Qt.AlignmentFlag.AlignCenter, p_txt)


class _HeroResizeFilter(QObject):
    def __init__(self, hero: QWidget, backdrop: NeuHeroStageBackdrop):
        super().__init__(hero)
        self._hero = hero
        self._backdrop = backdrop

    def eventFilter(self, watched, event) -> bool:
        if watched is self._hero and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._backdrop.setGeometry(self._hero.rect())
            self._backdrop.lower()
        return False


class AnimatedRadarCore(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(224, 224)
        self.setMaximumSize(248, 248)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._country_code = ""
        self._effective_code = ""

        c1, c2, c3 = get_flag_neon_triad("GLOBAL")
        self._flag_c1 = QColor(c1)
        self._flag_c2 = QColor(c2)
        self._flag_c3 = QColor(c3)
        self._tgt_c1 = QColor(c1)
        self._tgt_c2 = QColor(c2)
        self._tgt_c3 = QColor(c3)

        self._rx_kbps = 0.0
        self._tx_kbps = 0.0
        self._bubbles: list[dict] = []
        self._bubble_tick = 0

        self._angle = 0.0
        self._pulse = 0.0
        self._glow = 0.34

        self._backdrop: NeuHeroStageBackdrop | None = None
        self._hud_panel: FlagOrbitalHudWidget | None = None
        self._resize_filter: _HeroResizeFilter | None = None

        self._glow_anim = QPropertyAnimation(self, b"glowLevel", self)
        self._glow_anim.setDuration(360)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        I18N.language_changed.connect(self._on_lang_switched)
        QTimer.singleShot(0, self._ensure_hero_stage_attached)

    def sizeHint(self) -> QSize:
        return QSize(232, 232)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_hero_stage_attached()

    def _on_lang_switched(self, _lang: str) -> None:
        hero = self.parentWidget()
        home = hero.parentWidget() if hero is not None else None
        if home is not None and hasattr(home, "headline_lbl"):
            home.headline_lbl.setFont(make_ui_font(22, QFont.Weight.ExtraBold))
            if hasattr(home, "detail_lbl"):
                home.detail_lbl.setFont(make_ui_font(10, QFont.Weight.DemiBold))
        if self._backdrop is not None:
            self._backdrop.update()
        if self._hud_panel is not None:
            self._hud_panel.update()
        self.update()

    def _ensure_hero_stage_attached(self) -> None:
        hero = self.parentWidget()
        if not isinstance(hero, QFrame) or hero.objectName() != "HeroCard":
            return
        if getattr(hero, "_alan_neu_stage_ready", False):
            return
        setattr(hero, "_alan_neu_stage_ready", True)

        self._backdrop = NeuHeroStageBackdrop(hero)
        self._backdrop.set_palette_theme(self._palette)
        self._backdrop.setGeometry(hero.rect())
        self._backdrop.lower()
        self._backdrop.show()

        self._resize_filter = _HeroResizeFilter(hero, self._backdrop)
        hero.installEventFilter(self._resize_filter)

        hero_vbox = hero.layout()
        if hero_vbox is not None and hero_vbox.count() >= 1:
            top_item = hero_vbox.itemAt(0)
            center_row = top_item.layout() if top_item is not None else None
            if center_row is not None:
                self._hud_panel = FlagOrbitalHudWidget(hero)
                self._hud_panel.set_palette_theme(self._palette)
                center_row.addWidget(self._hud_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        home = hero.parentWidget()
        if home is not None:
            if hasattr(home, "headline_lbl"):
                home.headline_lbl.setFont(make_ui_font(22, QFont.Weight.ExtraBold))
            if hasattr(home, "detail_lbl"):
                home.detail_lbl.setFont(make_ui_font(10, QFont.Weight.DemiBold))

        self._sync_stage_companions()

    def _distinct_flag_pair(self) -> tuple[QColor, QColor]:
        c1, c2, c3 = self._flag_c1, self._flag_c2, self._flag_c3
        d12 = abs(c1.red() - c2.red()) + abs(c1.green() - c2.green()) + abs(c1.blue() - c2.blue())
        d13 = abs(c1.red() - c3.red()) + abs(c1.green() - c3.green()) + abs(c1.blue() - c3.blue())
        return (c1, c2) if (d12 >= d13) else (c1, c3)

    def _step_traffic_bubbles(self) -> None:
        is_conn = self._phase == "CONNECTED"
        has_dl = is_conn and (self._rx_kbps > 0.05)
        has_ul = is_conn and (self._tx_kbps > 0.05)

        # State 1: Zero DL & UL -> No bubbles emitted (existing ones fade cleanly)
        # State 2: Single direction active (DL or UL only) -> Single flag color
        # State 3: Both DL & UL active -> Simultaneous two-color flag mix
        self._bubble_tick += 1
        if has_dl or has_ul:
            col_dl, col_ul = self._distinct_flag_pair()
            both_active = has_dl and has_ul
            spawn_every = 2 if both_active else 3

            if (self._bubble_tick % spawn_every) == 0 and len(self._bubbles) < 34:
                burst_n = 2 if both_active else 1
                for b_i in range(burst_n):
                    is_micro = random.random() < 0.56
                    if both_active:
                        col = QColor(col_dl if ((self._bubble_tick + b_i) % 2 == 0) else col_ul)
                    else:
                        col = QColor(col_dl if has_dl else col_ul)

                    ang = random.uniform(0.0, 2.0 * math.pi)
                    self._bubbles.append(
                        {
                            "angle": ang,
                            "dist": random.uniform(0.0, 3.0),
                            "speed": random.uniform(0.45, 0.95) if not is_micro else random.uniform(0.60, 1.18),
                            "drift": random.uniform(-0.025, 0.025),
                            "r": random.uniform(1.4, 2.6) if is_micro else random.uniform(3.2, 5.6),
                            "life": 1.0,
                            "decay": random.uniform(0.022, 0.038),
                            "color": col,
                            "micro": is_micro,
                        }
                    )

        next_bubbles: list[dict] = []
        fade_boost = 2.4 if (not has_dl and not has_ul) else 1.0
        for b in self._bubbles:
            b["dist"] += b["speed"]
            b["angle"] += b["drift"]
            b["life"] -= b["decay"] * fade_boost
            if b["life"] > 0.02 and b["dist"] < 21.0:
                next_bubbles.append(b)
        self._bubbles = next_bubbles

    def _resolve_live_meta(self) -> tuple[str, str, str, int, float]:
        code = self._country_code if self._phase == "CONNECTED" else ""
        proto = "VLESS"
        vec = "AUTO"
        ping = 0
        boost = 0.0
        rx = 0.0
        tx = 0.0

        hero = self.parentWidget()
        home = hero.parentWidget() if hero is not None else None

        if home is not None:
            snap = getattr(home, "_last_snap", None)
            if isinstance(snap, dict) and snap:
                vec = str(snap.get("active_vector_id") or vec)
                ping = int(snap.get("ping_ms") or 0)
                rx = float(snap.get("rx_rate_kbps") or 0.0)
                tx = float(snap.get("tx_rate_kbps") or 0.0)
                if rx > 0.0 or tx > 0.0:
                    boost = min(1.0, math.log10(1.0 + rx + tx) / 3.6)

            cur_fn = getattr(home, "_resolve_current_output_dict", None)
            if callable(cur_fn):
                cur_out = cur_fn()
                if isinstance(cur_out, dict) and cur_out:
                    proto = str(cur_out.get("protocol") or proto).upper()
                    if vec == "AUTO":
                        vec = str(cur_out.get("vector_id") or cur_out.get("cached_vector_id") or vec)

        self._rx_kbps = rx if self._phase == "CONNECTED" else 0.0
        self._tx_kbps = tx if self._phase == "CONNECTED" else 0.0
        return code, proto, vec, ping, boost

    def _sync_stage_companions(self) -> None:
        eff_code, proto, vec, ping, boost = self._resolve_live_meta()
        self._effective_code = eff_code
        self._tgt_c1, self._tgt_c2, self._tgt_c3 = get_flag_neon_triad(eff_code or "GLOBAL")

        if self._backdrop is not None:
            self._backdrop.set_stage_context(eff_code, self._phase)
            self._backdrop.advance_frame()

        if self._hud_panel is not None:
            self._hud_panel.update_hud_state(eff_code, self._phase, proto, vec, ping, boost)

        hero = self.parentWidget()
        home = hero.parentWidget() if hero is not None else None
        if home is not None:
            btn = getattr(home, "connect_btn", None)
            if isinstance(btn, KineticConnectButton):
                btn.set_flag_accent(self._flag_c1)

    def get_glow_level(self) -> float:
        return self._glow

    def set_glow_level(self, val: float) -> None:
        self._glow = float(val)
        self.update()

    glowLevel = Property(float, get_glow_level, set_glow_level)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        if self._backdrop is not None:
            self._backdrop.set_palette_theme(palette)
        if self._hud_panel is not None:
            self._hud_panel.set_palette_theme(palette)
        hero = self.parentWidget()
        home = hero.parentWidget() if hero is not None else None
        if home is not None and hasattr(home, "headline_lbl"):
            home.headline_lbl.setFont(make_ui_font(22, QFont.Weight.ExtraBold))
        self.update()

    def set_country_code(self, code: str) -> None:
        spec = GeoFlagResolver.get_spec(code)
        self._country_code = spec.code
        self._sync_stage_companions()
        self.update()

    def set_ui_phase(self, phase: str) -> None:
        norm = str(phase or "IDLE").upper()
        if norm not in ("IDLE", "CONNECTING", "CONNECTED", "ERROR"):
            norm = "IDLE"
        if norm == self._phase:
            return
        self._phase = norm
        if norm != "CONNECTED":
            self._rx_kbps = 0.0
            self._tx_kbps = 0.0
        target = 0.98 if norm == "CONNECTED" else (0.88 if norm == "CONNECTING" else 0.36)
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow)
        self._glow_anim.setEndValue(target)
        self._glow_anim.start()
        self._sync_stage_companions()

    def _tick(self) -> None:
        if self._phase == "CONNECTING":
            self._angle = (self._angle + 6.2) % 360.0
            self._pulse = (self._pulse + 0.13) % (2.0 * math.pi)
        elif self._phase == "CONNECTED":
            self._angle = (self._angle + 1.45) % 360.0
            self._pulse = (self._pulse + 0.055) % (2.0 * math.pi)
        else:
            self._angle = (self._angle + 0.50) % 360.0
            self._pulse = (self._pulse + 0.032) % (2.0 * math.pi)

        self._flag_c1 = _lerp_color(self._flag_c1, self._tgt_c1, 0.12)
        self._flag_c2 = _lerp_color(self._flag_c2, self._tgt_c2, 0.12)
        self._flag_c3 = _lerp_color(self._flag_c3, self._tgt_c3, 0.12)

        self._sync_stage_companions()
        self._step_traffic_bubbles()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        max_r = min(cx, cy) - 21.0
        breath = 0.5 + 0.5 * math.sin(self._pulse)

        emerald = QColor("#10B981")
        orange = QColor("#F97316")
        crimson = QColor("#EF4444")

        if self._phase == "CONNECTED":
            core_col = emerald
            orbit_col = self._flag_c1
        elif self._phase == "CONNECTING":
            core_col = orange
            orbit_col = self._flag_c1
        elif self._phase == "ERROR":
            core_col = crimson
            orbit_col = self._flag_c1
        else:
            core_col = QColor(self._palette.accent_primary)
            orbit_col = self._flag_c2

        # 3-State Neumorphic Bubbles & Micro-Bubbles radiating around the dial
        for b in self._bubbles:
            life = max(0.0, min(1.0, b["life"]))
            rad_dist = max_r + 1.5 + b["dist"]
            bx = cx + math.cos(b["angle"]) * rad_dist
            by = cy + math.sin(b["angle"]) * rad_dist
            br = b["r"] * (0.75 + 0.25 * math.sin(life * math.pi))
            bc = QColor(b["color"])

            sh_c = parse_css_color(self._palette.neu_shadow_dark)
            sh_c.setAlpha(int(95 * life))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(sh_c)
            painter.drawEllipse(QPointF(bx + 1.0, by + 1.2), br, br)

            fill_c = QColor(bc)
            fill_c.setAlpha(int((145 if b["micro"] else 105) * life))
            rim_c = QColor(bc)
            rim_c.setAlpha(int(235 * life))
            painter.setBrush(fill_c)
            painter.setPen(QPen(rim_c, 0.9 if b["micro"] else 1.25))
            painter.drawEllipse(QPointF(bx, by), br, br)

            if not b["micro"]:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, int(185 * life)))
                painter.drawEllipse(QPointF(bx - br * 0.32, by - br * 0.32), max(0.8, br * 0.24), max(0.8, br * 0.24))

        outer_dial = QRectF(cx - max_r, cy - max_r, max_r * 2.0, max_r * 2.0)
        draw_neu_raised(painter, outer_dial, max_r, self._palette, depth=6.0, accent_tint=core_col)

        well_r = max_r * 0.86
        well_rect = QRectF(cx - well_r, cy - well_r, well_r * 2.0, well_r * 2.0)
        draw_neu_inset(painter, well_rect, well_r, self._palette, depth=5.0, glow_tint=core_col)

        ticks = 42
        t_in = well_r * 0.88
        t_out = well_r * 0.96
        head = int((self._angle / 360.0) * ticks)
        triad = (self._flag_c1, self._flag_c2, self._flag_c3)
        for i in range(ticks):
            rad = math.radians(i * (360.0 / ticks))
            dist = (i - head) % ticks
            lit = dist < 10
            tc = QColor(triad[i % 3] if lit else core_col)
            tc.setAlpha(220 if lit else (65 if self._palette.is_dark else 95))
            painter.setPen(QPen(tc, 2.0 if lit else 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(cx + math.cos(rad) * t_in, cy + math.sin(rad) * t_in),
                QPointF(cx + math.cos(rad) * t_out, cy + math.sin(rad) * t_out),
            )

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-self._angle * 1.35)
        r_mid = well_r * 0.72
        sweep = QConicalGradient(QPointF(0.0, 0.0), 0.0)
        sweep_a = 145 if self._phase == "CONNECTING" else (95 if self._phase == "CONNECTED" else 55)
        sweep.setColorAt(0.0, QColor(core_col.red(), core_col.green(), core_col.blue(), sweep_a))
        sweep.setColorAt(0.32, QColor(core_col.red(), core_col.green(), core_col.blue(), 0))
        sweep.setColorAt(1.0, QColor(core_col.red(), core_col.green(), core_col.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sweep)
        painter.drawEllipse(QPointF(0.0, 0.0), r_mid, r_mid)

        arc_rect = QRectF(-r_mid, -r_mid, r_mid * 2.0, r_mid * 2.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(core_col, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc_rect, 16 * 16, 112 * 16)
        painter.setPen(QPen(orbit_col, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc_rect, 196 * 16, 112 * 16)
        painter.restore()

        r_core = max_r * 0.45
        knob_rect = QRectF(cx - r_core, cy - r_core, r_core * 2.0, r_core * 2.0)
        draw_neu_raised(painter, knob_rect, r_core, self._palette, depth=4.5, accent_tint=core_col)

        ring_col = QColor(core_col)
        ring_col.setAlpha(int(135 + 85 * breath))
        painter.setPen(QPen(ring_col, 2.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r_core - 2.0, r_core - 2.0)

        lock_icon = "lock_closed" if self._phase == "CONNECTED" else "lock_open"
        lock_col = core_col if (not self._palette.is_dark or self._phase != "CONNECTED") else QColor("#F8FAFC")
        VectorIconPainter.draw_icon(
            painter,
            lock_icon,
            QRectF(cx - 17.0, cy - 26.0, 34.0, 34.0),
            lock_col,
            stroke=2.2,
        )

        flag_rect = QRectF(cx - 16.0, cy + 10.0, 32.0, 20.0)
        VectorFlagRenderer.draw_flag(painter, self._effective_code, flag_rect, radius=4.5, with_border=True)


class KineticConnectButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)
        self.setMaximumHeight(62)
        self.setMinimumWidth(265)

        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._custom_label = ""
        self._flag_accent = QColor("#FFD000")
        self._hover = 0.0
        self._shimmer = -0.35
        self._spin_angle = 0.0
        self._pulse = 0.0

        self._hover_anim = QPropertyAnimation(self, b"hoverVal", self)
        self._hover_anim.setDuration(220)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._shimmer_anim = QPropertyAnimation(self, b"shimmerVal", self)
        self._shimmer_anim.setDuration(880)
        self._shimmer_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.set_phase_and_label("IDLE", "")

    def set_flag_accent(self, col: QColor) -> None:
        self._flag_accent = QColor(col)
        self.update()

    def get_hover_val(self) -> float:
        return self._hover

    def set_hover_val(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    hoverVal = Property(float, get_hover_val, set_hover_val)

    def get_shimmer_val(self) -> float:
        return self._shimmer

    def set_shimmer_val(self, v: float) -> None:
        self._shimmer = float(v)
        self.update()

    shimmerVal = Property(float, get_shimmer_val, set_shimmer_val)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.setFont(make_ui_font(11, QFont.Weight.ExtraBold))
        self.update()

    def retranslate_ui(self) -> None:
        self.setFont(make_ui_font(11, QFont.Weight.ExtraBold))
        self._refresh_caption()
        self.update()

    def _tick(self) -> None:
        if self._phase == "CONNECTING":
            self._spin_angle = (self._spin_angle + 11.0) % 360.0
            self._pulse = (self._pulse + 0.15) % (2.0 * math.pi)
            self.update()
        elif self._hover > 0.01:
            self._pulse = (self._pulse + 0.05) % (2.0 * math.pi)
            self.update()

    def set_phase_and_label(self, phase: str, custom_label: str = "") -> None:
        norm = str(phase or "IDLE").upper()
        if norm not in ("IDLE", "CONNECTING", "CONNECTED", "ERROR"):
            norm = "IDLE"
        self._phase = norm
        self._custom_label = strip_emojis(custom_label)
        self.setFont(make_ui_font(11, QFont.Weight.ExtraBold))
        self._refresh_caption()
        self.update()

    def _refresh_caption(self) -> None:
        if self._custom_label and I18N.lang == "fa":
            self.setText(self._custom_label)
            return
        if self._phase == "CONNECTING":
            self.setText(I18N.t("btn_cancel_connect"))
        elif self._phase == "CONNECTED":
            self.setText(I18N.t("btn_disconnect"))
        else:
            self.setText(I18N.t("btn_connect"))

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

        self._shimmer_anim.stop()
        self._shimmer_anim.setStartValue(-0.35)
        self._shimmer_anim.setEndValue(1.35)
        self._shimmer_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        shell_rect = QRectF(5.0, 5.0, self.width() - 10.0, self.height() - 10.0)
        shell_r = shell_rect.height() / 2.0
        draw_neu_raised(painter, shell_rect, shell_r, self._palette, depth=2.6 if self.isDown() else 5.0)

        core_rect = shell_rect.adjusted(4.0, 4.0, -4.0, -4.0)
        core_r = core_rect.height() / 2.0
        breath = 0.5 + 0.5 * math.sin(self._pulse)

        if self._phase == "CONNECTING":
            grad = QLinearGradient(core_rect.topLeft(), core_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FB923C") if self._hover > 0.5 else QColor("#F97316"))
            grad.setColorAt(1.0, QColor("#DC2626") if self._hover > 0.5 else QColor("#EF4444"))
            rim_col = QColor(255, 237, 160, int(145 + 95 * breath))
            fg_col = QColor("#FFFFFF")
            icon_name = "spinner"
        elif self._phase == "CONNECTED":
            grad = QLinearGradient(core_rect.topLeft(), core_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#10B981"))
            grad.setColorAt(0.65, QColor("#059669"))
            grad.setColorAt(1.0, QColor("#047857"))
            rim_col = _lerp_color(QColor("#6EE7B7"), self._flag_accent, 0.35)
            fg_col = QColor("#FFFFFF")
            icon_name = "shield_check"
        else:
            grad = QLinearGradient(core_rect.topLeft(), core_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FFE866") if self._hover > 0.3 else QColor("#FFD60A"))
            grad.setColorAt(0.55, QColor("#FFC300"))
            grad.setColorAt(1.0, QColor("#F59E0B"))
            rim_col = QColor(255, 255, 255, int(135 + 80 * self._hover))
            fg_col = QColor("#10151F")
            icon_name = "power"

        capsule = QPainterPath()
        capsule.addRoundedRect(core_rect, core_r, core_r)
        painter.setBrush(grad)
        painter.setPen(QPen(rim_col, 1.4))
        painter.drawPath(capsule)

        if -0.30 < self._shimmer < 1.30:
            painter.save()
            painter.setClipPath(capsule)
            bx = core_rect.left() + core_rect.width() * self._shimmer
            bw = core_rect.width() * 0.25
            s_grad = QLinearGradient(QPointF(bx - bw, core_rect.top()), QPointF(bx + bw, core_rect.bottom()))
            s_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            s_grad.setColorAt(0.5, QColor(255, 255, 255, 105 if self._phase != "CONNECTED" else 75))
            s_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(s_grad)
            painter.drawRect(core_rect)
            painter.restore()

        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        label = self.text()
        tw = fm.horizontalAdvance(label)
        icon_d = 18.0
        gap = 9.0
        total_w = tw + gap + icon_d
        sx = core_rect.center().x() - total_w / 2.0
        shift = 0.8 if self.isDown() else 0.0

        if I18N.is_rtl():
            icon_rect = QRectF(sx + tw + gap + shift, core_rect.center().y() - icon_d / 2.0 + shift, icon_d, icon_d)
            txt_rect = QRectF(sx + shift, core_rect.top() + shift, tw + 4.0, core_rect.height())
        else:
            icon_rect = QRectF(sx + shift, core_rect.center().y() - icon_d / 2.0 + shift, icon_d, icon_d)
            txt_rect = QRectF(sx + icon_d + gap + shift, core_rect.top() + shift, tw + 4.0, core_rect.height())

        painter.setPen(fg_col)
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, label)
        VectorIconPainter.draw_icon(painter, icon_name, icon_rect, fg_col, stroke=2.0, angle=self._spin_angle)


class TacticalChronometerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(178, 50)
        self.setMaximumHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._palette: ThemePalette = DARK_PALETTE
        self._uptime_label = "00:00:00"
        self._is_connected = False
        self._pulse = 0.0
        self._arc_angle = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def sizeHint(self) -> QSize:
        return QSize(182, 50)

    def _tick(self) -> None:
        if self._is_connected:
            self._pulse = (self._pulse + 0.14) % (2.0 * math.pi)
            self._arc_angle = (self._arc_angle + 5.5) % 360.0
            self.update()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_uptime_state(self, uptime_label: str, is_connected: bool) -> None:
        clean = str(uptime_label or "").strip()
        self._uptime_label = clean if clean else "00:00:00"
        self._is_connected = bool(is_connected)
        self.update()

    def _seconds_ratio(self) -> float:
        parts = self._uptime_label.split(":")
        if len(parts) == 3 and parts[2].isdigit():
            return (int(parts[2]) % 60) / 59.0
        return 0.0

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(3.0, 4.0, self.width() - 6.0, self.height() - 8.0)
        tint = QColor("#10B981") if self._is_connected else None
        draw_neu_inset(painter, rect, 14.0, self._palette, depth=4.0, glow_tint=tint)

        led_center = QPointF(rect.left() + 19.0, rect.center().y())
        if self._is_connected:
            halo_a = int(50 + 80 * (0.5 + 0.5 * math.sin(self._pulse)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 185, 129, halo_a))
            painter.drawEllipse(led_center, 7.5, 7.5)

            painter.save()
            painter.translate(led_center)
            painter.rotate(self._arc_angle)
            painter.setPen(QPen(QColor("#10B981"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(-7.5, -7.5, 15.0, 15.0), 0, 125 * 16)
            painter.restore()
            dot_col = QColor("#10B981")
        else:
            dot_col = QColor(self._palette.text_muted)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        painter.drawEllipse(led_center, 3.2, 3.2)

        clock_rect = QRectF(rect.right() - 27.0, rect.center().y() - 8.5, 17.0, 17.0)
        clock_col = QColor(self._palette.accent_primary) if self._is_connected else QColor(self._palette.text_muted)
        VectorIconPainter.draw_icon(painter, "clock", clock_rect, clock_col, stroke=1.7)

        txt_rect = QRectF(rect.left() + 31.0, rect.top() + 2.0, rect.width() - 62.0, rect.height() - 6.0)
        painter.setFont(make_mono_font(12, bold=True))
        painter.setPen(
            QColor(self._palette.text_primary) if self._is_connected else QColor(self._palette.text_secondary)
        )
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, self._uptime_label)

        if self._is_connected:
            prog = self._seconds_ratio()
            bar_left = rect.left() + 16.0
            bar_max_w = rect.width() - 32.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 185, 129, 45))
            painter.drawRoundedRect(QRectF(bar_left, rect.bottom() - 4.0, bar_max_w, 2.2), 1.1, 1.1)
            painter.setBrush(QColor("#10B981"))
            painter.drawRoundedRect(QRectF(bar_left, rect.bottom() - 4.0, max(6.0, bar_max_w * prog), 2.2), 1.1, 1.1)


SpoilerChronometer = TacticalChronometerWidget


class RouteTopologyStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMaximumHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._palette: ThemePalette = DARK_PALETTE
        self._dest_code = ""
        self._dest_label = "---"
        self._ip_text = "---"
        self._ping_ms = 0
        self._phase = "IDLE"
        self._gemini_ready = False
        self._flow = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_route_state(
        self,
        dest_code: str,
        ip_text: str,
        ping_ms: int,
        phase: str,
        gemini_ready: bool = False,
        dest_label: str = "",
    ) -> None:
        spec = GeoFlagResolver.get_spec(dest_code)
        self._dest_code = spec.code
        raw_ip = str(ip_text or "").strip()
        self._ip_text = raw_ip if (raw_ip and raw_ip not in ("—", "---")) else "---"
        self._ping_ms = int(ping_ms or 0)
        self._phase = str(phase or "IDLE").upper()
        self._gemini_ready = bool(gemini_ready)

        clean_lbl = strip_emojis(str(dest_label or "").strip())
        if clean_lbl and clean_lbl not in ("—", "---"):
            self._dest_label = clean_lbl
        elif spec.code:
            self._dest_label = f"{spec.localized_name()} ({spec.code})"
        else:
            self._dest_label = "---"
        self.update()

    def _tick(self) -> None:
        spd = 0.035 if self._phase == "CONNECTING" else (0.018 if self._phase == "CONNECTED" else 0.006)
        self._flow = (self._flow + spd) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        if w < 220.0:
            return

        is_conn = self._phase == "CONNECTED"
        active_code = self._dest_code if is_conn else ""
        spec = GeoFlagResolver.get_spec(active_code)
        dest_c1, _, dest_c3 = get_flag_neon_triad(spec.code or "GLOBAL")

        card = QRectF(3.0, 3.0, w - 6.0, h - 6.0)
        draw_neu_inset(painter, card, 16.0, self._palette, depth=4.0, glow_tint=dest_c1 if is_conn else None)

        cy = card.center().y()
        fw, fh = 40.0, 26.0
        rtl = I18N.is_rtl()

        dest_title_val = self._dest_label if (is_conn and self._dest_label != "---") else "---"
        dest_sub_ip = self._ip_text if (is_conn and self._ip_text != "---") else "---"

        if rtl:
            orig_flag = QRectF(card.right() - 16.0 - fw, cy - fh / 2.0, fw, fh)
            VectorFlagRenderer.draw_flag(painter, "IR", orig_flag, radius=5.0)
            painter.setFont(make_ui_font(9, QFont.Weight.Bold))
            painter.setPen(QColor(self._palette.text_primary))
            orig_txt = QRectF(orig_flag.left() - 108.0, card.top() + 8.0, 100.0, 20.0)
            painter.drawText(orig_txt, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, I18N.t("route_origin"))
            painter.setFont(make_mono_font(8))
            painter.setPen(QColor(self._palette.text_muted))
            painter.drawText(QRectF(orig_flag.left() - 108.0, cy + 3.0, 100.0, 17.0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "LOCAL NODE")

            dest_flag = QRectF(card.left() + 16.0, cy - fh / 2.0, fw, fh)
            if is_conn and spec.code:
                painter.setPen(QPen(dest_c1, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(dest_flag.adjusted(-2.5, -2.5, 2.5, 2.5), 6.5, 6.5)
            VectorFlagRenderer.draw_flag(painter, spec.code, dest_flag, radius=5.0)
            painter.setFont(make_ui_font(9, QFont.Weight.Bold))
            painter.setPen(QColor(self._palette.text_primary))
            dest_txt = QRectF(dest_flag.right() + 10.0, card.top() + 8.0, 175.0, 20.0)
            painter.drawText(dest_txt, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, I18N.t("route_dest", country=dest_title_val))
            painter.setFont(make_mono_font(8, bold=True))
            painter.setPen(dest_c1 if (is_conn and self._palette.is_dark) else QColor(self._palette.text_secondary))
            painter.drawText(QRectF(dest_flag.right() + 10.0, cy + 3.0, 175.0, 17.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, dest_sub_ip)

            track_start = orig_txt.left() - 12.0
            track_end = dest_txt.right() + 12.0
        else:
            orig_flag = QRectF(card.left() + 16.0, cy - fh / 2.0, fw, fh)
            VectorFlagRenderer.draw_flag(painter, "IR", orig_flag, radius=5.0)
            painter.setFont(make_ui_font(9, QFont.Weight.Bold))
            painter.setPen(QColor(self._palette.text_primary))
            orig_txt = QRectF(orig_flag.right() + 10.0, card.top() + 8.0, 108.0, 20.0)
            painter.drawText(orig_txt, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, I18N.t("route_origin"))
            painter.setFont(make_mono_font(8))
            painter.setPen(QColor(self._palette.text_muted))
            painter.drawText(QRectF(orig_flag.right() + 10.0, cy + 3.0, 108.0, 17.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LOCAL NODE")

            dest_flag = QRectF(card.right() - 16.0 - fw, cy - fh / 2.0, fw, fh)
            if is_conn and spec.code:
                painter.setPen(QPen(dest_c1, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(dest_flag.adjusted(-2.5, -2.5, 2.5, 2.5), 6.5, 6.5)
            VectorFlagRenderer.draw_flag(painter, spec.code, dest_flag, radius=5.0)
            painter.setFont(make_ui_font(9, QFont.Weight.Bold))
            painter.setPen(QColor(self._palette.text_primary))
            dest_txt = QRectF(dest_flag.left() - 185.0, card.top() + 8.0, 175.0, 20.0)
            painter.drawText(dest_txt, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, I18N.t("route_dest", country=dest_title_val))
            painter.setFont(make_mono_font(8, bold=True))
            painter.setPen(dest_c1 if (is_conn and self._palette.is_dark) else QColor(self._palette.text_secondary))
            painter.drawText(QRectF(dest_flag.left() - 185.0, cy + 3.0, 175.0, 17.0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dest_sub_ip)

            track_start = orig_txt.right() + 12.0
            track_end = dest_txt.left() - 12.0

        span = abs(track_end - track_start)
        if span > 65.0:
            line_grad = QLinearGradient(QPointF(track_start, cy), QPointF(track_end, cy))
            line_grad.setColorAt(0.0, QColor(22, 155, 98, 105))
            line_grad.setColorAt(0.5, QColor(255, 208, 0, 85))
            line_grad.setColorAt(1.0, QColor(dest_c1.red(), dest_c1.green(), dest_c1.blue(), 115))
            painter.setPen(QPen(line_grad, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(track_start, cy), QPointF(track_end, cy))

            act_col = (
                QColor("#10B981")
                if is_conn
                else (QColor("#F97316") if self._phase == "CONNECTING" else dest_c1)
            )

            for i in range(4):
                prog = (self._flow + i * 0.25) % 1.0
                px = track_start + (track_end - track_start) * prog
                alpha = int(255 * math.sin(prog * math.pi))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(act_col.red(), act_col.green(), act_col.blue(), alpha))
                r_dot = 3.5 if self._phase in ("CONNECTING", "CONNECTED") else 2.3
                painter.drawEllipse(QPointF(px, cy - 2.0), r_dot, r_dot)

                if is_conn:
                    rev_px = track_end + (track_start - track_end) * prog
                    painter.setBrush(QColor(dest_c3.red(), dest_c3.green(), dest_c3.blue(), int(alpha * 0.75)))
                    painter.drawEllipse(QPointF(rev_px, cy + 2.2), 2.5, 2.5)

            if is_conn and self._ping_ms > 0:
                mid_txt = f"ENCRYPTED | {self._ping_ms} ms"
            elif is_conn:
                mid_txt = "ENCRYPTED"
            elif self._phase == "CONNECTING":
                mid_txt = "PROBING..."
            else:
                mid_txt = "READY"

            if self._gemini_ready and is_conn:
                mid_txt = f"{mid_txt} | GEMINI READY"

            painter.setFont(make_mono_font(8, bold=True))
            fm = QFontMetrics(painter.font())
            extra_icon = 16.0 if (self._gemini_ready and is_conn) else 0.0
            pw = fm.horizontalAdvance(mid_txt) + 22.0 + extra_icon
            mid_x = (track_start + track_end) / 2.0
            pill_rect = QRectF(mid_x - pw / 2.0, cy - 11.5, pw, 23.0)

            pill_accent = QColor("#38BDF8") if (self._gemini_ready and is_conn) else act_col
            draw_neu_raised(painter, pill_rect, 11.5, self._palette, depth=2.6, accent_tint=pill_accent)

            if self._gemini_ready and is_conn:
                star_rect = QRectF(pill_rect.left() + 8.0, cy - 6.0, 12.0, 12.0)
                VectorIconPainter.draw_icon(painter, "gemini", star_rect, QColor("#38BDF8"), stroke=1.5)
                t_rect = QRectF(pill_rect.left() + 19.0, pill_rect.top(), pill_rect.width() - 24.0, pill_rect.height())
            else:
                t_rect = pill_rect

            painter.setPen(pill_accent if self._palette.is_dark else QColor("#0F172A"))
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, mid_txt)


class LiveSparklineWidget(QWidget):
    def __init__(self, max_points: int = 32, stepped: bool = False, parent=None):
        super().__init__(parent)
        self._max_points = max_points
        self._stepped = stepped
        self._samples = deque([0.0] * max_points, maxlen=max_points)
        self._palette: ThemePalette = DARK_PALETTE
        self._custom_color: str | None = None
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_palette_theme(self, palette: ThemePalette, custom_hex: str | None = None) -> None:
        self._palette = palette
        if custom_hex:
            self._custom_color = custom_hex
        self.update()

    def push_sample(self, value: float) -> None:
        self._samples.append(max(0.0, float(value or 0.0)))
        self.update()

    def reset_flat(self) -> None:
        if any(v > 0.0 for v in self._samples):
            self._samples = deque([0.0] * self._max_points, maxlen=self._max_points)
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        if w < 14.0 or h < 14.0 or len(self._samples) < 2:
            return

        well = QRectF(1.0, 1.5, w - 2.0, h - 3.0)
        draw_neu_inset(painter, well, 8.5, self._palette, depth=2.6)

        clip = QPainterPath()
        clip.addRoundedRect(well.adjusted(1.5, 1.5, -1.5, -1.5), 7.0, 7.0)
        painter.save()
        painter.setClipPath(clip)

        pad_x, pad_top, pad_bot = 6.0, 6.0, 5.5
        usable_w = w - 2.0 * pad_x
        usable_h = h - pad_top - pad_bot
        baseline_y = pad_top + usable_h

        line_color = QColor(self._custom_color) if self._custom_color else QColor(self._palette.accent_primary)
        peak = max(self._samples)

        if peak <= 0.0001:
            flat_col = QColor(line_color)
            flat_col.setAlpha(68)
            painter.setPen(QPen(flat_col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(pad_x, baseline_y), QPointF(w - pad_x, baseline_y))
            painter.restore()
            return

        pts: list[QPointF] = []
        n = len(self._samples)
        for idx, val in enumerate(self._samples):
            x = pad_x + (idx / (n - 1)) * usable_w
            norm = min(val / (peak * 1.15), 1.0)
            y = pad_top + usable_h * (1.0 - norm)
            pts.append(QPointF(x, y))

        line_path = QPainterPath(pts[0])
        if self._stepped:
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                line_path.lineTo(QPointF(p1.x(), p0.y()))
                line_path.lineTo(p1)
        else:
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                mid_x = (p0.x() + p1.x()) / 2.0
                line_path.cubicTo(QPointF(mid_x, p0.y()), QPointF(mid_x, p1.y()), p1)

        fill_path = QPainterPath(line_path)
        fill_path.lineTo(pts[-1].x(), baseline_y + 2.0)
        fill_path.lineTo(pts[0].x(), baseline_y + 2.0)
        fill_path.closeSubpath()

        grad = QLinearGradient(0.0, pad_top, 0.0, h)
        top_fill = QColor(line_color)
        top_fill.setAlpha(75 if self._palette.is_dark else 52)
        bot_fill = QColor(line_color)
        bot_fill.setAlpha(0)
        grad.setColorAt(0.0, top_fill)
        grad.setColorAt(1.0, bot_fill)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill_path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line_color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(line_path)

        if self._samples[-1] > 0.0:
            tip = pts[-1]
            painter.setPen(Qt.PenStyle.NoPen)
            halo = QColor(line_color)
            halo.setAlpha(95)
            painter.setBrush(halo)
            painter.drawEllipse(tip, 4.4, 4.4)
            painter.setBrush(line_color)
            painter.drawEllipse(tip, 2.1, 2.1)

        painter.restore()

def _compute_safe_pill_min_width(btn) -> int:
    lbl = getattr(btn, "_label", None) or getattr(btn, "_text_lbl", None) or getattr(btn, "lbl", None)
    if lbl is not None and hasattr(lbl, "text"):
        txt = str(lbl.text() or "")
        fm = lbl.fontMetrics()
    else:
        txt = str(getattr(btn, "_text", "") or btn.text() or "")
        fm = btn.fontMetrics()
    if not txt:
        return 44
    has_icon = bool(getattr(btn, "_icon_name", "") or (hasattr(btn, "icon") and not btn.icon().isNull()))
    pad = 58 if has_icon else 34
    return int(fm.horizontalAdvance(txt) + pad)


class JustifiedFlowLayout(QLayout):
    """
    Responsive RTL/LTR-aware flow layout that justifies button rows cleanly across
    the full available width and wraps gracefully without ever squishing or clipping buttons.
    """

    def __init__(self, parent=None, h_spacing: int = 8, v_spacing: int = 8, justify: bool = True):
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = int(h_spacing)
        self._v_spacing = int(v_spacing)
        self._justify = bool(justify)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, max(1, int(width)), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        m = self.contentsMargins()
        w_sum = 0
        h_max = 0
        vis = 0
        for item in self._items:
            wdg = item.widget()
            if wdg is not None and wdg.isHidden():
                continue
            if wdg is None and item.spacerItem() is not None:
                continue
            sz = item.sizeHint()
            ms = item.minimumSize()
            iw = max(sz.width(), ms.width())
            ih = max(sz.height(), ms.height())
            w_sum += iw + (self._h_spacing if vis > 0 else 0)
            h_max = max(h_max, ih)
            vis += 1
        return QSize(w_sum + m.left() + m.right(), h_max + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        m = self.contentsMargins()
        max_w = 0
        max_h = 0
        for item in self._items:
            wdg = item.widget()
            if wdg is not None and wdg.isHidden():
                continue
            if wdg is None and item.spacerItem() is not None:
                continue
            sz = item.minimumSize()
            sh = item.sizeHint()
            max_w = max(max_w, min(sz.width(), sh.width()) if sz.width() > 0 else sh.width())
            max_h = max(max_h, max(sz.height(), sh.height()))
        return QSize(max_w + m.left() + m.right(), max_h + m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        avail_w = max(1, eff.width())
        h_sp = self._h_spacing
        v_sp = self._v_spacing

        visible_items = []
        for item in self._items:
            wdg = item.widget()
            if wdg is not None and wdg.isHidden():
                continue
            if wdg is None and item.spacerItem() is not None:
                continue
            sz = item.sizeHint()
            ms = item.minimumSize()
            iw = max(sz.width(), ms.width())
            ih = max(sz.height(), ms.height())
            visible_items.append((item, wdg, iw, ih))

        if not visible_items:
            return m.top() + m.bottom()

        rows = []
        cur_row = []
        cur_w = 0
        for entry in visible_items:
            iw = entry[2]
            needed = iw if not cur_row else (cur_w + h_sp + iw)
            if cur_row and needed > avail_w:
                rows.append(cur_row)
                cur_row = [entry]
                cur_w = iw
            else:
                cur_row.append(entry)
                cur_w = needed
        if cur_row:
            rows.append(cur_row)

        parent_w = self.parentWidget()
        if parent_w is not None:
            is_rtl = parent_w.layoutDirection() == Qt.LayoutDirection.RightToLeft
        else:
            is_rtl = I18N.is_rtl()

        y = eff.y()
        for r_idx, row in enumerate(rows):
            row_h = max(e[3] for e in row)
            if not test_only:
                base_total = sum(e[2] for e in row) + h_sp * max(0, len(row) - 1)
                slack = avail_w - base_total
                widths = [e[2] for e in row]

                if self._justify and slack > 0 and len(row) >= 2:
                    exp_idx = [
                        i
                        for i, e in enumerate(row)
                        if e[1] is not None
                        and isinstance(e[1], QAbstractButton)
                        and (not isinstance(e[1], QCheckBox))
                    ]
                    if not exp_idx:
                        exp_idx = list(range(len(row)))

                    per_item = slack / len(exp_idx)
                    is_sparse_tail = (len(rows) > 1) and (r_idx == len(rows) - 1) and (len(row) <= 2)
                    max_cap = 45.0 if is_sparse_tail else 140.0

                    if per_item <= max_cap:
                        add_int = int(slack // len(exp_idx))
                        rem = int(slack - add_int * len(exp_idx))
                        for k_i, idx_e in enumerate(exp_idx):
                            widths[idx_e] += add_int + (1 if k_i < rem else 0)
                    else:
                        bonus = int(min(36.0, max_cap))
                        for idx_e in exp_idx:
                            widths[idx_e] += bonus

                if is_rtl:
                    x = eff.x() + eff.width()
                    for (item, _wdg, _iw, ih), final_w in zip(row, widths):
                        x -= final_w
                        iy = y + (row_h - ih) // 2
                        item.setGeometry(QRect(x, iy, final_w, ih))
                        x -= h_sp
                else:
                    x = eff.x()
                    for (item, _wdg, _iw, ih), final_w in zip(row, widths):
                        iy = y + (row_h - ih) // 2
                        item.setGeometry(QRect(x, iy, final_w, ih))
                        x += final_w + h_sp

            y += row_h + v_sp

        return max(0, (y - v_sp) - eff.y() + m.top() + m.bottom())


def _trim_windows_working_set() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        k32.SetProcessWorkingSetSize.restype = ctypes.c_int
        k32.SetProcessWorkingSetSize(k32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


class PowerAwareTimerController(QObject):
    """
    Zero-impact RAM/CPU guard:
      - Keeps animations 100% smooth while window is visible (unless Eco Mode is enabled).
      - Caps QPlainTextEdit log memory dynamically (default 250 lines).
      - Pauses animation timers + trims Windows working-set RAM when minimized or in Tray.
      - Resumes all paused timers unconditionally when window returns to foreground.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused_timers: set = set()
        self.tray_ram_trim_enabled: bool = True
        self.eco_mode: bool = False
        self.max_log_lines: int = 250

    def configure(self, max_log_lines: int = 250, tray_ram_trim: bool = True, eco_mode: bool = False, root: QWidget = None) -> None:
        self.max_log_lines = max(80, min(1500, int(max_log_lines or 250)))
        self.tray_ram_trim_enabled = bool(tray_ram_trim)
        self.eco_mode = bool(eco_mode)
        if root is not None:
            self.optimize_widget_tree(root)
            if self.eco_mode:
                self.pause_animations_in(root, trim_ws=False)
            elif not (root.isMinimized() or root.isHidden()):
                self.resume_animations_in(root)

    def optimize_widget_tree(self, root: QWidget) -> int:
        if root is None:
            return 0
        capped = 0
        try:
            from PySide6.QtWidgets import QPlainTextEdit
            for ed in root.findChildren(QPlainTextEdit):
                if ed.maximumBlockCount() == 0 or ed.maximumBlockCount() != self.max_log_lines:
                    ed.setMaximumBlockCount(self.max_log_lines)
                    capped += 1
        except Exception:
            pass
        return capped

    def pause_animations_in(self, root: QWidget, trim_ws: bool = True) -> int:
        if root is None:
            return 0
        paused = 0
        for t in root.findChildren(QTimer):
            iv = int(t.interval())
            if t.isActive() and (1 <= iv <= 120):
                t.stop()
                self._paused_timers.add(t)
                paused += 1
        if trim_ws and self.tray_ram_trim_enabled:
            import gc
            gc.collect()
            _trim_windows_working_set()
        return paused

    def resume_animations_in(self, root: QWidget) -> int:
        if root is None or self.eco_mode:
            return 0
        resumed = 0
        for t in list(self._paused_timers):
            self._paused_timers.discard(t)
            try:
                if not t.isActive():
                    t.start()
                    resumed += 1
            except RuntimeError:
                pass
        return resumed
