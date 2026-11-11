import os
from pathlib import Path
from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .animated_widgets import (
    ActionPillButton,
    AnimatedRadarCore,
    AnimatedToggleSwitch,
    KineticConnectButton,
    LiveSparklineWidget,
    NeuCard,
    RouteTopologyStrip,
    SegmentedControl,
    SpoilerChronometer,
    VectorIconButton,
    draw_neu_inset,
    draw_neu_raised,
)
from .flag_icons import FlagBadgeWidget, GeoFlagResolver, make_flag_qicon
from .theme import (
    DARK_PALETTE,
    I18N,
    ThemePalette,
    apply_windows_titlebar_theme,
    enforce_english_ltr,
    get_bool,
    get_int,
    lock_widget_dimensions,
    make_mono_font,
    make_transparent_scroll_area,
    make_ui_font,
    strip_emojis,
)
from .vector_icons import VectorIconPainter, make_vector_qicon

SUB_UPDATE_INTERVAL_HOURS: tuple[int, ...] = (0, 1, 3, 6, 12, 24)

DEFAULT_FINGERPRINTS: list[tuple[str, str]] = [
    ("custom_poly", "Custom Polymorphic"),
    ("random", "random"),
    ("chrome", "chrome"),
    ("firefox", "firefox"),
    ("safari", "safari"),
    ("ios", "ios"),
    ("edge", "edge"),
    ("qq", "qq"),
    ("android", "android"),
    ("360", "360"),
]


def set_switch_blocked(sw: AnimatedToggleSwitch, checked: bool) -> None:
    state = bool(checked)
    with QSignalBlocker(sw):
        anim = getattr(sw, "_anim", None)
        if anim is not None:
            anim.stop()
        sw.setChecked(state)
        sw._offset = 1.0 if state else 0.0
    sw.update()


def normalize_vector_entries(vectors: list | None) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in vectors or []:
        if isinstance(item, dict):
            vid = str(item.get("vector_id") or item.get("id") or item.get("code") or "").strip()
            cname = strip_emojis(str(item.get("code_name") or item.get("name") or item.get("title") or "").strip())
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            vid = str(item[0]).strip()
            cname = strip_emojis(str(item[1]).strip())
        else:
            vid = str(getattr(item, "vector_id", getattr(item, "id", item)) or "").strip()
            cname = strip_emojis(str(getattr(item, "code_name", getattr(item, "name", "")) or "").strip())

        if not vid or vid in seen:
            continue
        seen.add(vid)
        label = f"{vid} — {cname}" if (cname and cname != vid) else vid
        entries.append((vid, label))
    return entries


def normalize_fingerprint_entries(fingerprints: list | None) -> list[tuple[str, str]]:
    if not fingerprints:
        return list(DEFAULT_FINGERPRINTS)

    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in fingerprints:
        if isinstance(item, dict):
            val = str(
                item.get("value")
                or item.get("id")
                or item.get("key")
                or item.get("fingerprint")
                or ""
            ).strip()
            lbl = strip_emojis(
                str(
                    item.get("label")
                    or item.get("name")
                    or item.get("title")
                    or val
                ).strip()
            )
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            val = str(item[0]).strip()
            lbl = strip_emojis(str(item[1]).strip())
        else:
            val = str(item or "").strip()
            lbl = val

        if not val or val in seen:
            continue
        seen.add(val)
        if val == "custom_poly" and (not lbl or lbl == "custom_poly"):
            lbl = "Custom Polymorphic"
        entries.append((val, lbl or val))

    return entries if entries else list(DEFAULT_FINGERPRINTS)


def extract_profile_uid(prof: dict, fallback_idx: int = 0) -> str:
    for key in ("uid", "profile_uid", "id"):
        val = prof.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return str(fallback_idx)


def extract_profile_group(prof: dict) -> str:
    for key in ("group", "group_tag", "subscription", "sub_tag", "sub_title"):
        val = prof.get(key)
        if val is not None and str(val).strip():
            return strip_emojis(str(val).strip())
    return "Manual"


def format_rate_kbps(kbps: float) -> str:
    if kbps <= 0.0:
        return "0 B/s"
    if kbps >= 1024.0:
        return f"{kbps / 1024.0:.2f} MB/s"
    if kbps < 1.0:
        return f"{kbps * 1024.0:.0f} B/s"
    return f"{kbps:.1f} KB/s"


def is_gemini_verified(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if get_bool(item, "gemini_ok", False) or get_bool(item, "gemini_ready", False):
        return True
    st = str(item.get("gemini_status") or "").strip().upper()
    return st in ("OK", "READY", "VERIFIED", "TRUE", "PASSED", "GEMINI")


class VectorGlyph(QWidget):
    def __init__(self, icon_name: str, size: int = 26, custom_hex: str | None = None, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._custom_hex = custom_hex
        self._palette: ThemePalette = DARK_PALETTE
        lock_widget_dimensions(self, size, size)

    def set_palette_theme(self, palette: ThemePalette, custom_hex: str | None = None) -> None:
        self._palette = palette
        if custom_hex:
            self._custom_hex = custom_hex
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        well = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        col = QColor(self._custom_hex) if self._custom_hex else QColor(self._palette.accent_primary)
        draw_neu_inset(painter, well, well.height() / 2.0, self._palette, depth=2.2)
        pad = self.width() * 0.24
        VectorIconPainter.draw_icon(
            painter,
            self._icon_name,
            QRectF(pad, pad, self.width() - 2.0 * pad, self.height() - 2.0 * pad),
            col,
            stroke=1.65,
        )


class NeuGroupTabButton(QPushButton):
    def __init__(self, text: str, palette: ThemePalette, parent=None):
        super().__init__(text, parent)
        self._palette = palette
        self._hovered = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)
        self._sync_width()

    def _sync_width(self) -> None:
        self.setFont(make_ui_font(9, QFont.Weight.Bold))
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(fm.horizontalAdvance(self.text()) + 28)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._sync_width()
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
        rect = QRectF(2.5, 2.0, self.width() - 5.0, self.height() - 4.0)
        accent = QColor(self._palette.accent_primary)

        if self.isChecked():
            draw_neu_raised(painter, rect, 9.5, self._palette, depth=2.8, accent_tint=accent)
            line_w = min(22.0, rect.width() * 0.42)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(
                QRectF(rect.center().x() - line_w / 2.0, rect.bottom() - 3.0, line_w, 2.0),
                1.0,
                1.0,
            )
            fg = accent if self._palette.is_dark else QColor("#9A6700")
            painter.setFont(make_ui_font(9, QFont.Weight.ExtraBold))
        else:
            if self._hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 20))
                painter.drawRoundedRect(rect, 9.5, 9.5)
            fg = QColor(self._palette.text_primary) if self._hovered else QColor(self._palette.text_muted)
            painter.setFont(make_ui_font(9, QFont.Weight.DemiBold))

        painter.setPen(fg)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class BaseThemedDialog(QDialog):
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
        self.setLayoutDirection(I18N.layout_direction())
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_windows_titlebar_theme(self, self._palette.is_dark)


class HuntSubscriptionDialog(BaseThemedDialog):
    def __init__(
        self,
        subscriptions: list,
        groups: list[str],
        palette: ThemePalette,
        parent=None,
    ):
        super().__init__(I18N.t("hunt_sub_dlg_title"), palette, parent)
        self._palette = palette
        self.setMinimumSize(520, 310)
        self.resize(560, 330)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(12)

        hdr_lbl = QLabel(I18N.t("hunt_sub_dlg_title"))
        hdr_lbl.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        root.addWidget(hdr_lbl)

        desc_lbl = QLabel(I18N.t("hunt_sub_dlg_desc"))
        desc_lbl.setObjectName("MutedLabel")
        desc_lbl.setWordWrap(True)
        root.addWidget(desc_lbl)

        card = NeuCard(mode="raised", radius=16.0, depth=4.6, pad=5.5)
        card.set_palette_theme(palette)
        form = QVBoxLayout(card)
        form.setContentsMargins(18, 14, 18, 16)
        form.setSpacing(10)

        existing_lbl = QLabel(I18N.t("hunt_sub_choose_existing"))
        existing_lbl.setObjectName("SecondaryLabel")
        self.existing_combo = QComboBox()
        self.existing_combo.addItem(I18N.t("hunt_sub_new_url_opt"), "")

        seen_titles: set[str] = set()
        for sub in subscriptions or []:
            if isinstance(sub, dict):
                t = strip_emojis(str(sub.get("title") or sub.get("name") or "")).strip()
                u = str(sub.get("url") or "").strip()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    self.existing_combo.addItem(f"{t} ({u[:36]}...)" if len(u) > 36 else f"{t} ({u})", t)
        for g in groups or []:
            g_clean = strip_emojis(str(g or "")).strip()
            if g_clean and g_clean not in ("Manual", "__ALL__") and g_clean not in seen_titles:
                seen_titles.add(g_clean)
                self.existing_combo.addItem(g_clean, g_clean)

        if self.existing_combo.count() > 1:
            self.existing_combo.setCurrentIndex(1)
        self.existing_combo.currentIndexChanged.connect(self._sync_inputs)

        url_lbl = QLabel(I18N.t("hunt_sub_url_lbl"))
        url_lbl.setObjectName("SecondaryLabel")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(I18N.t("subs_url_ph"))
        enforce_english_ltr(self.url_edit, mono_size=10)
        clip_txt = QGuiApplication.clipboard().text().strip()
        if clip_txt.startswith("http://") or clip_txt.startswith("https://"):
            self.url_edit.setText(clip_txt)
            self.existing_combo.setCurrentIndex(0)

        title_lbl = QLabel(I18N.t("hunt_sub_title_lbl"))
        title_lbl.setObjectName("SecondaryLabel")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(I18N.t("subs_title_ph"))

        form.addWidget(existing_lbl)
        form.addWidget(self.existing_combo)
        form.addWidget(url_lbl)
        form.addWidget(self.url_edit)
        form.addWidget(title_lbl)
        form.addWidget(self.title_edit)
        root.addWidget(card, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton(I18N.t("cancel"))
        cancel_btn.setObjectName("GhostBtn")
        cancel_btn.clicked.connect(self.reject)

        self.start_btn = ActionPillButton("bolt", I18N.t("hunt_sub_start_btn"), variant="gold")
        self.start_btn.set_palette_theme(palette)
        self.start_btn.clicked.connect(self._on_confirm)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.start_btn)
        root.addLayout(btn_row)

        self._sync_inputs()

    def _sync_inputs(self, *_args) -> None:
        is_new_url = not bool(self.existing_combo.currentData())
        self.url_edit.setEnabled(is_new_url)
        self.title_edit.setEnabled(is_new_url)

    def _on_confirm(self) -> None:
        sub_target, _ = self.collected_target()
        if sub_target:
            self.accept()

    def collected_target(self) -> tuple[str, str]:
        url_txt = self.url_edit.text().strip()
        title_txt = self.title_edit.text().strip()
        existing_tag = str(self.existing_combo.currentData() or "").strip()
        if url_txt and (not existing_tag or self.url_edit.isEnabled()):
            return url_txt, title_txt
        if existing_tag:
            return existing_tag, existing_tag
        return url_txt, title_txt


class SubscriptionManagerDialog(BaseThemedDialog):
    add_requested = Signal(str, str)
    refresh_requested = Signal()
    delete_requested = Signal(int)
    auto_update_hours_changed = Signal(int)
    hunt_subscription_requested = Signal(str, str)

    def __init__(
        self,
        subscriptions: list,
        auto_update_hours: int,
        palette: ThemePalette,
        parent=None,
    ):
        super().__init__(I18N.t("subs_dlg_title"), palette, parent)
        self._palette = palette
        self._item_cards: list[NeuCard] = []
        self.setMinimumSize(620, 440)
        self.resize(680, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(12)

        hdr_row = QHBoxLayout()
        hdr_lbl = QLabel(I18N.t("subs_dlg_title"))
        hdr_lbl.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        self.refresh_btn = ActionPillButton("refresh", I18N.t("subs_refresh_btn"), variant="ghost")
        self.refresh_btn.set_palette_theme(palette)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        hdr_row.addWidget(hdr_lbl)
        hdr_row.addStretch()
        hdr_row.addWidget(self.refresh_btn)
        root.addLayout(hdr_row)

        self.add_card = NeuCard(mode="raised", radius=16.0, depth=4.5, pad=5.5)
        self.add_card.set_palette_theme(palette)
        add_row = QHBoxLayout(self.add_card)
        add_row.setContentsMargins(16, 13, 16, 13)
        add_row.setSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(I18N.t("subs_title_ph"))
        self.title_edit.setMaximumWidth(175)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(I18N.t("subs_url_ph"))
        enforce_english_ltr(self.url_edit, mono_size=10)

        self.add_btn = QPushButton(I18N.t("subs_add_btn"))
        self.add_btn.setObjectName("AccentBtn")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add)

        self.hunt_input_btn = ActionPillButton("bolt", I18N.t("hunt_sub_btn"), variant="gold")
        self.hunt_input_btn.set_palette_theme(palette)
        self.hunt_input_btn.clicked.connect(self._on_hunt_from_input)

        add_row.addWidget(self.title_edit)
        add_row.addWidget(self.url_edit, 1)
        add_row.addWidget(self.add_btn)
        add_row.addWidget(self.hunt_input_btn)
        root.addWidget(self.add_card)

        sched_row = QHBoxLayout()
        sched_lbl = QLabel(I18N.t("sub_autoupdate_lbl"))
        sched_lbl.setObjectName("SecondaryLabel")
        self.sched_combo = QComboBox()
        for hrs in SUB_UPDATE_INTERVAL_HOURS:
            lbl = I18N.t("sub_off") if hrs == 0 else I18N.t("sub_every_h", h=hrs)
            self.sched_combo.addItem(lbl, hrs)
        idx_h = self.sched_combo.findData(int(auto_update_hours or 0))
        if idx_h >= 0:
            self.sched_combo.setCurrentIndex(idx_h)
        self.sched_combo.currentIndexChanged.connect(self._on_sched_changed)
        sched_row.addWidget(sched_lbl)
        sched_row.addWidget(self.sched_combo)
        sched_row.addStretch()
        root.addLayout(sched_row)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 2, 4, 2)
        self.list_layout.setSpacing(8)
        root.addWidget(make_transparent_scroll_area(self.list_host), 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton(I18N.t("close"))
        close_btn.setObjectName("GhostBtn")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        self.populate_subscriptions(subscriptions)

    def _on_add(self) -> None:
        url = self.url_edit.text().strip()
        title = self.title_edit.text().strip() or "Subscription"
        if url:
            self.add_requested.emit(url, title)
            self.url_edit.clear()
            self.title_edit.clear()

    def _on_hunt_from_input(self) -> None:
        url = self.url_edit.text().strip()
        title = self.title_edit.text().strip() or "Subscription"
        if url:
            self.hunt_subscription_requested.emit(url, title)
            self.accept()
            return
        clip_txt = QGuiApplication.clipboard().text().strip()
        if clip_txt.startswith("http://") or clip_txt.startswith("https://"):
            self.hunt_subscription_requested.emit(clip_txt, title)
            self.accept()

    def _trigger_row_hunt(self, sub_target: str, sub_title: str) -> None:
        if sub_target:
            self.hunt_subscription_requested.emit(sub_target, sub_title)
            self.accept()

    def _on_sched_changed(self, idx: int) -> None:
        hrs = self.sched_combo.itemData(idx)
        if hrs is not None:
            self.auto_update_hours_changed.emit(int(hrs))

    def populate_subscriptions(self, subs: list) -> None:
        self.list_host.setUpdatesEnabled(False)
        try:
            self._item_cards.clear()
            while self.list_layout.count():
                item = self.list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            for idx, sub in enumerate(subs or []):
                card = NeuCard(mode="raised", radius=14.0, depth=3.8, pad=4.5)
                card.set_palette_theme(self._palette)
                self._item_cards.append(card)
                row = QHBoxLayout(card)
                row.setContentsMargins(16, 11, 16, 11)
                row.setSpacing(10)

                if isinstance(sub, dict):
                    title = strip_emojis(str(sub.get("title") or sub.get("name") or f"Sub #{idx + 1}"))
                    url = str(sub.get("url") or "")
                else:
                    title = f"Sub #{idx + 1}"
                    url = str(sub)

                t_lbl = QLabel(title)
                t_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))
                u_lbl = QLabel(url)
                u_lbl.setObjectName("MutedLabel")
                enforce_english_ltr(u_lbl, mono_size=9)

                hunt_row_btn = ActionPillButton("bolt", I18N.t("hunt_sub_short_btn"), variant="emerald")
                hunt_row_btn.set_palette_theme(self._palette)
                target_arg = title if title else url
                hunt_row_btn.clicked.connect(
                    lambda _c=False, tg=target_arg, tt=title: self._trigger_row_hunt(tg, tt)
                )

                del_btn = VectorIconButton("trash", size=30, danger_hover=True)
                del_btn.set_palette_theme(self._palette)
                del_btn.clicked.connect(lambda _c=False, i=idx: self.delete_requested.emit(i))

                row.addWidget(t_lbl)
                row.addWidget(u_lbl, 1)
                row.addWidget(hunt_row_btn)
                row.addWidget(del_btn)
                self.list_layout.addWidget(card)

            self.list_layout.addStretch()
        finally:
            self.list_host.setUpdatesEnabled(True)


class ConfigEditorDialog(BaseThemedDialog):
    def __init__(
        self,
        is_new: bool,
        initial_data: dict | None,
        vectors: list | None,
        groups: list[str] | None,
        palette: ThemePalette,
        parent=None,
        fingerprints: list | None = None,
    ):
        title = I18N.t("editor_new_title") if is_new else I18N.t("editor_edit_title")
        super().__init__(title, palette, parent)
        self._initial = dict(initial_data) if isinstance(initial_data, dict) else {}
        self.setMinimumSize(700, 560)
        self.resize(780, 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        top_row = QHBoxLayout()
        hdr_lbl = QLabel(title)
        hdr_lbl.setFont(make_ui_font(13, QFont.Weight.ExtraBold))
        self.flag_preview = FlagBadgeWidget(GeoFlagResolver.resolve_code(self._initial), 32, 21)
        self.flag_preview.set_palette_theme(palette)
        top_row.addWidget(hdr_lbl)
        top_row.addStretch()
        top_row.addWidget(self.flag_preview)
        root.addLayout(top_row)

        host_w = QWidget()
        form_vbox = QVBoxLayout(host_w)
        form_vbox.setContentsMargins(0, 2, 6, 4)
        form_vbox.setSpacing(12)

        self.fields_card = NeuCard(mode="raised", radius=18.0, depth=5.0, pad=6.0)
        self.fields_card.set_palette_theme(palette)
        grid = QGridLayout(self.fields_card)
        grid.setContentsMargins(20, 18, 20, 20)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        self.name_edit = QLineEdit(strip_emojis(str(self._initial.get("name") or "")))
        self.name_edit.textChanged.connect(self._refresh_flag)

        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        group_opts = ["Manual"] + [g for g in (groups or []) if g and g != "Manual"]
        for g in dict.fromkeys(group_opts):
            self.group_combo.addItem(g)
        self.group_combo.setCurrentText(extract_profile_group(self._initial))

        self.proto_combo = QComboBox()
        for p_key, p_lbl in (
            ("vless", "VLESS"),
            ("vmess", "VMess"),
            ("trojan", "Trojan"),
            ("ss", "Shadowsocks"),
            ("tuic", "TUIC"),
            ("hysteria2", "Hysteria2"),
        ):
            self.proto_combo.addItem(p_lbl, p_key)
        enforce_english_ltr(self.proto_combo, mono_size=10, bold=True)

        addr_init = str(self._initial.get("host") or self._initial.get("original_host") or self._initial.get("address") or "")
        self.addr_edit = QLineEdit(addr_init)
        enforce_english_ltr(self.addr_edit, mono_size=10)
        self.addr_edit.textChanged.connect(self._refresh_flag)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        port_init = get_int(self._initial, "port", 443)
        self.port_spin.setValue(port_init if 1 <= port_init <= 65535 else 443)
        enforce_english_ltr(self.port_spin, mono_size=10)

        cred_init = str(self._initial.get("uuid_or_password") or self._initial.get("uuid") or self._initial.get("password") or "")
        self.cred_edit = QLineEdit(cred_init)
        enforce_english_ltr(self.cred_edit, mono_size=10)

        self.vec_combo = QComboBox()
        enforce_english_ltr(self.vec_combo, mono_size=10, bold=True)
        self.vec_combo.addItem("AUTO", "AUTO")
        for vid, vlabel in normalize_vector_entries(vectors):
            self.vec_combo.addItem(vlabel, vid)

        self.net_combo = QComboBox()
        for n_opt in ("ws", "tcp", "grpc", "httpupgrade", "xhttp", "quic"):
            self.net_combo.addItem(n_opt, n_opt)
        enforce_english_ltr(self.net_combo, mono_size=10)

        self.sec_combo = QComboBox()
        for s_opt in ("tls", "reality", "none"):
            self.sec_combo.addItem(s_opt, s_opt)
        enforce_english_ltr(self.sec_combo, mono_size=10)

        self.sni_edit = QLineEdit(str(self._initial.get("sni") or self._initial.get("server_name") or ""))
        enforce_english_ltr(self.sni_edit, mono_size=10)
        self.sni_edit.textChanged.connect(self._refresh_flag)

        self.host_hdr_edit = QLineEdit(str(self._initial.get("host_header") or ""))
        enforce_english_ltr(self.host_hdr_edit, mono_size=10)

        self.path_edit = QLineEdit(str(self._initial.get("path") or self._initial.get("service_name") or "/"))
        enforce_english_ltr(self.path_edit, mono_size=10)

        self.alpn_combo = QComboBox()
        self.alpn_combo.setEditable(True)
        for a_opt in ("", "h2,http/1.1", "http/1.1", "h2", "h3"):
            self.alpn_combo.addItem(a_opt)
        enforce_english_ltr(self.alpn_combo, mono_size=10)

        self.fp_combo = QComboBox()
        enforce_english_ltr(self.fp_combo, mono_size=10)
        for fp_val, fp_lbl in normalize_fingerprint_entries(fingerprints):
            self.fp_combo.addItem(fp_lbl, fp_val)

        self.pbk_edit = QLineEdit(str(self._initial.get("public_key") or self._initial.get("pbk") or ""))
        enforce_english_ltr(self.pbk_edit, mono_size=10)

        self.sid_edit = QLineEdit(str(self._initial.get("short_id") or self._initial.get("sid") or ""))
        enforce_english_ltr(self.sid_edit, mono_size=10)

        spec = [
            ("Profile Name:", self.name_edit, 0, 0),
            ("Subscription / Group:", self.group_combo, 0, 1),
            ("Protocol:", self.proto_combo, 1, 0),
            ("Bound Method:", self.vec_combo, 1, 1),
            ("Server Host / IP:", self.addr_edit, 2, 0),
            ("Port:", self.port_spin, 2, 1),
            ("UUID / Password:", self.cred_edit, 3, 0),
            ("Transport Network:", self.net_combo, 3, 1),
            ("Security Layer:", self.sec_combo, 4, 0),
            ("TLS SNI:", self.sni_edit, 4, 1),
            ("Host Header:", self.host_hdr_edit, 5, 0),
            ("Path / ServiceName:", self.path_edit, 5, 1),
            ("ALPN:", self.alpn_combo, 6, 0),
            ("uTLS Fingerprint:", self.fp_combo, 6, 1),
            ("Reality PublicKey (pbk):", self.pbk_edit, 7, 0),
            ("Reality ShortId (sid):", self.sid_edit, 7, 1),
        ]
        for lbl_txt, widget, r, c in spec:
            lbl = QLabel(lbl_txt)
            lbl.setObjectName("SecondaryLabel")
            grid.addWidget(lbl, r * 2, c)
            grid.addWidget(widget, r * 2 + 1, c)

        form_vbox.addWidget(self.fields_card)

        self.raw_card = NeuCard(mode="raised", radius=16.0, depth=4.5, pad=5.5)
        self.raw_card.set_palette_theme(palette)
        raw_vbox = QVBoxLayout(self.raw_card)
        raw_vbox.setContentsMargins(18, 14, 18, 16)
        raw_vbox.setSpacing(8)

        raw_hdr = QHBoxLayout()
        raw_lbl = QLabel(I18N.t("editor_use_raw"))
        raw_lbl.setObjectName("SecondaryLabel")
        self.sw_raw = AnimatedToggleSwitch(checked=get_bool(self._initial, "use_raw_uri", False))
        self.sw_raw.set_palette_theme(palette)
        self.sw_raw.toggled.connect(self._sync_raw_mode)
        raw_hdr.addWidget(raw_lbl)
        raw_hdr.addStretch()
        raw_hdr.addWidget(self.sw_raw)
        raw_vbox.addLayout(raw_hdr)

        self.raw_edit = QPlainTextEdit(str(self._initial.get("raw_uri") or self._initial.get("uri") or ""))
        self.raw_edit.setObjectName("CodeEditor")
        self.raw_edit.setMaximumHeight(92)
        enforce_english_ltr(self.raw_edit, mono_size=10)
        raw_vbox.addWidget(self.raw_edit)

        form_vbox.addWidget(self.raw_card)
        form_vbox.addStretch()
        root.addWidget(make_transparent_scroll_area(host_w), 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton(I18N.t("cancel"))
        cancel_btn.setObjectName("GhostBtn")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(I18N.t("save"))
        save_btn.setObjectName("AccentBtn")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        self._apply_initial_combos()
        self._sync_raw_mode(self.sw_raw.isChecked())

    def _apply_initial_combos(self) -> None:
        proto = str(self._initial.get("protocol") or "vless").lower()
        if proto == "shadowsocks":
            proto = "ss"
        idx = self.proto_combo.findData(proto)
        if idx >= 0:
            self.proto_combo.setCurrentIndex(idx)

        for combo, key, default in (
            (self.net_combo, "network", "ws"),
            (self.sec_combo, "security", "tls"),
        ):
            val = str(self._initial.get(key) or default).lower()
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)

        pref_v = str(self._initial.get("preferred_vector_id") or self._initial.get("cached_vector_id") or "AUTO").strip()
        if pref_v and self.vec_combo.findData(pref_v) < 0:
            self.vec_combo.addItem(pref_v, pref_v)
        iv = self.vec_combo.findData(pref_v)
        if iv >= 0:
            self.vec_combo.setCurrentIndex(iv)

        self.alpn_combo.setCurrentText(str(self._initial.get("alpn") or ""))

        init_fp = str(self._initial.get("fingerprint") or "custom_poly").strip()
        if init_fp and self.fp_combo.findData(init_fp) < 0:
            self.fp_combo.addItem(init_fp, init_fp)
        ifp = self.fp_combo.findData(init_fp)
        if ifp >= 0:
            self.fp_combo.setCurrentIndex(ifp)

    def _refresh_flag(self) -> None:
        code = GeoFlagResolver.resolve_code(self.name_edit.text(), self.sni_edit.text(), self.addr_edit.text())
        self.flag_preview.set_country_code(code)

    def _sync_raw_mode(self, use_raw: bool) -> None:
        self.fields_card.setEnabled(not use_raw)
        self.raw_edit.setReadOnly(not use_raw)

    def collect_data(self) -> dict:
        out = dict(self._initial)
        host_txt = self.addr_edit.text().strip()
        raw_txt = self.raw_edit.toPlainText().strip()
        pref_v = str(self.vec_combo.currentData() or "AUTO")
        fp_val = str(self.fp_combo.currentData() or "custom_poly")
        out.update(
            {
                "name": self.name_edit.text().strip() or "Alan Node",
                "group": self.group_combo.currentText().strip() or "Manual",
                "protocol": str(self.proto_combo.currentData() or "vless"),
                "host": host_txt,
                "address": host_txt,
                "port": int(self.port_spin.value()),
                "uuid_or_password": self.cred_edit.text().strip(),
                "network": str(self.net_combo.currentData() or "ws"),
                "security": str(self.sec_combo.currentData() or "tls"),
                "sni": self.sni_edit.text().strip(),
                "host_header": self.host_hdr_edit.text().strip(),
                "path": self.path_edit.text().strip(),
                "alpn": self.alpn_combo.currentText().strip(),
                "fingerprint": fp_val,
                "public_key": self.pbk_edit.text().strip(),
                "pbk": self.pbk_edit.text().strip(),
                "short_id": self.sid_edit.text().strip(),
                "sid": self.sid_edit.text().strip(),
                "preferred_vector_id": pref_v,
                "raw_uri": raw_txt,
                "uri": raw_txt,
                "use_raw_uri": bool(self.sw_raw.isChecked()),
            }
        )
        return out


class CompactTelemetryCard(NeuCard):
    def __init__(
        self,
        i18n_key: str,
        icon_name: str,
        line_hex: str,
        with_sparkline: bool = True,
        stepped: bool = False,
        with_flag: bool = False,
        parent=None,
    ):
        super().__init__(mode="raised", radius=18.0, depth=5.0, pad=6.0, parent=parent)
        self.setMinimumHeight(118)
        self._i18n_key = i18n_key
        self._line_hex = line_hex

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 13, 16, 13)
        vbox.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.glyph = VectorGlyph(icon_name, size=26, custom_hex=line_hex)
        self.title_lbl = QLabel(I18N.t(i18n_key))
        self.title_lbl.setObjectName("MutedLabel")
        self.title_lbl.setFont(make_ui_font(9, QFont.Weight.Bold))
        top.addWidget(self.glyph)
        top.addWidget(self.title_lbl)
        top.addStretch()

        self.flag_badge: FlagBadgeWidget | None = None
        if with_flag:
            self.flag_badge = FlagBadgeWidget("", 28, 19)
            top.addWidget(self.flag_badge)

        self.value_lbl = QLabel("---")
        enforce_english_ltr(self.value_lbl, mono_size=13, bold=True)

        vbox.addLayout(top)
        vbox.addWidget(self.value_lbl)

        self.sparkline: LiveSparklineWidget | None = None
        self.sub_lbl: QLabel | None = None
        if with_sparkline:
            self.sparkline = LiveSparklineWidget(stepped=stepped)
            vbox.addWidget(self.sparkline)
        else:
            self.sub_lbl = QLabel("---")
            self.sub_lbl.setObjectName("SecondaryLabel")
            vbox.addStretch()
            vbox.addWidget(self.sub_lbl)

    def retranslate_ui(self) -> None:
        self.title_lbl.setText(I18N.t(self._i18n_key))
        self.title_lbl.setFont(make_ui_font(9, QFont.Weight.Bold))

    def set_palette_theme(self, palette: ThemePalette) -> None:
        super().set_palette_theme(palette)
        self.glyph.set_palette_theme(palette, self._line_hex)
        if self.flag_badge is not None:
            self.flag_badge.set_palette_theme(palette)
        if self.sparkline is not None:
            self.sparkline.set_palette_theme(palette, self._line_hex)


class HomePage(QWidget):
    connect_triggered = Signal(str)
    disconnect_triggered = Signal()
    output_selection_changed = Signal(str)
    auto_location_changed = Signal(str)
    refresh_auto_pool_requested = Signal()
    ping_verified_requested = Signal()
    clear_verified_requested = Signal()
    system_proxy_toggled = Signal(bool)
    tun_mode_toggled = Signal(bool)
    autopilot_toggled = Signal(bool)

    SMART_AUTO_KEY = "__SMART_AUTO__"
    SMART_POOL_KEY = SMART_AUTO_KEY

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._ui_phase = "IDLE"
        self._is_connected = False
        self._is_connecting = False
        self._autopilot_enabled = True
        self._selected_profile_uid = ""
        self._auto_locations: list[dict] = []
        self._selected_auto_location = "ALL"
        self._verified_outputs: list[dict] = []
        self._vault_profiles: list[dict] = []
        self._last_snap: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 10, 18, 12)
        root.setSpacing(10)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("HeroCard")
        self.hero_card.setStyleSheet("QFrame#HeroCard { background: transparent; border: none; }")
        hero_vbox = QVBoxLayout(self.hero_card)
        hero_vbox.setContentsMargins(30, 22, 30, 20)
        hero_vbox.setSpacing(14)

        center_row = QHBoxLayout()
        center_row.setSpacing(26)

        self.radar_core = AnimatedRadarCore()
        self.radar_core.clicked.connect(self._on_main_button_clicked)

        info_col = QVBoxLayout()
        info_col.setSpacing(10)
        info_col.addStretch()

        title_line = QHBoxLayout()
        title_line.setSpacing(10)
        self.headline_lbl = QLabel(I18N.t("status_idle"))
        self.headline_lbl.setFont(make_ui_font(21, QFont.Weight.ExtraBold))

        self.gemini_pill = QLabel(I18N.t("gemini_ready"))
        self.gemini_pill.setObjectName("EmeraldPill")
        self.gemini_pill.hide()

        self.vec_pill = QLabel("AUTO")
        self.vec_pill.setObjectName("BadgePill")
        enforce_english_ltr(self.vec_pill, mono_size=10, bold=True)

        title_line.addWidget(self.headline_lbl)
        title_line.addWidget(self.vec_pill)
        title_line.addWidget(self.gemini_pill)
        title_line.addStretch()

        self.detail_lbl = QLabel(I18N.t("sub_idle"))
        self.detail_lbl.setObjectName("SecondaryLabel")
        self.detail_lbl.setWordWrap(True)

        ctrl_line = QHBoxLayout()
        ctrl_line.setSpacing(14)
        self.connect_btn = KineticConnectButton()
        self.connect_btn.clicked.connect(self._on_main_button_clicked)
        self.chronometer = SpoilerChronometer()
        ctrl_line.addWidget(self.connect_btn)
        ctrl_line.addWidget(self.chronometer)
        ctrl_line.addStretch()

        info_col.addLayout(title_line)
        info_col.addWidget(self.detail_lbl)
        info_col.addSpacing(2)
        info_col.addLayout(ctrl_line)
        info_col.addStretch()

        center_row.addWidget(self.radar_core, 0, Qt.AlignmentFlag.AlignVCenter)
        center_row.addLayout(info_col, 1)

        self.route_strip = RouteTopologyStrip()

        hero_vbox.addLayout(center_row, 1)
        hero_vbox.addWidget(self.route_strip)
        root.addWidget(self.hero_card, 1)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.ip_card = CompactTelemetryCard("card_egress_ip", "globe", "#FFD000", with_sparkline=False, with_flag=True)
        self.ping_card = CompactTelemetryCard("card_real_ping", "wave", "#10B981", with_sparkline=True, stepped=True)
        self.dl_card = CompactTelemetryCard("card_dl_speed", "download", "#FFD000", with_sparkline=True)
        self.ul_card = CompactTelemetryCard("card_ul_speed", "upload", "#38BDF8", with_sparkline=True)
        self.ip_card.value_lbl.setText("---")
        self.ping_card.value_lbl.setText("---")
        self.dl_card.value_lbl.setText("0 B/s")
        self.ul_card.value_lbl.setText("0 B/s")

        for c in (self.ip_card, self.ping_card, self.dl_card, self.ul_card):
            cards_row.addWidget(c, 1)
        root.addLayout(cards_row)

        self.dock_card = NeuCard(mode="dock", radius=18.0, depth=5.2, pad=6.0)
        dock_vbox = QVBoxLayout(self.dock_card)
        dock_vbox.setContentsMargins(20, 13, 20, 13)
        dock_vbox.setSpacing(9)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.out_lbl = QLabel(I18N.t("output_selector_lbl"))
        self.out_lbl.setObjectName("SecondaryLabel")

        self.output_combo = QComboBox()
        self.output_combo.setIconSize(QSize(24, 16))
        self.output_combo.setMinimumWidth(210)
        self.output_combo.currentIndexChanged.connect(self._on_output_combo_changed)

        self.auto_loc_lbl = QLabel(I18N.t("auto_loc_lbl"))
        self.auto_loc_lbl.setObjectName("SecondaryLabel")

        self.auto_loc_combo = QComboBox()
        self.auto_loc_combo.setIconSize(QSize(24, 16))
        self.auto_loc_combo.setMinimumWidth(180)
        self.auto_loc_combo.currentIndexChanged.connect(self._on_auto_loc_combo_changed)

        self.refresh_pool_btn = VectorIconButton("refresh", size=34)
        self.refresh_pool_btn.setToolTip(I18N.t("refresh_pool_tip"))
        self.refresh_pool_btn.clicked.connect(self.refresh_auto_pool_requested.emit)

        self.ping_out_btn = ActionPillButton("bolt", I18N.t("ping_outputs_btn"), variant="ghost")
        self.ping_out_btn.clicked.connect(self.ping_verified_requested.emit)

        self.clear_out_btn = VectorIconButton("trash", size=34, danger_hover=True)
        self.clear_out_btn.setToolTip(I18N.t("clear_outputs_tip"))
        self.clear_out_btn.clicked.connect(self.clear_verified_requested.emit)

        out_row.addWidget(self.out_lbl)
        out_row.addWidget(self.output_combo, 3)
        out_row.addSpacing(6)
        out_row.addWidget(self.auto_loc_lbl)
        out_row.addWidget(self.auto_loc_combo, 2)
        out_row.addWidget(self.refresh_pool_btn)
        out_row.addSpacing(4)
        out_row.addWidget(self.ping_out_btn)
        out_row.addWidget(self.clear_out_btn)

        sw_row = QHBoxLayout()
        sw_row.setSpacing(12)

        self.sw_sys_proxy = AnimatedToggleSwitch(checked=True)
        self.sw_sys_proxy.toggled.connect(self.system_proxy_toggled.emit)
        self.lbl_sys_proxy = QLabel(I18N.t("sw_sys_proxy"))
        self.lbl_sys_proxy.setObjectName("SecondaryLabel")

        self.sw_tun = AnimatedToggleSwitch(checked=False)
        self.sw_tun.toggled.connect(self.tun_mode_toggled.emit)
        self.lbl_tun = QLabel(I18N.t("sw_tun_mode"))
        self.lbl_tun.setObjectName("SecondaryLabel")
        self.tun_pill = QLabel("OFF")
        self.tun_pill.setObjectName("MutedPill")
        enforce_english_ltr(self.tun_pill, mono_size=9, bold=True)

        self.sw_autopilot = AnimatedToggleSwitch(checked=True)
        self.sw_autopilot.toggled.connect(self._on_autopilot_user_toggled)
        self.lbl_autopilot = QLabel(I18N.t("sw_autopilot"))
        self.lbl_autopilot.setObjectName("SecondaryLabel")

        sw_row.addWidget(self.sw_sys_proxy)
        sw_row.addWidget(self.lbl_sys_proxy)
        sw_row.addSpacing(12)
        sw_row.addWidget(self.sw_tun)
        sw_row.addWidget(self.lbl_tun)
        sw_row.addWidget(self.tun_pill)
        sw_row.addSpacing(12)
        sw_row.addWidget(self.sw_autopilot)
        sw_row.addWidget(self.lbl_autopilot)
        sw_row.addStretch()

        dock_vbox.addLayout(out_row)
        dock_vbox.addLayout(sw_row)
        root.addWidget(self.dock_card)

        self._rebuild_output_combo()
        self._rebuild_auto_location_combo()
        self._sync_auto_location_enabled_state()
        self._refresh_visual_route()

    def selected_output_key(self) -> str:
        data = self.output_combo.currentData()
        return str(data) if data is not None else self.SMART_AUTO_KEY

    def selected_auto_location_code(self) -> str:
        data = self.auto_loc_combo.currentData()
        return str(data).strip().upper() if data is not None else (self._selected_auto_location or "ALL")

    def on_auto_locations_updated(self, locations: list, selected_code: str = "") -> None:
        self._auto_locations = [dict(x) for x in (locations or []) if isinstance(x, dict)]
        if selected_code and str(selected_code).strip():
            self._selected_auto_location = str(selected_code).strip().upper()
        elif not self._selected_auto_location:
            self._selected_auto_location = "ALL"
        self._rebuild_auto_location_combo()
        self._sync_auto_location_enabled_state()

    def _rebuild_auto_location_combo(self) -> None:
        target_code = str(self._selected_auto_location or "ALL").strip().upper()
        is_en = I18N.lang == "en"

        with QSignalBlocker(self.auto_loc_combo):
            self.auto_loc_combo.clear()
            matched_idx = 0

            if not self._auto_locations:
                self.auto_loc_combo.addItem(
                    make_flag_qicon("ALL", 24, 16),
                    I18N.t("auto_loc_all_default"),
                    "ALL",
                )
                self.auto_loc_combo.setCurrentIndex(0)
                return

            for idx, item in enumerate(self._auto_locations):
                code = str(item.get("code") or "ALL").strip().upper()
                if code == "UK":
                    code = "GB"

                raw_label = str(
                    item.get("label_en" if is_en else "label_fa")
                    or item.get("label_fa" if is_en else "label_en")
                    or ""
                ).strip()
                if not raw_label:
                    cname = str(
                        item.get("name_en" if is_en else "name_fa")
                        or GeoFlagResolver.get_spec(code).localized_name()
                    ).strip()
                    cnt = get_int(item, "count", 0)
                    if code == "ALL":
                        raw_label = f"{cname} — {cnt}" if cnt > 0 else cname
                    else:
                        raw_label = f"{cname} ({code}) — {cnt}" if cnt > 0 else f"{cname} ({code})"

                icon_code = "" if code == "ALL" else code
                self.auto_loc_combo.addItem(
                    make_flag_qicon(icon_code, 24, 16),
                    strip_emojis(raw_label),
                    code,
                )
                if code == target_code:
                    matched_idx = idx

            self.auto_loc_combo.setCurrentIndex(matched_idx)
            actual_data = self.auto_loc_combo.itemData(matched_idx)
            if actual_data is not None:
                self._selected_auto_location = str(actual_data).strip().upper()

    def _on_auto_loc_combo_changed(self, idx: int) -> None:
        if idx < 0:
            return
        code = self.selected_auto_location_code()
        if code:
            self._selected_auto_location = code
            self.auto_location_changed.emit(code)

    def _sync_auto_location_enabled_state(self) -> None:
        is_auto = bool(self._autopilot_enabled) or (
            self.selected_output_key() in (self.SMART_AUTO_KEY, "__smart_pool__")
        )
        self.auto_loc_lbl.setEnabled(is_auto)
        self.auto_loc_combo.setEnabled(is_auto)
        self.refresh_pool_btn.setEnabled(is_auto)

    def _on_main_button_clicked(self) -> None:
        if self._is_connecting or self._is_connected:
            self.disconnect_triggered.emit()
        else:
            self.connect_triggered.emit(self.selected_output_key())

    def _on_autopilot_user_toggled(self, checked: bool) -> None:
        self._autopilot_enabled = bool(checked)
        if self._autopilot_enabled:
            with QSignalBlocker(self.output_combo):
                self.output_combo.setCurrentIndex(0)
            self._sync_auto_location_enabled_state()
            self.autopilot_toggled.emit(True)
        else:
            self.autopilot_toggled.emit(False)
            target_idx = -1
            if self._selected_profile_uid:
                target_idx = self.output_combo.findData(self._selected_profile_uid)
            if target_idx < 1 and self.output_combo.count() > 1:
                target_idx = 1
            if target_idx >= 1:
                with QSignalBlocker(self.output_combo):
                    self.output_combo.setCurrentIndex(target_idx)
                chosen_uid = str(self.output_combo.itemData(target_idx) or "")
                if chosen_uid:
                    self._selected_profile_uid = chosen_uid
                    self.output_selection_changed.emit(chosen_uid)
            self._sync_auto_location_enabled_state()
        self._refresh_visual_route()

    def _on_output_combo_changed(self, idx: int) -> None:
        if idx < 0:
            return
        key = self.selected_output_key()
        if key in (self.SMART_AUTO_KEY, "__smart_pool__"):
            self._autopilot_enabled = True
            set_switch_blocked(self.sw_autopilot, True)
            with QSignalBlocker(self.output_combo):
                self.output_combo.setCurrentIndex(0)
            self._sync_auto_location_enabled_state()
            self.autopilot_toggled.emit(True)
        else:
            self._autopilot_enabled = False
            self._selected_profile_uid = key
            set_switch_blocked(self.sw_autopilot, False)
            self._sync_auto_location_enabled_state()
            self.autopilot_toggled.emit(False)
            self.output_selection_changed.emit(key)
        self._refresh_visual_route()

    def set_vault_profiles_context(self, profiles: list[dict], selected_index: int = -1) -> None:
        self._vault_profiles = list(profiles or [])
        if 0 <= selected_index < len(self._vault_profiles):
            self._selected_profile_uid = extract_profile_uid(self._vault_profiles[selected_index], selected_index)
        else:
            for i, p in enumerate(self._vault_profiles):
                if get_bool(p, "is_selected", False):
                    self._selected_profile_uid = extract_profile_uid(p, i)
                    break
        self._rebuild_output_combo()
        self._sync_auto_location_enabled_state()

    def set_verified_outputs(self, outputs: list[dict], select_uid: str = "") -> None:
        self._verified_outputs = list(outputs or [])
        if select_uid:
            self._selected_profile_uid = select_uid
        self._rebuild_output_combo()
        self._sync_auto_location_enabled_state()
        self._refresh_visual_route()

    def _collect_selectable_configs(self) -> list[dict]:
        combined: list[dict] = []
        seen_uids: set[str] = set()

        for idx, item in enumerate(self._verified_outputs):
            uid = extract_profile_uid(item, idx)
            if uid and uid not in seen_uids:
                seen_uids.add(uid)
                combined.append(item)

        for idx, prof in enumerate(self._vault_profiles):
            uid = extract_profile_uid(prof, idx)
            st = str(prof.get("status") or "").upper()
            is_sel = (uid == self._selected_profile_uid) or get_bool(prof, "is_selected", False)
            if uid and (uid not in seen_uids) and (st == "VERIFIED" or is_sel):
                seen_uids.add(uid)
                combined.append(prof)

        return combined

    def _rebuild_output_combo(self) -> None:
        candidates = self._collect_selectable_configs()
        with QSignalBlocker(self.output_combo):
            self.output_combo.clear()
            self.output_combo.addItem(
                make_vector_qicon("bolt", "#FFD000", 18),
                I18N.t("smart_auto_pool"),
                self.SMART_AUTO_KEY,
            )

            matched_idx = -1
            for idx, item in enumerate(candidates):
                uid = extract_profile_uid(item, idx)
                name = GeoFlagResolver.clean_display_name(
                    str(item.get("name") or item.get("title") or f"Output #{idx + 1}")
                )
                proto = str(item.get("protocol") or "VLESS").upper()
                vec = str(item.get("vector_id") or item.get("cached_vector_id") or item.get("preferred_vector_id") or "AUTO")
                ping = get_int(item, "ping_ms", 0)
                ping_str = f"{ping}ms" if ping > 0 else "OK"
                cc = GeoFlagResolver.resolve_code(item)
                label = I18N.t("verified_item_fmt", name=name, proto=proto, vec=vec, ping=ping_str)
                if is_gemini_verified(item):
                    label = f"{label} [Gemini]"
                self.output_combo.addItem(make_flag_qicon(cc, 24, 16), label, uid)
                if uid == self._selected_profile_uid:
                    matched_idx = idx + 1

            if self._autopilot_enabled:
                self.output_combo.setCurrentIndex(0)
            elif matched_idx >= 1:
                self.output_combo.setCurrentIndex(matched_idx)
            elif self.output_combo.count() > 1:
                self.output_combo.setCurrentIndex(1)
            else:
                self.output_combo.setCurrentIndex(0)

    def sync_autopilot_state(self, autopilot_enabled: bool, selected_uid: str = "") -> None:
        self._autopilot_enabled = bool(autopilot_enabled)
        if selected_uid:
            self._selected_profile_uid = selected_uid
        set_switch_blocked(self.sw_autopilot, self._autopilot_enabled)
        self._rebuild_output_combo()
        self._sync_auto_location_enabled_state()

    def sync_switches(self, settings: dict) -> None:
        if "system_proxy" in settings:
            set_switch_blocked(self.sw_sys_proxy, get_bool(settings, "system_proxy", True))

        if ("auto_mode_enabled" in settings) or ("autopilot_enabled" in settings) or ("autopilot" in settings):
            if "auto_mode_enabled" in settings:
                ap_on = get_bool(settings, "auto_mode_enabled", True)
            elif "autopilot_enabled" in settings:
                ap_on = get_bool(settings, "autopilot_enabled", True)
            else:
                ap_on = get_bool(settings, "autopilot", True)
            sel_uid = str(settings.get("active_profile_uid") or self._selected_profile_uid)
            self.sync_autopilot_state(ap_on, sel_uid)

        if "selected_auto_location" in settings or "auto_location" in settings:
            loc_code = str(settings.get("selected_auto_location") or settings.get("auto_location") or "").strip().upper()
            if loc_code:
                self._selected_auto_location = loc_code
                self._rebuild_auto_location_combo()

        if ("tun_enabled" in settings) or ("tun_badge" in settings):
            tun_en = bool(settings.get("tun_enabled"))
            tun_b = str(settings.get("tun_badge") or "")
            self.apply_tun_status(tun_en, tun_en and self._is_connected, "", tun_b)

    def apply_tun_status(
        self,
        enabled: bool,
        active: bool = False,
        detail: str = "",
        tun_badge: str = "",
    ) -> None:
        tun_en = bool(enabled)
        set_switch_blocked(self.sw_tun, tun_en)

        badge_upper = str(tun_badge or "").strip().upper()
        is_on = (badge_upper == "ON") or tun_en or bool(active)
        self.tun_pill.setText("ON" if is_on else "OFF")
        obj = "EmeraldPill" if is_on else "MutedPill"
        if self.tun_pill.objectName() != obj:
            self.tun_pill.setObjectName(obj)
            self.tun_pill.style().unpolish(self.tun_pill)
            self.tun_pill.style().polish(self.tun_pill)
        if detail:
            self.tun_pill.setToolTip(strip_emojis(detail))

    def _resolve_current_output_dict(self) -> dict:
        sel = self.selected_output_key()
        if sel != self.SMART_AUTO_KEY:
            for item in self._collect_selectable_configs():
                if extract_profile_uid(item, -1) == sel:
                    return item
        if self._verified_outputs:
            return self._verified_outputs[0]
        if self._vault_profiles:
            return self._vault_profiles[0]
        return {}

    def _set_gemini_pill_state(self, ready: bool, show_unverified: bool) -> None:
        if ready:
            self.gemini_pill.setText(I18N.t("gemini_ready"))
            if self.gemini_pill.objectName() != "EmeraldPill":
                self.gemini_pill.setObjectName("EmeraldPill")
                self.gemini_pill.style().unpolish(self.gemini_pill)
                self.gemini_pill.style().polish(self.gemini_pill)
            self.gemini_pill.show()
        elif show_unverified:
            self.gemini_pill.setText(I18N.t("gemini_unverified"))
            if self.gemini_pill.objectName() != "MutedPill":
                self.gemini_pill.setObjectName("MutedPill")
                self.gemini_pill.style().unpolish(self.gemini_pill)
                self.gemini_pill.style().polish(self.gemini_pill)
            self.gemini_pill.show()
        else:
            self.gemini_pill.hide()

    def _refresh_visual_route(self) -> None:
        snap = self._last_snap
        ping = get_int(snap, "ping_ms", 0) if self._is_connected else 0

        if self._is_connected:
            eg_code = str(snap.get("egress_country_code") or "").strip().upper()
            if eg_code == "UK":
                eg_code = "GB"

            raw_ip = str(snap.get("egress_ip") or "").strip()
            disp_ip = raw_ip if (raw_ip and raw_ip not in ("—", "---")) else "---"

            dest_label = strip_emojis(str(snap.get("destination_label") or "").strip())
            if not dest_label or dest_label in ("—", "---"):
                eg_name = strip_emojis(str(snap.get("egress_country") or "").strip())
                if eg_name and eg_code:
                    dest_label = f"{eg_name} ({eg_code})"
                elif eg_name:
                    dest_label = eg_name
                elif eg_code:
                    spec_c = GeoFlagResolver.get_spec(eg_code)
                    dest_label = f"{spec_c.localized_name()} ({eg_code})"
                else:
                    dest_label = "---"

            has_explicit_gem = "gemini_ready" in snap
            gem_ok = get_bool(snap, "gemini_ready", False) if has_explicit_gem else is_gemini_verified(snap)
        else:
            eg_code = ""
            disp_ip = "---"
            dest_label = "---"
            has_explicit_gem = False
            gem_ok = False

        self.radar_core.set_country_code(eg_code)
        self.route_strip.set_route_state(
            dest_code=eg_code,
            ip_text=disp_ip,
            ping_ms=ping,
            phase=self._ui_phase,
            gemini_ready=gem_ok,
            dest_label=dest_label,
        )
        self._set_gemini_pill_state(
            ready=gem_ok,
            show_unverified=(self._is_connected and has_explicit_gem and not gem_ok),
        )

        self.ip_card.value_lbl.setText(disp_ip)
        if self.ip_card.flag_badge is not None:
            self.ip_card.flag_badge.set_country_code(eg_code)
        if self.ip_card.sub_lbl is not None:
            if self._is_connected and eg_code:
                self.ip_card.sub_lbl.setText(dest_label)
            else:
                self.ip_card.sub_lbl.setText("---")

    def apply_telemetry(self, snap: dict) -> None:
        self._last_snap = dict(snap)
        raw_phase = str(snap.get("ui_phase") or "").upper()
        raw_state = str(snap.get("state") or "disconnected").lower()

        def_conn = (raw_phase == "CONNECTING") or (raw_state in ("connecting", "probing", "scanning", "starting"))
        def_ok = (raw_phase == "CONNECTED") or (raw_state in ("connected", "online", "active"))

        self._is_connecting = get_bool(snap, "is_connecting", def_conn)
        self._is_connected = get_bool(snap, "is_connected", def_ok)

        if self._is_connecting:
            self._ui_phase = "CONNECTING"
        elif self._is_connected:
            self._ui_phase = "CONNECTED"
        elif raw_phase == "ERROR" or raw_state in ("error", "failed"):
            self._ui_phase = "ERROR"
        else:
            self._ui_phase = "IDLE"

        tun_en = bool(snap.get("tun_enabled"))
        tun_b = str(snap.get("tun_badge") or "")
        self.apply_tun_status(tun_en, tun_en and self._is_connected, "", tun_b)

        snap_uid = str(snap.get("active_profile_uid") or "").strip()
        if "auto_mode_enabled" in snap:
            self.sync_autopilot_state(bool(snap.get("auto_mode_enabled")), snap_uid)
        elif "autopilot_enabled" in snap:
            self.sync_autopilot_state(bool(snap.get("autopilot_enabled")), snap_uid)
        elif self._autopilot_enabled:
            with QSignalBlocker(self.output_combo):
                self.output_combo.setCurrentIndex(0)
            self._sync_auto_location_enabled_state()
        elif snap_uid and snap_uid != self._selected_profile_uid:
            self.sync_autopilot_state(False, snap_uid)

        if "selected_auto_location" in snap:
            loc_c = str(snap.get("selected_auto_location") or "").strip().upper()
            if loc_c and loc_c != self._selected_auto_location:
                self._selected_auto_location = loc_c
                self._rebuild_auto_location_combo()

        self.radar_core.set_ui_phase(self._ui_phase)
        self.connect_btn.set_phase_and_label(self._ui_phase, str(snap.get("button_text") or ""))
        self.chronometer.set_uptime_state(str(snap.get("uptime_label") or "00:00:00"), self._is_connected)

        default_head = (
            I18N.t("status_connecting")
            if self._is_connecting
            else (I18N.t("status_connected") if self._is_connected else I18N.t("status_idle"))
        )
        raw_head = strip_emojis(str(snap.get("status_headline") or ""))
        self.headline_lbl.setText(raw_head if (raw_head and I18N.lang == "fa") else default_head)

        raw_det = strip_emojis(str(snap.get("status_detail") or ""))
        self.detail_lbl.setText(raw_det if raw_det else I18N.t("sub_idle"))

        vec_id = strip_emojis(str(snap.get("active_vector_id") or "AUTO"))
        self.vec_pill.setText(vec_id)

        rx_kbps = float(snap.get("rx_rate_kbps") or 0.0) if self._is_connected else 0.0
        tx_kbps = float(snap.get("tx_rate_kbps") or 0.0) if self._is_connected else 0.0
        ping_ms = get_int(snap, "ping_ms", 0) if self._is_connected else 0

        rx_lbl = str(snap.get("rx_rate_label") or "").strip()
        tx_lbl = str(snap.get("tx_rate_label") or "").strip()

        if (not self._is_connected) or (rx_kbps <= 0.0):
            self.dl_card.value_lbl.setText("0 B/s")
            if self.dl_card.sparkline:
                self.dl_card.sparkline.reset_flat()
        else:
            self.dl_card.value_lbl.setText(rx_lbl if rx_lbl else format_rate_kbps(rx_kbps))
            if self.dl_card.sparkline:
                self.dl_card.sparkline.push_sample(rx_kbps)

        if (not self._is_connected) or (tx_kbps <= 0.0):
            self.ul_card.value_lbl.setText("0 B/s")
            if self.ul_card.sparkline:
                self.ul_card.sparkline.reset_flat()
        else:
            self.ul_card.value_lbl.setText(tx_lbl if tx_lbl else format_rate_kbps(tx_kbps))
            if self.ul_card.sparkline:
                self.ul_card.sparkline.push_sample(tx_kbps)

        if (not self._is_connected) or (ping_ms <= 0):
            self.ping_card.value_lbl.setText("---")
            if self.ping_card.sparkline:
                self.ping_card.sparkline.reset_flat()
        else:
            self.ping_card.value_lbl.setText(f"{ping_ms} ms")
            if self.ping_card.sparkline:
                self.ping_card.sparkline.push_sample(float(ping_ms))

        self._refresh_visual_route()

    def retranslate_ui(self) -> None:
        self.connect_btn.retranslate_ui()
        self.out_lbl.setText(I18N.t("output_selector_lbl"))
        self.auto_loc_lbl.setText(I18N.t("auto_loc_lbl"))
        self.refresh_pool_btn.setToolTip(I18N.t("refresh_pool_tip"))
        self.ping_out_btn.set_label_text(I18N.t("ping_outputs_btn"))
        self.clear_out_btn.setToolTip(I18N.t("clear_outputs_tip"))
        self.lbl_sys_proxy.setText(I18N.t("sw_sys_proxy"))
        self.lbl_tun.setText(I18N.t("sw_tun_mode"))
        self.lbl_autopilot.setText(I18N.t("sw_autopilot"))
        for c in (self.ip_card, self.ping_card, self.dl_card, self.ul_card):
            c.retranslate_ui()
        self._rebuild_output_combo()
        self._rebuild_auto_location_combo()
        self._sync_auto_location_enabled_state()
        if self._last_snap:
            self.apply_telemetry(self._last_snap)
        else:
            self.headline_lbl.setText(I18N.t("status_idle"))
            self.detail_lbl.setText(I18N.t("sub_idle"))
            self._refresh_visual_route()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.radar_core.set_palette_theme(palette)
        self.connect_btn.set_palette_theme(palette)
        self.chronometer.set_palette_theme(palette)
        self.route_strip.set_palette_theme(palette)
        self.dock_card.set_palette_theme(palette)
        self.refresh_pool_btn.set_palette_theme(palette)
        self.ping_out_btn.set_palette_theme(palette)
        self.clear_out_btn.set_palette_theme(palette)
        for sw in (self.sw_sys_proxy, self.sw_tun, self.sw_autopilot):
            sw.set_palette_theme(palette)
        for c in (self.ip_card, self.ping_card, self.dl_card, self.ul_card):
            c.set_palette_theme(palette)


class ConfigsPage(QWidget):
    select_active_requested = Signal(object)
    import_clipboard_requested = Signal(str, str)
    new_config_requested = Signal(str)
    edit_config_requested = Signal(object)
    delete_configs_requested = Signal(list)
    ping_configs_requested = Signal(object)
    probe_gemini_requested = Signal(object)
    sort_requested = Signal(str)
    dedup_requested = Signal()
    remove_dead_requested = Signal()
    export_verified_requested = Signal()
    send_batch_to_lab_requested = Signal(list, str)
    manage_subs_requested = Signal()
    hunt_subscription_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._profiles: list[dict] = []
        self._subscriptions: list[dict] = []
        self._selected_index = -1
        self._current_group_key = "__ALL__"
        self._checked_uids: set[str] = set()
        self._visible_rows: list[tuple[int, str, dict]] = []
        self._syncing_table = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        t_col = QVBoxLayout()
        t_col.setSpacing(2)
        self.title_lbl = QLabel(I18N.t("vault_title"))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(I18N.t("vault_subtitle"))
        self.sub_lbl.setObjectName("MutedLabel")
        t_col.addWidget(self.title_lbl)
        t_col.addWidget(self.sub_lbl)

        self.hunt_sub_btn = ActionPillButton("bolt", I18N.t("hunt_sub_btn"), variant="emerald")
        self.hunt_sub_btn.clicked.connect(self._on_hunt_sub_clicked)

        self.manage_subs_btn = ActionPillButton("plus", I18N.t("manage_subs_btn"), variant="ghost")
        self.manage_subs_btn.clicked.connect(self.manage_subs_requested.emit)

        hdr.addLayout(t_col, 1)
        hdr.addWidget(self.hunt_sub_btn)
        hdr.addWidget(self.manage_subs_btn)
        root.addLayout(hdr)

        self.tabs_card = NeuCard(mode="inset", radius=14.0, depth=3.8, pad=3.0)
        tabs_outer = QHBoxLayout(self.tabs_card)
        tabs_outer.setContentsMargins(10, 6, 10, 6)
        tabs_outer.setSpacing(6)
        self.group_tabs_host = QWidget()
        self.group_tabs_layout = QHBoxLayout(self.group_tabs_host)
        self.group_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.group_tabs_layout.setSpacing(6)
        self.group_btn_group = QButtonGroup(self)
        self.group_btn_group.setExclusive(True)
        tabs_outer.addWidget(self.group_tabs_host, 1)
        root.addWidget(self.tabs_card)

        self.toolbar_card = NeuCard(mode="raised", radius=16.0, depth=4.4, pad=5.0)
        toolbar = QHBoxLayout(self.toolbar_card)
        toolbar.setContentsMargins(14, 10, 14, 10)
        toolbar.setSpacing(7)

        self.btn_import = ActionPillButton("plus", I18N.t("import_clip_btn"), variant="ghost")
        self.btn_import.clicked.connect(self._import_from_clipboard)

        self.btn_new = ActionPillButton("edit", I18N.t("new_config_btn"), variant="ghost")
        self.btn_new.clicked.connect(self._request_new_in_group)

        self.btn_ping = ActionPillButton("bolt", I18N.t("ping_btn"), variant="ghost")
        self.btn_ping.clicked.connect(self._ping_selected_or_tab)

        self.btn_gemini = ActionPillButton("gemini", I18N.t("probe_gemini_btn"), variant="emerald")
        self.btn_gemini.clicked.connect(self._probe_gemini_selected_or_tab)

        self.btn_sort = QPushButton(I18N.t("sort_ping_btn"))
        self.btn_sort.setObjectName("GhostBtn")
        self.btn_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort.clicked.connect(lambda: self.sort_requested.emit("ping"))

        self.btn_dedup = QPushButton(I18N.t("dedup_btn"))
        self.btn_dedup.setObjectName("GhostBtn")
        self.btn_dedup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dedup.clicked.connect(self.dedup_requested.emit)

        self.btn_rm_dead = QPushButton(I18N.t("remove_dead_btn"))
        self.btn_rm_dead.setObjectName("DangerBtn")
        self.btn_rm_dead.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rm_dead.clicked.connect(self.remove_dead_requested.emit)

        self.btn_send_lab = ActionPillButton("lab", I18N.t("send_to_lab_btn", n=0), variant="gold")
        self.btn_send_lab.clicked.connect(self._send_checked_or_tab_to_lab)

        toolbar.addWidget(self.btn_import)
        toolbar.addWidget(self.btn_new)
        toolbar.addWidget(self.btn_ping)
        toolbar.addWidget(self.btn_gemini)
        toolbar.addWidget(self.btn_sort)
        toolbar.addWidget(self.btn_dedup)
        toolbar.addWidget(self.btn_rm_dead)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_send_lab)
        root.addWidget(self.toolbar_card)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        self.chk_select_all = QCheckBox(I18N.t("col_sel"))
        self.chk_select_all.toggled.connect(self._on_select_all_toggled)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(I18N.t("search_vault_ph"))
        self.search_edit.textChanged.connect(lambda _t: self._rebuild_table())

        filter_row.addWidget(self.chk_select_all)
        filter_row.addWidget(self.search_edit, 1)
        root.addLayout(filter_row)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("VaultTable")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        self.table.itemChanged.connect(self._on_item_check_changed)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 46)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        root.addWidget(self.table, 1)

        QShortcut(QKeySequence("Ctrl+A"), self, activated=self._shortcut_select_all)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self._import_from_clipboard)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_target_uids)

        self._apply_table_headers()
        self._rebuild_group_tabs()

    def _on_hunt_sub_clicked(self) -> None:
        if self._current_group_key not in ("__ALL__", "Manual"):
            self.hunt_subscription_requested.emit(self._current_group_key, self._current_group_key)
            return
        dlg = HuntSubscriptionDialog(
            subscriptions=self._subscriptions,
            groups=self.known_group_names(),
            palette=self._palette,
            parent=self.window(),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            target_sub, custom_title = dlg.collected_target()
            if target_sub:
                self.hunt_subscription_requested.emit(target_sub, custom_title)

    def _apply_table_headers(self) -> None:
        headers = [
            I18N.t("col_sel"),
            I18N.t("col_proto"),
            I18N.t("col_name"),
            I18N.t("col_endpoint"),
            I18N.t("col_group"),
            I18N.t("col_vector"),
            I18N.t("col_gemini"),
            I18N.t("col_ping"),
        ]
        self.table.setHorizontalHeaderLabels(headers)

    def known_group_names(self) -> list[str]:
        names = ["Manual"]
        for s in self._subscriptions:
            if isinstance(s, dict):
                t = strip_emojis(str(s.get("title") or s.get("name") or "")).strip()
                if t and t not in names:
                    names.append(t)
        for p in self._profiles:
            g = extract_profile_group(p)
            if g and g not in names:
                names.append(g)
        return names

    def active_import_group(self) -> str:
        if self._current_group_key in ("__ALL__", "Manual"):
            return "Manual"
        return self._current_group_key

    def set_subscriptions(self, subs: list) -> None:
        self._subscriptions = list(subs or [])
        self._rebuild_group_tabs()

    def set_profiles(self, profiles: list[dict], selected_index: int = -1) -> None:
        self._profiles = list(profiles or [])
        self._selected_index = selected_index
        valid_uids = {extract_profile_uid(p, i) for i, p in enumerate(self._profiles)}
        self._checked_uids.intersection_update(valid_uids)
        self._rebuild_group_tabs()
        self._rebuild_table()

    def _rebuild_group_tabs(self) -> None:
        counts: dict[str, int] = {"Manual": 0}
        for g in self.known_group_names():
            counts.setdefault(g, 0)
        for p in self._profiles:
            g = extract_profile_group(p)
            counts[g] = counts.get(g, 0) + 1

        while self.group_tabs_layout.count():
            item = self.group_tabs_layout.takeAt(0)
            if item.widget():
                self.group_btn_group.removeButton(item.widget())
                item.widget().deleteLater()

        tab_defs = [("__ALL__", I18N.t("tab_all", n=len(self._profiles)))]
        tab_defs.append(("Manual", I18N.t("tab_manual", n=counts.get("Manual", 0))))
        for g_name, cnt in counts.items():
            if g_name != "Manual":
                tab_defs.append((g_name, f"{g_name} ({cnt})"))

        valid_keys = {k for k, _ in tab_defs}
        if self._current_group_key not in valid_keys:
            self._current_group_key = "__ALL__"

        for key, label in tab_defs:
            btn = NeuGroupTabButton(label, self._palette, self.group_tabs_host)
            btn.setChecked(key == self._current_group_key)
            btn.clicked.connect(lambda _c=False, k=key: self._select_group_tab(k))
            self.group_btn_group.addButton(btn)
            self.group_tabs_layout.addWidget(btn)

        self.group_tabs_layout.addStretch()

    def _select_group_tab(self, key: str) -> None:
        self._current_group_key = key
        self._rebuild_group_tabs()
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        self._syncing_table = True
        self.table.setUpdatesEnabled(False)
        try:
            q = self.search_edit.text().strip().lower()
            self._visible_rows.clear()

            for idx, p in enumerate(self._profiles):
                grp = extract_profile_group(p)
                if (self._current_group_key != "__ALL__") and (grp != self._current_group_key):
                    continue
                uid = extract_profile_uid(p, idx)
                if q:
                    hay = " ".join(
                        str(p.get(k) or "")
                        for k in ("name", "title", "protocol", "host", "original_host", "address", "sni", "cached_vector_id")
                    ).lower()
                    if q not in hay and q not in grp.lower():
                        continue
                self._visible_rows.append((idx, uid, p))

            self.table.setRowCount(len(self._visible_rows))
            mono = make_mono_font(10, bold=True)
            mono_reg = make_mono_font(9, bold=False)

            for row_i, (orig_idx, uid, p) in enumerate(self._visible_rows):
                self.table.setRowHeight(row_i, 40)
                is_active = get_bool(p, "is_selected", orig_idx == self._selected_index)

                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                chk_item.setCheckState(Qt.CheckState.Checked if uid in self._checked_uids else Qt.CheckState.Unchecked)
                chk_item.setData(Qt.ItemDataRole.UserRole, uid)
                self.table.setItem(row_i, 0, chk_item)

                proto = str(p.get("protocol") or "VLESS").upper()
                proto_item = QTableWidgetItem(proto)
                proto_item.setFont(mono)
                proto_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                proto_item.setForeground(
                    QColor(self._palette.accent_primary if self._palette.is_dark else "#B45309")
                )
                self.table.setItem(row_i, 1, proto_item)

                raw_name = GeoFlagResolver.clean_display_name(str(p.get("name") or p.get("title") or f"Node #{orig_idx + 1}"))
                prefix = "* " if is_active else ""
                cc = GeoFlagResolver.resolve_code(p)
                name_item = QTableWidgetItem(make_flag_qicon(cc, 24, 16), f"{prefix}{raw_name}")
                name_item.setFont(make_ui_font(10, QFont.Weight.ExtraBold if is_active else QFont.Weight.DemiBold))
                if is_active:
                    name_item.setForeground(QColor(self._palette.emerald))
                self.table.setItem(row_i, 2, name_item)

                host = str(p.get("host") or p.get("original_host") or p.get("address") or "---")
                port = get_int(p, "port", 443)
                ep_txt = f"{host}:{port}" if (host != "---" and ":" not in host) else host
                ep_item = QTableWidgetItem(ep_txt)
                ep_item.setFont(mono_reg)
                ep_item.setForeground(QColor(self._palette.text_secondary))
                self.table.setItem(row_i, 3, ep_item)

                grp_item = QTableWidgetItem(extract_profile_group(p))
                grp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                grp_item.setForeground(QColor(self._palette.text_muted))
                self.table.setItem(row_i, 4, grp_item)

                vec = str(p.get("cached_vector_id") or p.get("preferred_vector_id") or "AUTO")
                vec_item = QTableWidgetItem(vec)
                vec_item.setFont(mono)
                vec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                vec_item.setForeground(
                    QColor(self._palette.cyan) if vec != "AUTO" else QColor(self._palette.text_muted)
                )
                self.table.setItem(row_i, 5, vec_item)

                gem_ok = is_gemini_verified(p)
                raw_gem_st = str(p.get("gemini_status") or "").strip().upper()
                if gem_ok:
                    gem_item = QTableWidgetItem(
                        make_vector_qicon("gemini", self._palette.emerald, 14),
                        "Gemini",
                    )
                    gem_item.setFont(mono)
                    gem_item.setForeground(QColor(self._palette.emerald))
                elif raw_gem_st in ("BLOCKED", "FAIL", "FAILED", "NO", "FALSE"):
                    gem_item = QTableWidgetItem("BLOCKED")
                    gem_item.setFont(mono_reg)
                    gem_item.setForeground(QColor(self._palette.danger))
                else:
                    gem_item = QTableWidgetItem("---")
                    gem_item.setFont(mono_reg)
                    gem_item.setForeground(QColor(self._palette.text_muted))
                gem_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_i, 6, gem_item)

                ping = get_int(p, "ping_ms", 0)
                st_upper = str(p.get("status") or "").upper()
                if ping > 0:
                    ping_txt = f"{ping} ms"
                    ping_col = (
                        QColor(self._palette.emerald)
                        if ping <= 110
                        else (QColor(self._palette.accent_primary) if ping <= 230 else QColor(self._palette.warning))
                    )
                elif st_upper in ("DEAD", "TIMEOUT", "FAILED"):
                    ping_txt = "TIMEOUT"
                    ping_col = QColor(self._palette.danger)
                else:
                    ping_txt = "---"
                    ping_col = QColor(self._palette.text_muted)

                ping_item = QTableWidgetItem(ping_txt)
                ping_item.setFont(mono)
                ping_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                ping_item.setForeground(ping_col)
                self.table.setItem(row_i, 7, ping_item)

            self._update_send_lab_caption()
        finally:
            self.table.setUpdatesEnabled(True)
            self._syncing_table = False

    def _effective_target_uids(self) -> list[str]:
        if self._checked_uids:
            return [uid for _, uid, _ in self._visible_rows if uid in self._checked_uids]
        sel_rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return [self._visible_rows[r][1] for r in sel_rows if 0 <= r < len(self._visible_rows)]

    def _update_send_lab_caption(self) -> None:
        cnt = len(self._checked_uids)
        if cnt > 0:
            self.btn_send_lab.set_label_text(I18N.t("send_to_lab_btn", n=cnt))
        elif self._current_group_key != "__ALL__":
            self.btn_send_lab.set_label_text(I18N.t("send_sub_to_lab_btn"))
        else:
            self.btn_send_lab.set_label_text(I18N.t("send_to_lab_btn", n=len(self._visible_rows)))

    def _on_item_check_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_table or item.column() != 0:
            return
        uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not uid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_uids.add(uid)
        else:
            self._checked_uids.discard(uid)
        self._update_send_lab_caption()

    def _on_select_all_toggled(self, checked: bool) -> None:
        for _, uid, _ in self._visible_rows:
            if checked:
                self._checked_uids.add(uid)
            else:
                self._checked_uids.discard(uid)
        self._rebuild_table()

    def _shortcut_select_all(self) -> None:
        self.chk_select_all.setChecked(True)

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._visible_rows):
            orig_idx, uid, _ = self._visible_rows[row]
            self.select_active_requested.emit(uid if uid else orig_idx)

    def _import_from_clipboard(self) -> None:
        clip = QGuiApplication.clipboard().text().strip()
        if clip:
            grp = self.active_import_group()
            self.import_clipboard_requested.emit(clip, grp)
            self.sub_lbl.setText(I18N.t("vault_feedback_imported", group=grp))
        else:
            self.sub_lbl.setText(I18N.t("vault_feedback_empty_clip"))

    def _request_new_in_group(self) -> None:
        self.new_config_requested.emit(self.active_import_group())

    def _ping_selected_or_tab(self) -> None:
        targets = self._effective_target_uids()
        if targets:
            self.ping_configs_requested.emit(targets)
        elif self._current_group_key != "__ALL__":
            tab_uids = [uid for _, uid, _ in self._visible_rows]
            self.ping_configs_requested.emit(tab_uids)
        else:
            self.ping_configs_requested.emit(None)

    def _probe_gemini_selected_or_tab(self) -> None:
        targets = self._effective_target_uids()
        if targets:
            self.probe_gemini_requested.emit(targets)
        elif self._current_group_key != "__ALL__":
            tab_uids = [uid for _, uid, _ in self._visible_rows]
            self.probe_gemini_requested.emit(tab_uids)
        else:
            self.probe_gemini_requested.emit(None)

    def _send_checked_or_tab_to_lab(self) -> None:
        targets = self._effective_target_uids()
        if targets:
            self.send_batch_to_lab_requested.emit(targets, "")
        else:
            tab_uids = [uid for _, uid, _ in self._visible_rows]
            grp = "" if self._current_group_key == "__ALL__" else self._current_group_key
            self.send_batch_to_lab_requested.emit(tab_uids, grp)

    def _delete_target_uids(self) -> None:
        targets = self._effective_target_uids()
        if targets:
            self.delete_configs_requested.emit(targets)

    def _copy_selected_uris(self) -> None:
        targets = set(self._effective_target_uids())
        uris = [
            str(p.get("raw_uri") or p.get("uri") or "")
            for _, uid, p in self._visible_rows
            if (uid in targets) and (p.get("raw_uri") or p.get("uri"))
        ]
        if uris:
            QGuiApplication.clipboard().setText("\n".join(uris))
            self.sub_lbl.setText(I18N.t("vault_feedback_copied"))

    def _open_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        clicked_uid = ""
        clicked_orig_idx = -1
        if 0 <= row < len(self._visible_rows):
            clicked_orig_idx, clicked_uid, _ = self._visible_rows[row]
            if not self.table.selectionModel().isRowSelected(row, self.table.rootIndex()):
                self.table.selectRow(row)

        targets = self._effective_target_uids()
        if (not targets) and clicked_uid:
            targets = [clicked_uid]

        menu = QMenu(self)
        menu.setLayoutDirection(I18N.layout_direction())

        act_active = menu.addAction(I18N.t("ctx_set_active"))
        act_ping = menu.addAction(I18N.t("ctx_real_ping"))
        act_gemini = menu.addAction(I18N.t("ctx_check_gemini"))
        act_hunt_sub = menu.addAction(I18N.t("hunt_sub_btn"))
        menu.addSeparator()
        act_lab_sel = menu.addAction(I18N.t("ctx_send_sel_lab"))
        act_lab_tab = menu.addAction(I18N.t("ctx_send_tab_lab"))
        menu.addSeparator()
        act_edit = menu.addAction(I18N.t("ctx_edit"))
        act_copy = menu.addAction(I18N.t("ctx_copy_uri"))
        act_export = menu.addAction(I18N.t("ctx_export_verified"))
        menu.addSeparator()
        act_del = menu.addAction(I18N.t("ctx_delete_sel"))

        has_single = clicked_orig_idx >= 0
        act_active.setEnabled(has_single)
        act_edit.setEnabled(has_single)
        act_del.setEnabled(bool(targets))

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_active and has_single:
            self.select_active_requested.emit(clicked_uid or clicked_orig_idx)
        elif chosen == act_ping:
            self.ping_configs_requested.emit(targets if targets else None)
        elif chosen == act_gemini:
            self.probe_gemini_requested.emit(targets if targets else None)
        elif chosen == act_hunt_sub:
            self._on_hunt_sub_clicked()
        elif chosen == act_lab_sel:
            self.send_batch_to_lab_requested.emit(targets, "")
        elif chosen == act_lab_tab:
            tab_uids = [u for _, u, _ in self._visible_rows]
            grp = "" if self._current_group_key == "__ALL__" else self._current_group_key
            self.send_batch_to_lab_requested.emit(tab_uids, grp)
        elif chosen == act_edit and has_single:
            self.edit_config_requested.emit(clicked_uid or clicked_orig_idx)
        elif chosen == act_copy:
            self._copy_selected_uris()
        elif chosen == act_export:
            self.export_verified_requested.emit()
        elif chosen == act_del and targets:
            self.delete_configs_requested.emit(targets)

    def retranslate_ui(self) -> None:
        self.title_lbl.setText(I18N.t("vault_title"))
        self.sub_lbl.setText(I18N.t("vault_subtitle"))
        self.hunt_sub_btn.set_label_text(I18N.t("hunt_sub_btn"))
        self.manage_subs_btn.set_label_text(I18N.t("manage_subs_btn"))
        self.btn_import.set_label_text(I18N.t("import_clip_btn"))
        self.btn_new.set_label_text(I18N.t("new_config_btn"))
        self.btn_ping.set_label_text(I18N.t("ping_btn"))
        self.btn_gemini.set_label_text(I18N.t("probe_gemini_btn"))
        self.btn_sort.setText(I18N.t("sort_ping_btn"))
        self.btn_dedup.setText(I18N.t("dedup_btn"))
        self.btn_rm_dead.setText(I18N.t("remove_dead_btn"))
        self.chk_select_all.setText(I18N.t("col_sel"))
        self.search_edit.setPlaceholderText(I18N.t("search_vault_ph"))
        self._apply_table_headers()
        self._rebuild_group_tabs()
        self._rebuild_table()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.tabs_card.set_palette_theme(palette)
        self.toolbar_card.set_palette_theme(palette)
        for b in (
            self.hunt_sub_btn,
            self.manage_subs_btn,
            self.btn_import,
            self.btn_new,
            self.btn_ping,
            self.btn_gemini,
            self.btn_send_lab,
        ):
            b.set_palette_theme(palette)
        self._rebuild_group_tabs()
        self._rebuild_table()


class LabPage(QWidget):
    start_lab_scan_requested = Signal(str, list, str, str, bool, bool)
    start_clean_ip_requested = Signal(int)
    start_doh_scan_requested = Signal()
    add_doh_custom_requested = Signal(str)
    apply_doh_tunnel_requested = Signal(str)
    toggle_doh_veil_requested = Signal(bool, str)
    stop_scanner_requested = Signal()
    connect_winner_requested = Signal(str, str)
    apply_clean_ip_requested = Signal(str, bool)
    go_home_requested = Signal()

    CLOUDFLARE_PORTS = [443, 2053, 2083, 2087, 2096, 8443, 80, 8080]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._is_running = False
        self._batch_uids: list[str] = []
        self._profiles: list[dict] = []
        self._groups: list[str] = ["Manual"]
        self._vectors: list = []
        self._lab_rows: list[dict] = []
        self._radar_rows: list[dict] = []
        self._doh_rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        t_col = QVBoxLayout()
        t_col.setSpacing(2)
        self.title_lbl = QLabel(I18N.t("lab_title"))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(I18N.t("lab_subtitle"))
        self.sub_lbl.setObjectName("MutedLabel")
        t_col.addWidget(self.title_lbl)
        t_col.addWidget(self.sub_lbl)
        hdr.addLayout(t_col, 1)
        root.addLayout(hdr)

        self.mode_seg = SegmentedControl(
            [
                I18N.t("lab_mode_vectors"),
                I18N.t("lab_mode_clean_ip"),
                I18N.t("lab_mode_doh"),
            ]
        )
        self.mode_seg.current_changed.connect(self._on_mode_switched)
        root.addWidget(self.mode_seg)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        vec_page = QWidget()
        vec_vbox = QVBoxLayout(vec_page)
        vec_vbox.setContentsMargins(0, 4, 0, 0)
        vec_vbox.setSpacing(10)

        self.cfg_card = NeuCard(mode="raised", radius=18.0, depth=5.0, pad=6.0)
        cfg_vbox = QVBoxLayout(self.cfg_card)
        cfg_vbox.setContentsMargins(18, 15, 18, 15)
        cfg_vbox.setSpacing(10)

        r1 = QHBoxLayout()
        r1.setSpacing(10)
        self.scope_lbl = QLabel(I18N.t("lab_scope_lbl"))
        self.scope_lbl.setObjectName("SecondaryLabel")
        self.scope_combo = QComboBox()
        self.scope_combo.currentIndexChanged.connect(self._sync_scope_selectors)

        self.group_target_combo = QComboBox()
        self.single_target_combo = QComboBox()
        self.single_target_combo.setMinimumWidth(200)

        self.method_lbl = QLabel(I18N.t("lab_method_lbl"))
        self.method_lbl.setObjectName("SecondaryLabel")
        self.method_combo = QComboBox()
        self.method_combo.setMinimumWidth(220)

        r1.addWidget(self.scope_lbl)
        r1.addWidget(self.scope_combo)
        r1.addWidget(self.group_target_combo)
        r1.addWidget(self.single_target_combo, 1)
        r1.addSpacing(10)
        r1.addWidget(self.method_lbl)
        r1.addWidget(self.method_combo, 1)
        cfg_vbox.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(14)
        self.chk_gemini = QCheckBox(I18N.t("chk_lab_gemini"))
        self.chk_gemini.setChecked(True)

        self.chk_autoconnect = QCheckBox(I18N.t("chk_lab_autoconnect"))
        self.chk_autoconnect.setChecked(False)

        self.sw_winners_only = AnimatedToggleSwitch(checked=True)
        self.sw_winners_only.toggled.connect(lambda _c: self._render_lab_table())
        self.lbl_winners_only = QLabel(I18N.t("sw_winners_only"))
        self.lbl_winners_only.setObjectName("SecondaryLabel")

        self.btn_run_lab = ActionPillButton("play", I18N.t("btn_start_lab"), variant="gold")
        self.btn_run_lab.clicked.connect(self._on_run_or_stop_lab)

        self.btn_go_home = ActionPillButton("check", I18N.t("btn_promote_home", n=0), variant="emerald")
        self.btn_go_home.clicked.connect(self.go_home_requested.emit)

        r2.addWidget(self.chk_gemini)
        r2.addWidget(self.chk_autoconnect)
        r2.addSpacing(8)
        r2.addWidget(self.sw_winners_only)
        r2.addWidget(self.lbl_winners_only)
        r2.addStretch()
        r2.addWidget(self.btn_go_home)
        r2.addWidget(self.btn_run_lab)
        cfg_vbox.addLayout(r2)
        vec_vbox.addWidget(self.cfg_card)

        self.lab_table = QTableWidget(0, 7)
        self.lab_table.setObjectName("VaultTable")
        self.lab_table.setAlternatingRowColors(True)
        self.lab_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lab_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_table.verticalHeader().setVisible(False)
        lh = self.lab_table.horizontalHeader()
        lh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.lab_table.setColumnWidth(6, 136)
        vec_vbox.addWidget(self.lab_table, 1)

        radar_page = QWidget()
        rad_vbox = QVBoxLayout(radar_page)
        rad_vbox.setContentsMargins(0, 4, 0, 0)
        rad_vbox.setSpacing(10)

        self.rad_bar = NeuCard(mode="raised", radius=18.0, depth=5.0, pad=6.0)
        rad_row = QHBoxLayout(self.rad_bar)
        rad_row.setContentsMargins(18, 14, 18, 14)
        rad_row.setSpacing(10)

        self.radar_port_lbl = QLabel(I18N.t("radar_port_lbl"))
        self.radar_port_lbl.setObjectName("SecondaryLabel")
        self.radar_port_combo = QComboBox()
        for pt in self.CLOUDFLARE_PORTS:
            self.radar_port_combo.addItem(str(pt), pt)
        enforce_english_ltr(self.radar_port_combo, mono_size=10, bold=True)

        self.btn_run_radar = ActionPillButton("play", I18N.t("btn_start_radar"), variant="gold")
        self.btn_run_radar.clicked.connect(self._on_run_or_stop_radar)

        self.btn_apply_sel_ip = QPushButton(I18N.t("btn_apply_sel_cdn"))
        self.btn_apply_sel_ip.setObjectName("GhostBtn")
        self.btn_apply_sel_ip.clicked.connect(lambda: self._apply_selected_radar_ip(False))

        self.btn_apply_all_ip = QPushButton(I18N.t("btn_apply_all_cdn"))
        self.btn_apply_all_ip.setObjectName("EmeraldBtn")
        self.btn_apply_all_ip.clicked.connect(lambda: self._apply_selected_radar_ip(True))

        rad_row.addWidget(self.radar_port_lbl)
        rad_row.addWidget(self.radar_port_combo)
        rad_row.addWidget(self.btn_run_radar)
        rad_row.addStretch()
        rad_row.addWidget(self.btn_apply_sel_ip)
        rad_row.addWidget(self.btn_apply_all_ip)
        rad_vbox.addWidget(self.rad_bar)

        self.radar_table = QTableWidget(0, 6)
        self.radar_table.setObjectName("VaultTable")
        self.radar_table.setAlternatingRowColors(True)
        self.radar_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.radar_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.radar_table.verticalHeader().setVisible(False)
        rh = self.radar_table.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        rad_vbox.addWidget(self.radar_table, 1)

        doh_page = QWidget()
        doh_vbox = QVBoxLayout(doh_page)
        doh_vbox.setContentsMargins(0, 4, 0, 0)
        doh_vbox.setSpacing(10)

        self.doh_bar = NeuCard(mode="raised", radius=18.0, depth=5.0, pad=6.0)
        doh_bar_vbox = QVBoxLayout(self.doh_bar)
        doh_bar_vbox.setContentsMargins(18, 14, 18, 14)
        doh_bar_vbox.setSpacing(10)

        doh_r1 = QHBoxLayout()
        doh_r1.setSpacing(8)
        self.doh_input_edit = QLineEdit()
        self.doh_input_edit.setPlaceholderText(I18N.t("doh_input_ph"))
        enforce_english_ltr(self.doh_input_edit, mono_size=10)

        self.btn_add_doh = ActionPillButton("plus", I18N.t("doh_add_btn"), variant="ghost")
        self.btn_add_doh.clicked.connect(self._on_add_doh_clicked)

        self.btn_run_doh = ActionPillButton("play", I18N.t("btn_start_doh"), variant="gold")
        self.btn_run_doh.clicked.connect(self._on_run_or_stop_doh)

        doh_r1.addWidget(self.doh_input_edit, 1)
        doh_r1.addWidget(self.btn_add_doh)
        doh_r1.addWidget(self.btn_run_doh)
        doh_bar_vbox.addLayout(doh_r1)

        doh_r2 = QHBoxLayout()
        doh_r2.setSpacing(12)
        self.lbl_doh_veil = QLabel(I18N.t("sw_doh_veil"))
        self.lbl_doh_veil.setObjectName("SecondaryLabel")
        self.sw_doh_veil = AnimatedToggleSwitch(checked=False)
        self.sw_doh_veil.toggled.connect(self._on_doh_veil_toggled)
        self.doh_veil_pill = QLabel("OFF")
        self.doh_veil_pill.setObjectName("MutedPill")
        enforce_english_ltr(self.doh_veil_pill, mono_size=9, bold=True)

        self.active_doh_lbl = QLabel("https://cloudflare-dns.com/dns-query")
        self.active_doh_lbl.setObjectName("MutedLabel")
        enforce_english_ltr(self.active_doh_lbl, mono_size=9)

        self.btn_apply_doh_tunnel = QPushButton(I18N.t("btn_apply_doh_tunnel"))
        self.btn_apply_doh_tunnel.setObjectName("EmeraldBtn")
        self.btn_apply_doh_tunnel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_doh_tunnel.clicked.connect(self._apply_selected_doh_to_tunnel)

        doh_r2.addWidget(self.lbl_doh_veil)
        doh_r2.addWidget(self.sw_doh_veil)
        doh_r2.addWidget(self.doh_veil_pill)
        doh_r2.addWidget(self.active_doh_lbl, 1)
        doh_r2.addWidget(self.btn_apply_doh_tunnel)
        doh_bar_vbox.addLayout(doh_r2)
        doh_vbox.addWidget(self.doh_bar)

        self.doh_table = QTableWidget(0, 6)
        self.doh_table.setObjectName("VaultTable")
        self.doh_table.setAlternatingRowColors(True)
        self.doh_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.doh_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.doh_table.verticalHeader().setVisible(False)
        dh = self.doh_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.doh_table.setColumnWidth(5, 136)
        doh_vbox.addWidget(self.doh_table, 1)

        self.stack.addWidget(vec_page)
        self.stack.addWidget(radar_page)
        self.stack.addWidget(doh_page)

        self._populate_scope_combo()
        self.set_vectors([])
        self._apply_table_headers()
        self._sync_scope_selectors()

    def set_doh_repositories(self, repos: list) -> None:
        if self._doh_rows:
            return
        self._doh_rows = [
            {
                "scan_type": "doh",
                "rank": f"#{i + 1}",
                "name": str(r.get("name") or "DoH"),
                "url": str(r.get("url") or ""),
                "category": str(r.get("category") or ""),
                "ping_ms": -1,
                "unblocks": str(r.get("category") or "---"),
                "status": "READY",
                "verified": True,
            }
            for i, r in enumerate(repos or [])
            if isinstance(r, dict) and r.get("url")
        ]
        self._render_doh_table()

    def sync_doh_veil_state(self, active: bool, doh_url: str = "") -> None:
        set_switch_blocked(self.sw_doh_veil, bool(active))
        self.doh_veil_pill.setText("ON" if active else "OFF")
        obj = "EmeraldPill" if active else "MutedPill"
        if self.doh_veil_pill.objectName() != obj:
            self.doh_veil_pill.setObjectName(obj)
            self.doh_veil_pill.style().unpolish(self.doh_veil_pill)
            self.doh_veil_pill.style().polish(self.doh_veil_pill)
        if doh_url:
            self.active_doh_lbl.setText(str(doh_url))

    def _selected_doh_url(self) -> str:
        sel = self.doh_table.currentRow()
        if sel < 0 and self.doh_table.rowCount() > 0:
            sel = 0
        if sel >= 0:
            it = self.doh_table.item(sel, 2)
            if it is not None and it.text().strip().startswith("https://"):
                return it.text().strip()
        txt = self.doh_input_edit.text().strip()
        if txt.startswith("https://"):
            return txt
        return self.active_doh_lbl.text().strip() or "https://cloudflare-dns.com/dns-query"

    def _on_add_doh_clicked(self) -> None:
        txt = self.doh_input_edit.text().strip()
        if not txt:
            txt = QGuiApplication.clipboard().text().strip()
        if txt:
            self.add_doh_custom_requested.emit(txt)
            self.doh_input_edit.clear()

    def _on_run_or_stop_doh(self) -> None:
        if self._is_running:
            self.stop_scanner_requested.emit()
            return
        self._doh_rows.clear()
        self._render_doh_table()
        self.start_doh_scan_requested.emit()

    def _on_doh_veil_toggled(self, checked: bool) -> None:
        url = self._selected_doh_url()
        self.toggle_doh_veil_requested.emit(bool(checked), url)

    def _apply_selected_doh_to_tunnel(self) -> None:
        url = self._selected_doh_url()
        if url:
            self.active_doh_lbl.setText(url)
            self.apply_doh_tunnel_requested.emit(url)

    def _activate_doh_row(self, doh_url: str) -> None:
        if not doh_url:
            return
        self.active_doh_lbl.setText(doh_url)
        self.apply_doh_tunnel_requested.emit(doh_url)
        self.toggle_doh_veil_requested.emit(True, doh_url)

    def _populate_scope_combo(self) -> None:
        prev_scope = self.scope_combo.currentData() or "single"
        with QSignalBlocker(self.scope_combo):
            self.scope_combo.clear()
            self.scope_combo.addItem(I18N.t("scope_batch", n=len(self._batch_uids)), "selected")
            self.scope_combo.addItem(I18N.t("scope_sub"), "group")
            self.scope_combo.addItem(I18N.t("scope_single"), "single")
            i_s = self.scope_combo.findData(prev_scope)
            if i_s >= 0:
                self.scope_combo.setCurrentIndex(i_s)

    def set_vectors(self, vectors: list) -> None:
        self._vectors = list(vectors or [])
        prev_val = str(self.method_combo.currentData() or "ALL")
        with QSignalBlocker(self.method_combo):
            self.method_combo.clear()
            self.method_combo.addItem(I18N.t("method_all"), "ALL")
            for vid, vlabel in normalize_vector_entries(self._vectors):
                self.method_combo.addItem(vlabel, vid)
            idx = self.method_combo.findData(prev_val)
            self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _apply_table_headers(self) -> None:
        self.lab_table.setHorizontalHeaderLabels(
            [
                I18N.t("lab_col_rank"),
                I18N.t("lab_col_profile"),
                I18N.t("lab_col_vector"),
                I18N.t("lab_col_ping"),
                I18N.t("lab_col_upload"),
                I18N.t("lab_col_status"),
                I18N.t("lab_col_action"),
            ]
        )
        self.radar_table.setHorizontalHeaderLabels(
            [
                I18N.t("lab_col_rank"),
                I18N.t("radar_col_ip"),
                I18N.t("radar_col_tcp"),
                I18N.t("radar_col_tls"),
                I18N.t("radar_col_score"),
                I18N.t("lab_col_status"),
            ]
        )
        self.doh_table.setHorizontalHeaderLabels(
            [
                I18N.t("lab_col_rank"),
                I18N.t("doh_col_name"),
                I18N.t("doh_col_url"),
                I18N.t("doh_col_ping"),
                I18N.t("doh_col_unblocks"),
                I18N.t("doh_col_action"),
            ]
        )

    def _on_mode_switched(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)

    def _sync_scope_selectors(self, *_args) -> None:
        scope = str(self.scope_combo.currentData() or "single")
        self.group_target_combo.setVisible(scope == "group")
        self.single_target_combo.setVisible(scope == "single")

    def set_profiles_and_groups(self, profiles: list[dict], groups: list[str], selected_index: int = -1) -> None:
        self._profiles = list(profiles or [])
        self._groups = list(groups or ["Manual"])

        self.group_target_combo.clear()
        for g in self._groups:
            self.group_target_combo.addItem(g, g)

        self.single_target_combo.clear()
        for idx, p in enumerate(self._profiles):
            uid = extract_profile_uid(p, idx)
            name = GeoFlagResolver.clean_display_name(str(p.get("name") or f"Node #{idx + 1}"))
            cc = GeoFlagResolver.resolve_code(p)
            self.single_target_combo.addItem(
                make_flag_qicon(cc, 22, 15),
                f"{name} ({str(p.get('protocol') or 'VLESS').upper()})",
                uid,
            )
        if 0 <= selected_index < len(self._profiles):
            self.single_target_combo.setCurrentIndex(selected_index)

    def receive_vault_batch(self, uid_list: list[str], group_tag: str = "") -> None:
        self.mode_seg.set_current_index(0, emit_signal=True)
        if group_tag and (not uid_list or len(uid_list) > 1):
            self._batch_uids = list(uid_list)
            self._populate_scope_combo()
            idx_g = self.group_target_combo.findData(group_tag)
            if idx_g >= 0:
                self.group_target_combo.setCurrentIndex(idx_g)
            idx_sc = self.scope_combo.findData("group")
            if idx_sc >= 0:
                self.scope_combo.setCurrentIndex(idx_sc)
        else:
            self._batch_uids = list(uid_list)
            self._populate_scope_combo()
            idx_sc = self.scope_combo.findData("selected")
            if idx_sc >= 0:
                self.scope_combo.setCurrentIndex(idx_sc)
        self._sync_scope_selectors()

    def _on_run_or_stop_lab(self) -> None:
        if self._is_running:
            self.stop_scanner_requested.emit()
            return
        self._lab_rows.clear()
        self._render_lab_table()

        scope = str(self.scope_combo.currentData() or "single")
        selected_vector_id = str(self.method_combo.currentData() or "ALL")
        chk_gem = bool(self.chk_gemini.isChecked())
        auto_conn = bool(self.chk_autoconnect.isChecked())

        if scope == "selected":
            uids = list(self._batch_uids)
            grp = ""
        elif scope == "group":
            uids = []
            grp = str(self.group_target_combo.currentData() or "Manual")
        else:
            cur_uid = str(self.single_target_combo.currentData() or "")
            uids = [cur_uid] if cur_uid else []
            grp = ""

        self.start_lab_scan_requested.emit(scope, uids, grp, selected_vector_id, chk_gem, auto_conn)

    def _on_run_or_stop_radar(self) -> None:
        if self._is_running:
            self.stop_scanner_requested.emit()
            return
        self._radar_rows.clear()
        self._render_radar_table()
        port = int(self.radar_port_combo.currentData() or 443)
        self.start_clean_ip_requested.emit(port)

    def update_scan_state(self, is_running: bool, _mode: str = "") -> None:
        self._is_running = bool(is_running)
        if self._is_running:
            self.btn_run_lab.set_label_text(I18N.t("btn_stop_lab"))
            self.btn_run_radar.set_label_text(I18N.t("btn_stop_lab"))
            self.btn_run_doh.set_label_text(I18N.t("btn_stop_lab"))
        else:
            self.btn_run_lab.set_label_text(I18N.t("btn_start_lab"))
            self.btn_run_radar.set_label_text(I18N.t("btn_start_radar"))
            self.btn_run_doh.set_label_text(I18N.t("btn_start_doh"))

    def append_scan_row(self, row: dict) -> None:
        st_type = str(row.get("scan_type") or "").lower()
        if st_type == "doh":
            url_key = str(row.get("url") or "")
            replaced = False
            for idx, existing in enumerate(self._doh_rows):
                if str(existing.get("url") or "") == url_key and url_key:
                    self._doh_rows[idx] = dict(row)
                    replaced = True
                    break
            if not replaced:
                self._doh_rows.append(dict(row))
            self._render_doh_table()
        elif st_type in ("clean_ip", "clean_ip_radar", "radar"):
            key = str(row.get("item_id") or row.get("ip") or row.get("endpoint") or "")
            replaced = False
            for idx, existing in enumerate(self._radar_rows):
                if str(existing.get("item_id") or existing.get("ip") or "") == key and key:
                    self._radar_rows[idx] = dict(row)
                    replaced = True
                    break
            if not replaced:
                self._radar_rows.append(dict(row))
            self._render_radar_table()
        else:
            key = f"{row.get('target_uid', '')}:{row.get('vector_id', row.get('item_id', ''))}"
            replaced = False
            for idx, existing in enumerate(self._lab_rows):
                ek = f"{existing.get('target_uid', '')}:{existing.get('vector_id', existing.get('item_id', ''))}"
                if ek == key and key != ":":
                    self._lab_rows[idx] = dict(row)
                    replaced = True
                    break
            if not replaced:
                self._lab_rows.append(dict(row))
            self._render_lab_table()

    def apply_ranked_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        first_t = str(rows[0].get("scan_type") or "").lower()
        if first_t == "doh":
            self._doh_rows = [dict(r) for r in rows]
            self._render_doh_table()
        elif first_t in ("clean_ip", "clean_ip_radar", "radar"):
            self._radar_rows = [dict(r) for r in rows]
            self._render_radar_table()
        else:
            self._lab_rows = [dict(r) for r in rows]
            self._render_lab_table()

    @staticmethod
    def _is_verified_row(row: dict) -> bool:
        if get_bool(row, "verified", False) or get_bool(row, "passed", False):
            return True
        st = str(row.get("status") or "").upper()
        return st in ("VERIFIED", "TRUE", "PASSED", "OK", "CLEAN")

    def _render_lab_table(self) -> None:
        self.lab_table.setUpdatesEnabled(False)
        try:
            winners_only = self.sw_winners_only.isChecked()
            verified_count = sum(1 for r in self._lab_rows if self._is_verified_row(r))
            self.btn_go_home.set_label_text(I18N.t("btn_promote_home", n=verified_count))

            shown = [r for r in self._lab_rows if (not winners_only) or self._is_verified_row(r)]
            self.lab_table.setRowCount(len(shown))
            mono = make_mono_font(10, bold=True)

            for r_idx, row in enumerate(shown):
                self.lab_table.setRowHeight(r_idx, 42)
                is_ok = self._is_verified_row(row)

                rank_str = str(row.get("rank") or f"#{r_idx + 1}")
                if not rank_str.startswith("#"):
                    rank_str = f"#{rank_str}"
                rk_item = QTableWidgetItem(rank_str)
                rk_item.setFont(mono)
                rk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                rk_item.setForeground(
                    QColor(self._palette.accent_primary if self._palette.is_dark else "#B45309")
                    if r_idx == 0
                    else QColor(self._palette.text_secondary)
                )
                self.lab_table.setItem(r_idx, 0, rk_item)

                title = GeoFlagResolver.clean_display_name(
                    str(row.get("title") or row.get("profile_name") or row.get("item_id") or "Config")
                )
                cc = GeoFlagResolver.resolve_code(row)
                prof_item = QTableWidgetItem(make_flag_qicon(cc, 22, 15), title)
                prof_item.setFont(make_ui_font(10, QFont.Weight.Bold))
                self.lab_table.setItem(r_idx, 1, prof_item)

                vec = str(row.get("vector_id") or row.get("bound_vector") or row.get("category") or "AUTO")
                vec_item = QTableWidgetItem(vec)
                vec_item.setFont(mono)
                vec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                vec_item.setForeground(QColor(self._palette.cyan))
                self.lab_table.setItem(r_idx, 2, vec_item)

                ping = get_int(row, "tunnel_ms", get_int(row, "ping_ms", 0))
                p_item = QTableWidgetItem(f"{ping} ms" if ping > 0 else "---")
                p_item.setFont(mono)
                p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                p_item.setForeground(
                    QColor(self._palette.emerald) if ping > 0 else QColor(self._palette.text_muted)
                )
                self.lab_table.setItem(r_idx, 3, p_item)

                up_ok = get_bool(row, "upload_ok", is_ok)
                gem = is_gemini_verified(row)
                up_str = f"UL:{'OK' if up_ok else '---'} | {'Gemini' if gem else 'AI:---'}"
                up_item = QTableWidgetItem(up_str)
                up_item.setFont(make_mono_font(9))
                up_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                up_item.setForeground(
                    QColor(self._palette.emerald) if gem else QColor(self._palette.text_secondary)
                )
                self.lab_table.setItem(r_idx, 4, up_item)

                verdict = "TRUE (VERIFIED)" if is_ok else str(row.get("status") or "FAILED").upper()
                v_item = QTableWidgetItem(verdict)
                v_item.setFont(mono)
                v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                v_item.setForeground(QColor(self._palette.emerald) if is_ok else QColor(self._palette.danger))
                self.lab_table.setItem(r_idx, 5, v_item)

                target_uid = str(row.get("target_uid") or row.get("uid") or "")
                btn_conn = QPushButton(I18N.t("btn_connect_now"))
                btn_conn.setObjectName("EmeraldBtn" if is_ok else "GhostBtn")
                btn_conn.setEnabled(is_ok)
                btn_conn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_conn.clicked.connect(
                    lambda _c=False, v=vec, u=target_uid: self.connect_winner_requested.emit(v, u)
                )
                cell_w = QWidget()
                cl = QHBoxLayout(cell_w)
                cl.setContentsMargins(6, 3, 6, 3)
                cl.addWidget(btn_conn)
                self.lab_table.setCellWidget(r_idx, 6, cell_w)
        finally:
            self.lab_table.setUpdatesEnabled(True)

    def _render_radar_table(self) -> None:
        self.radar_table.setUpdatesEnabled(False)
        try:
            self.radar_table.setRowCount(len(self._radar_rows))
            mono = make_mono_font(10, bold=True)
            for idx, row in enumerate(self._radar_rows):
                self.radar_table.setRowHeight(idx, 38)
                ip_txt = str(row.get("ip") or row.get("item_id") or row.get("endpoint") or "").split(":")[0]
                tcp = get_int(row, "tcp_ms", 0)
                tls = get_int(row, "tunnel_ms", get_int(row, "tls_ms", 0))
                score = float(row.get("score") or 0.0)
                st = str(row.get("status") or "CLEAN").upper()

                vals = [
                    f"#{idx + 1}",
                    ip_txt,
                    f"{tcp} ms" if tcp > 0 else "---",
                    f"{tls} ms" if tls > 0 else "---",
                    f"{score:.1f}",
                    st,
                ]
                for c_i, txt in enumerate(vals):
                    it = QTableWidgetItem(txt)
                    it.setFont(mono)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if c_i == 1:
                        it.setData(Qt.ItemDataRole.UserRole, ip_txt)
                        it.setForeground(
                            QColor(self._palette.accent_primary if self._palette.is_dark else "#B45309")
                        )
                    elif c_i == 5:
                        it.setForeground(QColor(self._palette.emerald))
                    self.radar_table.setItem(idx, c_i, it)
        finally:
            self.radar_table.setUpdatesEnabled(True)

    def _render_doh_table(self) -> None:
        self.doh_table.setUpdatesEnabled(False)
        try:
            self.doh_table.setRowCount(len(self._doh_rows))
            mono = make_mono_font(10, bold=True)
            mono_reg = make_mono_font(9, bold=False)

            for idx, row in enumerate(self._doh_rows):
                self.doh_table.setRowHeight(idx, 42)
                is_ok = get_bool(row, "verified", False)
                st = str(row.get("status") or "READY").upper()
                url_str = str(row.get("url") or "")
                name_str = strip_emojis(str(row.get("name") or f"DoH #{idx + 1}"))
                ping = get_int(row, "ping_ms", -1)
                unblocks = str(row.get("unblocks") or row.get("detail") or "---")

                rk_it = QTableWidgetItem(str(row.get("rank") or f"#{idx + 1}"))
                rk_it.setFont(mono)
                rk_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.doh_table.setItem(idx, 0, rk_it)

                nm_it = QTableWidgetItem(name_str)
                nm_it.setFont(make_ui_font(10, QFont.Weight.Bold))
                self.doh_table.setItem(idx, 1, nm_it)

                url_it = QTableWidgetItem(url_str)
                url_it.setFont(mono_reg)
                url_it.setForeground(QColor(self._palette.cyan))
                self.doh_table.setItem(idx, 2, url_it)

                p_it = QTableWidgetItem(f"{ping} ms" if ping > 0 else "---")
                p_it.setFont(mono)
                p_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                p_it.setForeground(
                    QColor(self._palette.emerald) if ping > 0 else QColor(self._palette.text_muted)
                )
                self.doh_table.setItem(idx, 3, p_it)

                ub_it = QTableWidgetItem(unblocks)
                ub_it.setFont(mono_reg)
                ub_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                ub_it.setForeground(
                    QColor(self._palette.emerald) if (is_ok and st == "VERIFIED") else QColor(self._palette.text_secondary)
                )
                self.doh_table.setItem(idx, 4, ub_it)

                btn_use = QPushButton(I18N.t("btn_use_doh"))
                btn_use.setObjectName("EmeraldBtn" if is_ok else "GhostBtn")
                btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_use.clicked.connect(lambda _c=False, u=url_str: self._activate_doh_row(u))
                cell_w = QWidget()
                cl = QHBoxLayout(cell_w)
                cl.setContentsMargins(6, 3, 6, 3)
                cl.addWidget(btn_use)
                self.doh_table.setCellWidget(idx, 5, cell_w)
        finally:
            self.doh_table.setUpdatesEnabled(True)

    def _apply_selected_radar_ip(self, apply_all_cdn: bool) -> None:
        sel = self.radar_table.currentRow()
        if sel < 0 and self.radar_table.rowCount() > 0:
            sel = 0
        if sel >= 0:
            it = self.radar_table.item(sel, 1)
            if it is not None:
                ip_addr = str(it.data(Qt.ItemDataRole.UserRole) or it.text()).strip()
                if ip_addr:
                    self.apply_clean_ip_requested.emit(ip_addr, apply_all_cdn)

    def retranslate_ui(self) -> None:
        self.title_lbl.setText(I18N.t("lab_title"))
        self.sub_lbl.setText(I18N.t("lab_subtitle"))
        self.mode_seg.update_labels(
            [
                I18N.t("lab_mode_vectors"),
                I18N.t("lab_mode_clean_ip"),
                I18N.t("lab_mode_doh"),
            ]
        )
        self.scope_lbl.setText(I18N.t("lab_scope_lbl"))
        self.method_lbl.setText(I18N.t("lab_method_lbl"))
        self._populate_scope_combo()
        self.set_vectors(self._vectors)
        self.chk_gemini.setText(I18N.t("chk_lab_gemini"))
        self.chk_autoconnect.setText(I18N.t("chk_lab_autoconnect"))
        self.lbl_winners_only.setText(I18N.t("sw_winners_only"))
        self.radar_port_lbl.setText(I18N.t("radar_port_lbl"))
        self.btn_apply_sel_ip.setText(I18N.t("btn_apply_sel_cdn"))
        self.btn_apply_all_ip.setText(I18N.t("btn_apply_all_cdn"))
        self.doh_input_edit.setPlaceholderText(I18N.t("doh_input_ph"))
        self.btn_add_doh.set_label_text(I18N.t("doh_add_btn"))
        self.lbl_doh_veil.setText(I18N.t("sw_doh_veil"))
        self.btn_apply_doh_tunnel.setText(I18N.t("btn_apply_doh_tunnel"))
        self.update_scan_state(self._is_running)
        self._apply_table_headers()
        self._render_lab_table()
        self._render_doh_table()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.mode_seg.set_palette_theme(palette)
        self.cfg_card.set_palette_theme(palette)
        self.rad_bar.set_palette_theme(palette)
        self.doh_bar.set_palette_theme(palette)
        self.sw_winners_only.set_palette_theme(palette)
        self.sw_doh_veil.set_palette_theme(palette)
        for b in (self.btn_run_lab, self.btn_go_home, self.btn_run_radar, self.btn_add_doh, self.btn_run_doh):
            b.set_palette_theme(palette)
        self._render_lab_table()
        self._render_radar_table()
        self._render_doh_table()


class RoutingSettingsPage(QWidget):
    settings_changed = Signal(dict)
    setting_key_changed = Signal(str, object)
    discover_apps_requested = Signal()
    launch_app_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette: ThemePalette = DARK_PALETTE
        self._updating = False
        self._syncing_app_table = False
        self._domains_as_list = False
        self._discovered_apps: list[dict] = []
        self._switches: list[AnimatedToggleSwitch] = []
        self._neu_cards: list[NeuCard] = []
        self._switch_labels: list[tuple[QLabel, str, QLabel | None, str | None]] = []

        self._domain_debounce = QTimer(self)
        self._domain_debounce.setSingleShot(True)
        self._domain_debounce.setInterval(450)
        self._domain_debounce.timeout.connect(self._emit_all)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(10)

        t_col = QVBoxLayout()
        t_col.setSpacing(2)
        self.title_lbl = QLabel(I18N.t("settings_title"))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(I18N.t("settings_subtitle"))
        self.sub_lbl.setObjectName("MutedLabel")
        t_col.addWidget(self.title_lbl)
        t_col.addWidget(self.sub_lbl)
        root.addLayout(t_col)

        self.sub_tabs = SegmentedControl(
            [
                I18N.t("stab_routing"),
                I18N.t("stab_per_app"),
                I18N.t("stab_behavior"),
                I18N.t("stab_core"),
            ]
        )
        self.sub_tabs.current_changed.connect(lambda idx: self.stack.setCurrentIndex(idx))
        root.addWidget(self.sub_tabs)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.stack.addWidget(self._build_routing_tab())
        self.stack.addWidget(self._build_per_app_tab())
        self.stack.addWidget(self._build_behavior_tab())
        self.stack.addWidget(self._build_core_tab())

    def _build_routing_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 4, 6, 8)
        vbox.setSpacing(12)

        card = NeuCard(mode="raised", radius=18.0, depth=5.2, pad=6.5)
        self._neu_cards.append(card)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 18, 20, 18)
        cv.setSpacing(12)

        rm_row = QHBoxLayout()
        self.lbl_rmode = QLabel(I18N.t("routing_mode_lbl"))
        self.lbl_rmode.setObjectName("SecondaryLabel")
        self.routing_mode_combo = QComboBox()
        self.routing_mode_combo.currentIndexChanged.connect(self._emit_all)
        rm_row.addWidget(self.lbl_rmode)
        rm_row.addWidget(self.routing_mode_combo, 1)
        cv.addLayout(rm_row)

        self.sw_block_quic = self._add_switch_item(
            cv, "block_quic", "sw_block_quic", "sw_block_quic_desc", True
        )

        dns_grid = QGridLayout()
        dns_grid.setHorizontalSpacing(14)
        dns_grid.setVerticalSpacing(6)
        self.lbl_remote_dns = QLabel(I18N.t("remote_dns_lbl"))
        self.lbl_remote_dns.setObjectName("SecondaryLabel")
        self.remote_dns_edit = QLineEdit("https://1.1.1.1/dns-query")
        enforce_english_ltr(self.remote_dns_edit, mono_size=10)
        self.remote_dns_edit.editingFinished.connect(self._emit_all)

        self.lbl_dom_dns = QLabel(I18N.t("domestic_dns_lbl"))
        self.lbl_dom_dns.setObjectName("SecondaryLabel")
        self.domestic_dns_edit = QLineEdit("178.22.122.100")
        enforce_english_ltr(self.domestic_dns_edit, mono_size=10)
        self.domestic_dns_edit.editingFinished.connect(self._emit_all)

        dns_grid.addWidget(self.lbl_remote_dns, 0, 0)
        dns_grid.addWidget(self.lbl_dom_dns, 0, 1)
        dns_grid.addWidget(self.remote_dns_edit, 1, 0)
        dns_grid.addWidget(self.domestic_dns_edit, 1, 1)
        cv.addLayout(dns_grid)

        rules_grid = QGridLayout()
        rules_grid.setHorizontalSpacing(12)
        rules_grid.setVerticalSpacing(6)

        self.lbl_direct_dom = QLabel(I18N.t("direct_domains_lbl"))
        self.lbl_direct_dom.setObjectName("SecondaryLabel")
        self.direct_domains_edit = QPlainTextEdit("geosite:ir\ngeoip:ir\ngeoip:private")
        self.direct_domains_edit.setObjectName("CodeEditor")
        self.direct_domains_edit.setMaximumHeight(95)
        enforce_english_ltr(self.direct_domains_edit, mono_size=9)
        self.direct_domains_edit.textChanged.connect(self._schedule_domain_emit)

        self.lbl_proxy_dom = QLabel(I18N.t("proxy_domains_lbl"))
        self.lbl_proxy_dom.setObjectName("SecondaryLabel")
        self.proxy_domains_edit = QPlainTextEdit("geosite:google\ngeosite:youtube\n*.gemini.google.com")
        self.proxy_domains_edit.setObjectName("CodeEditor")
        self.proxy_domains_edit.setMaximumHeight(95)
        enforce_english_ltr(self.proxy_domains_edit, mono_size=9)
        self.proxy_domains_edit.textChanged.connect(self._schedule_domain_emit)

        self.lbl_block_dom = QLabel(I18N.t("blocked_domains_lbl"))
        self.lbl_block_dom.setObjectName("SecondaryLabel")
        self.blocked_domains_edit = QPlainTextEdit("geosite:category-ads-all")
        self.blocked_domains_edit.setObjectName("CodeEditor")
        self.blocked_domains_edit.setMaximumHeight(95)
        enforce_english_ltr(self.blocked_domains_edit, mono_size=9)
        self.blocked_domains_edit.textChanged.connect(self._schedule_domain_emit)

        rules_grid.addWidget(self.lbl_direct_dom, 0, 0)
        rules_grid.addWidget(self.lbl_proxy_dom, 0, 1)
        rules_grid.addWidget(self.lbl_block_dom, 0, 2)
        rules_grid.addWidget(self.direct_domains_edit, 1, 0)
        rules_grid.addWidget(self.proxy_domains_edit, 1, 1)
        rules_grid.addWidget(self.blocked_domains_edit, 1, 2)
        cv.addLayout(rules_grid)

        vbox.addWidget(card)
        vbox.addStretch()
        self._populate_routing_combos()
        return make_transparent_scroll_area(host)

    def _build_per_app_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 4, 6, 8)
        vbox.setSpacing(12)

        card = NeuCard(mode="raised", radius=18.0, depth=5.2, pad=6.5)
        self._neu_cards.append(card)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(10)

        self.lbl_pa_title = QLabel(I18N.t("per_app_launcher_title"))
        self.lbl_pa_title.setFont(make_ui_font(11, QFont.Weight.ExtraBold))
        self.lbl_pa_desc = QLabel(I18N.t("per_app_launcher_desc"))
        self.lbl_pa_desc.setObjectName("MutedLabel")
        self.lbl_pa_desc.setWordWrap(True)
        cv.addWidget(self.lbl_pa_title)
        cv.addWidget(self.lbl_pa_desc)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self.lbl_pa_mode = QLabel(I18N.t("per_app_mode_lbl"))
        self.lbl_pa_mode.setObjectName("SecondaryLabel")
        self.per_app_mode_combo = QComboBox()
        self.per_app_mode_combo.currentIndexChanged.connect(self._emit_all)

        self.btn_refresh_apps = ActionPillButton("refresh", I18N.t("btn_refresh_apps"), variant="ghost")
        self.btn_refresh_apps.clicked.connect(self.discover_apps_requested.emit)

        self.btn_browse_exe = ActionPillButton("plus", I18N.t("btn_browse_exe"), variant="emerald")
        self.btn_browse_exe.clicked.connect(self._browse_and_add_exe)

        self.btn_launch_sel_app = ActionPillButton("bolt", I18N.t("btn_launch_custom"), variant="gold")
        self.btn_launch_sel_app.clicked.connect(self._launch_currently_selected_table_app)

        mode_row.addWidget(self.lbl_pa_mode)
        mode_row.addWidget(self.per_app_mode_combo, 1)
        mode_row.addWidget(self.btn_refresh_apps)
        mode_row.addWidget(self.btn_browse_exe)
        mode_row.addWidget(self.btn_launch_sel_app)
        cv.addLayout(mode_row)

        self.app_table = QTableWidget(0, 5)
        self.app_table.setObjectName("VaultTable")
        self.app_table.setMinimumHeight(230)
        self.app_table.setAlternatingRowColors(True)
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.app_table.verticalHeader().setVisible(False)
        self.app_table.itemChanged.connect(self._on_app_table_check_changed)
        ah = self.app_table.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.app_table.setColumnWidth(0, 54)
        ah.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ah.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ah.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ah.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.app_table.setColumnWidth(4, 152)
        cv.addWidget(self.app_table, 1)

        self.lbl_pa_manual = QLabel(I18N.t("per_app_manual_lbl"))
        self.lbl_pa_manual.setObjectName("SecondaryLabel")
        self.per_app_list_edit = QPlainTextEdit("")
        self.per_app_list_edit.setObjectName("CodeEditor")
        self.per_app_list_edit.setPlaceholderText("Claude.exe\nCursor.exe\nChatGPT.exe\nTelegram.exe")
        self.per_app_list_edit.setMaximumHeight(74)
        enforce_english_ltr(self.per_app_list_edit, mono_size=9)
        self.per_app_list_edit.textChanged.connect(self._schedule_domain_emit)

        cv.addWidget(self.lbl_pa_manual)
        cv.addWidget(self.per_app_list_edit)
        vbox.addWidget(card, 1)

        self._populate_per_app_combos()
        self._apply_per_app_headers()
        return make_transparent_scroll_area(host)

    def _populate_per_app_combos(self) -> None:
        prev = str(self.per_app_mode_combo.currentData() or "off")
        with QSignalBlocker(self.per_app_mode_combo):
            self.per_app_mode_combo.clear()
            self.per_app_mode_combo.addItem(I18N.t("pamode_off"), "off")
            self.per_app_mode_combo.addItem(I18N.t("pamode_include"), "include")
            self.per_app_mode_combo.addItem(I18N.t("pamode_exclude"), "exclude")
            idx = self.per_app_mode_combo.findData(prev)
            if idx >= 0:
                self.per_app_mode_combo.setCurrentIndex(idx)

    def _apply_per_app_headers(self) -> None:
        self.app_table.setHorizontalHeaderLabels(
            [
                I18N.t("per_app_col_sel"),
                I18N.t("per_app_col_name"),
                I18N.t("per_app_col_exe"),
                I18N.t("per_app_col_cat"),
                I18N.t("per_app_col_launch"),
            ]
        )

    def _current_per_app_exe_set(self) -> set[str]:
        raw = self.per_app_list_edit.toPlainText()
        out: set[str] = set()
        for ln in raw.replace(";", "\n").replace(",", "\n").splitlines():
            tok = os.path.basename(ln.strip()).lower()
            if tok:
                out.add(tok)
        return out

    def set_discovered_apps(self, apps: list) -> None:
        self._discovered_apps = [dict(a) for a in (apps or []) if isinstance(a, dict)]
        self._render_app_table()

    def _render_app_table(self) -> None:
        self._syncing_app_table = True
        self.app_table.setUpdatesEnabled(False)
        try:
            checked_set = self._current_per_app_exe_set()
            self.app_table.setRowCount(len(self._discovered_apps))
            mono = make_mono_font(9, bold=True)

            for r_idx, app in enumerate(self._discovered_apps):
                self.app_table.setRowHeight(r_idx, 42)
                exe_name = str(app.get("exe") or "").strip()
                full_path = str(app.get("path") or exe_name).strip()
                title = strip_emojis(str(app.get("name") or exe_name))
                cat = str(app.get("category") or "App")
                st = str(app.get("status") or "INSTALLED")

                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                chk.setCheckState(
                    Qt.CheckState.Checked if exe_name.lower() in checked_set else Qt.CheckState.Unchecked
                )
                chk.setData(Qt.ItemDataRole.UserRole, exe_name)
                chk.setData(Qt.ItemDataRole.UserRole + 1, full_path)
                self.app_table.setItem(r_idx, 0, chk)

                nm_it = QTableWidgetItem(title)
                nm_it.setFont(make_ui_font(10, QFont.Weight.Bold))
                if "AI" in cat:
                    nm_it.setForeground(QColor(self._palette.accent_primary if self._palette.is_dark else "#B45309"))
                self.app_table.setItem(r_idx, 1, nm_it)

                ex_it = QTableWidgetItem(exe_name)
                ex_it.setFont(mono)
                ex_it.setForeground(QColor(self._palette.cyan))
                self.app_table.setItem(r_idx, 2, ex_it)

                cat_it = QTableWidgetItem(f"{cat} ({st})")
                cat_it.setFont(mono)
                cat_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cat_it.setForeground(
                    QColor(self._palette.emerald) if st == "RUNNING" else QColor(self._palette.text_muted)
                )
                self.app_table.setItem(r_idx, 3, cat_it)

                btn_launch = QPushButton(I18N.t("btn_launch_app_row"))
                btn_launch.setObjectName("EmeraldBtn")
                btn_launch.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_launch.clicked.connect(lambda _c=False, p=full_path: self.launch_app_requested.emit(p))
                cell_w = QWidget()
                cl = QHBoxLayout(cell_w)
                cl.setContentsMargins(6, 3, 6, 3)
                cl.addWidget(btn_launch)
                self.app_table.setCellWidget(r_idx, 4, cell_w)
        finally:
            self.app_table.setUpdatesEnabled(True)
            self._syncing_app_table = False

    def _on_app_table_check_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_app_table or item.column() != 0:
            return
        exe_name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not exe_name:
            return
        current_lines = [
            ln.strip()
            for ln in self.per_app_list_edit.toPlainText().splitlines()
            if ln.strip()
        ]
        low_map = {os.path.basename(x).lower(): x for x in current_lines}
        if item.checkState() == Qt.CheckState.Checked:
            low_map[exe_name.lower()] = exe_name
            if str(self.per_app_mode_combo.currentData() or "off") == "off":
                idx_inc = self.per_app_mode_combo.findData("include")
                if idx_inc >= 0:
                    self.per_app_mode_combo.setCurrentIndex(idx_inc)
        else:
            low_map.pop(exe_name.lower(), None)

        self.per_app_list_edit.blockSignals(True)
        self.per_app_list_edit.setPlainText("\n".join(low_map.values()))
        self.per_app_list_edit.blockSignals(False)
        self._emit_all()

    def _browse_and_add_exe(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Application Executable (.exe)",
            "",
            "Windows Executables (*.exe)",
        )
        if not fpath:
            return
        exe_base = os.path.basename(fpath)
        cur_lines = [ln.strip() for ln in self.per_app_list_edit.toPlainText().splitlines() if ln.strip()]
        if exe_base.lower() not in {os.path.basename(x).lower() for x in cur_lines}:
            cur_lines.append(exe_base)
            self.per_app_list_edit.setPlainText("\n".join(cur_lines))
        if not any(str(a.get("exe") or "").lower() == exe_base.lower() for a in self._discovered_apps):
            self._discovered_apps.insert(0, {
                "name": os.path.splitext(exe_base)[0].title(),
                "exe": exe_base,
                "path": fpath,
                "status": "CUSTOM",
                "category": "Custom App",
            })
        self._render_app_table()
        self.launch_app_requested.emit(fpath)

    def _launch_currently_selected_table_app(self) -> None:
        row = self.app_table.currentRow()
        if row < 0 and self.app_table.rowCount() > 0:
            row = 0
        if row >= 0:
            it = self.app_table.item(row, 0)
            if it is not None:
                full_p = str(it.data(Qt.ItemDataRole.UserRole + 1) or it.data(Qt.ItemDataRole.UserRole) or "")
                if full_p:
                    self.launch_app_requested.emit(full_p)
                    return
        self._browse_and_add_exe()

    def _build_behavior_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 4, 6, 8)
        vbox.setSpacing(12)

        card = NeuCard(mode="raised", radius=18.0, depth=5.2, pad=6.5)
        self._neu_cards.append(card)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(22, 18, 22, 18)
        cv.setSpacing(14)

        self.sw_min_tray = self._add_switch_item(
            cv, "minimize_to_tray", "sw_min_tray", "sw_min_tray_desc", True
        )
        self.sw_pool_fallback = self._add_switch_item(
            cv, "auto_pool_fallback", "sw_pool_fallback", "sw_pool_fallback_desc", True
        )
        self.sw_yt_guard = self._add_switch_item(
            cv, "require_youtube_6s", "sw_yt_guard", "sw_yt_guard_desc", True
        )
        self.sw_upload_burst = self._add_switch_item(
            cv, "verify_upload_stream", "sw_upload_burst", "sw_upload_burst_desc", True
        )
        self.sw_watchdog = self._add_switch_item(
            cv, "self_healing_watchdog", "sw_watchdog", "sw_watchdog_desc", True
        )

        sub_row = QHBoxLayout()
        self.lbl_sub_hrs = QLabel(I18N.t("sub_autoupdate_lbl"))
        self.lbl_sub_hrs.setObjectName("SecondaryLabel")
        self.sub_hours_combo = QComboBox()
        self.sub_hours_combo.currentIndexChanged.connect(self._on_sub_hours_combo_changed)
        sub_row.addWidget(self.lbl_sub_hrs)
        sub_row.addWidget(self.sub_hours_combo, 1)
        cv.addLayout(sub_row)

        vbox.addWidget(card)
        vbox.addStretch()
        self._populate_behavior_combos()
        return make_transparent_scroll_area(host)

    def _build_core_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 4, 6, 8)
        vbox.setSpacing(12)

        card = NeuCard(mode="raised", radius=18.0, depth=5.2, pad=6.5)
        self._neu_cards.append(card)
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 18, 20, 20)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        self.engine_mode_combo = QComboBox()
        self.manual_vec_combo = QComboBox()
        enforce_english_ltr(self.manual_vec_combo, mono_size=10, bold=True)
        self.set_vectors([])

        frag_hdr_w = QWidget()
        fh_row = QHBoxLayout(frag_hdr_w)
        fh_row.setContentsMargins(0, 0, 0, 0)
        self.sw_frag = AnimatedToggleSwitch(checked=True)
        self.sw_frag.toggled.connect(lambda c: self._on_single_switch("fragment_enabled", c))
        self._switches.append(self.sw_frag)
        self.lbl_sw_frag = QLabel(I18N.t("sw_native_frag"))
        self.lbl_sw_frag.setObjectName("SecondaryLabel")
        fh_row.addWidget(self.sw_frag)
        fh_row.addWidget(self.lbl_sw_frag, 1)

        mux_hdr_w = QWidget()
        mh_row = QHBoxLayout(mux_hdr_w)
        mh_row.setContentsMargins(0, 0, 0, 0)
        self.sw_mux = AnimatedToggleSwitch(checked=False)
        self.sw_mux.toggled.connect(lambda c: self._on_single_switch("mux_enabled", c))
        self._switches.append(self.sw_mux)
        self.lbl_sw_mux = QLabel(I18N.t("sw_mux"))
        self.lbl_sw_mux.setObjectName("SecondaryLabel")
        self.mux_conc_spin = QSpinBox()
        self.mux_conc_spin.setRange(1, 64)
        self.mux_conc_spin.setValue(8)
        enforce_english_ltr(self.mux_conc_spin, mono_size=10)
        mh_row.addWidget(self.sw_mux)
        mh_row.addWidget(self.lbl_sw_mux, 1)
        mh_row.addWidget(self.mux_conc_spin)

        self.frag_packets_combo = QComboBox()
        for pk in ("tlshello", "1-3", "1-5"):
            self.frag_packets_combo.addItem(pk, pk)
        enforce_english_ltr(self.frag_packets_combo, mono_size=10)

        self.frag_len_edit = QLineEdit("5-16")
        enforce_english_ltr(self.frag_len_edit, mono_size=10)

        self.frag_int_edit = QLineEdit("2-3")
        enforce_english_ltr(self.frag_int_edit, mono_size=10)

        self.fp_combo = QComboBox()
        enforce_english_ltr(self.fp_combo, mono_size=10)
        self.set_fingerprints([])

        self.alpn_combo = QComboBox()
        for alpn in ("auto", "h2,http/1.1", "http/1.1", "h2"):
            self.alpn_combo.addItem(alpn, alpn)
        enforce_english_ltr(self.alpn_combo, mono_size=10)

        self.ed_combo = QComboBox()
        for ed in (0, 2048, 2560):
            self.ed_combo.addItem(f"{ed} B" if ed > 0 else "0 (Off)", ed)
        self.ed_combo.setCurrentIndex(1)
        enforce_english_ltr(self.ed_combo, mono_size=10)

        self.stride_spin = QSpinBox()
        self.stride_spin.setRange(0, 8192)
        self.stride_spin.setSingleStep(50)
        self.stride_spin.setValue(400)
        enforce_english_ltr(self.stride_spin, mono_size=10)

        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(0, 2048)
        self.jitter_spin.setValue(32)
        enforce_english_ltr(self.jitter_spin, mono_size=10)

        self.mtu_spin = QSpinBox()
        self.mtu_spin.setRange(1280, 9000)
        self.mtu_spin.setValue(1500)
        enforce_english_ltr(self.mtu_spin, mono_size=10)

        self.socks_spin = QSpinBox()
        self.socks_spin.setRange(1024, 65535)
        self.socks_spin.setValue(10808)
        enforce_english_ltr(self.socks_spin, mono_size=10)

        self.http_spin = QSpinBox()
        self.http_spin.setRange(1024, 65535)
        self.http_spin.setValue(10809)
        enforce_english_ltr(self.http_spin, mono_size=10)

        self.bridge_spin = QSpinBox()
        self.bridge_spin.setRange(1024, 65535)
        self.bridge_spin.setValue(10810)
        enforce_english_ltr(self.bridge_spin, mono_size=10)

        grid.addWidget(frag_hdr_w, 0, 0)
        grid.addWidget(mux_hdr_w, 0, 1)

        self._core_field_labels: list[tuple[QLabel, str]] = []
        core_fields = [
            ("engine_mode_lbl", self.engine_mode_combo, 1, 0),
            ("manual_vec_lbl", self.manual_vec_combo, 1, 1),
            ("frag_packets_lbl", self.frag_packets_combo, 2, 0),
            ("frag_length_lbl", self.frag_len_edit, 2, 1),
            ("frag_interval_lbl", self.frag_int_edit, 3, 0),
            ("tls_fp_lbl", self.fp_combo, 3, 1),
            ("alpn_lbl", self.alpn_combo, 4, 0),
            ("early_data_lbl", self.ed_combo, 4, 1),
            ("stride_lbl", self.stride_spin, 5, 0),
            ("jitter_lbl", self.jitter_spin, 5, 1),
            ("tun_mtu_lbl", self.mtu_spin, 6, 0),
            ("socks_port_lbl", self.socks_spin, 6, 1),
            ("http_port_lbl", self.http_spin, 7, 0),
            ("bridge_port_lbl", self.bridge_spin, 7, 1),
        ]
        for key_str, widget, r, c in core_fields:
            lbl = QLabel(I18N.t(key_str))
            lbl.setObjectName("SecondaryLabel")
            self._core_field_labels.append((lbl, key_str))
            grid.addWidget(lbl, r * 2 - 1, c)
            grid.addWidget(widget, r * 2, c)

        for cb in (
            self.engine_mode_combo,
            self.manual_vec_combo,
            self.frag_packets_combo,
            self.fp_combo,
            self.alpn_combo,
            self.ed_combo,
        ):
            cb.currentIndexChanged.connect(self._emit_all)

        for ed_w in (self.frag_len_edit, self.frag_int_edit):
            ed_w.editingFinished.connect(self._emit_all)

        for sp_w in (
            self.mux_conc_spin,
            self.stride_spin,
            self.jitter_spin,
            self.mtu_spin,
            self.socks_spin,
            self.http_spin,
            self.bridge_spin,
        ):
            sp_w.valueChanged.connect(self._emit_all)

        vbox.addWidget(card)
        vbox.addStretch()
        self._populate_core_combos()
        return make_transparent_scroll_area(host)

    def _schedule_domain_emit(self) -> None:
        if not self._updating:
            self._domain_debounce.start()

    def _on_sub_hours_combo_changed(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        hrs = int(self.sub_hours_combo.itemData(idx) or 0)
        self.setting_key_changed.emit("sub_auto_update_hours", hrs)
        self._emit_all()

    def _populate_routing_combos(self) -> None:
        prev = str(self.routing_mode_combo.currentData() or "bypass_ir")
        if prev == "bypass_iran_lan":
            prev = "bypass_ir"
        with QSignalBlocker(self.routing_mode_combo):
            self.routing_mode_combo.clear()
            self.routing_mode_combo.addItem(I18N.t("rmode_bypass_ir"), "bypass_ir")
            self.routing_mode_combo.addItem(I18N.t("rmode_global"), "global")
            self.routing_mode_combo.addItem(I18N.t("rmode_custom"), "custom")
            i = self.routing_mode_combo.findData(prev)
            if i >= 0:
                self.routing_mode_combo.setCurrentIndex(i)

    def _populate_behavior_combos(self) -> None:
        prev = self.sub_hours_combo.currentData()
        hrs_val = int(prev) if prev is not None else 6
        with QSignalBlocker(self.sub_hours_combo):
            self.sub_hours_combo.clear()
            for h in SUB_UPDATE_INTERVAL_HOURS:
                lbl = I18N.t("sub_off") if h == 0 else I18N.t("sub_every_h", h=h)
                self.sub_hours_combo.addItem(lbl, h)
            i = self.sub_hours_combo.findData(hrs_val)
            if i >= 0:
                self.sub_hours_combo.setCurrentIndex(i)

    def _populate_core_combos(self) -> None:
        prev = self.engine_mode_combo.currentData() or "auto_hybrid"
        with QSignalBlocker(self.engine_mode_combo):
            self.engine_mode_combo.clear()
            self.engine_mode_combo.addItem(I18N.t("emode_hybrid"), "auto_hybrid")
            self.engine_mode_combo.addItem(I18N.t("emode_prop"), "proprietary_only")
            self.engine_mode_combo.addItem(I18N.t("emode_frag"), "fragment_only")
            i = self.engine_mode_combo.findData(prev)
            if i >= 0:
                self.engine_mode_combo.setCurrentIndex(i)

    def _add_switch_item(
        self,
        layout: QVBoxLayout,
        setting_key: str,
        title_i18n: str,
        desc_i18n: str,
        default_val: bool,
    ) -> AnimatedToggleSwitch:
        row = QHBoxLayout()
        row.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        t_lbl = QLabel(I18N.t(title_i18n))
        t_lbl.setFont(make_ui_font(10, QFont.Weight.Bold))
        d_lbl = QLabel(I18N.t(desc_i18n))
        d_lbl.setObjectName("MutedLabel")
        d_lbl.setWordWrap(True)
        col.addWidget(t_lbl)
        col.addWidget(d_lbl)

        sw = AnimatedToggleSwitch(checked=default_val)
        sw.toggled.connect(lambda c, k=setting_key: self._on_single_switch(k, c))
        self._switches.append(sw)
        self._switch_labels.append((t_lbl, title_i18n, d_lbl, desc_i18n))

        row.addLayout(col, 1)
        row.addWidget(sw)
        layout.addLayout(row)
        return sw

    def _on_single_switch(self, key: str, checked: bool) -> None:
        if self._updating:
            return
        self.setting_key_changed.emit(key, bool(checked))
        self.settings_changed.emit(self.collect_settings())

    def set_vectors(self, vectors: list) -> None:
        prev = str(self.manual_vec_combo.currentData() or "AUTO")
        self._updating = True
        with QSignalBlocker(self.manual_vec_combo):
            self.manual_vec_combo.clear()
            self.manual_vec_combo.addItem("AUTO", "AUTO")
            for vid, vlabel in normalize_vector_entries(vectors):
                self.manual_vec_combo.addItem(vlabel, vid)
            i = self.manual_vec_combo.findData(prev)
            self.manual_vec_combo.setCurrentIndex(i if i >= 0 else 0)
        self._updating = False

    def set_fingerprints(self, fingerprints: list) -> None:
        prev = str(self.fp_combo.currentData() or "custom_poly")
        self._updating = True
        with QSignalBlocker(self.fp_combo):
            self.fp_combo.clear()
            for fp_val, fp_lbl in normalize_fingerprint_entries(fingerprints):
                self.fp_combo.addItem(fp_lbl, fp_val)
            i = self.fp_combo.findData(prev)
            self.fp_combo.setCurrentIndex(i if i >= 0 else 0)
        self._updating = False

    def set_sub_auto_update_hours_silent(self, hours: int) -> None:
        self._updating = True
        try:
            with QSignalBlocker(self.sub_hours_combo):
                idx = self.sub_hours_combo.findData(int(hours or 0))
                if idx >= 0:
                    self.sub_hours_combo.setCurrentIndex(idx)
        finally:
            self._updating = False

    def apply_settings(self, s: dict) -> None:
        if not isinstance(s, dict):
            return
        self._updating = True
        try:
            for sw, key in (
                (self.sw_block_quic, "block_quic"),
                (self.sw_min_tray, "minimize_to_tray"),
                (self.sw_pool_fallback, "auto_pool_fallback"),
                (self.sw_yt_guard, "require_youtube_6s"),
                (self.sw_upload_burst, "verify_upload_stream"),
                (self.sw_watchdog, "self_healing_watchdog"),
                (self.sw_frag, "fragment_enabled"),
                (self.sw_mux, "mux_enabled"),
            ):
                if key in s:
                    set_switch_blocked(sw, get_bool(s, key, sw.isChecked()))

            if "routing_mode" in s and s["routing_mode"] is not None:
                rm_val = str(s["routing_mode"]).strip()
                if rm_val == "bypass_iran_lan":
                    rm_val = "bypass_ir"
                idx_rm = self.routing_mode_combo.findData(rm_val)
                if idx_rm >= 0:
                    self.routing_mode_combo.setCurrentIndex(idx_rm)

            if "per_app_mode" in s and s["per_app_mode"] is not None:
                pa_val = str(s["per_app_mode"]).strip().lower()
                idx_pa = self.per_app_mode_combo.findData(pa_val)
                if idx_pa >= 0:
                    self.per_app_mode_combo.setCurrentIndex(idx_pa)

            if "per_app_list" in s and s["per_app_list"] is not None:
                pa_raw = s["per_app_list"]
                pa_txt = "\n".join(str(x) for x in pa_raw) if isinstance(pa_raw, list) else str(pa_raw)
                if pa_txt != self.per_app_list_edit.toPlainText():
                    self.per_app_list_edit.setPlainText(pa_txt)
                self._render_app_table()

            for combo, key in (
                (self.sub_hours_combo, "sub_auto_update_hours"),
                (self.engine_mode_combo, "engine_mode"),
                (self.manual_vec_combo, "manual_vector_id"),
                (self.frag_packets_combo, "fragment_packets"),
                (self.fp_combo, "fingerprint"),
                (self.alpn_combo, "alpn_override"),
                (self.ed_combo, "ws_early_data"),
            ):
                if key in s and s[key] is not None:
                    val = s[key]
                    if key in ("fingerprint", "manual_vector_id") and combo.findData(val) < 0:
                        combo.addItem(str(val), str(val))
                    idx = combo.findData(val)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)

            for edit, key in (
                (self.remote_dns_edit, "remote_dns"),
                (self.domestic_dns_edit, "domestic_dns"),
                (self.frag_len_edit, "fragment_length"),
                (self.frag_int_edit, "fragment_interval"),
            ):
                if key in s and s[key] is not None:
                    edit.setText(str(s[key]))

            for area, primary_key, legacy_key in (
                (self.direct_domains_edit, "custom_direct_domains", "direct_domains"),
                (self.proxy_domains_edit, "custom_proxy_domains", "proxy_domains"),
                (self.blocked_domains_edit, "custom_blocked_domains", "blocked_domains"),
            ):
                raw_dom = s.get(primary_key, s.get(legacy_key))
                if raw_dom is not None:
                    if isinstance(raw_dom, list):
                        self._domains_as_list = True
                        txt = "\n".join(str(x) for x in raw_dom if str(x).strip())
                    else:
                        txt = str(raw_dom)
                    area.setPlainText(txt)

            for spin, key in (
                (self.mux_conc_spin, "mux_concurrency"),
                (self.stride_spin, "forward_stride_bytes"),
                (self.jitter_spin, "stride_jitter_bytes"),
                (self.mtu_spin, "tun_mtu"),
                (self.socks_spin, "socks_port"),
                (self.http_spin, "http_port"),
                (self.bridge_spin, "bridge_port"),
            ):
                if key in s and s[key] is not None:
                    spin.setValue(get_int(s, key, spin.value()))
        finally:
            self._updating = False

    def _serialize_domain_field(self, area: QPlainTextEdit):
        raw = area.toPlainText().strip()
        if self._domains_as_list:
            return [ln.strip() for ln in raw.replace(",", "\n").splitlines() if ln.strip()]
        return raw

    def collect_settings(self) -> dict:
        return {
            "routing_mode": str(self.routing_mode_combo.currentData() or "bypass_ir"),
            "per_app_mode": str(self.per_app_mode_combo.currentData() or "off"),
            "per_app_list": self.per_app_list_edit.toPlainText().strip(),
            "block_quic": bool(self.sw_block_quic.isChecked()),
            "remote_dns": self.remote_dns_edit.text().strip() or "https://1.1.1.1/dns-query",
            "domestic_dns": self.domestic_dns_edit.text().strip() or "178.22.122.100",
            "custom_direct_domains": self._serialize_domain_field(self.direct_domains_edit),
            "custom_proxy_domains": self._serialize_domain_field(self.proxy_domains_edit),
            "custom_blocked_domains": self._serialize_domain_field(self.blocked_domains_edit),
            "minimize_to_tray": bool(self.sw_min_tray.isChecked()),
            "auto_pool_fallback": bool(self.sw_pool_fallback.isChecked()),
            "require_youtube_6s": bool(self.sw_yt_guard.isChecked()),
            "verify_upload_stream": bool(self.sw_upload_burst.isChecked()),
            "self_healing_watchdog": bool(self.sw_watchdog.isChecked()),
            "sub_auto_update_hours": int(self.sub_hours_combo.currentData() or 0),
            "engine_mode": str(self.engine_mode_combo.currentData() or "auto_hybrid"),
            "manual_vector_id": str(self.manual_vec_combo.currentData() or "AUTO"),
            "fragment_enabled": bool(self.sw_frag.isChecked()),
            "fragment_packets": str(self.frag_packets_combo.currentData() or "tlshello"),
            "fragment_length": self.frag_len_edit.text().strip() or "5-16",
            "fragment_interval": self.frag_int_edit.text().strip() or "2-3",
            "fingerprint": str(self.fp_combo.currentData() or "custom_poly"),
            "alpn_override": str(self.alpn_combo.currentData() or "auto"),
            "ws_early_data": int(self.ed_combo.currentData() or 0),
            "mux_enabled": bool(self.sw_mux.isChecked()),
            "mux_concurrency": int(self.mux_conc_spin.value()),
            "forward_stride_bytes": int(self.stride_spin.value()),
            "stride_jitter_bytes": int(self.jitter_spin.value()),
            "tun_mtu": int(self.mtu_spin.value()),
            "socks_port": int(self.socks_spin.value()),
            "http_port": int(self.http_spin.value()),
            "bridge_port": int(self.bridge_spin.value()),
        }

    def _emit_all(self, *_args) -> None:
        if not self._updating:
            self.settings_changed.emit(self.collect_settings())

    def retranslate_ui(self) -> None:
        self.title_lbl.setText(I18N.t("settings_title"))
        self.sub_lbl.setText(I18N.t("settings_subtitle"))
        self.sub_tabs.update_labels(
            [
                I18N.t("stab_routing"),
                I18N.t("stab_per_app"),
                I18N.t("stab_behavior"),
                I18N.t("stab_core"),
            ]
        )
        self.lbl_rmode.setText(I18N.t("routing_mode_lbl"))
        self.lbl_remote_dns.setText(I18N.t("remote_dns_lbl"))
        self.lbl_dom_dns.setText(I18N.t("domestic_dns_lbl"))
        self.lbl_direct_dom.setText(I18N.t("direct_domains_lbl"))
        self.lbl_proxy_dom.setText(I18N.t("proxy_domains_lbl"))
        self.lbl_block_dom.setText(I18N.t("blocked_domains_lbl"))
        self.lbl_pa_title.setText(I18N.t("per_app_launcher_title"))
        self.lbl_pa_desc.setText(I18N.t("per_app_launcher_desc"))
        self.lbl_pa_mode.setText(I18N.t("per_app_mode_lbl"))
        self.btn_refresh_apps.set_label_text(I18N.t("btn_refresh_apps"))
        self.btn_browse_exe.set_label_text(I18N.t("btn_browse_exe"))
        self.btn_launch_sel_app.set_label_text(I18N.t("btn_launch_custom"))
        self.lbl_pa_manual.setText(I18N.t("per_app_manual_lbl"))
        self.lbl_sub_hrs.setText(I18N.t("sub_autoupdate_lbl"))
        self.lbl_sw_frag.setText(I18N.t("sw_native_frag"))
        self.lbl_sw_mux.setText(I18N.t("sw_mux"))
        for t_l, t_k, d_l, d_k in self._switch_labels:
            t_l.setText(I18N.t(t_k))
            if d_l and d_k:
                d_l.setText(I18N.t(d_k))
        for lbl, k_str in self._core_field_labels:
            lbl.setText(I18N.t(k_str))
        self._populate_routing_combos()
        self._populate_per_app_combos()
        self._apply_per_app_headers()
        self._render_app_table()
        self._populate_behavior_combos()
        self._populate_core_combos()

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.sub_tabs.set_palette_theme(palette)
        for card in self._neu_cards:
            card.set_palette_theme(palette)
        for sw in self._switches:
            sw.set_palette_theme(palette)
        for b in (self.btn_refresh_apps, self.btn_browse_exe, self.btn_launch_sel_app):
            b.set_palette_theme(palette)
        self._render_app_table()


class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_lines: list[str] = []
        self._warn_only = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 14)
        root.setSpacing(10)

        self.top_card = NeuCard(mode="raised", radius=16.0, depth=4.5, pad=5.0)
        top = QHBoxLayout(self.top_card)
        top.setContentsMargins(16, 11, 16, 11)
        top.setSpacing(8)
        self.title_lbl = QLabel(I18N.t("logs_title"))
        self.title_lbl.setObjectName("PageTitle")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(I18N.t("logs_search_ph"))
        self.search_edit.setMaximumWidth(280)
        enforce_english_ltr(self.search_edit, mono_size=10)
        self.search_edit.textChanged.connect(lambda _t: self._refresh_view())

        self.filter_seg = SegmentedControl([I18N.t("logs_all"), I18N.t("logs_warn")])
        self.filter_seg.current_changed.connect(self._on_filter_mode)

        self.copy_btn = QPushButton(I18N.t("logs_copy"))
        self.copy_btn.setObjectName("GhostBtn")
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.console.toPlainText()))

        self.clear_btn = QPushButton(I18N.t("logs_clear"))
        self.clear_btn.setObjectName("DangerBtn")
        self.clear_btn.clicked.connect(self._clear)

        self.save_btn = QPushButton(I18N.t("logs_save"))
        self.save_btn.setObjectName("AccentBtn")
        self.save_btn.clicked.connect(self._export)

        top.addWidget(self.title_lbl)
        top.addStretch()
        top.addWidget(self.search_edit)
        top.addWidget(self.filter_seg)
        top.addWidget(self.copy_btn)
        top.addWidget(self.clear_btn)
        top.addWidget(self.save_btn)
        root.addWidget(self.top_card)

        self.console = QPlainTextEdit()
        self.console.setObjectName("LogConsole")
        self.console.setReadOnly(True)
        enforce_english_ltr(self.console, mono_size=10)
        root.addWidget(self.console, 1)

    def _on_filter_mode(self, idx: int) -> None:
        self._warn_only = (idx == 1)
        self._refresh_view()

    def _matches(self, line: str) -> bool:
        low = line.lower()
        if self._warn_only and not any(w in low for w in ("warn", "err", "fail", "timeout", "drop", "block")):
            return False
        q = self.search_edit.text().strip().lower()
        return (not q) or (q in low)

    def append_line(self, line: str) -> None:
        clean = strip_emojis(line)
        self._all_lines.append(clean)
        if len(self._all_lines) > 5000:
            self._all_lines = self._all_lines[-5000:]
        if self._matches(clean):
            self.console.appendPlainText(clean)
            sb = self.console.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _refresh_view(self) -> None:
        self.console.setUpdatesEnabled(False)
        try:
            filtered = [ln for ln in self._all_lines if self._matches(ln)]
            self.console.setPlainText("\n".join(filtered))
            sb = self.console.verticalScrollBar()
            sb.setValue(sb.maximum())
        finally:
            self.console.setUpdatesEnabled(True)

    def _clear(self) -> None:
        self._all_lines.clear()
        self.console.clear()

    def _export(self) -> None:
        fpath, _ = QFileDialog.getSaveFileName(self, "Export Logs", "alan-rip-dpi.log", "Log Files (*.log *.txt)")
        if fpath:
            Path(fpath).write_text(self.console.toPlainText(), encoding="utf-8")

    def retranslate_ui(self) -> None:
        self.title_lbl.setText(I18N.t("logs_title"))
        self.search_edit.setPlaceholderText(I18N.t("logs_search_ph"))
        self.filter_seg.update_labels([I18N.t("logs_all"), I18N.t("logs_warn")])
        self.copy_btn.setText(I18N.t("logs_copy"))
        self.clear_btn.setText(I18N.t("logs_clear"))
        self.save_btn.setText(I18N.t("logs_save"))

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self.top_card.set_palette_theme(palette)
        self.filter_seg.set_palette_theme(palette)