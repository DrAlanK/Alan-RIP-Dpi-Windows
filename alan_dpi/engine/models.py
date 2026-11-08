import re
import urllib.parse
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Tuple


APP_NAME = "Alan-RIP-Dpi"
APP_VERSION = "1.2.0"


COUNTRY_METADATA: Dict[str, Tuple[str, str]] = {
    "DE": ("Germany", "آلمان"),
    "NL": ("Netherlands", "هلند"),
    "US": ("United States", "آمریکا"),
    "GB": ("United Kingdom", "انگلستان"),
    "FR": ("France", "فرانسه"),
    "FI": ("Finland", "فنلاند"),
    "SE": ("Sweden", "سوئد"),
    "TR": ("Turkey", "ترکیه"),
    "AE": ("UAE", "امارات"),
    "CA": ("Canada", "کانادا"),
    "CH": ("Switzerland", "سوئیس"),
    "AT": ("Austria", "اتریش"),
    "PL": ("Poland", "لهستان"),
    "IT": ("Italy", "ایتالیا"),
    "ES": ("Spain", "اسپانیا"),
    "SG": ("Singapore", "سنگاپور"),
    "JP": ("Japan", "ژاپن"),
    "KR": ("South Korea", "کره جنوبی"),
    "HK": ("Hong Kong", "هنگ‌کنگ"),
    "TW": ("Taiwan", "تایوان"),
    "IN": ("India", "هند"),
    "AU": ("Australia", "استرالیا"),
    "RU": ("Russia", "روسیه"),
    "UA": ("Ukraine", "اوکراین"),
    "RO": ("Romania", "رومانی"),
    "BG": ("Bulgaria", "بلغارستان"),
    "CZ": ("Czechia", "جمهوری چک"),
    "HU": ("Hungary", "مجارستان"),
    "NO": ("Norway", "نروژ"),
    "DK": ("Denmark", "دانمارک"),
    "IE": ("Ireland", "ایرلند"),
    "BE": ("Belgium", "بلژیک"),
    "PT": ("Portugal", "پرتغال"),
    "EE": ("Estonia", "استونی"),
    "LV": ("Latvia", "لتونی"),
    "LT": ("Lithuania", "لیتوانی"),
    "IS": ("Iceland", "ایسلند"),
    "LU": ("Luxembourg", "لوکزامبورگ"),
    "GR": ("Greece", "یونان"),
    "CY": ("Cyprus", "قبرس"),
    "MD": ("Moldova", "مولداوی"),
    "RS": ("Serbia", "صربستان"),
    "AL": ("Albania", "آلبانی"),
    "SK": ("Slovakia", "اسلواکی"),
    "SI": ("Slovenia", "اسلوونی"),
    "HR": ("Croatia", "کرواسی"),
    "VN": ("Vietnam", "ویتنام"),
    "MY": ("Malaysia", "مالزی"),
    "ID": ("Indonesia", "اندونزی"),
    "TH": ("Thailand", "تایلند"),
    "PH": ("Philippines", "فیلیپین"),
    "BR": ("Brazil", "برزیل"),
    "AR": ("Argentina", "آرژانتین"),
    "CL": ("Chile", "شیلی"),
    "MX": ("Mexico", "مکزیک"),
    "ZA": ("South Africa", "آفریقای جنوبی"),
    "IL": ("Israel", "اسرائیل"),
    "SA": ("Saudi Arabia", "عربستان"),
    "QA": ("Qatar", "قطر"),
    "BH": ("Bahrain", "بحرین"),
    "OM": ("Oman", "عمان"),
    "IQ": ("Iraq", "عراق"),
    "AM": ("Armenia", "ارمنستان"),
    "AZ": ("Azerbaijan", "آذربایجان"),
    "GE": ("Georgia", "گرجستان"),
    "KZ": ("Kazakhstan", "قزاقستان"),
    "IR": ("Iran", "ایران"),
    "EU": ("Europe", "اروپا"),
}

_ALPHA3_TO_ALPHA2: Dict[str, str] = {
    "DEU": "DE", "GER": "DE", "NLD": "NL", "USA": "US", "GBR": "GB", "ENG": "GB",
    "FRA": "FR", "FIN": "FI", "SWE": "SE", "TUR": "TR", "ARE": "AE", "UAE": "AE",
    "CAN": "CA", "CHE": "CH", "SUI": "CH", "AUT": "AT", "POL": "PL", "ITA": "IT",
    "ESP": "ES", "SGP": "SG", "JPN": "JP", "KOR": "KR", "HKG": "HK", "TWN": "TW",
    "IND": "IN", "AUS": "AU", "RUS": "RU", "UKR": "UA", "ROU": "RO", "ROM": "RO",
    "BGR": "BG", "CZE": "CZ", "HUN": "HU", "NOR": "NO", "DNK": "DK", "IRL": "IE",
    "BEL": "BE", "PRT": "PT", "EST": "EE", "LVA": "LV", "LTU": "LT", "ISL": "IS",
    "LUX": "LU", "GRC": "GR", "CYP": "CY", "MDA": "MD", "SRB": "RS", "ALB": "AL",
    "VNM": "VN", "MYS": "MY", "IDN": "ID", "THA": "TH", "PHL": "PH", "BRA": "BR",
    "ZAF": "ZA", "SAU": "SA", "QAT": "QA", "BHR": "BH", "OMN": "OM", "IRQ": "IQ",
    "ARM": "AM", "AZE": "AZ", "GEO": "GE", "KAZ": "KZ", "IRN": "IR",
}

_NAME_TO_ALPHA2: List[Tuple[str, str]] = [
    ("united states", "US"), ("united kingdom", "GB"), ("great britain", "GB"),
    ("south korea", "KR"), ("south africa", "ZA"), ("saudi arabia", "SA"),
    ("hong kong", "HK"), ("netherlands", "NL"), ("holland", "NL"), ("deutschland", "DE"),
    ("germany", "DE"), ("england", "GB"), ("finland", "FI"), ("france", "FR"),
    ("sweden", "SE"), ("turkiye", "TR"), ("türkiye", "TR"), ("turkey", "TR"),
    ("emirates", "AE"), ("dubai", "AE"), ("canada", "CA"), ("switzerland", "CH"),
    ("austria", "AT"), ("poland", "PL"), ("italy", "IT"), ("spain", "ES"),
    ("singapore", "SG"), ("japan", "JP"), ("taiwan", "TW"), ("india", "IN"),
    ("australia", "AU"), ("russia", "RU"), ("ukraine", "UA"), ("romania", "RO"),
    ("bulgaria", "BG"), ("czechia", "CZ"), ("czech", "CZ"), ("hungary", "HU"),
    ("norway", "NO"), ("denmark", "DK"), ("ireland", "IE"), ("belgium", "BE"),
    ("portugal", "PT"), ("estonia", "EE"), ("latvia", "LV"), ("lithuania", "LT"),
    ("iceland", "IS"), ("luxembourg", "LU"), ("greece", "GR"), ("cyprus", "CY"),
    ("moldova", "MD"), ("serbia", "RS"), ("albania", "AL"), ("vietnam", "VN"),
    ("malaysia", "MY"), ("indonesia", "ID"), ("thailand", "TH"), ("brazil", "BR"),
    ("kazakhstan", "KZ"), ("armenia", "AM"), ("azerbaijan", "AZ"), ("georgia", "GE"),
    ("آلمان", "DE"), ("هلند", "NL"), ("آمریکا", "US"), ("انگلستان", "GB"),
    ("بریتانیا", "GB"), ("فرانسه", "FR"), ("فنلاند", "FI"), ("سوئد", "SE"),
    ("ترکیه", "TR"), ("امارات", "AE"), ("کانادا", "CA"), ("سوئیس", "CH"),
    ("اتریش", "AT"), ("لهستان", "PL"), ("ایتالیا", "IT"), ("اسپانیا", "ES"),
    ("سنگاپور", "SG"), ("ژاپن", "JP"), ("کره جنوبی", "KR"), ("هنگ‌کنگ", "HK"),
    ("هنگ کنگ", "HK"), ("هند", "IN"), ("استرالیا", "AU"), ("روسیه", "RU"),
    ("اوکراین", "UA"), ("رومانی", "RO"), ("بلغارستان", "BG"), ("نروژ", "NO"),
    ("دانمارک", "DK"), ("ایرلند", "IE"), ("بلژیک", "BE"), ("پرتغال", "PT"),
    ("استونی", "EE"), ("لتونی", "LV"), ("لیتوانی", "LT"), ("ایران", "IR"),
]

_EXCLUDED_PROXY_TOKENS = {
    "WS", "SS", "CF", "IP", "AI", "GO", "OK", "ID", "UP", "DL", "UL", "MS", "V2",
    "CDN", "TLS", "TCP", "UDP", "DNS", "TUN", "MUX", "OOB", "SNI", "ECH", "RAW",
    "PRO", "VIP", "NEW", "MAX", "FAST", "FREE",
}

_AMBIGUOUS_PREPOSITIONS = {"IS", "IT", "AT", "BY", "TO", "OR", "ME", "AS", "ON", "AN", "DO", "SO", "BE", "IN", "NO"}


class LocationExtractor:
    @classmethod
    def get_country_names(cls, code: str) -> Tuple[str, str]:
        cc = (code or "").strip().upper()
        if cc == "UK":
            cc = "GB"
        return COUNTRY_METADATA.get(cc, (cc or "Global", cc or "مسیر جهانی"))

    @classmethod
    def _scan_flag_emoji(cls, text: str) -> str:
        for idx in range(len(text) - 1):
            o1 = ord(text[idx])
            o2 = ord(text[idx + 1])
            if (0x1F1E6 <= o1 <= 0x1F1FF) and (0x1F1E6 <= o2 <= 0x1F1FF):
                cc = chr(o1 - 0x1F1E6 + 65) + chr(o2 - 0x1F1E6 + 65)
                if cc == "UK":
                    cc = "GB"
                if cc in COUNTRY_METADATA:
                    return cc
        return ""

    @classmethod
    def extract_country_code(cls, name: str = "", uri: str = "", explicit_loc: str = "") -> str:
        if explicit_loc:
            clean_exp = explicit_loc.strip()
            flag_cc = cls._scan_flag_emoji(clean_exp)
            if flag_cc:
                return flag_cc
            up_exp = clean_exp.upper()
            if up_exp == "UK":
                return "GB"
            if up_exp in COUNTRY_METADATA:
                return up_exp
            if up_exp in _ALPHA3_TO_ALPHA2:
                return _ALPHA3_TO_ALPHA2[up_exp]
            low_exp = clean_exp.lower()
            for kw, cc_val in _NAME_TO_ALPHA2:
                if kw in low_exp:
                    return cc_val

        frag_text = ""
        if uri:
            try:
                parsed = urllib.parse.urlsplit(uri)
                if parsed.query:
                    q = dict(urllib.parse.parse_qsl(parsed.query))
                    for qk in ("loc", "location", "country", "cc", "region"):
                        if q.get(qk):
                            res_q = cls.extract_country_code(explicit_loc=q[qk])
                            if res_q:
                                return res_q
                if parsed.fragment:
                    frag_text = urllib.parse.unquote(parsed.fragment)
            except Exception:
                pass

        combined = f"{name or ''} {frag_text}".strip()
        if not combined:
            return ""

        flag_hit = cls._scan_flag_emoji(combined)
        if flag_hit:
            return flag_hit

        stripped = re.sub(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?::\d+)?", " ", combined)

        bracket_m = re.findall(r"[\[\(\{]\s*([A-Za-z]{2,3})\s*[\]\)\}]", stripped)
        for tok in bracket_m:
            up_t = tok.upper()
            if up_t == "UK":
                return "GB"
            if (up_t not in _EXCLUDED_PROXY_TOKENS) and (up_t in COUNTRY_METADATA):
                return up_t
            if up_t in _ALPHA3_TO_ALPHA2:
                return _ALPHA3_TO_ALPHA2[up_t]

        low_s = stripped.lower()
        for kw, cc_val in _NAME_TO_ALPHA2:
            if kw.isascii():
                if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", low_s):
                    return cc_val
            elif kw in low_s:
                return cc_val

        lead_m = re.match(r"^\s*([A-Z]{2,3})(?=[\s\-_|·:/])", stripped)
        if lead_m:
            lt = lead_m.group(1).upper()
            if lt == "UK":
                return "GB"
            if (lt not in _EXCLUDED_PROXY_TOKENS) and (lt in COUNTRY_METADATA):
                return lt
            if lt in _ALPHA3_TO_ALPHA2:
                return _ALPHA3_TO_ALPHA2[lt]

        for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2,3})(?![A-Za-z])", stripped):
            tok = m.group(1)
            if tok == "UK":
                return "GB"
            if (tok in _EXCLUDED_PROXY_TOKENS) or (tok in _AMBIGUOUS_PREPOSITIONS):
                continue
            if tok in COUNTRY_METADATA:
                return tok
            if tok in _ALPHA3_TO_ALPHA2:
                return _ALPHA3_TO_ALPHA2[tok]

        return ""


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
    language: str = "fa"
    theme_mode: str = "dark"
    minimize_to_tray: bool = True

    autopilot_enabled: bool = True
    auto_pool_enabled: bool = True
    preferred_auto_location: str = "ALL"
    auto_clean_ip: bool = True
    require_youtube_6s: bool = True
    verify_upload_stream: bool = True
    self_healing_watchdog: bool = True

    system_proxy_enabled: bool = True
    tun_enabled: bool = False
    tun_auto_download: bool = False
    tun_mtu: int = 1400
    tun_dns: str = "1.1.1.1"

    sub_auto_update_hours: int = 6

    routing_mode: str = "bypass_ir"
    block_quic: bool = True
    remote_dns: str = "1.1.1.1"
    domestic_dns: str = "178.22.122.100"
    custom_direct_domains: str = ""
    custom_proxy_domains: str = ""
    custom_blocked_domains: str = ""

    selected_profile_uid: str = "__SMART_AUTO__"
    selected_index: int = 0

    engine_mode: str = "auto_hybrid"
    manual_vector_id: str = "VEC-01"
    fingerprint: str = "custom_poly"
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
        filtered = {k: v for k, v in data.items() if k in valid_keys}
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
    record_envelope: str = "none"
    uplink_oob_shield: bool = False
    uplink_mss_clamp: int = 0
    tail_anchor_bytes: int = 0
    hybrid_mode: str = "none"


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
    country_code: str = ""
    cached_clean_ip: str = ""
    cached_vector_id: str = ""
    last_ping_ms: int = -1
    health_status: str = "UNTESTED"
    gemini_status: str = "UNKNOWN"
    upload_kbps: float = 0.0
    last_tested_ts: int = 0
    is_hidden_pool: bool = False

    def __post_init__(self):
        if not self.country_code:
            self.country_code = LocationExtractor.extract_country_code(name=self.name, uri=self.uri)

    def to_dict(self) -> dict:
        payload = asdict(self)
        effective_host = self.cached_clean_ip if self.cached_clean_ip else self.original_host
        ping_val = int(self.last_ping_ms) if (self.last_ping_ms is not None) else -1
        gem_ok = self.gemini_status == "OK"
        if ping_val > 0:
            ping_lbl = f"{ping_val} ms"
        elif self.health_status == "DEAD":
            ping_lbl = "Timeout"
        else:
            ping_lbl = "---"

        en_c, fa_c = LocationExtractor.get_country_names(self.country_code) if self.country_code else ("", "")
        payload["host"] = effective_host
        payload["address"] = effective_host
        payload["endpoint"] = f"{effective_host}:{self.port}"
        payload["country_en"] = en_c
        payload["country_fa"] = fa_c
        payload["last_ping_ms"] = ping_val
        payload["ping_ms"] = ping_val
        payload["ping"] = ping_val
        payload["delay"] = ping_val
        payload["delay_ms"] = ping_val
        payload["real_ping_ms"] = ping_val
        payload["tunnel_ms"] = ping_val
        payload["latency"] = ping_val
        payload["latency_ms"] = ping_val
        payload["ping_label"] = ping_lbl
        payload["ping_text"] = ping_lbl
        payload["vector_id"] = self.cached_vector_id or "AUTO"
        payload["bound_vector"] = self.cached_vector_id or ""
        payload["method"] = self.cached_vector_id or "AUTO"
        payload["status"] = self.health_status
        payload["gemini_ok"] = gem_ok
        payload["gemini_ready"] = gem_ok
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
class VerifiedOutputItem:
    uid: str
    profile_uid: str
    name: str
    protocol: str
    uri: str
    endpoint_host: str
    port: int
    sni: str
    vector_id: str
    vector_name: str
    ping_ms: int = -1
    upload_kbps: float = 0.0
    gemini_status: str = "UNKNOWN"
    country_code: str = ""
    group_tag: str = "Lab"
    verified_ts: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["endpoint"] = f"{self.endpoint_host}:{self.port}"
        d["gemini_ok"] = self.gemini_status == "OK"
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "VerifiedOutputItem":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
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
    tun_badge: str = "OFF"
    system_proxy_enabled: bool = True
    auto_mode_enabled: bool = True
    preferred_auto_location: str = "ALL"
    available_auto_locations: List[dict] = field(default_factory=list)
    gemini_ready: bool = False
    gemini_status: str = "UNKNOWN"
    selected_index: int = 0
    active_profile_uid: str = ""
    active_profile_name: str = "---"
    protocol_label: str = "---"
    egress_ip: str = "---"
    egress_country_code: str = ""
    country_code: str = ""
    egress_country: str = "مسیر جهانی"
    egress_country_en: str = "Global"
    egress_country_fa: str = "مسیر جهانی"
    destination_label: str = "مسیر جهانی"
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


AUTOPILOT_PRIORITY_IDS: List[str] = [
    "VEC-21", "VEC-22", "VEC-01", "VEC-18", "VEC-17", "VEC-19",
    "VEC-20", "VEC-23", "VEC-04", "VEC-02", "VEC-03", "VEC-05",
    "VEC-06", "VEC-07", "VEC-08", "VEC-09", "VEC-10", "VEC-15",
    "VEC-16", "VEC-11", "VEC-13", "VEC-14", "VEC-12", "VEC-00",
]


VECTOR_REGISTRY: List[BypassVector] = [
    BypassVector("VEC-01", "Adaptive Core Alpha", "PROPRIETARY", "Primary structural stream desync with stride slicing", "none", 0x0304, "sni_tag", [400], coalesce_flight2=True),
    BypassVector("VEC-02", "Adaptive Core Sigma", "PROPRIETARY", "Mid-label structural alignment with stride slicing", "none", 0x0304, "mid_host", [400], coalesce_flight2=True),
    BypassVector("VEC-03", "Dual-Phase Boundary", "PROPRIETARY", "Bimodal boundary pointer with forward delta offset", "none", 0x0304, "sni_tag", second_urgent_delta=400, coalesce_flight2=True),
    BypassVector("VEC-04", "Preamble Fusion + Stride", "PROPRIETARY", "Empty TLS 1.3 record fusion with forward stride cut", "zero0304", 0x0304, "sni_tag", [400], coalesce_flight2=True),
    BypassVector("VEC-05", "Stepped Cascade 200/400", "PROPRIETARY", "Multi-stage forward window segmentation", "none", 0x0304, "sni_tag", [200, 400], coalesce_flight2=True),
    BypassVector("VEC-06", "Dual-Tag Vector", "PROPRIETARY", "Dual structural header offset alignment", "none", 0x0304, "dual", [400], coalesce_flight2=True),
    BypassVector("VEC-07", "Length-Field Desync", "PROPRIETARY", "Extension list length boundary segmentation", "none", 0x0304, "sni_len", [400], coalesce_flight2=True),
    BypassVector("VEC-08", "Zero-Drift Dual Preamble", "COALESCE", "Sequence-aligned dual empty record coalescing", "2xzero", 0x0304, "none", [400], coalesce_flight2=True),
    BypassVector("VEC-09", "Atomic Mid-SNI Record Split", "COALESCE", "Single-buffer TLS record split with forward stride", "zero0304", 0x0304, "none", [400], split_mode="1pkt_midsni", coalesce_flight2=True),
    BypassVector("VEC-10", "Tri-Stage Structural Core", "PROPRIETARY", "Three-point extension header boundary alignment", "zero0304", 0x0304, "triple", [400], coalesce_flight2=True),
    BypassVector("VEC-11", "Micro-Fragment Header (5-16B)", "FRAGMENT", "TLS Hello micro-slicing (5-16B, 2-3ms interval)", "none", 0x0303, "none", coalesce_flight2=False, frag_slice_min=5, frag_slice_max=16, frag_delay_min_ms=2, frag_delay_max_ms=3, frag_flights=1),
    BypassVector("VEC-12", "Window-5B Multi-Flight (1-3)", "FRAGMENT", "5-byte fixed header window exhaustion across flights 1-3", "none", 0x0303, "none", coalesce_flight2=False, frag_slice_min=5, frag_slice_max=5, frag_delay_min_ms=12, frag_delay_max_ms=20, frag_flights=3),
    BypassVector("VEC-13", "Rapid TLS Fragment (12-28B)", "FRAGMENT", "Low-latency TLS Hello slicing (12-28B, 1-2ms interval)", "zero0304", 0x0304, "none", coalesce_flight2=True, frag_slice_min=12, frag_slice_max=28, frag_delay_min_ms=1, frag_delay_max_ms=2, frag_flights=1),
    BypassVector("VEC-14", "Deep Frame Fragment (24-64B)", "FRAGMENT", "Medium-chunk multi-flight TLS fragmentation (flights 1-2)", "none", 0x0304, "none", coalesce_flight2=False, frag_slice_min=24, frag_slice_max=64, frag_delay_min_ms=3, frag_delay_max_ms=6, frag_flights=2),
    BypassVector("VEC-15", "Window-Boundary 512", "PROPRIETARY", "DPI 512-byte inspection buffer edge cut", "zero0304", 0x0304, "sni_tag", [512], coalesce_flight2=True),
    BypassVector("VEC-16", "Quad-Preamble Burst", "COALESCE", "4x mixed-version empty records with single-burst flush", "4xzero", 0x0304, "none", [400], coalesce_flight2=True),
    BypassVector("VEC-17", "Aligned Record Relay", "COALESCE", "Multi-frame record boundary alignment over single buffer flush", outer_version=0x0303, record_envelope="sni_dot_3rec", uplink_mss_clamp=1380, coalesce_flight2=False),
    BypassVector("VEC-18", "Adaptive Core Delta", "PROPRIETARY", "Early header pointer alignment with trailing segment split", outer_version=0x0304, urgent_mode="cipher_pivot", tail_anchor_bytes=36, uplink_mss_clamp=1360, coalesce_flight2=False),
    BypassVector("VEC-19", "Stream Window Balance", "PROPRIETARY", "Dual-frame handshake alignment with outbound stream pacing", outer_version=0x0303, record_envelope="sni_mid_2rec", uplink_oob_shield=True, uplink_mss_clamp=1360, coalesce_flight2=False),
    BypassVector("VEC-20", "Progressive Frame Sync", "COALESCE", "Stepped multi-record frame segmentation with tail pacing", outer_version=0x0303, record_envelope="fibonacci_7rec", uplink_mss_clamp=1380, coalesce_flight2=False),
    BypassVector("VEC-21", "Adaptive Core Omega", "PROPRIETARY", "Composite header boundary shift with forward window cut", outer_version=0x0303, hybrid_mode="phantom_seam_oob", uplink_mss_clamp=1380, coalesce_flight2=False),
    BypassVector("VEC-22", "Dual-Window Stream Core", "PROPRIETARY", "Segmented header cell alignment with secondary window cut", outer_version=0x0304, hybrid_mode="sni_microcell_pincer", uplink_mss_clamp=1360, coalesce_flight2=False),
    BypassVector("VEC-23", "Interleaved Record Sync", "COALESCE", "Alternating record header framing with forward segment split", outer_version=0x0301, hybrid_mode="chameleon_interleave", uplink_mss_clamp=1380, coalesce_flight2=False),
    BypassVector("VEC-00", "Direct Tunnel Passthrough", "DIRECT", "Zero-mutation kernel relay for domestic tunnels and encrypted streams", "none", 0x0303, "none", [], coalesce_flight2=False),
]


def find_vector(vector_id: str) -> BypassVector:
    for vec in VECTOR_REGISTRY:
        if vec.vector_id == vector_id:
            return vec
    return VECTOR_REGISTRY[0]


def filter_vectors_by_mode(engine_mode: str) -> List[BypassVector]:
    rank_map = {vid: idx for idx, vid in enumerate(AUTOPILOT_PRIORITY_IDS)}
    if engine_mode == "fragment_only":
        pool = [v for v in VECTOR_REGISTRY if v.family in ("FRAGMENT", "COALESCE", "DIRECT")]
    elif engine_mode == "proprietary_only":
        pool = [v for v in VECTOR_REGISTRY if v.family in ("PROPRIETARY", "COALESCE", "DIRECT")]
    else:
        pool = list(VECTOR_REGISTRY)
    pool.sort(key=lambda v: rank_map.get(v.vector_id, 999))
    return pool
