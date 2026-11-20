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

    @classmethod
    def resolve_egress_geo(cls, http_port: int, timeout: float = 4.2) -> dict:
        sess = cls._make_proxy_session(http_port)
        try:
            try:
                r_ipapi = sess.get(
                    "http://ip-api.com/json/?fields=status,country,countryCode,isp,org,as,mobile,proxy,hosting,query",
                    timeout=timeout,
                )
                if r_ipapi.status_code == 200:
                    d = r_ipapi.json()
                    if d.get("status") == "success" and d.get("query"):
                        return cls._build_geo_dict(
                            ip_str=str(d.get("query")),
                            cc_raw=str(d.get("countryCode") or ""),
                            fallback_country=str(d.get("country") or ""),
                            is_datacenter=bool(d.get("hosting", False)),
                            is_proxy=bool(d.get("proxy", False)),
                            asn=str(d.get("as") or ""),
                            org=str(d.get("org") or ""),
                            isp=str(d.get("isp") or ""),
                        )
            except Exception:
                pass

            try:
                r_who = sess.get("https://ipwho.is/", timeout=timeout)
                if r_who.status_code == 200:
                    d2 = r_who.json()
                    if d2.get("success", True) and d2.get("ip"):
                        conn = d2.get("connection") or {}
                        sec = d2.get("security") or {}
                        return cls._build_geo_dict(
                            ip_str=str(d2.get("ip")),
                            cc_raw=str(d2.get("country_code") or ""),
                            fallback_country=str(d2.get("country") or ""),
                            is_datacenter=bool(sec.get("hosting", False)),
                            is_proxy=bool(sec.get("proxy", False) or sec.get("vpn", False) or sec.get("tor", False)),
                            asn=str(conn.get("asn") or ""),
                            org=str(conn.get("org") or ""),
                            isp=str(conn.get("isp") or ""),
                        )
            except Exception:
                pass

            try:
                r_info = sess.get("https://ipinfo.io/json", timeout=timeout)
                if r_info.status_code == 200:
                    d3 = r_info.json()
                    if d3.get("ip"):
                        org_str = str(d3.get("org") or "")
                        return cls._build_geo_dict(
                            ip_str=str(d3.get("ip")),
                            cc_raw=str(d3.get("country") or ""),
                            asn=org_str.split(" ")[0] if org_str else "",
                            org=org_str,
                        )
            except Exception:
                pass

            try:
                r_cf = sess.get("https://api.country.is/", timeout=timeout)
                if r_cf.status_code == 200:
                    d4 = r_cf.json()
                    if d4.get("ip"):
                        return cls._build_geo_dict(str(d4.get("ip")), str(d4.get("country") or ""))
            except Exception:
                pass
        finally:
            sess.close()

        return {
            "ip": "---",
            "country_code": "",
            "country_en": "Global",
            "country_fa": "مسیر جهانی",
            "is_datacenter": False,
            "is_proxy": False,
            "asn": "",
            "org": "",
            "isp": "",
        }

    @classmethod
    def check_gemini_access(
        cls,
        http_port: int,
        timeout: float = 5.2,
        geo_hint: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        geo = geo_hint if isinstance(geo_hint, dict) and geo_hint.get("ip", "---") != "---" else cls.resolve_egress_geo(http_port, timeout=3.8)
        cc = (geo.get("country_code") or "").upper()
        is_dc = bool(geo.get("is_datacenter", False))
        is_px = bool(geo.get("is_proxy", False))
        meta_blob = f"{geo.get('asn', '')} {geo.get('org', '')} {geo.get('isp', '')}".lower()

        if cc in GEMINI_BLOCKED_COUNTRIES:
            return False, f"BLOCKED_COUNTRY_{cc}"

        if any(bad in meta_blob for bad in ABUSED_DATACENTER_KEYWORDS):
            return False, "BLOCKED_DATACENTER"

        if is_dc and is_px:
            return False, "FLAGGED_DATACENTER_PROXY"

        sess = cls._make_proxy_session(http_port)
        sess.cookies.set("SOCS", "CAISHAgBEhJnd3NfMjAyNDAxMTYtMF9SQzIaAmVuIAEaBgiA_LyuBg", domain=".google.com")
        sess.cookies.set("CONSENT", "YES+cb.20240116-07-p0.en+FX+410", domain=".google.com")

        try:
            api_probe = sess.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=AIzaSyDummyKeyRegionProbe00000000000000",
                json={"contents": [{"parts": [{"text": "ping"}]}]},
                timeout=timeout,
            )
            api_txt = (api_probe.text or "").lower()
            if (
                ("location is not supported" in api_txt)
                or ("user location is not supported" in api_txt)
                or (api_probe.status_code in (403, 451) and "api_key_invalid" not in api_txt)
            ):
                return False, ("BLOCKED_DATACENTER" if is_dc else "BLOCKED_REGION")

            web_resp = sess.get(
                "https://gemini.google.com/app?hl=en",
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                timeout=timeout,
                allow_redirects=True,
            )
            final_url = (web_resp.url or "").lower()
            if (
                ("/faq" in final_url)
                or ("unsupported" in final_url)
                or ("/sorry/" in final_url)
                or (web_resp.status_code != 200)
            ):
                return False, ("BLOCKED_DATACENTER" if is_dc else "BLOCKED_REGION")

            raw_html = (web_resp.text or "")
            norm_html = raw_html.lower().replace("&#39;", "'").replace("’", "'").replace("&apos;", "'")

            blocked_phrases = (
                "currently supported in your country",
                "not supported in your country",
                "not available in your country",
                "isn't currently supported",
                "stay tuned!",
                "unusual traffic from your computer network",
            )
            if any(phrase in norm_html for phrase in blocked_phrases):
                return False, ("BLOCKED_DATACENTER" if is_dc else "BLOCKED_REGION")

            gl_match = re.search(r'"(?:gl|country_code)"\s*:\s*"([a-zA-Z]{2})"', raw_html)
            if gl_match and (gl_match.group(1).upper() in GEMINI_BLOCKED_COUNTRIES):
                return False, "GOOGLE_GEO_BLOCKED"

            valid_markers = ("bardchatui", "accounts.google.com/servicelogin", "sign in", "wiz_global_data")
            if not any(m in norm_html for m in valid_markers):
                return False, "UNVERIFIED_HTML"

            return True, ("OK_DATACENTER" if is_dc else "OK_RESIDENTIAL")
        except Exception:
            return False, "UNREACHABLE"
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
