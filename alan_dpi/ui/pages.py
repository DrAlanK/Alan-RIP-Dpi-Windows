import re
from pathlib import Path
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .animated_widgets import (
    ActionIconPillButton,
    AnimatedHeroConnectionCard,
    AnimatedToggleSwitch,
    CollapsibleAccordion,
    KineticConnectButton,
    LiveSparklineWidget,
    RadarShieldCore,
    SegmentedCapsuleBar,
    SimpleChronometerWidget,
    TaskProgressStrip,
    TunnelRouteBridgeWidget,
    VectorIconButton,
    VectorIconPainter,
)
from .flag_icons import FlagBadgeWidget, GeoFlagResolver, make_flag_qicon
from .theme import (
    DARK_PALETTE,
    ThemePalette,
    apply_windows_titlebar_theme,
    enforce_english_ltr,
    lock_widget_dimensions,
    make_transparent_scroll_area,
    make_ui_font,
    sanitize_ui_text,
)


def get_bool_value(mapping: dict, key: str, default: bool) -> bool:
    if not isinstance(mapping, dict):
        return default
    val = mapping.get(key, default)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
    return default


def parse_int_value(raw_val, default: int = 0) -> int:
    if raw_val is None:
        return default
    if isinstance(raw_val, bool):
        return int(raw_val)
    if isinstance(raw_val, int):
        return raw_val
    if isinstance(raw_val, float):
        return int(raw_val)
    txt = str(raw_val).strip()
    if not txt:
        return default
    try:
        return int(float(txt))
    except (ValueError, TypeError):
        return default


def parse_float_value(raw_val, default: float = 0.0) -> float:
    if raw_val is None:
        return default
    if isinstance(raw_val, bool):
        return float(int(raw_val))
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    txt = str(raw_val).strip()
    if not txt:
        return default
    try:
        return float(txt)
    except (ValueError, TypeError):
        return default


def pick_first_text(mapping: dict, keys: tuple[str, ...], default: str = "") -> str:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        val = mapping.get(key, None)
        if val is not None:
            txt = str(val).strip()
            if txt:
                return txt
    return default


def resolve_active_profile_index(
    items: list[dict],
    fallback_index: int = -1,
    active_uid: str = "",
) -> int:
    if not items:
        return -1

    for idx, item in enumerate(items):
        if isinstance(item, dict) and get_bool_value(item, "is_selected", False):
            return idx

    if active_uid:
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                uid_val = pick_first_text(item, ("uid", "profile_uid", "id"), "")
                if uid_val and (uid_val == active_uid):
                    return idx

    for idx, item in enumerate(items):
        if isinstance(item, dict):
            if get_bool_value(item, "selected", False):
                return idx
            if get_bool_value(item, "is_active", False):
                return idx
            if get_bool_value(item, "active", False):
                return idx

    if (fallback_index >= 0) and (fallback_index < len(items)):
        return fallback_index

    return -1


def format_rate_from_kbps(kbps: float) -> str:
    if kbps <= 0.0:
        return "0 B/s"
    if kbps >= 1024.0:
        return f"{kbps / 1024.0:.2f} MB/s"
    if kbps < 1.0:
        return f"{kbps * 1024.0:.0f} B/s"
    return f"{kbps:.1f} KB/s"


def extract_ip_candidate(text: str) -> str:
    if not text:
        return ""
    raw = str(text).strip()
    m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", raw)
    if m:
        return m.group(0)
    if (":" in raw) and (not raw.startswith("[")):
        return raw.split(":")[0].strip()
    return raw


def normalize_rank_text(rank_val) -> str:
    if rank_val is None:
        return ""
    raw = str(rank_val).strip()
    if not raw:
        return ""
    return raw if raw.startswith("#") else f"#{raw}"


class VectorGlyphWidget(QWidget):
    def __init__(self, icon_name: str, size: int = 20, use_accent: bool = True, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._use_accent = use_accent
        self._palette: ThemePalette = DARK_PALETTE
        lock_widget_dimensions(self, size, size)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        col = QColor(self._palette.accent_primary) if self._use_accent else QColor(self._palette.text_secondary)
        VectorIconPainter.draw_icon(
            painter,
            self._icon_name,
            QRectF(1, 1, self.width() - 2, self.height() - 2),
            col,
            1.75,
        )


class NativeThemedDialog(QDialog):
    def __init__(self, title: str, palette: ThemePalette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self.setObjectName("ThemedDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_titlebar_theme(self, self._palette.is_dark)


class AdminElevationDialog(NativeThemedDialog):
    def __init__(self, palette: ThemePalette, parent=None):
        super().__init__("نیاز به دسترسی Administrator", palette, parent)
        self.setMinimumSize(450, 210)
        self.resize(485, 225)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        title_lbl = QLabel("فعال‌سازی شبکه مجازی کل سیستم (TUN)")
        title_lbl.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        layout.addWidget(title_lbl)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)
        glyph = VectorGlyphWidget("tun_shield", size=38, use_accent=True)
        glyph.set_palette_theme(palette)

        desc = QLabel(
            "برای ساخت کارت شبکه مجازی TUN و هدایت تمام ترافیک سیستم‌عامل از تونل امن، "
            "برنامه باید با دسترسی Administrator ویندوز اجرا شود."
        )
        desc.setObjectName("SecondaryLabel")
        desc.setWordWrap(True)

        mid_row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        mid_row.addWidget(desc, 1)
        layout.addLayout(mid_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("انصراف")
        cancel_btn.setObjectName("GhostPillBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        elevate_btn = QPushButton("اجرای مجدد با دسترسی Administrator")
        elevate_btn.setObjectName("AccentBtn")
        elevate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        elevate_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(elevate_btn)
        layout.addStretch()
        layout.addLayout(btn_row)


class RenameProfileDialog(NativeThemedDialog):
    def __init__(self, current_name: str, palette: ThemePalette, parent=None):
        super().__init__("تغییر نام کانفیگ", palette, parent)
        self.setMinimumSize(380, 165)
        self.resize(420, 175)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        lbl = QLabel("نام جدید پروفایل را وارد کنید:")
        lbl.setFont(make_ui_font(11, QFont.Weight.Bold))
        layout.addWidget(lbl)

        self.name_edit = QLineEdit(current_name)
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.setObjectName("GhostPillBtn")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("ذخیره نام")
        save_btn.setObjectName("AccentBtn")
        save_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addStretch()
        layout.addLayout(btn_row)

    def new_name(self) -> str:
        return self.name_edit.text().strip()


class ConfirmClearAllDialog(NativeThemedDialog):
    def __init__(self, count: int, palette: ThemePalette, parent=None):
        super().__init__("حذف کل کانفیگ‌ها", palette, parent)
        self.setMinimumSize(440, 210)
        self.resize(470, 225)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        hdr = QLabel("تایید دو مرحله‌ای تخلیه مخزن")
        hdr.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        layout.addWidget(hdr)

        desc = QLabel(
            f"شما در حال حذف دائمی تمام {count} کانفیگ موجود در مخزن هستید. این عملیات قابل بازگشت نیست."
        )
        desc.setObjectName("SecondaryLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.confirm_chk = QCheckBox("تایید می‌کنم که تمام کانفیگ‌های مخزن به صورت کامل پاک شوند.")
        layout.addWidget(self.confirm_chk)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.setObjectName("GhostPillBtn")
        cancel_btn.clicked.connect(self.reject)

        self.delete_btn = QPushButton("حذف قطعی کل کانفیگ‌ها")
        self.delete_btn.setObjectName("DangerSolidBtn")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.accept)
        self.confirm_chk.toggled.connect(self.delete_btn.setEnabled)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.delete_btn)
        layout.addStretch()
        layout.addLayout(btn_row)


class ConfigEditorDialog(NativeThemedDialog):
    def __init__(
        self,
        index: int,
        initial_data: dict | None,
        vectors: list | None,
        palette: ThemePalette,
        parent=None,
    ):
        title_str = "افزودن دستی کانفیگ جدید" if (index < 0) else "ویرایش کامل کانفیگ"
        super().__init__(title_str, palette, parent)
        self._index = index
        self._initial = dict(initial_data) if isinstance(initial_data, dict) else {}

        self.setMinimumSize(700, 540)
        self.resize(790, 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(12)

        top_row = QHBoxLayout()
        hdr_lbl = QLabel(title_str)
        hdr_lbl.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        self.preview_flag = FlagBadgeWidget(GeoFlagResolver.resolve_code(self._initial), width=32, height=21)
        top_row.addWidget(hdr_lbl)
        top_row.addStretch()
        top_row.addWidget(self.preview_flag)
        root.addLayout(top_row)

        form_host = QWidget()
        form_vbox = QVBoxLayout(form_host)
        form_vbox.setContentsMargins(2, 2, 6, 6)
        form_vbox.setSpacing(12)

        self.fields_card = QFrame()
        self.fields_card.setObjectName("GlassCard")
        grid = QGridLayout(self.fields_card)
        grid.setContentsMargins(16, 14, 16, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        self.name_edit = QLineEdit(pick_first_text(self._initial, ("name", "title"), ""))
        self.name_edit.setPlaceholderText("مثلاً DE Direct-German")
        self.name_edit.textChanged.connect(self._update_flag_preview)

        self.protocol_combo = QComboBox()
        for proto in ("vless", "vmess", "trojan", "ss"):
            self.protocol_combo.addItem(proto.upper(), proto)
        enforce_english_ltr(self.protocol_combo, mono_size=10, bold=True)

        init_addr = pick_first_text(self._initial, ("host", "original_host", "address"), "")
        self.address_edit = QLineEdit(init_addr)
        self.address_edit.setPlaceholderText("104.18.36.214 / domain.com")
        enforce_english_ltr(self.address_edit, mono_size=10)
        self.address_edit.textChanged.connect(self._update_flag_preview)

        init_port = parse_int_value(self._initial.get("port", 443), 443)
        if (init_port < 1) or (init_port > 65535):
            init_port = 443
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(init_port)
        enforce_english_ltr(self.port_spin, mono_size=10)

        cred_val = pick_first_text(self._initial, ("uuid_or_password", "uuid", "password"), "")
        self.uuid_edit = QLineEdit(cred_val)
        self.uuid_edit.setPlaceholderText("UUID / Trojan or SS Password")
        enforce_english_ltr(self.uuid_edit, mono_size=10)

        self.vector_combo = QComboBox()
        enforce_english_ltr(self.vector_combo, mono_size=10, bold=True)
        self._populate_vectors(vectors if isinstance(vectors, list) else [])

        self.network_combo = QComboBox()
        for net in ("ws", "tcp", "grpc", "httpupgrade"):
            self.network_combo.addItem(net, net)
        enforce_english_ltr(self.network_combo, mono_size=10)

        self.security_combo = QComboBox()
        for sec in ("tls", "reality", "none"):
            self.security_combo.addItem(sec, sec)
        enforce_english_ltr(self.security_combo, mono_size=10)

        self.sni_edit = QLineEdit(pick_first_text(self._initial, ("sni", "server_name"), ""))
        self.sni_edit.setPlaceholderText("sni.example.com")
        enforce_english_ltr(self.sni_edit, mono_size=10)
        self.sni_edit.textChanged.connect(self._update_flag_preview)

        self.host_edit = QLineEdit(pick_first_text(self._initial, ("host_header",), ""))
        self.host_edit.setPlaceholderText("cdn.example.com")
        enforce_english_ltr(self.host_edit, mono_size=10)

        self.path_edit = QLineEdit(pick_first_text(self._initial, ("path", "service_name"), "/"))
        self.path_edit.setPlaceholderText("/ws or grpc-service")
        enforce_english_ltr(self.path_edit, mono_size=10)

        self.alpn_combo = QComboBox()
        self.alpn_combo.setEditable(True)
        for alpn_opt in ("", "http/1.1", "h2,http/1.1", "h2"):
            self.alpn_combo.addItem(alpn_opt)
        enforce_english_ltr(self.alpn_combo, mono_size=10)

        self.fp_combo = QComboBox()
        self.fp_combo.setEditable(True)
        for fp_opt in ("chrome", "safari", "firefox", "ios", "edge", "randomized", ""):
            self.fp_combo.addItem(fp_opt)
        enforce_english_ltr(self.fp_combo, mono_size=10)

        self.flow_combo = QComboBox()
        self.flow_combo.setEditable(True)
        for fl_opt in ("", "xtls-rprx-vision"):
            self.flow_combo.addItem(fl_opt)
        enforce_english_ltr(self.flow_combo, mono_size=10)

        pbk_val = pick_first_text(self._initial, ("public_key", "pbk"), "")
        self.pbk_edit = QLineEdit(pbk_val)
        self.pbk_edit.setPlaceholderText("Reality PublicKey (pbk)")
        enforce_english_ltr(self.pbk_edit, mono_size=10)

        sid_val = pick_first_text(self._initial, ("short_id", "sid"), "")
        self.sid_edit = QLineEdit(sid_val)
        self.sid_edit.setPlaceholderText("Reality ShortId (sid)")
        enforce_english_ltr(self.sid_edit, mono_size=10)

        spec = [
            ("نام کانفیگ:", self.name_edit, 0, 0),
            ("پروتکل (Protocol):", self.protocol_combo, 0, 1),
            ("آدرس سرور / IP:", self.address_edit, 1, 0),
            ("پورت (Port):", self.port_spin, 1, 1),
            ("شناسه UUID / Password:", self.uuid_edit, 2, 0),
            ("متد عبوری مقیدشده:", self.vector_combo, 2, 1),
            ("شبکه انتقال (Network):", self.network_combo, 3, 0),
            ("لایه امنیت (Security):", self.security_combo, 3, 1),
            ("دامنه SNI:", self.sni_edit, 4, 0),
            ("هدر Host:", self.host_edit, 4, 1),
            ("مسیر Path / ServiceName:", self.path_edit, 5, 0),
            ("مقدار ALPN:", self.alpn_combo, 5, 1),
            ("اثرانگشت (Fingerprint):", self.fp_combo, 6, 0),
            ("جریان (Flow):", self.flow_combo, 6, 1),
            ("کلید عمومی (PublicKey / pbk):", self.pbk_edit, 7, 0),
            ("شناسه کوتاه (ShortId / sid):", self.sid_edit, 7, 1),
        ]

        for label_text, widget, r, c in spec:
            lbl = QLabel(label_text)
            lbl.setObjectName("SecondaryLabel")
            grid.addWidget(lbl, r * 2, c)
            grid.addWidget(widget, r * 2 + 1, c)

        form_vbox.addWidget(self.fields_card)

        raw_card = QFrame()
        raw_card.setObjectName("SubtleCard")
        raw_vbox = QVBoxLayout(raw_card)
        raw_vbox.setContentsMargins(16, 12, 16, 14)
        raw_vbox.setSpacing(8)

        raw_top = QHBoxLayout()
        raw_lbl = QLabel("لینک خام کانفیگ (Raw URI):")
        raw_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))

        sw_lbl = QLabel("ویرایش مستقیم از روی لینک خام")
        sw_lbl.setObjectName("SecondaryLabel")
        self.sw_use_raw = AnimatedToggleSwitch(checked=get_bool_value(self._initial, "use_raw_uri", False))
        self.sw_use_raw.set_palette_theme(palette)
        self.sw_use_raw.toggled.connect(self._sync_raw_mode)

        raw_top.addWidget(raw_lbl)
        raw_top.addStretch()
        raw_top.addWidget(sw_lbl)
        raw_top.addWidget(self.sw_use_raw)
        raw_vbox.addLayout(raw_top)

        raw_uri_str = pick_first_text(self._initial, ("raw_uri", "uri"), "")
        self.raw_uri_edit = QPlainTextEdit(raw_uri_str)
        self.raw_uri_edit.setObjectName("RawUriEdit")
        self.raw_uri_edit.setPlaceholderText("vless://uuid@host:443?security=tls&type=ws#Title")
        self.raw_uri_edit.setMinimumHeight(74)
        self.raw_uri_edit.setMaximumHeight(110)
        enforce_english_ltr(self.raw_uri_edit, mono_size=10)
        raw_vbox.addWidget(self.raw_uri_edit)

        form_vbox.addWidget(raw_card)
        form_vbox.addStretch()

        scroll = make_transparent_scroll_area(form_host)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.setObjectName("GhostPillBtn")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("ذخیره تغییرات")
        save_btn.setObjectName("AccentBtn")
        save_btn.clicked.connect(self.accept)

        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        self._apply_initial_selections()
        self._sync_raw_mode(self.sw_use_raw.isChecked())

    def _update_flag_preview(self):
        code = GeoFlagResolver.resolve_code(
            self.name_edit.text(),
            self.sni_edit.text(),
            self.address_edit.text(),
        )
        self.preview_flag.set_country_code(code)

    def _populate_vectors(self, vectors: list):
        self.vector_combo.clear()
        self.vector_combo.addItem("AUTO", "AUTO")
        seen = {"AUTO"}
        for item in vectors:
            if isinstance(item, dict):
                vid = pick_first_text(item, ("id", "vector_id", "code"), "")
                vname = sanitize_ui_text(pick_first_text(item, ("name", "title"), ""))
            else:
                vid = str(item).strip()
                vname = ""
            if vid and (vid not in seen):
                seen.add(vid)
                caption = f"{vid} | {vname}" if (vname and (vname != vid)) else vid
                self.vector_combo.addItem(caption, vid)

        for i in range(1, 17):
            code = f"VEC-{i:02d}"
            if code not in seen:
                seen.add(code)
                self.vector_combo.addItem(code, code)

    def _apply_initial_selections(self):
        proto = pick_first_text(self._initial, ("protocol",), "vless").lower()
        p_idx = self.protocol_combo.findData(proto)
        if p_idx >= 0:
            self.protocol_combo.setCurrentIndex(p_idx)

        net = pick_first_text(self._initial, ("network",), "ws").lower()
        n_idx = self.network_combo.findData(net)
        if n_idx >= 0:
            self.network_combo.setCurrentIndex(n_idx)

        sec = pick_first_text(self._initial, ("security",), "tls").lower()
        s_idx = self.security_combo.findData(sec)
        if s_idx >= 0:
            self.security_combo.setCurrentIndex(s_idx)

        pref_vec = pick_first_text(self._initial, ("preferred_vector_id", "cached_vector_id"), "AUTO")
        v_idx = self.vector_combo.findData(pref_vec)
        if v_idx >= 0:
            self.vector_combo.setCurrentIndex(v_idx)

        self.alpn_combo.setCurrentText(pick_first_text(self._initial, ("alpn",), ""))
        self.fp_combo.setCurrentText(pick_first_text(self._initial, ("fingerprint",), "chrome"))
        self.flow_combo.setCurrentText(pick_first_text(self._initial, ("flow",), ""))

    def _sync_raw_mode(self, use_raw: bool):
        self.fields_card.setEnabled(not use_raw)
        self.raw_uri_edit.setReadOnly(not use_raw)

    def collect_data(self) -> dict:
        out = dict(self._initial)
        name_txt = self.name_edit.text().strip()
        if not name_txt:
            name_txt = "Alan Profile"
        addr_txt = self.address_edit.text().strip()
        pbk_txt = self.pbk_edit.text().strip()
        sid_txt = self.sid_edit.text().strip()
        raw_txt = self.raw_uri_edit.toPlainText().strip()
        vec_data = self.vector_combo.currentData()
        pref_vec = str(vec_data) if (vec_data is not None and str(vec_data).strip()) else "AUTO"
        proto_data = self.protocol_combo.currentData()
        net_data = self.network_combo.currentData()
        sec_data = self.security_combo.currentData()

        out.update(
            {
                "name": name_txt,
                "protocol": str(proto_data) if proto_data is not None else "vless",
                "host": addr_txt,
                "address": addr_txt,
                "port": int(self.port_spin.value()),
                "uuid_or_password": self.uuid_edit.text().strip(),
                "network": str(net_data) if net_data is not None else "ws",
                "security": str(sec_data) if sec_data is not None else "tls",
                "sni": self.sni_edit.text().strip(),
                "host_header": self.host_edit.text().strip(),
                "path": self.path_edit.text().strip(),
                "alpn": self.alpn_combo.currentText().strip(),
                "fingerprint": self.fp_combo.currentText().strip(),
                "flow": self.flow_combo.currentText().strip(),
                "public_key": pbk_txt,
                "pbk": pbk_txt,
                "short_id": sid_txt,
                "sid": sid_txt,
                "preferred_vector_id": pref_vec,
                "raw_uri": raw_txt,
                "uri": raw_txt,
                "use_raw_uri": bool(self.sw_use_raw.isChecked()),
            }
        )
        return out


class TelemetryGlassCard(QFrame):
    def __init__(
        self,
        title: str,
        icon_name: str,
        with_sparkline: bool = True,
        white_tint: bool = False,
        with_flag: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.setMinimumHeight(114)
        self._white_tint = white_tint

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.icon_widget = VectorGlyphWidget(icon_name, size=18, use_accent=not white_tint)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("MutedLabel")
        self.title_lbl.setFont(make_ui_font(9, QFont.Weight.DemiBold))
        top_row.addWidget(self.icon_widget)
        top_row.addWidget(self.title_lbl)
        top_row.addStretch()

        self.flag_badge: FlagBadgeWidget | None = None
        if with_flag:
            self.flag_badge = FlagBadgeWidget("GLOBAL", width=26, height=17)
            top_row.addWidget(self.flag_badge)

        self.value_lbl = QLabel("—")
        enforce_english_ltr(self.value_lbl, mono_size=13, bold=True)
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(top_row)
        layout.addWidget(self.value_lbl)

        self.sparkline = None
        self.sub_lbl = None
        if with_sparkline:
            self.sparkline = LiveSparklineWidget()
            layout.addWidget(self.sparkline)
        else:
            self.sub_lbl = QLabel("آماده دریافت مسیر")
            self.sub_lbl.setObjectName("MutedLabel")
            self.sub_lbl.setFont(make_ui_font(9, QFont.Weight.Medium))
            layout.addStretch()
            layout.addWidget(self.sub_lbl)

    def set_country_info(self, code: str, is_connected: bool):
        spec = GeoFlagResolver.get_spec(code)
        if self.flag_badge is not None:
            self.flag_badge.set_country_code(spec.code)
        if self.sub_lbl is not None:
            if is_connected:
                self.sub_lbl.setText(f"خروجی: {spec.fa_name} | مسیر امن فعال")
            else:
                self.sub_lbl.setText(f"مقصد انتخابی: {spec.fa_name}")

    def set_palette_theme(self, palette: ThemePalette):
        self.icon_widget.set_palette_theme(palette)
        if self.sparkline:
            self.sparkline.set_palette_theme(palette, secondary_tint=self._white_tint)


class HomePage(QWidget):
    connect_toggled = Signal()
    quick_paste_clicked = Signal()
    hunt_best_requested = Signal()
    profile_selected = Signal(int)
    quick_setting_changed = Signal(dict)
    tun_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._ui_phase = "IDLE"
        self._is_connected = False
        self._profiles_list: list[dict] = []
        self._active_profile_idx = -1
        self._active_profile_uid = ""
        self._last_egress_ip = ""
        self._last_ping_ms = 0
        self._last_snap: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("PillBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 8, 14, 8)
        top_layout.setSpacing(10)

        prof_lbl = QLabel("پروفایل فعال:")
        prof_lbl.setObjectName("SecondaryLabel")
        prof_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(210)
        self.profile_combo.setIconSize(QSize(24, 16))
        self.profile_combo.setFont(make_ui_font(10, QFont.Weight.DemiBold))
        self.profile_combo.currentIndexChanged.connect(self._on_combo_changed)

        self.quick_paste_btn = QPushButton("افزودن از کلیپ‌بورد")
        self.quick_paste_btn.setObjectName("GhostPillBtn")
        self.quick_paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_paste_btn.clicked.connect(self.quick_paste_clicked.emit)

        self.hunt_best_btn = ActionIconPillButton(
            "hunter",
            "شکار برترین کانفیگ مخزن و اتصال",
            golden=True,
        )
        self.hunt_best_btn.clicked.connect(self.hunt_best_requested.emit)

        self.live_pill_lbl = QLabel("STANDBY")
        self.live_pill_lbl.setObjectName("PhaseStandby")
        enforce_english_ltr(self.live_pill_lbl, mono_size=10, bold=True)

        top_layout.addWidget(prof_lbl)
        top_layout.addWidget(self.profile_combo, 1)
        top_layout.addWidget(self.quick_paste_btn)
        top_layout.addWidget(self.hunt_best_btn)
        top_layout.addWidget(self.live_pill_lbl)
        root.addWidget(top_bar)

        self.hero_card = AnimatedHeroConnectionCard()
        hero_vbox = QVBoxLayout(self.hero_card)
        hero_vbox.setContentsMargins(26, 20, 26, 18)
        hero_vbox.setSpacing(14)

        upper_hero = QHBoxLayout()
        upper_hero.setSpacing(26)

        self.radar_core = RadarShieldCore()
        self.radar_core.clicked.connect(self.connect_toggled.emit)

        status_col = QVBoxLayout()
        status_col.setSpacing(10)
        status_col.addStretch()

        headline_row = QHBoxLayout()
        headline_row.setSpacing(12)

        self.headline_lbl = QLabel("آماده اتصال")
        self.headline_lbl.setObjectName("HeadlineLabel")
        self.headline_lbl.setFont(make_ui_font(21, QFont.Weight.ExtraBold))

        self.dest_pill_frame = QFrame()
        self.dest_pill_frame.setObjectName("SubtleCard")
        dp_row = QHBoxLayout(self.dest_pill_frame)
        dp_row.setContentsMargins(10, 4, 10, 4)
        dp_row.setSpacing(8)
        self.dest_flag_badge = FlagBadgeWidget("GLOBAL", width=28, height=18)
        self.dest_country_lbl = QLabel("مسیر جهانی")
        self.dest_country_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))
        dp_row.addWidget(self.dest_flag_badge)
        dp_row.addWidget(self.dest_country_lbl)

        headline_row.addWidget(self.headline_lbl)
        headline_row.addWidget(self.dest_pill_frame)
        headline_row.addStretch()

        self.detail_lbl = QLabel("موتور هوشمند آماده برقراری تونل امن و یافتن تمیزترین مسیر عبوری است.")
        self.detail_lbl.setObjectName("SecondaryLabel")
        self.detail_lbl.setFont(make_ui_font(11, QFont.Weight.Medium))
        self.detail_lbl.setWordWrap(True)

        self.scan_progress = QProgressBar()
        self.scan_progress.setObjectName("GoldProgress")
        self.scan_progress.setMinimumHeight(7)
        self.scan_progress.setMaximumHeight(8)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        enforce_english_ltr(self.scan_progress, mono_size=9)
        self.scan_progress.hide()

        action_row = QHBoxLayout()
        action_row.setSpacing(14)

        self.connect_btn = KineticConnectButton()
        self.connect_btn.clicked.connect(self.connect_toggled.emit)

        self.chronometer = SimpleChronometerWidget()

        action_row.addWidget(self.connect_btn)
        action_row.addWidget(self.chronometer)
        action_row.addStretch()

        status_col.addLayout(headline_row)
        status_col.addWidget(self.detail_lbl)
        status_col.addWidget(self.scan_progress)
        status_col.addSpacing(2)
        status_col.addLayout(action_row)
        status_col.addStretch()

        upper_hero.addWidget(self.radar_core, 0, Qt.AlignmentFlag.AlignVCenter)
        upper_hero.addLayout(status_col, 1)

        self.route_bridge = TunnelRouteBridgeWidget()

        hero_vbox.addLayout(upper_hero, 1)
        hero_vbox.addWidget(self.route_bridge)
        root.addWidget(self.hero_card, 1)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.ip_card = TelemetryGlassCard(
            "آدرس IP خروجی",
            "ip_globe",
            with_sparkline=False,
            with_flag=True,
        )
        self.rx_card = TelemetryGlassCard("سرعت دانلود", "download", with_sparkline=True, white_tint=False)
        self.tx_card = TelemetryGlassCard("سرعت آپلود", "upload", with_sparkline=True, white_tint=True)
        self.ping_card = TelemetryGlassCard("پینگ و پایداری", "wave", with_sparkline=True, white_tint=False)

        self.rx_card.value_lbl.setText("0 B/s")
        self.tx_card.value_lbl.setText("0 B/s")

        cards_row.addWidget(self.ip_card, 1)
        cards_row.addWidget(self.rx_card, 1)
        cards_row.addWidget(self.tx_card, 1)
        cards_row.addWidget(self.ping_card, 1)
        root.addLayout(cards_row)

        bottom_strip = QFrame()
        bottom_strip.setObjectName("PillBar")
        bot_layout = QHBoxLayout(bottom_strip)
        bot_layout.setContentsMargins(14, 9, 14, 9)
        bot_layout.setSpacing(10)

        self.sys_proxy_switch = AnimatedToggleSwitch(checked=True)
        self.sys_proxy_switch.toggled.connect(self._emit_quick_settings)
        lbl_proxy = QLabel("پروکسی سیستم ویندوز")
        lbl_proxy.setObjectName("SecondaryLabel")

        self.autopilot_switch = AnimatedToggleSwitch(checked=True)
        self.autopilot_switch.toggled.connect(self._emit_quick_settings)
        lbl_auto = QLabel("اتصال هوشمند AutoPilot")
        lbl_auto.setObjectName("SecondaryLabel")

        self.tun_switch = AnimatedToggleSwitch(checked=False)
        self.tun_switch.toggled.connect(self.tun_toggled.emit)
        lbl_tun = QLabel("شبکه مجازی کل سیستم (TUN)")
        lbl_tun.setObjectName("SecondaryLabel")

        self.tun_status_pill = QLabel("TUN OFF")
        self.tun_status_pill.setObjectName("TunOffPill")
        enforce_english_ltr(self.tun_status_pill, mono_size=9, bold=True)

        self.vector_badge = QLabel("AUTO-HYBRID")
        self.vector_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.vector_badge, mono_size=10, bold=True)

        bot_layout.addWidget(self.sys_proxy_switch)
        bot_layout.addWidget(lbl_proxy)
        bot_layout.addSpacing(8)
        bot_layout.addWidget(self.autopilot_switch)
        bot_layout.addWidget(lbl_auto)
        bot_layout.addSpacing(8)
        bot_layout.addWidget(self.tun_switch)
        bot_layout.addWidget(lbl_tun)
        bot_layout.addWidget(self.tun_status_pill)
        bot_layout.addStretch()

        vec_caption = QLabel("هسته:")
        vec_caption.setObjectName("MutedLabel")
        bot_layout.addWidget(vec_caption)
        bot_layout.addWidget(self.vector_badge)

        root.addWidget(bottom_strip)
        self._refresh_geo_visuals()

    def _resolve_active_country(self) -> str:
        if self._is_connected and bool(self._last_snap):
            snap_code = GeoFlagResolver.resolve_code(self._last_snap)
            if snap_code != "GLOBAL":
                return snap_code

        if (self._active_profile_idx >= 0) and (self._active_profile_idx < len(self._profiles_list)):
            prof_code = GeoFlagResolver.resolve_code(self._profiles_list[self._active_profile_idx])
            if prof_code != "GLOBAL":
                return prof_code

        if self._last_snap:
            return GeoFlagResolver.resolve_code(self._last_snap)
        return "GLOBAL"

    def _refresh_geo_visuals(self):
        code = self._resolve_active_country()
        spec = GeoFlagResolver.get_spec(code)

        self.hero_card.set_visual_context(spec.code, self._ui_phase)
        self.radar_core.set_country_code(spec.code)
        self.dest_flag_badge.set_country_code(spec.code)
        self.dest_country_lbl.setText(f"{spec.fa_name}  |  {spec.code}")
        self.route_bridge.set_route_state(
            spec.code,
            self._last_egress_ip,
            self._last_ping_ms,
            self._ui_phase,
        )
        self.ip_card.set_country_info(spec.code, self._is_connected)

    def _on_combo_changed(self, idx: int):
        if idx >= 0:
            self._active_profile_idx = idx
            if idx < len(self._profiles_list):
                self._active_profile_uid = pick_first_text(
                    self._profiles_list[idx],
                    ("uid", "profile_uid", "id"),
                    "",
                )
            self._refresh_geo_visuals()
            self.profile_selected.emit(idx)

    def _emit_quick_settings(self):
        self.quick_setting_changed.emit(
            {
                "system_proxy": self.sys_proxy_switch.isChecked(),
                "autopilot": self.autopilot_switch.isChecked(),
            }
        )

    def set_tun_switch_silent(self, checked: bool):
        self.tun_switch.set_CheckedSilent(bool(checked))

    def apply_tun_status(self, active: bool, detail: str = ""):
        self.tun_switch.set_CheckedSilent(bool(active))
        self.tun_status_pill.setText("TUN ACTIVE" if active else "TUN OFF")
        target_obj = "TunActivePill" if active else "TunOffPill"
        if self.tun_status_pill.objectName() != target_obj:
            self.tun_status_pill.setObjectName(target_obj)
            self.tun_status_pill.style().unpolish(self.tun_status_pill)
            self.tun_status_pill.style().polish(self.tun_status_pill)
        if detail:
            self.tun_status_pill.setToolTip(sanitize_ui_text(detail))

    def sync_switches(self, settings: dict):
        if "system_proxy" in settings:
            self.sys_proxy_switch.set_CheckedSilent(get_bool_value(settings, "system_proxy", True))
        elif "enable_system_proxy" in settings:
            self.sys_proxy_switch.set_CheckedSilent(get_bool_value(settings, "enable_system_proxy", True))

        if "autopilot" in settings:
            self.autopilot_switch.set_CheckedSilent(get_bool_value(settings, "autopilot", True))
        elif "auto_pilot" in settings:
            self.autopilot_switch.set_CheckedSilent(get_bool_value(settings, "auto_pilot", True))

        if "tun_enabled" in settings:
            self.apply_tun_status(get_bool_value(settings, "tun_enabled", False))

    def set_selected_profile_silent(self, selected_index: int = -1, active_uid: str = ""):
        if active_uid:
            self._active_profile_uid = active_uid
        if not self._profiles_list:
            if selected_index >= 0:
                self._active_profile_idx = selected_index
            return

        target_idx = -1
        if self._active_profile_uid:
            for idx, item in enumerate(self._profiles_list):
                uid_val = pick_first_text(item, ("uid", "profile_uid", "id"), "")
                if uid_val and (uid_val == self._active_profile_uid):
                    target_idx = idx
                    break

        if (target_idx < 0) and (selected_index >= 0) and (selected_index < len(self._profiles_list)):
            target_idx = selected_index

        if (target_idx >= 0) and (target_idx != self.profile_combo.currentIndex()):
            self._active_profile_idx = target_idx
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(target_idx)
            self.profile_combo.blockSignals(False)
            self._refresh_geo_visuals()

    def set_profiles(self, items: list[dict], active_index: int = -1, active_uid: str = ""):
        self._profiles_list = list(items) if isinstance(items, list) else []
        if active_uid:
            self._active_profile_uid = active_uid

        resolved_idx = resolve_active_profile_index(
            self._profiles_list,
            fallback_index=active_index,
            active_uid=self._active_profile_uid,
        )
        if (resolved_idx < 0) and (self._active_profile_idx >= 0) and (self._active_profile_idx < len(self._profiles_list)):
            resolved_idx = self._active_profile_idx

        self._active_profile_idx = resolved_idx

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for idx, item in enumerate(self._profiles_list):
            raw_name = sanitize_ui_text(pick_first_text(item, ("name", "title"), f"Profile #{idx + 1}"))
            clean_name = GeoFlagResolver.clean_display_name(raw_name)
            if not clean_name:
                clean_name = raw_name
            code = GeoFlagResolver.resolve_code(item)
            proto = pick_first_text(item, ("protocol",), "PROXY").upper()
            self.profile_combo.addItem(make_flag_qicon(code, 26, 18), f"{clean_name}  [{proto}]")

        if (resolved_idx >= 0) and (resolved_idx < len(self._profiles_list)):
            self.profile_combo.setCurrentIndex(resolved_idx)
        else:
            self.profile_combo.setCurrentIndex(-1)
        self.profile_combo.blockSignals(False)
        self._refresh_geo_visuals()

    def _resolve_phase(self, snap: dict) -> tuple[str, bool, bool]:
        raw_phase = pick_first_text(snap, ("ui_phase",), "").upper()
        raw_state = pick_first_text(snap, ("state",), "disconnected").lower()

        default_connecting = (raw_phase == "CONNECTING") or (
            raw_state in ("connecting", "scanning", "probing", "reconnecting", "starting")
        )
        default_connected = (raw_phase == "CONNECTED") or (
            raw_state in ("connected", "active", "online", "protected")
        )

        is_connecting = get_bool_value(snap, "is_connecting", default_connecting)
        is_connected = get_bool_value(snap, "is_connected", default_connected)

        if is_connecting:
            phase = "CONNECTING"
        elif is_connected:
            phase = "CONNECTED"
        elif (raw_phase == "ERROR") or (raw_state in ("error", "failed")):
            phase = "ERROR"
        else:
            phase = "IDLE"
        return phase, is_connecting, is_connected

    def _set_badge_style(self, text: str, obj_name: str):
        self.live_pill_lbl.setText(text)
        if self.live_pill_lbl.objectName() != obj_name:
            self.live_pill_lbl.setObjectName(obj_name)
            self.live_pill_lbl.style().unpolish(self.live_pill_lbl)
            self.live_pill_lbl.style().polish(self.live_pill_lbl)

    def apply_telemetry(self, snap: dict):
        self._last_snap = dict(snap)

        snap_uid = pick_first_text(snap, ("active_profile_uid",), "")
        snap_sel_raw = snap.get("selected_index", None)
        snap_sel_idx = parse_int_value(snap_sel_raw, -1) if (snap_sel_raw is not None) else -1
        if (snap_sel_idx >= 0) or bool(snap_uid):
            self.set_selected_profile_silent(snap_sel_idx, snap_uid)

        phase, is_connecting, is_connected = self._resolve_phase(snap)
        self._ui_phase = phase
        self._is_connected = is_connected

        btn_text = sanitize_ui_text(pick_first_text(snap, ("button_text",), ""))
        self.radar_core.set_ui_phase(phase)
        self.connect_btn.set_phase_and_label(phase, btn_text)

        uptime_label = pick_first_text(snap, ("uptime_label",), "00:00:00")
        self.chronometer.set_uptime_state(uptime_label, is_connected)

        default_headline = (
            "در حال یافتن بهترین مسیر..."
            if is_connecting
            else ("متصل است" if is_connected else "آماده اتصال")
        )
        headline = sanitize_ui_text(pick_first_text(snap, ("status_headline",), default_headline))
        default_detail = "" if is_connected else "موتور هوشمند آماده برقراری تونل امن است."
        detail = sanitize_ui_text(pick_first_text(snap, ("status_detail",), default_detail))
        self.headline_lbl.setText(headline)
        self.detail_lbl.setText(detail)

        prog = parse_int_value(snap.get("progress_percent", 0), 0)
        if is_connecting:
            self.scan_progress.show()
            self.scan_progress.setValue(max(5, prog))
            self._set_badge_style("PROBING...", "PhaseProbing")
        elif is_connected:
            self.scan_progress.hide()
            self._set_badge_style("ONLINE", "PhaseOnline")
        elif phase == "ERROR":
            self.scan_progress.hide()
            self._set_badge_style("ERROR", "PhaseError")
        else:
            self.scan_progress.hide()
            self._set_badge_style("STANDBY", "PhaseStandby")

        egress = pick_first_text(snap, ("egress_ip",), "—") if is_connected else "—"
        self._last_egress_ip = egress if (is_connected and (egress != "—")) else ""
        self.ip_card.value_lbl.setText(egress)

        rx_kbps = parse_float_value(snap.get("rx_rate_kbps", 0.0), 0.0) if is_connected else 0.0
        tx_kbps = parse_float_value(snap.get("tx_rate_kbps", 0.0), 0.0) if is_connected else 0.0
        ping = parse_int_value(snap.get("ping_ms", 0), 0) if is_connected else 0
        self._last_ping_ms = ping

        rx_label = pick_first_text(snap, ("rx_rate_label",), "")
        tx_label = pick_first_text(snap, ("tx_rate_label",), "")

        if (not is_connected) or (rx_kbps <= 0.0):
            rx_display = rx_label if (is_connected and bool(rx_label)) else "0 B/s"
            self.rx_card.sparkline.reset_flat()
        else:
            rx_display = rx_label if rx_label else format_rate_from_kbps(rx_kbps)
            self.rx_card.sparkline.push_sample(rx_kbps)

        if (not is_connected) or (tx_kbps <= 0.0):
            tx_display = tx_label if (is_connected and bool(tx_label)) else "0 B/s"
            self.tx_card.sparkline.reset_flat()
        else:
            tx_display = tx_label if tx_label else format_rate_from_kbps(tx_kbps)
            self.tx_card.sparkline.push_sample(tx_kbps)

        if (not is_connected) or (ping <= 0):
            self.ping_card.value_lbl.setText("—")
            self.ping_card.sparkline.reset_flat()
        else:
            self.ping_card.value_lbl.setText(f"{ping} ms")
            self.ping_card.sparkline.push_sample(float(ping))

        self.rx_card.value_lbl.setText(rx_display)
        self.tx_card.value_lbl.setText(tx_display)

        vec = sanitize_ui_text(pick_first_text(snap, ("active_vector_id",), "AUTO"))
        self.vector_badge.setText(vec)
        self._refresh_geo_visuals()

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.hero_card.set_palette_theme(palette)
        self.radar_core.set_palette_theme(palette)
        self.route_bridge.set_palette_theme(palette)
        self.connect_btn.set_palette_theme(palette)
        self.chronometer.set_palette_theme(palette)
        self.hunt_best_btn.set_palette_theme(palette)
        self.sys_proxy_switch.set_palette_theme(palette)
        self.autopilot_switch.set_palette_theme(palette)
        self.tun_switch.set_palette_theme(palette)
        for card in (self.ip_card, self.rx_card, self.tx_card, self.ping_card):
            card.set_palette_theme(palette)


class RepoStatCounterCard(QFrame):
    def __init__(self, caption: str, accent_hex: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SubtleCard")
        self._accent_hex = accent_hex

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        self.caption_lbl = QLabel(caption)
        self.caption_lbl.setObjectName("MutedLabel")

        self.value_lbl = QLabel("0")
        enforce_english_ltr(self.value_lbl, mono_size=12, bold=True)
        self.value_lbl.setStyleSheet(f"color: {accent_hex};")

        row.addWidget(self.caption_lbl)
        row.addStretch()
        row.addWidget(self.value_lbl)

    def set_value_text(self, text: str):
        self.value_lbl.setText(text)


class ScanResultRowWidget(QFrame):
    ip_selected = Signal(str)
    apply_ip_requested = Signal(str, bool)
    apply_vector_requested = Signal(str, int, str, bool)
    apply_vector_all_requested = Signal(str, str)
    connect_scanned_profile_requested = Signal(int, str, str)

    def __init__(self, row: dict, fallback_target_index: int = -1, parent=None):
        super().__init__(parent)
        self._row = dict(row)
        self._fallback_target_index = fallback_target_index
        self._ip = ""
        self._item_id = ""
        self._target_idx = -1
        self._endpoint = ""
        self._bound_vector = ""

        self.setObjectName("GlassCard")
        self.setMinimumHeight(68)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 10, 14, 10)
        self._layout.setSpacing(8)

        self.rank_badge = QLabel()
        enforce_english_ltr(self.rank_badge, mono_size=10, bold=True)

        self.flag_badge = FlagBadgeWidget("GLOBAL", width=26, height=17)

        self.cat_badge = QLabel()
        self.cat_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.cat_badge, mono_size=10, bold=True)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.title_lbl = QLabel()
        self.title_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))
        self.detail_lbl = QLabel()
        self.detail_lbl.setObjectName("MutedLabel")
        info_col.addWidget(self.title_lbl)
        info_col.addWidget(self.detail_lbl)

        self.endpoint_lbl = QLabel()
        enforce_english_ltr(self.endpoint_lbl, mono_size=10, bold=True)

        self.metrics_lbl = QLabel()
        enforce_english_ltr(self.metrics_lbl, mono_size=10)

        self.status_badge = QLabel()
        enforce_english_ltr(self.status_badge, mono_size=10, bold=True)

        self.btn_apply_vec = QPushButton("اعمال روی کانفیگ")
        self.btn_apply_vec.setObjectName("GhostPillBtn")
        self.btn_apply_vec.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_vec.clicked.connect(self._on_apply_vec_single)

        self.btn_apply_vec_all = QPushButton("اعمال روی کل مخزن")
        self.btn_apply_vec_all.setObjectName("AmberPillBtn")
        self.btn_apply_vec_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_vec_all.clicked.connect(self._on_apply_vec_all)

        self.btn_apply_vec_conn = QPushButton("اعمال و اتصال")
        self.btn_apply_vec_conn.setObjectName("SuccessPillBtn")
        self.btn_apply_vec_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_vec_conn.clicked.connect(self._on_apply_vec_and_connect)

        self.btn_repo_connect = QPushButton("انتخاب و اتصال فوری")
        self.btn_repo_connect.setObjectName("SuccessPillBtn")
        self.btn_repo_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_repo_connect.clicked.connect(self._on_repo_connect)

        self.btn_patch_ip_active = QPushButton("وصله به کانفیگ فعلی")
        self.btn_patch_ip_active.setObjectName("AccentBtn")
        self.btn_patch_ip_active.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_patch_ip_active.clicked.connect(self._on_patch_ip_active)

        self.btn_patch_ip_all = QPushButton("وصله به کل مخزن")
        self.btn_patch_ip_all.setObjectName("AmberPillBtn")
        self.btn_patch_ip_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_patch_ip_all.clicked.connect(self._on_patch_ip_all)

        self._layout.addWidget(self.rank_badge)
        self._layout.addWidget(self.flag_badge)
        self._layout.addWidget(self.cat_badge)
        self._layout.addLayout(info_col, 1)
        self._layout.addWidget(self.endpoint_lbl)
        self._layout.addWidget(self.metrics_lbl)
        self._layout.addWidget(self.status_badge)
        self._layout.addWidget(self.btn_apply_vec)
        self._layout.addWidget(self.btn_apply_vec_all)
        self._layout.addWidget(self.btn_apply_vec_conn)
        self._layout.addWidget(self.btn_repo_connect)
        self._layout.addWidget(self.btn_patch_ip_active)
        self._layout.addWidget(self.btn_patch_ip_all)

        self.update_data(row, fallback_target_index)

    def _on_apply_vec_single(self):
        self.btn_apply_vec.setText("اعمال شد")
        self.apply_vector_requested.emit(self._item_id, self._target_idx, self._endpoint, False)

    def _on_apply_vec_all(self):
        self.btn_apply_vec_all.setText("وصله به مخزن شد")
        self.apply_vector_all_requested.emit(self._item_id, self._endpoint)

    def _on_apply_vec_and_connect(self):
        self.btn_apply_vec_conn.setText("در حال اتصال...")
        self.apply_vector_requested.emit(self._item_id, self._target_idx, self._endpoint, True)

    def _on_repo_connect(self):
        self.btn_repo_connect.setText("در حال اتصال...")
        self.connect_scanned_profile_requested.emit(self._target_idx, self._bound_vector, self._endpoint)

    def _on_patch_ip_active(self):
        cand = extract_ip_candidate(self._item_id)
        target_ip = self._item_id if bool(cand) else self._ip
        if target_ip:
            self.btn_patch_ip_active.setText("وصله شد")
            self.apply_ip_requested.emit(target_ip, True)

    def _on_patch_ip_all(self):
        cand = extract_ip_candidate(self._item_id)
        target_ip = self._item_id if bool(cand) else self._ip
        if target_ip:
            self.btn_patch_ip_all.setText("وصله به مخزن شد")
            self.apply_ip_requested.emit(target_ip, False)

    def _resolve_profile_index(self, row: dict) -> int:
        for k in ("target_index", "profile_index", "index"):
            v = row.get(k, None)
            if isinstance(v, int) and (not isinstance(v, bool)) and (v >= 0):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        m = re.search(r"(\d+)", pick_first_text(row, ("item_id",), ""))
        if m:
            return int(m.group(1))
        return self._fallback_target_index

    def update_data(self, row: dict, fallback_target_index: int = -1):
        self._row = dict(row)
        if fallback_target_index >= 0:
            self._fallback_target_index = fallback_target_index

        scan_type = pick_first_text(row, ("scan_type",), "").lower()
        self._item_id = pick_first_text(row, ("item_id",), "")
        self._endpoint = pick_first_text(row, ("endpoint",), "")
        self._bound_vector = pick_first_text(row, ("bound_vector", "vector_id"), "")
        self._target_idx = self._resolve_profile_index(row)

        self.flag_badge.set_country_code(GeoFlagResolver.resolve_code(row))

        rank_str = normalize_rank_text(row.get("rank", None))
        if rank_str:
            self.rank_badge.setText(rank_str)
            if rank_str == "#1":
                r_obj = "RankGold"
                self.setObjectName("HeroCard")
            elif rank_str == "#2":
                r_obj = "RankSilver"
            elif rank_str == "#3":
                r_obj = "RankBronze"
            else:
                r_obj = "RankDefault"
            self.rank_badge.setObjectName(r_obj)
            self.rank_badge.style().unpolish(self.rank_badge)
            self.rank_badge.style().polish(self.rank_badge)
            self.style().unpolish(self)
            self.style().polish(self)
            self.rank_badge.show()
        else:
            self.rank_badge.hide()

        raw_title = sanitize_ui_text(pick_first_text(row, ("title", "item_id"), "Result"))
        clean_title = GeoFlagResolver.clean_display_name(raw_title)
        if not clean_title:
            clean_title = raw_title
        default_cat = scan_type.upper() if scan_type else "SCAN"
        category = sanitize_ui_text(pick_first_text(row, ("category",), default_cat))
        tcp_ms = row.get("tcp_ms", None)
        tunnel_ms = row.get("tunnel_ms", None)
        score = row.get("score", None)
        status = pick_first_text(row, ("status",), "UNTESTED").upper()
        detail = sanitize_ui_text(pick_first_text(row, ("detail",), "ارزیابی کامل شد"))

        self.cat_badge.setText(category[:16])
        self.title_lbl.setText(clean_title)
        self.detail_lbl.setText(detail)
        self.endpoint_lbl.setText(self._endpoint)

        parts = []
        if (score is not None) and (str(score).strip() != ""):
            parts.append(f"Score {parse_float_value(score, 0.0):.0f}")
        tcp_int = parse_int_value(tcp_ms, 0)
        if tcp_int > 0:
            parts.append(f"TCP {tcp_int}ms")
        tls_int = parse_int_value(tunnel_ms, 0)
        if tls_int > 0:
            parts.append(f"TLS {tls_int}ms")
        self.metrics_lbl.setText(" | ".join(parts) if parts else "—")

        self.status_badge.setText(status)
        if status in ("VERIFIED", "OK", "PASS", "CLEAN", "HEALTHY", "ONLINE"):
            self.status_badge.setObjectName("StatusVerified")
        elif status in ("PARTIAL_OK", "PARTIAL", "WARN"):
            self.status_badge.setObjectName("StatusPartial")
        elif status in ("DEAD", "FAIL", "FAILED", "TIMEOUT", "BLOCKED", "ERROR"):
            self.status_badge.setObjectName("StatusDead")
        else:
            self.status_badge.setObjectName("StatusUntested")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        is_vector_type = scan_type in ("vector", "active_profile")
        is_repo_type = scan_type in ("repository", "full_repository")
        is_ip_type = scan_type in ("clean_ip", "clean_ip_radar")

        is_method_ok = is_vector_type and (status in ("VERIFIED", "PARTIAL_OK"))
        self.btn_apply_vec.setVisible(is_method_ok)
        self.btn_apply_vec_all.setVisible(is_method_ok)
        self.btn_apply_vec_conn.setVisible(is_method_ok)

        is_repo_ok = is_repo_type and (
            status in ("VERIFIED", "PARTIAL_OK", "OK", "CLEAN", "HEALTHY")
        )
        self.btn_repo_connect.setVisible(is_repo_ok)

        ip_cand = extract_ip_candidate(self._item_id)
        if not ip_cand:
            ip_cand = extract_ip_candidate(self._endpoint)
        if not ip_cand:
            ip_cand = extract_ip_candidate(raw_title)
        self._ip = ip_cand
        show_ip_btns = is_ip_type and bool(ip_cand)
        self.btn_patch_ip_active.setVisible(show_ip_btns)
        self.btn_patch_ip_all.setVisible(show_ip_btns)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton) and bool(self._ip):
            self.ip_selected.emit(self._ip)
        super().mouseReleaseEvent(event)


class ScannerPage(QWidget):
    start_scan_requested = Signal(str, int, dict)
    stop_scan_requested = Signal()
    apply_ip_requested = Signal(str, bool)
    apply_vector_requested = Signal(str, int, str, bool)
    apply_vector_all_requested = Signal(str, str)
    connect_scanned_profile_requested = Signal(int, str, str)

    MODES = ["active_profile", "full_repository", "clean_ip_radar"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._is_running = False
        self._selected_ip = ""
        self._total_profiles_count = 0
        self._current_target_index = -1
        self._repo_verified_ids: set[str] = set()
        self._repo_dead_ids: set[str] = set()
        self._row_widgets: dict[str, ScanResultRowWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        t_col = QVBoxLayout()
        t_lbl = QLabel("اسکنر هوشمند، رتبه‌بندی متدها و رادار IP تمیز")
        t_lbl.setFont(make_ui_font(15, QFont.Weight.ExtraBold))
        s_lbl = QLabel("رتبه‌بندی خودکار متدهای عبوری، وصله مستقیم به تک‌کانفیگ یا کل مخزن و پایش دسته‌جمعی.")
        s_lbl.setObjectName("MutedLabel")
        t_col.addWidget(t_lbl)
        t_col.addWidget(s_lbl)
        hdr.addLayout(t_col, 1)
        root.addLayout(hdr)

        self.inline_task_strip = TaskProgressStrip(inline_style=True)
        self.inline_task_strip.stop_requested.connect(self.stop_scan_requested.emit)
        root.addWidget(self.inline_task_strip)

        self.mode_bar = SegmentedCapsuleBar(
            [
                "اسکن عمیق کانفیگ انتخابی",
                "اسکن دسته‌جمعی کل مخزن",
                "رادار چندرنجی IP تمیز",
            ]
        )
        self.mode_bar.current_changed.connect(self._on_mode_changed)
        root.addWidget(self.mode_bar)

        self.options_card = QFrame()
        self.options_card.setObjectName("PillBar")
        opt_layout = QHBoxLayout(self.options_card)
        opt_layout.setContentsMargins(14, 10, 14, 10)
        opt_layout.setSpacing(12)

        self.mode0_widget = QWidget()
        m0 = QHBoxLayout(self.mode0_widget)
        m0.setContentsMargins(0, 0, 0, 0)
        m0.setSpacing(12)
        m0_lbl = QLabel("کانفیگ هدف:")
        m0_lbl.setObjectName("SecondaryLabel")
        self.target_profile_combo = QComboBox()
        self.target_profile_combo.setMinimumWidth(240)
        self.target_profile_combo.setIconSize(QSize(24, 16))
        self.chk_auto_connect = QCheckBox("اتصال خودکار به اولین متد موفق")
        self.chk_auto_connect.setChecked(False)
        m0.addWidget(m0_lbl)
        m0.addWidget(self.target_profile_combo, 1)
        m0.addSpacing(10)
        m0.addWidget(self.chk_auto_connect)
        m0.addStretch()

        self.mode1_widget = QWidget()
        m1 = QHBoxLayout(self.mode1_widget)
        m1.setContentsMargins(0, 0, 0, 0)
        m1.setSpacing(12)
        self.sw_repo_clean_ip = AnimatedToggleSwitch(checked=True)
        m1_lbl1 = QLabel("تزریق خودکار IP تمیز روی کانفیگ‌ها")
        m1_lbl1.setObjectName("SecondaryLabel")
        self.sw_repo_prune = AnimatedToggleSwitch(checked=False)
        m1_lbl2 = QLabel("حذف خودکار کانفیگ‌های ازکارافتاده")
        m1_lbl2.setObjectName("SecondaryLabel")
        m1.addWidget(self.sw_repo_clean_ip)
        m1.addWidget(m1_lbl1)
        m1.addSpacing(14)
        m1.addWidget(self.sw_repo_prune)
        m1.addWidget(m1_lbl2)
        m1.addStretch()
        self.mode1_widget.hide()

        self.mode2_widget = QWidget()
        m2 = QHBoxLayout(self.mode2_widget)
        m2.setContentsMargins(0, 0, 0, 0)
        m2.setSpacing(10)
        port_lbl = QLabel("پورت TLS:")
        port_lbl.setObjectName("SecondaryLabel")
        self.radar_port_spin = QSpinBox()
        self.radar_port_spin.setRange(1, 65535)
        self.radar_port_spin.setValue(443)
        enforce_english_ltr(self.radar_port_spin, mono_size=10)

        samp_lbl = QLabel("تعداد نمونه:")
        samp_lbl.setObjectName("SecondaryLabel")
        self.radar_samples_spin = QSpinBox()
        self.radar_samples_spin.setRange(4, 500)
        self.radar_samples_spin.setValue(44)
        enforce_english_ltr(self.radar_samples_spin, mono_size=10)

        self.selected_ip_badge = QLabel("IP: —")
        self.selected_ip_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.selected_ip_badge, mono_size=10, bold=True)

        self.top_apply_active_btn = QPushButton("وصله به کانفیگ فعلی")
        self.top_apply_active_btn.setObjectName("GhostPillBtn")
        self.top_apply_active_btn.setEnabled(False)
        self.top_apply_active_btn.clicked.connect(lambda: self._apply_selected_ip(True))

        self.top_apply_repo_btn = QPushButton("وصله به کل مخزن")
        self.top_apply_repo_btn.setObjectName("GhostPillBtn")
        self.top_apply_repo_btn.setEnabled(False)
        self.top_apply_repo_btn.clicked.connect(lambda: self._apply_selected_ip(False))

        m2.addWidget(port_lbl)
        m2.addWidget(self.radar_port_spin)
        m2.addWidget(samp_lbl)
        m2.addWidget(self.radar_samples_spin)
        m2.addStretch()
        m2.addWidget(self.selected_ip_badge)
        m2.addWidget(self.top_apply_active_btn)
        m2.addWidget(self.top_apply_repo_btn)
        self.mode2_widget.hide()

        opt_layout.addWidget(self.mode0_widget, 1)
        opt_layout.addWidget(self.mode1_widget, 1)
        opt_layout.addWidget(self.mode2_widget, 1)
        root.addWidget(self.options_card)

        ctrl_bar = QFrame()
        ctrl_bar.setObjectName("PillBar")
        ctrl_layout = QHBoxLayout(ctrl_bar)
        ctrl_layout.setContentsMargins(14, 9, 14, 9)
        ctrl_layout.setSpacing(12)

        self.action_btn = QPushButton("شروع اسکن")
        self.action_btn.setObjectName("AccentBtn")
        self.action_btn.setMinimumWidth(135)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self._toggle_scan)

        self.clear_btn = QPushButton("پاکسازی نتایج")
        self.clear_btn.setObjectName("GhostPillBtn")
        self.clear_btn.clicked.connect(self.clear_results)

        prog_col = QVBoxLayout()
        prog_col.setSpacing(4)
        self.status_lbl = QLabel("آماده شروع عملیات اسکن")
        self.status_lbl.setObjectName("SecondaryLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("GoldProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        enforce_english_ltr(self.progress_bar, mono_size=9)
        prog_col.addWidget(self.status_lbl)
        prog_col.addWidget(self.progress_bar)

        self.percent_badge = QLabel("0%")
        self.percent_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.percent_badge, mono_size=10, bold=True)

        ctrl_layout.addWidget(self.action_btn)
        ctrl_layout.addWidget(self.clear_btn)
        ctrl_layout.addLayout(prog_col, 1)
        ctrl_layout.addWidget(self.percent_badge)
        root.addWidget(ctrl_bar)

        self.repo_stats_bar = QWidget()
        stats_row = QHBoxLayout(self.repo_stats_bar)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(10)

        self.stat_total = RepoStatCounterCard("کل کانفیگ‌ها", "#38BDF8")
        self.stat_verified = RepoStatCounterCard("تاییدشده (سالم)", "#10B981")
        self.stat_dead = RepoStatCounterCard("ازکارافتاده (خطا)", "#EF4444")
        self.stat_progress = RepoStatCounterCard("پیشرفت", "#FFD000")

        stats_row.addWidget(self.stat_total, 1)
        stats_row.addWidget(self.stat_verified, 1)
        stats_row.addWidget(self.stat_dead, 1)
        stats_row.addWidget(self.stat_progress, 1)
        self.repo_stats_bar.hide()
        root.addWidget(self.repo_stats_bar)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 4, 4, 6)
        self.rows_layout.setSpacing(8)
        self.empty_lbl = QLabel("نتایج اسکن زنده و رتبه‌بندی نهایی در این بخش نمایش داده می‌شوند.")
        self.empty_lbl.setObjectName("MutedLabel")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows_layout.addWidget(self.empty_lbl)
        self.rows_layout.addStretch()

        self.scroll = make_transparent_scroll_area(self.rows_container)
        root.addWidget(self.scroll, 1)

    def _on_mode_changed(self, idx: int):
        self.mode0_widget.setVisible(idx == 0)
        self.mode1_widget.setVisible(idx == 1)
        self.mode2_widget.setVisible(idx == 2)
        self.repo_stats_bar.setVisible(idx == 1)
        self._refresh_repo_counters()

    def set_profiles(self, items: list[dict], active_index: int = -1, active_uid: str = ""):
        safe_items = list(items) if isinstance(items, list) else []
        self._total_profiles_count = len(safe_items)
        prev = self.target_profile_combo.currentIndex()
        resolved_active = resolve_active_profile_index(safe_items, active_index, active_uid)

        self.target_profile_combo.blockSignals(True)
        self.target_profile_combo.clear()
        for idx, item in enumerate(safe_items):
            raw_name = sanitize_ui_text(pick_first_text(item, ("name", "title"), f"Profile #{idx + 1}"))
            clean_name = GeoFlagResolver.clean_display_name(raw_name)
            if not clean_name:
                clean_name = raw_name
            code = GeoFlagResolver.resolve_code(item)
            proto = pick_first_text(item, ("protocol",), "PROXY").upper()
            self.target_profile_combo.addItem(
                make_flag_qicon(code, 26, 18),
                f"#{idx + 1} - {clean_name} ({proto})",
            )

        chosen = resolved_active if (resolved_active >= 0) else prev
        if (chosen >= 0) and (chosen < len(safe_items)):
            self.target_profile_combo.setCurrentIndex(chosen)
        elif safe_items:
            self.target_profile_combo.setCurrentIndex(0)
        else:
            self.target_profile_combo.setCurrentIndex(-1)
        self.target_profile_combo.blockSignals(False)
        self._refresh_repo_counters()

    def trigger_profile_deep_scan(self, index: int):
        self.mode_bar.set_current_index(0, emit_signal=True)
        if (index >= 0) and (index < self.target_profile_combo.count()):
            self.target_profile_combo.setCurrentIndex(index)
        self._current_target_index = index
        self.clear_results()
        self.start_scan_requested.emit(
            "active_profile",
            index,
            {"auto_connect": self.chk_auto_connect.isChecked()},
        )

    def _toggle_scan(self):
        if self._is_running:
            self.stop_scan_requested.emit()
            return

        self.clear_results()
        idx = self.mode_bar.current_index()
        mode = self.MODES[idx]
        if mode == "active_profile":
            target = max(0, self.target_profile_combo.currentIndex())
            self._current_target_index = target
            opts = {"auto_connect": self.chk_auto_connect.isChecked()}
        elif mode == "full_repository":
            target = -1
            self._current_target_index = -1
            opts = {
                "prune_dead": self.sw_repo_prune.isChecked(),
                "auto_clean_ip": self.sw_repo_clean_ip.isChecked(),
            }
        else:
            target = -1
            self._current_target_index = -1
            opts = {
                "port": int(self.radar_port_spin.value()),
                "samples": int(self.radar_samples_spin.value()),
            }
        self.start_scan_requested.emit(mode, target, opts)

    def _refresh_repo_counters(self):
        self.stat_total.set_value_text(str(self._total_profiles_count))
        self.stat_verified.set_value_text(str(len(self._repo_verified_ids)))
        self.stat_dead.set_value_text(str(len(self._repo_dead_ids)))
        self.stat_progress.set_value_text(f"{self.progress_bar.value()}%")

    def clear_results(self):
        self.rows_container.setUpdatesEnabled(False)
        try:
            self._row_widgets.clear()
            self._repo_verified_ids.clear()
            self._repo_dead_ids.clear()
            self.progress_bar.setValue(0)
            self.percent_badge.setText("0%")
            self._refresh_repo_counters()

            while self.rows_layout.count():
                item = self.rows_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.empty_lbl = QLabel("نتایج اسکن زنده و رتبه‌بندی نهایی در این بخش نمایش داده می‌شوند.")
            self.empty_lbl.setObjectName("MutedLabel")
            self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rows_layout.addWidget(self.empty_lbl)
            self.rows_layout.addStretch()
        finally:
            self.rows_container.setUpdatesEnabled(True)

    def _on_ip_selected(self, ip: str):
        self._selected_ip = ip
        self.selected_ip_badge.setText(f"IP: {ip}")
        self.top_apply_active_btn.setEnabled(bool(ip))
        self.top_apply_repo_btn.setEnabled(bool(ip))

    def _apply_selected_ip(self, only_active: bool):
        if self._selected_ip:
            self.apply_ip_requested.emit(self._selected_ip, only_active)

    def _create_row_widget(self, row: dict) -> ScanResultRowWidget:
        widget = ScanResultRowWidget(row, fallback_target_index=self._current_target_index)
        widget.ip_selected.connect(self._on_ip_selected)
        widget.apply_ip_requested.connect(self.apply_ip_requested.emit)
        widget.apply_vector_requested.connect(self.apply_vector_requested.emit)
        widget.apply_vector_all_requested.connect(self.apply_vector_all_requested.emit)
        widget.connect_scanned_profile_requested.connect(self.connect_scanned_profile_requested.emit)
        return widget

    def _track_repo_row_stats(self, row: dict):
        scan_t = pick_first_text(row, ("scan_type",), "").lower()
        if scan_t not in ("repository", "full_repository"):
            return
        key = pick_first_text(row, ("item_id",), str(id(row)))
        status = pick_first_text(row, ("status",), "").upper()
        if status in ("VERIFIED", "PARTIAL_OK", "OK", "CLEAN", "HEALTHY"):
            self._repo_verified_ids.add(key)
            self._repo_dead_ids.discard(key)
        elif status in ("DEAD", "FAIL", "FAILED", "TIMEOUT", "BLOCKED", "ERROR"):
            self._repo_dead_ids.add(key)
            self._repo_verified_ids.discard(key)
        self._refresh_repo_counters()

    def append_or_update_row(self, row: dict):
        self.rows_container.setUpdatesEnabled(False)
        try:
            if self.empty_lbl is not None:
                self.empty_lbl.hide()

            self._track_repo_row_stats(row)

            key = pick_first_text(row, ("item_id",), "")
            if key and (key in self._row_widgets):
                self._row_widgets[key].update_data(row, fallback_target_index=self._current_target_index)
            else:
                widget = self._create_row_widget(row)
                insert_pos = max(0, self.rows_layout.count() - 1)
                self.rows_layout.insertWidget(insert_pos, widget)
                if key:
                    self._row_widgets[key] = widget

            scan_t = pick_first_text(row, ("scan_type",), "").lower()
            if (scan_t in ("clean_ip", "clean_ip_radar")) and (not self._selected_ip):
                cand = extract_ip_candidate(pick_first_text(row, ("item_id", "endpoint"), ""))
                if cand:
                    self._on_ip_selected(cand)
        finally:
            self.rows_container.setUpdatesEnabled(True)

    def apply_ranked_results(self, rows: list):
        if not rows:
            return
        self.rows_container.setUpdatesEnabled(False)
        try:
            self._row_widgets.clear()
            self._repo_verified_ids.clear()
            self._repo_dead_ids.clear()

            while self.rows_layout.count():
                item = self.rows_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.empty_lbl = None

            for idx, raw_row in enumerate(rows):
                if not isinstance(raw_row, dict):
                    continue
                r_copy = dict(raw_row)
                if not r_copy.get("rank"):
                    r_copy["rank"] = f"#{idx + 1}"
                if ("target_index" not in r_copy) and (self._current_target_index >= 0):
                    r_copy["target_index"] = self._current_target_index

                self._track_repo_row_stats(r_copy)
                widget = self._create_row_widget(r_copy)
                self.rows_layout.addWidget(widget)
                key = pick_first_text(r_copy, ("item_id",), "")
                if key:
                    self._row_widgets[key] = widget

            self.rows_layout.addStretch()
            self._refresh_repo_counters()
        finally:
            self.rows_container.setUpdatesEnabled(True)

    def show_confirmation(self, message: str):
        self.status_lbl.setText(sanitize_ui_text(message))

    def update_progress(self, percent: int, label: str):
        clamped = max(0, min(100, parse_int_value(percent, 0)))
        self.progress_bar.setValue(clamped)
        self.percent_badge.setText(f"{clamped}%")
        if label:
            self.status_lbl.setText(sanitize_ui_text(label))
        self._refresh_repo_counters()

    def update_scan_state(self, is_running: bool, summary: str):
        self._is_running = bool(is_running)
        if self._is_running:
            self.action_btn.setText("توقف اسکن")
            self.action_btn.setObjectName("DangerSolidBtn")
        else:
            self.action_btn.setText("شروع اسکن")
            self.action_btn.setObjectName("AccentBtn")
        self.action_btn.style().unpolish(self.action_btn)
        self.action_btn.style().polish(self.action_btn)
        if summary:
            self.status_lbl.setText(sanitize_ui_text(summary))

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.inline_task_strip.set_palette_theme(palette)
        self.mode_bar.set_palette_theme(palette)
        for sw in (self.sw_repo_clean_ip, self.sw_repo_prune):
            sw.set_palette_theme(palette)


class ProfileCardWidget(QFrame):
    selected = Signal(int)
    deleted = Signal(int)
    full_edit_requested = Signal(int)
    rename_requested = Signal(int, str)
    clone_clean_requested = Signal(int)
    send_to_scanner_requested = Signal(int)
    copied_uri = Signal(str)

    def __init__(self, index: int, data: dict, is_active: bool, palette: ThemePalette, parent=None):
        super().__init__(parent)
        self._index = index
        self._data = data
        self.setObjectName("HeroCard" if is_active else "GlassCard")
        self.setMinimumHeight(82)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(9)

        country_code = GeoFlagResolver.resolve_code(data)
        flag_widget = FlagBadgeWidget(country_code, width=32, height=21)

        proto = pick_first_text(data, ("protocol", "scheme"), "VLESS").upper()
        proto_badge = QLabel(proto)
        proto_badge.setObjectName("BadgePill")
        enforce_english_ltr(proto_badge, mono_size=10, bold=True)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        raw_name = sanitize_ui_text(pick_first_text(data, ("name", "title"), f"Profile #{index + 1}"))
        clean_name = GeoFlagResolver.clean_display_name(raw_name)
        if not clean_name:
            clean_name = raw_name
        title_lbl = QLabel(clean_name)
        title_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))

        server_addr = str(data.get("host") or data.get("original_host") or "").strip()
        if not server_addr:
            server_addr = pick_first_text(data, ("address", "endpoint"), "—")
        port_num = parse_int_value(data.get("port", 0), 0)
        sni = pick_first_text(data, ("sni", "server_name"), "")
        if (port_num > 0) and (server_addr != "—") and (":" not in server_addr):
            host_part = f"{server_addr}:{port_num}"
        else:
            host_part = server_addr
        sub_txt = f"{host_part} | SNI: {sni}" if sni else host_part
        sub_lbl = QLabel(sub_txt)
        sub_lbl.setObjectName("MutedLabel")
        enforce_english_ltr(sub_lbl, mono_size=9)
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        info_col.addWidget(title_lbl)
        info_col.addWidget(sub_lbl)

        status_raw = pick_first_text(data, ("status", "health"), "UNTESTED").upper()
        health_lbl = QLabel(status_raw)
        enforce_english_ltr(health_lbl, mono_size=9, bold=True)
        if status_raw in ("VERIFIED", "OK", "HEALTHY", "CLEAN"):
            health_lbl.setObjectName("StatusVerified")
        elif status_raw in ("PARTIAL_OK", "PARTIAL"):
            health_lbl.setObjectName("StatusPartial")
        elif status_raw in ("DEAD", "FAIL", "FAILED", "TIMEOUT"):
            health_lbl.setObjectName("StatusDead")
        else:
            health_lbl.setObjectName("StatusUntested")

        raw_ping = data.get("ping_ms", None)
        if raw_ping is None:
            raw_ping = data.get("latency_ms", 0)
        ping_int = parse_int_value(raw_ping, 0)
        ping_txt = f"{ping_int} ms" if (ping_int > 0) else "— ms"
        ping_lbl = QLabel(ping_txt)
        ping_lbl.setObjectName("BadgePill")
        enforce_english_ltr(ping_lbl, mono_size=10, bold=True)

        bound_vec = sanitize_ui_text(
            pick_first_text(data, ("preferred_vector_id", "cached_vector_id"), "AUTO")
        )
        vec_lbl = QLabel(bound_vec if bound_vec else "AUTO")
        vec_lbl.setObjectName("BadgePill")
        enforce_english_ltr(vec_lbl, mono_size=9, bold=True)

        full_edit_btn = QPushButton("ویرایش کامل")
        full_edit_btn.setObjectName("GhostPillBtn")
        full_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        full_edit_btn.clicked.connect(lambda: self.full_edit_requested.emit(self._index))

        clone_btn = QPushButton("کلون IP تمیز")
        clone_btn.setObjectName("GhostPillBtn")
        clone_btn.setToolTip("تولید ۳ کلون با IPهای تمیز")
        clone_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clone_btn.clicked.connect(lambda: self.clone_clean_requested.emit(self._index))

        scan_btn = QPushButton("ارسال به اسکنر")
        scan_btn.setObjectName("GhostPillBtn")
        scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        scan_btn.clicked.connect(lambda: self.send_to_scanner_requested.emit(self._index))

        select_btn = QPushButton("فعال" if is_active else "انتخاب")
        select_btn.setObjectName("GhostPillBtn" if is_active else "AccentBtn")
        select_btn.setEnabled(not is_active)
        select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        select_btn.clicked.connect(lambda: self.selected.emit(self._index))

        rename_btn = VectorIconButton("edit", size=30)
        rename_btn.setToolTip("تغییر نام سریع")
        rename_btn.set_palette_theme(palette)
        rename_btn.clicked.connect(lambda: self.rename_requested.emit(self._index, raw_name))

        copy_btn = VectorIconButton("copy", size=30)
        copy_btn.setToolTip("کپی لینک کانفیگ")
        copy_btn.set_palette_theme(palette)
        copy_btn.clicked.connect(self._copy_single)

        del_btn = VectorIconButton("trash", size=30, danger_hover=True)
        del_btn.setToolTip("حذف کانفیگ")
        del_btn.set_palette_theme(palette)
        del_btn.clicked.connect(lambda: self.deleted.emit(self._index))

        row.addWidget(flag_widget)
        row.addWidget(proto_badge)
        row.addLayout(info_col, 1)
        row.addWidget(vec_lbl)
        row.addWidget(ping_lbl)
        row.addWidget(health_lbl)
        row.addWidget(full_edit_btn)
        row.addWidget(clone_btn)
        row.addWidget(scan_btn)
        row.addWidget(select_btn)
        row.addWidget(rename_btn)
        row.addWidget(copy_btn)
        row.addWidget(del_btn)

    def _copy_single(self):
        uri = pick_first_text(self._data, ("raw_uri", "uri", "raw"), "")
        if uri:
            QGuiApplication.clipboard().setText(uri)
            self.copied_uri.emit("لینک کانفیگ در کلیپ‌بورد کپی شد.")


class ProfilesPage(QWidget):
    import_clipboard_requested = Signal(str)
    import_file_requested = Signal(str)
    open_config_editor_requested = Signal(int)
    hunt_best_requested = Signal()
    stop_task_requested = Signal()
    clear_all_requested = Signal()
    quick_ping_requested = Signal()
    sort_requested = Signal(str)
    deduplicate_requested = Signal()
    remove_dead_requested = Signal()
    rename_requested = Signal(int, str)
    select_requested = Signal(int)
    delete_requested = Signal(int)
    clone_clean_requested = Signal(int, int)
    send_to_scanner_requested = Signal(int)
    export_requested = Signal(str, int)
    add_sub_requested = Signal(str, str)
    refresh_subs_requested = Signal()
    delete_sub_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._items: list[dict] = []
        self._subs: list[dict] = []
        self._active_idx = -1
        self._active_uid = ""
        self._filter_query = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_col = QVBoxLayout()
        h_lbl = QLabel("مخزن حرفه‌ای پروفایل‌ها و ویرایشگر کانفیگ")
        h_lbl.setFont(make_ui_font(15, QFont.Weight.ExtraBold))
        self.feedback_lbl = QLabel("شکار خودکار برترین کانفیگ، ویرایش کامل پارامترها و مدیریت سابسکریپشن.")
        self.feedback_lbl.setObjectName("MutedLabel")
        title_col.addWidget(h_lbl)
        title_col.addWidget(self.feedback_lbl)

        self.hunt_best_btn = ActionIconPillButton(
            "hunter",
            "شکار برترین کانفیگ مخزن و اتصال",
            golden=True,
        )
        self.hunt_best_btn.clicked.connect(self.hunt_best_requested.emit)

        self.count_badge = QLabel("0 ITEMS")
        self.count_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.count_badge, mono_size=10, bold=True)

        header.addLayout(title_col, 1)
        header.addWidget(self.hunt_best_btn)
        header.addWidget(self.count_badge)
        root.addLayout(header)

        self.inline_task_strip = TaskProgressStrip(inline_style=True)
        self.inline_task_strip.stop_requested.connect(self.stop_task_requested.emit)
        root.addWidget(self.inline_task_strip)

        row1 = QFrame()
        row1.setObjectName("PillBar")
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(12, 8, 12, 8)
        r1.setSpacing(8)

        btn_new_manual = QPushButton("افزودن دستی کانفیگ جدید")
        btn_new_manual.setObjectName("AccentBtn")
        btn_new_manual.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new_manual.clicked.connect(lambda: self.open_config_editor_requested.emit(-1))

        btn_paste = QPushButton("افزودن از کلیپ‌بورد")
        btn_paste.setObjectName("GhostPillBtn")
        btn_paste.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_paste.clicked.connect(self._on_paste_clicked)

        btn_file = QPushButton("واردسازی از فایل")
        btn_file.setObjectName("GhostPillBtn")
        btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_file.clicked.connect(self._on_import_file_clicked)

        self.btn_toggle_subs = QPushButton("مدیریت لینک‌های سابسکریپشن")
        self.btn_toggle_subs.setObjectName("GhostPillBtn")
        self.btn_toggle_subs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_subs.clicked.connect(self._toggle_subs_drawer)

        btn_export = QPushButton("خروجی سالم‌ها با EarlyData")
        btn_export.setObjectName("GhostPillBtn")
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.clicked.connect(lambda: self.export_requested.emit("verified", 2048))

        btn_clear_all = QPushButton("حذف کل کانفیگ‌ها")
        btn_clear_all.setObjectName("DangerSolidBtn")
        btn_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_all.clicked.connect(self._confirm_clear_all)

        r1.addWidget(btn_new_manual)
        r1.addWidget(btn_paste)
        r1.addWidget(btn_file)
        r1.addWidget(self.btn_toggle_subs)
        r1.addStretch()
        r1.addWidget(btn_export)
        r1.addWidget(btn_clear_all)
        root.addWidget(row1)

        self.subs_drawer = QFrame()
        self.subs_drawer.setObjectName("HeroCard")
        subs_vbox = QVBoxLayout(self.subs_drawer)
        subs_vbox.setContentsMargins(14, 12, 14, 12)
        subs_vbox.setSpacing(10)

        sub_top = QHBoxLayout()
        sub_top.setSpacing(8)
        self.sub_title_edit = QLineEdit()
        self.sub_title_edit.setPlaceholderText("عنوان سابسکریپشن (مثلاً VIP)")
        self.sub_title_edit.setMaximumWidth(200)

        self.sub_url_edit = QLineEdit()
        self.sub_url_edit.setPlaceholderText("https://example.com/sub/token")
        enforce_english_ltr(self.sub_url_edit, mono_size=10)

        btn_add_sub = QPushButton("افزودن لینک")
        btn_add_sub.setObjectName("AccentBtn")
        btn_add_sub.clicked.connect(self._submit_subscription)

        btn_refresh_subs = QPushButton("بروزرسانی همه")
        btn_refresh_subs.setObjectName("GhostPillBtn")
        btn_refresh_subs.clicked.connect(self.refresh_subs_requested.emit)

        sub_top.addWidget(self.sub_title_edit)
        sub_top.addWidget(self.sub_url_edit, 1)
        sub_top.addWidget(btn_add_sub)
        sub_top.addWidget(btn_refresh_subs)
        subs_vbox.addLayout(sub_top)

        self.subs_list_container = QWidget()
        self.subs_list_layout = QVBoxLayout(self.subs_list_container)
        self.subs_list_layout.setContentsMargins(0, 0, 0, 0)
        self.subs_list_layout.setSpacing(6)
        subs_vbox.addWidget(self.subs_list_container)
        self.subs_drawer.hide()
        root.addWidget(self.subs_drawer)

        row2 = QFrame()
        row2.setObjectName("PillBar")
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(12, 7, 12, 7)
        r2.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("جستجوی نام، کشور، پروتکل یا آدرس...")
        self.search_edit.textChanged.connect(self._on_search_changed)

        btn_ping_all = QPushButton("پینگ سریع همه")
        btn_ping_all.setObjectName("GhostPillBtn")
        btn_ping_all.clicked.connect(self.quick_ping_requested.emit)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("مرتب‌سازی: پینگ", "ping")
        self.sort_combo.addItem("مرتب‌سازی: نام", "name")
        self.sort_combo.addItem("مرتب‌سازی: پروتکل", "protocol")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_selected)

        btn_dedup = QPushButton("حذف تکراری‌ها")
        btn_dedup.setObjectName("GhostPillBtn")
        btn_dedup.clicked.connect(self.deduplicate_requested.emit)

        btn_clean_dead = QPushButton("پاکسازی خراب‌ها")
        btn_clean_dead.setObjectName("DangerPillBtn")
        btn_clean_dead.clicked.connect(self.remove_dead_requested.emit)

        r2.addWidget(self.search_edit, 1)
        r2.addWidget(btn_ping_all)
        r2.addWidget(self.sort_combo)
        r2.addWidget(btn_dedup)
        r2.addWidget(btn_clean_dead)
        root.addWidget(row2)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 4, 4, 6)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        self.scroll = make_transparent_scroll_area(self.cards_container)
        root.addWidget(self.scroll, 1)

    def show_feedback(self, message: str):
        self.feedback_lbl.setText(sanitize_ui_text(message))

    def _confirm_clear_all(self):
        if not self._items:
            self.show_feedback("مخزن در حال حاضر خالی است.")
            return
        dlg = ConfirmClearAllDialog(len(self._items), self._palette, self.window())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.clear_all_requested.emit()

    def _toggle_subs_drawer(self):
        self.subs_drawer.setVisible(not self.subs_drawer.isVisible())

    def _submit_subscription(self):
        url = self.sub_url_edit.text().strip()
        title = self.sub_title_edit.text().strip()
        if not title:
            title = "Subscription"
        if url:
            self.add_sub_requested.emit(url, title)
            self.sub_url_edit.clear()
            self.sub_title_edit.clear()

    def _on_paste_clicked(self):
        clip = QGuiApplication.clipboard().text().strip()
        if clip:
            self.import_clipboard_requested.emit(clip)
        else:
            self.show_feedback("کلیپ‌بورد خالی است؛ ابتدا لینک کانفیگ را کپی کنید.")

    def _on_import_file_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "انتخاب فایل کانفیگ",
            "",
            "Config Files (*.txt *.json *.conf *.sub);;All Files (*.*)",
        )
        if path:
            self.import_file_requested.emit(path)

    def _on_sort_selected(self, idx: int):
        key = self.sort_combo.itemData(idx)
        if key:
            self.sort_requested.emit(str(key))

    def _on_search_changed(self, text: str):
        self._filter_query = text.strip().lower()
        self.refresh_cards(self._items, self._active_idx, self._active_uid)

    def _open_rename_dialog(self, index: int, old_name: str):
        dlg = RenameProfileDialog(old_name, self._palette, self.window())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_title = dlg.new_name()
            if new_title:
                self.rename_requested.emit(index, new_title)

    def refresh_subscriptions(self, subs: list):
        self.subs_list_container.setUpdatesEnabled(False)
        try:
            self._subs = list(subs) if isinstance(subs, list) else []
            while self.subs_list_layout.count():
                child = self.subs_list_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            if not self._subs:
                empty = QLabel("هنوز لینک سابسکریپشنی ثبت نشده است.")
                empty.setObjectName("MutedLabel")
                self.subs_list_layout.addWidget(empty)
                return

            for idx, sub in enumerate(self._subs):
                item_frame = QFrame()
                item_frame.setObjectName("SubtleCard")
                row = QHBoxLayout(item_frame)
                row.setContentsMargins(12, 6, 12, 6)
                row.setSpacing(10)

                if isinstance(sub, dict):
                    title = pick_first_text(sub, ("title", "name"), f"Sub #{idx + 1}")
                    url = pick_first_text(sub, ("url",), "")
                else:
                    title = f"Sub #{idx + 1}"
                    url = str(sub)

                t_lbl = QLabel(title)
                t_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))
                u_lbl = QLabel(url)
                u_lbl.setObjectName("MutedLabel")
                enforce_english_ltr(u_lbl, mono_size=9)

                del_btn = VectorIconButton("trash", size=26, danger_hover=True)
                del_btn.set_palette_theme(self._palette)
                del_btn.clicked.connect(lambda _c=False, i=idx: self.delete_sub_requested.emit(i))

                row.addWidget(t_lbl)
                row.addWidget(u_lbl, 1)
                row.addWidget(del_btn)
                self.subs_list_layout.addWidget(item_frame)
        finally:
            self.subs_list_container.setUpdatesEnabled(True)

    def refresh_cards(self, items: list[dict], active_index: int = -1, active_uid: str = ""):
        self.cards_container.setUpdatesEnabled(False)
        try:
            self._items = list(items) if isinstance(items, list) else []
            if active_uid:
                self._active_uid = active_uid

            resolved_idx = resolve_active_profile_index(
                self._items,
                fallback_index=active_index,
                active_uid=self._active_uid,
            )
            if (resolved_idx < 0) and (self._active_idx >= 0) and (self._active_idx < len(self._items)):
                resolved_idx = self._active_idx

            self._active_idx = resolved_idx
            self.count_badge.setText(f"{len(self._items)} ITEMS")

            while self.cards_layout.count():
                child = self.cards_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            matched = 0
            for idx, item in enumerate(self._items):
                if self._filter_query:
                    spec = GeoFlagResolver.get_spec(GeoFlagResolver.resolve_code(item))
                    haystack = " ".join(
                        [
                            *(
                                str(item.get(k, ""))
                                for k in (
                                    "name",
                                    "title",
                                    "protocol",
                                    "host",
                                    "original_host",
                                    "address",
                                    "endpoint",
                                    "sni",
                                )
                            ),
                            spec.fa_name,
                            spec.en_name,
                            spec.code,
                        ]
                    ).lower()
                    if self._filter_query not in haystack:
                        continue
                matched += 1
                is_card_active = get_bool_value(item, "is_selected", False)
                if not is_card_active:
                    is_card_active = (idx == resolved_idx)
                card = ProfileCardWidget(idx, item, is_card_active, self._palette)
                card.selected.connect(self.select_requested.emit)
                card.deleted.connect(self.delete_requested.emit)
                card.full_edit_requested.connect(self.open_config_editor_requested.emit)
                card.rename_requested.connect(self._open_rename_dialog)
                card.clone_clean_requested.connect(lambda i: self.clone_clean_requested.emit(i, 3))
                card.send_to_scanner_requested.connect(self.send_to_scanner_requested.emit)
                card.copied_uri.connect(self.show_feedback)
                self.cards_layout.addWidget(card)

            if matched == 0:
                empty = QLabel(
                    "هیچ کانفیگی در مخزن وجود ندارد. از «افزودن دستی کانفیگ جدید» یا «افزودن از کلیپ‌بورد» استفاده کنید."
                )
                empty.setObjectName("MutedLabel")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cards_layout.addWidget(empty)

            self.cards_layout.addStretch()
        finally:
            self.cards_container.setUpdatesEnabled(True)

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.hunt_best_btn.set_palette_theme(palette)
        self.inline_task_strip.set_palette_theme(palette)
        self.refresh_cards(self._items, self._active_idx, self._active_uid)
        self.refresh_subscriptions(self._subs)


class SettingsPage(QWidget):
    settings_updated = Signal(dict)
    base_switch_toggled = Signal(str, bool)

    BASE_SWITCH_SLOTS = {
        "auto_clean_ip": "set_auto_clean_ip",
        "require_youtube_6s": "set_require_youtube_6s",
        "verify_upload_stream": "set_verify_upload_stream",
        "self_healing_watchdog": "set_self_healing_watchdog",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._updating = False
        self._controller = None
        self._switches: list[AnimatedToggleSwitch] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 16)
        outer.setSpacing(12)

        hdr = QVBoxLayout()
        t_lbl = QLabel("تنظیمات هوشمند و پیکربندی موتور")
        t_lbl.setFont(make_ui_font(15, QFont.Weight.ExtraBold))
        d_lbl = QLabel("پایش خودکار به صورت پیش‌فرض فعال است؛ پارامترهای سطح پایین در پنل بازشونده قرار دارند.")
        d_lbl.setObjectName("MutedLabel")
        hdr.addWidget(t_lbl)
        hdr.addWidget(d_lbl)
        outer.addLayout(hdr)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 6, 10)
        body_layout.setSpacing(14)

        base_card = QFrame()
        base_card.setObjectName("GlassCard")
        base_vbox = QVBoxLayout(base_card)
        base_vbox.setContentsMargins(18, 16, 18, 16)
        base_vbox.setSpacing(14)

        sec_hdr = QLabel("تنظیمات پایه و پایش خودکار")
        sec_hdr.setFont(make_ui_font(11, QFont.Weight.Bold))
        base_vbox.addWidget(sec_hdr)

        self.sw_auto_clean_ip = self._add_base_switch_row(
            base_vbox,
            "auto_clean_ip",
            "یافتن خودکار IP تمیز از چند رنج (Auto Clean IP)",
            "جایگزینی خودکار آدرس خروجی با کم‌تاخیرترین IP سالم پیش از برقراری تونل",
            True,
        )
        self.sw_youtube_6s = self._add_base_switch_row(
            base_vbox,
            "require_youtube_6s",
            "تست بقای ۶ ثانیه‌ای استریم یوتیوب",
            "تایید پایداری واقعی تبادل داده پس از هندشیک اولیه برای جلوگیری از فریز تصویر",
            True,
        )
        self.sw_upload_stream = self._add_base_switch_row(
            base_vbox,
            "verify_upload_stream",
            "ارزیابی سلامت جریان آپلود",
            "سنجش عبور بدون اختلال درخواست‌های حجیم خروجی روی مسیر انتخاب‌شده",
            True,
        )
        self.sw_watchdog = self._add_base_switch_row(
            base_vbox,
            "self_healing_watchdog",
            "نگهبان ترمیم خودکار اتصال در پس‌زمینه (Self-Healing Watchdog)",
            "پایش پیوسته کیفیت تونل و سوییچ بی‌وقفه در صورت افت سرعت یا قطع مسیر",
            True,
        )
        body_layout.addWidget(base_card)

        self.adv_accordion = CollapsibleAccordion(
            title="تنظیمات پیشرفته هسته و فرگمنت",
            subtitle="حالت موتور، فرگمنت بومی Xray، اثرانگشت TLS، مالتی‌پلکسینگ و پورت‌های محلی",
            expanded=False,
        )
        adv = self.adv_accordion.body_layout

        mode_row = QHBoxLayout()
        mode_lbl = QLabel("حالت عملیاتی موتور:")
        mode_lbl.setObjectName("SecondaryLabel")
        self.engine_mode_combo = QComboBox()
        self.engine_mode_combo.addItem("ترکیبی هوشمند خودکار (Auto Hybrid)", "auto_hybrid")
        self.engine_mode_combo.addItem("فقط فرگمنت بومی (Fragment Only)", "fragment_only")
        self.engine_mode_combo.addItem("فقط موتور اختصاصی هسته (Core Engine Only)", "proprietary_only")
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.engine_mode_combo, 1)
        adv.addLayout(mode_row)

        frag_box = QFrame()
        frag_box.setObjectName("SubtleCard")
        frag_vbox = QVBoxLayout(frag_box)
        frag_vbox.setContentsMargins(14, 12, 14, 12)
        frag_vbox.setSpacing(10)

        frag_top = QHBoxLayout()
        frag_title = QLabel("فرگمنت بومی Xray (Native Fragment)")
        frag_title.setFont(make_ui_font(10, QFont.Weight.Bold))
        self.sw_fragment_enabled = AnimatedToggleSwitch(checked=True)
        self.sw_fragment_enabled.toggled.connect(self._emit_changes)
        self._switches.append(self.sw_fragment_enabled)

        btn_preset_micro = QPushButton("پروفایل فرگمنت میکرو ۵-۱۶")
        btn_preset_micro.setObjectName("GhostPillBtn")
        btn_preset_micro.clicked.connect(lambda: self._apply_fragment_preset("tlshello", "5-16", "2-3"))

        btn_preset_win5 = QPushButton("پروفایل پنجره ۵ بایتی")
        btn_preset_win5.setObjectName("GhostPillBtn")
        btn_preset_win5.clicked.connect(lambda: self._apply_fragment_preset("1-3", "5-5", "15-25"))

        frag_top.addWidget(frag_title)
        frag_top.addSpacing(8)
        frag_top.addWidget(self.sw_fragment_enabled)
        frag_top.addStretch()
        frag_top.addWidget(btn_preset_micro)
        frag_top.addWidget(btn_preset_win5)
        frag_vbox.addLayout(frag_top)

        frag_grid = QGridLayout()
        frag_grid.setHorizontalSpacing(12)
        frag_grid.setVerticalSpacing(6)

        self.frag_packets_combo = QComboBox()
        for pkt in ("tlshello", "1-3", "1-5"):
            self.frag_packets_combo.addItem(pkt, pkt)
        enforce_english_ltr(self.frag_packets_combo, mono_size=10)

        self.frag_length_edit = QLineEdit("5-16")
        enforce_english_ltr(self.frag_length_edit, mono_size=10)

        self.frag_interval_edit = QLineEdit("2-3")
        enforce_english_ltr(self.frag_interval_edit, mono_size=10)

        frag_grid.addWidget(self._sec_lbl("بسته‌های هدف (Packets):"), 0, 0)
        frag_grid.addWidget(self._sec_lbl("طول تکه بایت (Length):"), 0, 1)
        frag_grid.addWidget(self._sec_lbl("وقفه ارسال (Interval ms):"), 0, 2)
        frag_grid.addWidget(self.frag_packets_combo, 1, 0)
        frag_grid.addWidget(self.frag_length_edit, 1, 1)
        frag_grid.addWidget(self.frag_interval_edit, 1, 2)
        frag_vbox.addLayout(frag_grid)
        adv.addWidget(frag_box)

        net_grid = QGridLayout()
        net_grid.setHorizontalSpacing(14)
        net_grid.setVerticalSpacing(8)

        self.fingerprint_combo = QComboBox()
        for fp in ("chrome", "safari", "firefox", "ios"):
            self.fingerprint_combo.addItem(fp, fp)
        enforce_english_ltr(self.fingerprint_combo, mono_size=10)

        self.alpn_combo = QComboBox()
        for alpn in ("auto", "http/1.1", "h2,http/1.1"):
            self.alpn_combo.addItem(alpn, alpn)
        enforce_english_ltr(self.alpn_combo, mono_size=10)

        self.early_data_combo = QComboBox()
        for ed in (0, 2048, 2560):
            self.early_data_combo.addItem(f"{ed} Bytes" if (ed > 0) else "0 (Disabled)", ed)
        enforce_english_ltr(self.early_data_combo, mono_size=10)
        self.early_data_combo.setCurrentIndex(1)

        mux_wrap = QWidget()
        mux_row = QHBoxLayout(mux_wrap)
        mux_row.setContentsMargins(0, 0, 0, 0)
        mux_row.setSpacing(10)
        self.sw_mux_enabled = AnimatedToggleSwitch(checked=False)
        self.sw_mux_enabled.toggled.connect(self._emit_changes)
        self._switches.append(self.sw_mux_enabled)
        self.mux_concurrency_spin = QSpinBox()
        self.mux_concurrency_spin.setRange(1, 64)
        self.mux_concurrency_spin.setValue(8)
        self.mux_concurrency_spin.setPrefix("Concurrency: ")
        enforce_english_ltr(self.mux_concurrency_spin, mono_size=10)
        mux_row.addWidget(self.sw_mux_enabled)
        mux_row.addWidget(self.mux_concurrency_spin, 1)

        self.manual_vector_combo = QComboBox()
        enforce_english_ltr(self.manual_vector_combo, mono_size=10)
        self.set_vectors([])

        self.stride_spin = QSpinBox()
        self.stride_spin.setRange(0, 8192)
        self.stride_spin.setSingleStep(50)
        self.stride_spin.setValue(400)
        self.stride_spin.setSuffix(" B")
        enforce_english_ltr(self.stride_spin, mono_size=10)

        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(0, 2048)
        self.jitter_spin.setSingleStep(8)
        self.jitter_spin.setValue(32)
        self.jitter_spin.setSuffix(" B")
        enforce_english_ltr(self.jitter_spin, mono_size=10)

        self.socks_port_spin = QSpinBox()
        self.socks_port_spin.setRange(1024, 65535)
        self.socks_port_spin.setValue(10808)
        enforce_english_ltr(self.socks_port_spin, mono_size=10)

        self.http_port_spin = QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.http_port_spin.setValue(10809)
        enforce_english_ltr(self.http_port_spin, mono_size=10)

        pairs = [
            ("اثرانگشت TLS (Fingerprint):", self.fingerprint_combo, 0, 0),
            ("تنظیم ALPN Override:", self.alpn_combo, 0, 1),
            ("حجم WebSocket EarlyData:", self.early_data_combo, 1, 0),
            ("مالتی‌پلکسینگ (Mux & Concurrency):", mux_wrap, 1, 1),
            ("انتخاب دستی بردار عبوری:", self.manual_vector_combo, 2, 0),
            ("گام پیشروی بایت (Forward Stride):", self.stride_spin, 2, 1),
            ("دامنه تغییرات گام (Stride Jitter):", self.jitter_spin, 3, 0),
            ("پورت محلی SOCKS5:", self.socks_port_spin, 3, 1),
            ("پورت محلی HTTP Proxy:", self.http_port_spin, 4, 0),
        ]

        for title_txt, widget, r, c in pairs:
            net_grid.addWidget(self._sec_lbl(title_txt), r * 2, c)
            net_grid.addWidget(widget, r * 2 + 1, c)

        adv.addLayout(net_grid)
        body_layout.addWidget(self.adv_accordion)
        body_layout.addStretch()

        self.scroll = make_transparent_scroll_area(body)
        outer.addWidget(self.scroll, 1)

        for combo in (
            self.engine_mode_combo,
            self.frag_packets_combo,
            self.fingerprint_combo,
            self.alpn_combo,
            self.early_data_combo,
            self.manual_vector_combo,
        ):
            combo.currentIndexChanged.connect(self._emit_changes)

        for edit in (self.frag_length_edit, self.frag_interval_edit):
            edit.editingFinished.connect(self._emit_changes)

        for sp in (
            self.mux_concurrency_spin,
            self.stride_spin,
            self.jitter_spin,
            self.socks_port_spin,
            self.http_port_spin,
        ):
            sp.valueChanged.connect(self._emit_changes)

    def bind_controller(self, controller) -> None:
        self._controller = controller
        if controller is not None:
            getter = getattr(controller, "get_settings", None)
            if callable(getter):
                raw_settings = getter()
                if isinstance(raw_settings, dict):
                    self.apply_settings_dict(raw_settings)

    def _sec_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SecondaryLabel")
        return lbl

    def _add_base_switch_row(
        self,
        parent_layout: QVBoxLayout,
        setting_key: str,
        title: str,
        desc: str,
        default: bool,
    ) -> AnimatedToggleSwitch:
        row = QHBoxLayout()
        row.setSpacing(12)
        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        t = QLabel(title)
        t.setFont(make_ui_font(10, QFont.Weight.Bold))
        d = QLabel(desc)
        d.setObjectName("MutedLabel")
        txt_col.addWidget(t)
        txt_col.addWidget(d)

        sw = AnimatedToggleSwitch(checked=bool(default))
        sw.toggled.connect(lambda checked, k=setting_key: self._on_base_switch_toggled(k, checked))
        self._switches.append(sw)

        row.addLayout(txt_col, 1)
        row.addWidget(sw)
        parent_layout.addLayout(row)
        return sw

    def _on_base_switch_toggled(self, key: str, checked: bool):
        if self._updating:
            return
        state = bool(checked)
        if self._controller is not None:
            slot_name = self.BASE_SWITCH_SLOTS.get(key, f"set_{key}")
            setter = getattr(self._controller, slot_name, None)
            if callable(setter):
                setter(state)
            else:
                updater = getattr(self._controller, "update_settings", None)
                if callable(updater):
                    updater({key: state})
        self.base_switch_toggled.emit(key, state)

    def _apply_fragment_preset(self, packets: str, length: str, interval: str):
        self._updating = True
        self.sw_fragment_enabled.set_CheckedSilent(True)
        idx = self.frag_packets_combo.findData(packets)
        if idx >= 0:
            self.frag_packets_combo.setCurrentIndex(idx)
        self.frag_length_edit.setText(length)
        self.frag_interval_edit.setText(interval)
        self._updating = False
        self._emit_changes()

    def set_vectors(self, vectors: list):
        prev_val = self.manual_vector_combo.currentData()
        self._updating = True
        self.manual_vector_combo.clear()
        if not vectors:
            for i in range(1, 17):
                vid = f"VEC-{i:02d}"
                self.manual_vector_combo.addItem(vid, vid)
        else:
            for v in vectors:
                if isinstance(v, dict):
                    vid = pick_first_text(v, ("id", "vector_id", "code"), "VEC-01")
                    vname = sanitize_ui_text(pick_first_text(v, ("name", "title"), ""))
                    label = f"{vid} | {vname}" if (vname and (vname != vid)) else vid
                elif isinstance(v, str):
                    vid = v
                    label = sanitize_ui_text(v)
                else:
                    vid = str(getattr(v, "id", getattr(v, "vector_id", str(v))))
                    vname = sanitize_ui_text(str(getattr(v, "name", "")))
                    label = f"{vid} | {vname}" if vname else vid
                self.manual_vector_combo.addItem(label, vid)
        if prev_val is not None:
            idx = self.manual_vector_combo.findData(prev_val)
            if idx >= 0:
                self.manual_vector_combo.setCurrentIndex(idx)
        self._updating = False

    def set_autopilot_mode(self, autopilot_enabled: bool):
        self.manual_vector_combo.setEnabled(not bool(autopilot_enabled))

    def apply_settings_dict(self, s: dict):
        if not isinstance(s, dict):
            return
        self._updating = True
        try:
            self.sw_auto_clean_ip.set_CheckedSilent(
                get_bool_value(s, "auto_clean_ip", self.sw_auto_clean_ip.isChecked())
            )
            self.sw_youtube_6s.set_CheckedSilent(
                get_bool_value(s, "require_youtube_6s", self.sw_youtube_6s.isChecked())
            )
            self.sw_upload_stream.set_CheckedSilent(
                get_bool_value(s, "verify_upload_stream", self.sw_upload_stream.isChecked())
            )
            self.sw_watchdog.set_CheckedSilent(
                get_bool_value(s, "self_healing_watchdog", self.sw_watchdog.isChecked())
            )
            self.sw_fragment_enabled.set_CheckedSilent(
                get_bool_value(s, "fragment_enabled", self.sw_fragment_enabled.isChecked())
            )
            self.sw_mux_enabled.set_CheckedSilent(
                get_bool_value(s, "mux_enabled", self.sw_mux_enabled.isChecked())
            )

            self._select_combo_data(self.engine_mode_combo, s.get("engine_mode", None))
            self._select_combo_data(self.frag_packets_combo, s.get("fragment_packets", None))
            self._select_combo_data(self.fingerprint_combo, s.get("fingerprint", None))
            self._select_combo_data(self.alpn_combo, s.get("alpn_override", None))
            if ("ws_early_data" in s) and (s["ws_early_data"] is not None):
                self._select_combo_data(
                    self.early_data_combo,
                    parse_int_value(s.get("ws_early_data", 2048), 2048),
                )
            self._select_combo_data(self.manual_vector_combo, s.get("manual_vector_id", None))

            if ("fragment_length" in s) and (s["fragment_length"] is not None):
                self.frag_length_edit.setText(str(s["fragment_length"]))
            if ("fragment_interval" in s) and (s["fragment_interval"] is not None):
                self.frag_interval_edit.setText(str(s["fragment_interval"]))
            if ("mux_concurrency" in s) and (s["mux_concurrency"] is not None):
                self.mux_concurrency_spin.setValue(parse_int_value(s.get("mux_concurrency", 8), 8))
            if ("forward_stride_bytes" in s) and (s["forward_stride_bytes"] is not None):
                self.stride_spin.setValue(parse_int_value(s.get("forward_stride_bytes", 400), 400))
            if ("stride_jitter_bytes" in s) and (s["stride_jitter_bytes"] is not None):
                self.jitter_spin.setValue(parse_int_value(s.get("stride_jitter_bytes", 32), 32))
            if ("socks_port" in s) and (s["socks_port"] is not None):
                self.socks_port_spin.setValue(parse_int_value(s.get("socks_port", 10808), 10808))
            if ("http_port" in s) and (s["http_port"] is not None):
                self.http_port_spin.setValue(parse_int_value(s.get("http_port", 10809), 10809))

            if "autopilot" in s:
                self.set_autopilot_mode(get_bool_value(s, "autopilot", True))
        finally:
            self._updating = False

    def _select_combo_data(self, combo: QComboBox, value):
        if value is None:
            return
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findText(str(value))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def collect_settings(self) -> dict:
        frag_len = self.frag_length_edit.text().strip()
        if not frag_len:
            frag_len = "5-16"
        frag_int = self.frag_interval_edit.text().strip()
        if not frag_int:
            frag_int = "2-3"
        early_data_raw = self.early_data_combo.currentData()
        vec_raw = self.manual_vector_combo.currentData()
        vec_id = str(vec_raw) if (vec_raw is not None and str(vec_raw).strip()) else "VEC-01"

        return {
            "auto_clean_ip": bool(self.sw_auto_clean_ip.isChecked()),
            "require_youtube_6s": bool(self.sw_youtube_6s.isChecked()),
            "verify_upload_stream": bool(self.sw_upload_stream.isChecked()),
            "self_healing_watchdog": bool(self.sw_watchdog.isChecked()),
            "engine_mode": self.engine_mode_combo.currentData(),
            "fragment_enabled": bool(self.sw_fragment_enabled.isChecked()),
            "fragment_packets": self.frag_packets_combo.currentData(),
            "fragment_length": frag_len,
            "fragment_interval": frag_int,
            "fingerprint": self.fingerprint_combo.currentData(),
            "alpn_override": self.alpn_combo.currentData(),
            "ws_early_data": parse_int_value(early_data_raw, 0),
            "mux_enabled": bool(self.sw_mux_enabled.isChecked()),
            "mux_concurrency": int(self.mux_concurrency_spin.value()),
            "manual_vector_id": vec_id,
            "forward_stride_bytes": int(self.stride_spin.value()),
            "stride_jitter_bytes": int(self.jitter_spin.value()),
            "socks_port": int(self.socks_port_spin.value()),
            "http_port": int(self.http_port_spin.value()),
        }

    def _emit_changes(self, *_args):
        if not self._updating:
            self.settings_updated.emit(self.collect_settings())

    def set_palette_theme(self, palette: ThemePalette):
        self._palette = palette
        self.adv_accordion.set_palette_theme(palette)
        for sw in self._switches:
            sw.set_palette_theme(palette)


class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_lines: list[str] = []
        self._query = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(12)

        top_bar = QHBoxLayout()
        title = QLabel("گزارش زنده موتور Alan-RIP-Dpi")
        title.setFont(make_ui_font(15, QFont.Weight.ExtraBold))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("فیلتر و جستجو در لاگ...")
        self.search_edit.setMaximumWidth(260)
        enforce_english_ltr(self.search_edit, mono_size=10)
        self.search_edit.textChanged.connect(self._on_filter_changed)

        self.copy_btn = QPushButton("کپی همه")
        self.copy_btn.setObjectName("GhostPillBtn")
        self.copy_btn.clicked.connect(self._copy_logs)

        self.clear_btn = QPushButton("پاکسازی")
        self.clear_btn.setObjectName("GhostPillBtn")
        self.clear_btn.clicked.connect(self._clear_logs)

        self.save_btn = QPushButton("ذخیره در فایل")
        self.save_btn.setObjectName("AccentBtn")
        self.save_btn.clicked.connect(self._save_logs)

        top_bar.addWidget(title)
        top_bar.addStretch()
        top_bar.addWidget(self.search_edit)
        top_bar.addWidget(self.copy_btn)
        top_bar.addWidget(self.clear_btn)
        top_bar.addWidget(self.save_btn)
        root.addLayout(top_bar)

        self.console = QPlainTextEdit()
        self.console.setObjectName("LogConsole")
        self.console.setReadOnly(True)
        enforce_english_ltr(self.console, mono_size=10)
        root.addWidget(self.console, 1)

    def append_line(self, line: str):
        clean_line = sanitize_ui_text(line)
        self._all_lines.append(clean_line)
        if len(self._all_lines) > 5000:
            self._all_lines = self._all_lines[-5000:]

        if (not self._query) or (self._query in clean_line.lower()):
            self.console.appendPlainText(clean_line)
            sb = self.console.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_filter_changed(self, text: str):
        self._query = text.strip().lower()
        self.console.setUpdatesEnabled(False)
        try:
            if not self._query:
                self.console.setPlainText("\n".join(self._all_lines))
            else:
                filtered = [ln for ln in self._all_lines if self._query in ln.lower()]
                self.console.setPlainText("\n".join(filtered))
            sb = self.console.verticalScrollBar()
            sb.setValue(sb.maximum())
        finally:
            self.console.setUpdatesEnabled(True)

    def _copy_logs(self):
        QGuiApplication.clipboard().setText(self.console.toPlainText())

    def _clear_logs(self):
        self._all_lines.clear()
        self.console.clear()

    def _save_logs(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره گزارش Alan-RIP-Dpi",
            "alan-rip-dpi.log",
            "Log Files (*.log *.txt)",
        )
        if file_path:
            Path(file_path).write_text(self.console.toPlainText(), encoding="utf-8")