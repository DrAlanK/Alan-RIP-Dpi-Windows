import ctypes
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .animated_widgets import (
    NavRailButton,
    TaskProgressStrip,
    VectorIconButton,
    VectorIconPainter,
)
from .flag_icons import FlagBadgeWidget, GeoFlagResolver
from .pages import (
    AdminElevationDialog,
    ConfigEditorDialog,
    HomePage,
    LogsPage,
    ProfilesPage,
    ScannerPage,
    SettingsPage,
    format_rate_from_kbps,
    get_bool_value,
    parse_float_value,
    parse_int_value,
    pick_first_text,
    resolve_active_profile_index,
)
from .theme import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    ThemePalette,
    apply_windows_titlebar_theme,
    build_qpalette,
    build_stylesheet,
    enforce_english_ltr,
    load_application_fonts,
    lock_widget_dimensions,
    make_ui_font,
)

_IPV4_COUNTRY_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "2.144.",
            "2.176.",
            "5.52.",
            "5.112.",
            "5.160.",
            "5.200.",
            "31.56.",
            "37.98.",
            "46.100.",
            "78.38.",
            "80.191.",
            "85.15.",
            "91.98.",
            "91.99.",
            "151.232.",
            "178.131.",
            "185.143.",
            "188.158.",
            "192.15.",
        ),
        "IR",
    ),
    (
        (
            "5.161.",
            "49.12.",
            "49.13.",
            "78.46.",
            "78.47.",
            "88.99.",
            "88.198.",
            "116.202.",
            "116.203.",
            "128.140.",
            "138.201.",
            "142.132.",
            "148.251.",
            "159.69.",
            "162.55.",
            "167.235.",
            "168.119.",
            "176.9.",
            "178.63.",
            "188.40.",
            "195.201.",
            "213.133.",
        ),
        "DE",
    ),
    (("65.21.", "65.108.", "65.109.", "95.216.", "95.217.", "135.181."), "FI"),
    (("45.89.", "89.40.", "146.70.", "185.209.", "185.107."), "NL"),
    (("45.33.", "64.225.", "137.184.", "143.198.", "198.51."), "US"),
    (("51.140.", "51.145.", "109.74.", "212.71."), "GB"),
    (("51.38.", "51.68.", "51.75.", "51.91.", "163.172."), "FR"),
)


def infer_country_from_ipv4(ip_text: str) -> str:
    if not ip_text:
        return ""
    m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(ip_text))
    if not m:
        return ""
    ip = m.group(0)
    for prefixes, code in _IPV4_COUNTRY_PREFIXES:
        if ip.startswith(prefixes):
            return code
    return ""


def format_uptime_hms(seconds: int) -> str:
    sec = max(0, int(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_brand_window_icon(logo_path: str = "assets/logo.png") -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    VectorIconPainter.draw_brand_logo(painter, QRectF(4.0, 4.0, 56.0, 56.0), logo_path)
    painter.end()
    return QIcon(pix)


def coerce_dict(obj) -> dict:
    if isinstance(obj, dict):
        return dict(obj)
    if obj is None:
        return {}
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


class BackendControllerAdapter(QObject):
    telemetry_updated = Signal(dict)
    log_message = Signal(str)
    profiles_updated = Signal(list)
    settings_updated = Signal(dict)
    scan_row_emitted = Signal(dict)
    scan_results_ranked = Signal(list)
    scan_progress = Signal(int, str)
    scan_state_changed = Signal(bool, str)
    subscriptions_updated = Signal(list)
    task_progress = Signal(bool, int, str)
    tun_status_changed = Signal(bool, str)


class DemoDpiController(BackendControllerAdapter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = {
            "system_proxy": True,
            "autopilot": True,
            "tun_enabled": False,
            "auto_clean_ip": True,
            "require_youtube_6s": True,
            "verify_upload_stream": True,
            "self_healing_watchdog": True,
            "engine_mode": "auto_hybrid",
            "fragment_enabled": True,
            "fragment_packets": "tlshello",
            "fragment_length": "5-16",
            "fragment_interval": "2-3",
            "fingerprint": "chrome",
            "alpn_override": "auto",
            "ws_early_data": 2048,
            "mux_enabled": False,
            "mux_concurrency": 8,
            "manual_vector_id": "VEC-01",
            "forward_stride_bytes": 400,
            "stride_jitter_bytes": 32,
            "socks_port": 10808,
            "http_port": 10809,
        }
        self._vectors = [
            {"id": f"VEC-{i:02d}", "name": f"Adaptive Profile {i:02d}"}
            for i in range(1, 17)
        ]
        self._selected_index = 1
        self._profiles = [
            {
                "uid": "prof-de-01",
                "name": "DE Direct-German",
                "country_code": "DE",
                "protocol": "vless",
                "host": "49.12.104.21",
                "original_host": "de-edge.alan-cdn.net",
                "address": "49.12.104.21",
                "port": 443,
                "uuid_or_password": "11111111-2222-3333-4444-555555555555",
                "network": "ws",
                "security": "tls",
                "sni": "de-edge.alan-cdn.net",
                "host_header": "de-edge.alan-cdn.net",
                "path": "/ws",
                "alpn": "http/1.1",
                "fingerprint": "chrome",
                "flow": "",
                "public_key": "",
                "short_id": "",
                "status": "VERIFIED",
                "ping_ms": 42,
                "preferred_vector_id": "VEC-01",
                "cached_vector_id": "VEC-01",
                "is_selected": False,
                "uri": "vless://11111111-2222-3333-4444-555555555555@49.12.104.21:443?security=tls&type=ws&sni=de-edge.alan-cdn.net#DE%20Direct-German",
            },
            {
                "uid": "prof-nl-02",
                "name": "NL Amsterdam-Clean",
                "country_code": "NL",
                "protocol": "vless",
                "host": "185.209.22.14",
                "original_host": "nl-stream.alan-cdn.net",
                "address": "185.209.22.14",
                "port": 443,
                "uuid_or_password": "22222222-3333-4444-5555-666666666666",
                "network": "ws",
                "security": "tls",
                "sni": "nl-stream.alan-cdn.net",
                "host_header": "nl-stream.alan-cdn.net",
                "path": "/ed2048",
                "alpn": "http/1.1",
                "fingerprint": "chrome",
                "flow": "",
                "public_key": "",
                "short_id": "",
                "status": "VERIFIED",
                "ping_ms": 47,
                "preferred_vector_id": "VEC-02",
                "cached_vector_id": "VEC-02",
                "is_selected": True,
                "uri": "vless://22222222-3333-4444-5555-666666666666@185.209.22.14:443?security=tls&type=ws&sni=nl-stream.alan-cdn.net#NL%20Amsterdam-Clean",
            },
            {
                "uid": "prof-fi-03",
                "name": "FI Helsinki-Nordic",
                "country_code": "FI",
                "protocol": "trojan",
                "host": "65.109.88.19",
                "original_host": "fi-core.alan-cdn.net",
                "address": "65.109.88.19",
                "port": 443,
                "uuid_or_password": "secret-trojan-pass",
                "network": "grpc",
                "security": "tls",
                "sni": "fi-core.alan-cdn.net",
                "host_header": "",
                "path": "grpc-stream",
                "alpn": "h2",
                "fingerprint": "chrome",
                "flow": "",
                "public_key": "",
                "short_id": "",
                "status": "UNTESTED",
                "ping_ms": 0,
                "preferred_vector_id": "AUTO",
                "cached_vector_id": "",
                "is_selected": False,
                "uri": "trojan://secret-trojan-pass@65.109.88.19:443?security=tls&type=grpc#FI%20Helsinki-Nordic",
            },
            {
                "uid": "prof-ir-04",
                "name": "IR Tehran-Relay",
                "country_code": "IR",
                "protocol": "vless",
                "host": "185.143.233.12",
                "original_host": "relay.alan-edge.ir",
                "address": "185.143.233.12",
                "port": 443,
                "uuid_or_password": "33333333-4444-5555-6666-777777777777",
                "network": "tcp",
                "security": "tls",
                "sni": "relay.alan-edge.ir",
                "host_header": "",
                "path": "/",
                "alpn": "h2,http/1.1",
                "fingerprint": "chrome",
                "flow": "",
                "public_key": "",
                "short_id": "",
                "status": "VERIFIED",
                "ping_ms": 19,
                "preferred_vector_id": "VEC-01",
                "cached_vector_id": "VEC-01",
                "is_selected": False,
                "uri": "vless://33333333-4444-5555-6666-777777777777@185.143.233.12:443?security=tls&type=tcp&sni=relay.alan-edge.ir#IR%20Tehran-Relay",
            },
        ]
        self._subscriptions = [
            {"title": "Alan Primary Pool", "url": "https://sub.alan-network.example/api/v1/pull"}
        ]
        self._phase = "IDLE"
        self._connected_since: float | None = None
        self._connect_step = 0
        self._scan_mode = ""
        self._scan_step = 0
        self._scan_target = -1
        self._scan_options: dict = {}
        self._scan_collected: list[dict] = []
        self._hunt_step = 0

        self._connect_timer = QTimer(self)
        self._connect_timer.setInterval(680)
        self._connect_timer.timeout.connect(self._step_connect)

        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(1000)
        self._metrics_timer.timeout.connect(self._step_metrics)
        self._metrics_timer.start()

        self._scanner_timer = QTimer(self)
        self._scanner_timer.setInterval(360)
        self._scanner_timer.timeout.connect(self._step_scanner)

        self._hunt_timer = QTimer(self)
        self._hunt_timer.setInterval(420)
        self._hunt_timer.timeout.connect(self._step_hunt)

    def get_selected_index(self) -> int:
        if (self._selected_index >= 0) and (self._selected_index < len(self._profiles)):
            return self._selected_index
        return -1

    def _active_profile_dict(self) -> dict:
        idx = self.get_selected_index()
        if idx >= 0:
            return self._profiles[idx]
        return self._profiles[0] if bool(self._profiles) else {}

    def is_admin(self) -> bool:
        if sys.platform == "win32":
            try:
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False
        return True

    def request_admin_elevation(self):
        self._emit_log("Requested Windows UAC Administrator elevation restart...")

    def set_tun_mode(self, enabled: bool):
        if bool(enabled) and (not self.is_admin()):
            self.tun_status_changed.emit(False, "نیاز به دسترسی Administrator")
            return
        self._settings["tun_enabled"] = bool(enabled)
        detail = "رابط شبکه مجازی کل سیستم فعال است" if enabled else "رابط شبکه مجازی غیرفعال است"
        self.tun_status_changed.emit(bool(enabled), detail)
        self.settings_updated.emit(dict(self._settings))
        self._emit_log(f"System-wide TUN mode set to {enabled}.")

    def set_auto_clean_ip(self, checked: bool):
        self.update_settings({"auto_clean_ip": bool(checked)})

    def set_require_youtube_6s(self, checked: bool):
        self.update_settings({"require_youtube_6s": bool(checked)})

    def set_verify_upload_stream(self, checked: bool):
        self.update_settings({"verify_upload_stream": bool(checked)})

    def set_self_healing_watchdog(self, checked: bool):
        self.update_settings({"self_healing_watchdog": bool(checked)})

    def get_settings(self) -> dict:
        return dict(self._settings)

    def get_profiles(self) -> list:
        out = []
        for idx, p in enumerate(self._profiles):
            item = dict(p)
            item["is_selected"] = (idx == self._selected_index)
            out.append(item)
        return out

    def get_vectors(self) -> list:
        return [dict(v) for v in self._vectors]

    def get_subscriptions(self) -> list:
        return [dict(s) for s in self._subscriptions]

    def toggle_connection(self):
        if self._phase in ("CONNECTING", "CONNECTED"):
            self.request_disconnect()
        else:
            self.request_connect()

    def request_connect(self, uri: str = ""):
        self._phase = "CONNECTING"
        self._connected_since = None
        self._connect_step = 0
        target_label = uri[:36] if bool(uri) else "active-profile"
        self._emit_log(f"v3.1.0 AutoPilot probing started ({target_label})...")
        self._step_connect()
        self._connect_timer.start()

    def request_disconnect(self):
        was_probing = (self._phase == "CONNECTING")
        self._connect_timer.stop()
        self._hunt_timer.stop()
        self._phase = "IDLE"
        self._connected_since = None
        self.task_progress.emit(False, 0, "")
        msg = "فرایند اتصال فوراً لغو شد." if was_probing else "اتصال امن قطع شد و مسیر شبکه بازگردانی گردید."
        self._emit_log("Connection/probing aborted cleanly." if was_probing else "Active tunnel disconnected.")
        active_prof = self._active_profile_dict()
        self.telemetry_updated.emit(
            {
                "ui_phase": "IDLE",
                "state": "disconnected",
                "is_connecting": False,
                "is_connected": False,
                "selected_index": self.get_selected_index(),
                "active_profile_uid": pick_first_text(active_prof, ("uid",), ""),
                "button_text": "اتصال هوشمند",
                "uptime_label": "00:00:00",
                "status_headline": "آماده اتصال",
                "status_detail": msg,
                "egress_ip": "—",
                "active_vector_id": "AUTO",
                "ping_ms": 0,
                "tx_rate_kbps": 0.0,
                "rx_rate_kbps": 0.0,
                "tx_rate_label": "0 B/s",
                "rx_rate_label": "0 B/s",
                "progress_percent": 0,
            }
        )

    def hunt_best_and_connect(self):
        if not self._profiles:
            self._emit_log("Repository is empty; cannot start Hunt Best.")
            return
        self._scanner_timer.stop()
        self._hunt_step = 0
        self._emit_log("Hunt Best & Connect started across entire repository...")
        self.task_progress.emit(True, 8, "شکارچی هوشمند: پالایش کانفیگ‌های مخزن و کشف تمیزترین مسیر...")
        self._hunt_timer.start()

    def _step_hunt(self):
        self._hunt_step += 1
        stages = [
            (34, "شکارچی هوشمند: تست موازی پینگ و سلامت کانفیگ‌های مخزن..."),
            (68, "شکارچی هوشمند: ارزیابی متدهای عبوری و جایگزینی IP تمیز..."),
            (94, "شکارچی هوشمند: برترین کانفیگ انتخاب شد؛ برقراری تونل امن..."),
        ]
        if self._hunt_step <= len(stages):
            pct, msg = stages[self._hunt_step - 1]
            self.task_progress.emit(True, pct, msg)
            return

        self._hunt_timer.stop()
        self._selected_index = 0
        for idx, p in enumerate(self._profiles):
            p["is_selected"] = (idx == 0)
            if idx == 0:
                p["status"] = "VERIFIED"
                p["ping_ms"] = 37
                p["preferred_vector_id"] = "VEC-01"
                p["cached_vector_id"] = "VEC-01"
        self.profiles_updated.emit(self.get_profiles())
        self.task_progress.emit(False, 100, "شکار بهترین کانفیگ تکمیل شد.")
        self.request_connect(pick_first_text(self._profiles[0], ("uri",), ""))

    def update_settings(self, settings_dict: dict):
        if not isinstance(settings_dict, dict):
            return
        self._settings.update(settings_dict)
        self.settings_updated.emit(dict(self._settings))
        self._emit_log(f"Engine configuration updated ({len(settings_dict)} keys).")

    def select_config(self, index: int):
        if (index >= 0) and (index < len(self._profiles)):
            self._selected_index = index
            for i, p in enumerate(self._profiles):
                p["is_selected"] = (i == index)
            self.profiles_updated.emit(self.get_profiles())
            self._emit_log(f"Active profile set to #{index + 1}: {self._profiles[index]['name']}")

    def get_config_editable(self, index: int) -> dict:
        if (index >= 0) and (index < len(self._profiles)):
            p = dict(self._profiles[index])
            p.setdefault("raw_uri", pick_first_text(p, ("uri",), ""))
            p.setdefault("use_raw_uri", False)
            return p
        return {
            "name": f"DE Custom Node #{len(self._profiles) + 1}",
            "protocol": "vless",
            "host": "49.12.104.21",
            "original_host": "49.12.104.21",
            "address": "49.12.104.21",
            "port": 443,
            "uuid_or_password": "",
            "network": "ws",
            "security": "tls",
            "sni": "",
            "host_header": "",
            "path": "/",
            "alpn": "http/1.1",
            "fingerprint": "chrome",
            "flow": "",
            "public_key": "",
            "short_id": "",
            "preferred_vector_id": "AUTO",
            "raw_uri": "",
            "use_raw_uri": False,
        }

    def save_config_editable(self, index: int, form_dict: dict):
        entry = dict(form_dict)
        use_raw = get_bool_value(entry, "use_raw_uri", False)
        raw_uri = pick_first_text(entry, ("raw_uri",), "")
        if (not use_raw) or (not raw_uri):
            proto = pick_first_text(entry, ("protocol",), "vless")
            cred = pick_first_text(entry, ("uuid_or_password",), "00000000-0000-0000-0000-000000000000")
            addr = pick_first_text(entry, ("host", "address"), "127.0.0.1")
            port = parse_int_value(entry.get("port", 443), 443)
            net = pick_first_text(entry, ("network",), "ws")
            sec = pick_first_text(entry, ("security",), "tls")
            sni = pick_first_text(entry, ("sni",), "")
            name = pick_first_text(entry, ("name",), "Alan-Profile")
            entry["host"] = addr
            entry.setdefault("original_host", addr)
            entry["address"] = addr
            entry["uri"] = f"{proto}://{cred}@{addr}:{port}?security={sec}&type={net}&sni={sni}#{name}"
            entry["raw_uri"] = entry["uri"]
        else:
            entry["uri"] = raw_uri

        entry["country_code"] = GeoFlagResolver.resolve_code(entry)
        pref = pick_first_text(entry, ("preferred_vector_id",), "AUTO")
        entry["cached_vector_id"] = "" if (pref == "AUTO") else pref
        entry.setdefault("status", "UNTESTED")
        entry.setdefault("ping_ms", 0)
        entry.setdefault("uid", f"prof-{int(time.time() * 1000)}-{len(self._profiles)}")

        if (index >= 0) and (index < len(self._profiles)):
            entry["is_selected"] = (index == self._selected_index)
            self._profiles[index] = entry
            self._emit_log(f"Updated profile #{index + 1}: {entry.get('name')}")
        else:
            if self._selected_index < 0:
                self._selected_index = len(self._profiles)
            entry["is_selected"] = (len(self._profiles) == self._selected_index)
            self._profiles.append(entry)
            self._emit_log(f"Created new profile: {entry.get('name')}")

        self.profiles_updated.emit(self.get_profiles())

    def clear_all_configs(self):
        if self._phase in ("CONNECTING", "CONNECTED"):
            self.request_disconnect()
        self._profiles.clear()
        self._selected_index = -1
        self.profiles_updated.emit([])
        self._emit_log("All profiles cleared from repository.")

    def import_configs(self, raw_text: str):
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        for idx, ln in enumerate(lines):
            proto = ln.split("://")[0].lower() if ("://" in ln) else "vless"
            name = ln.split("#")[-1] if ("#" in ln) else f"DE Node #{len(self._profiles) + 1}"
            host_parsed = "49.12.104.91"
            m_host = re.search(r"@([^:/?#]+)", ln)
            if m_host:
                host_parsed = m_host.group(1)
            if self._selected_index < 0:
                self._selected_index = len(self._profiles)
            item = {
                "uid": f"prof-imp-{int(time.time() * 1000)}-{idx}",
                "name": name[:36],
                "protocol": proto,
                "host": host_parsed,
                "original_host": host_parsed,
                "address": host_parsed,
                "port": 443,
                "sni": "cdn.clean-edge.org",
                "status": "UNTESTED",
                "ping_ms": 0,
                "preferred_vector_id": "AUTO",
                "cached_vector_id": "",
                "is_selected": (len(self._profiles) == self._selected_index),
                "uri": ln,
            }
            item["country_code"] = GeoFlagResolver.resolve_code(item)
            self._profiles.append(item)
        self.profiles_updated.emit(self.get_profiles())
        self._emit_log(f"Imported {len(lines)} profile(s).")

    def import_configs_from_file(self, file_path: str):
        p = Path(file_path)
        if p.is_file():
            self.import_configs(p.read_text(encoding="utf-8", errors="ignore"))

    def quick_ping_configs(self):
        total = len(self._profiles)
        if total == 0:
            return
        self.task_progress.emit(True, 25, "در حال پینگ سریع تمام کانفیگ‌های مخزن...")
        for idx, p in enumerate(self._profiles):
            alive = random.random() > 0.15
            p["status"] = "VERIFIED" if alive else "DEAD"
            p["ping_ms"] = random.randint(24, 98) if alive else 0
            pct = int(((idx + 1) / total) * 100)
            self.task_progress.emit(True, pct, f"پینگ سریع کانفیگ ({idx + 1}/{total})...")
        self.profiles_updated.emit(self.get_profiles())
        self.task_progress.emit(False, 100, "پینگ سریع همه کانفیگ‌ها به پایان رسید.")
        self._emit_log("Quick repository ping completed.")

    def sort_configs(self, by: str):
        active_uid = ""
        if (self._selected_index >= 0) and (self._selected_index < len(self._profiles)):
            active_uid = pick_first_text(self._profiles[self._selected_index], ("uid",), "")

        if by == "ping":
            self._profiles.sort(
                key=lambda x: parse_int_value(x.get("ping_ms", 0), 0)
                if (parse_int_value(x.get("ping_ms", 0), 0) > 0)
                else 99999
            )
        elif by == "protocol":
            self._profiles.sort(key=lambda x: str(x.get("protocol", "")))
        else:
            self._profiles.sort(key=lambda x: str(x.get("name", "")))

        if active_uid:
            for idx, p in enumerate(self._profiles):
                is_sel = (pick_first_text(p, ("uid",), "") == active_uid)
                p["is_selected"] = is_sel
                if is_sel:
                    self._selected_index = idx
        self.profiles_updated.emit(self.get_profiles())

    def deduplicate_configs(self):
        active_uid = ""
        if (self._selected_index >= 0) and (self._selected_index < len(self._profiles)):
            active_uid = pick_first_text(self._profiles[self._selected_index], ("uid",), "")
        seen = set()
        unique = []
        for p in self._profiles:
            u = pick_first_text(p, ("uri", "name"), "")
            if u not in seen:
                seen.add(u)
                unique.append(p)
        self._profiles = unique
        self._sync_selected_after_mutation(active_uid)
        self.profiles_updated.emit(self.get_profiles())

    def remove_dead_configs(self):
        active_uid = ""
        if (self._selected_index >= 0) and (self._selected_index < len(self._profiles)):
            active_uid = pick_first_text(self._profiles[self._selected_index], ("uid",), "")
        self._profiles = [p for p in self._profiles if str(p.get("status", "")).upper() != "DEAD"]
        self._sync_selected_after_mutation(active_uid)
        self.profiles_updated.emit(self.get_profiles())

    def _sync_selected_after_mutation(self, active_uid: str):
        if not self._profiles:
            self._selected_index = -1
            return
        found = -1
        if active_uid:
            for idx, p in enumerate(self._profiles):
                if pick_first_text(p, ("uid",), "") == active_uid:
                    found = idx
                    break
        if found < 0:
            found = min(max(0, self._selected_index), len(self._profiles) - 1)
        self._selected_index = found
        for idx, p in enumerate(self._profiles):
            p["is_selected"] = (idx == found)

    def rename_config(self, index: int, new_name: str):
        if (index >= 0) and (index < len(self._profiles)):
            self._profiles[index]["name"] = new_name
            self._profiles[index]["country_code"] = GeoFlagResolver.resolve_code(self._profiles[index])
            self.profiles_updated.emit(self.get_profiles())

    def delete_config(self, index: int):
        if (index >= 0) and (index < len(self._profiles)):
            active_uid = ""
            if (self._selected_index >= 0) and (self._selected_index < len(self._profiles)):
                active_uid = pick_first_text(self._profiles[self._selected_index], ("uid",), "")
            self._profiles.pop(index)
            self._sync_selected_after_mutation(active_uid)
            self.profiles_updated.emit(self.get_profiles())

    def clone_config_with_clean_ips(self, index: int, count: int = 3):
        if (index >= 0) and (index < len(self._profiles)):
            src = self._profiles[index]
            clean_pool = ["104.18.21.44", "172.67.19.102", "104.16.88.15", "162.159.135.42"]
            orig_h = pick_first_text(src, ("original_host", "host", "address"), "")
            for i in range(count):
                ip = clean_pool[i % len(clean_pool)]
                clone = dict(src)
                clone["uid"] = f"prof-clone-{int(time.time() * 1000)}-{i}"
                clone["name"] = f"{src['name']} [Clean-{i + 1}]"
                clone["host"] = ip
                clone["original_host"] = orig_h
                clone["address"] = ip
                clone["status"] = "VERIFIED"
                clone["ping_ms"] = 38 + i * 5
                clone["is_selected"] = False
                self._profiles.append(clone)
            self.profiles_updated.emit(self.get_profiles())

    def export_configs(self, mode: str = "verified", inject_early_data: int = 2048) -> str:
        out = []
        for p in self._profiles:
            if (mode == "verified") and (str(p.get("status", "")).upper() != "VERIFIED"):
                continue
            uri = pick_first_text(p, ("uri",), "")
            if (inject_early_data > 0) and ("ed=" not in uri) and ("?" in uri):
                uri = uri.replace("?", f"?ed={inject_early_data}&", 1)
            out.append(uri)
        return "\n".join(out)

    def add_subscription(self, url: str, title: str):
        self._subscriptions.append({"title": title, "url": url})
        self.subscriptions_updated.emit(self.get_subscriptions())

    def refresh_subscriptions(self):
        self.task_progress.emit(True, 45, "در حال دریافت و به‌روزرسانی لینک‌های سابسکریپشن...")
        self._emit_log("Refreshing subscriptions...")
        self.subscriptions_updated.emit(self.get_subscriptions())
        QTimer.singleShot(500, lambda: self.task_progress.emit(False, 100, "به‌روزرسانی سابسکریپشن تکمیل شد."))

    def delete_subscription(self, idx: int):
        if (idx >= 0) and (idx < len(self._subscriptions)):
            self._subscriptions.pop(idx)
            self.subscriptions_updated.emit(self.get_subscriptions())

    def start_scanner(self, mode: str, target_index: int = -1, options: dict | None = None):
        self._scan_mode = mode
        self._scan_target = target_index
        self._scan_options = dict(options) if isinstance(options, dict) else {}
        self._scan_step = 0
        self._scan_collected.clear()
        self.scan_state_changed.emit(True, f"اسکن «{mode}» آغاز شد...")
        self.scan_progress.emit(4, "آماده‌سازی موتور کاوش و ارزیابی...")
        self.task_progress.emit(True, 4, "در حال اجرای اسکن هوشمند...")
        self._scanner_timer.start()

    def stop_scanner(self):
        self._scanner_timer.stop()
        self._hunt_timer.stop()
        self.scan_state_changed.emit(False, "عملیات اسکن متوقف شد.")
        self.task_progress.emit(False, 0, "عملیات متوقف شد.")

    def apply_scanned_ip(self, ip: str, only_active: bool = True):
        clean_ip = ip.split(":")[0] if (":" in ip) else ip
        if only_active:
            idx = self.get_selected_index()
            if idx >= 0:
                self._profiles[idx]["host"] = clean_ip
                self._profiles[idx]["address"] = clean_ip
                self._profiles[idx]["status"] = "VERIFIED"
        else:
            for p in self._profiles:
                p["host"] = clean_ip
                p["address"] = clean_ip
        self.profiles_updated.emit(self.get_profiles())
        self._emit_log(f"Patched clean IP {clean_ip} (only_active={only_active}).")

    def apply_scanned_vector(
        self, vector_id: str, target_index: int = -1, endpoint: str = "", auto_connect: bool = False
    ):
        idx = target_index if ((target_index >= 0) and (target_index < len(self._profiles))) else self.get_selected_index()
        if (idx >= 0) and (idx < len(self._profiles)):
            self._profiles[idx]["preferred_vector_id"] = vector_id
            self._profiles[idx]["cached_vector_id"] = vector_id
            self._profiles[idx]["status"] = "VERIFIED"
            if endpoint and (":" in endpoint):
                clean_h = endpoint.split(":")[0]
                self._profiles[idx]["host"] = clean_h
                self._profiles[idx]["address"] = clean_h
            if auto_connect:
                self._selected_index = idx
                for i, p in enumerate(self._profiles):
                    p["is_selected"] = (i == idx)
            self.profiles_updated.emit(self.get_profiles())
            self._emit_log(f"Applied vector {vector_id} to profile #{idx + 1} (auto_connect={auto_connect}).")
            if auto_connect:
                self.request_connect(pick_first_text(self._profiles[idx], ("uri",), ""))

    def apply_vector_to_all_configs(self, vector_id: str, endpoint: str = ""):
        clean_host = endpoint.split(":")[0] if (bool(endpoint) and (":" in endpoint)) else ""
        for p in self._profiles:
            p["preferred_vector_id"] = vector_id
            p["cached_vector_id"] = vector_id
            if clean_host:
                p["host"] = clean_host
                p["address"] = clean_host
        self.profiles_updated.emit(self.get_profiles())
        self._emit_log(f"Applied vector {vector_id} across all {len(self._profiles)} repository profiles.")

    def connect_scanned_profile(self, target_index: int, bound_vector: str = "", endpoint: str = ""):
        if (target_index >= 0) and (target_index < len(self._profiles)):
            self._selected_index = target_index
            for i, p in enumerate(self._profiles):
                p["is_selected"] = (i == target_index)
            if bound_vector:
                self._profiles[target_index]["preferred_vector_id"] = bound_vector
                self._profiles[target_index]["cached_vector_id"] = bound_vector
            if endpoint and (":" in endpoint):
                clean_h = endpoint.split(":")[0]
                self._profiles[target_index]["host"] = clean_h
                self._profiles[target_index]["address"] = clean_h
            self.profiles_updated.emit(self.get_profiles())
            self._emit_log(f"Connecting immediately to scanned profile #{target_index + 1}...")
            self.request_connect(pick_first_text(self._profiles[target_index], ("uri",), ""))

    def _step_scanner(self):
        self._scan_step += 1
        total = 6 if (self._scan_mode != "full_repository") else max(1, len(self._profiles))
        pct = min(100, int((self._scan_step / total) * 100))

        if self._scan_mode == "active_profile":
            target_prof = (
                self._profiles[self._scan_target]
                if ((self._scan_target >= 0) and (self._scan_target < len(self._profiles)))
                else self._active_profile_dict()
            )
            vid = f"VEC-{self._scan_step:02d}"
            tls = random.randint(39, 108)
            st = random.choice(["VERIFIED", "VERIFIED", "PARTIAL_OK", "FAILED"])
            sc = round(max(10.0, 99.0 - tls * 0.32), 1) if (st != "FAILED") else 0.0
            msg = f"ارزیابی متد {vid} ({self._scan_step}/{total})..."
            host_str = pick_first_text(target_prof, ("host", "original_host", "address"), "49.12.104.21")
            row = {
                "scan_type": "vector",
                "item_id": vid,
                "target_index": max(0, self._scan_target),
                "country_code": GeoFlagResolver.resolve_code(target_prof),
                "title": f"آزمون متد عبوری {vid}",
                "category": vid,
                "endpoint": f"{host_str}:443",
                "tcp_ms": 34,
                "tunnel_ms": tls if (st != "FAILED") else 0,
                "status": st,
                "score": sc,
                "detail": "پایداری استریم تایید شد"
                if (st == "VERIFIED")
                else ("عبور نیمه‌پایدار" if (st == "PARTIAL_OK") else "عدم پاسخ هندشیک"),
            }
            self._scan_collected.append(row)
            self.scan_row_emitted.emit(row)
            self.scan_progress.emit(pct, msg)
            self.task_progress.emit(True, pct, msg)
            if (st == "VERIFIED") and get_bool_value(self._scan_options, "auto_connect", False):
                self._scanner_timer.stop()
                self.task_progress.emit(False, 100, "")
                self.apply_scanned_vector(vid, self._scan_target, row["endpoint"], True)
                self.scan_state_changed.emit(False, f"اتصال خودکار با اولین متد موفق ({vid}) انجام شد.")
                return
        elif self._scan_mode == "full_repository":
            idx = self._scan_step - 1
            msg = f"پایش دسته‌جمعی مخزن ({self._scan_step}/{total})..."
            if (idx >= 0) and (idx < len(self._profiles)):
                prof = self._profiles[idx]
                ok = (idx != 2)
                tls = random.randint(22, 86) if ok else 0
                st = "VERIFIED" if ok else "DEAD"
                prof["status"] = st
                prof["ping_ms"] = tls
                host_str = pick_first_text(prof, ("host", "original_host", "address"), "49.12.104.21")
                port_num = parse_int_value(prof.get("port", 443), 443)
                row = {
                    "scan_type": "repository",
                    "item_id": f"profile-{idx}",
                    "target_index": idx,
                    "country_code": GeoFlagResolver.resolve_code(prof),
                    "bound_vector": "VEC-01" if ok else "",
                    "title": pick_first_text(prof, ("name",), f"Profile #{idx + 1}"),
                    "category": pick_first_text(prof, ("protocol",), "vless").upper(),
                    "endpoint": f"{host_str}:{port_num}",
                    "tcp_ms": 32 if ok else 0,
                    "tunnel_ms": tls,
                    "status": st,
                    "score": round(100 - tls * 0.35, 1) if ok else 0.0,
                    "detail": "مسیر سالم و آماده اتصال فوری" if ok else "عدم برقراری تونل TLS",
                }
                self._scan_collected.append(row)
                self.scan_row_emitted.emit(row)
                self.scan_progress.emit(pct, msg)
                self.task_progress.emit(True, pct, msg)
        else:
            ip = f"104.18.{20 + self._scan_step}.{12 + self._scan_step * 15}"
            tcp = random.randint(28, 56)
            tls = tcp + random.randint(14, 32)
            msg = f"رادار رنج‌های IP تمیز ({self._scan_step}/{total})..."
            row = {
                "scan_type": "clean_ip",
                "item_id": ip,
                "country_code": "GLOBAL",
                "title": f"Clean Edge {ip}",
                "category": "CF-RANGE",
                "endpoint": f"{ip}:443",
                "tcp_ms": tcp,
                "tunnel_ms": tls,
                "status": "VERIFIED",
                "score": round(100 - tls * 0.35, 1),
                "detail": f"Jitter {random.randint(2, 8)}ms | Loss 0%",
            }
            self._scan_collected.append(row)
            self.scan_row_emitted.emit(row)
            self.scan_progress.emit(pct, msg)
            self.task_progress.emit(True, pct, msg)

        if self._scan_step >= total:
            self._scanner_timer.stop()
            ranked = sorted(
                self._scan_collected,
                key=lambda x: (
                    -parse_float_value(x.get("score", 0.0), 0.0),
                    parse_int_value(x.get("tunnel_ms", 99999), 99999)
                    if (parse_int_value(x.get("tunnel_ms", 0), 0) > 0)
                    else 99999,
                ),
            )
            for pos, item in enumerate(ranked):
                item["rank"] = f"#{pos + 1}"
            self.scan_results_ranked.emit(ranked)
            self.profiles_updated.emit(self.get_profiles())
            self.scan_state_changed.emit(False, "اسکن کامل شد و نتایج بر اساس امتیاز رتبه‌بندی شدند.")
            self.task_progress.emit(False, 100, "اسکن به پایان رسید.")

    def _step_connect(self):
        active_prof = self._active_profile_dict()
        cc = GeoFlagResolver.resolve_code(active_prof)
        stages = [
            (32, "کاوش موازی رنج‌های IP تمیز (RTT < 60ms)..."),
            (68, "اعمال فرگمنت تطبیقی و بهینه‌سازی هندشیک TLS..."),
            (92, "تایید بقای ۶ ثانیه‌ای یوتیوب و تست سلامت آپلود..."),
        ]
        if self._connect_step < len(stages):
            pct, detail = stages[self._connect_step]
            self.telemetry_updated.emit(
                {
                    "ui_phase": "CONNECTING",
                    "state": "connecting",
                    "is_connecting": True,
                    "is_connected": False,
                    "selected_index": self.get_selected_index(),
                    "active_profile_uid": pick_first_text(active_prof, ("uid",), ""),
                    "country_code": cc,
                    "button_text": "لغو فرایند (کلیک برای توقف)",
                    "uptime_label": "00:00:00",
                    "status_headline": "در حال یافتن بهترین مسیر...",
                    "status_detail": detail,
                    "egress_ip": "—",
                    "active_vector_id": "PROBING",
                    "ping_ms": 0,
                    "tx_rate_kbps": 0.0,
                    "rx_rate_kbps": 0.0,
                    "tx_rate_label": "0 B/s",
                    "rx_rate_label": "0 B/s",
                    "progress_percent": pct,
                }
            )
            self._connect_step += 1
        else:
            self._connect_timer.stop()
            self._phase = "CONNECTED"
            self._connected_since = time.monotonic()
            vec = (
                "AUTO-HYBRID"
                if get_bool_value(self._settings, "autopilot", True)
                else pick_first_text(self._settings, ("manual_vector_id",), "VEC-01")
            )
            egress = pick_first_text(active_prof, ("host", "original_host", "address"), "49.12.104.21")
            self._emit_log(f"Tunnel ONLINE via {egress} ({cc}) | Profile: {vec}")
            self._step_metrics()

    def _step_metrics(self):
        if self._phase != "CONNECTED":
            return
        active_prof = self._active_profile_dict()
        cc = GeoFlagResolver.resolve_code(active_prof)
        egress = pick_first_text(active_prof, ("host", "original_host", "address"), "49.12.104.21")
        started = self._connected_since if (self._connected_since is not None) else time.monotonic()
        elapsed = int(time.monotonic() - started)
        idle_slot = random.random() < 0.20
        rx = 0.0 if idle_slot else round(random.uniform(220.0, 3850.0), 1)
        tx = 0.0 if idle_slot else round(random.uniform(45.0, 680.0), 1)
        base_ping = parse_int_value(active_prof.get("ping_ms", 42), 42)
        if base_ping <= 0:
            base_ping = 42
        ping = max(14, base_ping + random.randint(-4, 5))
        vec = (
            "AUTO-HYBRID"
            if get_bool_value(self._settings, "autopilot", True)
            else pick_first_text(self._settings, ("manual_vector_id",), "VEC-01")
        )
        self.telemetry_updated.emit(
            {
                "ui_phase": "CONNECTED",
                "state": "connected",
                "is_connecting": False,
                "is_connected": True,
                "selected_index": self.get_selected_index(),
                "active_profile_uid": pick_first_text(active_prof, ("uid",), ""),
                "country_code": cc,
                "egress_country": cc,
                "button_text": "قطع اتصال امن",
                "uptime_label": format_uptime_hms(elapsed),
                "status_headline": "متصل است",
                "status_detail": "تونل عبوری پایدار است | نگهبان ترمیم خودکار (Watchdog) فعال",
                "egress_ip": egress,
                "active_vector_id": vec,
                "ping_ms": ping,
                "tx_rate_kbps": tx,
                "rx_rate_kbps": rx,
                "tx_rate_label": format_rate_from_kbps(tx),
                "rx_rate_label": format_rate_from_kbps(rx),
                "progress_percent": 100,
            }
        )

    def _emit_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_message.emit(f"[{ts}] {msg}")


class BrandLogoWidget(QWidget):
    def __init__(self, logo_path: str = "assets/logo.png", size: int = 30, parent=None):
        super().__init__(parent)
        self._logo_path = logo_path
        lock_widget_dimensions(self, size, size)

    def paintEvent(self, _event):
        painter = QPainter(self)
        VectorIconPainter.draw_brand_logo(
            painter,
            QRectF(1, 1, self.width() - 2, self.height() - 2),
            self._logo_path,
        )


class TopBrandHeaderBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBrandBar")
        self.setMinimumHeight(48)
        self.setMaximumHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 6, 18, 6)
        layout.setSpacing(10)

        self.logo = BrandLogoWidget("assets/logo.png", size=28)
        self.brand_lbl = QLabel("Alan-RIP-Dpi")
        enforce_english_ltr(self.brand_lbl, mono_size=12, bold=True)

        self.ver_badge = QLabel("v1.0.0")
        self.ver_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.ver_badge, mono_size=9, bold=True)

        self.origin_flag = FlagBadgeWidget("IR", width=28, height=18)
        self.origin_lbl = QLabel("نود محلی: ایران")
        self.origin_lbl.setObjectName("MutedLabel")
        self.origin_lbl.setFont(make_ui_font(9, QFont.Weight.DemiBold))

        self.theme_btn = VectorIconButton("sun", size=32)
        self.theme_btn.setToolTip("تغییر حالت شب / روز")

        layout.addWidget(self.logo)
        layout.addWidget(self.brand_lbl)
        layout.addWidget(self.ver_badge)
        layout.addStretch()
        layout.addWidget(self.origin_lbl)
        layout.addWidget(self.origin_flag)
        layout.addSpacing(6)
        layout.addWidget(self.theme_btn)

    def set_palette_theme(self, palette: ThemePalette):
        self.theme_btn.set_icon_name("sun" if palette.is_dark else "moon")
        self.theme_btn.set_palette_theme(palette)


class AlanMainWindow(QMainWindow):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        load_application_fonts()

        self.setWindowTitle("Alan-RIP-Dpi")
        self.setWindowIcon(build_brand_window_icon("assets/logo.png"))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setMinimumSize(980, 640)
        self.resize(1180, 760)

        self._palette: ThemePalette = DARK_PALETTE
        self._is_connecting = False
        self._is_connected = False
        self._active_profile_index = -1
        self._active_profile_uid = ""
        self._profiles_cache: list[dict] = []
        self._vectors_cache: list = []
        self._settings_cache: dict = {}
        self.controller = controller if (controller is not None) else DemoDpiController(self)

        self.shell = QFrame()
        self.shell.setObjectName("MainShell")

        shell_vbox = QVBoxLayout(self.shell)
        shell_vbox.setContentsMargins(0, 0, 0, 0)
        shell_vbox.setSpacing(0)

        self.top_bar = TopBrandHeaderBar(self.shell)
        self.top_bar.theme_btn.clicked.connect(self.toggle_theme)
        shell_vbox.addWidget(self.top_bar)

        self.global_task_strip = TaskProgressStrip(inline_style=False)
        self.global_task_strip.stop_requested.connect(self._invoke_stop_scanner)
        shell_vbox.addWidget(self.global_task_strip)

        body_hbox = QHBoxLayout()
        body_hbox.setContentsMargins(0, 0, 0, 0)
        body_hbox.setSpacing(0)

        self.nav_rail = QFrame()
        self.nav_rail.setObjectName("NavRail")
        self.nav_rail.setMinimumWidth(90)
        self.nav_rail.setMaximumWidth(92)
        rail_layout = QVBoxLayout(self.nav_rail)
        rail_layout.setContentsMargins(6, 12, 6, 12)
        rail_layout.setSpacing(8)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_home = NavRailButton("radar_home", "خانه")
        self.btn_scanner = NavRailButton("scanner", "اسکنر")
        self.btn_profiles = NavRailButton("profiles", "پروفایل‌ها")
        self.btn_settings = NavRailButton("settings", "تنظیمات")
        self.btn_logs = NavRailButton("logs", "گزارش زنده")

        self._nav_buttons = (
            self.btn_home,
            self.btn_scanner,
            self.btn_profiles,
            self.btn_settings,
            self.btn_logs,
        )
        for idx, btn in enumerate(self._nav_buttons):
            self.nav_group.addButton(btn, idx)
            rail_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

        rail_layout.addStretch()

        self.pages = QStackedWidget()
        self.home_page = HomePage()
        self.scanner_page = ScannerPage()
        self.profiles_page = ProfilesPage()
        self.settings_page = SettingsPage()
        self.logs_page = LogsPage()

        for page in (
            self.home_page,
            self.scanner_page,
            self.profiles_page,
            self.settings_page,
            self.logs_page,
        ):
            self.pages.addWidget(page)

        self.btn_home.setChecked(True)
        self.nav_group.idClicked.connect(self.pages.setCurrentIndex)

        body_hbox.addWidget(self.nav_rail)
        body_hbox.addWidget(self.pages, 1)
        shell_vbox.addLayout(body_hbox, 1)

        self.setCentralWidget(self.shell)

        self.apply_theme(DARK_PALETTE)
        self._wire_ui_and_controller()
        self._hydrate_initial_state()

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_titlebar_theme(self, self._palette.is_dark)

    def _wire_ui_and_controller(self):
        self.settings_page.bind_controller(self.controller)

        self.home_page.connect_toggled.connect(self._handle_connect_toggle)
        self.home_page.quick_paste_clicked.connect(self._handle_quick_clipboard_import)
        self.home_page.hunt_best_requested.connect(self._invoke_hunt_best)
        self.home_page.profile_selected.connect(self._invoke_select_config)
        self.home_page.quick_setting_changed.connect(self._handle_home_quick_settings)
        self.home_page.tun_toggled.connect(self._handle_tun_toggled)

        self.scanner_page.start_scan_requested.connect(self._invoke_start_scanner)
        self.scanner_page.stop_scan_requested.connect(self._invoke_stop_scanner)
        self.scanner_page.apply_ip_requested.connect(self._invoke_apply_scanned_ip)
        self.scanner_page.apply_vector_requested.connect(self._invoke_apply_scanned_vector)
        self.scanner_page.apply_vector_all_requested.connect(self._invoke_apply_vector_to_all)
        self.scanner_page.connect_scanned_profile_requested.connect(self._invoke_connect_scanned_profile)

        self.profiles_page.import_clipboard_requested.connect(self._invoke_import_configs)
        self.profiles_page.import_file_requested.connect(self._invoke_import_from_file)
        self.profiles_page.open_config_editor_requested.connect(self._open_full_config_editor)
        self.profiles_page.hunt_best_requested.connect(self._invoke_hunt_best)
        self.profiles_page.stop_task_requested.connect(self._invoke_stop_scanner)
        self.profiles_page.clear_all_requested.connect(self._invoke_clear_all_configs)
        self.profiles_page.quick_ping_requested.connect(lambda: self._call_ctrl("quick_ping_configs"))
        self.profiles_page.sort_requested.connect(lambda by: self._call_ctrl("sort_configs", by))
        self.profiles_page.deduplicate_requested.connect(lambda: self._call_ctrl("deduplicate_configs"))
        self.profiles_page.remove_dead_requested.connect(lambda: self._call_ctrl("remove_dead_configs"))
        self.profiles_page.rename_requested.connect(lambda idx, name: self._call_ctrl("rename_config", idx, name))
        self.profiles_page.select_requested.connect(self._invoke_select_config)
        self.profiles_page.delete_requested.connect(lambda idx: self._call_ctrl("delete_config", idx))
        self.profiles_page.clone_clean_requested.connect(
            lambda idx, cnt: self._call_ctrl("clone_config_with_clean_ips", idx, cnt)
        )
        self.profiles_page.send_to_scanner_requested.connect(self._jump_and_scan_profile)
        self.profiles_page.export_requested.connect(self._handle_export_configs)
        self.profiles_page.add_sub_requested.connect(lambda url, title: self._call_ctrl("add_subscription", url, title))
        self.profiles_page.refresh_subs_requested.connect(lambda: self._call_ctrl("refresh_subscriptions"))
        self.profiles_page.delete_sub_requested.connect(lambda idx: self._call_ctrl("delete_subscription", idx))

        self.settings_page.base_switch_toggled.connect(self._handle_base_switch_toggled)
        self.settings_page.settings_updated.connect(self._handle_settings_page_change)

        signal_map = [
            (("telemetry_updated",), self.on_telemetry_update),
            (("log_message", "log_emitted"), self.on_log_message),
            (("profiles_updated", "profiles_changed"), self.on_profiles_updated),
            (("settings_updated", "settings_changed"), self.on_settings_updated),
            (("scan_row_emitted", "scan_row"), self.on_scan_row),
            (("scan_results_ranked",), self.on_scan_results_ranked),
            (("scan_progress", "scan_progress_updated"), self.on_scan_progress),
            (("scan_state_changed",), self.on_scan_state_changed),
            (("subscriptions_updated", "subscriptions_changed"), self.on_subscriptions_updated),
            (("task_progress", "task_progress_updated", "task_progress_changed"), self.on_task_progress),
            (("tun_status_changed", "tun_state_changed"), self.on_tun_status_changed),
        ]
        for attr_names, slot in signal_map:
            for attr in attr_names:
                sig = getattr(self.controller, attr, None)
                if (sig is not None) and hasattr(sig, "connect"):
                    try:
                        sig.connect(slot, Qt.ConnectionType.UniqueConnection)
                    except (TypeError, RuntimeError):
                        pass
                    break

    def _query_controller_selected_index(self) -> int:
        fn = getattr(self.controller, "get_selected_index", None)
        if callable(fn):
            try:
                raw_val = fn()
            except Exception:
                raw_val = None
            if raw_val is not None:
                return parse_int_value(raw_val, -1)
        return -1

    def _hydrate_initial_state(self):
        vectors = self._call_ctrl("get_vectors")
        if isinstance(vectors, list):
            self._vectors_cache = list(vectors)
            self.settings_page.set_vectors(vectors)

        raw_settings = self._call_ctrl("get_settings")
        settings = coerce_dict(raw_settings)
        if settings:
            self.on_settings_updated(settings)

        sel_from_ctrl = self._query_controller_selected_index()
        if sel_from_ctrl >= 0:
            self._active_profile_index = sel_from_ctrl

        profiles = self._call_ctrl("get_profiles")
        if isinstance(profiles, list):
            self.on_profiles_updated(profiles)

        subs = self._call_ctrl("get_subscriptions")
        if isinstance(subs, list):
            self.on_subscriptions_updated(subs)

        snap = self._call_ctrl("get_telemetry_snapshot")
        if isinstance(snap, dict):
            self.on_telemetry_update(snap)

    def _call_ctrl(self, method_name: str, *args, **kwargs):
        fn = getattr(self.controller, method_name, None)
        if callable(fn):
            return fn(*args, **kwargs)
        return None

    def _get_active_uri(self) -> str:
        if (self._active_profile_index >= 0) and (self._active_profile_index < len(self._profiles_cache)):
            prof = self._profiles_cache[self._active_profile_index]
            return pick_first_text(prof, ("raw_uri", "uri", "raw"), "")
        return ""

    def _handle_connect_toggle(self):
        toggle_fn = getattr(self.controller, "toggle_connection", None)
        if callable(toggle_fn):
            toggle_fn()
            return

        if any((self._is_connecting, self._is_connected)):
            self._call_ctrl("request_disconnect")
            return

        conn_fn = getattr(self.controller, "request_connect", None)
        if callable(conn_fn):
            uri = self._get_active_uri()
            try:
                conn_fn(uri)
            except TypeError:
                conn_fn()

    def _invoke_hunt_best(self):
        self.pages.setCurrentIndex(0)
        self.btn_home.setChecked(True)
        self._call_ctrl("hunt_best_and_connect")

    def _handle_tun_toggled(self, checked: bool):
        if checked:
            admin_fn = getattr(self.controller, "is_admin", None)
            has_admin = bool(admin_fn()) if callable(admin_fn) else True
            if not has_admin:
                self.home_page.set_tun_switch_silent(False)
                dlg = AdminElevationDialog(self._palette, self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._call_ctrl("request_admin_elevation")
                return

        tun_fn = getattr(self.controller, "set_tun_mode", None)
        if callable(tun_fn):
            tun_fn(bool(checked))
        else:
            self._settings_cache["tun_enabled"] = bool(checked)
            self._call_ctrl("update_settings", {"tun_enabled": bool(checked)})

    def _handle_quick_clipboard_import(self):
        clip = QGuiApplication.clipboard().text().strip()
        if clip:
            self._invoke_import_configs(clip)

    def _handle_base_switch_toggled(self, key: str, checked: bool):
        self._settings_cache[key] = bool(checked)

    def _handle_home_quick_settings(self, partial: dict):
        if "autopilot" in partial:
            self.settings_page.set_autopilot_mode(get_bool_value(partial, "autopilot", True))
        merged = dict(self._settings_cache)
        merged.update(self.settings_page.collect_settings())
        merged.update(partial)
        merged["tun_enabled"] = bool(self.home_page.tun_switch.isChecked())
        self._settings_cache = merged
        self._call_ctrl("update_settings", dict(partial))

    def _handle_settings_page_change(self, page_settings: dict):
        merged = dict(self._settings_cache)
        merged.update(page_settings)
        merged["system_proxy"] = bool(self.home_page.sys_proxy_switch.isChecked())
        merged["autopilot"] = bool(self.home_page.autopilot_switch.isChecked())
        merged["tun_enabled"] = bool(self.home_page.tun_switch.isChecked())
        self._settings_cache = merged
        self._call_ctrl("update_settings", merged)

    def _invoke_select_config(self, index: int):
        if index < 0:
            return
        self._active_profile_index = index
        if index < len(self._profiles_cache):
            self._active_profile_uid = pick_first_text(
                self._profiles_cache[index],
                ("uid", "profile_uid", "id"),
                "",
            )
        self._call_ctrl("select_config", index)

    def _open_full_config_editor(self, index: int):
        editable_data = self._call_ctrl("get_config_editable", index)
        if not isinstance(editable_data, dict):
            if (index >= 0) and (index < len(self._profiles_cache)):
                editable_data = dict(self._profiles_cache[index])
            else:
                editable_data = {}

        vectors = self._call_ctrl("get_vectors")
        if isinstance(vectors, list):
            self._vectors_cache = list(vectors)

        dlg = ConfigEditorDialog(index, editable_data, self._vectors_cache, self._palette, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            form_dict = dlg.collect_data()
            self._call_ctrl("save_config_editable", index, form_dict)
            msg = "کانفیگ جدید با موفقیت ذخیره شد." if (index < 0) else "تغییرات کانفیگ با موفقیت ذخیره شد."
            self.profiles_page.show_feedback(msg)

    def _invoke_clear_all_configs(self):
        self._active_profile_index = -1
        self._active_profile_uid = ""
        self._call_ctrl("clear_all_configs")
        self.profiles_page.show_feedback("تمام کانفیگ‌های مخزن حذف شدند.")

    def _invoke_import_configs(self, raw_text: str):
        self._call_ctrl("import_configs", raw_text)
        self.profiles_page.show_feedback("کانفیگ‌های جدید به مخزن اضافه شدند.")

    def _invoke_import_from_file(self, file_path: str):
        self._call_ctrl("import_configs_from_file", file_path)
        self.profiles_page.show_feedback("واردسازی از فایل انجام شد.")

    def _invoke_start_scanner(self, mode: str, target_index: int, options: dict):
        self._call_ctrl("start_scanner", mode, target_index, options)

    def _invoke_stop_scanner(self):
        self._call_ctrl("stop_scanner")

    def _invoke_apply_scanned_ip(self, ip: str, only_active: bool):
        self._call_ctrl("apply_scanned_ip", ip, only_active)
        scope = "کانفیگ فعلی" if only_active else "کل مخزن"
        self.scanner_page.show_confirmation(f"آدرس تمیز {ip} با موفقیت به {scope} وصله شد.")

    def _invoke_apply_scanned_vector(self, item_id: str, target_index: int, endpoint: str, auto_connect: bool):
        self._call_ctrl("apply_scanned_vector", item_id, target_index, endpoint, auto_connect)
        if auto_connect:
            self.scanner_page.show_confirmation(f"متد {item_id} روی کانفیگ ثبت شد و اتصال آغاز گردید.")
            self.pages.setCurrentIndex(0)
            self.btn_home.setChecked(True)
        else:
            self.scanner_page.show_confirmation(f"متد {item_id} با موفقیت روی کانفیگ ذخیره شد.")

    def _invoke_apply_vector_to_all(self, item_id: str, endpoint: str):
        self._call_ctrl("apply_vector_to_all_configs", item_id, endpoint)
        self.scanner_page.show_confirmation(f"متد {item_id} روی تمام کانفیگ‌های مخزن اعمال شد.")

    def _invoke_connect_scanned_profile(self, target_index: int, bound_vector: str, endpoint: str):
        fn = getattr(self.controller, "connect_scanned_profile", None)
        self.pages.setCurrentIndex(0)
        self.btn_home.setChecked(True)
        if callable(fn):
            fn(target_index, bound_vector, endpoint)
        else:
            if target_index >= 0:
                self._invoke_select_config(target_index)
            self._handle_connect_toggle()

    def _jump_and_scan_profile(self, index: int):
        self.pages.setCurrentIndex(1)
        self.btn_scanner.setChecked(True)
        self.scanner_page.trigger_profile_deep_scan(index)

    def _handle_export_configs(self, mode: str, inject_early_data: int):
        fn = getattr(self.controller, "export_configs", None)
        if not callable(fn):
            return
        try:
            res = fn(mode=mode, inject_early_data=inject_early_data)
        except TypeError:
            res = fn(mode, inject_early_data)

        text_out = ""
        if isinstance(res, str):
            text_out = res
        elif isinstance(res, list):
            text_out = "\n".join(str(x) for x in res if x)

        if text_out:
            QGuiApplication.clipboard().setText(text_out)
            count = len([ln for ln in text_out.splitlines() if ln.strip()])
            self.profiles_page.show_feedback(
                f"{count} کانفیگ سالم بهینه‌شده با EarlyData={inject_early_data} در کلیپ‌بورد کپی شد."
            )
        else:
            self.profiles_page.show_feedback("خروجی کانفیگ انجام شد (مورد VERIFIED یافت نشد یا توسط بک‌اند ذخیره شد).")

    def _enrich_snapshot_geo(self, snapshot: dict) -> dict:
        enriched = dict(snapshot)
        existing_cc = pick_first_text(enriched, ("country_code", "egress_country", "country", "cc"), "")
        if not existing_cc:
            ip_cc = infer_country_from_ipv4(pick_first_text(enriched, ("egress_ip",), ""))
            if ip_cc:
                enriched["egress_country"] = ip_cc
        return enriched

    def _sync_selection_from_snapshot(self, snap: dict):
        snap_uid = pick_first_text(snap, ("active_profile_uid",), "")
        raw_sel = snap.get("selected_index", None)
        snap_idx = parse_int_value(raw_sel, -1) if (raw_sel is not None) else -1

        resolved = -1
        if snap_uid and bool(self._profiles_cache):
            for idx, item in enumerate(self._profiles_cache):
                uid_val = pick_first_text(item, ("uid", "profile_uid", "id"), "")
                if uid_val and (uid_val == snap_uid):
                    resolved = idx
                    break

        if (resolved < 0) and (snap_idx >= 0):
            if (not self._profiles_cache) or (snap_idx < len(self._profiles_cache)):
                resolved = snap_idx

        changed = False
        if snap_uid and (snap_uid != self._active_profile_uid):
            self._active_profile_uid = snap_uid
            changed = True
        if (resolved >= 0) and (resolved != self._active_profile_index):
            self._active_profile_index = resolved
            changed = True

        if changed and bool(self._profiles_cache):
            self.home_page.set_selected_profile_silent(self._active_profile_index, self._active_profile_uid)
            self.profiles_page.refresh_cards(
                self._profiles_cache,
                self._active_profile_index,
                self._active_profile_uid,
            )

    @Slot(dict)
    def on_telemetry_update(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            return
        enriched = self._enrich_snapshot_geo(snapshot)
        self._sync_selection_from_snapshot(enriched)

        phase = pick_first_text(enriched, ("ui_phase",), "").upper()
        state = pick_first_text(enriched, ("state",), "disconnected").lower()

        default_connecting = (phase == "CONNECTING") if bool(phase) else (
            state in ("connecting", "scanning", "probing", "reconnecting", "starting")
        )
        default_connected = (phase == "CONNECTED") if bool(phase) else (
            state in ("connected", "active", "online", "protected")
        )

        self._is_connecting = get_bool_value(enriched, "is_connecting", default_connecting)
        self._is_connected = get_bool_value(enriched, "is_connected", default_connected)
        self.home_page.apply_telemetry(enriched)

    @Slot(str)
    def on_log_message(self, line: str):
        self.logs_page.append_line(str(line))

    @Slot(list)
    def on_profiles_updated(self, profiles: list):
        self.setUpdatesEnabled(False)
        try:
            normalized: list[dict] = []
            selected_by_flag = -1
            input_list = profiles if isinstance(profiles, list) else []

            for idx, item in enumerate(input_list):
                if isinstance(item, dict):
                    d = dict(item)
                else:
                    d = coerce_dict(item)
                    if not d:
                        d = {"name": str(item), "uri": str(item)}
                if (selected_by_flag < 0) and get_bool_value(d, "is_selected", False):
                    selected_by_flag = idx
                normalized.append(d)

            self._profiles_cache = normalized

            if not normalized:
                resolved_idx = -1
                self._active_profile_uid = ""
            else:
                resolved_idx = selected_by_flag
                if resolved_idx < 0:
                    ctrl_idx = self._query_controller_selected_index()
                    if (ctrl_idx >= 0) and (ctrl_idx < len(normalized)):
                        resolved_idx = ctrl_idx
                if resolved_idx < 0:
                    resolved_idx = resolve_active_profile_index(
                        normalized,
                        fallback_index=self._active_profile_index,
                        active_uid=self._active_profile_uid,
                    )
                if (resolved_idx >= 0) and (resolved_idx < len(normalized)):
                    self._active_profile_uid = pick_first_text(
                        normalized[resolved_idx],
                        ("uid", "profile_uid", "id"),
                        self._active_profile_uid,
                    )

            self._active_profile_index = resolved_idx

            self.home_page.set_profiles(normalized, self._active_profile_index, self._active_profile_uid)
            self.scanner_page.set_profiles(normalized, self._active_profile_index, self._active_profile_uid)
            self.profiles_page.refresh_cards(normalized, self._active_profile_index, self._active_profile_uid)
        finally:
            self.setUpdatesEnabled(True)

    @Slot(dict)
    def on_settings_updated(self, settings: dict):
        parsed = coerce_dict(settings)
        if not parsed:
            return
        self._settings_cache.update(parsed)

        uid_in_settings = pick_first_text(parsed, ("active_profile_uid",), "")
        if uid_in_settings:
            self._active_profile_uid = uid_in_settings

        if ("selected_index" in parsed) and (parsed["selected_index"] is not None):
            idx_val = parse_int_value(parsed.get("selected_index", -1), -1)
            if idx_val >= 0:
                self._active_profile_index = idx_val
        elif ("active_profile_index" in parsed) and (parsed["active_profile_index"] is not None):
            idx_val = parse_int_value(parsed.get("active_profile_index", -1), -1)
            if idx_val >= 0:
                self._active_profile_index = idx_val

        self.home_page.sync_switches(self._settings_cache)
        self.settings_page.apply_settings_dict(self._settings_cache)

    @Slot(dict)
    def on_scan_row(self, row: dict):
        if isinstance(row, dict):
            self.scanner_page.append_or_update_row(row)

    @Slot(list)
    def on_scan_results_ranked(self, rows: list):
        if isinstance(rows, list):
            self.scanner_page.apply_ranked_results(rows)

    @Slot(int, str)
    def on_scan_progress(self, percent: int, label: str):
        self.scanner_page.update_progress(percent, label)

    @Slot(bool, str)
    def on_scan_state_changed(self, is_running: bool, summary: str):
        self.scanner_page.update_scan_state(is_running, summary)

    @Slot(list)
    def on_subscriptions_updated(self, subs: list):
        self.profiles_page.refresh_subscriptions(subs if isinstance(subs, list) else [])

    @Slot(bool, int, str)
    def on_task_progress(self, active: bool, percent: int, message: str):
        self.global_task_strip.update_task_state(active, percent, message)
        self.profiles_page.inline_task_strip.update_task_state(active, percent, message)
        self.scanner_page.inline_task_strip.update_task_state(active, percent, message)

    @Slot(bool, str)
    def on_tun_status_changed(self, active: bool, detail: str):
        self._settings_cache["tun_enabled"] = bool(active)
        self.home_page.apply_tun_status(active, detail)

    def toggle_theme(self):
        target = LIGHT_PALETTE if self._palette.is_dark else DARK_PALETTE
        self.apply_theme(target)

    def apply_theme(self, palette: ThemePalette):
        self.setUpdatesEnabled(False)
        try:
            self._palette = palette
            qpal = build_qpalette(palette)
            base_font = make_ui_font(10, QFont.Weight.Medium)
            self.setFont(base_font)
            self.setPalette(qpal)

            app = QApplication.instance()
            if app is not None:
                app.setFont(base_font)
                app.setPalette(qpal)

            self.setStyleSheet(build_stylesheet(palette))
            apply_windows_titlebar_theme(self, palette.is_dark)

            self.top_bar.set_palette_theme(palette)
            self.global_task_strip.set_palette_theme(palette)

            for btn in self._nav_buttons:
                btn.set_palette_theme(palette)

            self.home_page.set_palette_theme(palette)
            self.scanner_page.set_palette_theme(palette)
            self.profiles_page.set_palette_theme(palette)
            self.settings_page.set_palette_theme(palette)
        finally:
            self.setUpdatesEnabled(True)