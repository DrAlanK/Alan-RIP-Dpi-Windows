import os
import re
import time
from typing import Callable, Dict, Optional, Tuple
import requests


GEMINI_BLOCKED_COUNTRIES = {
    "IR", "RU", "BY", "CN", "HK", "MO", "CU", "KP", "SY", "VE",
}

ABUSED_DATACENTER_KEYWORDS = (
    "pq hosting",
    "pq.hosting",
    "stark industries",
    "aeza",
    "melbicom",
    "justhost",
    "timeweb",
    "vdsina",
    "fornex",
    "selectel",
    "beget",
    "zomro",
    "serveroid",
    "firstbyte",
    "inferno",
    "cloudflare",
    "warp",
)

COUNTRY_DIRECTORY: Dict[str, Tuple[str, str]] = {
    "DE": ("Germany", "آلمان"),
    "NL": ("Netherlands", "هلند"),
    "US": ("United States", "آمریکا"),
    "GB": ("United Kingdom", "انگلستان"),
    "UK": ("United Kingdom", "انگلستان"),
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
    "VN": ("Vietnam", "ویتنام"),
    "BR": ("Brazil", "برزیل"),
    "IQ": ("Iraq", "عراق"),
    "AM": ("Armenia", "ارمنستان"),
    "AZ": ("آذربایجان", "آذربایجان"),
    "GE": ("Georgia", "گرجستان"),
    "KZ": ("Kazakhstan", "قزاقستان"),
    "IR": ("Iran", "ایران"),
}


class TunnelStreamVerifier:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @classmethod
    def _make_proxy_session(cls, http_port: int) -> requests.Session:
        proxy_url = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": proxy_url, "https": proxy_url}
        sess.headers.update({
            "User-Agent": cls.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        return sess

    @classmethod
    def fast_probe(cls, http_port: int, timeout: float = 4.2) -> Tuple[bool, int, str]:
        sess = cls._make_proxy_session(http_port)
        urls = (
            "https://www.gstatic.com/generate_204",
            "http://connectivitycheck.gstatic.com/generate_204",
        )
        try:
            for url in urls:
                t0 = time.perf_counter()
                try:
                    resp = sess.get(url, timeout=timeout, allow_redirects=False)
                    rtt = max(1, int((time.perf_counter() - t0) * 1000))
                    if resp.status_code in (200, 204):
                        return True, rtt, "OK"
                    if resp.status_code in (502, 503):
                        return False, -1, f"HTTP {resp.status_code}"
                except Exception:
                    continue
            return False, -1, "Timeout"
        finally:
            sess.close()

    @classmethod
    def _build_geo_dict(
        cls,
        ip_str: str,
        cc_raw: str,
        fallback_country: str = "",
        is_datacenter: bool = False,
        is_proxy: bool = False,
        asn: str = "",
        org: str = "",
        isp: str = "",
    ) -> dict:
        cc = (cc_raw or "").strip().upper()
        if cc == "UK":
            cc = "GB"
        if (len(cc) != 2) or (cc == "XX"):
            cc = ""
        en_name, fa_name = COUNTRY_DIRECTORY.get(
            cc,
            (fallback_country or cc or "Global", fallback_country or cc or "مسیر جهانی"),
        )
        meta_blob = f"{asn} {org} {isp}".lower()
        dc_keywords = (
            "hosting", "datacenter", "data center", "cloud", "vps", "hetzner",
            "digitalocean", "ovh", "vultr", "linode", "akamai", "contabo",
            "leaseweb", "choopa", "m247", "datacamp", "serverius", "worldstream",
            "scaleway", "gcore", "g-core", "aeza", "pq hosting", "stark industries",
            "cloudflare", "amazon", "google cloud", "microsoft",
        )
        detected_dc = bool(is_datacenter) or any(k in meta_blob for k in dc_keywords)
        return {
            "ip": (ip_str or "---").strip(),
            "country_code": cc,
            "country_en": en_name,
            "country_fa": fa_name,
            "is_datacenter": detected_dc,
            "is_proxy": bool(is_proxy),
            "asn": asn.strip(),
            "org": org.strip(),
            "isp": isp.strip(),
        }

    _DATACENTER_KEYWORDS = (
        "cloudflare", "amazon", "aws", "google cloud", "gcp", "digitalocean",
        "hetzner", "ovh", "linode", "akamai", "vultr", "choopa", "contabo",
        "oracle", "microsoft", "azure", "alibaba", "aliyun", "tencent",
        "datacamp", "m247", "leaseweb", "psychz", "hostinger", "scalaxy",
        "aeza", "stark industries", "vultr", "serverius", "fdcservers",
        "hosting", "datacenter", "data center", "vps", "cloud", "cdn",
        "fastly", "scaleway", "kamatera", "upcloud", "ionos", "aruba",
    )

    _GEMINI_BLOCKED_COUNTRIES = {
        "IR", "CN", "HK", "MO", "RU", "BY", "KP", "SY", "CU", "VE", "AF", "MM",
    }

    _GEMINI_GEO_BLOCK_PHRASES = (
        "gemini isn't currently supported in your country",
        "currently supported in your country. stay tuned",
        "not currently supported in your country",
        "gemini isn't available in your country",
        "not available in your country",
        "isn't available in your region",
        "not available in your region",
        "country is not supported",
        "region is not supported",
        "location isn't supported",
        "not supported in your location",
        "unavailable in your country",
        "user location is not supported",
        "isunsupportedcountry\":true",
        "unsupported_country",
    )

    @classmethod
    def _classify_ip_datacenter(cls, isp: str, org: str, asn: str, hosting_flag=None, proxy_flag=None) -> Tuple[bool, str, str]:
        blob = f"{isp} {org} {asn}".lower()
        is_dc = bool(hosting_flag) or bool(proxy_flag) or any(k in blob for k in cls._DATACENTER_KEYWORDS)
        if is_dc:
            return True, "DATACENTER", "دیتاسنتر"
        if isp or org:
            return False, "RESIDENTIAL", "خانگی/ISP"
        return False, "UNKNOWN", "نامشخص"

    @classmethod
    def resolve_egress_geo(cls, http_port: int, timeout: float = 5.0) -> dict:
        from alan_dpi.engine.models import LocationExtractor
        px = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": px, "https": px}
        sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

        out = {
            "ip": "---",
            "country_code": "",
            "country_en": "Unknown",
            "country_fa": "نامشخص",
            "isp": "",
            "org": "",
            "asn": "",
            "is_datacenter": False,
            "is_proxy": False,
            "ip_type": "UNKNOWN",
            "ip_type_fa": "نامشخص",
        }
        try:
            # Primary: ip-api.com (provides exact hosting & proxy flags)
            try:
                r = sess.get(
                    "http://ip-api.com/json/?fields=status,country,countryCode,isp,org,as,hosting,proxy,query",
                    timeout=timeout,
                )
                if r.status_code == 200:
                    js = r.json()
                    if js.get("status") == "success":
                        cc = str(js.get("countryCode") or "").strip().upper()
                        en_n, fa_n = LocationExtractor.get_country_names(cc) if cc else (str(js.get("country") or "Unknown"), "نامشخص")
                        isp = str(js.get("isp") or "").strip()
                        org = str(js.get("org") or "").strip()
                        asn = str(js.get("as") or "").strip()
                        is_dc, t_en, t_fa = cls._classify_ip_datacenter(
                            isp, org, asn, js.get("hosting"), js.get("proxy")
                        )
                        out.update({
                            "ip": str(js.get("query") or "---"),
                            "country_code": cc,
                            "country_en": en_n,
                            "country_fa": fa_n,
                            "isp": isp,
                            "org": org,
                            "asn": asn,
                            "is_datacenter": is_dc,
                            "is_proxy": bool(js.get("proxy")),
                            "ip_type": t_en,
                            "ip_type_fa": t_fa,
                        })
                        return out
            except Exception:
                pass

            # Fallback: ipwho.is
            try:
                r2 = sess.get("https://ipwho.is/", timeout=timeout)
                if r2.status_code == 200:
                    js2 = r2.json()
                    if js2.get("success", True) and js2.get("ip"):
                        cc = str(js2.get("country_code") or "").strip().upper()
                        en_n, fa_n = LocationExtractor.get_country_names(cc) if cc else (str(js2.get("country") or "Unknown"), "نامشخص")
                        conn = js2.get("connection") if isinstance(js2.get("connection"), dict) else {}
                        isp = str(conn.get("isp") or "").strip()
                        org = str(conn.get("org") or "").strip()
                        asn = str(conn.get("asn") or "").strip()
                        sec = js2.get("security") if isinstance(js2.get("security"), dict) else {}
                        is_dc, t_en, t_fa = cls._classify_ip_datacenter(
                            isp, org, asn, sec.get("hosting"), sec.get("proxy") or sec.get("vpn")
                        )
                        out.update({
                            "ip": str(js2.get("ip") or "---"),
                            "country_code": cc,
                            "country_en": en_n,
                            "country_fa": fa_n,
                            "isp": isp,
                            "org": org,
                            "asn": asn,
                            "is_datacenter": is_dc,
                            "is_proxy": bool(sec.get("proxy") or sec.get("vpn")),
                            "ip_type": t_en,
                            "ip_type_fa": t_fa,
                        })
                        return out
            except Exception:
                pass

            # Fallback 2: Cloudflare trace (always available over TLS)
            try:
                r3 = sess.get("https://1.1.1.1/cdn-cgi/trace", timeout=min(timeout, 3.5))
                if r3.status_code == 200:
                    kv = {}
                    for ln in r3.text.splitlines():
                        if "=" in ln:
                            k, v = ln.split("=", 1)
                            kv[k.strip()] = v.strip()
                    cc = str(kv.get("loc") or "").strip().upper()
                    en_n, fa_n = LocationExtractor.get_country_names(cc) if cc else ("Unknown", "نامشخص")
                    out.update({
                        "ip": str(kv.get("ip") or "---"),
                        "country_code": cc,
                        "country_en": en_n,
                        "country_fa": fa_n,
                    })
            except Exception:
                pass
            return out
        finally:
            sess.close()

    @classmethod
    def _contains_gemini_geo_block_text(cls, html_text: str, final_url: str = "") -> bool:
        norm_url = str(final_url or "").lower()
        if any(tok in norm_url for tok in ("/unavailable", "/unsupported", "/sorry/index")):
            return True
        norm = (
            str(html_text or "")
            .replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("&#39;", "'")
            .replace("&apos;", "'")
            .lower()
        )
        return any(phrase in norm for phrase in cls._GEMINI_GEO_BLOCK_PHRASES)

    @classmethod
    def check_gemini_access(cls, http_port: int, timeout: float = 5.5, geo_hint: Optional[dict] = None) -> Tuple[bool, str]:
        """
        3-Layer Gemini Verification (Eliminates HTTP-200 false positives):
          1) Egress IP Geo + Datacenter/Hosting classification
          2) gemini.google.com/?hl=en & /app?hl=en HTTP status + exact HTML unsupported-country inspection
          3) generativelanguage.googleapis.com API geo-enforcement probe (immune to Angular CSR)
        """
        geo = geo_hint if isinstance(geo_hint, dict) and geo_hint.get("country_code") else cls.resolve_egress_geo(http_port=http_port, timeout=min(timeout, 4.0))
        cc = str(geo.get("country_code") or "").strip().upper()
        is_dc = bool(geo.get("is_datacenter", False))
        ip_tag = "DC" if is_dc else ("ISP" if geo.get("ip_type") == "RESIDENTIAL" else "IP")

        if cc and (cc in cls._GEMINI_BLOCKED_COUNTRIES):
            return False, f"BLOCKED ({cc} Geo-Restricted | {ip_tag})"

        px = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": px, "https": px}
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        try:
            # Layer 2: Web page inspection (catches 403/451 AND HTTP-200 "Gemini isn't currently supported in your country. Stay tuned!")
            web_ok = False
            for url in ("https://gemini.google.com/?hl=en", "https://gemini.google.com/app?hl=en"):
                try:
                    resp = sess.get(url, timeout=timeout, allow_redirects=True)
                    if resp.status_code in (403, 451):
                        return False, f"BLOCKED (Web HTTP {resp.status_code} | IP={geo.get('ip', '?')} {cc or '?'} {ip_tag} | ISP={str(geo.get('isp', '-'))[:24]})"
                    if resp.status_code >= 500:
                        continue
                    body_head = (resp.text or "")[:180000]
                    if cls._contains_gemini_geo_block_text(body_head, str(resp.url)):
                        return False, f"BLOCKED (Web HTML: Country Unsupported | IP={geo.get('ip', '?')} {cc or '?'} {ip_tag} | ISP={str(geo.get('isp', '-'))[:24]})"
                    if resp.status_code == 200:
                        web_ok = True
                        break
                except Exception:
                    continue

            if not web_ok:
                return False, f"BLOCKED (Unreachable | {ip_tag})"

            # Layer 3: Deterministic Google AI API geo check (catches Angular client-side blocks immediately)
            try:
                api_resp = sess.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    timeout=min(timeout, 4.5),
                    allow_redirects=False,
                )
                api_txt = (api_resp.text or "")[:4000].lower()
                if api_resp.status_code == 451 or "user location is not supported" in api_txt or "location is not supported" in api_txt:
                    return False, f"BLOCKED (Google AI API Geo-Denied HTTP {api_resp.status_code} | IP={geo.get('ip', '?')} {cc or '?'} {ip_tag} | ISP={str(geo.get('isp', '-'))[:24]})"
                if api_resp.status_code == 403 and ("api_key" not in api_txt and "unregistered" not in api_txt and "credentials" not in api_txt):
                    return False, f"BLOCKED (API 403 | {cc or '?'} {ip_tag})"
            except Exception:
                pass

            isp_s = str(geo.get("isp") or geo.get("org") or "-")[:28]
            return True, f"OK ({geo.get('ip', '?')} | {cc or 'Global'} | {ip_tag} | {isp_s})"
        finally:
            sess.close()




    @classmethod
    def measure_sustained_download_kbps(
        cls,
        http_port: int,
        target_bytes: int = 163840,
        timeout: float = 7.5,
        abort_check=None,
    ) -> Tuple[bool, float, str]:
        """
        Catches regional PMTU blackholes & 16KB-32KB flow-stalls where tiny pings pass
        but real web pages freeze after initial handshake.
        """
        px = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": px, "https": px}
        sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

        endpoints = [
            (f"https://speed.cloudflare.com/__down?bytes={int(target_bytes)}", 65536),
            ("https://www.gstatic.com/webp/gallery/4.webp", 45000),
            ("https://raw.githubusercontent.com/XTLS/Xray-core/main/README.md", 8000),
        ]

        try:
            for url, min_ok_bytes in endpoints:
                if (abort_check is not None) and abort_check():
                    return False, 0.0, "Aborted"
                try:
                    t0 = time.perf_counter()
                    received = 0
                    with sess.get(url, stream=True, timeout=(4.0, timeout), allow_redirects=True) as resp:
                        if resp.status_code != 200:
                            continue
                        for chunk in resp.iter_content(chunk_size=16384):
                            if (abort_check is not None) and abort_check():
                                return False, 0.0, "Aborted"
                            if chunk:
                                received += len(chunk)
                                if received >= target_bytes:
                                    break
                    dt = max(0.05, time.perf_counter() - t0)
                    if received >= min_ok_bytes:
                        kbps = round((received / 1024.0) / dt, 1)
                        lbl = f"{kbps / 1024.0:.2f} MB/s" if kbps >= 1024.0 else f"{kbps:.0f} KB/s"
                        return True, kbps, f"DL {lbl}"
                except Exception:
                    continue
            return False, 0.0, "Download Stalled (PMTU/16KB Drop)"
        finally:
            sess.close()

    @classmethod
    def measure_accurate_upload_kbps(
        cls,
        http_port: int,
        payload_kb: int = 192,
        timeout: float = 8.5,
        abort_check=None,
    ) -> Tuple[bool, float, str]:
        px = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": px, "https": px}
        sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

        size_bytes = max(32, int(payload_kb)) * 1024
        blob = os.urandom(size_bytes)

        endpoints = [
            ("https://speed.cloudflare.com/__up", blob),
            ("https://postman-echo.com/post", blob[:65536]),
            ("https://httpbin.org/post", blob[:65536]),
        ]

        try:
            for url, data_chunk in endpoints:
                if (abort_check is not None) and abort_check():
                    return False, 0.0, "Aborted"
                try:
                    t0 = time.perf_counter()
                    resp = sess.post(
                        url,
                        data=data_chunk,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Cache-Control": "no-cache",
                        },
                        timeout=timeout,
                        allow_redirects=False,
                    )
                    dt = max(0.05, time.perf_counter() - t0)
                    if resp.status_code in (200, 201, 204):
                        kbps = round((len(data_chunk) / 1024.0) / dt, 1)
                        if kbps >= 3.0:
                            lbl = f"{kbps / 1024.0:.2f} MB/s" if kbps >= 1024.0 else f"{kbps:.0f} KB/s"
                            return True, kbps, f"Real Upload {lbl}"
                except Exception:
                    continue
            return False, 0.0, "Upload Stalled / Timeout"
        finally:
            sess.close()

    @classmethod
    def run_full_qualification(
        cls,
        http_port: int,
        verify_upload: bool = True,
        require_youtube_6s: bool = True,
        abort_check=None,
    ) -> Tuple[bool, int, float, str]:
        ok_fast, base_ping, fast_detail = cls.fast_probe(http_port=http_port, timeout=4.2)
        if not ok_fast:
            return False, -1, 0.0, fast_detail

        dl_ok, dl_kbps, dl_det = cls.measure_sustained_download_kbps(
            http_port=http_port,
            target_bytes=163840,
            timeout=7.5,
            abort_check=abort_check,
        )
        if not dl_ok:
            return False, base_ping, 0.0, dl_det

        upload_kbps = 0.0
        if verify_upload:
            up_ok, upload_kbps, up_det = cls.measure_accurate_upload_kbps(
                http_port=http_port,
                payload_kb=192,
                timeout=8.5,
                abort_check=abort_check,
            )
            if not up_ok:
                return False, base_ping, 0.0, up_det

        px = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": px, "https": px}
        sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

        try:
            if require_youtube_6s:
                for step_i in range(2):
                    if (abort_check is not None) and abort_check():
                        return False, base_ping, upload_kbps, "Aborted"
                    time.sleep(0.55)
                    ry = sess.get(
                        f"https://www.youtube.com/generate_204?t={step_i}",
                        timeout=4.2,
                        allow_redirects=False,
                    )
                    if ry.status_code not in (200, 204):
                        return False, base_ping, upload_kbps, f"YouTube stream drop ({ry.status_code})"

            t_end = time.perf_counter()
            r_final = sess.get("https://www.gstatic.com/generate_204", timeout=3.8, allow_redirects=False)
            if r_final.status_code not in (200, 204):
                return False, base_ping, upload_kbps, f"Final check HTTP {r_final.status_code}"
            final_ping = max(1, int((time.perf_counter() - t_end) * 1000))
            avg_ping = (base_ping + final_ping) // 2
            up_str = f"{upload_kbps / 1024.0:.2f} MB/s" if upload_kbps >= 1024.0 else f"{upload_kbps:.0f} KB/s"
            return True, avg_ping, upload_kbps, f"{dl_det} | UL {up_str}"
        except Exception as exc:
            return False, base_ping, upload_kbps, f"Stream interrupted: {str(exc)[:36]}"
        finally:
            sess.close()


    @classmethod
    def resolve_egress_ip(cls, http_port: int, timeout: float = 4.0) -> str:
        geo = cls.resolve_egress_geo(http_port=http_port, timeout=timeout)
        ip_val = geo.get("ip", "---")
        cc_val = geo.get("country_code", "")
        if (ip_val != "---") and cc_val:
            return f"{ip_val} ({cc_val})"
        return ip_val
