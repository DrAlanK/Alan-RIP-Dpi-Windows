import random
import base64
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

from alan_dpi.engine.bridge import FullDuplexMutatorBridge
from alan_dpi.engine.clean_ip import CleanIpScanner
from alan_dpi.engine.models import EngineSettings, LocationExtractor, ProfileNode, find_vector
from alan_dpi.engine.verifier import TunnelStreamVerifier


DIRECT_IR_DOMAINS = [
    "domain:ir",
    "domain:local",
    "domain:shaparak.ir",
    "domain:digikala.com",
    "domain:snapp.ir",
    "domain:aparat.com",
    "domain:divar.ir",
    "domain:telewebion.com",
    "domain:torob.com",
    "domain:zarinpal.com",
]

PRIVATE_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
]


def _b64_decode_padded(raw: str) -> str:
    clean = (raw or "").strip().replace("-", "+").replace("_", "/")
    pad = (-len(clean)) % 4
    if pad:
        clean += "=" * pad
    return base64.b64decode(clean).decode("utf-8", errors="ignore")


def _b64_encode_nopad(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def find_free_tcp_port(preferred: int = 0) -> int:
    if preferred > 0:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", int(preferred)))
            return int(preferred)
        except OSError:
            pass
        finally:
            s.close()
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s2.bind(("127.0.0.1", 0))
        return int(s2.getsockname()[1])
    finally:
        s2.close()


class UriConfigCodec:
    SUPPORTED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "socks://")

    @classmethod
    def extract_uris_from_blob(cls, text: str) -> List[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        if "://" not in raw:
            try:
                decoded = _b64_decode_padded(raw)
                if "://" in decoded:
                    raw = decoded
            except Exception:
                pass
        results: List[str] = []
        for line in raw.splitlines():
            item = line.strip()
            if any(item.lower().startswith(sch) for sch in cls.SUPPORTED_SCHEMES):
                results.append(item)
        return results

    @classmethod
    def parse_editable_fields(cls, node: ProfileNode) -> dict:
        ed = cls.parse_to_editable(
            node.uri,
            uid=node.uid,
            group_tag=node.group_tag,
            preferred_vec=node.cached_vector_id or "AUTO",
        )
        if node.cached_clean_ip:
            ed["address"] = node.cached_clean_ip
        return ed

    @classmethod
    def parse_to_editable(cls, uri: str, uid: str = "", group_tag: str = "Manual", preferred_vec: str = "AUTO") -> dict:
        clean_uri = (uri or "").strip()
        lower = clean_uri.lower()
        base = {
            "uid": uid,
            "name": "Profile",
            "group_tag": group_tag,
            "protocol": "vless",
            "address": "",
            "port": 443,
            "uuid_or_password": "",
            "network": "tcp",
            "header_type": "none",
            "security": "none",
            "allow_insecure": False,
            "sni": "",
            "host_header": "",
            "path": "/",
            "alpn": "",
            "fingerprint": "chrome",
            "flow": "",
            "pbk": "",
            "sid": "",
            "scy": "auto",
            "preferred_vector_id": preferred_vec or "AUTO",
            "raw_uri": clean_uri,
            "use_raw_uri": False,
        }

        if lower.startswith("vmess://"):
            body = clean_uri[8:]
            if "#" in body:
                body, frag = body.split("#", 1)
                base["name"] = urllib.parse.unquote(frag) or "VMess"
            data = json.loads(_b64_decode_padded(body))
            base["protocol"] = "vmess"
            base["name"] = str(data.get("ps") or base["name"] or "VMess")
            base["address"] = str(data.get("add") or "").strip()
            base["port"] = int(data.get("port") or 443)
            base["uuid_or_password"] = str(data.get("id") or "").strip()
            base["scy"] = str(data.get("scy") or "auto")
            base["network"] = str(data.get("net") or "tcp").lower()
            base["header_type"] = str(data.get("type") or "none").lower()
            tls_val = str(data.get("tls") or "").lower()
            base["security"] = "tls" if tls_val == "tls" else "none"
            base["allow_insecure"] = str(data.get("allowInsecure") or "0").lower() in ("1", "true")
            base["sni"] = str(data.get("sni") or data.get("host") or "").strip()
            base["host_header"] = str(data.get("host") or "").strip()
            base["path"] = str(data.get("path") or "/")
            base["alpn"] = str(data.get("alpn") or "")
            base["fingerprint"] = str(data.get("fp") or "chrome")
            return base

        if lower.startswith("ss://"):
            body = clean_uri[5:]
            name = "Shadowsocks"
            if "#" in body:
                body, frag = body.split("#", 1)
                name = urllib.parse.unquote(frag) or name
            if "?" in body:
                body = body.split("?", 1)[0]
            if "@" in body:
                userinfo, hostport = body.rsplit("@", 1)
                userinfo = urllib.parse.unquote(userinfo)
                if ":" not in userinfo:
                    userinfo = _b64_decode_padded(userinfo)
            else:
                decoded_all = _b64_decode_padded(body)
                userinfo, hostport = decoded_all.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
            host, port_s = hostport.rsplit(":", 1)
            base.update({
                "protocol": "ss",
                "name": name,
                "address": host.strip("[]"),
                "port": int(port_s),
                "scy": method.strip(),
                "uuid_or_password": password,
                "security": "none",
            })
            return base

        parsed = urllib.parse.urlsplit(clean_uri)
        proto = parsed.scheme.lower()
        q = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else proto.upper()
        user_val = urllib.parse.unquote(parsed.username or "")
        if (proto == "socks") and (not parsed.password) and user_val:
            try:
                dec_u = _b64_decode_padded(user_val)
                if ":" in dec_u:
                    user_val = dec_u
            except Exception:
                pass
        elif parsed.password:
            user_val = f"{user_val}:{urllib.parse.unquote(parsed.password)}"

        sec = (q.get("security") or ("tls" if proto == "trojan" else "none")).lower()
        net = (q.get("type") or "tcp").lower()
        sni_val = (q.get("sni") or q.get("peer") or q.get("host") or "").strip()
        if (not sni_val) and (sec == "tls") and parsed.hostname:
            sni_val = parsed.hostname

        insecure_raw = str(q.get("allowInsecure") or q.get("insecure") or "0").strip().lower()
        base.update({
            "protocol": proto,
            "name": name,
            "address": (parsed.hostname or "").strip(),
            "port": int(parsed.port or 443),
            "uuid_or_password": user_val,
            "network": net,
            "header_type": (q.get("headerType") or "none").lower(),
            "security": sec,
            "allow_insecure": insecure_raw in ("1", "true"),
            "sni": sni_val,
            "host_header": (q.get("host") or q.get("authority") or "").strip(),
            "path": q.get("path") or q.get("serviceName") or "/",
            "alpn": q.get("alpn") or "",
            "fingerprint": q.get("fp") or "chrome",
            "flow": q.get("flow") or "",
            "pbk": q.get("pbk") or "",
            "sid": q.get("sid") or "",
            "scy": q.get("encryption") or "none",
        })
        return base

    @classmethod
    def build_uri_from_editable(cls, fields: dict, inject_early_data: int = 0) -> str:
        if fields.get("use_raw_uri") and fields.get("raw_uri"):
            return str(fields["raw_uri"]).strip()

        proto = str(fields.get("protocol") or "vless").lower()
        name = str(fields.get("name") or "Profile").strip()
        addr = str(fields.get("address") or "").strip()
        port = int(fields.get("port") or 443)
        secret = str(fields.get("uuid_or_password") or "").strip()
        net = str(fields.get("network") or "tcp").lower()
        htype = str(fields.get("header_type") or "none").lower()
        sec = str(fields.get("security") or "none").lower()
        sni = str(fields.get("sni") or "").strip()
        host_h = str(fields.get("host_header") or "").strip()
        path = str(fields.get("path") or "/")
        alpn = str(fields.get("alpn") or "").strip()
        fp = str(fields.get("fingerprint") or "chrome").strip()

        if (inject_early_data > 0) and (net in ("ws", "httpupgrade")) and ("ed=" not in path):
            sep = "&" if ("?" in path) else "?"
            path = f"{path}{sep}ed={int(inject_early_data)}"

        if proto == "vmess":
            scy_val = str(fields.get("scy") or "auto")
            if scy_val not in ("auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"):
                scy_val = "auto"
            v_obj = {
                "v": "2",
                "ps": name,
                "add": addr,
                "port": str(port),
                "id": secret,
                "aid": "0",
                "scy": scy_val,
                "net": net,
                "type": htype,
                "host": host_h,
                "path": path,
                "tls": "tls" if sec == "tls" else "",
                "sni": sni,
                "alpn": alpn,
                "fp": fp,
            }
            return "vmess://" + base64.b64encode(json.dumps(v_obj, ensure_ascii=False).encode("utf-8")).decode("ascii")

        if proto == "ss":
            method = str(fields.get("scy") or "chacha20-ietf-poly1305")
            if method in ("auto", "none", ""):
                method = "chacha20-ietf-poly1305"
            enc_user = _b64_encode_nopad(f"{method}:{secret}")
            return f"ss://{enc_user}@{addr}:{port}#{urllib.parse.quote(name)}"

        params: Dict[str, str] = {"type": net, "security": sec}
        if proto == "vless":
            params["encryption"] = "none"
            if fields.get("flow"):
                params["flow"] = str(fields["flow"])
        if htype and (htype != "none"):
            params["headerType"] = htype
        if host_h:
            params["host"] = host_h
        if net in ("ws", "httpupgrade", "xhttp", "splithttp"):
            params["path"] = path
        elif net == "grpc":
            params["serviceName"] = path.lstrip("/")
        if sec in ("tls", "reality"):
            if sni:
                params["sni"] = sni
            if fp:
                params["fp"] = fp
            if alpn:
                params["alpn"] = alpn
            if sec == "tls" and fields.get("allow_insecure"):
                params["allowInsecure"] = "1"
            if sec == "reality":
                if fields.get("pbk"):
                    params["pbk"] = str(fields["pbk"])
                if fields.get("sid"):
                    params["sid"] = str(fields["sid"])

        q_str = urllib.parse.urlencode(params)
        return f"{proto}://{urllib.parse.quote(secret)}@{addr}:{port}?{q_str}#{urllib.parse.quote(name)}"

    @classmethod
    def extract_profile_node(
        cls,
        uri: str,
        group_tag: str = "Manual",
        is_hidden: bool = False,
        explicit_country: str = "",
    ) -> ProfileNode:
        ed = cls.parse_to_editable(uri, group_tag=group_tag)
        proto_map = {
            "vless": "VLESS",
            "vmess": "VMess",
            "trojan": "Trojan",
            "ss": "Shadowsocks",
            "socks": "SOCKS",
        }
        proto_label = proto_map.get(ed["protocol"], ed["protocol"].upper())
        cc = LocationExtractor.extract_country_code(name=ed["name"], uri=uri, explicit_loc=explicit_country)
        return ProfileNode(
            uri=uri.strip(),
            name=ed["name"],
            protocol=proto_label,
            original_host=ed["address"],
            port=int(ed["port"]),
            sni=ed["sni"],
            group_tag=group_tag,
            country_code=cc,
            is_hidden_pool=is_hidden,
        )

    @classmethod
    def build_xray_outbound(
        cls,
        uri: str,
        settings: EngineSettings,
        target_host: str = "127.0.0.1",
        target_port: int = 20809,
        tag: str = "proxy-out",
        dialer_proxy: str = "",
        strip_allow_insecure: bool = False,
    ) -> dict:
        ed = cls.parse_to_editable(uri)
        proto = ed["protocol"]

        if proto == "vless":
            user_obj = {"id": ed["uuid_or_password"], "encryption": "none"}
            if ed["flow"]:
                user_obj["flow"] = ed["flow"]
            out_settings = {"vnext": [{"address": target_host, "port": int(target_port), "users": [user_obj]}]}
            out_proto = "vless"
        elif proto == "vmess":
            scy_val = ed["scy"] if ed["scy"] in ("auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero") else "auto"
            user_obj = {"id": ed["uuid_or_password"], "alterId": 0, "security": scy_val}
            out_settings = {"vnext": [{"address": target_host, "port": int(target_port), "users": [user_obj]}]}
            out_proto = "vmess"
        elif proto == "trojan":
            out_settings = {"servers": [{"address": target_host, "port": int(target_port), "password": ed["uuid_or_password"]}]}
            out_proto = "trojan"
        elif proto == "ss":
            ss_method = ed["scy"] if (ed["scy"] and ed["scy"] not in ("auto", "none")) else "chacha20-ietf-poly1305"
            out_settings = {
                "servers": [{
                    "address": target_host,
                    "port": int(target_port),
                    "method": ss_method,
                    "password": ed["uuid_or_password"],
                }]
            }
            out_proto = "shadowsocks"
        else:
            srv: dict = {"address": target_host, "port": int(target_port)}
            if ":" in ed["uuid_or_password"]:
                u, p = ed["uuid_or_password"].split(":", 1)
                srv["users"] = [{"user": u, "pass": p}]
            out_settings = {"servers": [srv]}
            out_proto = "socks"

        net = ed["network"]
        if net == "splithttp":
            net = "xhttp"

        stream: dict = {"network": net, "security": ed["security"]}
        path_val = ed["path"] or "/"
        if (settings.ws_early_data > 0) and (net in ("ws", "httpupgrade")) and ("ed=" not in path_val):
            sep = "&" if ("?" in path_val) else "?"
            path_val = f"{path_val}{sep}ed={int(settings.ws_early_data)}"

        host_hdr = ed["host_header"] or ed["sni"] or ed["address"]

        if net == "ws":
            ws_cfg: dict = {"path": path_val}
            if host_hdr:
                ws_cfg["host"] = host_hdr
            stream["wsSettings"] = ws_cfg
        elif net == "httpupgrade":
            hu_cfg: dict = {"path": path_val}
            if host_hdr:
                hu_cfg["host"] = host_hdr
            stream["httpupgradeSettings"] = hu_cfg
        elif net == "xhttp":
            xh_cfg: dict = {"path": path_val, "mode": "auto"}
            if host_hdr:
                xh_cfg["host"] = host_hdr
            stream["xhttpSettings"] = xh_cfg
        elif net == "grpc":
            grpc_cfg: dict = {"serviceName": path_val.lstrip("/"), "multiMode": False}
            if host_hdr:
                grpc_cfg["authority"] = host_hdr
            stream["grpcSettings"] = grpc_cfg
        elif net == "kcp":
            stream["kcpSettings"] = {"seed": path_val.lstrip("/"), "header": {"type": ed["header_type"] or "none"}}
        elif (net == "tcp") and (ed["header_type"] == "http"):
            stream["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [path_val],
                        "headers": {
                            "Host": [host_hdr] if host_hdr else ["www.speedtest.net"],
                            "User-Agent": ["Mozilla/5.0 Chrome/131.0.0.0"],
                            "Connection": ["keep-alive"],
                        },
                    },
                }
            }

        raw_fp_pref = (settings.fingerprint or "custom_poly").strip().lower()
        if raw_fp_pref in ("custom_poly", "custom", "polymorphic", "auto"):
            if ed["security"] == "reality":
                fp = random.choice(("safari", "ios", "edge"))
            else:
                fp = random.choice(("random", "safari", "ios", "edge", "qq"))
        else:
            fp = raw_fp_pref or ed["fingerprint"] or "random"
        alpn_raw = settings.alpn_override if (settings.alpn_override and settings.alpn_override != "auto") else ed["alpn"]
        alpn_list = [x.strip() for x in alpn_raw.split(",") if x.strip()] if alpn_raw else []
        if (not alpn_list) and (net in ("ws", "httpupgrade")) and (ed["security"] == "tls"):
            alpn_list = ["http/1.1"]

        if ed["security"] == "tls":
            tls_cfg: dict = {
                "serverName": ed["sni"] or host_hdr or ed["address"],
                "fingerprint": fp,
            }
            if alpn_list:
                tls_cfg["alpn"] = alpn_list
            if bool(ed["allow_insecure"]) and (not strip_allow_insecure):
                tls_cfg["allowInsecure"] = True
            stream["tlsSettings"] = tls_cfg
        elif ed["security"] == "reality":
            stream["realitySettings"] = {
                "serverName": ed["sni"] or ed["address"],
                "fingerprint": fp,
                "publicKey": ed["pbk"],
                "shortId": ed["sid"],
                "spiderX": "/",
            }

        sockopt: dict = {"tcpNoDelay": True}
        if dialer_proxy:
            sockopt["dialerProxy"] = dialer_proxy
        stream["sockopt"] = sockopt

        outbound = {
            "tag": tag,
            "protocol": out_proto,
            "settings": out_settings,
            "streamSettings": stream,
        }
        if settings.mux_enabled and (ed["security"] != "reality") and (net != "xhttp"):
            outbound["mux"] = {"enabled": True, "concurrency": max(1, int(settings.mux_concurrency))}
        return outbound


class XrayProcessDriver:
    _cached_major_ver: Optional[int] = None

    def __init__(self, core_dir: str, configs_dir: str, log_fn=None):
        self.core_dir = core_dir
        self.configs_dir = configs_dir
        self.log_fn = log_fn
        self.proc: Optional[subprocess.Popen] = None
        self.active_socks_port: int = 10808
        self.active_http_port: int = 10809
        self._native_tun_supported: Optional[bool] = None
        self._temp_cfg_file: str = ""
        self._temp_log_file: str = ""

    def _log(self, text: str):
        if self.log_fn is not None:
            self.log_fn(text)

    @property
    def xray_exe_path(self) -> str:
        name = "xray.exe" if os.name == "nt" else "xray"
        return os.path.join(self.core_dir, name)

    def _detect_xray_major_version(self) -> int:
        if XrayProcessDriver._cached_major_ver is not None:
            return XrayProcessDriver._cached_major_ver
        exe = self.xray_exe_path
        if not os.path.exists(exe):
            return 25
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=2.5, creationflags=flags)
            m = re.search(r"Xray\s+(\d+)\.", res.stdout or "")
            if m:
                XrayProcessDriver._cached_major_ver = int(m.group(1))
                return XrayProcessDriver._cached_major_ver
        except Exception:
            pass
        XrayProcessDriver._cached_major_ver = 25
        return 25

    def supports_native_tun(self) -> bool:
        if self._native_tun_supported is not None:
            return self._native_tun_supported
        exe = self.xray_exe_path
        if not os.path.exists(exe):
            return False
        probe_cfg = {
            "log": {"loglevel": "none"},
            "inbounds": [{"tag": "t", "protocol": "tun", "settings": {"name": "AlanProbe", "MTU": 1400}}],
            "outbounds": [{"tag": "d", "protocol": "freedom"}],
        }
        tmp_path = os.path.join(self.configs_dir, "_probe_tun.json")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(probe_cfg, fh)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run([exe, "run", "-test", "-c", tmp_path], capture_output=True, timeout=3.0, creationflags=flags)
            self._native_tun_supported = res.returncode == 0
        except Exception:
            self._native_tun_supported = False
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return bool(self._native_tun_supported)

    def _build_routing_and_dns(self, settings: EngineSettings, physical_nic_alias: str = "") -> Tuple[dict, list, dict]:
        has_geosite = os.path.exists(os.path.join(self.core_dir, "geosite.dat"))
        has_geoip = os.path.exists(os.path.join(self.core_dir, "geoip.dat"))

        custom_direct = [x.strip() for x in (settings.custom_direct_domains or "").replace("\n", ",").split(",") if x.strip()]
        custom_proxy = [x.strip() for x in (settings.custom_proxy_domains or "").replace("\n", ",").split(",") if x.strip()]
        custom_block = [x.strip() for x in (settings.custom_blocked_domains or "").replace("\n", ",").split(",") if x.strip()]

        ir_domains = list(DIRECT_IR_DOMAINS)

        dns_cfg = {
            "servers": [
                settings.remote_dns or "1.1.1.1",
                {
                    "address": settings.domestic_dns or "178.22.122.100",
                    "domains": ir_domains,
                },
            ]
        }

        direct_outbound: dict = {"tag": "direct-out", "protocol": "freedom"}
        if physical_nic_alias:
            direct_outbound["streamSettings"] = {"sockopt": {"interface": physical_nic_alias}}

        extra_outbounds = [
            direct_outbound,
            {"tag": "block-out", "protocol": "blackhole"},
        ]

        rules: List[dict] = []
        if settings.block_quic:
            rules.append({"type": "field", "network": "udp", "port": "443", "outboundTag": "block-out"})

        if custom_block:
            rules.append({"type": "field", "domain": custom_block, "outboundTag": "block-out"})
        elif has_geosite and (settings.routing_mode != "global"):
            rules.append({"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block-out"})

        if custom_proxy:
            rules.append({"type": "field", "domain": custom_proxy, "outboundTag": "proxy-out"})

        if custom_direct:
            rules.append({"type": "field", "domain": custom_direct, "outboundTag": "direct-out"})

        rules.append({"type": "field", "ip": list(PRIVATE_CIDRS), "outboundTag": "direct-out"})

        if settings.routing_mode == "bypass_ir":
            rules.append({"type": "field", "domain": ir_domains, "outboundTag": "direct-out"})
            if has_geoip:
                rules.append({"type": "field", "ip": ["geoip:ir", "geoip:private"], "outboundTag": "direct-out"})

        routing_cfg = {
            "domainStrategy": "IPIfNonMatch",
            "rules": rules,
        }
        return dns_cfg, extra_outbounds, routing_cfg

    def _spawn_and_wait(self, exe: str, cfg_path: str, log_path: str, http_p: int) -> Tuple[bool, str]:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(log_path, "w", encoding="utf-8", errors="ignore") as log_fh:
            self.proc = subprocess.Popen(
                [exe, "run", "-c", cfg_path],
                cwd=self.core_dir,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )

        deadline = time.perf_counter() + 3.5
        while time.perf_counter() < deadline:
            if self.proc.poll() is not None:
                err_txt = ""
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as rfh:
                        lines = [ln.strip() for ln in rfh.read().splitlines() if ln.strip()]
                        err_txt = " | ".join(lines[-3:])[:260]
                except Exception:
                    pass
                return False, (err_txt or f"ExitCode={self.proc.returncode}")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            try:
                s.connect(("127.0.0.1", http_p))
                return True, ""
            except Exception:
                time.sleep(0.05)
            finally:
                s.close()

        return True, ""

    def ensure_running(
        self,
        uri: str,
        settings: EngineSettings,
        use_native_fragment: bool = False,
        direct_remote_host: str = "",
        direct_remote_port: int = 0,
        enable_native_tun_inbound: bool = False,
        physical_nic_alias: str = "",
        is_probe_mode: bool = False,
    ) -> Tuple[int, int]:
        exe = self.xray_exe_path
        if not os.path.exists(exe):
            raise FileNotFoundError(f"Xray binary missing at {exe}")

        self.stop()

        is_lab = bool(is_probe_mode) or (int(settings.bridge_port) >= 21000)
        socks_p = find_free_tcp_port(settings.socks_port)
        http_p = find_free_tcp_port(settings.http_port if (settings.http_port != socks_p) else (socks_p + 1))
        self.active_socks_port = socks_p
        self.active_http_port = http_p

        if use_native_fragment and direct_remote_host:
            target_h = direct_remote_host
            target_p = int(direct_remote_port)
            dialer_tag = "fragment-out"
        else:
            target_h = "127.0.0.1"
            target_p = int(settings.bridge_port)
            dialer_tag = ""

        strip_insecure = self._detect_xray_major_version() >= 26

        inbounds = [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": socks_p,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "sniffing": {"enabled": not is_lab, "destOverride": ["http", "tls", "quic"]},
            },
            {
                "tag": "http-in",
                "listen": "127.0.0.1",
                "port": http_p,
                "protocol": "http",
                "settings": {"allowTransparent": False},
                "sniffing": {"enabled": not is_lab, "destOverride": ["http", "tls", "quic"]},
            },
        ]

        if enable_native_tun_inbound and (not is_lab):
            inbounds.append({
                "tag": "tun-in",
                "protocol": "tun",
                "settings": {"name": "AlanTUN", "MTU": int(settings.tun_mtu or 1400), "userLevel": 0},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            })

        def _assemble_config(minimal: bool, force_strip_ins: bool) -> dict:
            p_out = UriConfigCodec.build_xray_outbound(
                uri=uri,
                settings=settings,
                target_host=target_h,
                target_port=target_p,
                tag="proxy-out",
                dialer_proxy=dialer_tag,
                strip_allow_insecure=force_strip_ins,
            )
            obs = [p_out]
            if dialer_tag == "fragment-out":
                frag_out: dict = {
                    "tag": "fragment-out",
                    "protocol": "freedom",
                    "settings": {
                        "fragment": {
                            "packets": settings.fragment_packets or "tlshello",
                            "length": settings.fragment_length or "5-16",
                            "interval": settings.fragment_interval or "2-3",
                        }
                    },
                    "streamSettings": {"sockopt": {"tcpNoDelay": True}},
                }
                if physical_nic_alias:
                    frag_out["streamSettings"]["sockopt"]["interface"] = physical_nic_alias
                obs.append(frag_out)

            if minimal:
                obs.append({"tag": "direct-out", "protocol": "freedom"})
                return {
                    "log": {"loglevel": "error"},
                    "inbounds": inbounds,
                    "outbounds": obs,
                }

            dns_cfg, extra_obs, routing_cfg = self._build_routing_and_dns(
                settings=settings,
                physical_nic_alias=physical_nic_alias,
            )
            obs.extend(extra_obs)
            return {
                "log": {"loglevel": "warning"},
                "dns": dns_cfg,
                "inbounds": inbounds,
                "outbounds": obs,
                "routing": routing_cfg,
            }

        prefix = f"lab_{http_p}" if is_lab else "active_runtime"
        cfg_path = os.path.join(self.configs_dir, f"{prefix}.json")
        log_path = os.path.join(self.configs_dir, f"{prefix}_xray.log")
        if is_lab:
            self._temp_cfg_file = cfg_path
            self._temp_log_file = log_path

        primary_cfg = _assemble_config(minimal=is_lab, force_strip_ins=strip_insecure)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(primary_cfg, fh, indent=2, ensure_ascii=False)

        ok, err_msg = self._spawn_and_wait(exe, cfg_path, log_path, http_p)
        if ok:
            return socks_p, http_p

        fallback_cfg = _assemble_config(minimal=True, force_strip_ins=True)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(fallback_cfg, fh, indent=2, ensure_ascii=False)

        ok_fb, err_fb = self._spawn_and_wait(exe, cfg_path, log_path, http_p)
        if ok_fb:
            self._log(f"[Xray] Started in compatibility mode ({err_msg[:90]})")
            return socks_p, http_p

        raise RuntimeError(f"Xray exited early: {err_fb or err_msg}")

    @staticmethod
    def _reserve_unique_ports(count: int) -> List[int]:
        holders = []
        ports: List[int] = []
        try:
            for _ in range(max(1, count)):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", 0))
                holders.append(s)
                ports.append(int(s.getsockname()[1]))
        finally:
            for s in holders:
                try:
                    s.close()
                except Exception:
                    pass
        return ports

    def batch_real_ping_and_gemini(
        self,
        nodes: List[ProfileNode],
        settings: EngineSettings,
        shared_cdn_ip: str = "",
        check_gemini: bool = False,
        chunk_size: int = 8,
        abort_check=None,
        progress_cb=None,
        on_chunk_done=None,
    ) -> Dict[str, Tuple[int, str]]:
        exe = self.xray_exe_path
        if (not os.path.exists(exe)) or (not nodes):
            return {}

        strip_insecure = self._detect_xray_major_version() >= 26
        results: Dict[str, Tuple[int, str]] = {}
        total = len(nodes)
        processed = 0
        lazy_cdn_cache: Dict[int, str] = {}
        cdn_lock = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _get_lazy_fallback_cdn_ip(port_num: int) -> str:
            if port_num in lazy_cdn_cache:
                return lazy_cdn_cache[port_num]
            if shared_cdn_ip and (CleanIpScanner.fast_tcp_ping(shared_cdn_ip, port_num, timeout=1.2) >= 0):
                lazy_cdn_cache[port_num] = shared_cdn_ip
                return shared_cdn_ip
            found = CleanIpScanner.discover_best_ips(port=port_num, top_n=1, sample_count=24)
            ip_res = found[0][0] if found else ""
            lazy_cdn_cache[port_num] = ip_res
            return ip_res

        def _run_subchunk(sub_batch: List[ProfileNode]) -> Dict[str, Tuple[int, str]]:
            sub_res: Dict[str, Tuple[int, str]] = {}

            def _prep_endpoint(nd: ProfileNode) -> Tuple[ProfileNode, str]:
                if not CleanIpScanner.is_cdn_eligible(nd):
                    nd.cached_clean_ip = ""
                orig_ip = CleanIpScanner.resolve_unpoisoned_ipv4(nd.original_host, timeout=1.5)
                if orig_ip and (not CleanIpScanner.is_poisoned_ip(orig_ip)):
                    if CleanIpScanner.fast_tcp_ping(orig_ip, nd.port, timeout=1.5) >= 0:
                        return nd, orig_ip
                if nd.cached_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
                    if CleanIpScanner.fast_tcp_ping(nd.cached_clean_ip, nd.port, timeout=1.4) >= 0:
                        return nd, nd.cached_clean_ip
                if settings.auto_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
                    fb_ip = cdn_lock.submit(_get_lazy_fallback_cdn_ip, nd.port).result()
                    if fb_ip and (CleanIpScanner.fast_tcp_ping(fb_ip, nd.port, timeout=1.4) >= 0):
                        return nd, fb_ip
                return nd, ""

            alive_pairs: List[Tuple[ProfileNode, str]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(sub_batch))) as pre_pool:
                for nd_item, ep_ok in pre_pool.map(_prep_endpoint, sub_batch):
                    if ep_ok:
                        alive_pairs.append((nd_item, ep_ok))
                    else:
                        sub_res[nd_item.uid] = (-1, "UNKNOWN")

            if not alive_pairs:
                return sub_res

            reserved = self._reserve_unique_ports(len(alive_pairs) * 2)
            bridges: List[FullDuplexMutatorBridge] = []
            inbounds: List[dict] = []
            outbounds: List[dict] = []
            rules: List[dict] = []
            probe_entries: List[Tuple[ProfileNode, int, FullDuplexMutatorBridge, str, bool]] = []
            tmp_proc: Optional[subprocess.Popen] = None
            tmp_cfg_path = ""

            try:
                for idx, (node, ep_host) in enumerate(alive_pairs):
                    b_port = reserved[idx * 2]
                    h_port = reserved[(idx * 2) + 1]
                    try:
                        ob = UriConfigCodec.build_xray_outbound(
                            uri=node.uri,
                            settings=settings,
                            target_host="127.0.0.1",
                            target_port=b_port,
                            tag=f"out-{idx}",
                            strip_allow_insecure=strip_insecure,
                        )
                    except Exception:
                        sub_res[node.uid] = (-1, "UNKNOWN")
                        continue

                    uri_low = node.uri.lower()
                    is_direct = (
                        CleanIpScanner.is_domestic_or_direct_tunnel(node)
                        or ("security=reality" in uri_low)
                        or ("security=none" in uri_low)
                    )
                    init_vec_id = node.cached_vector_id or ("VEC-00" if is_direct else "VEC-21")
                    br = FullDuplexMutatorBridge(listen_port=b_port)
                    br.update_route(
                        remote_host=ep_host,
                        remote_port=node.port,
                        vector=find_vector(init_vec_id),
                        custom_stride=settings.forward_stride_bytes,
                        jitter_bytes=settings.stride_jitter_bytes,
                        raw_passthrough=(is_direct or init_vec_id == "VEC-00"),
                    )
                    br.start()
                    bridges.append(br)

                    in_tag = f"in-{idx}"
                    inbounds.append({
                        "tag": in_tag,
                        "listen": "127.0.0.1",
                        "port": h_port,
                        "protocol": "http",
                        "settings": {"allowTransparent": False},
                    })
                    outbounds.append(ob)
                    rules.append({"type": "field", "inboundTag": [in_tag], "outboundTag": f"out-{idx}"})
                    probe_entries.append((node, h_port, br, ep_host, is_direct))

                if not probe_entries:
                    return sub_res

                fd, tmp_cfg_path = tempfile.mkstemp(prefix="ping_", suffix=".json", dir=self.configs_dir)
                os.close(fd)
                with open(tmp_cfg_path, "w", encoding="utf-8") as fh:
                    json.dump(
                        {
                            "log": {"loglevel": "none"},
                            "inbounds": inbounds,
                            "outbounds": outbounds,
                            "routing": {"rules": rules},
                        },
                        fh,
                    )

                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                tmp_proc = subprocess.Popen(
                    [exe, "run", "-c", tmp_cfg_path],
                    cwd=self.core_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=flags,
                )

                first_hp = probe_entries[0][1]
                ready = False
                wait_until = time.perf_counter() + 3.8
                while time.perf_counter() < wait_until:
                    if tmp_proc.poll() is not None:
                        break
                    s_chk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s_chk.settimeout(0.12)
                    try:
                        s_chk.connect(("127.0.0.1", first_hp))
                        ready = True
                        break
                    except Exception:
                        time.sleep(0.05)
                    finally:
                        s_chk.close()

                if (not ready) and (tmp_proc.poll() is not None) and (len(sub_batch) > 1):
                    for br in bridges:
                        br.stop()
                    bridges.clear()
                    for single_nd, _ in alive_pairs:
                        sub_res.update(_run_subchunk([single_nd]))
                    return sub_res

                if not ready:
                    for nd_item, _, _, _, _ in probe_entries:
                        sub_res[nd_item.uid] = (-1, "UNKNOWN")
                    return sub_res

                def _probe_entry(entry: Tuple[ProfileNode, int, FullDuplexMutatorBridge, str, bool]) -> Tuple[str, int, str]:
                    nd, hp, br, ep_h, is_dir = entry
                    used_vec = br.active_vector.vector_id
                    active_ep = ep_h
                    ok, rtt, _ = TunnelStreamVerifier.fast_probe(hp, timeout=4.0)

                    if (not ok) and (not is_dir):
                        for fb_vid in ("VEC-01", "VEC-20"):
                            if fb_vid == used_vec:
                                continue
                            br.update_route(
                                remote_host=active_ep,
                                remote_port=nd.port,
                                vector=find_vector(fb_vid),
                                custom_stride=settings.forward_stride_bytes,
                                jitter_bytes=settings.stride_jitter_bytes,
                                raw_passthrough=False,
                                flush_existing_pool=True,
                            )
                            ok, rtt, _ = TunnelStreamVerifier.fast_probe(hp, timeout=3.6)
                            if ok:
                                used_vec = fb_vid
                                break

                    if (not ok) and (not is_dir) and settings.auto_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
                        fb_cdn_ip = cdn_lock.submit(_get_lazy_fallback_cdn_ip, nd.port).result()
                        if fb_cdn_ip and (fb_cdn_ip != active_ep):
                            for fb_vid in ("VEC-21", "VEC-01"):
                                br.update_route(
                                    remote_host=fb_cdn_ip,
                                    remote_port=nd.port,
                                    vector=find_vector(fb_vid),
                                    custom_stride=settings.forward_stride_bytes,
                                    jitter_bytes=settings.stride_jitter_bytes,
                                    raw_passthrough=False,
                                    flush_existing_pool=True,
                                )
                                ok, rtt, _ = TunnelStreamVerifier.fast_probe(hp, timeout=3.8)
                                if ok:
                                    used_vec = fb_vid
                                    active_ep = fb_cdn_ip
                                    break

                    if not ok:
                        return nd.uid, -1, "UNKNOWN"

                    nd.cached_vector_id = used_vec
                    orig_resolved = CleanIpScanner.resolve_unpoisoned_ipv4(nd.original_host, timeout=1.0)
                    if active_ep in (nd.original_host, orig_resolved):
                        nd.cached_clean_ip = ""
                    elif CleanIpScanner.is_cdn_eligible(nd):
                        nd.cached_clean_ip = active_ep

                    gem_stat = nd.gemini_status if (nd.gemini_status == "OK") else "UNKNOWN"
                    if check_gemini:
                        g_ok, _ = TunnelStreamVerifier.check_gemini_access(hp, timeout=5.2)
                        gem_stat = "OK" if g_ok else "BLOCKED"
                    return nd.uid, rtt, gem_stat

                with concurrent.futures.ThreadPoolExecutor(max_workers=len(probe_entries)) as ex_pool:
                    for uid_v, rtt_v, gem_v in ex_pool.map(_probe_entry, probe_entries):
                        sub_res[uid_v] = (rtt_v, gem_v)

                return sub_res
            finally:
                if tmp_proc is not None:
                    try:
                        tmp_proc.terminate()
                        tmp_proc.wait(timeout=1.2)
                    except Exception:
                        try:
                            tmp_proc.kill()
                        except Exception:
                            pass
                for br in bridges:
                    br.stop()
                if tmp_cfg_path and os.path.exists(tmp_cfg_path):
                    try:
                        os.remove(tmp_cfg_path)
                    except Exception:
                        pass

        try:
            step_sz = max(1, int(chunk_size))
            for start in range(0, total, step_sz):
                if (abort_check is not None) and abort_check():
                    break
                batch = nodes[start : start + step_sz]
                chunk_out = _run_subchunk(batch)
                results.update(chunk_out)
                if on_chunk_done is not None:
                    try:
                        on_chunk_done(chunk_out)
                    except Exception:
                        pass
                processed += len(batch)
                if progress_cb is not None:
                    pct = min(99, int((processed / max(1, total)) * 100))
                    progress_cb(pct, f"پینگ واقعی تونل ({processed}/{total})...")
        finally:
            cdn_lock.shutdown(wait=False)

        return results

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

        for fpath in (self._temp_cfg_file, self._temp_log_file):
            if fpath and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        self._temp_cfg_file = ""
        self._temp_log_file = ""