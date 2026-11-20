import math
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

_VEC_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}


class VectorIconPainter:
    @staticmethod
    def draw_brand_logo(painter: QPainter, rect: QRectF, logo_path: str = "assets/logo.png") -> None:
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
                x = rect.x() + (rect.width() - scaled.width()) / 2.0
                y = rect.y() + (rect.height() - scaled.height()) / 2.0
                painter.drawPixmap(int(x), int(y), scaled)
                painter.restore()
                return

        cx, cy = rect.center().x(), rect.center().y()
        w, h = rect.width() * 0.86, rect.height() * 0.86
        left, top = cx - w / 2.0, cy - h / 2.0

        shield = QPainterPath()
        shield.moveTo(cx, top)
        shield.lineTo(left + w, top + h * 0.20)
        shield.cubicTo(left + w, top + h * 0.62, cx + w * 0.36, top + h * 0.86, cx, top + h)
        shield.cubicTo(cx - w * 0.36, top + h * 0.86, left, top + h * 0.62, left, top + h * 0.20)
        shield.closeSubpath()

        grad = QLinearGradient(left, top, left + w, top + h)
        grad.setColorAt(0.0, QColor("#FFE55C"))
        grad.setColorAt(0.6, QColor("#FFD000"))
        grad.setColorAt(1.0, QColor("#D97706"))

        painter.setBrush(QColor(255, 208, 0, 42))
        painter.setPen(QPen(grad, max(1.6, w * 0.075)))
        painter.drawPath(shield)

        bolt = QPainterPath()
        bolt.moveTo(cx + w * 0.11, top + h * 0.17)
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
    def build_tray_icon(phase: str = "IDLE", logo_path: str = "assets/logo.png") -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        VectorIconPainter.draw_brand_logo(painter, QRectF(4.0, 4.0, 52.0, 52.0), logo_path)

        norm = str(phase or "IDLE").upper()
        if norm == "CONNECTED":
            dot_col = QColor("#10B981")
        elif norm == "CONNECTING":
            dot_col = QColor("#F97316")
        else:
            dot_col = QColor("#FFD000")

        painter.setPen(QPen(QColor("#181F2C"), 3.0))
        painter.setBrush(dot_col)
        painter.drawEllipse(QPointF(50.0, 50.0), 9.5, 9.5)
        painter.end()
        return QIcon(pix)

    @staticmethod
    def draw_icon(
        painter: QPainter,
        name: str,
        rect: QRectF,
        color: QColor,
        stroke: float = 1.8,
        angle: float = 0.0,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) * 0.40

        if name == "home":
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.drawEllipse(QPointF(cx, cy), r * 0.50, r * 0.50)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.70, cy - r * 0.68))

        elif name == "configs":
            top_p = QPainterPath()
            top_p.moveTo(cx, cy - r * 0.90)
            top_p.lineTo(cx + r, cy - r * 0.35)
            top_p.lineTo(cx, cy + r * 0.18)
            top_p.lineTo(cx - r, cy - r * 0.35)
            top_p.closeSubpath()
            painter.drawPath(top_p)

            mid_p = QPainterPath()
            mid_p.moveTo(cx - r, cy + r * 0.14)
            mid_p.lineTo(cx, cy + r * 0.66)
            mid_p.lineTo(cx + r, cy + r * 0.14)
            painter.drawPath(mid_p)

            bot_p = QPainterPath()
            bot_p.moveTo(cx - r, cy + r * 0.52)
            bot_p.lineTo(cx, cy + r * 1.04)
            bot_p.lineTo(cx + r, cy + r * 0.52)
            painter.drawPath(bot_p)

        elif name == "lab":
            flask = QPainterPath()
            flask.moveTo(cx - r * 0.28, cy - r * 0.88)
            flask.lineTo(cx + r * 0.28, cy - r * 0.88)
            flask.moveTo(cx - r * 0.20, cy - r * 0.88)
            flask.lineTo(cx - r * 0.20, cy - r * 0.22)
            flask.lineTo(cx - r * 0.82, cy + r * 0.78)
            flask.quadTo(cx - r * 0.88, cy + r * 0.95, cx - r * 0.65, cy + r * 0.95)
            flask.lineTo(cx + r * 0.65, cy + r * 0.95)
            flask.quadTo(cx + r * 0.88, cy + r * 0.95, cx + r * 0.82, cy + r * 0.78)
            flask.lineTo(cx + r * 0.20, cy - r * 0.22)
            flask.lineTo(cx + r * 0.20, cy - r * 0.88)
            painter.drawPath(flask)
            painter.drawLine(QPointF(cx - r * 0.52, cy + r * 0.38), QPointF(cx + r * 0.52, cy + r * 0.38))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx - r * 0.15, cy + r * 0.66), 1.6, 1.6)
            painter.drawEllipse(QPointF(cx + r * 0.20, cy + r * 0.58), 1.3, 1.3)

        elif name in ("routing", "settings"):
            rad_k = r * 0.23
            y1, y2, y3 = cy - r * 0.56, cy, cy + r * 0.56
            k1, k2, k3 = cx - r * 0.28, cx + r * 0.34, cx - r * 0.14
            painter.drawLine(QPointF(cx - r * 0.88, y1), QPointF(k1 - rad_k, y1))
            painter.drawLine(QPointF(k1 + rad_k, y1), QPointF(cx + r * 0.88, y1))
            painter.drawLine(QPointF(cx - r * 0.88, y2), QPointF(k2 - rad_k, y2))
            painter.drawLine(QPointF(k2 + rad_k, y2), QPointF(cx + r * 0.88, y2))
            painter.drawLine(QPointF(cx - r * 0.88, y3), QPointF(k3 - rad_k, y3))
            painter.drawLine(QPointF(k3 + rad_k, y3), QPointF(cx + r * 0.88, y3))
            painter.drawEllipse(QPointF(k1, y1), rad_k, rad_k)
            painter.drawEllipse(QPointF(k2, y2), rad_k, rad_k)
            painter.drawEllipse(QPointF(k3, y3), rad_k, rad_k)

        elif name == "logs":
            box = QRectF(cx - r, cy - r * 0.82, r * 2.0, r * 1.64)
            painter.drawRoundedRect(box, 3.8, 3.8)
            painter.drawLine(QPointF(cx - r * 0.55, cy - r * 0.25), QPointF(cx - r * 0.15, cy + r * 0.08))
            painter.drawLine(QPointF(cx - r * 0.15, cy + r * 0.08), QPointF(cx - r * 0.55, cy + r * 0.40))
            painter.drawLine(QPointF(cx + r * 0.05, cy + r * 0.40), QPointF(cx + r * 0.55, cy + r * 0.40))

        elif name == "gemini":
            star = QPainterPath()
            star.moveTo(cx, cy - r)
            star.quadTo(cx, cy, cx + r, cy)
            star.quadTo(cx, cy, cx, cy + r)
            star.quadTo(cx, cy, cx - r, cy)
            star.quadTo(cx, cy, cx, cy - r)
            star.closeSubpath()
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(star)

        elif name == "power":
            arc_r = r * 0.86
            arc_rect = QRectF(cx - arc_r, cy - arc_r + r * 0.08, arc_r * 2.0, arc_r * 2.0)
            painter.drawArc(arc_rect, 130 * 16, 280 * 16)
            painter.drawLine(QPointF(cx, cy - r * 0.95), QPointF(cx, cy - r * 0.05))

        elif name == "shield_check":
            w, h = r * 1.82, r * 2.02
            left, top = cx - w / 2.0, cy - h / 2.0
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
            faint = QColor(color)
            faint.setAlpha(55)
            painter.setPen(QPen(faint, stroke))
            painter.drawEllipse(QPointF(0.0, 0.0), sp_r, sp_r)
            painter.setPen(QPen(color, stroke + 0.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(-sp_r, -sp_r, sp_r * 2.0, sp_r * 2.0), 0, 108 * 16)

        elif name in ("lock", "lock_closed"):
            body = QRectF(cx - r * 0.68, cy - r * 0.05, r * 1.36, r * 1.04)
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
            shackle.arcTo(QRectF(cx - r * 0.42, cy - r * 0.96, r * 0.84, r * 0.84), 180, -152)
            painter.drawPath(shackle)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy + r * 0.50), 2.0, 2.0)

        elif name == "clock":
            painter.drawEllipse(QPointF(cx, cy + r * 0.05), r * 0.88, r * 0.88)
            painter.drawLine(QPointF(cx - r * 0.26, cy - r * 1.02), QPointF(cx + r * 0.26, cy - r * 1.02))
            painter.drawLine(QPointF(cx, cy + r * 0.05), QPointF(cx, cy - r * 0.42))
            painter.drawLine(QPointF(cx, cy + r * 0.05), QPointF(cx + r * 0.38, cy + r * 0.24))

        elif name == "eye":
            eye = QPainterPath()
            eye.moveTo(cx - r * 1.02, cy)
            eye.quadTo(cx, cy - r * 0.80, cx + r * 1.02, cy)
            eye.quadTo(cx, cy + r * 0.80, cx - r * 1.02, cy)
            painter.drawPath(eye)
            painter.drawEllipse(QPointF(cx, cy), r * 0.30, r * 0.30)

        elif name == "eye_off":
            eye = QPainterPath()
            eye.moveTo(cx - r * 1.02, cy)
            eye.quadTo(cx, cy - r * 0.80, cx + r * 1.02, cy)
            eye.quadTo(cx, cy + r * 0.80, cx - r * 1.02, cy)
            painter.drawPath(eye)
            painter.drawLine(QPointF(cx - r * 0.82, cy - r * 0.75), QPointF(cx + r * 0.82, cy + r * 0.75))

        elif name in ("globe", "ip_globe"):
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.drawEllipse(QPointF(cx, cy), r * 0.48, r)
            painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))

        elif name == "download":
            painter.drawLine(QPointF(cx, cy - r * 0.85), QPointF(cx, cy + r * 0.55))
            painter.drawLine(QPointF(cx - r * 0.48, cy + r * 0.08), QPointF(cx, cy + r * 0.58))
            painter.drawLine(QPointF(cx + r * 0.48, cy + r * 0.08), QPointF(cx, cy + r * 0.58))
            painter.drawLine(QPointF(cx - r * 0.70, cy + r * 0.90), QPointF(cx + r * 0.70, cy + r * 0.90))

        elif name == "upload":
            painter.drawLine(QPointF(cx, cy + r * 0.65), QPointF(cx, cy - r * 0.75))
            painter.drawLine(QPointF(cx - r * 0.48, cy - r * 0.25), QPointF(cx, cy - r * 0.78))
            painter.drawLine(QPointF(cx + r * 0.48, cy - r * 0.25), QPointF(cx, cy - r * 0.78))
            painter.drawLine(QPointF(cx - r * 0.70, cy + r * 0.90), QPointF(cx + r * 0.70, cy + r * 0.90))

        elif name == "wave":
            path = QPainterPath()
            path.moveTo(cx - r, cy)
            path.lineTo(cx - r * 0.45, cy)
            path.lineTo(cx - r * 0.20, cy - r * 0.75)
            path.lineTo(cx + r * 0.20, cy + r * 0.75)
            path.lineTo(cx + r * 0.45, cy)
            path.lineTo(cx + r, cy)
            painter.drawPath(path)

        elif name == "plus":
            painter.drawLine(QPointF(cx - r * 0.76, cy), QPointF(cx + r * 0.76, cy))
            painter.drawLine(QPointF(cx, cy - r * 0.76), QPointF(cx, cy + r * 0.76))

        elif name == "copy":
            r1 = QRectF(cx - r * 0.25, cy - r * 0.75, r * 1.10, r * 1.20)
            r2 = QRectF(cx - r * 0.80, cy - r * 0.20, r * 1.10, r * 1.20)
            painter.drawRoundedRect(r1, 2.5, 2.5)
            painter.drawRoundedRect(r2, 2.5, 2.5)

        elif name == "edit":
            p = QPainterPath()
            p.moveTo(cx - r * 0.75, cy + r * 0.75)
            p.lineTo(cx - r * 0.34, cy + r * 0.64)
            p.lineTo(cx + r * 0.72, cy - r * 0.42)
            p.lineTo(cx + r * 0.42, cy - r * 0.72)
            p.lineTo(cx - r * 0.64, cy + r * 0.34)
            p.closeSubpath()
            painter.drawPath(p)

        elif name == "trash":
            painter.drawLine(QPointF(cx - r * 0.80, cy - r * 0.50), QPointF(cx + r * 0.80, cy - r * 0.50))
            body = QRectF(cx - r * 0.60, cy - r * 0.50, r * 1.20, r * 1.35)
            painter.drawRoundedRect(body, 2.0, 2.0)
            painter.drawLine(QPointF(cx - r * 0.26, cy - r * 0.80), QPointF(cx + r * 0.26, cy - r * 0.80))

        elif name == "refresh":
            arc_rect = QRectF(cx - r * 0.80, cy - r * 0.80, r * 1.60, r * 1.60)
            painter.drawArc(arc_rect, 35 * 16, 285 * 16)
            painter.drawLine(QPointF(cx + r * 0.62, cy - r * 0.56), QPointF(cx + r * 0.82, cy - r * 0.08))
            painter.drawLine(QPointF(cx + r * 0.32, cy - r * 0.22), QPointF(cx + r * 0.82, cy - r * 0.08))

        elif name == "play":
            tri = QPainterPath()
            tri.moveTo(cx - r * 0.45, cy - r * 0.72)
            tri.lineTo(cx + r * 0.72, cy)
            tri.lineTo(cx - r * 0.45, cy + r * 0.72)
            tri.closeSubpath()
            painter.setBrush(color)
            painter.drawPath(tri)

        elif name == "stop":
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(cx - r * 0.60, cy - r * 0.60, r * 1.20, r * 1.20), 2.2, 2.2)

        elif name == "check":
            painter.drawLine(QPointF(cx - r * 0.72, cy + r * 0.04), QPointF(cx - r * 0.16, cy + r * 0.58))
            painter.drawLine(QPointF(cx - r * 0.16, cy + r * 0.58), QPointF(cx + r * 0.76, cy - r * 0.52))

        elif name == "bolt":
            bolt = QPainterPath()
            bolt.moveTo(cx + r * 0.14, cy - r * 0.90)
            bolt.lineTo(cx - r * 0.52, cy + r * 0.08)
            bolt.lineTo(cx + r * 0.04, cy + r * 0.08)
            bolt.lineTo(cx - r * 0.18, cy + r * 0.90)
            bolt.lineTo(cx + r * 0.54, cy - r * 0.08)
            bolt.lineTo(cx - r * 0.02, cy - r * 0.08)
            bolt.closeSubpath()
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(bolt)

        elif name == "sun":
            painter.drawEllipse(QPointF(cx, cy), r * 0.45, r * 0.45)
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

        elif name == "info":
            painter.drawEllipse(QPointF(cx, cy), r * 0.92, r * 0.92)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy - r * 0.36), 1.35, 1.35)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx, cy - r * 0.06), QPointF(cx, cy + r * 0.48))

        elif name == "close":
            painter.drawLine(QPointF(cx - r * 0.65, cy - r * 0.65), QPointF(cx + r * 0.65, cy + r * 0.65))
            painter.drawLine(QPointF(cx + r * 0.65, cy - r * 0.65), QPointF(cx - r * 0.65, cy + r * 0.65))

        painter.restore()


def make_vector_qicon(name: str, color_hex: str = "#FFD000", size: int = 18) -> QIcon:
    key = (name, color_hex, size)
    if key in _VEC_ICON_CACHE:
        return _VEC_ICON_CACHE[key]

    dpr = 2.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    VectorIconPainter.draw_icon(
        painter,
        name,
        QRectF(1.0, 1.0, size - 2.0, size - 2.0),
        QColor(color_hex),
        stroke=1.65,
    )
    painter.end()

    icon = QIcon(pix)
    _VEC_ICON_CACHE[key] = icon
    return icon