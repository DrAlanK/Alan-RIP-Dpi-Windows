import math
import random
from collections import deque
from pathlib import Path
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
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
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .flag_icons import GeoFlagResolver, VectorFlagRenderer
from .theme import (
    DARK_PALETTE,
    ThemePalette,
    enforce_english_ltr,
    lock_widget_dimensions,
    make_mono_font,
    make_ui_font,
    sanitize_ui_text,
)


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class VectorIconPainter:
    @staticmethod
    def draw_brand_logo(painter: QPainter, rect: QRectF, logo_path: str = "assets/logo.png"):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        path_obj = Path(logo_path)
        if path_obj.is_file():
            pix = QPixmap(str(path_obj))
            if not pix.isNull():
                scaled = pix.scaled(
                    int(rect.width()),
                    int(rect.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = rect.x() + (rect.width() - scaled.width()) / 2
                y = rect.y() + (rect.height() - scaled.height()) / 2
                painter.drawPixmap(int(x), int(y), scaled)
                painter.restore()
                return

        cx, cy = rect.center().x(), rect.center().y()
        w, h = rect.width() * 0.84, rect.height() * 0.84
        left, top = cx - w / 2, cy - h / 2

        shield = QPainterPath()
        shield.moveTo(cx, top)
        shield.lineTo(left + w, top + h * 0.20)
        shield.cubicTo(left + w, top + h * 0.62, cx + w * 0.35, top + h * 0.86, cx, top + h)
        shield.cubicTo(cx - w * 0.35, top + h * 0.86, left, top + h * 0.62, left, top + h * 0.20)
        shield.closeSubpath()

        grad = QLinearGradient(left, top, left + w, top + h)
        grad.setColorAt(0.0, QColor("#FFE14D"))
        grad.setColorAt(1.0, QColor("#F59E0B"))

        painter.setBrush(QColor(255, 208, 0, 38))
        painter.setPen(QPen(grad, 2.0))
        painter.drawPath(shield)

        bolt = QPainterPath()
        bolt.moveTo(cx + w * 0.10, top + h * 0.18)
        bolt.lineTo(cx - w * 0.20, cy + h * 0.04)
        bolt.lineTo(cx + w * 0.02, cy + h * 0.04)
        bolt.lineTo(cx - w * 0.12, top + h * 0.82)
        bolt.lineTo(cx + w * 0.22, cy - h * 0.05)
        bolt.lineTo(cx + w * 0.01, cy - h * 0.05)
        bolt.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(bolt)
        painter.restore()

    @staticmethod
    def draw_icon(
        painter: QPainter,
        name: str,
        rect: QRectF,
        color: QColor,
        stroke: float = 1.8,
        angle: float = 0.0,
    ):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) * 0.40

        if name == "radar_home":
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.drawEllipse(QPointF(cx, cy), r * 0.52, r * 0.52)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.72, cy - r * 0.68))

        elif name == "scanner":
            painter.drawEllipse(QPointF(cx, cy), r * 0.82, r * 0.82)
            painter.drawLine(QPointF(cx - r * 1.08, cy), QPointF(cx - r * 0.45, cy))
            painter.drawLine(QPointF(cx + r * 0.45, cy), QPointF(cx + r * 1.08, cy))
            painter.drawLine(QPointF(cx, cy - r * 1.08), QPointF(cx, cy - r * 0.45))
            painter.drawLine(QPointF(cx, cy + r * 0.45), QPointF(cx, cy + r * 1.08))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), 2.0, 2.0)

        elif name == "hunter":
            painter.drawEllipse(QPointF(cx, cy), r * 0.90, r * 0.90)
            painter.drawLine(QPointF(cx - r * 1.15, cy), QPointF(cx - r * 0.62, cy))
            painter.drawLine(QPointF(cx + r * 0.62, cy), QPointF(cx + r * 1.15, cy))
            painter.drawLine(QPointF(cx, cy - r * 1.15), QPointF(cx, cy - r * 0.62))
            painter.drawLine(QPointF(cx, cy + r * 0.62), QPointF(cx, cy + r * 1.15))
            bolt = QPainterPath()
            bolt.moveTo(cx + r * 0.16, cy - r * 0.56)
            bolt.lineTo(cx - r * 0.30, cy + r * 0.05)
            bolt.lineTo(cx + r * 0.04, cy + r * 0.05)
            bolt.lineTo(cx - r * 0.16, cy + r * 0.58)
            bolt.lineTo(cx + r * 0.32, cy - r * 0.06)
            bolt.lineTo(cx - r * 0.02, cy - r * 0.06)
            bolt.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(bolt)

        elif name == "power":
            arc_r = r * 0.86
            arc_rect = QRectF(cx - arc_r, cy - arc_r + r * 0.08, arc_r * 2, arc_r * 2)
            painter.drawArc(arc_rect, 130 * 16, 280 * 16)
            painter.drawLine(QPointF(cx, cy - r * 0.95), QPointF(cx, cy - r * 0.05))

        elif name == "shield_check":
            w, h = r * 1.85, r * 2.05
            left, top = cx - w / 2, cy - h / 2
            sh = QPainterPath()
            sh.moveTo(cx, top)
            sh.lineTo(left + w, top + h * 0.22)
            sh.cubicTo(left + w, top + h * 0.64, cx + w * 0.36, top + h * 0.88, cx, top + h)
            sh.cubicTo(cx - w * 0.36, top + h * 0.88, left, top + h * 0.64, left, top + h * 0.22)
            sh.closeSubpath()
            painter.drawPath(sh)
            painter.drawLine(QPointF(cx - r * 0.36, cy + r * 0.04), QPointF(cx - r * 0.06, cy + r * 0.34))
            painter.drawLine(QPointF(cx - r * 0.06, cy + r * 0.34), QPointF(cx + r * 0.42, cy - r * 0.22))

        elif name == "spinner":
            painter.translate(cx, cy)
            painter.rotate(angle)
            sp_r = r * 0.88
            arc_rect = QRectF(-sp_r, -sp_r, sp_r * 2, sp_r * 2)
            faint = QColor(color)
            faint.setAlpha(55)
            painter.setPen(QPen(faint, stroke))
            painter.drawEllipse(QPointF(0, 0), sp_r, sp_r)
            painter.setPen(QPen(color, stroke + 0.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, 0, 105 * 16)

        elif name == "clock":
            painter.drawEllipse(QPointF(cx, cy + r * 0.06), r * 0.88, r * 0.88)
            painter.drawLine(QPointF(cx - r * 0.28, cy - r * 1.02), QPointF(cx + r * 0.28, cy - r * 1.02))
            painter.drawLine(QPointF(cx, cy + r * 0.06), QPointF(cx, cy - r * 0.42))
            painter.drawLine(QPointF(cx, cy + r * 0.06), QPointF(cx + r * 0.38, cy + r * 0.24))

        elif name == "tun_shield":
            w, h = r * 1.85, r * 2.05
            left, top = cx - w / 2, cy - h / 2
            sh = QPainterPath()
            sh.moveTo(cx, top)
            sh.lineTo(left + w, top + h * 0.22)
            sh.cubicTo(left + w, top + h * 0.64, cx + w * 0.36, top + h * 0.88, cx, top + h)
            sh.cubicTo(cx - w * 0.36, top + h * 0.88, left, top + h * 0.64, left, top + h * 0.22)
            sh.closeSubpath()
            painter.drawPath(sh)
            painter.drawLine(QPointF(cx - r * 0.42, cy + r * 0.05), QPointF(cx + r * 0.42, cy + r * 0.05))
            painter.drawEllipse(QPointF(cx, cy + r * 0.05), r * 0.24, r * 0.24)

        elif name == "profiles":
            p1 = QPainterPath()
            p1.moveTo(cx, cy - r * 0.9)
            p1.lineTo(cx + r, cy - r * 0.35)
            p1.lineTo(cx, cy + r * 0.2)
            p1.lineTo(cx - r, cy - r * 0.35)
            p1.closeSubpath()
            painter.drawPath(p1)

            p2 = QPainterPath()
            p2.moveTo(cx - r, cy + r * 0.15)
            p2.lineTo(cx, cy + r * 0.7)
            p2.lineTo(cx + r, cy + r * 0.15)
            painter.drawPath(p2)

            p3 = QPainterPath()
            p3.moveTo(cx - r, cy + r * 0.55)
            p3.lineTo(cx, cy + r * 1.05)
            p3.lineTo(cx + r, cy + r * 0.55)
            painter.drawPath(p3)

        elif name == "settings":
            painter.drawEllipse(QPointF(cx, cy), r * 0.40, r * 0.40)
            for i in range(8):
                ang = i * (math.pi / 4.0)
                p_in = QPointF(cx + math.cos(ang) * r * 0.68, cy + math.sin(ang) * r * 0.68)
                p_out = QPointF(cx + math.cos(ang) * r * 0.98, cy + math.sin(ang) * r * 0.98)
                painter.drawLine(p_in, p_out)
            painter.drawEllipse(QPointF(cx, cy), r * 0.70, r * 0.70)

        elif name == "logs":
            box = QRectF(cx - r, cy - r * 0.82, r * 2.0, r * 1.64)
            painter.drawRoundedRect(box, 3.5, 3.5)
            painter.drawLine(QPointF(cx - r * 0.55, cy - r * 0.25), QPointF(cx - r * 0.15, cy + r * 0.08))
            painter.drawLine(QPointF(cx - r * 0.15, cy + r * 0.08), QPointF(cx - r * 0.55, cy + r * 0.40))
            painter.drawLine(QPointF(cx + r * 0.05, cy + r * 0.40), QPointF(cx + r * 0.55, cy + r * 0.40))

        elif name in ("lock", "lock_closed"):
            body = QRectF(cx - r * 0.68, cy - r * 0.05, r * 1.36, r * 1.05)
            painter.drawRoundedRect(body, 3.8, 3.8)
            shackle = QPainterPath()
            shackle.moveTo(cx - r * 0.42, cy - r * 0.05)
            shackle.lineTo(cx - r * 0.42, cy - r * 0.48)
            shackle.arcTo(QRectF(cx - r * 0.42, cy - r * 0.92, r * 0.84, r * 0.84), 180, -180)
            shackle.lineTo(cx + r * 0.42, cy - r * 0.05)
            painter.drawPath(shackle)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy + r * 0.44), 2.0, 2.0)

        elif name == "lock_open":
            body = QRectF(cx - r * 0.68, cy + r * 0.02, r * 1.36, r * 1.02)
            painter.drawRoundedRect(body, 3.8, 3.8)
            shackle = QPainterPath()
            shackle.moveTo(cx - r * 0.42, cy + r * 0.02)
            shackle.lineTo(cx - r * 0.42, cy - r * 0.52)
            shackle.arcTo(QRectF(cx - r * 0.42, cy - r * 0.96, r * 0.84, r * 0.84), 180, -155)
            painter.drawPath(shackle)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy + r * 0.50), 2.0, 2.0)

        elif name == "ip_globe":
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.drawEllipse(QPointF(cx, cy), r * 0.48, r)
            painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))

        elif name == "download":
            painter.drawLine(QPointF(cx, cy - r * 0.85), QPointF(cx, cy + r * 0.55))
            painter.drawLine(QPointF(cx - r * 0.5, cy + r * 0.08), QPointF(cx, cy + r * 0.6))
            painter.drawLine(QPointF(cx + r * 0.5, cy + r * 0.08), QPointF(cx, cy + r * 0.6))
            painter.drawLine(QPointF(cx - r * 0.7, cy + r * 0.9), QPointF(cx + r * 0.7, cy + r * 0.9))

        elif name == "upload":
            painter.drawLine(QPointF(cx, cy + r * 0.65), QPointF(cx, cy - r * 0.75))
            painter.drawLine(QPointF(cx - r * 0.5, cy - r * 0.25), QPointF(cx, cy - r * 0.78))
            painter.drawLine(QPointF(cx + r * 0.5, cy - r * 0.25), QPointF(cx, cy - r * 0.78))
            painter.drawLine(QPointF(cx - r * 0.7, cy + r * 0.9), QPointF(cx + r * 0.7, cy + r * 0.9))

        elif name == "wave":
            path = QPainterPath()
            path.moveTo(cx - r, cy)
            path.lineTo(cx - r * 0.45, cy)
            path.lineTo(cx - r * 0.20, cy - r * 0.75)
            path.lineTo(cx + r * 0.20, cy + r * 0.75)
            path.lineTo(cx + r * 0.45, cy)
            path.lineTo(cx + r, cy)
            painter.drawPath(path)

        elif name == "copy":
            r1 = QRectF(cx - r * 0.25, cy - r * 0.75, r * 1.10, r * 1.20)
            r2 = QRectF(cx - r * 0.80, cy - r * 0.20, r * 1.10, r * 1.20)
            painter.drawRoundedRect(r1, 2.5, 2.5)
            painter.drawRoundedRect(r2, 2.5, 2.5)

        elif name == "edit":
            p = QPainterPath()
            p.moveTo(cx - r * 0.75, cy + r * 0.75)
            p.lineTo(cx - r * 0.35, cy + r * 0.65)
            p.lineTo(cx + r * 0.72, cy - r * 0.42)
            p.lineTo(cx + r * 0.42, cy - r * 0.72)
            p.lineTo(cx - r * 0.65, cy + r * 0.35)
            p.closeSubpath()
            painter.drawPath(p)

        elif name == "trash":
            painter.drawLine(QPointF(cx - r * 0.8, cy - r * 0.5), QPointF(cx + r * 0.8, cy - r * 0.5))
            body = QRectF(cx - r * 0.6, cy - r * 0.5, r * 1.2, r * 1.35)
            painter.drawRoundedRect(body, 2.0, 2.0)
            painter.drawLine(QPointF(cx - r * 0.25, cy - r * 0.8), QPointF(cx + r * 0.25, cy - r * 0.8))

        elif name == "chevron_down":
            painter.drawLine(QPointF(cx - r * 0.65, cy - r * 0.25), QPointF(cx, cy + r * 0.38))
            painter.drawLine(QPointF(cx, cy + r * 0.38), QPointF(cx + r * 0.65, cy - r * 0.25))

        elif name == "chevron_left":
            painter.drawLine(QPointF(cx + r * 0.30, cy - r * 0.65), QPointF(cx - r * 0.35, cy))
            painter.drawLine(QPointF(cx - r * 0.35, cy), QPointF(cx + r * 0.30, cy + r * 0.65))

        elif name == "sun":
            painter.drawEllipse(QPointF(cx, cy), r * 0.46, r * 0.46)
            for i in range(8):
                ang = i * (math.pi / 4.0)
                painter.drawLine(
                    QPointF(cx + math.cos(ang) * r * 0.68, cy + math.sin(ang) * r * 0.68),
                    QPointF(cx + math.cos(ang) * r * 0.98, cy + math.sin(ang) * r * 0.98),
                )

        elif name == "moon":
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), r * 0.85, r * 0.85)
            cut = QPainterPath()
            cut.addEllipse(QPointF(cx + r * 0.38, cy - r * 0.28), r * 0.75, r * 0.75)
            painter.drawPath(path.subtracted(cut))

        elif name == "close":
            painter.drawLine(QPointF(cx - r * 0.65, cy - r * 0.65), QPointF(cx + r * 0.65, cy + r * 0.65))
            painter.drawLine(QPointF(cx + r * 0.65, cy - r * 0.65), QPointF(cx - r * 0.65, cy + r * 0.65))

        painter.restore()


class RadarShieldCore(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(215, 215)
        self.setMaximumSize(245, 245)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._country_code = "GLOBAL"
        self._flag_c1 = QColor("#FFD000")
        self._flag_c2 = QColor("#38BDF8")
        self._angle = 0.0
        self._pulse_phase = 0.0
        self._glow_intensity = 0.30

        self._glow_anim = QPropertyAnimation(self, b"glowIntensity", self)
        self._glow_anim.setDuration(400)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def sizeHint(self) -> QSize:
        return QSize(226, 226)

    def get_glow_intensity(self) -> float:
        return self._glow_intensity

    def set_glow_intensity(self, value: float):
        self._glow_intensity = value
        self.update()

    glowIntensity = Property(float, get_glow_intensity, set_glow_intensity)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def set_country_code(self, code: str):
        norm = str(code or "GLOBAL").upper()
        self._country_code = norm
        spec = GeoFlagResolver.get_spec(norm)
        self._flag_c1 = QColor(spec.c1)
        self._flag_c2 = QColor(spec.c2)
        self.update()

    def set_ui_phase(self, phase: str):
        norm = str(phase or "IDLE").upper()
        if norm not in ("IDLE", "CONNECTING", "CONNECTED", "ERROR"):
            norm = "IDLE"
        if norm == self._phase:
            return
        self._phase = norm
        target = 0.98 if norm == "CONNECTED" else (0.88 if norm == "CONNECTING" else 0.34)
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_intensity)
        self._glow_anim.setEndValue(target)
        self._glow_anim.start()

    def _on_tick(self):
        if self._phase == "CONNECTING":
            self._angle = (self._angle + 6.4) % 360.0
            self._pulse_phase = (self._pulse_phase + 0.13) % (2 * math.pi)
        elif self._phase == "CONNECTED":
            self._angle = (self._angle + 1.45) % 360.0
            self._pulse_phase = (self._pulse_phase + 0.055) % (2 * math.pi)
        else:
            self._angle = (self._angle + 0.55) % 360.0
            self._pulse_phase = (self._pulse_phase + 0.032) % (2 * math.pi)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        max_r = min(cx, cy) - 6.0
        breath = 0.5 + 0.5 * math.sin(self._pulse_phase)

        gold = QColor(self._palette.accent_primary)
        orange = QColor("#F97316")
        emerald = QColor("#10B981")
        crimson = QColor("#EF4444")

        if self._phase == "CONNECTED":
            core_color = emerald
            orbit_color = self._flag_c1
        elif self._phase == "CONNECTING":
            core_color = orange
            orbit_color = gold
        elif self._phase == "ERROR":
            core_color = crimson
            orbit_color = gold
        else:
            core_color = self._flag_c1
            orbit_color = gold

        aura_r = max_r * (0.90 + 0.09 * breath)
        aura = QRadialGradient(QPointF(cx, cy), aura_r)
        c_mid = QColor(core_color)
        c_mid.setAlpha(int(95 * self._glow_intensity + 30 * breath))
        aura.setColorAt(0.0, c_mid)
        aura.setColorAt(0.55, QColor(orbit_color.red(), orbit_color.green(), orbit_color.blue(), int(35 * self._glow_intensity)))
        aura.setColorAt(1.0, QColor(core_color.red(), core_color.green(), core_color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(aura)
        painter.drawEllipse(QPointF(cx, cy), aura_r, aura_r)

        for wave_idx in range(2):
            wave_prog = ((self._pulse_phase / (2 * math.pi)) + wave_idx * 0.5) % 1.0
            wave_r = max_r * (0.40 + 0.56 * wave_prog)
            base_alpha = 185 if self._phase == "CONNECTING" else (120 if self._phase == "CONNECTED" else 55)
            wave_alpha = int((1.0 - wave_prog) * base_alpha)
            wave_col = QColor(core_color.red(), core_color.green(), core_color.blue(), wave_alpha)
            painter.setPen(QPen(wave_col, 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), wave_r, wave_r)

        ticks = 36
        tick_r_in = max_r * 0.89
        tick_r_out = max_r * 0.96
        active_tick = int((self._angle / 360.0) * ticks)
        for i in range(ticks):
            ang = math.radians(i * (360.0 / ticks))
            dist = (i - active_tick) % ticks
            lit = dist < 8
            t_col = QColor(orbit_color if lit else core_color)
            t_col.setAlpha(210 if lit else 55)
            painter.setPen(QPen(t_col, 2.0 if lit else 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(cx + math.cos(ang) * tick_r_in, cy + math.sin(ang) * tick_r_in),
                QPointF(cx + math.cos(ang) * tick_r_out, cy + math.sin(ang) * tick_r_out),
            )

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        r_outer = max_r * 0.78
        seg_pen = QPen(
            QColor(orbit_color.red(), orbit_color.green(), orbit_color.blue(), 195),
            2.2,
            Qt.PenStyle.CustomDashLine,
            Qt.PenCapStyle.RoundCap,
        )
        seg_pen.setDashPattern([10, 8, 2, 8])
        painter.setPen(seg_pen)
        painter.drawEllipse(QPointF(0, 0), r_outer, r_outer)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(orbit_color)
        painter.drawEllipse(QPointF(r_outer, 0), 3.6, 3.6)
        painter.setBrush(self._flag_c2)
        painter.drawEllipse(QPointF(-r_outer, 0), 3.2, 3.2)
        painter.restore()

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-self._angle * 1.45)
        r_mid = max_r * 0.62
        sweep = QConicalGradient(QPointF(0, 0), 0)
        sweep_alpha = 165 if self._phase == "CONNECTING" else (110 if self._phase == "CONNECTED" else 65)
        sweep.setColorAt(0.0, QColor(core_color.red(), core_color.green(), core_color.blue(), sweep_alpha))
        sweep.setColorAt(0.32, QColor(core_color.red(), core_color.green(), core_color.blue(), 0))
        sweep.setColorAt(1.0, QColor(core_color.red(), core_color.green(), core_color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sweep)
        painter.drawEllipse(QPointF(0, 0), r_mid, r_mid)

        arc_col = QColor(core_color.red(), core_color.green(), core_color.blue(), 215)
        painter.setPen(QPen(arc_col, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arc_rect = QRectF(-r_mid, -r_mid, r_mid * 2, r_mid * 2)
        painter.drawArc(arc_rect, 15 * 16, 115 * 16)
        painter.drawArc(arc_rect, 195 * 16, 115 * 16)
        painter.restore()

        r_core = max_r * 0.42
        core_bg = QColor("#101521") if self._palette.is_dark else QColor("#FFFFFF")
        border_col = (
            emerald
            if self._phase == "CONNECTED"
            else (orange if self._phase == "CONNECTING" else (crimson if self._phase == "ERROR" else gold))
        )
        painter.setBrush(core_bg)
        painter.setPen(QPen(border_col, 2.6))
        painter.drawEllipse(QPointF(cx, cy), r_core, r_core)

        halo_col = QColor(border_col)
        halo_col.setAlpha(int(95 + 75 * breath))
        painter.setPen(QPen(halo_col, 4.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r_core - 4.5, r_core - 4.5)

        if self._phase == "CONNECTED":
            icon_name = "lock_closed"
            lock_color = emerald if not self._palette.is_dark else QColor("#FFFFFF")
        elif self._phase == "CONNECTING":
            icon_name = "lock_open"
            lock_color = orange
        else:
            icon_name = "lock_open"
            lock_color = crimson if self._phase == "ERROR" else gold

        VectorIconPainter.draw_icon(painter, icon_name, QRectF(cx - 21, cy - 21, 42, 42), lock_color, stroke=2.4)

        badge_w, badge_h = 38.0, 25.0
        bx = cx - r_core * 0.98
        by = cy + r_core * 0.48
        plate = QRectF(bx - 3, by - 3, badge_w + 6, badge_h + 6)
        painter.setPen(QPen(border_col, 1.5))
        painter.setBrush(core_bg)
        painter.drawRoundedRect(plate, 8.0, 8.0)
        VectorFlagRenderer.draw_flag(painter, self._country_code, QRectF(bx, by, badge_w, badge_h), radius=5.0)


class TunnelRouteBridgeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(62)
        self.setMaximumHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._palette: ThemePalette = DARK_PALETTE
        self._dest_code = "GLOBAL"
        self._dest_label = "مسیر جهانی"
        self._ip_text = ""
        self._ping_ms = 0
        self._phase = "IDLE"
        self._flow_offset = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def set_route_state(self, dest_code: str, ip_text: str, ping_ms: int, phase: str):
        norm = str(dest_code or "GLOBAL").upper()
        spec = GeoFlagResolver.get_spec(norm)
        self._dest_code = spec.code
        self._dest_label = spec.fa_name
        self._ip_text = str(ip_text or "").strip()
        self._ping_ms = int(ping_ms or 0)
        self._phase = str(phase or "IDLE").upper()
        self.update()

    def _tick(self):
        speed = 0.036 if self._phase == "CONNECTING" else (0.018 if self._phase == "CONNECTED" else 0.006)
        self._flow_offset = (self._flow_offset + speed) % 1.0
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        if w < 180:
            return

        spec = GeoFlagResolver.get_spec(self._dest_code)
        dest_accent = QColor(spec.c1)
        card_rect = QRectF(1.0, 2.0, w - 2.0, h - 4.0)

        bg = QColor(12, 16, 25, 195) if self._palette.is_dark else QColor(241, 245, 249, 225)
        border = QColor(dest_accent.red(), dest_accent.green(), dest_accent.blue(), 95 if self._phase == "CONNECTED" else 55)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.2))
        painter.drawRoundedRect(card_rect, 15.0, 15.0)

        cy = card_rect.center().y()
        flag_w, flag_h = 42.0, 28.0

        orig_flag_rect = QRectF(card_rect.right() - 16.0 - flag_w, cy - flag_h / 2.0, flag_w, flag_h)
        VectorFlagRenderer.draw_flag(painter, "IR", orig_flag_rect, radius=5.5)

        painter.setFont(make_ui_font(9, QFont.Weight.Bold))
        painter.setPen(QColor(self._palette.text_primary))
        orig_txt_rect = QRectF(orig_flag_rect.left() - 92.0, card_rect.top() + 8.0, 84.0, 20.0)
        painter.drawText(orig_txt_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "مبدأ: ایران")

        painter.setFont(make_mono_font(8, bold=False))
        painter.setPen(QColor(self._palette.text_muted))
        orig_sub_rect = QRectF(orig_flag_rect.left() - 92.0, cy + 2.0, 84.0, 18.0)
        painter.drawText(orig_sub_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "LOCAL NODE")

        dest_flag_rect = QRectF(card_rect.left() + 16.0, cy - flag_h / 2.0, flag_w, flag_h)
        if self._phase == "CONNECTED":
            halo_rect = dest_flag_rect.adjusted(-3.0, -3.0, 3.0, 3.0)
            painter.setPen(QPen(QColor("#10B981"), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(halo_rect, 7.0, 7.0)
        VectorFlagRenderer.draw_flag(painter, self._dest_code, dest_flag_rect, radius=5.5)

        painter.setFont(make_ui_font(9, QFont.Weight.Bold))
        painter.setPen(QColor(self._palette.text_primary))
        dest_txt_rect = QRectF(dest_flag_rect.right() + 10.0, card_rect.top() + 8.0, 155.0, 20.0)
        painter.drawText(
            dest_txt_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"مقصد: {self._dest_label}",
        )

        painter.setFont(make_mono_font(9, bold=True))
        sub_ip = self._ip_text if (self._phase == "CONNECTED" and self._ip_text and self._ip_text != "—") else spec.en_name
        painter.setPen(dest_accent if self._palette.is_dark else QColor(self._palette.text_secondary))
        dest_sub_rect = QRectF(dest_flag_rect.right() + 10.0, cy + 2.0, 155.0, 18.0)
        painter.drawText(dest_sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub_ip)

        track_right = orig_txt_rect.left() - 14.0
        track_left = dest_txt_rect.right() + 14.0
        if track_right - track_left > 50.0:
            base_line_col = QColor(255, 255, 255, 32) if self._palette.is_dark else QColor(15, 23, 42, 28)
            painter.setPen(QPen(base_line_col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(track_right, cy), QPointF(track_left, cy))

            active_col = (
                QColor("#10B981")
                if self._phase == "CONNECTED"
                else (QColor("#F97316") if self._phase == "CONNECTING" else dest_accent)
            )

            span = track_right - track_left
            num_pulses = 4
            for i in range(num_pulses):
                prog = (self._flow_offset + i / num_pulses) % 1.0
                px = track_right - prog * span
                alpha = int(255 * math.sin(prog * math.pi))
                dot_col = QColor(active_col.red(), active_col.green(), active_col.blue(), alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(dot_col)
                r_dot = 3.6 if self._phase in ("CONNECTING", "CONNECTED") else 2.4
                painter.drawEllipse(QPointF(px, cy), r_dot, r_dot)

            if self._phase == "CONNECTED" and self._ping_ms > 0:
                pill_txt = f"ENCRYPTED • {self._ping_ms} ms"
            elif self._phase == "CONNECTING":
                pill_txt = "SCANNING TUNNEL..."
            else:
                pill_txt = f"READY • {spec.code}"

            painter.setFont(make_mono_font(8, bold=True))
            fm = QFontMetrics(painter.font())
            pw = fm.horizontalAdvance(pill_txt) + 18.0
            mid_x = (track_left + track_right) / 2.0
            pill_rect = QRectF(mid_x - pw / 2.0, cy - 10.0, pw, 20.0)
            pill_bg = QColor("#0E131D") if self._palette.is_dark else QColor("#FFFFFF")
            painter.setBrush(pill_bg)
            painter.setPen(QPen(active_col, 1.1))
            painter.drawRoundedRect(pill_rect, 10.0, 10.0)
            painter.setPen(active_col if self._palette.is_dark else QColor("#0F172A"))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, pill_txt)


class AnimatedHeroConnectionCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._country_code = "GLOBAL"

        self._cur_c1 = QColor("#FFD000")
        self._cur_c2 = QColor("#38BDF8")
        self._cur_c3 = QColor("#10B981")
        self._target_c1 = QColor("#FFD000")
        self._target_c2 = QColor("#38BDF8")
        self._target_c3 = QColor("#10B981")

        self._wave_t = 0.0
        rng = random.Random(77)
        self._motes = [
            {
                "x": rng.uniform(0.03, 0.97),
                "y": rng.uniform(0.08, 0.92),
                "vx": rng.uniform(-0.0028, -0.0007),
                "vy": rng.uniform(-0.0018, 0.0018),
                "r": rng.uniform(1.2, 2.8),
                "slot": i % 3,
                "phase": rng.uniform(0, 2 * math.pi),
            }
            for i in range(28)
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def set_visual_context(self, country_code: str, phase: str):
        norm_code = str(country_code or "GLOBAL").upper()
        spec = GeoFlagResolver.get_spec(norm_code)
        self._country_code = spec.code
        self._target_c1 = QColor(spec.c1)
        self._target_c2 = QColor(spec.c2)
        self._target_c3 = QColor(spec.c3)
        self._phase = str(phase or "IDLE").upper()
        self.update()

    def _on_tick(self):
        speed_mult = 2.6 if self._phase == "CONNECTING" else (1.55 if self._phase == "CONNECTED" else 0.75)
        self._wave_t = (self._wave_t + 0.035 * speed_mult) % (2 * math.pi * 10)

        self._cur_c1 = _lerp_color(self._cur_c1, self._target_c1, 0.09)
        self._cur_c2 = _lerp_color(self._cur_c2, self._target_c2, 0.09)
        self._cur_c3 = _lerp_color(self._cur_c3, self._target_c3, 0.09)

        for m in self._motes:
            m["x"] = (m["x"] + m["vx"] * speed_mult) % 1.0
            m["y"] = (m["y"] + m["vy"] * speed_mult) % 1.0
            m["phase"] = (m["phase"] + 0.08 * speed_mult) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = 20.0
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)

        base_grad = QLinearGradient(rect.topRight(), rect.bottomLeft())
        if self._palette.is_dark:
            base_grad.setColorAt(0.0, QColor("#0D121C"))
            base_grad.setColorAt(0.55, QColor("#111827"))
            base_grad.setColorAt(1.0, QColor("#0B0F18"))
        else:
            base_grad.setColorAt(0.0, QColor("#FFFFFF"))
            base_grad.setColorAt(1.0, QColor("#F1F5F9"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base_grad)
        painter.drawRect(rect)

        grid_alpha = 15 if self._palette.is_dark else 12
        grid_pen = QPen(QColor(255, 255, 255, grid_alpha) if self._palette.is_dark else QColor(15, 23, 42, grid_alpha), 1.0)
        painter.setPen(grid_pen)
        step = 38
        for gx in range(int(rect.left()), int(rect.right()), step):
            painter.drawLine(gx, int(rect.top()), gx, int(rect.bottom()))
        for gy in range(int(rect.top()), int(rect.bottom()), step):
            painter.drawLine(int(rect.left()), gy, int(rect.right()), gy)

        aura_boost = 1.35 if self._phase == "CONNECTED" else (1.15 if self._phase == "CONNECTING" else 0.80)
        halo_left = QRadialGradient(QPointF(rect.left() + rect.width() * 0.22, rect.center().y()), rect.width() * 0.45)
        c1_glow = QColor(self._cur_c1)
        c1_glow.setAlpha(int((54 if self._palette.is_dark else 34) * aura_boost))
        halo_left.setColorAt(0.0, c1_glow)
        halo_left.setColorAt(1.0, QColor(c1_glow.red(), c1_glow.green(), c1_glow.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo_left)
        painter.drawRect(rect)

        halo_right = QRadialGradient(QPointF(rect.right() - 140.0, rect.center().y()), rect.height() * 0.85)
        right_base = QColor("#10B981") if self._phase == "CONNECTED" else (QColor("#F97316") if self._phase == "CONNECTING" else self._cur_c2)
        right_base.setAlpha(int((48 if self._palette.is_dark else 28) * aura_boost))
        halo_right.setColorAt(0.0, right_base)
        halo_right.setColorAt(1.0, QColor(right_base.red(), right_base.green(), right_base.blue(), 0))
        painter.setBrush(halo_right)
        painter.drawRect(rect)

        colors = (self._cur_c1, self._cur_c2, self._cur_c3)
        for idx, wave_col in enumerate(colors):
            ribbon = QPainterPath()
            base_y = rect.bottom() - (28.0 + idx * 22.0)
            ribbon.moveTo(rect.left(), rect.bottom())
            ribbon.lineTo(rect.left(), base_y)
            segs = 18
            for s in range(segs + 1):
                sx = rect.left() + (s / segs) * rect.width()
                sy = base_y + math.sin(s * 0.55 + self._wave_t * (0.9 + idx * 0.25) + idx * 1.4) * (14.0 + idx * 5.0)
                ribbon.lineTo(sx, sy)
            ribbon.lineTo(rect.right(), rect.bottom())
            ribbon.closeSubpath()

            fill = QColor(wave_col)
            fill.setAlpha(int((26 - idx * 5) * aura_boost) if self._palette.is_dark else int((18 - idx * 3) * aura_boost))
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(wave_col.red(), wave_col.green(), wave_col.blue(), int(55 * aura_boost)), 1.1))
            painter.drawPath(ribbon)

        painter.save()
        crest_w, crest_h = 184.0, 120.0
        painter.translate(rect.left() + 125.0, rect.bottom() - 82.0)
        painter.rotate(-9.0)
        crest_rect = QRectF(-crest_w / 2.0, -crest_h / 2.0, crest_w, crest_h)
        crest_opacity = 0.20 if self._phase == "CONNECTED" else 0.13
        if not self._palette.is_dark:
            crest_opacity *= 0.75
        VectorFlagRenderer.draw_flag(painter, self._country_code, crest_rect, radius=14.0, opacity=crest_opacity, with_border=True)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        for m in self._motes:
            m_col = QColor(colors[m["slot"]])
            twinkle = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(m["phase"]))
            m_col.setAlpha(int(155 * twinkle))
            painter.setBrush(m_col)
            px = rect.left() + m["x"] * rect.width()
            py = rect.top() + m["y"] * rect.height()
            painter.drawEllipse(QPointF(px, py), m["r"], m["r"])

        painter.setClipping(False)
        rim_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim_left = QColor(self._cur_c1)
        rim_left.setAlpha(155 if self._phase == "CONNECTED" else 105)
        rim_right = QColor("#10B981") if self._phase == "CONNECTED" else (QColor("#F97316") if self._phase == "CONNECTING" else QColor(self._palette.accent_primary))
        rim_right.setAlpha(155)
        rim_grad.setColorAt(0.0, rim_left)
        rim_grad.setColorAt(1.0, rim_right)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(rim_grad, 1.6))
        painter.drawRoundedRect(rect, radius, radius)


class KineticConnectButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setMaximumHeight(60)
        self.setMinimumWidth(285)
        self._palette: ThemePalette = DARK_PALETTE
        self._phase = "IDLE"
        self._hover_level = 0.0
        self._shimmer_pos = -0.35
        self._spinner_angle = 0.0
        self._pulse_phase = 0.0

        self._hover_anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._hover_anim.setDuration(240)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._shimmer_anim = QPropertyAnimation(self, b"shimmerPos", self)
        self._shimmer_anim.setDuration(900)
        self._shimmer_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._kinetic_timer = QTimer(self)
        self._kinetic_timer.setInterval(28)
        self._kinetic_timer.timeout.connect(self._on_kinetic_tick)
        self._kinetic_timer.start()

        self.setFont(make_ui_font(12, QFont.Weight.ExtraBold))
        self.set_phase_and_label("IDLE", "")

    def get_hover_level(self) -> float:
        return self._hover_level

    def set_hover_level(self, val: float):
        self._hover_level = val
        self.update()

    hoverLevel = Property(float, get_hover_level, set_hover_level)

    def get_shimmer_pos(self) -> float:
        return self._shimmer_pos

    def set_shimmer_pos(self, val: float):
        self._shimmer_pos = val
        self.update()

    shimmerPos = Property(float, get_shimmer_pos, set_shimmer_pos)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def _on_kinetic_tick(self):
        if self._phase == "CONNECTING":
            self._spinner_angle = (self._spinner_angle + 11.0) % 360.0
            self._pulse_phase = (self._pulse_phase + 0.15) % (2 * math.pi)
            self.update()
        else:
            self._pulse_phase = (self._pulse_phase + 0.045) % (2 * math.pi)
            if self._hover_level > 0.01:
                self.update()

    def _trigger_shimmer_sweep(self):
        self._shimmer_anim.stop()
        self._shimmer_anim.setStartValue(-0.35)
        self._shimmer_anim.setEndValue(1.35)
        self._shimmer_anim.start()

    def set_phase_and_label(self, phase: str, custom_label: str = ""):
        norm = str(phase or "IDLE").upper()
        if norm not in ("IDLE", "CONNECTING", "CONNECTED", "ERROR"):
            norm = "IDLE"
        self._phase = norm

        if norm == "CONNECTING":
            label = "لغو فرایند (کلیک برای توقف)"
            if custom_label and "لغو" in custom_label and "توقف" in custom_label:
                label = custom_label
            self.setText(label)
        elif norm == "CONNECTED":
            label = "قطع اتصال امن"
            if custom_label and "امن" in custom_label:
                label = custom_label
            self.setText(label)
        else:
            self.setText(custom_label if custom_label else "اتصال هوشمند")
        self.update()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_level)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        self._trigger_shimmer_sweep()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_level)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = 5.0
        rect = QRectF(pad, pad, self.width() - 2 * pad, self.height() - 2 * pad)
        radius = rect.height() / 2.0
        breath = 0.5 + 0.5 * math.sin(self._pulse_phase)

        if self._phase == "CONNECTING":
            glow_col = QColor(249, 115, 22, int(65 + 55 * breath + 35 * self._hover_level))
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FB923C") if self._hover_level > 0.5 else QColor("#F97316"))
            grad.setColorAt(1.0, QColor("#DC2626") if self._hover_level > 0.5 else QColor("#EF4444"))
            rim_col = QColor(255, 237, 160, int(145 + 100 * breath))
            text_col = QColor("#FFFFFF")
            icon_name = "spinner"
        elif self._phase == "CONNECTED":
            glow_col = QColor(16, 185, 129, int(55 + 45 * self._hover_level))
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#10B981"))
            grad.setColorAt(0.65, QColor("#059669"))
            grad.setColorAt(1.0, QColor("#047857"))
            rim_col = QColor("#FCD34D") if self._hover_level > 0.35 else QColor("#34D399")
            text_col = QColor("#FFFFFF")
            icon_name = "shield_check"
        else:
            glow_col = QColor(255, 208, 0, int(52 + 62 * self._hover_level))
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FFE55C") if self._hover_level > 0.3 else QColor("#FFD000"))
            grad.setColorAt(0.55, QColor("#FFC300"))
            grad.setColorAt(1.0, QColor("#F59E0B"))
            rim_col = QColor(255, 255, 255, int(130 + 85 * self._hover_level))
            text_col = QColor("#090B10")
            icon_name = "power"

        outer_rect = rect.adjusted(-4.0, -4.0, 4.0, 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_col)
        painter.drawRoundedRect(outer_rect, radius + 4.0, radius + 4.0)

        capsule_path = QPainterPath()
        capsule_path.addRoundedRect(rect, radius, radius)

        painter.setBrush(grad)
        painter.setPen(QPen(rim_col, 1.8))
        painter.drawPath(capsule_path)

        if -0.30 < self._shimmer_pos < 1.30:
            painter.save()
            painter.setClipPath(capsule_path)
            band_cx = rect.left() + rect.width() * self._shimmer_pos
            band_w = rect.width() * 0.28
            shimmer_grad = QLinearGradient(
                QPointF(band_cx - band_w, rect.top()),
                QPointF(band_cx + band_w, rect.bottom()),
            )
            shimmer_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer_grad.setColorAt(0.5, QColor(255, 255, 255, 115 if self._phase != "CONNECTED" else 85))
            shimmer_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shimmer_grad)
            painter.drawRect(rect)
            painter.restore()

        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        label = self.text()
        text_w = fm.horizontalAdvance(label)
        icon_dim = 20.0
        gap = 10.0
        total_w = text_w + gap + icon_dim
        start_x = rect.center().x() - total_w / 2.0

        icon_rect = QRectF(start_x + text_w + gap, rect.center().y() - icon_dim / 2.0, icon_dim, icon_dim)
        text_rect = QRectF(start_x, rect.top(), text_w + 4.0, rect.height())

        painter.setPen(text_col)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
        VectorIconPainter.draw_icon(
            painter,
            icon_name,
            icon_rect,
            text_col,
            stroke=2.1,
            angle=self._spinner_angle,
        )


PrimaryConnectButton = KineticConnectButton


class SimpleChronometerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(158, 46)
        self.setMaximumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._palette: ThemePalette = DARK_PALETTE
        self._uptime_label = "00:00:00"
        self._is_connected = False
        self._pulse = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def sizeHint(self) -> QSize:
        return QSize(164, 46)

    def _tick(self):
        if self._is_connected:
            self._pulse = (self._pulse + 0.14) % (2 * math.pi)
            self.update()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def set_uptime_state(self, uptime_label: str, is_connected: bool):
        clean = str(uptime_label or "").strip()
        self._uptime_label = clean if clean else "00:00:00"
        self._is_connected = bool(is_connected)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(1.5, 2.0, self.width() - 3.0, self.height() - 4.0)
        radius = rect.height() / 2.0

        bg = QColor(12, 16, 25, 215) if self._palette.is_dark else QColor(241, 245, 249, 240)
        border = (
            QColor(16, 185, 129, 145)
            if self._is_connected
            else (QColor(255, 255, 255, 34) if self._palette.is_dark else QColor(15, 23, 42, 32))
        )
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.3))
        painter.drawRoundedRect(rect, radius, radius)

        dot_col = QColor("#10B981") if self._is_connected else QColor(self._palette.text_muted)
        dot_center = QPointF(rect.left() + 18.0, rect.center().y())
        if self._is_connected:
            halo_alpha = int(55 + 75 * (0.5 + 0.5 * math.sin(self._pulse)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 185, 129, halo_alpha))
            painter.drawEllipse(dot_center, 6.2, 6.2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        painter.drawEllipse(dot_center, 3.2, 3.2)

        clock_rect = QRectF(rect.right() - 28.0, rect.center().y() - 8.5, 17.0, 17.0)
        clock_col = QColor(self._palette.accent_primary) if self._is_connected else QColor(self._palette.text_muted)
        VectorIconPainter.draw_icon(painter, "clock", clock_rect, clock_col, stroke=1.7)

        txt_rect = QRectF(rect.left() + 28.0, rect.top(), rect.width() - 60.0, rect.height())
        painter.setFont(make_mono_font(12, bold=True))
        painter.setPen(
            QColor(self._palette.text_primary) if self._is_connected else QColor(self._palette.text_secondary)
        )
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, self._uptime_label)


SpoilerChronometerWidget = SimpleChronometerWidget


class SpinnerGlyphWidget(QWidget):
    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        lock_widget_dimensions(self, size, size)
        self._palette: ThemePalette = DARK_PALETTE
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_running(self, running: bool):
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running and self._timer.isActive():
            self._timer.stop()
        self.update()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def _tick(self):
        self._angle = (self._angle + 12.0) % 360.0
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        col = QColor(self._palette.accent_primary)
        VectorIconPainter.draw_icon(
            painter,
            "spinner",
            QRectF(1, 1, self.width() - 2, self.height() - 2),
            col,
            stroke=1.8,
            angle=self._angle,
        )


class TaskProgressStrip(QFrame):
    stop_requested = Signal()

    def __init__(self, inline_style: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("InlineTaskBar" if inline_style else "GlobalTaskBar")
        self._target_height = 42 if inline_style else 38
        self._palette: ThemePalette = DARK_PALETTE
        self.setMaximumHeight(0)
        self.hide()

        self._height_anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._height_anim.setDuration(240)
        self._height_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height_anim.finished.connect(self._on_anim_finished)

        self._hide_delay = QTimer(self)
        self._hide_delay.setSingleShot(True)
        self._hide_delay.setInterval(420)
        self._hide_delay.timeout.connect(self._collapse_now)

        self._active = False

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 5, 16, 5)
        row.setSpacing(10)

        self.spinner = SpinnerGlyphWidget(size=18)

        self.msg_lbl = QLabel("در حال اجرای عملیات...")
        self.msg_lbl.setObjectName("SecondaryLabel")

        self.bar = QProgressBar()
        self.bar.setObjectName("GoldProgress")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setMinimumWidth(160)
        self.bar.setMaximumWidth(280)
        self.bar.setMinimumHeight(7)
        self.bar.setMaximumHeight(8)
        enforce_english_ltr(self.bar, mono_size=9)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setObjectName("BadgePill")
        enforce_english_ltr(self.pct_lbl, mono_size=10, bold=True)

        self.stop_btn = QPushButton("توقف")
        self.stop_btn.setObjectName("DangerPillBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        row.addWidget(self.spinner)
        row.addWidget(self.msg_lbl, 1)
        row.addWidget(self.bar)
        row.addWidget(self.pct_lbl)
        row.addWidget(self.stop_btn)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.spinner.set_palette_theme(palette)

    def update_task_state(self, active: bool, percent: int, message: str):
        clamped = max(0, min(100, int(percent or 0)))
        self.bar.setValue(clamped)
        self.pct_lbl.setText(f"{clamped}%")
        if message:
            self.msg_lbl.setText(sanitize_ui_text(message))

        if active:
            self._hide_delay.stop()
            self._active = True
            self.spinner.set_running(True)
            if not self.isVisible() or self.maximumHeight() < self._target_height:
                self.show()
                self._height_anim.stop()
                self._height_anim.setStartValue(self.maximumHeight())
                self._height_anim.setEndValue(self._target_height)
                self._height_anim.start()
        else:
            self._active = False
            self.spinner.set_running(False)
            if self.isVisible():
                self._hide_delay.start()

    def _collapse_now(self):
        if self._active:
            return
        self._height_anim.stop()
        self._height_anim.setStartValue(self.maximumHeight())
        self._height_anim.setEndValue(0)
        self._height_anim.start()

    def _on_anim_finished(self):
        if not self._active and self.maximumHeight() == 0:
            self.hide()


class ActionIconPillButton(QPushButton):
    def __init__(self, icon_name: str, text: str, golden: bool = True, parent=None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._golden = golden
        self._hovered = False
        self._palette: ThemePalette = DARK_PALETTE
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(35)
        self.setMaximumHeight(37)
        self.setFont(make_ui_font(9, QFont.Weight.Bold))
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(fm.horizontalAdvance(text) + 48)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = 11.0

        if self._golden:
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FFE352") if self._hovered else QColor("#FFD000"))
            grad.setColorAt(1.0, QColor("#F59E0B"))
            painter.setPen(QPen(QColor(255, 255, 255, 90 if self._hovered else 45), 1.0))
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, radius, radius)
            fg = QColor("#090B10")
        else:
            bg = QColor(255, 208, 0, 42 if self._hovered else 24)
            painter.setPen(QPen(QColor(self._palette.accent_primary), 1.2))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, radius, radius)
            fg = QColor(self._palette.accent_primary) if self._palette.is_dark else QColor("#9A6B00")

        icon_rect = QRectF(rect.right() - 26.0, rect.center().y() - 8.5, 17.0, 17.0)
        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, fg, stroke=1.7)

        txt_rect = QRectF(rect.left() + 10.0, rect.top(), rect.width() - 40.0, rect.height())
        painter.setPen(fg)
        painter.setFont(self.font())
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, self.text())


class LiveSparklineWidget(QWidget):
    def __init__(self, max_points: int = 34, parent=None):
        super().__init__(parent)
        self._max_points = max_points
        self._samples = deque([0.0] * max_points, maxlen=max_points)
        self._palette: ThemePalette = DARK_PALETTE
        self._secondary_tint = False
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_palette_theme(self, palette: ThemePalette, secondary_tint: bool = False):
        self._palette = palette
        self._secondary_tint = secondary_tint
        self.update()

    def push_sample(self, value: float):
        clean_val = max(0.0, float(value or 0.0))
        self._samples.append(clean_val)
        self.update()

    def reset_flat(self):
        if any(v > 0.0 for v in self._samples):
            self._samples = deque([0.0] * self._max_points, maxlen=self._max_points)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        if w < 10 or h < 10 or len(self._samples) < 2:
            return

        pad_x, pad_top, pad_bot = 4.0, 5.0, 5.0
        usable_w = w - 2 * pad_x
        usable_h = h - pad_top - pad_bot
        baseline_y = pad_top + usable_h

        line_color = (
            QColor("#FFFFFF")
            if (self._secondary_tint and self._palette.is_dark)
            else QColor(self._palette.accent_primary)
        )

        peak = max(self._samples)
        if peak <= 0.0001:
            flat_col = QColor(line_color)
            flat_col.setAlpha(65)
            painter.setPen(QPen(flat_col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(pad_x, baseline_y), QPointF(w - pad_x, baseline_y))
            return

        pts = []
        n = len(self._samples)
        for idx, val in enumerate(self._samples):
            x = pad_x + (idx / (n - 1)) * usable_w
            norm = min(val / (peak * 1.12), 1.0)
            y = pad_top + usable_h * (1.0 - norm)
            pts.append(QPointF(x, y))

        line_path = QPainterPath(pts[0])
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            mid_x = (p0.x() + p1.x()) / 2.0
            line_path.cubicTo(QPointF(mid_x, p0.y()), QPointF(mid_x, p1.y()), p1)

        fill_path = QPainterPath(line_path)
        fill_path.lineTo(pts[-1].x(), baseline_y)
        fill_path.lineTo(pts[0].x(), baseline_y)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, pad_top, 0, h)
        top_fill = QColor(line_color)
        top_fill.setAlpha(75 if self._palette.is_dark else 55)
        bot_fill = QColor(line_color)
        bot_fill.setAlpha(0)
        grad.setColorAt(0.0, top_fill)
        grad.setColorAt(1.0, bot_fill)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill_path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line_color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(line_path)

        if self._samples[-1] > 0.0:
            tip = pts[-1]
            painter.setPen(Qt.PenStyle.NoPen)
            halo = QColor(line_color)
            halo.setAlpha(95)
            painter.setBrush(halo)
            painter.drawEllipse(tip, 4.6, 4.6)
            painter.setBrush(line_color)
            painter.drawEllipse(tip, 2.2, 2.2)


class AnimatedToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lock_widget_dimensions(self, 46, 25)
        self._palette: ThemePalette = DARK_PALETTE
        self._offset = 1.0 if checked else 0.0

        self._anim = QPropertyAnimation(self, b"knobOffset", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_state)

    def get_knob_offset(self) -> float:
        return self._offset

    def set_knob_offset(self, val: float):
        self._offset = val
        self.update()

    knobOffset = Property(float, get_knob_offset, set_knob_offset)

    def set_CheckedSilent(self, checked: bool):
        self.blockSignals(True)
        self.setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.blockSignals(False)
        self.update()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def _animate_state(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(46, 25)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = rect.height() / 2.0

        off_bg = QColor("#1E293B") if self._palette.is_dark else QColor("#CBD5E1")
        on_bg = QColor(self._palette.accent_primary)

        r = int(off_bg.red() + (on_bg.red() - off_bg.red()) * self._offset)
        g = int(off_bg.green() + (on_bg.green() - off_bg.green()) * self._offset)
        b = int(off_bg.blue() + (on_bg.blue() - off_bg.blue()) * self._offset)
        track_col = QColor(r, g, b)

        painter.setPen(
            QPen(QColor(255, 255, 255, 28) if self._palette.is_dark else QColor(15, 23, 42, 22), 1.0)
        )
        painter.setBrush(track_col)
        painter.drawRoundedRect(rect, radius, radius)

        knob_d = rect.height() - 5.0
        min_x = rect.left() + 2.5
        max_x = rect.right() - knob_d - 2.5
        knob_x = min_x + (max_x - min_x) * self._offset
        knob_rect = QRectF(knob_x, rect.top() + 2.5, knob_d, knob_d)

        knob_col = QColor("#090B10") if (self._offset > 0.5 and self._palette.is_dark) else QColor("#FFFFFF")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_col)
        painter.drawEllipse(knob_rect)


class NavRailButton(QAbstractButton):
    def __init__(self, icon_name: str, title: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._title = title
        self._palette: ThemePalette = DARK_PALETTE
        self._hovered = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lock_widget_dimensions(self, 78, 62)

    def sizeHint(self) -> QSize:
        return QSize(78, 62)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(5, 3, self.width() - 10, self.height() - 6)

        active = self.isChecked()
        accent = QColor(self._palette.accent_primary)

        if active:
            bg = QColor(accent.red(), accent.green(), accent.blue(), 34 if self._palette.is_dark else 44)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 95), 1.0))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 13, 13)

            pill = QRectF(self.width() - 4.2, 16, 3.0, self.height() - 32)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(pill, 1.5, 1.5)
        elif self._hovered:
            bg = QColor(255, 255, 255, 12) if self._palette.is_dark else QColor(15, 23, 42, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 13, 13)

        icon_col = (
            accent
            if (active and self._palette.is_dark)
            else (QColor("#9A6B00") if active else QColor(self._palette.text_muted))
        )
        if self._hovered and not active:
            icon_col = QColor(self._palette.text_primary)

        icon_rect = QRectF((self.width() - 22) / 2, 8, 22, 22)
        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, icon_col, stroke=1.8)

        painter.setPen(icon_col)
        painter.setFont(make_ui_font(9, QFont.Weight.Bold if active else QFont.Weight.Medium))
        painter.drawText(QRectF(2, 33, self.width() - 4, 23), Qt.AlignmentFlag.AlignCenter, self._title)


class VectorIconButton(QAbstractButton):
    def __init__(self, icon_name: str, size: int = 32, danger_hover: bool = False, parent=None):
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

    def set_icon_name(self, icon_name: str):
        self._icon_name = icon_name
        self.update()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)

        if self._hovered:
            bg = (
                QColor("#EF4444")
                if self._danger_hover
                else (QColor(255, 208, 0, 32) if self._palette.is_dark else QColor(15, 23, 42, 16))
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 9, 9)

        col = (
            QColor("#FFFFFF")
            if (self._hovered and self._danger_hover)
            else (
                QColor(self._palette.accent_primary)
                if (self._hovered and self._palette.is_dark)
                else QColor(self._palette.text_secondary)
            )
        )
        pad = self.width() * 0.24
        icon_rect = QRectF(pad, pad, self.width() - 2 * pad, self.height() - 2 * pad)
        VectorIconPainter.draw_icon(painter, self._icon_name, icon_rect, col, stroke=1.75)


class SegmentedCapsuleBar(QFrame):
    current_changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("PillBar")
        self._palette: ThemePalette = DARK_PALETTE
        self._buttons: list[QPushButton] = []
        self._current_index = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        for idx, text in enumerate(labels):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _chk=False, i=idx: self.set_current_index(i, emit_signal=True))
            self._buttons.append(btn)
            layout.addWidget(btn, 1)

        self._refresh_button_styles()

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int, emit_signal: bool = False):
        if not (0 <= index < len(self._buttons)):
            return
        self._current_index = index
        for i, btn in enumerate(self._buttons):
            btn.blockSignals(True)
            btn.setChecked(i == index)
            btn.blockSignals(False)
        self._refresh_button_styles()
        if emit_signal:
            self.current_changed.emit(index)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self._refresh_button_styles()

    def _refresh_button_styles(self):
        p = self._palette
        for i, btn in enumerate(self._buttons):
            if i == self._current_index:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {p.accent_primary}; color: {p.button_text_on_accent}; "
                    f"border: none; border-radius: 10px; font-weight: 800; font-size: 11px; padding: 6px 12px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; color: {p.text_secondary}; "
                    f"border: none; border-radius: 10px; font-weight: 600; font-size: 11px; padding: 6px 12px; }}"
                    f"QPushButton:hover {{ background-color: {p.accent_soft_bg}; color: {p.text_primary}; }}"
                )


class CollapsibleAccordion(QFrame):
    def __init__(self, title: str, subtitle: str = "", expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self._expanded = expanded
        self._palette: ThemePalette = DARK_PALETTE

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_btn = QWidget()
        self.header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr_layout = QHBoxLayout(self.header_btn)
        hdr_layout.setContentsMargins(18, 14, 18, 14)
        hdr_layout.setSpacing(12)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(make_ui_font(11, QFont.Weight.Bold))
        txt_col.addWidget(self.title_lbl)
        if subtitle:
            self.sub_lbl = QLabel(subtitle)
            self.sub_lbl.setObjectName("MutedLabel")
            txt_col.addWidget(self.sub_lbl)

        self.state_pill = QLabel("باز کردن" if not expanded else "بستن")
        self.state_pill.setObjectName("BadgePill")

        self.chevron = VectorIconButton("chevron_down" if expanded else "chevron_left", size=28)
        self.chevron.clicked.connect(self.toggle)

        hdr_layout.addLayout(txt_col, 1)
        hdr_layout.addWidget(self.state_pill)
        hdr_layout.addWidget(self.chevron)
        self.header_btn.mouseReleaseEvent = lambda _e: self.toggle()

        self.body_container = QWidget()
        self.body_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout(self.body_container)
        self.body_layout.setContentsMargins(18, 4, 18, 18)
        self.body_layout.setSpacing(14)
        self.body_container.setVisible(expanded)

        outer.addWidget(self.header_btn)
        outer.addWidget(self.body_container)

    def toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self.body_container.setVisible(expanded)
        self.chevron.set_icon_name("chevron_down" if expanded else "chevron_left")
        self.state_pill.setText("بستن" if expanded else "باز کردن")

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.chevron.set_palette_theme(palette)