import random
import re
import time
from datetime import datetime
from PySide6.QtCore import QObject, QRectF, QSignalBlocker, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .animated_widgets import (
    GlobalTaskStrip,
    NavRailButton,
    NeuCard,
    VectorIconButton,
    draw_neu_inset,
)
from .flag_icons import FlagBadgeWidget, GeoFlagResolver
from .pages import (
    DEFAULT_FINGERPRINTS,
    ConfigEditorDialog,
    ConfigsPage,
    HomePage,
    LabPage,
    LogsPage,
    RoutingSettingsPage,
    SubscriptionManagerDialog,
    extract_profile_group,
    extract_profile_uid,
    format_rate_kbps,
    is_gemini_verified,
    set_switch_blocked,
)
from .theme import (
    DARK_PALETTE,
    I18N,
    LIGHT_PALETTE,
    ThemePalette,
    apply_windows_titlebar_theme,
    build_qpalette,
    build_stylesheet,
    enforce_english_ltr,
    get_bool,
    get_int,
    load_application_fonts,
    lock_widget_dimensions,
    make_ui_font,
    strip_emojis,
)
from .vector_icons import VectorIconPainter

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
            "91.107.",
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
    profiles_updated = Signal(list, int)
    verified_outputs_updated = Signal(list)
    auto_locations_updated = Signal(list, str)
    settings_updated = Signal(dict)
    subscriptions_updated = Signal(list)
    scan_row = Signal(dict)
    scan_results_ranked = Signal(list)
    scan_progress = Signal(int, str)
    scan_state_changed = Signal(bool, str)
    task_progress = Signal(bool, int, str)
    tun_status_changed = Signal(bool, bool, str)


class DemoDpiController(BackendControllerAdapter):
    VECTOR_CATALOG: list[tuple[str, str]] = [
        ("VEC-00", "Direct Baseline Stream"),
        ("VEC-01", "Adaptive TLS Record Split"),
        ("VEC-02", "Micro-Fragment 5-16B"),
        ("VEC-03", "Window-5B SNI Slicer"),
        ("VEC-04", "WS EarlyData 2048B Hybrid"),
        ("VEC-05", "Multi-Record ClientHello"),
        ("VEC-06", "Randomized Stride +400B"),
        ("VEC-07", "ALPN h2/http1.1 Morph"),
        ("VEC-08", "Low-Latency CDN Edge Split"),
        ("VEC-09", "Deep Record Padding"),
        ("VEC-10", "Burst Jitter Desync"),
        ("VEC-11", "Dual-Chunk Extension Split"),
        ("VEC-12", "Chrome uTLS Handshake"),
        ("VEC-13", "Firefox uTLS Handshake"),
        ("VEC-14", "Safari Handshake Profile"),
        ("VEC-15", "gRPC Stream Frame Slicer"),
        ("VEC-16", "HTTPUpgrade Early Split"),
        ("VEC-17", "Adaptive Stride Matrix"),
        ("VEC-18", "Sustained Stream Guard"),
        ("VEC-19", "Outbound Burst Balancer"),
        ("VEC-20", "Hybrid Multi-Layer Split"),
        ("VEC-21", "Polymorphic Record Slicer"),
        ("VEC-22", "Dynamic Window Cadence"),
        ("VEC-23", "Symmetric Duplex Framing"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_auto_location = "ALL"
        self._auto_locations: list[dict] = [
            {
                "code": "ALL",
                "name_fa": "همه لوکیشن‌ها",
                "name_en": "All Locations",
                "label_fa": "همه لوکیشن‌ها — 240",
                "label_en": "All Locations — 240",
                "count": 240,
            },
            {
                "code": "DE",
                "name_fa": "آلمان",
                "name_en": "Germany",
                "label_fa": "آلمان (DE) — 85",
                "label_en": "Germany (DE) — 85",
                "count": 85,
            },
            {
                "code": "NL",
                "name_fa": "هلند",
                "name_en": "Netherlands",
                "label_fa": "هلند (NL) — 64",
                "label_en": "Netherlands (NL) — 64",
                "count": 64,
            },
            {
                "code": "FI",
                "name_fa": "فنلاند",
                "name_en": "Finland",
                "label_fa": "فنلاند (FI) — 42",
                "label_en": "Finland (FI) — 42",
                "count": 42,
            },
            {
                "code": "US",
                "name_fa": "آمریکا",
                "name_en": "United States",
                "label_fa": "آمریکا (US) — 49",
                "label_en": "United States (US) — 49",
                "count": 49,
            },
        ]
        self._settings: dict = {
            "ui_language": "fa",
            "system_proxy": True,
            "tun_enabled": False,
            "tun_badge": "OFF",
            "autopilot": True,
            "autopilot_enabled": True,
            "auto_mode_enabled": True,
            "selected_auto_location": "ALL",
            "routing_mode": "bypass_ir",
            "block_quic": True,
            "remote_dns": "https://1.1.1.1/dns-query",
            "domestic_dns": "178.22.122.100",
            "custom_direct_domains": "geosite:ir\ngeoip:ir\ngeoip:private",
            "custom_proxy_domains": "geosite:google\ngeosite:youtube\n*.gemini.google.com",
            "custom_blocked_domains": "geosite:category-ads-all",
            "minimize_to_tray": True,
            "auto_pool_fallback": True,
            "require_youtube_6s": True,
            "verify_upload_stream": True,
            "self_healing_watchdog": True,
            "sub_auto_update_hours": 6,
            "engine_mode": "auto_hybrid",
            "manual_vector_id": "AUTO",
            "fragment_enabled": True,
            "fragment_packets": "tlshello",
            "fragment_length": "5-16",
            "fragment_interval": "2-3",
            "fingerprint": "custom_poly",
            "alpn_override": "auto",
            "ws_early_data": 2048,
            "mux_enabled": False,
            "mux_concurrency": 8,
            "forward_stride_bytes": 400,
            "stride_jitter_bytes": 32,
            "tun_mtu": 1500,
            "socks_port": 10808,
            "http_port": 10809,
            "bridge_port": 10810,
        }
        self._vectors = [
            {"vector_id": code, "code_name": desc}
            for code, desc in self.VECTOR_CATALOG
        ]
        self._fingerprints = [
            {"value": fp_val, "label": fp_lbl}
            for fp_val, fp_lbl in DEFAULT_FINGERPRINTS
        ]
        self._subscriptions = [
            {"title": "Alan-EU-Pool", "url": "https://sub.alan-network.example/api/v1/eu"},
            {"title": "CDN-Fast", "url": "https://sub.alan-network.example/api/v1/cdn"},
        ]
        self._selected_index = 0
        self._profiles: list[dict] = [
            {
                "uid": "node-de-01",
                "name": "DE Frankfurt Hetzner-01",
                "group": "Alan-EU-Pool",
                "country_code": "DE",
                "protocol": "vless",
                "host": "91.107.142.11",
                "original_host": "de1.alan-edge.net",
                "port": 443,
                "network": "ws",
                "security": "tls",
                "sni": "de1.alan-edge.net",
                "fingerprint": "custom_poly",
                "status": "VERIFIED",
                "gemini_ok": True,
                "gemini_status": "OK",
                "ping_ms": 43,
                "cached_vector_id": "VEC-01",
                "preferred_vector_id": "VEC-01",
                "is_selected": True,
                "uri": "vless://11111111-2222-3333-4444-555555555555@91.107.142.11:443?security=tls&type=ws&sni=de1.alan-edge.net#DE-Frankfurt-01",
            },
            {
                "uid": "node-nl-02",
                "name": "NL Amsterdam Core-02",
                "group": "Alan-EU-Pool",
                "country_code": "NL",
                "protocol": "vless",
                "host": "185.209.22.14",
                "original_host": "nl2.alan-edge.net",
                "port": 443,
                "network": "xhttp",
                "security": "tls",
                "sni": "nl2.alan-edge.net",
                "fingerprint": "custom_poly",
                "status": "VERIFIED",
                "gemini_ok": True,
                "gemini_status": "OK",
                "ping_ms": 49,
                "cached_vector_id": "VEC-04",
                "preferred_vector_id": "VEC-04",
                "is_selected": False,
                "uri": "vless://22222222-3333-4444-5555-666666666666@185.209.22.14:443?security=tls&type=xhttp&sni=nl2.alan-edge.net#NL-Amsterdam-02",
            },
            {
                "uid": "node-fi-03",
                "name": "FI Helsinki CDN-03",
                "group": "CDN-Fast",
                "country_code": "FI",
                "protocol": "trojan",
                "host": "104.18.36.214",
                "original_host": "fi.cdn-alan.org",
                "port": 2053,
                "network": "ws",
                "security": "tls",
                "sni": "fi.cdn-alan.org",
                "fingerprint": "custom_poly",
                "status": "UNTESTED",
                "gemini_ok": False,
                "gemini_status": "",
                "ping_ms": 0,
                "cached_vector_id": "AUTO",
                "preferred_vector_id": "AUTO",
                "is_selected": False,
                "uri": "trojan://pass@104.18.36.214:2053?security=tls&type=ws&sni=fi.cdn-alan.org#FI-Helsinki-CDN",
            },
            {
                "uid": "node-us-04",
                "name": "US Ashburn Edge-04",
                "group": "Manual",
                "country_code": "US",
                "protocol": "hysteria2",
                "host": "143.198.44.80",
                "original_host": "us.alan-ai.net",
                "port": 443,
                "network": "quic",
                "security": "tls",
                "sni": "us.alan-ai.net",
                "fingerprint": "custom_poly",
                "status": "VERIFIED",
                "gemini_ok": True,
                "gemini_status": "OK",
                "ping_ms": 112,
                "cached_vector_id": "VEC-08",
                "preferred_vector_id": "VEC-08",
                "is_selected": False,
                "uri": "hysteria2://auth@143.198.44.80:443?sni=us.alan-ai.net#US-Ashburn-04",
            },
        ]
        self._verified_outputs: list[dict] = [
            {
                "uid": "node-de-01",
                "name": "DE Frankfurt Hetzner-01",
                "country_code": "DE",
                "protocol": "VLESS",
                "vector_id": "VEC-01",
                "ping_ms": 43,
                "gemini_ok": True,
                "gemini_status": "OK",
                "host": "91.107.142.11",
            },
            {
                "uid": "node-nl-02",
                "name": "NL Amsterdam Core-02",
                "country_code": "NL",
                "protocol": "VLESS",
                "vector_id": "VEC-04",
                "ping_ms": 49,
                "gemini_ok": True,
                "gemini_status": "OK",
                "host": "185.209.22.14",
            },
        ]

        self._phase = "IDLE"
        self._connected_since: float | None = None
        self._connect_step = 0
        self._scan_mode = ""
        self._scan_step = 0
        self._scan_queue: list[tuple[dict, str]] = []
        self._scan_check_gemini = True
        self._scan_auto_connect = False
        self._scan_collected: list[dict] = []
        self._radar_port = 443

        self._connect_timer = QTimer(self)
        self._connect_timer.setInterval(560)
        self._connect_timer.timeout.connect(self._step_connect)

        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(1000)
        self._metrics_timer.timeout.connect(self._step_metrics)
        self._metrics_timer.start()

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(260)
        self._scan_timer.timeout.connect(self._step_scanner)

    def _emit_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_message.emit(f"[{ts}] {msg}")

    def _active_profile(self) -> dict:
        if 0 <= self._selected_index < len(self._profiles):
            return self._profiles[self._selected_index]
        return self._profiles[0] if self._profiles else {}

    def _emit_profiles(self) -> None:
        out = []
        for idx, p in enumerate(self._profiles):
            item = dict(p)
            item["is_selected"] = (idx == self._selected_index)
            out.append(item)
        self.profiles_updated.emit(out, self._selected_index)

    def get_profiles(self) -> list:
        out = []
        for idx, p in enumerate(self._profiles):
            item = dict(p)
            item["is_selected"] = (idx == self._selected_index)
            out.append(item)
        return out

    def get_selected_index(self) -> int:
        return self._selected_index if (0 <= self._selected_index < len(self._profiles)) else -1

    def get_verified_outputs(self) -> list:
        return [dict(x) for x in self._verified_outputs]

    def get_auto_locations(self) -> list:
        return [dict(loc) for loc in self._auto_locations]

    def get_selected_auto_location(self) -> str:
        return str(self._selected_auto_location or "ALL").upper()

    def set_auto_location(self, code: str) -> None:
        norm = str(code or "ALL").strip().upper()
        self._selected_auto_location = norm
        self._settings["selected_auto_location"] = norm
        self.auto_locations_updated.emit(self.get_auto_locations(), norm)
        self._emit_log(f"Auto-connect target location set to '{norm}'.")

    def refresh_auto_pool(self) -> None:
        self.task_progress.emit(True, 45, "Syncing auto-connect locations from repository...")
        QTimer.singleShot(
            380,
            lambda: (
                self.auto_locations_updated.emit(self.get_auto_locations(), self.get_selected_auto_location()),
                self.task_progress.emit(False, 100, ""),
            ),
        )
        self._emit_log("Synced auto-connect pool locations.")

    def hunt_subscription_and_connect(self, sub_url_or_title: str = "", title: str = "") -> None:
        target = str(sub_url_or_title or "").strip()
        grp_title = strip_emojis(str(title or "").strip()) or "Sub-Hunt"
        if target.startswith("http://") or target.startswith("https://"):
            existing_titles = {str(s.get("title") or "") for s in self._subscriptions if isinstance(s, dict)}
            if grp_title not in existing_titles:
                self._subscriptions.append({"title": grp_title, "url": target})
                self.subscriptions_updated.emit(self.get_subscriptions())
            group_filter = ""
        else:
            group_filter = target

        self._settings["autopilot"] = True
        self._settings["autopilot_enabled"] = True
        self._settings["auto_mode_enabled"] = True
        self.settings_updated.emit(dict(self._settings))
        self.start_lab_scan(
            scope="group" if group_filter else "selected",
            uid_list=None,
            group_tag=group_filter,
            target_vector="ALL",
            check_gemini=True,
            auto_connect=True,
        )

    def get_vectors(self) -> list:
        return [dict(v) for v in self._vectors]

    def get_fingerprints(self) -> list:
        return [dict(fp) for fp in self._fingerprints]

    def get_subscriptions(self) -> list:
        return [dict(s) for s in self._subscriptions]

    def get_settings(self) -> dict:
        return dict(self._settings)

    def update_settings(self, new_dict: dict) -> None:
        if isinstance(new_dict, dict):
            self._settings.update(new_dict)
            if "autopilot_enabled" in new_dict:
                ap_v = bool(new_dict["autopilot_enabled"])
                self._settings["autopilot"] = ap_v
                self._settings["auto_mode_enabled"] = ap_v
            elif "autopilot" in new_dict:
                ap_v = bool(new_dict["autopilot"])
                self._settings["autopilot_enabled"] = ap_v
                self._settings["auto_mode_enabled"] = ap_v
            self._settings["tun_badge"] = "ON" if bool(self._settings.get("tun_enabled")) else "OFF"
            self.settings_updated.emit(dict(self._settings))
            self._emit_log(f"Updated {len(new_dict)} configuration parameter(s).")

    def set_setting_value(self, key: str, value) -> None:
        k = str(key)
        self._settings[k] = value
        if k in ("autopilot_enabled", "auto_mode_enabled", "autopilot"):
            ap_v = bool(value)
            self._settings["autopilot"] = ap_v
            self._settings["autopilot_enabled"] = ap_v
            self._settings["auto_mode_enabled"] = ap_v
        elif k == "tun_enabled":
            self._settings["tun_badge"] = "ON" if bool(value) else "OFF"
        self.settings_updated.emit(dict(self._settings))
        self._emit_log(f"Setting '{k}' -> {value}")

    def set_system_proxy(self, enabled: bool) -> None:
        self._settings["system_proxy"] = bool(enabled)
        self.settings_updated.emit(dict(self._settings))
        self._emit_log(f"Windows System Proxy {'ENABLED' if enabled else 'DISABLED'}.")

    def set_tun_mode(self, enabled: bool) -> bool:
        state = bool(enabled)
        self._settings["tun_enabled"] = state
        self._settings["tun_badge"] = "ON" if state else "OFF"
        detail = "Wintun adapter active" if state else "TUN adapter standby"
        self.tun_status_changed.emit(state, state and (self._phase == "CONNECTED"), detail)
        self.settings_updated.emit(dict(self._settings))
        self._emit_log(f"TUN Virtual Adapter -> {'ON' if state else 'OFF'}.")
        return state

    def quit_application(self) -> None:
        self._scan_timer.stop()
        self._connect_timer.stop()
        self._metrics_timer.stop()
        if self._phase in ("CONNECTING", "CONNECTED"):
            self._phase = "IDLE"
        self._emit_log("Shutting down Xray core and restoring system proxy...")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def toggle_connection(self) -> None:
        if self._phase in ("CONNECTING", "CONNECTED"):
            self.request_disconnect()
        else:
            self.request_connect("")

    def request_connect(self, uri: str = "") -> None:
        self._phase = "CONNECTING"
        self._connected_since = None
        self._connect_step = 0
        ap_on = bool(self._settings.get("autopilot_enabled", True))
        if (not uri) and ap_on:
            loc_filter = self.get_selected_auto_location()
            if loc_filter != "ALL":
                for idx, p in enumerate(self._profiles):
                    if GeoFlagResolver.resolve_code(p) == loc_filter:
                        self._selected_index = idx
                        break
            elif self._verified_outputs:
                best = min(self._verified_outputs, key=lambda x: get_int(x, "ping_ms", 9999))
                self._select_by_uid(str(best.get("uid") or ""))
        prof = self._active_profile()
        self._emit_log(f"Initiating tunnel to '{prof.get('name', 'Smart-Auto')}'...")
        self._step_connect()
        self._connect_timer.start()

    def request_disconnect(self) -> None:
        was_probing = (self._phase == "CONNECTING")
        self._connect_timer.stop()
        self._phase = "IDLE"
        self._connected_since = None
        tun_en = bool(self._settings.get("tun_enabled", False))
        ap_on = bool(self._settings.get("autopilot_enabled", True))
        self.task_progress.emit(False, 0, "")
        self.tun_status_changed.emit(tun_en, False, "TUN standby")
        self._emit_log("Probing cancelled." if was_probing else "Tunnel disconnected cleanly.")
        prof = self._active_profile()
        self.telemetry_updated.emit(
            {
                "ui_phase": "IDLE",
                "state": "disconnected",
                "is_connecting": False,
                "is_connected": False,
                "tun_enabled": tun_en,
                "tun_badge": "ON" if tun_en else "OFF",
                "autopilot_enabled": ap_on,
                "auto_mode_enabled": ap_on,
                "selected_auto_location": self.get_selected_auto_location(),
                "gemini_ready": False,
                "selected_index": self.get_selected_index(),
                "active_profile_uid": extract_profile_uid(prof, 0),
                "egress_ip": "---",
                "egress_country_code": "",
                "egress_country": "",
                "destination_label": "---",
                "active_vector_id": "AUTO",
                "ping_ms": 0,
                "rx_rate_kbps": 0.0,
                "tx_rate_kbps": 0.0,
                "rx_rate_label": "0 B/s",
                "tx_rate_label": "0 B/s",
                "uptime_label": "00:00:00",
            }
        )

    def hunt_best_and_connect(self) -> None:
        self.ping_verified_outputs()
        self.request_connect("")

    def connect_verified_output(self, uid_or_index) -> None:
        if isinstance(uid_or_index, int) and 0 <= uid_or_index < len(self._verified_outputs):
            target_uid = str(self._verified_outputs[uid_or_index].get("uid") or "")
        else:
            target_uid = str(uid_or_index or "")
        self._select_by_uid(target_uid)
        self.request_connect("")

    def ping_verified_outputs(self) -> None:
        if not self._verified_outputs:
            return
        self.task_progress.emit(True, 45, "Pinging verified outputs...")
        for item in self._verified_outputs:
            item["ping_ms"] = random.randint(36, 94)
        self._verified_outputs.sort(key=lambda x: get_int(x, "ping_ms", 9999))
        self.verified_outputs_updated.emit(self.get_verified_outputs())
        QTimer.singleShot(320, lambda: self.task_progress.emit(False, 100, "Verified outputs sorted by ping."))
        self._emit_log("Sorted verified outputs by lowest real RTT.")

    def clear_verified_outputs(self) -> None:
        self._verified_outputs.clear()
        self.verified_outputs_updated.emit([])
        self._emit_log("Cleared verified outputs list.")

    def _select_by_uid(self, uid: str) -> None:
        if not uid:
            return
        for idx, p in enumerate(self._profiles):
            if extract_profile_uid(p, idx) == uid:
                self._selected_index = idx
                self._settings["active_profile_uid"] = uid
                self._emit_profiles()
                return

    def select_config(self, index_or_uid) -> None:
        if isinstance(index_or_uid, int):
            if 0 <= index_or_uid < len(self._profiles):
                self._selected_index = index_or_uid
                uid = extract_profile_uid(self._profiles[index_or_uid], index_or_uid)
                self._settings["active_profile_uid"] = uid
                self._emit_profiles()
                self._emit_log(f"Selected active config #{index_or_uid + 1}: {self._profiles[index_or_uid]['name']}")
        else:
            self._select_by_uid(str(index_or_uid))

    def import_configs(self, raw_text: str, group_tag: str = "Manual") -> None:
        lines = [ln.strip() for ln in str(raw_text or "").splitlines() if ln.strip()]
        if not lines:
            return
        grp = strip_emojis(group_tag) or "Manual"
        for i, ln in enumerate(lines):
            proto = ln.split("://")[0].lower() if "://" in ln else "vless"
            tag = ln.split("#")[-1] if "#" in ln else f"Imported-{len(self._profiles) + 1}"
            m_host = re.search(r"@([^:/?#]+)", ln)
            host = m_host.group(1) if m_host else "104.18.36.214"
            entry = {
                "uid": f"imp-{int(time.time() * 1000)}-{i}",
                "name": strip_emojis(tag)[:40],
                "group": grp,
                "protocol": proto,
                "host": host,
                "original_host": host,
                "port": 443,
                "network": "ws",
                "security": "tls",
                "sni": host,
                "fingerprint": "custom_poly",
                "status": "UNTESTED",
                "gemini_ok": False,
                "gemini_status": "",
                "ping_ms": 0,
                "cached_vector_id": "AUTO",
                "preferred_vector_id": "AUTO",
                "uri": ln,
            }
            entry["country_code"] = GeoFlagResolver.resolve_code(entry)
            self._profiles.append(entry)
        if self._selected_index < 0 and self._profiles:
            self._selected_index = 0
        self._emit_profiles()
        self._emit_log(f"Imported {len(lines)} config(s) into '{grp}'.")

    def delete_configs(self, uid_list: list) -> None:
        kill = {str(u) for u in (uid_list or [])}
        if not kill:
            return
        self._profiles = [p for i, p in enumerate(self._profiles) if extract_profile_uid(p, i) not in kill]
        self._verified_outputs = [v for v in self._verified_outputs if str(v.get("uid")) not in kill]
        self._selected_index = min(max(0, self._selected_index), len(self._profiles) - 1) if self._profiles else -1
        self._emit_profiles()
        self.verified_outputs_updated.emit(self.get_verified_outputs())
        self._emit_log(f"Deleted {len(kill)} config(s) from vault.")

    def delete_config(self, index_or_uid) -> None:
        if isinstance(index_or_uid, int) and 0 <= index_or_uid < len(self._profiles):
            uid = extract_profile_uid(self._profiles[index_or_uid], index_or_uid)
            self.delete_configs([uid])
        else:
            self.delete_configs([str(index_or_uid)])

    def clear_all_configs(self) -> None:
        self._profiles.clear()
        self._verified_outputs.clear()
        self._selected_index = -1
        self._emit_profiles()
        self.verified_outputs_updated.emit([])

    def deduplicate_configs(self) -> None:
        seen = set()
        uniq = []
        for p in self._profiles:
            key = str(p.get("uri") or f"{p.get('host')}:{p.get('port')}:{p.get('name')}")
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        self._profiles = uniq
        self._selected_index = min(max(0, self._selected_index), len(self._profiles) - 1) if self._profiles else -1
        self._emit_profiles()
        self._emit_log("Deduplicated vault profiles.")

    def remove_dead_configs(self) -> None:
        self._profiles = [p for p in self._profiles if str(p.get("status") or "").upper() != "DEAD"]
        self._selected_index = min(max(0, self._selected_index), len(self._profiles) - 1) if self._profiles else -1
        self._emit_profiles()
        self._emit_log("Removed DEAD configs from vault.")

    def sort_configs(self, sort_by: str = "ping") -> None:
        cur_uid = extract_profile_uid(self._active_profile(), -1) if self._profiles else ""
        if sort_by == "ping":
            self._profiles.sort(key=lambda x: get_int(x, "ping_ms", 0) if get_int(x, "ping_ms", 0) > 0 else 99999)
        elif sort_by == "protocol":
            self._profiles.sort(key=lambda x: str(x.get("protocol") or ""))
        else:
            self._profiles.sort(key=lambda x: str(x.get("name") or ""))
        for idx, p in enumerate(self._profiles):
            if extract_profile_uid(p, idx) == cur_uid:
                self._selected_index = idx
                break
        self._emit_profiles()

    def ping_configs(self, uid_list=None) -> None:
        target_set = {str(u) for u in uid_list} if uid_list else None
        self.task_progress.emit(True, 35, "Probing real TCP/TLS delay...")
        count = 0
        for idx, p in enumerate(self._profiles):
            uid = extract_profile_uid(p, idx)
            if (target_set is None) or (uid in target_set):
                alive = random.random() > 0.15
                p["status"] = "VERIFIED" if alive else "DEAD"
                p["ping_ms"] = random.randint(36, 138) if alive else 0
                count += 1
        self._emit_profiles()
        QTimer.singleShot(350, lambda: self.task_progress.emit(False, 100, "Delay check finished."))
        self._emit_log(f"Real delay ping completed for {count} node(s).")

    def probe_gemini_configs(self, uid_list=None) -> None:
        target_set = {str(u) for u in uid_list} if uid_list else None
        self.task_progress.emit(True, 50, "Checking Gemini AI endpoint reachability...")
        for idx, p in enumerate(self._profiles):
            uid = extract_profile_uid(p, idx)
            if (target_set is None) or (uid in target_set):
                ok = str(p.get("country_code") or "").upper() != "IR" and random.random() > 0.2
                p["gemini_ok"] = ok
                p["gemini_status"] = "OK" if ok else "BLOCKED"
        self._emit_profiles()
        QTimer.singleShot(400, lambda: self.task_progress.emit(False, 100, "Gemini AI check finished."))
        self._emit_log("Completed Gemini AI reachability probe.")

    def export_configs(self, mode: str = "verified", inject_early_data: int = 0) -> str:
        uris = []
        for p in self._profiles:
            if mode == "verified" and str(p.get("status") or "").upper() != "VERIFIED":
                continue
            u = str(p.get("uri") or "")
            if inject_early_data > 0 and "?" in u and "ed=" not in u:
                u = u.replace("?", f"?ed={inject_early_data}&", 1)
            if u:
                uris.append(u)
        return "\n".join(uris)

    def get_config_editable(self, index_or_uid) -> dict:
        if isinstance(index_or_uid, int) and 0 <= index_or_uid < len(self._profiles):
            return dict(self._profiles[index_or_uid])
        uid_str = str(index_or_uid)
        for idx, p in enumerate(self._profiles):
            if extract_profile_uid(p, idx) == uid_str:
                return dict(p)
        return {}

    def save_config_editable(self, index_or_uid, data_dict: dict) -> None:
        entry = dict(data_dict)
        if not get_bool(entry, "use_raw_uri", False) or not entry.get("raw_uri"):
            proto = entry.get("protocol", "vless")
            cred = entry.get("uuid_or_password") or "00000000-0000-0000-0000-000000000000"
            host = entry.get("host") or entry.get("address") or "127.0.0.1"
            port = get_int(entry, "port", 443)
            net = entry.get("network", "ws")
            sec = entry.get("security", "tls")
            sni = entry.get("sni", "")
            fp = entry.get("fingerprint", "custom_poly")
            name = entry.get("name", "Alan-Node")
            entry["uri"] = f"{proto}://{cred}@{host}:{port}?security={sec}&type={net}&sni={sni}&fp={fp}#{name}"
        else:
            entry["uri"] = entry["raw_uri"]

        entry["country_code"] = GeoFlagResolver.resolve_code(entry)
        entry["cached_vector_id"] = entry.get("preferred_vector_id", "AUTO")

        target_idx = -1
        if isinstance(index_or_uid, int) and 0 <= index_or_uid < len(self._profiles):
            target_idx = index_or_uid
        elif str(index_or_uid) not in ("-1", ""):
            for i, p in enumerate(self._profiles):
                if extract_profile_uid(p, i) == str(index_or_uid):
                    target_idx = i
                    break

        if target_idx >= 0:
            entry["uid"] = extract_profile_uid(self._profiles[target_idx], target_idx)
            self._profiles[target_idx] = entry
        else:
            entry["uid"] = f"manual-{int(time.time() * 1000)}"
            entry.setdefault("status", "UNTESTED")
            entry.setdefault("ping_ms", 0)
            self._profiles.append(entry)
            if self._selected_index < 0:
                self._selected_index = 0
        self._emit_profiles()

    def add_subscription(self, url: str, title: str = "Subscription") -> None:
        self._subscriptions.append({"title": strip_emojis(title) or "Subscription", "url": url.strip()})
        self.subscriptions_updated.emit(self.get_subscriptions())
        self._emit_log(f"Added subscription '{title}'.")

    def refresh_subscriptions(self) -> None:
        self.task_progress.emit(True, 55, "Refreshing all subscription feeds...")
        self.subscriptions_updated.emit(self.get_subscriptions())
        QTimer.singleShot(450, lambda: self.task_progress.emit(False, 100, "Subscriptions updated."))
        self._emit_log("Synced all active subscriptions.")

    def delete_subscription(self, index: int) -> None:
        if 0 <= index < len(self._subscriptions):
            self._subscriptions.pop(index)
            self.subscriptions_updated.emit(self.get_subscriptions())

    def start_lab_scan(
        self,
        scope: str = "selected",
        uid_list=None,
        group_tag: str = "",
        target_vector: str = "ALL",
        check_gemini: bool = False,
        auto_connect: bool = False,
    ) -> None:
        self._scan_timer.stop()
        self._scan_mode = "lab"
        self._scan_step = 0
        self._scan_collected.clear()
        self._scan_check_gemini = bool(check_gemini)
        self._scan_auto_connect = bool(auto_connect)

        if scope == "group" and group_tag:
            targets = [p for p in self._profiles if extract_profile_group(p) == group_tag]
        elif uid_list:
            uset = {str(u) for u in uid_list}
            targets = [p for i, p in enumerate(self._profiles) if extract_profile_uid(p, i) in uset]
        else:
            targets = [self._active_profile()] if self._profiles else []

        if not targets and self._profiles:
            targets = list(self._profiles)

        selected_vec = str(target_vector or "ALL").strip().upper()
        all_vec_ids = [v["vector_id"] for v in self._vectors]
        if selected_vec != "ALL":
            vec_pool = [selected_vec]
        else:
            vec_pool = all_vec_ids if len(targets) <= 1 else all_vec_ids[:6]

        self._scan_queue = [(prof, vid) for prof in targets for vid in vec_pool]

        self.scan_state_changed.emit(True, "lab")
        self.task_progress.emit(True, 5, "Alan Lab method simulation started...")
        self._emit_log(
            f"Started Lab scan: scope={scope}, target_vector={selected_vec}, pairs={len(self._scan_queue)}"
        )
        self._scan_timer.start()

    def start_clean_ip_scan(self, port: int = 443) -> None:
        self._scan_timer.stop()
        self._scan_mode = "clean_ip"
        self._scan_step = 0
        self._scan_collected.clear()
        self._radar_port = int(port or 443)
        self.scan_state_changed.emit(True, "clean_ip")
        self.task_progress.emit(True, 6, f"Scanning clean Cloudflare IPs on port {self._radar_port}...")
        self._scan_timer.start()

    def stop_scanner(self) -> None:
        self._scan_timer.stop()
        self.scan_state_changed.emit(False, self._scan_mode)
        self.task_progress.emit(False, 0, "")
        self._emit_log("Scanner stopped.")

    def apply_clean_ip(self, ip_addr: str, apply_all_cdn: bool = True) -> None:
        clean = str(ip_addr or "").split(":")[0].strip()
        if not clean:
            return
        if apply_all_cdn:
            for p in self._profiles:
                if str(p.get("network") or "") in ("ws", "grpc", "httpupgrade", "xhttp"):
                    p["host"] = clean
        elif 0 <= self._selected_index < len(self._profiles):
            self._profiles[self._selected_index]["host"] = clean
        self._emit_profiles()
        self._emit_log(f"Applied clean IP {clean} (all_cdn={apply_all_cdn}).")

    def apply_scanned_vector(self, vector_id: str, target_uid: str = "", connect_now: bool = False) -> None:
        for idx, p in enumerate(self._profiles):
            uid = extract_profile_uid(p, idx)
            if (not target_uid and idx == self._selected_index) or (uid == target_uid):
                p["cached_vector_id"] = vector_id
                p["preferred_vector_id"] = vector_id
                p["status"] = "VERIFIED"
                if connect_now:
                    self._selected_index = idx
                break
        self._emit_profiles()
        if connect_now:
            self.request_connect("")

    def _promote_winner_to_home(self, prof: dict, vec_id: str, ping_ms: int, gem_ok: bool) -> None:
        uid = extract_profile_uid(prof, 0)
        entry = {
            "uid": uid,
            "name": prof.get("name", "Verified Node"),
            "country_code": GeoFlagResolver.resolve_code(prof),
            "protocol": str(prof.get("protocol") or "VLESS").upper(),
            "vector_id": vec_id,
            "ping_ms": ping_ms,
            "gemini_ok": gem_ok,
            "gemini_status": "OK" if gem_ok else "",
            "host": prof.get("host") or prof.get("original_host") or "",
        }
        replaced = False
        for i, existing in enumerate(self._verified_outputs):
            if str(existing.get("uid")) == uid:
                if ping_ms < get_int(existing, "ping_ms", 9999):
                    self._verified_outputs[i] = entry
                replaced = True
                break
        if not replaced:
            self._verified_outputs.append(entry)
        self._verified_outputs.sort(key=lambda x: get_int(x, "ping_ms", 9999))
        self.verified_outputs_updated.emit(self.get_verified_outputs())

    def _step_scanner(self) -> None:
        self._scan_step += 1
        if self._scan_mode == "clean_ip":
            total = 8
            pct = min(100, int((self._scan_step / total) * 100))
            ip = f"104.18.{22 + self._scan_step}.{14 + self._scan_step * 11}"
            tcp = random.randint(26, 54)
            tls = tcp + random.randint(12, 28)
            row = {
                "scan_type": "clean_ip",
                "item_id": ip,
                "ip": ip,
                "endpoint": f"{ip}:{self._radar_port}",
                "tcp_ms": tcp,
                "tunnel_ms": tls,
                "score": round(100.0 - tls * 0.34, 1),
                "status": "VERIFIED",
                "verified": True,
            }
            self._scan_collected.append(row)
            self.scan_row.emit(row)
            msg = f"Radar clean IP {ip}:{self._radar_port} ({tls}ms)"
            self.scan_progress.emit(pct, msg)
            self.task_progress.emit(True, pct, msg)
            if self._scan_step >= total:
                self._scan_timer.stop()
                ranked = sorted(self._scan_collected, key=lambda r: -float(r.get("score") or 0.0))
                self.scan_results_ranked.emit(ranked)
                self.scan_state_changed.emit(False, "clean_ip")
                self.task_progress.emit(False, 100, "")
            return

        total = max(1, len(self._scan_queue))
        if self._scan_step <= len(self._scan_queue):
            prof, vid = self._scan_queue[self._scan_step - 1]
            uid = extract_profile_uid(prof, 0)
            passed = random.random() > 0.42
            ping = random.randint(38, 104) if passed else 0
            gem_ok = passed and self._scan_check_gemini and (GeoFlagResolver.resolve_code(prof) != "IR")
            pct = min(100, int((self._scan_step / total) * 100))
            row = {
                "scan_type": "lab",
                "item_id": f"{uid}:{vid}",
                "target_uid": uid,
                "title": prof.get("name", "Config"),
                "country_code": GeoFlagResolver.resolve_code(prof),
                "vector_id": vid,
                "tunnel_ms": ping,
                "upload_ok": passed,
                "gemini_ok": gem_ok,
                "gemini_status": "OK" if gem_ok else "",
                "verified": passed,
                "status": "VERIFIED" if passed else "FAILED",
                "score": round(100.0 - ping * 0.35, 1) if passed else 0.0,
            }
            self._scan_collected.append(row)
            self.scan_row.emit(row)
            summary = f"[{self._scan_step}/{total}] {prof.get('name')} -> {vid}"
            self.scan_progress.emit(pct, summary)
            self.task_progress.emit(True, pct, summary)

            if passed:
                prof["status"] = "VERIFIED"
                prof["ping_ms"] = ping
                prof["cached_vector_id"] = vid
                prof["gemini_ok"] = gem_ok
                prof["gemini_status"] = "OK" if gem_ok else ""
                self._promote_winner_to_home(prof, vid, ping, gem_ok)

        if self._scan_step >= total:
            self._scan_timer.stop()
            ranked = sorted(
                self._scan_collected,
                key=lambda x: (-int(bool(x.get("verified"))), get_int(x, "tunnel_ms", 99999) or 99999),
            )
            for idx_r, r_item in enumerate(ranked):
                r_item["rank"] = f"#{idx_r + 1}"
            self.scan_results_ranked.emit(ranked)
            self._emit_profiles()
            self.scan_state_changed.emit(False, "lab")
            self.task_progress.emit(False, 100, "")
            self._emit_log("Lab scan finished; verified winners promoted to Home.")
            if self._scan_auto_connect and self._verified_outputs:
                self.connect_verified_output(0)

    def _step_connect(self) -> None:
        prof = self._active_profile()
        tun_en = bool(self._settings.get("tun_enabled", False))
        ap_on = bool(self._settings.get("autopilot_enabled", True))
        stages = [
            "Selecting verified anti-DPI method...",
            "Applying TLS fragmentation & verifying 6s stream...",
            "Finalizing local SOCKS5/HTTP & routing rules...",
        ]
        if self._connect_step < len(stages):
            self.telemetry_updated.emit(
                {
                    "ui_phase": "CONNECTING",
                    "state": "connecting",
                    "is_connecting": True,
                    "is_connected": False,
                    "tun_enabled": tun_en,
                    "tun_badge": "ON" if tun_en else "OFF",
                    "autopilot_enabled": ap_on,
                    "auto_mode_enabled": ap_on,
                    "selected_auto_location": self.get_selected_auto_location(),
                    "gemini_ready": False,
                    "egress_country_code": "",
                    "egress_country": "",
                    "destination_label": "---",
                    "status_detail": stages[self._connect_step],
                    "active_vector_id": str(prof.get("cached_vector_id") or "VEC-01"),
                    "egress_ip": "---",
                    "ping_ms": 0,
                    "rx_rate_kbps": 0.0,
                    "tx_rate_kbps": 0.0,
                    "uptime_label": "00:00:00",
                }
            )
            self._connect_step += 1
        else:
            self._connect_timer.stop()
            self._phase = "CONNECTED"
            self._connected_since = time.monotonic()
            if tun_en:
                self.tun_status_changed.emit(True, True, "Wintun tunnel active")
            self._emit_log(
                f"Tunnel ONLINE -> {prof.get('host', '91.107.142.11')} via {prof.get('cached_vector_id', 'VEC-01')}"
            )
            self._step_metrics()

    def _step_metrics(self) -> None:
        if self._phase != "CONNECTED":
            return
        prof = self._active_profile()
        egress = str(prof.get("host") or "91.107.142.11")
        cc = GeoFlagResolver.resolve_code(prof) or infer_country_from_ipv4(egress) or "DE"
        spec = GeoFlagResolver.get_spec(cc)
        cname = spec.localized_name()
        dest_lbl = f"{cname} ({spec.code})" if spec.code else "---"

        vec = str(prof.get("cached_vector_id") or "VEC-01")
        ap_on = bool(self._settings.get("autopilot_enabled", True))
        if not ap_on:
            manual_v = str(self._settings.get("manual_vector_id") or "AUTO")
            if manual_v != "AUTO":
                vec = manual_v
        elapsed = int(time.monotonic() - (self._connected_since or time.monotonic()))
        quiet = random.random() < 0.18
        rx = 0.0 if quiet else round(random.uniform(240.0, 4200.0), 1)
        tx = 0.0 if quiet else round(random.uniform(48.0, 760.0), 1)
        base_p = get_int(prof, "ping_ms", 44) or 44
        ping = max(18, base_p + random.randint(-4, 5))
        gem_ready = is_gemini_verified(prof)
        tun_en = bool(self._settings.get("tun_enabled", False))

        self.telemetry_updated.emit(
            {
                "ui_phase": "CONNECTED",
                "state": "connected",
                "is_connecting": False,
                "is_connected": True,
                "tun_enabled": tun_en,
                "tun_badge": "ON" if tun_en else "OFF",
                "autopilot_enabled": ap_on,
                "auto_mode_enabled": ap_on,
                "selected_auto_location": self.get_selected_auto_location(),
                "selected_index": self.get_selected_index(),
                "active_profile_uid": extract_profile_uid(prof, 0),
                "egress_ip": egress,
                "egress_country_code": spec.code,
                "egress_country": cname,
                "destination_label": dest_lbl,
                "gemini_ready": gem_ready,
                "gemini_ok": gem_ready,
                "active_vector_id": vec,
                "status_detail": f"{prof.get('name', 'Active Node')} | {vec} | Watchdog Active",
                "ping_ms": ping,
                "rx_rate_kbps": rx,
                "tx_rate_kbps": tx,
                "rx_rate_label": format_rate_kbps(rx),
                "tx_rate_label": format_rate_kbps(tx),
                "uptime_label": format_uptime_hms(elapsed),
            }
        )


class BrandLogoWidget(QWidget):
    def __init__(self, logo_path: str = "assets/logo.png", size: int = 36, parent=None):
        super().__init__(parent)
        self._logo_path = logo_path
        self._palette: ThemePalette = DARK_PALETTE
        lock_widget_dimensions(self, size, size)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        well = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        draw_neu_inset(painter, well, 10.0, self._palette, depth=2.8)
        VectorIconPainter.draw_brand_logo(
            painter,
            QRectF(5.5, 5.5, self.width() - 11.0, self.height() - 11.0),
            self._logo_path,
        )


class TopBrandHeaderBar(NeuCard):
    language_toggle_clicked = Signal()
    theme_toggle_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(mode="raised", radius=16.0, depth=4.6, pad=5.0, parent=parent)
        self.setMinimumHeight(58)
        self.setMaximumHeight(62)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 8, 18, 8)
        row.setSpacing(10)

        self.logo = BrandLogoWidget("assets/logo.png", size=36)
        self.brand_lbl = QLabel("Alan-RIP-Dpi")
        enforce_english_ltr(self.brand_lbl, mono_size=12, bold=True)

        self.ver_badge = QLabel("v1.1.0")
        self.ver_badge.setObjectName("BadgePill")
        enforce_english_ltr(self.ver_badge, mono_size=9, bold=True)

        self.origin_flag = FlagBadgeWidget("IR", width=28, height=19)
        self.origin_lbl = QLabel(I18N.t("local_node_ir"))
        self.origin_lbl.setObjectName("MutedLabel")
        self.origin_lbl.setFont(make_ui_font(9, QFont.Weight.DemiBold))

        self.lang_btn = QPushButton("EN | FA")
        self.lang_btn.setObjectName("LangPillBtn")
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.setToolTip(I18N.t("lang_toggle_tip"))
        enforce_english_ltr(self.lang_btn, mono_size=9, bold=True)
        self.lang_btn.clicked.connect(self.language_toggle_clicked.emit)

        self.theme_btn = VectorIconButton("sun", size=34)
        self.theme_btn.setToolTip(I18N.t("theme_toggle_tip"))
        self.theme_btn.clicked.connect(self.theme_toggle_clicked.emit)

        row.addWidget(self.logo)
        row.addWidget(self.brand_lbl)
        row.addWidget(self.ver_badge)
        row.addStretch()
        row.addWidget(self.origin_lbl)
        row.addWidget(self.origin_flag)
        row.addSpacing(6)
        row.addWidget(self.lang_btn)
        row.addWidget(self.theme_btn)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.origin_lbl.setText(I18N.t("local_node_ir"))
        self.origin_lbl.setFont(make_ui_font(9, QFont.Weight.DemiBold))
        self.origin_flag.set_country_code("IR")
        self.lang_btn.setText("FA" if I18N.lang == "en" else "EN")
        self.lang_btn.setToolTip(I18N.t("lang_toggle_tip"))
        self.theme_btn.setToolTip(I18N.t("theme_toggle_tip"))

    def set_palette_theme(self, palette: ThemePalette) -> None:
        super().set_palette_theme(palette)
        self.logo.set_palette_theme(palette)
        self.origin_flag.set_palette_theme(palette)
        self.theme_btn.set_icon_name("sun" if palette.is_dark else "moon")
        self.theme_btn.set_palette_theme(palette)


class AlanMainWindow(QMainWindow):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        load_application_fonts()

        self._palette: ThemePalette = DARK_PALETTE
        self._force_quit = False
        self._quit_dispatched = False
        self._tray_notified_once = False
        self._tun_signal_received = False
        self._is_connecting = False
        self._is_connected = False
        self._selected_index = -1
        self._profiles_cache: list[dict] = []
        self._verified_cache: list[dict] = []
        self._subscriptions_cache: list = []
        self._vectors_cache: list = []
        self._fingerprints_cache: list = []
        self._settings_cache: dict = {
            "minimize_to_tray": True,
            "system_proxy": True,
            "tun_enabled": False,
            "tun_badge": "OFF",
            "autopilot": True,
            "autopilot_enabled": True,
            "auto_mode_enabled": True,
            "selected_auto_location": "ALL",
            "fingerprint": "custom_poly",
            "routing_mode": "bypass_ir",
            "sub_auto_update_hours": 6,
        }
        self._sub_dialog: SubscriptionManagerDialog | None = None

        self.controller = controller if (controller is not None) else DemoDpiController(self)

        self.setWindowTitle("Alan-RIP-Dpi")
        self.setWindowIcon(VectorIconPainter.build_tray_icon("IDLE", "assets/logo.png"))
        self.setLayoutDirection(I18N.layout_direction())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setMinimumSize(1120, 680)
        self.resize(1280, 790)

        self.shell = QFrame()
        self.shell.setObjectName("MainShell")
        shell_vbox = QVBoxLayout(self.shell)
        shell_vbox.setContentsMargins(12, 8, 12, 8)
        shell_vbox.setSpacing(6)

        self.header_bar = TopBrandHeaderBar(self.shell)
        self.header_bar.language_toggle_clicked.connect(self.toggle_language)
        self.header_bar.theme_toggle_clicked.connect(self.toggle_theme)
        shell_vbox.addWidget(self.header_bar)

        self.global_task_strip = GlobalTaskStrip(self.shell)
        self.global_task_strip.stop_requested.connect(lambda: self._call_ctrl("stop_scanner"))
        shell_vbox.addWidget(self.global_task_strip)

        body_hbox = QHBoxLayout()
        body_hbox.setContentsMargins(0, 2, 0, 2)
        body_hbox.setSpacing(0)

        self.nav_rail = NeuCard(mode="raised", radius=20.0, depth=5.0, pad=5.5, parent=self.shell)
        self.nav_rail.setFixedWidth(98)
        rail_vbox = QVBoxLayout(self.nav_rail)
        rail_vbox.setContentsMargins(8, 14, 8, 14)
        rail_vbox.setSpacing(8)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_home = NavRailButton("home", "nav_home")
        self.btn_configs = NavRailButton("configs", "nav_configs")
        self.btn_lab = NavRailButton("lab", "nav_lab")
        self.btn_routing = NavRailButton("routing", "nav_routing")
        self.btn_logs = NavRailButton("logs", "nav_logs")

        self._nav_buttons = (
            self.btn_home,
            self.btn_configs,
            self.btn_lab,
            self.btn_routing,
            self.btn_logs,
        )
        for idx, btn in enumerate(self._nav_buttons):
            self.nav_group.addButton(btn, idx)
            rail_vbox.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        rail_vbox.addStretch()

        self.pages = QStackedWidget()
        self.home_page = HomePage()
        self.configs_page = ConfigsPage()
        self.lab_page = LabPage()
        self.routing_page = RoutingSettingsPage()
        self.logs_page = LogsPage()

        for pg in (
            self.home_page,
            self.configs_page,
            self.lab_page,
            self.routing_page,
            self.logs_page,
        ):
            self.pages.addWidget(pg)

        self.btn_home.setChecked(True)
        self.nav_group.idClicked.connect(self.pages.setCurrentIndex)

        body_hbox.addWidget(self.nav_rail)
        body_hbox.addWidget(self.pages, 1)
        shell_vbox.addLayout(body_hbox, 1)
        self.setCentralWidget(self.shell)

        self._setup_system_tray()
        I18N.language_changed.connect(self._on_language_changed)

        self._wire_pages_and_controller()
        self._hydrate_from_controller()
        self.apply_theme(DARK_PALETTE)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_windows_titlebar_theme(self, self._palette.is_dark)

    def _setup_system_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(
            VectorIconPainter.build_tray_icon("IDLE", "assets/logo.png"),
            self,
        )
        self.tray_icon.setToolTip("Alan-RIP-Dpi v1.1.0")

        self.tray_menu = QMenu(self)
        self.act_tray_conn = QAction(I18N.t("tray_connect"), self)
        self.act_tray_conn.triggered.connect(self._on_tray_toggle_connect)

        self.act_tray_proxy = QAction(I18N.t("tray_sys_proxy"), self)
        self.act_tray_proxy.setCheckable(True)
        self.act_tray_proxy.setChecked(True)
        self.act_tray_proxy.toggled.connect(self._handle_system_proxy_toggled)

        self.act_tray_tun = QAction(I18N.t("tray_tun_mode"), self)
        self.act_tray_tun.setCheckable(True)
        self.act_tray_tun.setChecked(False)
        self.act_tray_tun.toggled.connect(self._handle_tun_mode_toggled)

        self.act_tray_open = QAction(I18N.t("tray_open"), self)
        self.act_tray_open.triggered.connect(self.restore_from_tray)

        self.act_tray_exit = QAction(I18N.t("tray_exit"), self)
        self.act_tray_exit.triggered.connect(self.exit_completely)

        self.tray_menu.addAction(self.act_tray_conn)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.act_tray_proxy)
        self.tray_menu.addAction(self.act_tray_tun)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.act_tray_open)
        self.tray_menu.addAction(self.act_tray_exit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _sync_tray_state(self, phase: str = "IDLE") -> None:
        is_busy = self._is_connecting or self._is_connected
        self.act_tray_conn.setText(I18N.t("tray_disconnect") if is_busy else I18N.t("tray_connect"))

        with QSignalBlocker(self.act_tray_proxy):
            self.act_tray_proxy.setChecked(get_bool(self._settings_cache, "system_proxy", True))

        with QSignalBlocker(self.act_tray_tun):
            self.act_tray_tun.setChecked(bool(self._settings_cache.get("tun_enabled", False)))

        icon = VectorIconPainter.build_tray_icon(phase, "assets/logo.png")
        self.tray_icon.setIcon(icon)
        self.setWindowIcon(icon)

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def _on_tray_toggle_connect(self) -> None:
        if self._is_connecting or self._is_connected:
            self._handle_disconnect_request()
        else:
            self._handle_home_connect(self.home_page.selected_output_key())

    def restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _dispatch_backend_quit_once(self) -> None:
        if self._quit_dispatched:
            return
        self._quit_dispatched = True
        quit_fn = getattr(self.controller, "quit_application", None)
        if callable(quit_fn):
            quit_fn()
        elif self._is_connecting or self._is_connected:
            self._call_ctrl("request_disconnect")

    def exit_completely(self) -> None:
        self._force_quit = True
        self.tray_icon.hide()
        self._dispatch_backend_quit_once()
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            self.close()

    def closeEvent(self, event) -> None:
        min_to_tray = get_bool(self._settings_cache, "minimize_to_tray", True)
        if (not self._force_quit) and min_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            if not self._tray_notified_once:
                self._tray_notified_once = True
                self.tray_icon.showMessage(
                    "Alan-RIP-Dpi",
                    I18N.t("tray_minimized_msg"),
                    QSystemTrayIcon.MessageIcon.Information,
                    2200,
                )
            return
        self.tray_icon.hide()
        self._dispatch_backend_quit_once()
        super().closeEvent(event)

    def _call_ctrl(self, method_name: str, *args, **kwargs):
        fn = getattr(self.controller, method_name, None)
        if callable(fn):
            return fn(*args, **kwargs)
        return None

    def _wire_pages_and_controller(self) -> None:
        self.home_page.connect_triggered.connect(self._handle_home_connect)
        self.home_page.disconnect_triggered.connect(self._handle_disconnect_request)
        self.home_page.output_selection_changed.connect(self._handle_home_output_selected)
        self.home_page.auto_location_changed.connect(self._handle_auto_location_changed)
        self.home_page.refresh_auto_pool_requested.connect(self._handle_refresh_auto_pool)
        self.home_page.ping_verified_requested.connect(lambda: self._call_ctrl("ping_verified_outputs"))
        self.home_page.clear_verified_requested.connect(self._handle_clear_verified)
        self.home_page.system_proxy_toggled.connect(self._handle_system_proxy_toggled)
        self.home_page.tun_mode_toggled.connect(self._handle_tun_mode_toggled)
        self.home_page.autopilot_toggled.connect(self._handle_autopilot_toggled)

        self.configs_page.select_active_requested.connect(self._handle_vault_select_active)
        self.configs_page.import_clipboard_requested.connect(self._handle_import_clipboard)
        self.configs_page.new_config_requested.connect(self._open_new_config_dialog)
        self.configs_page.edit_config_requested.connect(self._open_edit_config_dialog)
        self.configs_page.delete_configs_requested.connect(self._handle_delete_configs)
        self.configs_page.ping_configs_requested.connect(lambda uids: self._call_ctrl("ping_configs", uids))
        self.configs_page.probe_gemini_requested.connect(lambda uids: self._call_ctrl("probe_gemini_configs", uids))
        self.configs_page.sort_requested.connect(lambda by: self._call_ctrl("sort_configs", by))
        self.configs_page.dedup_requested.connect(lambda: self._call_ctrl("deduplicate_configs"))
        self.configs_page.remove_dead_requested.connect(lambda: self._call_ctrl("remove_dead_configs"))
        self.configs_page.export_verified_requested.connect(self._handle_export_verified)
        self.configs_page.send_batch_to_lab_requested.connect(self._route_batch_to_lab)
        self.configs_page.manage_subs_requested.connect(self._open_subs_dialog)
        self.configs_page.hunt_subscription_requested.connect(self._handle_hunt_subscription_and_connect)

        self.lab_page.start_lab_scan_requested.connect(self._handle_start_lab_scan)
        self.lab_page.start_clean_ip_requested.connect(lambda port: self._call_ctrl("start_clean_ip_scan", port))
        self.lab_page.stop_scanner_requested.connect(lambda: self._call_ctrl("stop_scanner"))
        self.lab_page.connect_winner_requested.connect(self._handle_connect_lab_winner)
        self.lab_page.apply_clean_ip_requested.connect(
            lambda ip, all_cdn: self._call_ctrl("apply_clean_ip", ip, all_cdn)
        )
        self.lab_page.go_home_requested.connect(self._switch_to_home_tab)

        self.routing_page.setting_key_changed.connect(self._handle_single_setting)
        self.routing_page.settings_changed.connect(self._handle_bulk_settings)

        signal_bindings = [
            (("telemetry_updated",), self.on_telemetry_update),
            (("log_message", "log_emitted"), self.on_log_message),
            (("profiles_updated", "profiles_changed"), self.on_profiles_updated),
            (("verified_outputs_updated", "verified_outputs_changed"), self.on_verified_outputs_updated),
            (("auto_locations_updated", "auto_locations_changed"), self.on_auto_locations_updated),
            (("settings_updated", "settings_changed"), self.on_settings_updated),
            (("subscriptions_updated", "subscriptions_changed"), self.on_subscriptions_updated),
            (("scan_row", "scan_row_emitted"), self.on_scan_row),
            (("scan_results_ranked",), self.on_scan_results_ranked),
            (("scan_progress", "scan_progress_updated"), self.on_scan_progress),
            (("scan_state_changed",), self.on_scan_state_changed),
            (("task_progress", "task_progress_updated"), self.on_task_progress),
            (("tun_status_changed", "tun_state_changed"), self.on_tun_status_changed),
        ]
        for names, slot in signal_bindings:
            for attr in names:
                sig = getattr(self.controller, attr, None)
                if sig is not None and hasattr(sig, "connect"):
                    try:
                        sig.connect(slot, Qt.ConnectionType.UniqueConnection)
                    except (TypeError, RuntimeError):
                        pass
                    break

    def _hydrate_from_controller(self) -> None:
        vectors = self._call_ctrl("get_vectors")
        if isinstance(vectors, list):
            self._vectors_cache = list(vectors)
            self.lab_page.set_vectors(self._vectors_cache)
            self.routing_page.set_vectors(self._vectors_cache)

        fingerprints = self._call_ctrl("get_fingerprints")
        if isinstance(fingerprints, list):
            self._fingerprints_cache = list(fingerprints)
            self.routing_page.set_fingerprints(self._fingerprints_cache)

        subs = self._call_ctrl("get_subscriptions")
        if isinstance(subs, list):
            self.on_subscriptions_updated(subs)

        sel_idx = self._call_ctrl("get_selected_index")
        init_sel = int(sel_idx) if isinstance(sel_idx, int) else -1

        profiles = self._call_ctrl("get_profiles")
        if isinstance(profiles, list):
            self.on_profiles_updated(profiles, init_sel)

        verified = self._call_ctrl("get_verified_outputs")
        if isinstance(verified, list):
            self.on_verified_outputs_updated(verified)

        auto_locs = self._call_ctrl("get_auto_locations")
        sel_auto_loc = self._call_ctrl("get_selected_auto_location")
        if isinstance(auto_locs, list):
            self.on_auto_locations_updated(
                auto_locs,
                str(sel_auto_loc or "ALL"),
            )

        raw_settings = coerce_dict(self._call_ctrl("get_settings"))
        if raw_settings:
            lang_pref = str(raw_settings.get("ui_language") or raw_settings.get("language") or "")
            if lang_pref:
                I18N.set_language(lang_pref)
            self.on_settings_updated(raw_settings)

        snap = self._call_ctrl("get_telemetry_snapshot")
        if isinstance(snap, dict):
            self.on_telemetry_update(snap)

    def _switch_to_home_tab(self) -> None:
        self.pages.setCurrentIndex(0)
        self.btn_home.setChecked(True)

    def _handle_auto_location_changed(self, code: str) -> None:
        norm = str(code or "ALL").strip().upper()
        self._settings_cache["selected_auto_location"] = norm
        fn = getattr(self.controller, "set_auto_location", None)
        if callable(fn):
            fn(norm)
        else:
            self._handle_single_setting("selected_auto_location", norm)

    def _handle_refresh_auto_pool(self) -> None:
        fn = getattr(self.controller, "refresh_auto_pool", None)
        if callable(fn):
            fn()

    def _handle_hunt_subscription_and_connect(self, sub_url_or_title: str, title: str = "") -> None:
        target = str(sub_url_or_title or "").strip()
        if not target:
            return
        self._switch_to_home_tab()
        fn = getattr(self.controller, "hunt_subscription_and_connect", None)
        if callable(fn):
            try:
                fn(target, title)
            except TypeError:
                fn(target)

    def _handle_home_connect(self, output_key: str) -> None:
        if output_key and output_key not in (HomePage.SMART_AUTO_KEY, "__smart_pool__"):
            self._call_ctrl("select_config", output_key)
            conn_ver = getattr(self.controller, "connect_verified_output", None)
            if callable(conn_ver):
                conn_ver(output_key)
                return

        ap_on = get_bool(
            self._settings_cache,
            "auto_mode_enabled",
            get_bool(
                self._settings_cache,
                "autopilot_enabled",
                get_bool(self._settings_cache, "autopilot", True),
            ),
        )
        hunt_fn = getattr(self.controller, "hunt_best_and_connect", None)
        toggle_fn = getattr(self.controller, "toggle_connection", None)
        req_fn = getattr(self.controller, "request_connect", None)

        if ap_on and (not self._verified_cache) and callable(hunt_fn):
            hunt_fn()
        elif callable(req_fn):
            try:
                req_fn("")
            except TypeError:
                req_fn()
        elif callable(toggle_fn):
            toggle_fn()

    def _handle_disconnect_request(self) -> None:
        disc_fn = getattr(self.controller, "request_disconnect", None)
        if callable(disc_fn):
            disc_fn()
        else:
            self._call_ctrl("toggle_connection")

    def _handle_home_output_selected(self, output_key: str) -> None:
        if not output_key or output_key in (HomePage.SMART_AUTO_KEY, "__smart_pool__"):
            self._handle_autopilot_toggled(True)
            return
        self._settings_cache["auto_mode_enabled"] = False
        self._settings_cache["autopilot_enabled"] = False
        self._settings_cache["autopilot"] = False
        self._settings_cache["active_profile_uid"] = str(output_key)
        self._call_ctrl("select_config", output_key)

    def _handle_vault_select_active(self, index_or_uid) -> None:
        self._call_ctrl("select_config", index_or_uid)

    def _handle_autopilot_toggled(self, enabled: bool) -> None:
        state = bool(enabled)
        self._settings_cache["auto_mode_enabled"] = state
        self._settings_cache["autopilot_enabled"] = state
        self._settings_cache["autopilot"] = state
        if not state:
            cur_out = self.home_page.selected_output_key()
            if cur_out and cur_out not in (HomePage.SMART_AUTO_KEY, "__smart_pool__"):
                self._settings_cache["active_profile_uid"] = cur_out
        self.home_page.sync_autopilot_state(
            state,
            str(self._settings_cache.get("active_profile_uid") or ""),
        )
        fn = getattr(self.controller, "set_setting_value", None)
        if callable(fn):
            fn("autopilot_enabled", state)
        else:
            self._call_ctrl(
                "update_settings",
                {
                    "auto_mode_enabled": state,
                    "autopilot_enabled": state,
                    "autopilot": state,
                },
            )

    def _handle_clear_verified(self) -> None:
        self._verified_cache.clear()
        self._call_ctrl("clear_verified_outputs")
        self.home_page.set_verified_outputs([])
        self.btn_home.set_badge_count(0)

    def _handle_system_proxy_toggled(self, enabled: bool) -> None:
        state = bool(enabled)
        self._settings_cache["system_proxy"] = state
        set_switch_blocked(self.home_page.sw_sys_proxy, state)
        fn = getattr(self.controller, "set_system_proxy", None)
        if callable(fn):
            fn(state)
        else:
            self._handle_single_setting("system_proxy", state)
        self._sync_tray_state()

    def _handle_tun_mode_toggled(self, enabled: bool) -> None:
        self._tun_signal_received = False
        fn = getattr(self.controller, "set_tun_mode", None)
        if callable(fn):
            res = fn(bool(enabled))
            if not self._tun_signal_received:
                latest_settings = coerce_dict(self._call_ctrl("get_settings"))
                if "tun_enabled" in latest_settings:
                    actual_tun = bool(latest_settings.get("tun_enabled"))
                    tun_badge = str(latest_settings.get("tun_badge") or ("ON" if actual_tun else "OFF"))
                elif isinstance(res, bool):
                    actual_tun = res
                    tun_badge = "ON" if actual_tun else "OFF"
                else:
                    actual_tun = bool(self._settings_cache.get("tun_enabled", False))
                    tun_badge = str(self._settings_cache.get("tun_badge") or ("ON" if actual_tun else "OFF"))
                self._settings_cache["tun_enabled"] = actual_tun
                self._settings_cache["tun_badge"] = tun_badge
                self.home_page.apply_tun_status(
                    actual_tun,
                    actual_tun and self._is_connected,
                    "",
                    tun_badge,
                )
        else:
            state = bool(enabled)
            self._handle_single_setting("tun_enabled", state)
            self.home_page.apply_tun_status(
                state,
                state and self._is_connected,
                "",
                "ON" if state else "OFF",
            )
        self._sync_tray_state()

    def _handle_single_setting(self, key: str, value) -> None:
        self._settings_cache[key] = value
        if key == "sub_auto_update_hours":
            self.routing_page.set_sub_auto_update_hours_silent(int(value or 0))
        fn = getattr(self.controller, "set_setting_value", None)
        if callable(fn):
            fn(key, value)
        else:
            self._call_ctrl("update_settings", {key: value})

    def _handle_bulk_settings(self, page_dict: dict) -> None:
        merged = dict(self._settings_cache)
        merged.update(page_dict)
        merged["system_proxy"] = bool(self.home_page.sw_sys_proxy.isChecked())
        merged["tun_enabled"] = bool(self.home_page.sw_tun.isChecked())
        ap_state = bool(self.home_page.sw_autopilot.isChecked())
        merged["auto_mode_enabled"] = ap_state
        merged["autopilot_enabled"] = ap_state
        merged["autopilot"] = ap_state
        self._settings_cache = merged
        self._call_ctrl("update_settings", merged)

    def _handle_import_clipboard(self, raw_text: str, group_tag: str) -> None:
        fn = getattr(self.controller, "import_configs", None)
        if callable(fn):
            try:
                fn(raw_text, group_tag=group_tag)
            except TypeError:
                fn(raw_text)

    def _refresh_catalogs_if_needed(self) -> None:
        if not self._vectors_cache:
            vectors = self._call_ctrl("get_vectors")
            if isinstance(vectors, list):
                self._vectors_cache = list(vectors)
                self.lab_page.set_vectors(self._vectors_cache)
                self.routing_page.set_vectors(self._vectors_cache)
        if not self._fingerprints_cache:
            fps = self._call_ctrl("get_fingerprints")
            if isinstance(fps, list):
                self._fingerprints_cache = list(fps)
                self.routing_page.set_fingerprints(self._fingerprints_cache)

    def _open_new_config_dialog(self, group_tag: str) -> None:
        self._refresh_catalogs_if_needed()
        dlg = ConfigEditorDialog(
            is_new=True,
            initial_data={
                "group": group_tag,
                "port": 443,
                "protocol": "vless",
                "fingerprint": "custom_poly",
            },
            vectors=self._vectors_cache,
            groups=self.configs_page.known_group_names(),
            palette=self._palette,
            parent=self,
            fingerprints=self._fingerprints_cache,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._call_ctrl("save_config_editable", -1, dlg.collect_data())

    def _open_edit_config_dialog(self, index_or_uid) -> None:
        self._refresh_catalogs_if_needed()
        data = self._call_ctrl("get_config_editable", index_or_uid)
        if not isinstance(data, dict):
            data = {}
        dlg = ConfigEditorDialog(
            is_new=False,
            initial_data=data,
            vectors=self._vectors_cache,
            groups=self.configs_page.known_group_names(),
            palette=self._palette,
            parent=self,
            fingerprints=self._fingerprints_cache,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._call_ctrl("save_config_editable", index_or_uid, dlg.collect_data())

    def _handle_delete_configs(self, uid_list: list) -> None:
        batch_fn = getattr(self.controller, "delete_configs", None)
        if callable(batch_fn):
            batch_fn(uid_list)
        else:
            for uid in uid_list:
                self._call_ctrl("delete_config", uid)

    def _handle_export_verified(self) -> None:
        fn = getattr(self.controller, "export_configs", None)
        if not callable(fn):
            return
        try:
            res = fn(mode="verified", inject_early_data=2048)
        except TypeError:
            res = fn("verified", 2048)
        txt = "\n".join(res) if isinstance(res, list) else str(res or "")
        if txt.strip():
            QGuiApplication.clipboard().setText(txt.strip())

    def _route_batch_to_lab(self, uid_list: list, group_tag: str) -> None:
        self.lab_page.receive_vault_batch(uid_list, group_tag)
        self.pages.setCurrentIndex(2)
        self.btn_lab.setChecked(True)

    def _open_subs_dialog(self) -> None:
        hrs = get_int(self._settings_cache, "sub_auto_update_hours", 6)
        dlg = SubscriptionManagerDialog(
            subscriptions=self._subscriptions_cache,
            auto_update_hours=hrs,
            palette=self._palette,
            parent=self,
        )
        self._sub_dialog = dlg
        dlg.add_requested.connect(lambda url, title: self._call_ctrl("add_subscription", url, title))
        dlg.refresh_requested.connect(lambda: self._call_ctrl("refresh_subscriptions"))
        dlg.delete_requested.connect(lambda idx: self._call_ctrl("delete_subscription", idx))
        dlg.auto_update_hours_changed.connect(
            lambda h: self._handle_single_setting("sub_auto_update_hours", int(h))
        )
        dlg.hunt_subscription_requested.connect(self._handle_hunt_subscription_and_connect)
        dlg.exec()
        self._sub_dialog = None

    def _handle_start_lab_scan(
        self,
        scope: str,
        uid_list: list,
        group_tag: str,
        target_vector: str,
        check_gemini: bool,
        auto_connect: bool,
    ) -> None:
        fn = getattr(self.controller, "start_lab_scan", None)
        if callable(fn):
            fn(
                scope=scope,
                uid_list=uid_list,
                group_tag=group_tag,
                target_vector=target_vector,
                check_gemini=check_gemini,
                auto_connect=auto_connect,
            )

    def _handle_connect_lab_winner(self, vector_id: str, target_uid: str) -> None:
        self._call_ctrl("apply_scanned_vector", vector_id, target_uid, True)
        self._switch_to_home_tab()

    @Slot(list)
    @Slot(list, str)
    def on_auto_locations_updated(self, locations: list, selected_code: str = "") -> None:
        code = str(selected_code or "").strip().upper()
        if not code:
            ctrl_code = self._call_ctrl("get_selected_auto_location")
            code = str(ctrl_code or self._settings_cache.get("selected_auto_location") or "ALL").strip().upper()
        self._settings_cache["selected_auto_location"] = code
        self.home_page.on_auto_locations_updated(
            locations if isinstance(locations, list) else [],
            code,
        )

    @Slot(dict)
    def on_telemetry_update(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            return
        enriched = dict(snapshot)

        raw_phase = str(enriched.get("ui_phase") or "").upper()
        raw_state = str(enriched.get("state") or "disconnected").lower()
        self._is_connecting = get_bool(
            enriched,
            "is_connecting",
            (raw_phase == "CONNECTING") or (raw_state in ("connecting", "probing", "scanning")),
        )
        self._is_connected = get_bool(
            enriched,
            "is_connected",
            (raw_phase == "CONNECTED") or (raw_state in ("connected", "online", "active")),
        )

        if self._is_connected and not str(enriched.get("egress_country_code") or "").strip():
            inferred_cc = infer_country_from_ipv4(str(enriched.get("egress_ip") or ""))
            if inferred_cc:
                spec = GeoFlagResolver.get_spec(inferred_cc)
                enriched["egress_country_code"] = spec.code
                if not str(enriched.get("egress_country") or "").strip():
                    enriched["egress_country"] = spec.localized_name()
                if not str(enriched.get("destination_label") or "").strip():
                    enriched["destination_label"] = f"{spec.localized_name()} ({spec.code})"

        if ("tun_enabled" in enriched) or ("tun_badge" in enriched):
            self._tun_signal_received = True
            tun_en = bool(enriched.get("tun_enabled"))
            tun_b = str(enriched.get("tun_badge") or ("ON" if tun_en else "OFF"))
            self._settings_cache["tun_enabled"] = tun_en
            self._settings_cache["tun_badge"] = tun_b

        if ("auto_mode_enabled" in enriched) or ("autopilot_enabled" in enriched):
            ap_key = "auto_mode_enabled" if ("auto_mode_enabled" in enriched) else "autopilot_enabled"
            ap_val = bool(enriched.get(ap_key))
            self._settings_cache["auto_mode_enabled"] = ap_val
            self._settings_cache["autopilot_enabled"] = ap_val
            self._settings_cache["autopilot"] = ap_val

        phase_key = "CONNECTING" if self._is_connecting else ("CONNECTED" if self._is_connected else "IDLE")
        self._sync_tray_state(phase_key)
        self.home_page.apply_telemetry(enriched)

    @Slot(str)
    def on_log_message(self, line: str) -> None:
        self.logs_page.append_line(str(line))

    @Slot(list)
    @Slot(list, int)
    def on_profiles_updated(self, profiles: list, selected_index: int = -1) -> None:
        normalized: list[dict] = []
        detected_sel = selected_index if isinstance(selected_index, int) else -1

        for idx, item in enumerate(profiles or []):
            d = dict(item) if isinstance(item, dict) else coerce_dict(item)
            if (detected_sel < 0) and get_bool(d, "is_selected", False):
                detected_sel = idx
            normalized.append(d)

        if detected_sel < 0 and normalized:
            ctrl_sel = self._call_ctrl("get_selected_index")
            if isinstance(ctrl_sel, int) and 0 <= ctrl_sel < len(normalized):
                detected_sel = ctrl_sel

        self._profiles_cache = normalized
        self._selected_index = detected_sel
        if 0 <= detected_sel < len(normalized):
            self._settings_cache["active_profile_uid"] = extract_profile_uid(normalized[detected_sel], detected_sel)

        self.btn_configs.set_badge_count(len(normalized))
        self.home_page.set_vault_profiles_context(normalized, detected_sel)
        self.configs_page.set_profiles(normalized, detected_sel)
        self.lab_page.set_profiles_and_groups(
            normalized,
            self.configs_page.known_group_names(),
            detected_sel,
        )

    @Slot(list)
    def on_verified_outputs_updated(self, outputs: list) -> None:
        normalized = [dict(x) if isinstance(x, dict) else coerce_dict(x) for x in (outputs or [])]
        self._verified_cache = normalized
        self.btn_home.set_badge_count(len(normalized))
        self.home_page.set_verified_outputs(normalized)

    @Slot(dict)
    def on_settings_updated(self, settings: dict) -> None:
        parsed = coerce_dict(settings)
        if not parsed:
            return
        if ("tun_enabled" in parsed) or ("tun_badge" in parsed):
            self._tun_signal_received = True
        if ("auto_mode_enabled" in parsed) and ("autopilot_enabled" not in parsed):
            parsed["autopilot_enabled"] = bool(parsed["auto_mode_enabled"])
            parsed["autopilot"] = bool(parsed["auto_mode_enabled"])
        elif ("autopilot_enabled" in parsed) and ("autopilot" not in parsed):
            parsed["autopilot"] = bool(parsed["autopilot_enabled"])
            parsed["auto_mode_enabled"] = bool(parsed["autopilot_enabled"])
        elif ("autopilot" in parsed) and ("autopilot_enabled" not in parsed):
            parsed["autopilot_enabled"] = bool(parsed["autopilot"])
            parsed["auto_mode_enabled"] = bool(parsed["autopilot"])

        cur_out = self.home_page.selected_output_key()
        if (
            not bool(parsed.get("autopilot_enabled", self._settings_cache.get("autopilot_enabled", True)))
            and ("active_profile_uid" not in parsed)
            and cur_out
            and cur_out not in (HomePage.SMART_AUTO_KEY, "__smart_pool__")
        ):
            parsed["active_profile_uid"] = cur_out

        self._settings_cache.update(parsed)
        self.home_page.sync_switches(self._settings_cache)
        self.routing_page.apply_settings(self._settings_cache)
        self._sync_tray_state()

    @Slot(list)
    def on_subscriptions_updated(self, subs: list) -> None:
        self._subscriptions_cache = list(subs or [])
        self.configs_page.set_subscriptions(self._subscriptions_cache)
        self.lab_page.set_profiles_and_groups(
            self._profiles_cache,
            self.configs_page.known_group_names(),
            self._selected_index,
        )
        if self._sub_dialog is not None:
            self._sub_dialog.populate_subscriptions(self._subscriptions_cache)

    @Slot(dict)
    def on_scan_row(self, row: dict) -> None:
        if not isinstance(row, dict):
            return
        self.lab_page.append_scan_row(row)

        if LabPage._is_verified_row(row) and str(row.get("scan_type") or "").lower() not in (
            "clean_ip",
            "clean_ip_radar",
            "radar",
        ):
            ver_getter = getattr(self.controller, "get_verified_outputs", None)
            if callable(ver_getter):
                latest = ver_getter()
                if isinstance(latest, list):
                    self.on_verified_outputs_updated(latest)
            else:
                uid = str(row.get("target_uid") or row.get("uid") or row.get("item_id") or "")
                gem_ok = is_gemini_verified(row)
                entry = {
                    "uid": uid,
                    "name": row.get("title") or row.get("profile_name") or "Verified Output",
                    "country_code": GeoFlagResolver.resolve_code(row),
                    "protocol": str(row.get("protocol") or "VLESS").upper(),
                    "vector_id": str(row.get("vector_id") or row.get("bound_vector") or "AUTO"),
                    "ping_ms": get_int(row, "tunnel_ms", get_int(row, "ping_ms", 0)),
                    "gemini_ok": gem_ok,
                    "gemini_status": "OK" if gem_ok else "",
                }
                existing_uids = {str(x.get("uid")) for x in self._verified_cache}
                if uid and uid not in existing_uids:
                    self._verified_cache.append(entry)
                    self.on_verified_outputs_updated(self._verified_cache)

    @Slot(list)
    def on_scan_results_ranked(self, rows: list) -> None:
        if isinstance(rows, list):
            self.lab_page.apply_ranked_rows(rows)

    @Slot(int, str)
    def on_scan_progress(self, percent: int, summary: str) -> None:
        if summary:
            self.lab_page.sub_lbl.setText(strip_emojis(summary))
        if percent < 100:
            self.global_task_strip.update_task_state(True, percent, summary)

    @Slot(bool)
    @Slot(bool, str)
    def on_scan_state_changed(self, is_running: bool, mode: str = "") -> None:
        self.lab_page.update_scan_state(bool(is_running), str(mode or ""))
        if not is_running:
            self.global_task_strip.update_task_state(False, 100, "")

    @Slot(bool, int, str)
    def on_task_progress(self, active: bool, percent: int, message: str) -> None:
        self.global_task_strip.update_task_state(bool(active), int(percent or 0), str(message or ""))

    @Slot(bool, str)
    @Slot(bool, bool, str)
    def on_tun_status_changed(self, enabled: bool, active: bool = False, detail: str = "") -> None:
        if isinstance(active, str) and not detail:
            detail = active
            active = enabled
        self._tun_signal_received = True
        tun_en = bool(enabled)
        badge_str = "ON" if (tun_en or bool(active)) else "OFF"
        self._settings_cache["tun_enabled"] = tun_en
        self._settings_cache["tun_badge"] = badge_str
        self.home_page.apply_tun_status(
            tun_en,
            bool(active),
            str(detail or ""),
            badge_str,
        )
        self._sync_tray_state()

    def toggle_language(self) -> None:
        new_lang = I18N.toggle_language()
        self._handle_single_setting("ui_language", new_lang)

    def _on_language_changed(self, lang: str) -> None:
        self.setUpdatesEnabled(False)
        try:
            direction = I18N.layout_direction()
            self.setLayoutDirection(direction)
            self.tray_menu.setLayoutDirection(direction)

            base_font = make_ui_font(10, QFont.Weight.Medium)
            self.setFont(base_font)
            app = QApplication.instance()
            if app is not None:
                app.setFont(base_font)

            self.setStyleSheet(build_stylesheet(self._palette, lang))

            self.header_bar.retranslate_ui()
            self.global_task_strip.retranslate_ui()
            for btn in self._nav_buttons:
                btn.update()

            self.home_page.retranslate_ui()
            self.configs_page.retranslate_ui()
            self.lab_page.retranslate_ui()
            self.routing_page.retranslate_ui()
            self.logs_page.retranslate_ui()

            self.act_tray_proxy.setText(I18N.t("tray_sys_proxy"))
            self.act_tray_tun.setText(I18N.t("tray_tun_mode"))
            self.act_tray_open.setText(I18N.t("tray_open"))
            self.act_tray_exit.setText(I18N.t("tray_exit"))
            self._sync_tray_state()
        finally:
            self.setUpdatesEnabled(True)

    def toggle_theme(self) -> None:
        target = LIGHT_PALETTE if self._palette.is_dark else DARK_PALETTE
        self.apply_theme(target)

    def apply_theme(self, palette: ThemePalette) -> None:
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

            self.setStyleSheet(build_stylesheet(palette, I18N.lang))
            apply_windows_titlebar_theme(self, palette.is_dark)

            self.header_bar.set_palette_theme(palette)
            self.nav_rail.set_palette_theme(palette)
            self.global_task_strip.set_palette_theme(palette)
            for btn in self._nav_buttons:
                btn.set_palette_theme(palette)

            self.home_page.set_palette_theme(palette)
            self.configs_page.set_palette_theme(palette)
            self.lab_page.set_palette_theme(palette)
            self.routing_page.set_palette_theme(palette)
            self.logs_page.set_palette_theme(palette)
        finally:
            self.setUpdatesEnabled(True)