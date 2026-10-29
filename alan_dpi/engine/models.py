import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List


APP_NAME = "Alan-RIP-Dpi"
APP_VERSION = "1.0.0"


class EngineState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    FAST_RESUME = "FAST_RESUME"
    SCANNING_CLEAN_IP = "SCANNING_CLEAN_IP"
    PROBING_VECTORS = "PROBING_VECTORS"
    SCANNING_REPOSITORY = "SCANNING_REPOSITORY"
    HUNTING_BEST = "HUNTING_BEST"
    VERIFYING_STABILITY = "VERIFYING_STABILITY"
    CONNECTED = "CONNECTED"
    RECOVERING = "RECOVERING"
    ERROR = "ERROR"


def format_byte_rate(kbps: float) -> str:
    if kbps <= 0.01:
        return "0 B/s"
    if kbps < 1.0:
        return f"{int(kbps * 1024)} B/s"
    if kbps < 1024.0:
        return f"{kbps:.1f} KB/s"
    return f"{kbps / 1024.0:.2f} MB/s"


def format_uptime_hms(total_seconds: int) -> str:
    sec = max(0, int(total_seconds))
    hrs, rem = divmod(sec, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


@dataclass
class EngineSettings:
    autopilot_enabled: bool = True
    auto_clean_ip: bool = True
    require_youtube_6s: bool = True
    verify_upload_stream: bool = True
    self_healing_watchdog: bool = True
    system_proxy_enabled: bool = True
    tun_enabled: bool = False
    tun_auto_download: bool = True
    tun_mtu: int = 1400
    tun_dns: str = "1.1.1.1"
    theme_mode: str = "dark"

    selected_profile_uid: str = ""
    selected_index: int = 0

    engine_mode: str = "auto_hybrid"
    manual_vector_id: str = "VEC-01"
    fingerprint: str = "chrome"
    alpn_override: str = "auto"
    ws_early_data: int = 0

    fragment_enabled: bool = False
    fragment_packets: str = "tlshello"
    fragment_length: str = "5-16"
    fragment_interval: str = "2-3"

    mux_enabled: bool = False
    mux_concurrency: int = 8

    forward_stride_bytes: int = 400
    stride_jitter_bytes: int = 20
    socks_port: int = 10808
    http_port: int = 10809
    bridge_port: int = 20809

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EngineSettings":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {}
        for k, v in data.items():
            if k in valid_keys:
                filtered[k] = v
        return cls(**filtered)


@dataclass(frozen=True)
class BypassVector:
    vector_id: str
    code_name: str
    family: str
    summary: str
    preamble: str = "none"
    outer_version: int = 0x0304
    urgent_mode: str = "none"
    forward_cuts: List[int] = field(default_factory=list)
    second_urgent_delta: int = 0
    split_mode: str = "none"
    coalesce_flight2: bool = True
    frag_slice_min: int = 0
    frag_slice_max: int = 0
    frag_delay_min_ms: int = 0
    frag_delay_max_ms: int = 0
    frag_flights: int = 1


@dataclass
class ProfileNode:
    uri: str
    name: str
    protocol: str
    original_host: str
    port: int
    sni: str
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    group_tag: str = "Manual"
    cached_clean_ip: str = ""
    cached_vector_id: str = ""
    last_ping_ms: int = -1
    health_status: str = "UNTESTED"
    last_tested_ts: int = 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        effective_host = self.cached_clean_ip if self.cached_clean_ip else self.original_host
        payload["host"] = effective_host
        payload["address"] = effective_host
        payload["endpoint"] = f"{effective_host}:{self.port}"
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileNode":
        normalized = dict(data)
        if not normalized.get("original_host"):
            fallback_host = normalized.get("host") or normalized.get("address") or ""
            normalized["original_host"] = str(fallback_host)
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in normalized.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class SubscriptionItem:
    url: str
    title: str
    last_updated_ts: int = 0
    node_count: int = 0
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SubscriptionItem":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class TelemetrySnapshot:
    state: str = EngineState.DISCONNECTED.value
    ui_phase: str = "IDLE"
    is_connecting: bool = False
    is_connected: bool = False
    status_headline: str = "آماده اتصال"
    status_detail: str = "موتور هوشمند آماده برقراری تونل است"
    button_text: str = "اتصال هوشمند"
    uptime_seconds: int = 0
    uptime_label: str = "00:00:00"
    tun_enabled: bool = False
    tun_active: bool = False
    selected_index: int = 0
    active_profile_uid: str = ""
    active_profile_name: str = "---"
    protocol_label: str = "---"
    egress_ip: str = "---"
    endpoint_ip: str = "---"
    active_vector_id: str = "AUTO"
    active_vector_name: str = "Auto-Adaptive Core"
    ping_ms: int = -1
    tx_rate_kbps: float = 0.0
    rx_rate_kbps: float = 0.0
    tx_rate_label: str = "0 B/s"
    rx_rate_label: str = "0 B/s"
    tx_total_bytes: int = 0
    rx_total_bytes: int = 0
    active_sessions: int = 0
    progress_percent: int = 0


VECTOR_REGISTRY: List[BypassVector] = [
    BypassVector(
        vector_id="VEC-01",
        code_name="Adaptive Core Alpha",
        family="PROPRIETARY",
        summary="Primary structural stream desync with stride slicing",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="sni_tag",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-02",
        code_name="Adaptive Core Sigma",
        family="PROPRIETARY",
        summary="Mid-label structural alignment with stride slicing",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="mid_host",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-03",
        code_name="Dual-Phase Boundary",
        family="PROPRIETARY",
        summary="Bimodal boundary pointer with forward delta offset",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="sni_tag",
        second_urgent_delta=400,
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-04",
        code_name="Preamble Fusion + Stride",
        family="PROPRIETARY",
        summary="Empty TLS 1.3 record fusion with forward stride cut",
        preamble="zero0304",
        outer_version=0x0304,
        urgent_mode="sni_tag",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-05",
        code_name="Stepped Cascade 200/400",
        family="PROPRIETARY",
        summary="Multi-stage forward window segmentation",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="sni_tag",
        forward_cuts=[200, 400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-06",
        code_name="Dual-Tag Vector",
        family="PROPRIETARY",
        summary="Dual structural header offset alignment",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="dual",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-07",
        code_name="Length-Field Desync",
        family="PROPRIETARY",
        summary="Extension list length boundary segmentation",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="sni_len",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-08",
        code_name="Zero-Drift Dual Preamble",
        family="COALESCE",
        summary="Sequence-aligned dual empty record coalescing",
        preamble="2xzero",
        outer_version=0x0304,
        urgent_mode="none",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-09",
        code_name="Atomic Mid-SNI Record Split",
        family="COALESCE",
        summary="Single-buffer TLS record split with forward stride",
        preamble="zero0304",
        outer_version=0x0304,
        urgent_mode="none",
        forward_cuts=[400],
        split_mode="1pkt_midsni",
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-10",
        code_name="Tri-Stage Structural Core",
        family="PROPRIETARY",
        summary="Three-point extension header boundary alignment",
        preamble="zero0304",
        outer_version=0x0304,
        urgent_mode="triple",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-11",
        code_name="Micro-Fragment Header (5-16B)",
        family="FRAGMENT",
        summary="TLS Hello micro-slicing (5-16B, 2-3ms interval)",
        preamble="none",
        outer_version=0x0303,
        urgent_mode="none",
        frag_slice_min=5,
        frag_slice_max=16,
        frag_delay_min_ms=2,
        frag_delay_max_ms=3,
        frag_flights=1,
        coalesce_flight2=False,
    ),
    BypassVector(
        vector_id="VEC-12",
        code_name="Window-5B Multi-Flight (1-3)",
        family="FRAGMENT",
        summary="5-byte fixed header window exhaustion across flights 1-3",
        preamble="none",
        outer_version=0x0303,
        urgent_mode="none",
        frag_slice_min=5,
        frag_slice_max=5,
        frag_delay_min_ms=12,
        frag_delay_max_ms=20,
        frag_flights=3,
        coalesce_flight2=False,
    ),
    BypassVector(
        vector_id="VEC-13",
        code_name="Rapid TLS Fragment (12-28B)",
        family="FRAGMENT",
        summary="Low-latency TLS Hello slicing (12-28B, 1-2ms interval)",
        preamble="zero0304",
        outer_version=0x0304,
        urgent_mode="none",
        frag_slice_min=12,
        frag_slice_max=28,
        frag_delay_min_ms=1,
        frag_delay_max_ms=2,
        frag_flights=1,
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-14",
        code_name="Deep Frame Fragment (24-64B)",
        family="FRAGMENT",
        summary="Medium-chunk multi-flight TLS fragmentation (flights 1-2)",
        preamble="none",
        outer_version=0x0304,
        urgent_mode="none",
        frag_slice_min=24,
        frag_slice_max=64,
        frag_delay_min_ms=3,
        frag_delay_max_ms=6,
        frag_flights=2,
        coalesce_flight2=False,
    ),
    BypassVector(
        vector_id="VEC-15",
        code_name="Window-Boundary 512",
        family="PROPRIETARY",
        summary="DPI 512-byte inspection buffer edge cut",
        preamble="zero0304",
        outer_version=0x0304,
        urgent_mode="sni_tag",
        forward_cuts=[512],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-16",
        code_name="Quad-Preamble Burst",
        family="COALESCE",
        summary="4x mixed-version empty records with single-burst flush",
        preamble="4xzero",
        outer_version=0x0304,
        urgent_mode="none",
        forward_cuts=[400],
        coalesce_flight2=True,
    ),
    BypassVector(
        vector_id="VEC-00",
        code_name="Direct Tunnel Passthrough",
        family="DIRECT",
        summary="Zero-mutation kernel relay for domestic tunnels and encrypted streams",
        preamble="none",
        outer_version=0x0303,
        urgent_mode="none",
        forward_cuts=[],
        coalesce_flight2=False,
    ),
]


def find_vector(vector_id: str) -> BypassVector:
    for vec in VECTOR_REGISTRY:
        if vec.vector_id == vector_id:
            return vec
    return VECTOR_REGISTRY[0]


def filter_vectors_by_mode(engine_mode: str) -> List[BypassVector]:
    if engine_mode == "fragment_only":
        return [v for v in VECTOR_REGISTRY if v.family in ("FRAGMENT", "COALESCE", "DIRECT")]
    if engine_mode == "proprietary_only":
        return [v for v in VECTOR_REGISTRY if v.family in ("PROPRIETARY", "COALESCE", "DIRECT")]
    return list(VECTOR_REGISTRY)