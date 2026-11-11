import queue
import threading
from typing import Any, List, Optional
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from alan_dpi.engine.autopilot import AlanAutoPilotEngine


SUPPORTED_FINGERPRINTS: List[str] = [
    "custom_poly",
    "random",
    "chrome",
    "firefox",
    "safari",
    "ios",
    "edge",
    "qq",
    "android",
    "360",
]


class AlanQtBackendController(QObject):
    telemetry_updated = Signal(dict)
    log_emitted = Signal(str)
    profiles_updated = Signal(list, int)
    verified_outputs_updated = Signal(list)
    settings_updated = Signal(dict)
    subscriptions_updated = Signal(list)
    scan_row_emitted = Signal(dict)
    scan_results_ranked = Signal(list)
    scan_progress_updated = Signal(int, str)
    scan_state_changed = Signal(bool, str)
    task_progress_updated = Signal(bool, int, str)
    tun_status_changed = Signal(bool, bool, str)
    auto_locations_updated = Signal(list, str)

    def __init__(self, base_dir: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._ui_queue: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()
        self._ui_pump = QTimer(self)
        self._ui_pump.setInterval(25)
        self._ui_pump.timeout.connect(self._drain_ui_queue)
        self._ui_pump.start()

        self.engine = AlanAutoPilotEngine(base_dir=base_dir)
        self.engine.on_telemetry = lambda d: self._post_ui(self.telemetry_updated, d)
        self.engine.on_log = lambda s: self._post_ui(self.log_emitted, s)
        self.engine.on_profiles = lambda p, i: self._post_ui(self.profiles_updated, list(p), int(i))
        self.engine.on_verified_outputs = lambda v: self._post_ui(self.verified_outputs_updated, list(v))
        self.engine.on_settings = lambda s: self._post_ui(self.settings_updated, dict(s))
        self.engine.on_subscriptions = lambda sb: self._post_ui(self.subscriptions_updated, list(sb))
        self.engine.on_scan_row = lambda r: self._post_ui(self.scan_row_emitted, dict(r))
        self.engine.on_scan_ranked = lambda rs: self._post_ui(self.scan_results_ranked, list(rs))
        self.engine.on_scan_progress = lambda p, m: self._post_ui(self.scan_progress_updated, int(p), str(m))
        self.engine.on_scan_state = lambda b, m: self._post_ui(self.scan_state_changed, bool(b), str(m))
        self.engine.on_task_progress = lambda a, p, m: self._post_ui(self.task_progress_updated, bool(a), int(p), str(m))
        self.engine.on_tun_status = lambda e, a, d: self._post_ui(self.tun_status_changed, bool(e), bool(a), str(d))
        self.engine.on_auto_locations = lambda locs, sel: self._post_ui(self.auto_locations_updated, list(locs), str(sel))
        self.engine.on_request_quit = lambda: self._ui_queue.put(("__QUIT__", ()))

    def _post_ui(self, sig, *args):
        self._ui_queue.put((sig, args))

    def _drain_ui_queue(self):
        for _ in range(80):
            try:
                sig, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if sig == "__QUIT__":
                self.quit_application()
                return
            try:
                sig.emit(*args)
            except Exception as exc:
                print(f"[UI Signal Warning] {exc}")

    def discover_system_apps(self) -> list:
        return self.engine.discover_system_apps()

    def launch_tunneled_app(self, exe_path_or_name: str, extra_args: str = "") -> tuple:
        return self.engine.launch_tunneled_app(exe_path_or_name, extra_args=extra_args)

    def get_doh_repositories(self) -> list:
        return self.engine.get_doh_repositories()

    def add_doh_custom(self, url_or_text: str, title: str = "Custom DoH") -> int:
        return self.engine.add_doh_custom(url_or_text, title=title)

    def start_doh_scan(self):
        self.engine.start_doh_scan()

    def apply_doh_to_tunnel_dns(self, doh_url: str):
        self.engine.apply_doh_to_tunnel_dns(doh_url)

    def toggle_system_doh_veil(self, enabled: bool, doh_url: str = "") -> tuple:
        return self.engine.toggle_system_doh_veil(bool(enabled), doh_url=str(doh_url or ""))

    def get_auto_locations(self) -> list:
        return self.engine.get_available_auto_locations()

    def get_selected_auto_location(self) -> str:
        return self.engine.get_selected_auto_location()

    def set_auto_location(self, location_code: str):
        self.engine.set_auto_location(str(location_code or "ALL"))

    def refresh_auto_pool(self):
        threading.Thread(target=self.engine._sync_hidden_auto_pool, daemon=True).start()

    def hunt_subscription_and_connect(self, sub_url_or_title: Any = "", title: str = ""):
        self.engine.hunt_subscription_and_connect(sub_url_or_title=sub_url_or_title, title=title)

    def scan_subscription_and_connect(self, sub_url_or_title: Any = "", title: str = ""):
        self.engine.hunt_subscription_and_connect(sub_url_or_title=sub_url_or_title, title=title)

    def get_vectors(self) -> list:
        return self.engine.get_vectors_as_dicts()

    def get_fingerprints(self) -> list:
        return list(SUPPORTED_FINGERPRINTS)

    def get_settings(self) -> dict:
        return self.engine.get_settings_as_dict()

    def get_telemetry_snapshot(self) -> dict:
        return self.engine.get_telemetry_snapshot()

    def update_settings(self, new_dict: dict):
        self.engine.update_settings(new_dict)

    def set_setting_value(self, key: str, value: Any):
        self.engine.set_single_setting(key, value)

    def toggle_connection(self, uri: str = ""):
        self.engine.toggle_connection(uri)

    def request_connect(self, uri: str = ""):
        self.engine.request_connect(uri)

    def request_disconnect(self):
        self.engine.request_disconnect()

    def hunt_best_and_connect(self):
        self.engine.hunt_best_and_connect()

    def set_system_proxy(self, enabled: bool):
        self.engine.set_system_proxy(enabled)

    def set_tun_mode(self, enabled: bool):
        self.engine.set_tun_mode(enabled)

    def get_profiles(self) -> list:
        return self.engine.get_profiles_as_dicts()

    def get_verified_outputs(self) -> list:
        return [v.to_dict() for v in self.engine.verified_outputs]

    def get_selected_index(self) -> int:
        return self.engine.get_selected_index()

    def select_config(self, index_or_uid: Any):
        self.engine.select_config(index_or_uid)

    def import_configs(self, raw_text: str, group_tag: str = "Manual") -> int:
        return self.engine.import_configs(raw_text, group_tag=group_tag)

    def import_configs_from_file(self, file_path: str) -> int:
        return self.engine.import_configs_from_file(file_path)

    def rename_config(self, index_or_uid: Any, new_name: str):
        self.engine.rename_config(index_or_uid, new_name)

    def clone_config_with_clean_ips(self, index_or_uid: Any, clone_count: int = 3):
        self.engine.clone_config_with_clean_ips(index_or_uid, clone_count=clone_count)

    def delete_configs(self, uid_list: list) -> int:
        return self.engine.delete_configs(uid_list)

    def delete_config(self, index_or_uid: Any) -> int:
        return self.engine.delete_config(index_or_uid)

    def clear_all_configs(self) -> int:
        return self.engine.clear_all_configs()

    def deduplicate_configs(self) -> int:
        return self.engine.deduplicate_configs()

    def remove_dead_configs(self) -> int:
        return self.engine.remove_dead_configs()

    def sort_configs(self, sort_by: str = "ping"):
        self.engine.sort_configs(sort_by=sort_by)

    def ping_configs(self, uid_list: Optional[Any] = None, *args, **kwargs):
        self.engine.ping_configs(uid_list=uid_list, check_gemini=False)

    def ping_single_config(self, uid_or_index: Any, *args, **kwargs):
        self.engine.ping_configs(uid_list=[uid_or_index], check_gemini=False)

    def ping_profile(self, uid_or_index: Any, *args, **kwargs):
        self.engine.ping_configs(uid_list=[uid_or_index], check_gemini=False)

    def real_delay_ping(self, uid_or_index: Optional[Any] = None, *args, **kwargs):
        self.engine.ping_configs(uid_list=uid_or_index, check_gemini=False)

    def quick_ping_configs(self, *args, **kwargs):
        self.engine.quick_ping_repository()

    def probe_gemini_configs(self, uid_list: Optional[Any] = None, *args, **kwargs):
        self.engine.ping_configs(uid_list=uid_list, check_gemini=True)

    def export_configs(self, mode: str = "verified", inject_early_data: int = 0) -> str:
        return self.engine.export_configs(mode=mode, inject_early_data=int(inject_early_data))

    def get_config_editable(self, index_or_uid: Any) -> dict:
        return self.engine.get_config_editable(index_or_uid)

    def save_config_editable(self, index_or_uid: Any, data_dict: dict) -> bool:
        return self.engine.save_config_editable(index_or_uid, data_dict)

    def get_subscriptions(self) -> list:
        return self.engine.get_subscriptions_as_dicts()

    def add_subscription(self, url: str, title: str = "Subscription"):
        self.engine.add_subscription(url=url, title=title)

    def refresh_subscriptions(self):
        self.engine.refresh_all_subscriptions()

    def delete_subscription(self, index: int):
        self.engine.delete_subscription(int(index))

    def connect_verified_output(self, uid_or_index: Any):
        self.engine.connect_verified_output(uid_or_index)

    def ping_verified_outputs(self):
        self.engine.ping_verified_outputs()

    def clear_verified_outputs(self):
        self.engine.clear_verified_outputs()

    def start_lab_scan(
        self,
        scope: str = "selected",
        uid_list: Optional[list] = None,
        group_tag: str = "",
        scan_depth: str = "all",
        target_vector: str = "ALL",
        check_gemini: bool = False,
        auto_connect: bool = False,
    ):
        self.engine.start_lab_scan(
            scope=scope,
            uid_list=uid_list,
            group_tag=group_tag,
            scan_depth=scan_depth,
            target_vector=target_vector,
            check_gemini=bool(check_gemini),
            auto_connect=bool(auto_connect),
        )

    def start_clean_ip_scan(self, port: int = 443):
        self.engine.start_clean_ip_scan(port=int(port))

    def start_dedicated_scan(self, mode: str = "active_profile", target_index: Any = -1, options: Optional[dict] = None):
        self.engine.start_dedicated_scan(mode=mode, target_index=target_index, options=options)

    def start_scanner(
        self,
        mode: str = "active_profile",
        target_index: int = -1,
        auto_connect: bool = False,
        prune_dead: bool = False,
        port: int = 443,
        target_vector: str = "ALL",
    ):
        self.engine.start_dedicated_scan(
            mode=mode,
            target_index=target_index,
            options={
                "auto_connect": auto_connect,
                "prune_dead": prune_dead,
                "port": port,
                "target_vector": target_vector,
            },
        )

    def stop_scanner(self):
        self.engine.stop_dedicated_scan()

    def apply_clean_ip(self, ip_addr: str, apply_all_cdn: bool = True) -> int:
        return self.engine.apply_clean_ip(ip_addr=ip_addr, apply_all_cdn=bool(apply_all_cdn))

    def bind_vector_to_profile(self, vector_id: str, target_index: Any = -1, clean_ip: str = "", connect_now: bool = False):
        self.engine.bind_vector_to_profile(vector_id, target_index=target_index, clean_ip=clean_ip, connect_now=connect_now)

    def apply_scanned_vector(self, vector_id: str, target_uid: str = "", connect_now: bool = False):
        self.engine.apply_scanned_vector(vector_id=vector_id, target_uid=str(target_uid), connect_now=bool(connect_now))

    def apply_vector_to_all_configs(self, vector_id: str, clean_ip: str = "") -> int:
        return self.engine.apply_vector_to_all_configs(vector_id=vector_id, clean_ip=clean_ip)

    def connect_scanned_profile(self, target_index_or_uid: Any, vector_id: str = "", clean_ip: str = ""):
        self.engine.connect_scanned_profile(target_index_or_uid, vector_id=vector_id, clean_ip=clean_ip)

    def quit_application(self):
        self._ui_pump.stop()
        self.engine.shutdown()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def shutdown(self):
        self._ui_pump.stop()
        self.engine.shutdown()
