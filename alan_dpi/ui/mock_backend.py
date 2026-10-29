import math
import random
from datetime import datetime
from PySide6.QtCore import QObject, QTimer, Signal


class BackendControllerAdapter(QObject):
    """Standard Qt Signal/Slot contract between UI and Alan-RIP-Dpi engine."""

    telemetry_updated = Signal(dict)
    log_emitted = Signal(str)
    profiles_changed = Signal(list, int)

    def request_connect(self, uri: str) -> None:
        raise NotImplementedError

    def request_disconnect(self) -> None:
        raise NotImplementedError

    def update_settings(self, settings_dict: dict) -> None:
        raise NotImplementedError

    def import_configs(self, raw_text: str) -> None:
        raise NotImplementedError

    def delete_config(self, index: int) -> None:
        raise NotImplementedError

    def select_config(self, index: int) -> None:
        raise NotImplementedError


class MockDpiController(BackendControllerAdapter):
    """Built-in interactive simulator for standalone testing before backend hookup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles = [
            {
                "name": "Alan Clean-Edge #01",
                "protocol": "VLESS-WS-TLS",
                "endpoint": "104.18.36.214:443",
                "uri": "vless://01@104.18.36.214:443?security=tls&type=ws#Alan-Edge-01",
            },
            {
                "name": "Alan Multi-Range #02",
                "protocol": "TROJAN-GRPC",
                "endpoint": "172.67.142.88:443",
                "uri": "trojan://02@172.67.142.88:443?security=tls&type=grpc#Alan-Edge-02",
            },
        ]
        self._active_index = 0
        self._state = "disconnected"
        self._scan_step = 0
        self._tick_counter = 0
        self._settings = {"autopilot": True, "manual_vector": "VEC-01"}

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(950)
        self._scan_timer.timeout.connect(self._advance_scan_pipeline)

        self._live_timer = QTimer(self)
        self._live_timer.setInterval(650)
        self._live_timer.timeout.connect(self._emit_live_metrics)
        self._live_timer.start()

    def bootstrap(self):
        self.profiles_changed.emit(self._profiles, self._active_index)
        self._log("Alan-RIP-Dpi UI engine ready. AutoPilot standby.")
        self._emit_snapshot(
            state="disconnected",
            headline="قطع است",
            detail="برای اسکن خودکار IP تمیز و اتصال با یک کلیک، دکمه اتصال هوشمند را بزنید.",
            progress=0,
        )

    def get_active_uri(self) -> str:
        if 0 <= self._active_index < len(self._profiles):
            return self._profiles[self._active_index]["uri"]
        return ""

    def request_connect(self, uri: str) -> None:
        self._state = "connecting"
        self._scan_step = 0
        self._log(f"Starting AutoPilot pipeline for URI: {uri[:46]}...")
        self._advance_scan_pipeline()
        self._scan_timer.start()

    def request_disconnect(self) -> None:
        self._scan_timer.stop()
        self._state = "disconnected"
        self._log("Tunnel terminated cleanly. System proxy restored.")
        self._emit_snapshot(
            state="disconnected",
            headline="قطع است",
            detail="اتصال متوقف شد. آماده برقراری مجدد با یک کلیک.",
            progress=0,
        )

    def update_settings(self, settings_dict: dict) -> None:
        self._settings.update(settings_dict)
        summary = ", ".join(f"{k}={v}" for k, v in list(settings_dict.items())[:4])
        self._log(f"Settings updated -> {summary}")

    def import_configs(self, raw_text: str) -> None:
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        added = 0
        for ln in lines:
            proto = ln.split("://")[0].upper() if "://" in ln else "VLESS"
            tag = ln.split("#")[-1] if "#" in ln else f"Alan Node #{len(self._profiles) + 1}"
            self._profiles.append({
                "name": tag[:32],
                "protocol": f"{proto}-TLS",
                "endpoint": "auto-clean-range:443",
                "uri": ln,
            })
            added += 1
        if added:
            self._active_index = len(self._profiles) - 1
            self.profiles_changed.emit(self._profiles, self._active_index)
            self._log(f"Imported {added} config(s) into repository.")

    def delete_config(self, index: int) -> None:
        if 0 <= index < len(self._profiles):
            removed = self._profiles.pop(index)
            self._active_index = max(0, min(self._active_index, len(self._profiles) - 1))
            self.profiles_changed.emit(self._profiles, self._active_index)
            self._log(f"Removed profile: {removed['name']}")

    def select_config(self, index: int) -> None:
        if 0 <= index < len(self._profiles):
            self._active_index = index
            self.profiles_changed.emit(self._profiles, self._active_index)
            self._log(f"Selected active profile: {self._profiles[index]['name']}")

    def _advance_scan_pipeline(self):
        stages = [
            (24, "اسکن موازی ۴ رنج IP تمیز (RTT < 65ms)..."),
            (52, "اسکن رنج IP تمیز <- تست متد عبوری (Adaptive Split +400B)..."),
            (81, "تست متد عبوری <- بررسی بقای ۶ ثانیه‌ای یوتیوب و سلامت آپلود..."),
            (100, "مسیر تمیز تایید شد. فعال‌سازی تونل پایدار..."),
        ]
        if self._scan_step < len(stages):
            prog, detail = stages[self._scan_step]
            self._log(f"[Stage {self._scan_step + 1}/4] {detail}")
            self._emit_snapshot(
                state="connecting",
                headline="در حال یافتن بهترین مسیر...",
                detail=detail,
                progress=prog,
            )
            self._scan_step += 1
        else:
            self._scan_timer.stop()
            self._state = "connected"
            vec = "VEC-01" if self._settings.get("autopilot", True) else self._settings.get("manual_vector", "VEC-01")
            self._log(f"Tunnel established via clean IP 104.18.39.112 | Active Vector: {vec}")
            self._emit_snapshot(
                state="connected",
                headline="متصل است",
                detail="مسیر عبوری پایدار است • پایش خودکار پس‌زمینه (Self-Healing) فعال",
                egress="104.18.39.112",
                vector=vec,
                ping=44,
                rx=1840.0,
                tx=420.0,
                progress=100,
            )

    def _emit_live_metrics(self):
        self._tick_counter += 1
        if self._state != "connected":
            return
        wave = math.sin(self._tick_counter * 0.45)
        rx = max(120.0, 2450.0 + wave * 1350.0 + random.uniform(-260, 420))
        tx = max(45.0, 540.0 + math.cos(self._tick_counter * 0.35) * 260.0 + random.uniform(-80, 120))
        ping = int(max(32, 46 + math.sin(self._tick_counter * 0.25) * 7 + random.uniform(-3, 4)))
        vec = "VEC-01" if self._settings.get("autopilot", True) else self._settings.get("manual_vector", "VEC-01")

        self._emit_snapshot(
            state="connected",
            headline="متصل است",
            detail="مسیر عبوری پایدار است • یوتیوب و آپلود تایید شده • Self-Healing فعال",
            egress="104.18.39.112",
            vector=vec,
            ping=ping,
            rx=rx,
            tx=tx,
            progress=100,
        )

    def _emit_snapshot(
        self,
        state: str,
        headline: str,
        detail: str,
        egress: str = "—",
        vector: str = "VEC-AUTO",
        ping: int = 0,
        rx: float = 0.0,
        tx: float = 0.0,
        progress: int = 0,
    ):
        self.telemetry_updated.emit({
            "state": state,
            "status_headline": headline,
            "status_detail": detail,
            "egress_ip": egress,
            "active_vector_id": vector,
            "ping_ms": ping,
            "tx_rate_kbps": tx,
            "rx_rate_kbps": rx,
            "progress_percent": progress,
        })

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_emitted.emit(f"[{ts}] {msg}")