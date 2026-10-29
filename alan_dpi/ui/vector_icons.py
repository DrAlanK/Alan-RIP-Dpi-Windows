import math
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


class VectorIconPainter:
    """Pure QPainter/QPainterPath vector icon renderer."""

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

        # Fallback: Custom Electric-Yellow & Pure-White Shield + Lightning Bolt
        cx, cy = rect.center().x(), rect.center().y()
        w, h = rect.width() * 0.84, rect.height() * 0.84
        left, top = cx - w / 2, cy - h / 2

        shield = QPainterPath()
        shield.moveTo(cx, top)
        shield.lineTo(left + w, top + h * 0.20)
        shield.cubicTo(
            left + w, top + h * 0.62,
            cx + w * 0.35, top + h * 0.86,
            cx, top + h
        )
        shield.cubicTo(
            cx - w * 0.35, top + h * 0.86,
            left, top + h * 0.62,
            left, top + h * 0.20
        )
        shield.closeSubpath()

        grad = QLinearGradient(left, top, left + w, top + h)
        grad.setColorAt(0.0, QColor("#FFE14D"))
        grad.setColorAt(1.0, QColor("#F59E0B"))

        painter.setBrush(QColor(255, 208, 0, 35))
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
    def draw_icon(painter: QPainter, name: str, rect: QRectF, color: QColor, stroke: float = 1.8):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) * 0.40

        if name == "radar_home":
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.drawEllipse(QPointF(cx, cy), r * 0.55, r * 0.55)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.72, cy - r * 0.68))

        elif name == "profiles":
            # Stacked geometric layers
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
            painter.drawEllipse(QPointF(cx, cy), r * 0.42, r * 0.42)
            teeth = 8
            for i in range(teeth):
                ang = i * (2 * math.pi / teeth)
                p_in = QPointF(cx + math.cos(ang) * r * 0.68, cy + math.sin(ang) * r * 0.68)
                p_out = QPointF(cx + math.cos(ang) * r * 0.98, cy + math.sin(ang) * r * 0.98)
                painter.drawLine(p_in, p_out)
            painter.drawEllipse(QPointF(cx, cy), r * 0.72, r * 0.72)

        elif name == "logs":
            box = QRectF(cx - r, cy - r * 0.85, r * 2, r * 1.7)
            painter.drawRoundedRect(box, 3.5, 3.5)
            painter.drawLine(QPointF(cx - r * 0.55, cy - r * 0.25), QPointF(cx - r * 0.15, cy + r * 0.08))
            painter.drawLine(QPointF(cx - r * 0.15, cy + r * 0.08), QPointF(cx - r * 0.55, cy + r * 0.40))
            painter.drawLine(QPointF(cx + r * 0.05, cy + r * 0.40), QPointF(cx + r * 0.55, cy + r * 0.40))

        elif name == "lock":
            body = QRectF(cx - r * 0.68, cy - r * 0.08, r * 1.36, r * 1.05)
            painter.drawRoundedRect(body, 3.5, 3.5)
            shackle = QPainterPath()
            shackle.moveTo(cx - r * 0.42, cy - r * 0.08)
            shackle.lineTo(cx - r * 0.42, cy - r * 0.48)
            shackle.arcTo(QRectF(cx - r * 0.42, cy - r * 0.92, r * 0.84, r * 0.84), 180, -180)
            shackle.lineTo(cx + r * 0.42, cy - r * 0.08)
            painter.drawPath(shackle)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy + r * 0.42), 1.8, 1.8)

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
            r1 = QRectF(cx - r * 0.3, cy - r * 0.75, r * 1.15, r * 1.25)
            r2 = QRectF(cx - r * 0.8, cy - r * 0.25, r * 1.15, r * 1.25)
            painter.drawRoundedRect(r1, 2.5, 2.5)
            painter.drawRoundedRect(r2, 2.5, 2.5)

        elif name == "plus":
            painter.drawLine(QPointF(cx - r * 0.75, cy), QPointF(cx + r * 0.75, cy))
            painter.drawLine(QPointF(cx, cy - r * 0.75), QPointF(cx, cy + r * 0.75))

        elif name == "trash":
            painter.drawLine(QPointF(cx - r * 0.8, cy - r * 0.5), QPointF(cx + r * 0.8, cy - r * 0.5))
            body = QRectF(cx - r * 0.6, cy - r * 0.5, r * 1.2, r * 1.35)
            painter.drawRoundedRect(body, 2.0, 2.0)
            painter.drawLine(QPointF(cx - r * 0.25, cy - r * 0.8), QPointF(cx + r * 0.25, cy - r * 0.8))

        elif name == "sun":
            painter.drawEllipse(QPointF(cx, cy), r * 0.46, r * 0.46)
            for i in range(8):
                ang = i * (math.pi / 4)
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

        elif name == "minimize":
            painter.drawLine(QPointF(cx - r * 0.7, cy), QPointF(cx + r * 0.7, cy))

        painter.restore()