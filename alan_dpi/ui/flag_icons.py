import math
import re
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .theme import lock_widget_dimensions


@dataclass(frozen=True)
class CountryVisualSpec:
    code: str
    fa_name: str
    en_name: str
    c1: str
    c2: str
    c3: str


COUNTRY_SPECS: dict[str, CountryVisualSpec] = {
    "IR": CountryVisualSpec("IR", "ایران", "IRAN", "#169B62", "#FFD000", "#DA291C"),
    "DE": CountryVisualSpec("DE", "آلمان", "GERMANY", "#FFCE00", "#DD0000", "#F59E0B"),
    "NL": CountryVisualSpec("NL", "هلند", "NETHERLANDS", "#2563EB", "#F8FAFC", "#E11D48"),
    "US": CountryVisualSpec("US", "آمریکا", "UNITED STATES", "#3B82F6", "#EF4444", "#F8FAFC"),
    "GB": CountryVisualSpec("GB", "بریتانیا", "UNITED KINGDOM", "#2563EB", "#EF4444", "#F8FAFC"),
    "FR": CountryVisualSpec("FR", "فرانسه", "FRANCE", "#2563EB", "#F8FAFC", "#EF4444"),
    "FI": CountryVisualSpec("FI", "فنلاند", "FINLAND", "#38BDF8", "#F8FAFC", "#0284C7"),
    "SE": CountryVisualSpec("SE", "سوئد", "SWEDEN", "#0EA5E9", "#FACC15", "#38BDF8"),
    "CH": CountryVisualSpec("CH", "سوئیس", "SWITZERLAND", "#EF4444", "#FFFFFF", "#F87171"),
    "TR": CountryVisualSpec("TR", "ترکیه", "TURKEY", "#EF4444", "#F8FAFC", "#DC2626"),
    "AE": CountryVisualSpec("AE", "امارات", "UAE", "#10B981", "#EF4444", "#F8FAFC"),
    "SG": CountryVisualSpec("SG", "سنگاپور", "SINGAPORE", "#EF4444", "#FFFFFF", "#FB7185"),
    "JP": CountryVisualSpec("JP", "ژاپن", "JAPAN", "#F43F5E", "#FFFFFF", "#FDA4AF"),
    "CA": CountryVisualSpec("CA", "کانادا", "CANADA", "#EF4444", "#FFFFFF", "#F87171"),
    "PL": CountryVisualSpec("PL", "لهستان", "POLAND", "#F8FAFC", "#DC2626", "#FB7185"),
    "AT": CountryVisualSpec("AT", "اتریش", "AUSTRIA", "#EF4444", "#FFFFFF", "#DC2626"),
    "IT": CountryVisualSpec("IT", "ایتالیا", "ITALY", "#10B981", "#FFFFFF", "#EF4444"),
    "ES": CountryVisualSpec("ES", "اسپانیا", "SPAIN", "#FACC15", "#DC2626", "#F59E0B"),
    "RU": CountryVisualSpec("RU", "روسیه", "RUSSIA", "#3B82F6", "#EF4444", "#FFFFFF"),
    "UA": CountryVisualSpec("UA", "اوکراین", "UKRAINE", "#0EA5E9", "#FFD000", "#38BDF8"),
    "KR": CountryVisualSpec("KR", "کره جنوبی", "SOUTH KOREA", "#3B82F6", "#EF4444", "#FFFFFF"),
    "IN": CountryVisualSpec("IN", "هند", "INDIA", "#FB923C", "#10B981", "#FFFFFF"),
    "GLOBAL": CountryVisualSpec("GLOBAL", "مسیر جهانی", "GLOBAL EDGE", "#FFD000", "#38BDF8", "#10B981"),
}

_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("iran", "tehran", "shiraz", "tabriz", "isfahan", "mashhad", "mci", "irancell", "rightel", "shatel", "ایران", "تهران", "همراه", "ایرانسل"), "IR"),
    (("german", "germany", "frankfurt", "falkenstein", "nuremberg", "hetzner", "berlin", "munich", "آلمان", "فرانکفورت", "هتزنر"), "DE"),
    (("netherland", "holland", "amsterdam", "rotterdam", "هلند", "آمستردام"), "NL"),
    (("united states", "america", "usa", "newyork", "new york", "dallas", "los angeles", "chicago", "miami", "ashburn", "آمریکا"), "US"),
    (("united kingdom", "britain", "england", "london", "manchester", "انگلیس", "بریتانیا", "لندن"), "GB"),
    (("finland", "helsinki", "فنلاند", "هلسینکی"), "FI"),
    (("france", "paris", "marseille", "فرانسه", "پاریس"), "FR"),
    (("turkey", "turkiye", "istanbul", "ankara", "izmir", "ترکیه", "استانبول"), "TR"),
    (("uae", "dubai", "abudhabi", "emirates", "امارات", "دبی"), "AE"),
    (("sweden", "stockholm", "سوئد", "استکهلم"), "SE"),
    (("switzerland", "swiss", "zurich", "geneva", "سوئیس", "زوریخ"), "CH"),
    (("singapore", "سنگاپور"), "SG"),
    (("japan", "tokyo", "osaka", "ژاپن", "توکیو"), "JP"),
    (("canada", "toronto", "montreal", "vancouver", "کانادا"), "CA"),
    (("poland", "warsaw", "لهستان"), "PL"),
    (("austria", "vienna", "اتریش", "وین"), "AT"),
    (("italy", "milan", "rome", "ایتالیا"), "IT"),
    (("spain", "madrid", "barcelona", "اسپانیا"), "ES"),
    (("russia", "moscow", "روسیه", "مسکو"), "RU"),
    (("ukraine", "kyiv", "اوکراین"), "UA"),
    (("korea", "seoul", "کره"), "KR"),
    (("india", "mumbai", "هند"), "IN"),
]

_ICON_CACHE: dict[tuple[str, int, int], QIcon] = {}


class GeoFlagResolver:
    @staticmethod
    def extract_unicode_flag(text: str) -> str:
        if not text:
            return ""
        chars = list(str(text))
        for i in range(len(chars) - 1):
            o1, o2 = ord(chars[i]), ord(chars[i + 1])
            if 0x1F1E6 <= o1 <= 0x1F1FF and 0x1F1E6 <= o2 <= 0x1F1FF:
                code = chr(o1 - 0x1F1E6 + ord("A")) + chr(o2 - 0x1F1E6 + ord("A"))
                return "GB" if code == "UK" else code
        return ""

    @staticmethod
    def clean_display_name(text: str) -> str:
        if not text:
            return ""
        no_ri = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}", "", str(text)).strip()
        m = re.match(r"^([A-Za-z]{2})\s+(.+)$", no_ri)
        if m and m.group(1).upper() in COUNTRY_SPECS:
            return m.group(2).strip()
        return no_ri

    @staticmethod
    def resolve_code(*sources) -> str:
        for src in sources:
            if not src:
                continue
            if isinstance(src, dict):
                for explicit_key in ("country_code", "egress_country", "country", "cc"):
                    val = str(src.get(explicit_key) or "").strip().upper()
                    if val == "UK":
                        val = "GB"
                    if val in COUNTRY_SPECS:
                        return val
                combined = " ".join(
                    str(src.get(k) or "")
                    for k in ("name", "title", "sni", "host_header", "address", "endpoint", "detail")
                )
                found = GeoFlagResolver.resolve_code(combined)
                if found != "GLOBAL":
                    return found
                continue

            raw = str(src).strip()
            upper_exact = raw.upper()
            if upper_exact == "UK":
                return "GB"
            if upper_exact in COUNTRY_SPECS:
                return upper_exact

            uni = GeoFlagResolver.extract_unicode_flag(raw)
            if uni in COUNTRY_SPECS:
                return uni

            m_prefix = re.match(r"^\[?([A-Za-z]{2})\]?[\s\-_|•:]+", raw)
            if m_prefix:
                cand = m_prefix.group(1).upper()
                cand = "GB" if cand == "UK" else cand
                if cand in COUNTRY_SPECS:
                    return cand

            low = raw.lower()
            if low.endswith(".ir") or ".ir:" in low:
                return "IR"
            for keywords, code in _KEYWORD_MAP:
                for kw in keywords:
                    if kw in low:
                        return code

        return "GLOBAL"

    @staticmethod
    def get_spec(code: str) -> CountryVisualSpec:
        norm = str(code or "GLOBAL").strip().upper()
        if norm == "UK":
            norm = "GB"
        return COUNTRY_SPECS.get(norm, COUNTRY_SPECS["GLOBAL"])


class VectorFlagRenderer:
    @staticmethod
    def draw_flag(
        painter: QPainter,
        code: str,
        rect: QRectF,
        radius: float = 4.5,
        opacity: float = 1.0,
        with_border: bool = True,
    ) -> None:
        if rect.width() < 4 or rect.height() < 4:
            return
        norm = str(code or "GLOBAL").strip().upper()
        if norm == "UK":
            norm = "GB"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(opacity)

        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)

        if norm == "IR":
            VectorFlagRenderer._draw_iran_lion_sun(painter, rect)
        elif norm == "DE":
            VectorFlagRenderer._draw_h3(painter, rect, "#141414", "#DD0000", "#FFCE00")
        elif norm == "NL":
            VectorFlagRenderer._draw_h3(painter, rect, "#AE1C28", "#FFFFFF", "#21468B")
        elif norm == "RU":
            VectorFlagRenderer._draw_h3(painter, rect, "#FFFFFF", "#0039A6", "#D52B1E")
        elif norm == "AT":
            VectorFlagRenderer._draw_h3(painter, rect, "#ED2939", "#FFFFFF", "#ED2939")
        elif norm == "FR":
            VectorFlagRenderer._draw_v3(painter, rect, "#002395", "#FFFFFF", "#ED2939")
        elif norm == "IT":
            VectorFlagRenderer._draw_v3(painter, rect, "#009246", "#FFFFFF", "#CE2B37")
        elif norm == "PL":
            VectorFlagRenderer._draw_h2(painter, rect, "#FFFFFF", "#DC143C")
        elif norm == "UA":
            VectorFlagRenderer._draw_h2(painter, rect, "#0057B7", "#FFD700")
        elif norm == "FI":
            VectorFlagRenderer._draw_nordic(painter, rect, "#FFFFFF", "#003580")
        elif norm == "SE":
            VectorFlagRenderer._draw_nordic(painter, rect, "#006AA7", "#FECC02")
        elif norm == "CH":
            VectorFlagRenderer._draw_swiss(painter, rect)
        elif norm == "TR":
            VectorFlagRenderer._draw_turkey(painter, rect)
        elif norm == "AE":
            VectorFlagRenderer._draw_uae(painter, rect)
        elif norm == "JP":
            VectorFlagRenderer._draw_japan(painter, rect)
        elif norm == "US":
            VectorFlagRenderer._draw_usa(painter, rect)
        elif norm == "GB":
            VectorFlagRenderer._draw_uk(painter, rect)
        elif norm == "SG":
            VectorFlagRenderer._draw_singapore(painter, rect)
        elif norm == "CA":
            VectorFlagRenderer._draw_canada(painter, rect)
        elif norm == "ES":
            VectorFlagRenderer._draw_spain(painter, rect)
        elif norm == "IN":
            VectorFlagRenderer._draw_india(painter, rect)
        elif norm == "KR":
            VectorFlagRenderer._draw_korea(painter, rect)
        else:
            VectorFlagRenderer._draw_global_edge(painter, rect)

        gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 42))
        gloss.setColorAt(0.45, QColor(255, 255, 255, 0))
        gloss.setColorAt(1.0, QColor(0, 0, 0, 32))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gloss)
        painter.drawRect(rect)

        painter.setClipping(False)
        if with_border:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 58), 1.0))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        painter.restore()

    @staticmethod
    def _draw_h3(p: QPainter, r: QRectF, c1: str, c2: str, c3: str):
        p.setPen(Qt.PenStyle.NoPen)
        sh = r.height() / 3.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), r.width(), sh + 0.5))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x(), r.y() + sh, r.width(), sh + 0.5))
        p.setBrush(QColor(c3))
        p.drawRect(QRectF(r.x(), r.y() + 2 * sh, r.width(), r.height() - 2 * sh))

    @staticmethod
    def _draw_v3(p: QPainter, r: QRectF, c1: str, c2: str, c3: str):
        p.setPen(Qt.PenStyle.NoPen)
        sw = r.width() / 3.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), sw + 0.5, r.height()))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x() + sw, r.y(), sw + 0.5, r.height()))
        p.setBrush(QColor(c3))
        p.drawRect(QRectF(r.x() + 2 * sw, r.y(), r.width() - 2 * sw, r.height()))

    @staticmethod
    def _draw_h2(p: QPainter, r: QRectF, c1: str, c2: str):
        p.setPen(Qt.PenStyle.NoPen)
        sh = r.height() / 2.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), r.width(), sh + 0.5))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x(), r.y() + sh, r.width(), sh))

    @staticmethod
    def _draw_iran_lion_sun(p: QPainter, r: QRectF):
        VectorFlagRenderer._draw_h3(p, r, "#169B62", "#FFFFFF", "#DA291C")

        cx = r.center().x()
        cy = r.center().y()
        u = r.height() * 0.30

        sun_cx = cx + u * 0.08
        sun_cy = cy - u * 0.01
        sun_r = u * 0.27

        rays = QPainterPath()
        num_rays = 15
        for i in range(num_rays):
            ang_deg = -172.0 + i * (164.0 / (num_rays - 1))
            ang = math.radians(ang_deg)
            spread = math.radians(4.8)
            tip_len = sun_r * (1.58 if i % 2 == 0 else 1.34)
            p_base1 = QPointF(sun_cx + math.cos(ang - spread) * (sun_r * 0.82), sun_cy + math.sin(ang - spread) * (sun_r * 0.82))
            p_tip = QPointF(sun_cx + math.cos(ang) * tip_len, sun_cy + math.sin(ang) * tip_len)
            p_base2 = QPointF(sun_cx + math.cos(ang + spread) * (sun_r * 0.82), sun_cy + math.sin(ang + spread) * (sun_r * 0.82))
            rays.moveTo(p_base1)
            rays.lineTo(p_tip)
            rays.lineTo(p_base2)
            rays.closeSubpath()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F59E0B"))
        p.drawPath(rays)

        sun_grad = QRadialGradient(QPointF(sun_cx, sun_cy - sun_r * 0.2), sun_r * 1.1)
        sun_grad.setColorAt(0.0, QColor("#FFF7BF"))
        sun_grad.setColorAt(0.65, QColor("#FFD000"))
        sun_grad.setColorAt(1.0, QColor("#D97706"))
        p.setBrush(sun_grad)
        p.drawEllipse(QPointF(sun_cx, sun_cy), sun_r, sun_r)

        def pt(nx: float, ny: float) -> QPointF:
            return QPointF(cx + nx * u, cy + ny * u)

        gold_grad = QLinearGradient(pt(-0.45, -0.45), pt(0.42, 0.45))
        gold_grad.setColorAt(0.0, QColor("#FFE047"))
        gold_grad.setColorAt(0.55, QColor("#EAB308"))
        gold_grad.setColorAt(1.0, QColor("#B45309"))

        lion = QPainterPath()
        lion.moveTo(pt(-0.24, 0.43))
        lion.lineTo(pt(-0.26, 0.15))
        lion.cubicTo(pt(-0.37, 0.08), pt(-0.39, -0.10), pt(-0.31, -0.21))
        lion.lineTo(pt(-0.41, -0.23))
        lion.lineTo(pt(-0.40, -0.31))
        lion.lineTo(pt(-0.29, -0.36))
        lion.cubicTo(pt(-0.20, -0.40), pt(-0.13, -0.28), pt(-0.11, -0.14))
        lion.cubicTo(pt(0.03, -0.10), pt(0.19, -0.13), pt(0.32, -0.05))
        lion.cubicTo(pt(0.40, 0.07), pt(0.38, 0.25), pt(0.34, 0.43))
        lion.lineTo(pt(0.24, 0.43))
        lion.lineTo(pt(0.21, 0.16))
        lion.cubicTo(pt(0.08, 0.11), pt(-0.06, 0.14), pt(-0.15, 0.19))
        lion.lineTo(pt(-0.15, 0.43))
        lion.closeSubpath()

        arm_and_sword = QPainterPath()
        arm_and_sword.moveTo(pt(-0.27, -0.02))
        arm_and_sword.lineTo(pt(-0.45, -0.08))
        arm_and_sword.lineTo(pt(-0.43, -0.15))
        arm_and_sword.lineTo(pt(-0.25, -0.09))
        arm_and_sword.closeSubpath()

        arm_and_sword.moveTo(pt(-0.47, -0.05))
        arm_and_sword.cubicTo(pt(-0.54, -0.27), pt(-0.36, -0.47), pt(-0.09, -0.50))
        arm_and_sword.cubicTo(pt(-0.31, -0.43), pt(-0.46, -0.24), pt(-0.41, -0.06))
        arm_and_sword.closeSubpath()

        outline_pen = (
            QPen(QColor("#78350F"), max(0.55, u * 0.035), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            if r.height() >= 24
            else Qt.PenStyle.NoPen
        )
        p.setPen(outline_pen)
        p.setBrush(gold_grad)
        p.drawPath(lion)
        p.drawPath(arm_and_sword)

        tail = QPainterPath()
        tail.moveTo(pt(0.32, -0.03))
        tail.cubicTo(pt(0.51, -0.11), pt(0.48, -0.37), pt(0.28, -0.39))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#D97706"), max(1.0, u * 0.075), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(tail)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#B45309"))
        p.drawEllipse(pt(0.26, -0.39), max(0.8, u * 0.06), max(0.8, u * 0.045))

        p.setPen(QPen(QColor("#B45309"), max(0.9, u * 0.065), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(pt(-0.50, 0.45), pt(0.48, 0.45))

    @staticmethod
    def _draw_nordic(p: QPainter, r: QRectF, bg: str, cross: str):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRect(r)
        p.setBrush(QColor(cross))
        thick = r.height() * 0.22
        cx = r.x() + r.width() * 0.36
        p.drawRect(QRectF(cx - thick / 2, r.y(), thick, r.height()))
        p.drawRect(QRectF(r.x(), r.center().y() - thick / 2, r.width(), thick))

    @staticmethod
    def _draw_swiss(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#DA291C"))
        p.drawRect(r)
        p.setBrush(QColor("#FFFFFF"))
        arm_l = min(r.width(), r.height()) * 0.60
        arm_t = arm_l * 0.32
        cx, cy = r.center().x(), r.center().y()
        p.drawRect(QRectF(cx - arm_t / 2, cy - arm_l / 2, arm_t, arm_l))
        p.drawRect(QRectF(cx - arm_l / 2, cy - arm_t / 2, arm_l, arm_t))

    @staticmethod
    def _draw_turkey(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E30A17"))
        p.drawRect(r)
        cx, cy = r.x() + r.width() * 0.42, r.center().y()
        cr = r.height() * 0.26
        cres = QPainterPath()
        cres.addEllipse(QPointF(cx, cy), cr, cr)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + cr * 0.28, cy), cr * 0.80, cr * 0.80)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(cres.subtracted(cut))
        p.drawEllipse(QPointF(cx + cr * 1.02, cy), cr * 0.24, cr * 0.24)

    @staticmethod
    def _draw_uae(p: QPainter, r: QRectF):
        VectorFlagRenderer._draw_h3(p, r, "#00732F", "#FFFFFF", "#111111")
        p.setBrush(QColor("#FF0000"))
        p.drawRect(QRectF(r.x(), r.y(), r.width() * 0.26, r.height()))

    @staticmethod
    def _draw_japan(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        p.setBrush(QColor("#BC002D"))
        rad = min(r.width(), r.height()) * 0.29
        p.drawEllipse(r.center(), rad, rad)

    @staticmethod
    def _draw_usa(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        sh = r.height() / 7.0
        p.setBrush(QColor("#B22234"))
        for i in range(0, 7, 2):
            p.drawRect(QRectF(r.x(), r.y() + i * sh, r.width(), sh))
        cw, ch = r.width() * 0.44, sh * 4.0
        p.setBrush(QColor("#3C3B6E"))
        p.drawRect(QRectF(r.x(), r.y(), cw, ch))
        p.setBrush(QColor("#FFFFFF"))
        dot_r = max(0.7, r.height() * 0.025)
        for row in range(3):
            for col in range(4):
                px = r.x() + cw * (0.18 + col * 0.21)
                py = r.y() + ch * (0.22 + row * 0.28)
                p.drawEllipse(QPointF(px, py), dot_r, dot_r)

    @staticmethod
    def _draw_uk(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#012169"))
        p.drawRect(r)
        h = r.height()
        p.setPen(QPen(QColor("#FFFFFF"), h * 0.18))
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(QPen(QColor("#C8102E"), h * 0.08))
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(QRectF(r.center().x() - h * 0.16, r.y(), h * 0.32, h))
        p.drawRect(QRectF(r.x(), r.center().y() - h * 0.16, r.width(), h * 0.32))
        p.setBrush(QColor("#C8102E"))
        p.drawRect(QRectF(r.center().x() - h * 0.09, r.y(), h * 0.18, h))
        p.drawRect(QRectF(r.x(), r.center().y() - h * 0.09, r.width(), h * 0.18))

    @staticmethod
    def _draw_singapore(p: QPainter, r: QRectF):
        VectorFlagRenderer._draw_h2(p, r, "#EF3340", "#FFFFFF")
        cx, cy = r.x() + r.width() * 0.26, r.y() + r.height() * 0.25
        cr = r.height() * 0.16
        cres = QPainterPath()
        cres.addEllipse(QPointF(cx, cy), cr, cr)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + cr * 0.35, cy), cr * 0.85, cr * 0.85)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(cres.subtracted(cut))

    @staticmethod
    def _draw_canada(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        p.setBrush(QColor("#FF0000"))
        bw = r.width() * 0.25
        p.drawRect(QRectF(r.x(), r.y(), bw, r.height()))
        p.drawRect(QRectF(r.right() - bw, r.y(), bw, r.height()))
        cx, cy = r.center().x(), r.center().y()
        s = r.height() * 0.26
        leaf = QPainterPath()
        leaf.moveTo(cx, cy - s)
        leaf.lineTo(cx + s * 0.35, cy - s * 0.25)
        leaf.lineTo(cx + s * 0.85, cy - s * 0.20)
        leaf.lineTo(cx + s * 0.42, cy + s * 0.25)
        leaf.lineTo(cx + s * 0.12, cy + s * 0.25)
        leaf.lineTo(cx + s * 0.12, cy + s * 0.85)
        leaf.lineTo(cx - s * 0.12, cy + s * 0.85)
        leaf.lineTo(cx - s * 0.12, cy + s * 0.25)
        leaf.lineTo(cx - s * 0.42, cy + s * 0.25)
        leaf.lineTo(cx - s * 0.85, cy - s * 0.20)
        leaf.lineTo(cx - s * 0.35, cy - s * 0.25)
        leaf.closeSubpath()
        p.drawPath(leaf)

    @staticmethod
    def _draw_spain(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#AA151B"))
        p.drawRect(r)
        p.setBrush(QColor("#F1BF00"))
        p.drawRect(QRectF(r.x(), r.y() + r.height() * 0.25, r.width(), r.height() * 0.50))

    @staticmethod
    def _draw_india(p: QPainter, r: QRectF):
        VectorFlagRenderer._draw_h3(p, r, "#FF9933", "#FFFFFF", "#138808")
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#000080"), max(1.0, r.height() * 0.05)))
        rad = r.height() * 0.12
        p.drawEllipse(r.center(), rad, rad)

    @staticmethod
    def _draw_korea(p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        rad = min(r.width(), r.height()) * 0.25
        cx, cy = r.center().x(), r.center().y()
        top_half = QPainterPath()
        top_half.moveTo(cx, cy)
        top_half.arcTo(QRectF(cx - rad, cy - rad, rad * 2, rad * 2), 0, 180)
        top_half.closeSubpath()
        bot_half = QPainterPath()
        bot_half.moveTo(cx, cy)
        bot_half.arcTo(QRectF(cx - rad, cy - rad, rad * 2, rad * 2), 180, 180)
        bot_half.closeSubpath()
        p.setBrush(QColor("#CD2E3A"))
        p.drawPath(top_half)
        p.setBrush(QColor("#0047A0"))
        p.drawPath(bot_half)

    @staticmethod
    def _draw_global_edge(p: QPainter, r: QRectF):
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, QColor("#0F172A"))
        grad.setColorAt(1.0, QColor("#1E293B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(r)
        rad = min(r.width(), r.height()) * 0.34
        cx, cy = r.center().x(), r.center().y()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#FFD000"), max(1.1, r.height() * 0.06)))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.drawEllipse(QPointF(cx, cy), rad * 0.48, rad)
        p.drawLine(QPointF(cx - rad, cy), QPointF(cx + rad, cy))


def make_flag_qicon(code: str, width: int = 26, height: int = 18) -> QIcon:
    norm = str(code or "GLOBAL").strip().upper()
    key = (norm, width, height)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    dpr = 2.0
    pix = QPixmap(int(width * dpr), int(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    VectorFlagRenderer.draw_flag(
        painter,
        norm,
        QRectF(0.5, 0.5, width - 1.0, height - 1.0),
        radius=3.5,
        with_border=True,
    )
    painter.end()

    icon = QIcon(pix)
    _ICON_CACHE[key] = icon
    return icon


class FlagBadgeWidget(QWidget):
    def __init__(self, code: str = "GLOBAL", width: int = 30, height: int = 20, parent=None):
        super().__init__(parent)
        self._code = code
        lock_widget_dimensions(self, width, height)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def set_country_code(self, code: str):
        norm = str(code or "GLOBAL").strip().upper()
        if norm != self._code:
            self._code = norm
            spec = GeoFlagResolver.get_spec(norm)
            self.setToolTip(f"{spec.fa_name} ({spec.code})")
            self.update()

    def country_code(self) -> str:
        return self._code

    def paintEvent(self, _event):
        painter = QPainter(self)
        VectorFlagRenderer.draw_flag(
            painter,
            self._code,
            QRectF(0.8, 0.8, self.width() - 1.6, self.height() - 1.6),
            radius=4.5,
            with_border=True,
        )