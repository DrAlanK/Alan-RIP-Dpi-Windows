import base64
import concurrent.futures
import copy
import json
import os
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from alan_dpi.engine.models import (
    BypassVector,
    EngineSettings,
    EngineState,
    ProfileNode,
    SubscriptionItem,
    TelemetrySnapshot,
    VECTOR_REGISTRY,
    filter_vectors_by_mode,
    find_vector,
    format_byte_rate,
    format_uptime_hms,
)
from alan_dpi.engine.bridge import FullDuplexMutatorBridge
from alan_dpi.engine.xray_driver import SystemProxyController, UriConfigCodec, XrayProcessDriver
from alan_dpi.engine.clean_ip import CleanIpScanner, SEED_CLEAN_IPS
from alan_dpi.engine.verifier import TunnelStreamVerifier
from alan_dpi.engine.tun_manager import WinTunManager, is_windows_admin


DEFAULT_BOOTSTRAP_URI = (
    ""
)

CONNECTING_STATES = {
    EngineState.FAST_RESUME,
    EngineState.SCANNING_CLEAN_IP,
    EngineState.PROBING_VECTORS,
    EngineState.SCANNING_REPOSITORY,
    EngineState.HUNTING_BEST,
    EngineState.VERIFYING_STABILITY,
    EngineState.RECOVERING,
}

SETTING_KEY_ALIASES = {
    "clean_ip": "auto_clean_ip",
    "auto_clean": "auto_clean_ip",
    "youtube_6s": "require_youtube_6s",
    "youtube_guard": "require_youtube_6s",
    "yt_guard": "require_youtube_6s",
    "upload_check": "verify_upload_stream",
    "verify_upload": "verify_upload_stream",
    "self_healing": "self_healing_watchdog",
    "watchdog": "self_healing_watchdog",
    "system_proxy": "system_proxy_enabled",
    "sys_proxy": "system_proxy_enabled",
    "autopilot": "autopilot_enabled",
    "tun": "tun_enabled",
}


class AlanAutoPilotEngine:
    def __init__(
        self,
        base_dir: str,
        on_telemetry: Optional[Callable[[dict], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_profiles_changed: Optional[Callable[[List[dict]], None]] = None,
        on_settings_changed: Optional[Callable[[dict], None]] = None,
        on_scan_row: Optional[Callable[[dict], None]] = None,
        on_scan_ranked: Optional[Callable[[List[dict]], None]] = None,
        on_scan_progress: Optional[Callable[[int, str], None]] = None,
        on_scan_state: Optional[Callable[[bool, str], None]] = None,
        on_subscriptions_changed: Optional[Callable[[List[dict]], None]] = None,
        on_task_progress: Optional[Callable[[bool, int, str], None]] = None,
        on_tun_status: Optional[Callable[[bool, str], None]] = None,
    ):
        self.base_dir = base_dir
        self.core_dir = os.path.join(base_dir, "core")
        self.configs_dir = os.path.join(base_dir, "configs")
        self.logs_dir = os.path.join(base_dir, "logs")
        for folder in (self.core_dir, self.configs_dir, self.logs_dir):
            os.makedirs(folder, exist_ok=True)

        self.settings_path = os.path.join(self.configs_dir, "settings.json")
        self.repo_path = os.path.join(self.configs_dir, "repository.json")
        self.subs_path = os.path.join(self.configs_dir, "subscriptions.json")

        self._on_telemetry = on_telemetry
        self._on_log = on_log
        self._on_profiles_changed = on_profiles_changed
        self._on_settings_changed = on_settings_changed
        self._on_scan_row = on_scan_row
        self._on_scan_ranked = on_scan_ranked
        self._on_scan_progress = on_scan_progress
        self._on_scan_state = on_scan_state
        self._on_subscriptions_changed = on_subscriptions_changed
        self._on_task_progress = on_task_progress
        self._on_tun_status = on_tun_status

        self._state_lock = threading.RLock()
        self._repo_lock = threading.RLock()
        self._op_generation = 0
        self._abort_flag = False
        self._scan_abort_flag = False
        self._task_abort_flag = False
        self._shutdown_flag = False
        self._worker_thread: Optional[threading.Thread] = None
        self._connected_since_ts: Optional[float] = None

        self.settings: EngineSettings = self._load_settings()
        self.profiles: List[ProfileNode] = self._load_profiles()
        self.subscriptions: List[SubscriptionItem] = self._load_subscriptions()
        self.selected_index: int = self._restore_persisted_selection()

        self.snapshot = TelemetrySnapshot(
            tun_enabled=self.settings.tun_enabled,
            selected_index=self.selected_index,
        )
        self._persist_active_selection(save_disk=True)

        self.tun = WinTunManager(
            core_dir=self.core_dir,
            configs_dir=self.configs_dir,
            log_fn=self.emit_log,
            status_fn=self._handle_tun_status_callback,
            progress_fn=self._emit_task_progress,
        )

        self.bridge = FullDuplexMutatorBridge(
            listen_port=self.settings.bridge_port,
            log_fn=self.emit_log,
            on_endpoint_change=self._handle_bridge_endpoint_change,
        )
        self.bridge.start()

        self.xray = XrayProcessDriver(
            core_dir=self.core_dir,
            configs_dir=self.configs_dir,
            log_fn=self.emit_log,
        )

        self._prev_tx_bytes = 0
        self._prev_rx_bytes = 0
        self._prev_tick_ts = time.perf_counter()

        threading.Thread(target=self._telemetry_ticker_loop, daemon=True).start()
        threading.Thread(target=self._self_healing_watchdog_loop, daemon=True).start()

    def _restore_persisted_selection(self) -> int:
        with self._repo_lock:
            if not self.profiles:
                return 0
            target_uid = (self.settings.selected_profile_uid or "").strip()
            if target_uid:
                for idx, node in enumerate(self.profiles):
                    if node.uid == target_uid:
                        return idx
            idx_val = int(self.settings.selected_index)
            if 0 <= idx_val < len(self.profiles):
                return idx_val
            return 0

    def _persist_active_selection(self, save_disk: bool = True):
        with self._repo_lock:
            if self.profiles:
                self.selected_index = max(0, min(self.selected_index, len(self.profiles) - 1))
                active = self.profiles[self.selected_index]
                self.settings.selected_index = self.selected_index
                self.settings.selected_profile_uid = active.uid
                with self._state_lock:
                    self.snapshot.selected_index = self.selected_index
                    self.snapshot.active_profile_uid = active.uid
                    self.snapshot.active_profile_name = active.name
                    self.snapshot.protocol_label = active.protocol
            else:
                self.selected_index = 0
                self.settings.selected_index = 0
                self.settings.selected_profile_uid = ""
                with self._state_lock:
                    self.snapshot.selected_index = 0
                    self.snapshot.active_profile_uid = ""
                    self.snapshot.active_profile_name = "---"
                    self.snapshot.protocol_label = "---"
        if save_disk:
            self._save_settings(self.settings)

    def _resolve_profile_index(self, index_or_uid: Any) -> int:
        with self._repo_lock:
            if not self.profiles:
                return -1
            if isinstance(index_or_uid, str) and (not index_or_uid.lstrip("-").isdigit()):
                uid_clean = index_or_uid.strip()
                for idx, node in enumerate(self.profiles):
                    if node.uid == uid_clean:
                        return idx
                return -1
            try:
                idx_num = int(index_or_uid)
                if 0 <= idx_num < len(self.profiles):
                    return idx_num
            except Exception:
                pass
            return -1

    def _serialize_profiles(self) -> List[dict]:
        with self._repo_lock:
            out: List[dict] = []
            for idx, node in enumerate(self.profiles):
                item = node.to_dict()
                is_sel = idx == self.selected_index
                item["index"] = idx
                item["is_selected"] = is_sel
                item["is_active"] = is_sel
                out.append(item)
            return out

    @staticmethod
    def _build_vector_plan(node: ProfileNode, engine_mode: str) -> List[BypassVector]:
        base_vectors = [v for v in filter_vectors_by_mode(engine_mode) if v.family != "DIRECT"]
        direct_vec = find_vector("VEC-00")
        uri_low = node.uri.lower()
        proto_up = node.protocol.upper()

        if proto_up == "SHADOWSOCKS":
            return [direct_vec]

        if "security=reality" in uri_low:
            frag_subset = [v for v in base_vectors if v.family == "FRAGMENT"][:2]
            return [direct_vec] + frag_subset

        is_tunnel_or_plain = (
            CleanIpScanner.is_domestic_or_direct_tunnel(node)
            or ("headertype=http" in uri_low)
            or ("security=none" in uri_low)
        )
        if is_tunnel_or_plain:
            return [direct_vec] + base_vectors

        return base_vectors + [direct_vec]

    def _handle_bridge_endpoint_change(self, remote_host: str):
        if self.settings.tun_enabled and self.tun.is_active:
            self.tun.add_bypass_endpoint(remote_host)

    def _handle_tun_status_callback(self, active: bool, detail: str):
        with self._state_lock:
            self.snapshot.tun_active = active
            self.snapshot.tun_enabled = self.settings.tun_enabled
        if self._on_tun_status is not None:
            self._on_tun_status(active, detail)
        self._push_telemetry()

    def emit_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        if self._on_log is not None:
            self._on_log(f"[{ts}] {message}")

    def _emit_task_progress(self, active: bool, pct: int, message: str):
        clamped = max(0, min(100, int(pct)))
        if self._on_task_progress is not None:
            self._on_task_progress(bool(active), clamped, str(message))

    def _emit_scan_row(self, row: dict):
        if self._on_scan_row is not None:
            self._on_scan_row(copy.deepcopy(row))

    def _emit_scan_ranked(self, rows: List[dict]):
        if self._on_scan_ranked is not None:
            self._on_scan_ranked(copy.deepcopy(rows))

    def _emit_scan_progress(self, pct: int, label: str):
        clamped = max(0, min(100, int(pct)))
        if self._on_scan_progress is not None:
            self._on_scan_progress(clamped, label)
        is_running_pct = (clamped > 0) and (clamped < 100)
        self._emit_task_progress(is_running_pct, clamped, label)

    def _emit_scan_state(self, running: bool, summary: str):
        if self._on_scan_state is not None:
            self._on_scan_state(running, summary)
        if not running:
            self._emit_task_progress(False, 100, summary)

    def _push_telemetry(self):
        if self._on_telemetry is not None:
            with self._state_lock:
                payload = asdict(self.snapshot)
            self._on_telemetry(payload)

    def _notify_settings_updated(self):
        if self._on_settings_changed is not None:
            self._on_settings_changed(self.settings.to_dict())

    def _set_state(self, state: EngineState, headline: str, detail: str, progress: Optional[int] = None):
        with self._state_lock:
            self.snapshot.state = state.value
            self.snapshot.tun_enabled = self.settings.tun_enabled
            self.snapshot.tun_active = self.tun.is_active
            self.snapshot.selected_index = self.selected_index

            if state == EngineState.CONNECTED:
                if self._connected_since_ts is None:
                    self._connected_since_ts = time.perf_counter()
                self.snapshot.ui_phase = "CONNECTED"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = True
                self.snapshot.button_text = "قطع اتصال امن"
            elif state in CONNECTING_STATES:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "CONNECTING"
                self.snapshot.is_connecting = True
                self.snapshot.is_connected = False
                self.snapshot.button_text = "لغو فرایند (کلیک برای توقف)"
            elif state == EngineState.ERROR:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "ERROR"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = False
                self.snapshot.button_text = "اتصال هوشمند"
            else:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "IDLE"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = False
                self.snapshot.button_text = "اتصال هوشمند"

            self.snapshot.status_headline = headline
            self.snapshot.status_detail = detail
            if progress is not None:
                self.snapshot.progress_percent = max(0, min(100, progress))
        self._push_telemetry()

    def _load_settings(self) -> EngineSettings:
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return EngineSettings.from_dict(json.load(f))
            except Exception:
                pass
        cfg = EngineSettings()
        self._save_settings(cfg)
        return cfg

    def _save_settings(self, cfg: EngineSettings):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self.emit_log(f"[Settings] Write error: {exc}")

    def _load_profiles(self) -> List[ProfileNode]:
        if os.path.exists(self.repo_path):
            try:
                with open(self.repo_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        if len(raw) > 0:
                            return [ProfileNode.from_dict(item) for item in raw]
                        return []
            except Exception:
                pass
        seed = UriConfigCodec.extract_profile_node(DEFAULT_BOOTSTRAP_URI, group_tag="Default")
        self._save_profiles([seed])
        return [seed]

    def _save_profiles(self, nodes: List[ProfileNode]):
        with self._repo_lock:
            try:
                serializable = [n.to_dict() for n in nodes]
                with open(self.repo_path, "w", encoding="utf-8") as f:
                    json.dump(serializable, f, indent=2, ensure_ascii=False)
            except Exception as exc:
                self.emit_log(f"[Repository] Write error: {exc}")

    def _load_subscriptions(self) -> List[SubscriptionItem]:
        if os.path.exists(self.subs_path):
            try:
                with open(self.subs_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        return [SubscriptionItem.from_dict(x) for x in raw]
            except Exception:
                pass
        return []

    def _save_subscriptions(self):
        with self._repo_lock:
            try:
                with open(self.subs_path, "w", encoding="utf-8") as f:
                    json.dump([s.to_dict() for s in self.subscriptions], f, indent=2, ensure_ascii=False)
            except Exception as exc:
                self.emit_log(f"[Subscriptions] Write error: {exc}")

    def _notify_profiles_updated(self, save_selection: bool = True):
        self._persist_active_selection(save_disk=save_selection)
        snapshot_list = self._serialize_profiles()
        if self._on_profiles_changed is not None:
            self._on_profiles_changed(snapshot_list)

    def _notify_subscriptions_updated(self):
        with self._repo_lock:
            subs_copy = [s.to_dict() for s in self.subscriptions]
        if self._on_subscriptions_changed is not None:
            self._on_subscriptions_changed(subs_copy)

    def get_profiles_as_dicts(self) -> List[dict]:
        return self._serialize_profiles()

    def get_subscriptions_as_dicts(self) -> List[dict]:
        with self._repo_lock:
            return [s.to_dict() for s in self.subscriptions]

    def get_settings_as_dict(self) -> dict:
        return self.settings.to_dict()

    def get_vectors_as_dicts(self) -> List[dict]:
        return [
            {
                "vector_id": v.vector_id,
                "code_name": v.code_name,
                "family": v.family,
                "summary": v.summary,
            }
            for v in VECTOR_REGISTRY
        ]

    def set_tun_mode(self, enabled: bool):
        want_tun = bool(enabled)
        if want_tun and (not is_windows_admin()):
            self.settings.tun_enabled = False
            self._save_settings(self.settings)
            self._handle_tun_status_callback(False, "نیاز به دسترسی Administrator")
            self._notify_settings_updated()
            return

        self.settings.tun_enabled = want_tun
        self._save_settings(self.settings)
        self.snapshot.tun_enabled = want_tun
        self._notify_settings_updated()

        if want_tun and self.snapshot.is_connected:
            ep = self.snapshot.endpoint_ip if (self.snapshot.endpoint_ip != "---") else self.bridge.remote_host
            threading.Thread(target=self._activate_tun_async, args=(ep,), daemon=True).start()
        elif not want_tun:
            threading.Thread(target=self.tun.stop, daemon=True).start()

    def _activate_tun_async(self, endpoint_host: str):
        ok = self.tun.start(
            socks_port=self.settings.socks_port,
            http_port=self.settings.http_port,
            endpoint_host=endpoint_host,
            mtu=self.settings.tun_mtu,
            dns_server=self.settings.tun_dns,
            allow_download=self.settings.tun_auto_download,
        )
        if not ok:
            self.settings.tun_enabled = False
            self.snapshot.tun_enabled = False
            self._save_settings(self.settings)
            self._notify_settings_updated()
        self._push_telemetry()

    def set_single_setting(self, key: str, value: Any):
        clean_key = SETTING_KEY_ALIASES.get(str(key).strip(), str(key).strip())
        if clean_key == "tun_enabled":
            self.set_tun_mode(bool(value))
            return
        self.update_settings({clean_key: value})

    def update_settings(self, settings_dict: dict):
        if not isinstance(settings_dict, dict):
            return

        prev_tun = self.settings.tun_enabled
        prev_sys_proxy = self.settings.system_proxy_enabled
        cur_uid = self.settings.selected_profile_uid
        cur_idx = self.settings.selected_index

        normalized: Dict[str, Any] = {}
        for raw_k, raw_v in settings_dict.items():
            if raw_v is None:
                continue
            mapped_k = SETTING_KEY_ALIASES.get(str(raw_k).strip(), str(raw_k).strip())
            normalized[mapped_k] = raw_v

        merged = self.settings.to_dict()
        merged.update(normalized)
        if "selected_profile_uid" not in normalized:
            merged["selected_profile_uid"] = cur_uid
        if "selected_index" not in normalized:
            merged["selected_index"] = cur_idx

        self.settings = EngineSettings.from_dict(merged)
        self._save_settings(self.settings)
        self.snapshot.tun_enabled = self.settings.tun_enabled

        self.emit_log(
            f"[Settings] Applied (AutoCleanIP={self.settings.auto_clean_ip}, "
            f"YT6s={self.settings.require_youtube_6s}, UploadCheck={self.settings.verify_upload_stream}, "
            f"Watchdog={self.settings.self_healing_watchdog}, Mode={self.settings.engine_mode})"
        )

        if self.snapshot.is_connected:
            if self.settings.system_proxy_enabled != prev_sys_proxy:
                SystemProxyController.apply(self.settings.system_proxy_enabled, self.settings.http_port)
            if self.settings.tun_enabled != prev_tun:
                self.set_tun_mode(self.settings.tun_enabled)

        self._notify_settings_updated()
        self._push_telemetry()

    def get_config_editable(self, index_or_uid: Any) -> dict:
        idx = self._resolve_profile_index(index_or_uid)
        with self._repo_lock:
            if 0 <= idx < len(self.profiles):
                return UriConfigCodec.parse_editable_fields(self.profiles[idx])
        return {}

    def save_config_editable(self, index_or_uid: Any, data: dict) -> bool:
        try:
            raw_override = str(data.get("raw_uri", "")).strip()
            use_raw = bool(data.get("use_raw_uri", False))
            rebuilt_uri = raw_override if (use_raw and bool(raw_override)) else UriConfigCodec.build_uri_from_editable(data)

            group = str(data.get("group_tag", "Manual")).strip() or "Manual"
            pref_vec = str(data.get("preferred_vector_id", "")).strip()
            if pref_vec == "AUTO":
                pref_vec = ""

            parsed_node = UriConfigCodec.extract_profile_node(rebuilt_uri, group_tag=group)
            parsed_node.cached_vector_id = pref_vec

            idx = self._resolve_profile_index(index_or_uid)
            with self._repo_lock:
                if 0 <= idx < len(self.profiles):
                    old = self.profiles[idx]
                    parsed_node.uid = old.uid
                    old_host = old.cached_clean_ip if old.cached_clean_ip else old.original_host
                    if parsed_node.original_host == old_host:
                        parsed_node.last_ping_ms = old.last_ping_ms
                        parsed_node.health_status = old.health_status
                    self.profiles[idx] = parsed_node
                    self.emit_log(f"[Repository] Updated configuration for '{parsed_node.name}'.")
                else:
                    self.profiles.insert(0, parsed_node)
                    self.selected_index = 0
                    self.emit_log(f"[Repository] Created new profile '{parsed_node.name}'.")

            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self._push_telemetry()
            return True
        except Exception as exc:
            self.emit_log(f"[Editor] Validation failed: {exc}")
            return False

    def clear_all_configs(self) -> int:
        if self.snapshot.is_connected or self.snapshot.is_connecting:
            self.request_disconnect()
        with self._repo_lock:
            removed_count = len(self.profiles)
            self.profiles.clear()
            self.selected_index = 0
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()
        self._push_telemetry()
        self.emit_log(f"[Repository] Cleared all {removed_count} profile(s) from repository.")
        return removed_count

    def import_configs(self, raw_text: str, group_tag: str = "Manual") -> int:
        if (not raw_text) or (not raw_text.strip()):
            return 0
        text = raw_text.strip()
        if "://" not in text:
            try:
                padded = text + ("=" * ((4 - (len(text) % 4)) % 4))
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                if "://" in decoded:
                    text = decoded
            except Exception:
                pass

        added = 0
        with self._repo_lock:
            existing_uris = {p.uri for p in self.profiles}
            for line in text.splitlines():
                candidate = line.strip()
                if (not candidate) or (candidate in existing_uris):
                    continue
                if candidate.startswith(("vless://", "vmess://", "trojan://", "ss://")):
                    try:
                        node = UriConfigCodec.extract_profile_node(candidate, group_tag=group_tag)
                        self.profiles.append(node)
                        existing_uris.add(candidate)
                        added += 1
                    except Exception as exc:
                        self.emit_log(f"[Import] Rejected malformed URI: {exc}")

        if added > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Added {added} profile(s) under group '{group_tag}'.")
        return added

    def import_configs_from_file(self, file_path: str) -> int:
        if (not file_path) or (not os.path.exists(file_path)):
            return 0
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.import_configs(content, group_tag=os.path.basename(file_path))
        except Exception as exc:
            self.emit_log(f"[Import] File read error: {exc}")
            return 0

    def add_subscription(self, url: str, title: str = "Subscription") -> int:
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            return 0
        with self._repo_lock:
            existing = next((s for s in self.subscriptions if s.url == clean_url), None)
            if existing is None:
                existing = SubscriptionItem(url=clean_url, title=title.strip() or "Subscription")
                self.subscriptions.append(existing)
                self._save_subscriptions()
                self._notify_subscriptions_updated()
        return self._pull_single_subscription(existing)

    def _pull_single_subscription(self, sub: SubscriptionItem) -> int:
        self._emit_task_progress(True, 30, f"دریافت اشتراک «{sub.title}»...")
        try:
            sess = requests.Session()
            sess.trust_env = False
            if self.snapshot.is_connected:
                px = f"http://127.0.0.1:{self.settings.http_port}"
                sess.proxies = {"http": px, "https": px}
            resp = sess.get(sub.url, timeout=12.0)
            sess.close()
            if (resp.status_code == 200) and bool(resp.text):
                with self._repo_lock:
                    active_uid = (
                        self.profiles[self.selected_index].uid
                        if (0 <= self.selected_index < len(self.profiles))
                        else ""
                    )
                    self.profiles = [p for p in self.profiles if p.group_tag != sub.title]
                count = self.import_configs(resp.text, group_tag=sub.title)
                with self._repo_lock:
                    for idx_i, p_item in enumerate(self.profiles):
                        if p_item.uid == active_uid:
                            self.selected_index = idx_i
                            break
                sub.last_updated_ts = int(time.time())
                sub.node_count = count
                self._save_subscriptions()
                self._notify_subscriptions_updated()
                self._notify_profiles_updated()
                self._emit_task_progress(False, 100, f"اشتراک «{sub.title}» به‌روزرسانی شد ({count} کانفیگ)")
                return count
        except Exception as exc:
            self.emit_log(f"[Subscription] Failed fetching '{sub.title}': {exc}")
        self._emit_task_progress(False, 0, f"خطا در دریافت اشتراک «{sub.title}»")
        return 0

    def refresh_all_subscriptions(self):
        def _bg():
            with self._repo_lock:
                subs_list = [s for s in self.subscriptions if s.enabled]
            if not subs_list:
                return
            self._task_abort_flag = False
            total_added = 0
            for idx, sub in enumerate(subs_list, 1):
                if self._task_abort_flag or self._shutdown_flag:
                    break
                pct = int((idx / len(subs_list)) * 90)
                self._emit_task_progress(True, pct, f"به‌روزرسانی اشتراک ({idx}/{len(subs_list)}): {sub.title}...")
                total_added += self._pull_single_subscription(sub)
            self._emit_task_progress(False, 100, f"به‌روزرسانی اشتراک‌ها کامل شد ({total_added} نود فعال)")

        threading.Thread(target=_bg, daemon=True).start()

    def delete_subscription(self, index: int):
        with self._repo_lock:
            if 0 <= index < len(self.subscriptions):
                removed = self.subscriptions.pop(index)
                self._save_subscriptions()
                self._notify_subscriptions_updated()
                self.emit_log(f"[Subscription] Removed feed: {removed.title}")

    def delete_config(self, index_or_uid: Any):
        idx = self._resolve_profile_index(index_or_uid)
        with self._repo_lock:
            if 0 <= idx < len(self.profiles):
                active_uid = self.profiles[self.selected_index].uid if (0 <= self.selected_index < len(self.profiles)) else ""
                removed = self.profiles.pop(idx)
                if removed.uid == active_uid:
                    self.selected_index = min(idx, max(0, len(self.profiles) - 1))
                else:
                    for i, p in enumerate(self.profiles):
                        if p.uid == active_uid:
                            self.selected_index = i
                            break
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self._push_telemetry()
                self.emit_log(f"[Repository] Deleted profile: {removed.name}")

    def rename_config(self, index_or_uid: Any, new_name: str):
        idx = self._resolve_profile_index(index_or_uid)
        with self._repo_lock:
            if (0 <= idx < len(self.profiles)) and bool(new_name.strip()):
                node = self.profiles[idx]
                node.name = new_name.strip()
                node.uri = UriConfigCodec.update_remark(node.uri, node.name)
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()

    def select_config(self, index_or_uid: Any):
        idx = self._resolve_profile_index(index_or_uid)
        with self._repo_lock:
            if 0 <= idx < len(self.profiles):
                self.selected_index = idx
                name = self.profiles[idx].name
            else:
                return
        self._notify_profiles_updated(save_selection=True)
        self._push_telemetry()
        self.emit_log(f"[Repository] Selected active node: {name}")

    def deduplicate_configs(self) -> int:
        with self._repo_lock:
            active_uid = self.profiles[self.selected_index].uid if (0 <= self.selected_index < len(self.profiles)) else ""
            seen = set()
            unique_list: List[ProfileNode] = []
            removed = 0
            for node in self.profiles:
                base_sig = node.uri.split("#")[0].strip()
                if base_sig in seen:
                    removed += 1
                else:
                    seen.add(base_sig)
                    unique_list.append(node)
            if removed > 0:
                self.profiles = unique_list
                self.selected_index = 0
                for i, p in enumerate(self.profiles):
                    if p.uid == active_uid:
                        self.selected_index = i
                        break
        if removed > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Deduplicated {removed} identical profile(s).")
        return removed

    def remove_dead_configs(self) -> int:
        with self._repo_lock:
            active_uid = self.profiles[self.selected_index].uid if (0 <= self.selected_index < len(self.profiles)) else ""
            alive = [p for p in self.profiles if p.health_status != "DEAD"]
            removed = len(self.profiles) - len(alive)
            if removed > 0:
                self.profiles = alive
                self.selected_index = 0
                for i, p in enumerate(self.profiles):
                    if p.uid == active_uid:
                        self.selected_index = i
                        break
        if removed > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Purged {removed} dead profile(s).")
        return removed

    def sort_configs(self, sort_by: str = "ping"):
        with self._repo_lock:
            active_uid = self.profiles[self.selected_index].uid if (0 <= self.selected_index < len(self.profiles)) else ""
            if sort_by == "ping":
                self.profiles.sort(
                    key=lambda n: (
                        0 if (n.health_status == "VERIFIED") else (1 if (n.health_status == "HEALTHY") else 2),
                        n.last_ping_ms if (n.last_ping_ms > 0) else 999999,
                        n.name.lower(),
                    )
                )
            elif sort_by == "name":
                self.profiles.sort(key=lambda n: n.name.lower())
            elif sort_by == "protocol":
                self.profiles.sort(key=lambda n: (n.protocol, n.last_ping_ms if (n.last_ping_ms > 0) else 999999))

            for i, p in enumerate(self.profiles):
                if p.uid == active_uid:
                    self.selected_index = i
                    break
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()

    def quick_ping_repository(self):
        def _ping_worker():
            with self._repo_lock:
                snapshot_nodes = list(self.profiles)
            total = len(snapshot_nodes)
            if total == 0:
                self._emit_task_progress(False, 0, "مخزن خالی است")
                return

            self._task_abort_flag = False
            self._emit_task_progress(True, 5, f"آماده‌سازی تست سریع {total} کانفیگ...")
            self.emit_log(f"[Repository] Starting parallel TCP/Edge ping across {total} profile(s)...")

            fallback_cdn_ip = ""
            if self.settings.auto_clean_ip:
                for seed_ip in SEED_CLEAN_IPS:
                    if CleanIpScanner.fast_tcp_ping(seed_ip, 443, timeout=1.1) >= 0:
                        fallback_cdn_ip = seed_ip
                        break

            completed = 0
            alive_count = 0
            count_lock = threading.Lock()

            def _probe_single(node: ProfileNode):
                nonlocal completed, alive_count
                if self._task_abort_flag or self._shutdown_flag:
                    return
                ep = node.cached_clean_ip if node.cached_clean_ip else node.original_host
                ms = CleanIpScanner.fast_tcp_ping(ep, node.port, timeout=1.8)
                if (ms < 0) and bool(fallback_cdn_ip) and CleanIpScanner.is_cdn_eligible(node):
                    ms = CleanIpScanner.fast_tcp_ping(fallback_cdn_ip, node.port, timeout=1.8)
                    if ms >= 0:
                        node.cached_clean_ip = fallback_cdn_ip

                node.last_ping_ms = ms
                node.last_tested_ts = int(time.time())
                if ms >= 0:
                    if node.health_status in ("UNTESTED", "DEAD"):
                        node.health_status = "HEALTHY"
                else:
                    node.health_status = "DEAD"

                with count_lock:
                    completed += 1
                    if ms >= 0:
                        alive_count += 1
                    pct = 10 + int((completed / total) * 85)
                    self._emit_task_progress(
                        True,
                        pct,
                        f"پینگ سریع کانفیگ‌ها ({completed}/{total}) — پاسخ‌گو: {alive_count}",
                    )

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(_probe_single, snapshot_nodes))

            if self._task_abort_flag:
                self._emit_task_progress(False, 0, "پینگ سریع متوقف شد")
                return

            self.sort_configs("ping")
            summary = f"تست سریع پایان یافت: {alive_count} از {total} کانفیگ در دسترس هستند"
            self.emit_log(f"[Repository] {summary}")
            self._emit_task_progress(False, 100, summary)

        threading.Thread(target=_ping_worker, daemon=True).start()

    def clone_config_with_clean_ips(self, index_or_uid: Any, clone_count: int = 3):
        idx = self._resolve_profile_index(index_or_uid)
        with self._repo_lock:
            if not (0 <= idx < len(self.profiles)):
                return
            base_node = copy.deepcopy(self.profiles[idx])

        def _clone_worker():
            self._task_abort_flag = False
            self._emit_task_progress(True, 10, f"یافتن {clone_count} آی‌پی تمیز برتر برای کلون «{base_node.name}»...")
            edges = CleanIpScanner.discover_best_ips(
                port=base_node.port,
                top_n=clone_count,
                sample_count=32,
                progress_cb=lambda p, m: self._emit_task_progress(True, p, m),
                abort_check=lambda: (self._task_abort_flag or self._shutdown_flag),
            )
            if self._task_abort_flag:
                self._emit_task_progress(False, 0, "عملیات کلون لغو شد")
                return

            created = 0
            with self._repo_lock:
                active_uid = self.profiles[self.selected_index].uid if (0 <= self.selected_index < len(self.profiles)) else ""
                insert_pos = min(idx + 1, len(self.profiles))
                for rank, (ip_addr, tls_ms) in enumerate(edges, 1):
                    cloned_name = f"{base_node.name} [Edge-{rank} | {tls_ms}ms]"
                    cloned_uri = UriConfigCodec.replace_endpoint_ip(base_node.uri, ip_addr)
                    cloned_uri = UriConfigCodec.update_remark(cloned_uri, cloned_name)
                    new_node = UriConfigCodec.extract_profile_node(cloned_uri, group_tag="Optimized-Clones")
                    new_node.cached_clean_ip = ip_addr
                    new_node.cached_vector_id = base_node.cached_vector_id
                    new_node.last_ping_ms = tls_ms
                    new_node.health_status = "HEALTHY"
                    self.profiles.insert(insert_pos + created, new_node)
                    created += 1
                for i, p in enumerate(self.profiles):
                    if p.uid == active_uid:
                        self.selected_index = i
                        break

            if created > 0:
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self.emit_log(f"[Repository] Created {created} optimized Clean-IP clone(s).")
            self._emit_task_progress(False, 100, f"{created} کلون بهینه با آی‌پی تمیز ساخته شد")

        threading.Thread(target=_clone_worker, daemon=True).start()

    def export_configs(self, mode: str = "verified", inject_early_data: int = 0) -> str:
        lines: List[str] = []
        with self._repo_lock:
            for node in self.profiles:
                if (mode == "verified") and (node.health_status not in ("VERIFIED", "HEALTHY")):
                    continue
                lines.append(UriConfigCodec.build_exportable_uri(node, inject_early_data=inject_early_data))
        return "\n".join(lines)

    def apply_clean_ip_to_repository(self, clean_ip: str, only_selected: bool = False) -> int:
        ip_val = (clean_ip or "").strip().split(":")[0]
        if not ip_val:
            return 0
        updated = 0
        with self._repo_lock:
            if not self.profiles:
                return 0
            targets = [self.profiles[self.selected_index]] if only_selected else self.profiles
            for node in targets:
                if only_selected or CleanIpScanner.is_cdn_eligible(node):
                    node.cached_clean_ip = ip_val
                    node.uri = UriConfigCodec.replace_endpoint_ip(node.uri, ip_val)
                    updated += 1
        if updated > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Patch] Applied Clean IP {ip_val} onto {updated} profile(s).")
            self._emit_task_progress(False, 100, f"آی‌پی تمیز {ip_val} روی {updated} کانفیگ وصله شد")
        return updated

    def bind_vector_to_profile(
        self,
        vector_id: str,
        target_index: Any = -1,
        clean_ip: str = "",
        connect_now: bool = False,
    ):
        clean_ep = (clean_ip or "").strip().split(":")[0]
        resolved = self._resolve_profile_index(target_index)
        with self._repo_lock:
            idx = resolved if (resolved >= 0) else self.selected_index
            if not (0 <= idx < len(self.profiles)):
                return
            node = self.profiles[idx]
            node.cached_vector_id = "" if (vector_id == "AUTO") else vector_id
            if bool(clean_ep) and (clean_ep != node.original_host) and CleanIpScanner.is_cdn_eligible(node):
                node.cached_clean_ip = clean_ep
                node.uri = UriConfigCodec.replace_endpoint_ip(node.uri, clean_ep)
            node_name = node.name

        vec_obj = find_vector(vector_id)
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()
        self.emit_log(f"[Patch] Bound {vec_obj.vector_id} ({vec_obj.code_name}) -> '{node_name}'.")
        self._emit_task_progress(False, 100, f"متد {vec_obj.vector_id} روی «{node_name}» اعمال شد")

        if connect_now:
            self.select_config(idx)
            self.request_connect()

    def apply_vector_to_all_configs(self, vector_id: str, clean_ip: str = "") -> int:
        clean_ep = (clean_ip or "").strip().split(":")[0]
        vec_val = "" if (vector_id == "AUTO") else vector_id
        count = 0
        with self._repo_lock:
            for node in self.profiles:
                if (node.protocol.upper() == "SHADOWSOCKS") and (vec_val not in ("", "VEC-00")):
                    continue
                node.cached_vector_id = vec_val
                if bool(clean_ep) and (clean_ep != node.original_host) and CleanIpScanner.is_cdn_eligible(node):
                    node.cached_clean_ip = clean_ep
                    node.uri = UriConfigCodec.replace_endpoint_ip(node.uri, clean_ep)
                count += 1
        if count > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            vec_obj = find_vector(vector_id)
            self.emit_log(f"[Patch] Applied {vec_obj.vector_id} ({vec_obj.code_name}) across {count} profiles.")
            self._emit_task_progress(False, 100, f"متد {vec_obj.vector_id} روی {count} کانفیگ مخزن وصله شد")
        return count

    def connect_scanned_profile(self, target_index_or_uid: Any, vector_id: str = "", clean_ip: str = ""):
        clean_ep = (clean_ip or "").strip().split(":")[0]
        resolved_idx = self._resolve_profile_index(target_index_or_uid)
        if resolved_idx < 0:
            return

        with self._repo_lock:
            node = self.profiles[resolved_idx]
            if bool(vector_id) and (vector_id != "AUTO"):
                node.cached_vector_id = vector_id
            if bool(clean_ep) and (clean_ep != node.original_host) and CleanIpScanner.is_cdn_eligible(node):
                node.cached_clean_ip = clean_ep
            self.selected_index = resolved_idx

        self._save_profiles(self.profiles)
        self._notify_profiles_updated(save_selection=True)
        self.request_connect()

    def hunt_best_and_connect(self):
        with self._repo_lock:
            if not self.profiles:
                self._set_state(EngineState.ERROR, "مخزن خالی است", "ابتدا کانفیگ وارد کنید", 0)
                return

        if self.snapshot.is_connecting or self.snapshot.is_connected:
            self._teardown_active_tunnel_sync()

        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._abort_flag = False
            self._scan_abort_flag = False
            self._task_abort_flag = False

        self._set_state(
            EngineState.HUNTING_BEST,
            "شکار هوشمند برترین کانفیگ مخزن...",
            "پویش موازی تمام کانفیگ‌ها، تانل‌ها، IPهای تمیز و متدهای عبوری",
            progress=5,
        )
        self._emit_task_progress(True, 5, "شروع شکار خودکار برترین کانفیگ مخزن...")

        self._worker_thread = threading.Thread(
            target=self._run_hunt_best_pipeline,
            args=(gen_id,),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_hunt_best_pipeline(self, gen_id: int):
        try:
            with self._repo_lock:
                all_nodes = list(self.profiles)
            total_nodes = len(all_nodes)

            best_cdn_edges: List[str] = []
            has_any_cdn = any(CleanIpScanner.is_cdn_eligible(nd) for nd in all_nodes)
            if self.settings.auto_clean_ip and has_any_cdn:
                self._set_state(EngineState.HUNTING_BEST, "شکار برترین کانفیگ...", "کشف لبه‌های تمیز CDN...", 12)
                edges = CleanIpScanner.discover_best_ips(
                    port=443,
                    top_n=2,
                    sample_count=30,
                    log_fn=self.emit_log,
                    progress_cb=lambda p, m: self._emit_task_progress(True, max(8, p // 4), m),
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                )
                best_cdn_edges = [ip for ip, _ in edges]

            if self._is_op_cancelled(gen_id):
                return

            self._set_state(EngineState.HUNTING_BEST, "پالایش سرعت مخزن...", f"بررسی موازی {total_nodes} کانفیگ", 26)
            self._emit_task_progress(True, 26, f"غربالگری موازی TCP روی {total_nodes} کانفیگ...")

            def _fast_eval(nd: ProfileNode):
                if bool(best_cdn_edges) and CleanIpScanner.is_cdn_eligible(nd):
                    ep = best_cdn_edges[0]
                else:
                    ep = nd.cached_clean_ip if nd.cached_clean_ip else nd.original_host
                ms = CleanIpScanner.fast_tcp_ping(ep, nd.port, timeout=1.5)
                if (ms < 0) and (nd.original_host != ep):
                    ms = CleanIpScanner.fast_tcp_ping(nd.original_host, nd.port, timeout=1.5)
                    if ms >= 0:
                        ep = nd.original_host
                return ms, nd, ep

            prior_verified: List[Tuple[int, ProfileNode, str]] = []
            foreign_candidates: List[Tuple[int, ProfileNode, str]] = []
            domestic_candidates: List[Tuple[int, ProfileNode, str]] = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                for ms, nd, ep in pool.map(_fast_eval, all_nodes):
                    if ms < 0:
                        nd.health_status = "DEAD"
                        nd.last_ping_ms = -1
                        continue
                    if (nd.health_status == "VERIFIED") or bool(nd.cached_vector_id):
                        prior_verified.append((ms, nd, ep))
                    elif CleanIpScanner.is_domestic_or_direct_tunnel(nd):
                        domestic_candidates.append((ms, nd, ep))
                    else:
                        foreign_candidates.append((ms, nd, ep))

            if self._is_op_cancelled(gen_id):
                return

            prior_verified.sort(key=lambda x: x[0])
            foreign_candidates.sort(key=lambda x: x[0])
            domestic_candidates.sort(key=lambda x: x[0])

            shortlist: List[Tuple[int, ProfileNode, str]] = []
            shortlist.extend(prior_verified[:5])
            shortlist.extend(foreign_candidates[:7])
            shortlist.extend(domestic_candidates[:5])

            if not shortlist:
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self._emit_task_progress(False, 0, "هیچ کانفیگ در دسترسی در مخزن یافت نشد")
                self._set_state(EngineState.ERROR, "کانفیگ فعالی یافت نشد", "سرورهای موجود در مخزن پاسخ نمی‌دهند", 0)
                return

            qualified_winners: List[Tuple[int, ProfileNode, str, BypassVector]] = []
            soft_winners: List[Tuple[int, ProfileNode, str, BypassVector]] = []

            total_short = len(shortlist)
            for c_idx, (_, cand_node, cand_ep) in enumerate(shortlist, 1):
                if self._is_op_cancelled(gen_id):
                    return
                try:
                    self.xray.ensure_running(uri=cand_node.uri, settings=self.settings, use_native_fragment=False)
                except Exception:
                    continue

                node_plan = self._build_vector_plan(cand_node, self.settings.engine_mode)
                probe_vecs = node_plan[:3] if CleanIpScanner.is_domestic_or_direct_tunnel(cand_node) else node_plan[:4]
                if cand_node.cached_vector_id:
                    cv = find_vector(cand_node.cached_vector_id)
                    if cv not in probe_vecs:
                        probe_vecs.insert(0, cv)

                for v_i, vec in enumerate(probe_vecs):
                    if self._is_op_cancelled(gen_id):
                        return
                    pct = 32 + int(((c_idx - 1 + ((v_i + 1) / max(1, len(probe_vecs)))) / total_short) * 60)
                    msg = f"[{c_idx}/{total_short}] تست «{cand_node.name}» با {vec.vector_id}..."
                    self._set_state(EngineState.HUNTING_BEST, "شکار برترین کانفیگ...", msg, pct)
                    self._emit_task_progress(True, pct, msg)

                    self.bridge.update_route(
                        remote_host=cand_ep,
                        remote_port=cand_node.port,
                        vector=vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=False,
                        flush_existing_pool=True,
                    )

                    q_rep = TunnelStreamVerifier.fast_probe(http_port=self.settings.http_port, timeout=2.6)
                    if self._is_op_cancelled(gen_id):
                        return
                    if not q_rep.passed:
                        continue

                    cand_node.last_ping_ms = q_rep.ping_ms
                    cand_node.health_status = "HEALTHY"
                    soft_winners.append((q_rep.ping_ms, cand_node, cand_ep, vec))

                    full_rep = TunnelStreamVerifier.run_full_qualification(
                        http_port=self.settings.http_port,
                        verify_upload=self.settings.verify_upload_stream,
                        require_youtube_6s=self.settings.require_youtube_6s,
                        base_rtt_ms=q_rep.ping_ms,
                        abort_check=lambda: self._is_op_cancelled(gen_id),
                        log_fn=self.emit_log,
                    )
                    if self._is_op_cancelled(gen_id):
                        return

                    if full_rep.passed:
                        qualified_winners.append((full_rep.ping_ms, cand_node, cand_ep, vec))
                        break

                if len(qualified_winners) >= 1:
                    break

            if self._is_op_cancelled(gen_id):
                return

            final_pool = qualified_winners if qualified_winners else soft_winners
            if final_pool:
                final_pool.sort(key=lambda x: x[0])
                win_ms, win_node, win_ep, win_vec = final_pool[0]

                self.xray.ensure_running(uri=win_node.uri, settings=self.settings, use_native_fragment=False)
                self.bridge.update_route(
                    remote_host=win_ep,
                    remote_port=win_node.port,
                    vector=win_vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=False,
                    flush_existing_pool=True,
                )

                win_node.cached_vector_id = win_vec.vector_id
                win_node.cached_clean_ip = win_ep if (win_ep != win_node.original_host) else ""
                win_node.last_ping_ms = win_ms
                win_node.health_status = "VERIFIED"

                self.sort_configs("ping")
                with self._repo_lock:
                    for idx_i, p_item in enumerate(self.profiles):
                        if p_item.uid == win_node.uid:
                            self.selected_index = idx_i
                            break
                self._notify_profiles_updated(save_selection=True)

                self._emit_task_progress(
                    False, 100, f"برترین کانفیگ متصل شد: «{win_node.name}» ({win_ms}ms • {win_vec.vector_id})"
                )
                self._lock_winning_tunnel(gen_id, win_node, win_ep, win_vec, win_ms, raw_passthrough=False)
                return

            self.xray.stop()
            self._emit_task_progress(False, 0, "هیچ کانفیگ پایداری در مخزن پاسخ نداد")
            self._set_state(EngineState.ERROR, "شکار ناموفق بود", "هیچ‌یک از کانفیگ‌های مخزن تونل پایدار باز نکردند", 0)
        except Exception as exc:
            self.emit_log(f"[Hunter] Unexpected error: {exc}")
            self._emit_task_progress(False, 0, f"خطا در شکار مخزن: {exc}")
            if not self._is_op_cancelled(gen_id):
                self._set_state(EngineState.ERROR, "خطا در پویش مخزن", str(exc), 0)

    def start_dedicated_scan(self, mode: str = "active_profile", target_index: Any = -1, options: Optional[dict] = None):
        if self.snapshot.is_connecting:
            self._teardown_active_tunnel_sync()

        opts = options if isinstance(options, dict) else {}
        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._scan_abort_flag = False
            self._task_abort_flag = False
            self._abort_flag = False

        if mode == "clean_ip_radar":
            port = int(opts.get("port", 443))
            samples = int(opts.get("samples", 44))
            self._worker_thread = threading.Thread(
                target=self._run_clean_ip_radar_task, args=(gen_id, port, samples), daemon=True
            )
            self._worker_thread.start()
        elif mode == "full_repository":
            prune_dead = bool(opts.get("prune_dead", False))
            auto_ip = bool(opts.get("auto_clean_ip", True))
            self._worker_thread = threading.Thread(
                target=self._run_repository_deep_scan_task, args=(gen_id, prune_dead, auto_ip), daemon=True
            )
            self._worker_thread.start()
        else:
            resolved = self._resolve_profile_index(target_index)
            with self._repo_lock:
                idx = resolved if (resolved >= 0) else self.selected_index
            auto_connect = bool(opts.get("auto_connect", False))
            self._worker_thread = threading.Thread(
                target=self._run_active_profile_matrix_scan, args=(gen_id, idx, auto_connect), daemon=True
            )
            self._worker_thread.start()

    def stop_dedicated_scan(self):
        was_connecting = self.snapshot.is_connecting
        with self._state_lock:
            self._op_generation += 1
            self._scan_abort_flag = True
            self._task_abort_flag = True
            if was_connecting:
                self._abort_flag = True

        if was_connecting or (not self.snapshot.is_connected):
            self.bridge.drop_active_connections()
            threading.Thread(target=self.xray.stop, daemon=True).start()
            self._set_state(EngineState.DISCONNECTED, "آماده اتصال", "عملیات اسکن متوقف شد", 0)

        self._emit_scan_state(False, "اسکن توسط کاربر متوقف شد")
        self._emit_task_progress(False, 0, "عملیات توسط کاربر متوقف شد")

    def _is_op_cancelled(self, gen_id: int) -> bool:
        return (
            self._abort_flag
            or self._scan_abort_flag
            or self._task_abort_flag
            or self._shutdown_flag
            or (gen_id != self._op_generation)
        )

    def _run_clean_ip_radar_task(self, gen_id: int, port: int, sample_count: int):
        try:
            collected: List[dict] = []
            self._emit_scan_state(True, f"در حال اسکن {sample_count} کاندید رنج IP تمیز...")
            self._emit_scan_progress(8, "کاوش موازی زیرشبکه‌های CDN...")

            def _capture_row(r: dict):
                collected.append(r)
                self._emit_scan_row(r)

            winners = CleanIpScanner.discover_best_ips(
                port=port,
                top_n=12,
                sample_count=sample_count,
                log_fn=self.emit_log,
                on_row_cb=_capture_row,
                progress_cb=self._emit_scan_progress,
                abort_check=lambda: self._is_op_cancelled(gen_id),
            )
            if self._is_op_cancelled(gen_id):
                return

            collected.sort(key=lambda x: (-x.get("score", 0), x.get("tunnel_ms", 9999)))
            for rk, item in enumerate(collected, 1):
                item["rank"] = rk
            self._emit_scan_ranked(collected)
            self._emit_scan_progress(100, f"{len(winners)} آی‌پی تمیز رتبه‌بندی شد")
            self._emit_scan_state(False, f"اسکن IP تمیز کامل شد ({len(winners)} لبه برتر)")
        except Exception as exc:
            self.emit_log(f"[Radar] Error: {exc}")
            self._emit_scan_state(False, f"خطا در رادار IP: {exc}")

    def _run_active_profile_matrix_scan(self, gen_id: int, idx: int, auto_connect: bool):
        try:
            with self._repo_lock:
                if not (0 <= idx < len(self.profiles)):
                    self._emit_scan_state(False, "پروفایل معتبری در مخزن انتخاب نشده است")
                    return
                node = self.profiles[idx]

            if self.snapshot.is_connected:
                self._teardown_active_tunnel_sync()

            self._emit_scan_state(True, f"اسکن عمیق و رتبه‌بندی متدها روی «{node.name}»...")
            self._emit_scan_progress(6, "راه‌اندازی هسته آزمون...")

            try:
                self.xray.ensure_running(uri=node.uri, settings=self.settings, use_native_fragment=False)
            except Exception as exc:
                self._emit_scan_state(False, f"خطای هسته: {exc}")
                return

            endpoint = node.cached_clean_ip if node.cached_clean_ip else node.original_host
            if self.settings.auto_clean_ip and CleanIpScanner.is_cdn_eligible(node):
                self._emit_scan_progress(14, "انتخاب سریع‌ترین IP تمیز برای پروفایل...")
                edges = CleanIpScanner.discover_best_ips(
                    port=node.port,
                    top_n=1,
                    sample_count=28,
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                )
                if edges:
                    endpoint = edges[0][0]

            vectors = self._build_vector_plan(node, self.settings.engine_mode)
            evaluated_rows: List[dict] = []
            passing_results: List[Tuple[int, int, BypassVector]] = []

            for v_idx, vec in enumerate(vectors, 1):
                if self._is_op_cancelled(gen_id):
                    return
                pct = 18 + int((v_idx / max(1, len(vectors))) * 78)
                self._emit_scan_progress(pct, f"[{v_idx}/{len(vectors)}] آزمایش {vec.vector_id} ({vec.code_name})...")

                self.bridge.update_route(
                    remote_host=endpoint,
                    remote_port=node.port,
                    vector=vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=False,
                    flush_existing_pool=True,
                )

                tcp_ms = CleanIpScanner.fast_tcp_ping(endpoint, node.port, timeout=1.8)
                q_rep = TunnelStreamVerifier.fast_probe(http_port=self.settings.http_port, timeout=2.8)

                if self._is_op_cancelled(gen_id):
                    return

                if not q_rep.passed:
                    row = {
                        "scan_type": "vector",
                        "rank": 99,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": vec.vector_id,
                        "title": f"{vec.vector_id} • {vec.code_name}",
                        "category": vec.family,
                        "endpoint": endpoint,
                        "tcp_ms": tcp_ms,
                        "tunnel_ms": -1,
                        "status": "BLOCKED",
                        "score": 0,
                        "detail": q_rep.detail,
                    }
                    evaluated_rows.append(row)
                    self._emit_scan_row(row)
                    continue

                full_rep = TunnelStreamVerifier.run_full_qualification(
                    http_port=self.settings.http_port,
                    verify_upload=self.settings.verify_upload_stream,
                    require_youtube_6s=self.settings.require_youtube_6s,
                    base_rtt_ms=q_rep.ping_ms,
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                    log_fn=self.emit_log,
                )

                if self._is_op_cancelled(gen_id):
                    return

                if full_rep.passed:
                    score = max(35, min(100, 100 - (full_rep.ping_ms // 22)))
                    row = {
                        "scan_type": "vector",
                        "rank": 1,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": vec.vector_id,
                        "title": f"{vec.vector_id} • {vec.code_name}",
                        "category": vec.family,
                        "endpoint": endpoint,
                        "tcp_ms": tcp_ms,
                        "tunnel_ms": full_rep.ping_ms,
                        "status": "VERIFIED",
                        "score": score,
                        "detail": full_rep.detail,
                    }
                    evaluated_rows.append(row)
                    self._emit_scan_row(row)
                    passing_results.append((-score, full_rep.ping_ms, vec))
                    if auto_connect:
                        break
                else:
                    partial_score = max(15, 50 - (q_rep.ping_ms // 35))
                    row = {
                        "scan_type": "vector",
                        "rank": 50,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": vec.vector_id,
                        "title": f"{vec.vector_id} • {vec.code_name}",
                        "category": vec.family,
                        "endpoint": endpoint,
                        "tcp_ms": tcp_ms,
                        "tunnel_ms": q_rep.ping_ms,
                        "status": "PARTIAL_OK",
                        "score": partial_score,
                        "detail": f"Initial {q_rep.ping_ms}ms OK ({full_rep.stage_failed})",
                    }
                    evaluated_rows.append(row)
                    self._emit_scan_row(row)
                    passing_results.append((-partial_score, q_rep.ping_ms, vec))

            if self._is_op_cancelled(gen_id):
                return

            evaluated_rows.sort(
                key=lambda r: (
                    0 if (r["status"] == "VERIFIED") else (1 if (r["status"] == "PARTIAL_OK") else 2),
                    -r["score"],
                    r["tunnel_ms"] if (r["tunnel_ms"] > 0) else 999999,
                )
            )
            for rk, r_item in enumerate(evaluated_rows, 1):
                r_item["rank"] = rk
            self._emit_scan_ranked(evaluated_rows)

            if passing_results:
                passing_results.sort(key=lambda x: (x[0], x[1]))
                _, best_ms, best_vec = passing_results[0]
                node.cached_vector_id = best_vec.vector_id
                node.cached_clean_ip = endpoint if (endpoint != node.original_host) else ""
                node.last_ping_ms = best_ms
                node.health_status = "VERIFIED"
                node.last_tested_ts = int(time.time())
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self._emit_scan_progress(100, f"رتبه ۱: {best_vec.vector_id} ({best_vec.code_name}) با پینگ {best_ms}ms")
                self._emit_scan_state(
                    False,
                    f"رتبه‌بندی کامل شد — برنده: {best_vec.vector_id} ({best_ms}ms). از دکمه‌های وصله استفاده کنید.",
                )
                if auto_connect:
                    with self._repo_lock:
                        self.selected_index = idx
                    self._notify_profiles_updated(save_selection=True)
                    self.bridge.update_route(
                        remote_host=endpoint,
                        remote_port=node.port,
                        vector=best_vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=False,
                        flush_existing_pool=True,
                    )
                    self._lock_winning_tunnel(gen_id, node, endpoint, best_vec, best_ms, raw_passthrough=False)
                else:
                    self.xray.stop()
            else:
                self.xray.stop()
                self._emit_scan_progress(0, "متد فعالی روی این سرور پاسخ نداد")
                self._emit_scan_state(False, "اسکن پایان یافت؛ پاسخی از سرور کانفیگ دریافت نشد")
        except Exception as exc:
            self.emit_log(f"[MatrixScan] Error: {exc}")
            self._emit_scan_state(False, f"خطا در اسکن عمیق: {exc}")

    def _run_repository_deep_scan_task(self, gen_id: int, prune_dead: bool, auto_clean_ip: bool):
        try:
            with self._repo_lock:
                scan_nodes = list(self.profiles)
            total = len(scan_nodes)
            if total == 0:
                self._emit_scan_state(False, "مخزن خالی است")
                return

            if self.snapshot.is_connected:
                self._teardown_active_tunnel_sync()

            self._emit_scan_state(True, f"اسکن هوشمند {total} پروفایل مخزن...")
            self._set_state(EngineState.SCANNING_REPOSITORY, "اسکن دسته‌جمعی مخزن...", f"پیش‌پالایش موازی {total} کانفیگ", 8)

            best_cdn_ips: List[str] = []
            if auto_clean_ip and any(CleanIpScanner.is_cdn_eligible(nd) for nd in scan_nodes):
                self._emit_scan_progress(10, "یافتن لبه‌های تمیز CDN برای پروفایل‌ها...")
                edges = CleanIpScanner.discover_best_ips(
                    port=443,
                    top_n=2,
                    sample_count=30,
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                )
                best_cdn_ips = [ip for ip, _ in edges]

            if self._is_op_cancelled(gen_id):
                return

            self._emit_scan_progress(18, "تست موازی دسترسی TCP روی تمام پروفایل‌ها...")
            node_tcp_map = {}

            def _precheck(item_pair):
                i, nd = item_pair
                if bool(best_cdn_ips) and CleanIpScanner.is_cdn_eligible(nd):
                    ep = best_cdn_ips[0]
                else:
                    ep = nd.cached_clean_ip if nd.cached_clean_ip else nd.original_host
                ms = CleanIpScanner.fast_tcp_ping(ep, nd.port, timeout=1.5)
                if (ms < 0) and (nd.original_host != ep):
                    ms = CleanIpScanner.fast_tcp_ping(nd.original_host, nd.port, timeout=1.5)
                    if ms >= 0:
                        ep = nd.original_host
                return i, ep, ms

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                for i, ep, ms in pool.map(_precheck, enumerate(scan_nodes)):
                    node_tcp_map[i] = (ep, ms)

            ranked_repo_rows: List[dict] = []
            verified_count = 0
            dead_count = 0

            for idx, node in enumerate(scan_nodes):
                if self._is_op_cancelled(gen_id):
                    return
                step_num = idx + 1
                pct = 22 + int((step_num / total) * 75)
                ep, tcp_ms = node_tcp_map.get(idx, (node.original_host, -1))
                self._emit_scan_progress(
                    pct, f"[{step_num}/{total}] بررسی «{node.name}» (سالم: {verified_count} | خطا: {dead_count})"
                )

                if tcp_ms < 0:
                    node.health_status = "DEAD"
                    node.last_ping_ms = -1
                    dead_count += 1
                    row = {
                        "scan_type": "repository",
                        "rank": 999,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": node.uid,
                        "bound_vector": "",
                        "title": node.name,
                        "category": node.protocol,
                        "endpoint": ep,
                        "tcp_ms": -1,
                        "tunnel_ms": -1,
                        "status": "DEAD",
                        "score": 0,
                        "detail": "سرور غیرقابل دسترس (TCP Timeout)",
                    }
                    ranked_repo_rows.append(row)
                    self._emit_scan_row(row)
                    continue

                try:
                    self.xray.ensure_running(uri=node.uri, settings=self.settings, use_native_fragment=False)
                except Exception as exc:
                    node.health_status = "DEAD"
                    dead_count += 1
                    row = {
                        "scan_type": "repository",
                        "rank": 999,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": node.uid,
                        "bound_vector": "",
                        "title": node.name,
                        "category": node.protocol,
                        "endpoint": ep,
                        "tcp_ms": tcp_ms,
                        "tunnel_ms": -1,
                        "status": "CONFIG_ERR",
                        "score": 0,
                        "detail": str(exc),
                    }
                    ranked_repo_rows.append(row)
                    self._emit_scan_row(row)
                    continue

                probe_vectors = self._build_vector_plan(node, self.settings.engine_mode)[:3]
                node_passed = False

                for vec in probe_vectors:
                    if self._is_op_cancelled(gen_id):
                        return
                    self.bridge.update_route(
                        remote_host=ep,
                        remote_port=node.port,
                        vector=vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=False,
                        flush_existing_pool=True,
                    )
                    rep = TunnelStreamVerifier.fast_probe(http_port=self.settings.http_port, timeout=2.8)
                    if rep.passed:
                        node.cached_vector_id = vec.vector_id
                        node.cached_clean_ip = ep if (ep != node.original_host) else ""
                        node.last_ping_ms = rep.ping_ms
                        node.health_status = "VERIFIED"
                        node.last_tested_ts = int(time.time())
                        verified_count += 1
                        node_passed = True
                        sc = max(20, min(100, 100 - (rep.ping_ms // 20)))
                        row = {
                            "scan_type": "repository",
                            "rank": 1,
                            "target_index": idx,
                            "uid": node.uid,
                            "item_id": node.uid,
                            "bound_vector": vec.vector_id,
                            "title": node.name,
                            "category": node.protocol,
                            "endpoint": ep,
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": rep.ping_ms,
                            "status": "VERIFIED",
                            "score": sc,
                            "detail": f"متد بهینه: {vec.vector_id} ({vec.code_name})",
                        }
                        ranked_repo_rows.append(row)
                        self._emit_scan_row(row)
                        break

                if not node_passed:
                    node.health_status = "DEAD"
                    node.last_ping_ms = -1
                    dead_count += 1
                    row = {
                        "scan_type": "repository",
                        "rank": 999,
                        "target_index": idx,
                        "uid": node.uid,
                        "item_id": node.uid,
                        "bound_vector": "",
                        "title": node.name,
                        "category": node.protocol,
                        "endpoint": ep,
                        "tcp_ms": tcp_ms,
                        "tunnel_ms": -1,
                        "status": "DEAD",
                        "score": 0,
                        "detail": "عدم پاسخ تونل در تمام متدها",
                    }
                    ranked_repo_rows.append(row)
                    self._emit_scan_row(row)

            self.xray.stop()
            if self._is_op_cancelled(gen_id):
                return

            if prune_dead and (verified_count > 0):
                self.remove_dead_configs()
            self.sort_configs("ping")

            with self._repo_lock:
                uid_index_map = {p.uid: i for i, p in enumerate(self.profiles)}

            ranked_repo_rows = [r for r in ranked_repo_rows if ((not prune_dead) or (r["uid"] in uid_index_map))]
            for r_item in ranked_repo_rows:
                r_item["target_index"] = uid_index_map.get(r_item["uid"], -1)

            ranked_repo_rows.sort(
                key=lambda r: (
                    0 if (r["status"] == "VERIFIED") else 1,
                    -r["score"],
                    r["tunnel_ms"] if (r["tunnel_ms"] > 0) else 999999,
                )
            )
            for rk, r_item in enumerate(ranked_repo_rows, 1):
                r_item["rank"] = rk
            self._emit_scan_ranked(ranked_repo_rows)

            self._set_state(EngineState.DISCONNECTED, "آماده اتصال", f"{verified_count} پروفایل سالم تایید و مرتب شد", 0)
            self._emit_scan_progress(100, f"اتمام اسکن مخزن — سالم: {verified_count} | ناموفق: {dead_count}")
            self._emit_scan_state(False, f"نتیجه اسکن مخزن: {verified_count} سالم از {total} کانفیگ")
        except Exception as exc:
            self.emit_log(f"[RepoScan] Error: {exc}")
            self._emit_scan_state(False, f"خطا در اسکن مخزن: {exc}")

    def toggle_connection(self, uri: str = ""):
        if self.snapshot.is_connecting or self.snapshot.is_connected:
            self.request_disconnect()
        else:
            self.request_connect(uri)

    def _teardown_active_tunnel_sync(self):
        with self._state_lock:
            self._op_generation += 1
            self._abort_flag = True
        self.tun.stop()
        SystemProxyController.apply(False, self.settings.http_port)
        self.bridge.drop_active_connections()
        self.xray.stop()

    def request_connect(self, uri: str = ""):
        if self.snapshot.is_connecting and (not uri):
            self.request_disconnect()
            return

        clean_uri = uri.strip() if isinstance(uri, str) else ""
        if clean_uri:
            with self._repo_lock:
                matched_idx = next((i for i, p in enumerate(self.profiles) if p.uri == clean_uri), -1)
                if matched_idx >= 0:
                    self.selected_index = matched_idx
                else:
                    try:
                        new_node = UriConfigCodec.extract_profile_node(clean_uri, group_tag="QuickConnect")
                        self.profiles.insert(0, new_node)
                        self.selected_index = 0
                    except Exception as exc:
                        self._set_state(EngineState.ERROR, "خطا در ساختار کانفیگ", str(exc), 0)
                        return
            self._save_profiles(self.profiles)
            self._notify_profiles_updated(save_selection=True)

        with self._repo_lock:
            if not self.profiles:
                self._set_state(EngineState.ERROR, "مخزن خالی است", "ابتدا یک کانفیگ اضافه کنید", 0)
                return
            self.selected_index = max(0, min(self.selected_index, len(self.profiles) - 1))
            target_node = self.profiles[self.selected_index]

        self._persist_active_selection(save_disk=True)

        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._abort_flag = False
            self._scan_abort_flag = False
            self._task_abort_flag = False

        self._set_state(
            EngineState.FAST_RESUME,
            "در حال آغاز اتصال هوشمند...",
            f"آماده‌سازی پروفایل «{target_node.name}» (برای لغو کلیک کنید)",
            progress=6,
        )
        self._worker_thread = threading.Thread(
            target=self._execute_autopilot_pipeline,
            args=(gen_id, target_node),
            daemon=True,
        )
        self._worker_thread.start()

    def request_disconnect(self):
        with self._state_lock:
            self._op_generation += 1
            self._abort_flag = True
            self._scan_abort_flag = True
            self._task_abort_flag = True

        self.snapshot.egress_ip = "---"
        self.snapshot.endpoint_ip = "---"
        self.snapshot.ping_ms = -1
        self.snapshot.tx_rate_kbps = 0.0
        self.snapshot.rx_rate_kbps = 0.0
        self.snapshot.tx_rate_label = "0 B/s"
        self.snapshot.rx_rate_label = "0 B/s"
        self._set_state(EngineState.DISCONNECTED, "اتصال قطع است", "آماده برقراری تونل هوشمند", progress=0)
        self._emit_task_progress(False, 0, "متوقف شد")

        def _async_teardown():
            self.tun.stop()
            SystemProxyController.apply(False, self.settings.http_port)
            self.bridge.drop_active_connections()
            self.xray.stop()
            self.emit_log("[AutoPilot] Tunnel stopped and routes restored.")

        threading.Thread(target=_async_teardown, daemon=True).start()

    def shutdown(self):
        with self._state_lock:
            self._op_generation += 1
            self._shutdown_flag = True
            self._abort_flag = True
            self._scan_abort_flag = True
            self._task_abort_flag = True
        self.tun.stop()
        SystemProxyController.apply(False, self.settings.http_port)
        self.bridge.stop()
        self.xray.stop()

    def _execute_autopilot_pipeline(self, gen_id: int, node: ProfileNode):
        try:
            self.bridge.reset_counters()
            self._prev_tx_bytes = 0
            self._prev_rx_bytes = 0
            self.snapshot.active_profile_uid = node.uid
            self.snapshot.active_profile_name = node.name
            self.snapshot.protocol_label = node.protocol

            use_native_xray_frag = bool(self.settings.fragment_enabled and (not self.settings.autopilot_enabled))

            try:
                self.xray.ensure_running(
                    uri=node.uri,
                    settings=self.settings,
                    use_native_fragment=use_native_xray_frag,
                )
            except Exception as exc:
                if not self._is_op_cancelled(gen_id):
                    self._set_state(EngineState.ERROR, "خطا در اجرای هسته Xray", str(exc), 0)
                return

            if self._is_op_cancelled(gen_id):
                return

            if not self.settings.autopilot_enabled:
                default_vec_id = (
                    "VEC-00"
                    if CleanIpScanner.is_domestic_or_direct_tunnel(node)
                    else (node.cached_vector_id or self.settings.manual_vector_id)
                )
                vec = find_vector(default_vec_id)
                ep = node.cached_clean_ip if node.cached_clean_ip else node.original_host
                self._set_state(EngineState.VERIFYING_STABILITY, "در حال اتصال مستقیم...", f"مسیر {ep}", 65)
                self.bridge.update_route(
                    remote_host=ep,
                    remote_port=node.port,
                    vector=vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=use_native_xray_frag,
                    flush_existing_pool=True,
                )
                rep = TunnelStreamVerifier.quick_ping(http_port=self.settings.http_port, timeout=4.5)
                if not self._is_op_cancelled(gen_id):
                    self._lock_winning_tunnel(
                        gen_id, node, ep, vec, rep.ping_ms if rep.passed else -1, raw_passthrough=use_native_xray_frag
                    )
                return

            soft_winners: List[Tuple[int, str, BypassVector]] = []

            if node.cached_vector_id:
                cached_vec = find_vector(node.cached_vector_id)
                cached_ep = node.cached_clean_ip if node.cached_clean_ip else node.original_host
                self._set_state(EngineState.FAST_RESUME, "اتصال سریع هوشمند...", f"آزمایش مسیر بهینه ({cached_ep})", 20)
                self.bridge.update_route(
                    remote_host=cached_ep,
                    remote_port=node.port,
                    vector=cached_vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=False,
                    flush_existing_pool=True,
                )
                fast_rep = TunnelStreamVerifier.fast_probe(http_port=self.settings.http_port, timeout=3.0)
                if self._is_op_cancelled(gen_id):
                    return
                if fast_rep.passed:
                    soft_winners.append((fast_rep.ping_ms, cached_ep, cached_vec))
                    self._set_state(
                        EngineState.VERIFYING_STABILITY,
                        "تایید پایداری استریم...",
                        f"پینگ اولیه {fast_rep.ping_ms}ms — بررسی سلامت تونل",
                        75,
                    )
                    qual = TunnelStreamVerifier.run_full_qualification(
                        http_port=self.settings.http_port,
                        verify_upload=self.settings.verify_upload_stream,
                        require_youtube_6s=self.settings.require_youtube_6s,
                        base_rtt_ms=fast_rep.ping_ms,
                        abort_check=lambda: self._is_op_cancelled(gen_id),
                        log_fn=self.emit_log,
                    )
                    if self._is_op_cancelled(gen_id):
                        return
                    if qual.passed:
                        self._lock_winning_tunnel(gen_id, node, cached_ep, cached_vec, qual.ping_ms, raw_passthrough=False)
                        return

            candidate_endpoints: List[str] = []
            if node.original_host:
                orig_ms = CleanIpScanner.fast_tcp_ping(node.original_host, node.port, timeout=1.6)
                if orig_ms >= 0:
                    candidate_endpoints.append(node.original_host)

            if self.settings.auto_clean_ip and CleanIpScanner.is_cdn_eligible(node):
                self._set_state(EngineState.SCANNING_CLEAN_IP, "جستجوی خودکار IP تمیز...", "کاوش موازی رنج‌های CDN", 28)
                discovered = CleanIpScanner.discover_best_ips(
                    port=node.port,
                    top_n=3,
                    sample_count=36,
                    log_fn=self.emit_log,
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                )
                clean_ips = [ip_addr for ip_addr, _ in discovered if ip_addr not in candidate_endpoints]
                candidate_endpoints = clean_ips + candidate_endpoints

            if (not candidate_endpoints) and bool(node.original_host):
                candidate_endpoints.append(node.original_host)

            vectors_to_try = self._build_vector_plan(node, self.settings.engine_mode)
            total_steps = max(1, len(candidate_endpoints) * len(vectors_to_try))
            step_counter = 0

            for endpoint in candidate_endpoints:
                if self._is_op_cancelled(gen_id):
                    return
                if CleanIpScanner.fast_tcp_ping(endpoint, node.port, timeout=2.0) < 0:
                    step_counter += len(vectors_to_try)
                    continue

                for vec in vectors_to_try:
                    if self._is_op_cancelled(gen_id):
                        return
                    step_counter += 1
                    pct = 32 + int((step_counter / total_steps) * 62)
                    self._set_state(
                        EngineState.PROBING_VECTORS,
                        "تنظیم خودکار موتور عبوری...",
                        f"آزمایش {vec.code_name} روی {endpoint}",
                        progress=pct,
                    )

                    self.bridge.update_route(
                        remote_host=endpoint,
                        remote_port=node.port,
                        vector=vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=False,
                        flush_existing_pool=True,
                    )

                    q_ping = TunnelStreamVerifier.fast_probe(http_port=self.settings.http_port, timeout=2.8)
                    if self._is_op_cancelled(gen_id):
                        return
                    if not q_ping.passed:
                        continue

                    soft_winners.append((q_ping.ping_ms, endpoint, vec))
                    self._set_state(
                        EngineState.VERIFYING_STABILITY,
                        "تست پایداری ۶ ثانیه‌ای و آپلود...",
                        f"پینگ اولیه {q_ping.ping_ms}ms — تایید سلامت استریم",
                        progress=min(96, pct + 4),
                    )
                    full_rep = TunnelStreamVerifier.run_full_qualification(
                        http_port=self.settings.http_port,
                        verify_upload=self.settings.verify_upload_stream,
                        require_youtube_6s=self.settings.require_youtube_6s,
                        base_rtt_ms=q_ping.ping_ms,
                        abort_check=lambda: self._is_op_cancelled(gen_id),
                        log_fn=self.emit_log,
                    )
                    if self._is_op_cancelled(gen_id):
                        return
                    if full_rep.passed:
                        self._lock_winning_tunnel(gen_id, node, endpoint, vec, full_rep.ping_ms, raw_passthrough=False)
                        return

                    if len(soft_winners) >= 2:
                        soft_winners.sort(key=lambda x: x[0])
                        best_ping, best_ep, best_v = soft_winners[0]
                        self.bridge.update_route(
                            remote_host=best_ep,
                            remote_port=node.port,
                            vector=best_v,
                            custom_stride=self.settings.forward_stride_bytes,
                            jitter_bytes=self.settings.stride_jitter_bytes,
                            raw_passthrough=False,
                            flush_existing_pool=True,
                        )
                        self._lock_winning_tunnel(gen_id, node, best_ep, best_v, best_ping, raw_passthrough=False)
                        return

            if self._is_op_cancelled(gen_id):
                return

            if soft_winners:
                soft_winners.sort(key=lambda x: x[0])
                best_ping, best_ep, best_v = soft_winners[0]
                self.bridge.update_route(
                    remote_host=best_ep,
                    remote_port=node.port,
                    vector=best_v,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=False,
                    flush_existing_pool=True,
                )
                self._lock_winning_tunnel(gen_id, node, best_ep, best_v, best_ping, raw_passthrough=False)
                return

            self.xray.stop()
            node.health_status = "DEAD"
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self._set_state(EngineState.ERROR, "مسیر پایداری یافت نشد", "سلامت کانفیگ یا اینترنت را بررسی کنید", 0)
        except Exception as exc:
            self.emit_log(f"[AutoPilot] Pipeline exception: {exc}")
            if not self._is_op_cancelled(gen_id):
                self._set_state(EngineState.ERROR, "خطای داخلی موتور اتصال", str(exc), 0)

    def _lock_winning_tunnel(
        self,
        gen_id: int,
        node: ProfileNode,
        endpoint_ip: str,
        vec: BypassVector,
        ping_ms: int,
        raw_passthrough: bool = False,
    ):
        if self._is_op_cancelled(gen_id):
            return

        self.bridge.reset_counters()
        self._prev_tx_bytes = 0
        self._prev_rx_bytes = 0

        node.cached_vector_id = vec.vector_id
        node.cached_clean_ip = endpoint_ip if (endpoint_ip != node.original_host) else ""
        node.last_ping_ms = ping_ms
        node.health_status = "VERIFIED"
        node.last_tested_ts = int(time.time())
        self._save_profiles(self.profiles)
        self._notify_profiles_updated(save_selection=True)

        if self.settings.system_proxy_enabled:
            SystemProxyController.apply(True, self.settings.http_port)

        self.snapshot.endpoint_ip = endpoint_ip
        self.snapshot.active_vector_id = "FRAG" if raw_passthrough else vec.vector_id
        self.snapshot.active_vector_name = (
            f"Native Fragment ({self.settings.fragment_length})" if raw_passthrough else vec.code_name
        )
        self.snapshot.ping_ms = ping_ms

        self._set_state(
            EngineState.CONNECTED,
            "VPN متصل است",
            f"{self.snapshot.active_vector_name} | لبه: {endpoint_ip}",
            progress=100,
        )

        if self.settings.tun_enabled:
            threading.Thread(target=self._activate_tun_async, args=(endpoint_ip,), daemon=True).start()

        def _resolve_ip_bg():
            egress = TunnelStreamVerifier.resolve_egress_ip(http_port=self.settings.http_port)
            if (not self._is_op_cancelled(gen_id)) and self.snapshot.is_connected:
                with self._state_lock:
                    self.snapshot.egress_ip = egress
                self._push_telemetry()

        threading.Thread(target=_resolve_ip_bg, daemon=True).start()

    def _telemetry_ticker_loop(self):
        while not self._shutdown_flag:
            time.sleep(1.0)
            now = time.perf_counter()
            dt = max(0.1, now - self._prev_tick_ts)
            self._prev_tick_ts = now

            tx_cur = self.bridge.tx_bytes_total
            rx_cur = self.bridge.rx_bytes_total

            with self._state_lock:
                connected = self.snapshot.is_connected
                since = self._connected_since_ts

            if connected:
                tx_delta = max(0, tx_cur - self._prev_tx_bytes)
                rx_delta = max(0, rx_cur - self._prev_rx_bytes)
                tx_kbps = round((tx_delta / 1024.0) / dt, 2)
                rx_kbps = round((rx_delta / 1024.0) / dt, 2)
                up_sec = int(max(0.0, now - since)) if (since is not None) else 0
            else:
                tx_kbps = 0.0
                rx_kbps = 0.0
                up_sec = 0

            self._prev_tx_bytes = tx_cur
            self._prev_rx_bytes = rx_cur

            with self._state_lock:
                self.snapshot.tx_rate_kbps = tx_kbps
                self.snapshot.rx_rate_kbps = rx_kbps
                self.snapshot.tx_rate_label = format_byte_rate(tx_kbps)
                self.snapshot.rx_rate_label = format_byte_rate(rx_kbps)
                self.snapshot.tx_total_bytes = tx_cur if connected else 0
                self.snapshot.rx_total_bytes = rx_cur if connected else 0
                self.snapshot.active_sessions = self.bridge.active_session_count if connected else 0
                self.snapshot.uptime_seconds = up_sec
                self.snapshot.uptime_label = format_uptime_hms(up_sec)
                self.snapshot.tun_enabled = self.settings.tun_enabled
                self.snapshot.tun_active = self.tun.is_active
                self.snapshot.selected_index = self.selected_index

            self._push_telemetry()

    def _self_healing_watchdog_loop(self):
        missed = 0
        while not self._shutdown_flag:
            time.sleep(18.0)
            if (not self.snapshot.is_connected) or (not self.settings.self_healing_watchdog):
                missed = 0
                continue
            if self.snapshot.rx_rate_kbps > 1.5:
                missed = 0
                continue

            rep = TunnelStreamVerifier.quick_ping(http_port=self.settings.http_port, timeout=4.2)
            if rep.passed:
                missed = 0
                with self._state_lock:
                    self.snapshot.ping_ms = rep.ping_ms
            else:
                missed += 1
                if (missed >= 2) and self.snapshot.is_connected:
                    missed = 0
                    with self._repo_lock:
                        has_profiles = bool(self.profiles)
                        active_node = self.profiles[self.selected_index] if has_profiles else None
                    worker_idle = (self._worker_thread is None) or (not self._worker_thread.is_alive())
                    if (active_node is not None) and worker_idle:
                        active_node.cached_vector_id = ""
                        with self._state_lock:
                            self._op_generation += 1
                            gen_id = self._op_generation
                            self._abort_flag = False
                        self._set_state(EngineState.RECOVERING, "ترمیم خودکار مسیر...", "سوییچ خودکار به مسیر جایگزین", 35)
                        self._worker_thread = threading.Thread(
                            target=self._execute_autopilot_pipeline, args=(gen_id, active_node), daemon=True
                        )
                        self._worker_thread.start()