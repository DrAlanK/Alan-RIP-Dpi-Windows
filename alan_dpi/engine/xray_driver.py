import atexit
import base64
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import urllib.parse
from typing import Callable, Dict, Optional, Tuple
from alan_dpi.engine.models import EngineSettings, ProfileNode

try:
    import winreg
except ImportError:
    winreg = None


TLS_DEFAULT_PORTS = (443, 2053, 2083, 2087, 2096, 8443)


def _is_truthy_param(val: str) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


class SystemProxyController:
    @staticmethod
    def apply(enable: bool, http_port: int = 10809):
        if os.name != "nt" or winreg is None:
            return
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                if enable:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{http_port}")
                    winreg.SetValueEx(
                        key,
                        "ProxyOverride",
                        0,
                        winreg.REG_SZ,
                        "localhost;127.*;10.*;192.168.*;198.18.*;<local>",
                    )
                else:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

            try:
                ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
                ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
            except Exception:
                pass
        except Exception:
            pass


atexit.register(SystemProxyController.apply, False)


class UriConfigCodec:
    @staticmethod
    def _decode_ss_components(uri: str) -> Tuple[str, str, str, int, str]:
        parsed = urllib.parse.urlsplit(uri.strip())
        remark = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
        raw_netloc = parsed.netloc

        user_info = ""
        host_port = ""
        if "@" in raw_netloc:
            raw_user, host_port = raw_netloc.rsplit("@", 1)
            unquoted_user = urllib.parse.unquote(raw_user)
            if ":" in unquoted_user:
                user_info = unquoted_user
            else:
                padded = unquoted_user + ("=" * ((4 - (len(unquoted_user) % 4)) % 4))
                try:
                    user_info = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
                except Exception:
                    user_info = unquoted_user
        else:
            b64_part = urllib.parse.unquote(raw_netloc)
            padded = b64_part + ("=" * ((4 - (len(b64_part) % 4)) % 4))
            dec = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            if "@" in dec:
                user_info, host_port = dec.rsplit("@", 1)

        if ":" in user_info:
            method, password = user_info.split(":", 1)
        else:
            method, password = "chacha20-ietf-poly1305", user_info

        host_port = host_port.split("/")[0].strip()
        if host_port.startswith("[") and "]:" in host_port:
            r_host, port_str = host_port[1:].split("]:", 1)
        elif ":" in host_port:
            r_host, port_str = host_port.rsplit(":", 1)
        else:
            r_host, port_str = (parsed.hostname or ""), str(parsed.port or 443)

        r_port = int(port_str)
        return method.strip(), password, r_host.strip(), r_port, (remark or r_host.strip())

    @staticmethod
    def _build_http_tcp_settings(host_header: str, path_str: str) -> Dict:
        hosts = [h.strip() for h in (host_header or "").split(",") if h.strip()]
        paths = [p.strip() for p in (path_str or "/").split(",") if p.strip()] or ["/"]
        req_headers = {
            "User-Agent": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ],
            "Accept-Encoding": ["gzip, deflate"],
            "Connection": ["keep-alive"],
            "Pragma": "no-cache",
        }
        if hosts:
            req_headers["Host"] = hosts
        return {
            "header": {
                "type": "http",
                "request": {
                    "version": "1.1",
                    "method": "GET",
                    "path": paths,
                    "headers": req_headers,
                },
            }
        }

    @staticmethod
    def replace_endpoint_ip(uri: str, new_ip: str) -> str:
        uri = uri.strip()
        new_ip = new_ip.strip()
        if not uri or not new_ip:
            return uri

        if uri.startswith(("vless://", "trojan://")):
            parsed = urllib.parse.urlsplit(uri)
            user = parsed.username or ""
            port = parsed.port or 443
            params = urllib.parse.parse_qs(parsed.query)
            orig_host = parsed.hostname or ""
            if orig_host and (not orig_host.replace(".", "").isdigit()):
                if ("sni" not in params) and (params.get("security", [""])[0] in ("tls", "reality")):
                    params["sni"] = [orig_host]
                if "host" not in params:
                    params["host"] = [orig_host]
            new_query = urllib.parse.urlencode(params, doseq=True)
            new_netloc = f"{user}@{new_ip}:{port}"
            return urllib.parse.urlunsplit((parsed.scheme, new_netloc, parsed.path, new_query, parsed.fragment))

        if uri.startswith("vmess://"):
            try:
                b64 = uri[8:] + ("=" * ((4 - (len(uri[8:]) % 4)) % 4))
                v_data = json.loads(base64.b64decode(b64).decode("utf-8"))
                orig_add = v_data.get("add", "")
                if orig_add and (not orig_add.replace(".", "").isdigit()):
                    if (not v_data.get("sni")) and (v_data.get("tls") == "tls"):
                        v_data["sni"] = orig_add
                    if not v_data.get("host"):
                        v_data["host"] = orig_add
                v_data["add"] = new_ip
                encoded = base64.b64encode(json.dumps(v_data, ensure_ascii=False).encode("utf-8")).decode("ascii")
                return f"vmess://{encoded}"
            except Exception:
                return uri

        return uri

    @staticmethod
    def update_remark(uri: str, new_remark: str) -> str:
        uri = uri.strip()
        new_remark = new_remark.strip()
        if uri.startswith(("vless://", "trojan://", "ss://")):
            parsed = urllib.parse.urlsplit(uri)
            return urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.query, urllib.parse.quote(new_remark))
            )
        if uri.startswith("vmess://"):
            try:
                b64 = uri[8:] + ("=" * ((4 - (len(uri[8:]) % 4)) % 4))
                v_data = json.loads(base64.b64decode(b64).decode("utf-8"))
                v_data["ps"] = new_remark
                encoded = base64.b64encode(json.dumps(v_data, ensure_ascii=False).encode("utf-8")).decode("ascii")
                return f"vmess://{encoded}"
            except Exception:
                return uri
        return uri

    @staticmethod
    def parse_editable_fields(node: ProfileNode) -> dict:
        uri = node.uri.strip()
        base = {
            "uid": node.uid,
            "name": node.name,
            "group_tag": node.group_tag,
            "protocol": "vless",
            "address": node.cached_clean_ip or node.original_host,
            "port": int(node.port),
            "uuid_or_password": "",
            "network": "ws",
            "header_type": "none",
            "security": "tls",
            "allow_insecure": False,
            "sni": node.sni,
            "host_header": node.sni,
            "path": "/",
            "alpn": "http/1.1",
            "fingerprint": "chrome",
            "flow": "",
            "pbk": "",
            "sid": "",
            "scy": "auto",
            "preferred_vector_id": node.cached_vector_id or "AUTO",
            "raw_uri": uri,
        }

        if uri.startswith(("vless://", "trojan://")):
            parsed = urllib.parse.urlsplit(uri)
            params = urllib.parse.parse_qs(parsed.query)
            port = parsed.port or 443
            default_sec = "tls" if port in TLS_DEFAULT_PORTS else "none"
            sec = params.get("security", [default_sec])[0]
            net = params.get("type", ["ws" if uri.startswith("vless://") else "tcp"])[0]
            hdr_type = params.get("headerType", ["none"])[0]
            sni = params.get("sni", [parsed.hostname or ""])[0].split("#mut=")[0]
            host_hdr = params.get("host", [sni])[0]
            path_val = (
                params.get("serviceName", [params.get("path", ["/"])[0]])[0]
                if net == "grpc"
                else params.get("path", ["/"])[0]
            )
            insec = _is_truthy_param(params.get("allowInsecure", ["0"])[0]) or _is_truthy_param(
                params.get("insecure", ["0"])[0]
            )
            base.update({
                "protocol": "vless" if uri.startswith("vless://") else "trojan",
                "address": parsed.hostname or node.original_host,
                "port": int(port),
                "uuid_or_password": urllib.parse.unquote(parsed.username or ""),
                "network": net,
                "header_type": hdr_type,
                "security": sec,
                "allow_insecure": insec,
                "sni": sni,
                "host_header": host_hdr,
                "path": path_val,
                "alpn": params.get("alpn", ["http/1.1"])[0],
                "fingerprint": params.get("fp", ["chrome"])[0],
                "flow": params.get("flow", [""])[0],
                "pbk": params.get("pbk", [""])[0],
                "sid": params.get("sid", [""])[0],
                "scy": params.get("encryption", ["none"])[0],
            })
        elif uri.startswith("vmess://"):
            try:
                b64 = uri[8:] + ("=" * ((4 - (len(uri[8:]) % 4)) % 4))
                v = json.loads(base64.b64decode(b64).decode("utf-8"))
                base.update({
                    "protocol": "vmess",
                    "address": v.get("add", node.original_host),
                    "port": int(v.get("port", 443)),
                    "uuid_or_password": v.get("id", ""),
                    "network": v.get("net", "ws"),
                    "header_type": v.get("type", "none"),
                    "security": v.get("tls") if v.get("tls") in ("tls", "reality") else "none",
                    "allow_insecure": _is_truthy_param(str(v.get("allowInsecure", "0"))),
                    "sni": v.get("sni") or v.get("host") or v.get("add", ""),
                    "host_header": v.get("host") or v.get("sni") or "",
                    "path": v.get("path") or "/",
                    "alpn": v.get("alpn", "http/1.1"),
                    "fingerprint": v.get("fp", "chrome"),
                    "scy": v.get("scy", "auto"),
                })
            except Exception:
                pass
        elif uri.startswith("ss://"):
            method, password, r_host, r_port, _ = UriConfigCodec._decode_ss_components(uri)
            base.update({
                "protocol": "ss",
                "address": r_host,
                "port": r_port,
                "uuid_or_password": password,
                "scy": method,
                "network": "tcp",
                "security": "none",
            })

        return base

    @staticmethod
    def build_uri_from_editable(fields: dict) -> str:
        proto = str(fields.get("protocol", "vless")).lower().strip()
        name = str(fields.get("name", "Profile")).strip() or "Profile"
        addr = str(fields.get("address", "")).strip()
        port = int(fields.get("port", 443) or 443)
        secret = str(fields.get("uuid_or_password", "")).strip()
        net = str(fields.get("network", "ws")).strip() or "ws"
        hdr_type = str(fields.get("header_type", "none")).strip() or "none"
        sec = str(fields.get("security", "tls")).strip() or "none"
        insec = bool(fields.get("allow_insecure", False))
        sni = str(fields.get("sni", "")).strip()
        host_hdr = str(fields.get("host_header", "")).strip()
        path_val = str(fields.get("path", "/")).strip() or "/"
        alpn = str(fields.get("alpn", "http/1.1")).strip()
        fp = str(fields.get("fingerprint", "chrome")).strip()
        flow = str(fields.get("flow", "")).strip()
        pbk = str(fields.get("pbk", "")).strip()
        sid = str(fields.get("sid", "")).strip()
        scy = str(fields.get("scy", "auto")).strip()

        if not addr:
            raise ValueError("Server address cannot be empty.")

        if proto in ("vless", "trojan"):
            q = {"type": net, "security": sec}
            if hdr_type != "none":
                q["headerType"] = hdr_type
            if proto == "vless":
                q["encryption"] = scy if (scy and scy != "auto") else "none"
                if flow:
                    q["flow"] = flow
            if net == "grpc":
                q["serviceName"] = path_val
            else:
                q["path"] = path_val
                if host_hdr:
                    q["host"] = host_hdr
            if sec in ("tls", "reality"):
                if sni:
                    q["sni"] = sni
                if fp:
                    q["fp"] = fp
                if alpn and (sec == "tls"):
                    q["alpn"] = alpn
                if insec and (sec == "tls"):
                    q["allowInsecure"] = "1"
                if sec == "reality":
                    if pbk:
                        q["pbk"] = pbk
                    if sid:
                        q["sid"] = sid
            query_str = urllib.parse.urlencode(q)
            return f"{proto}://{urllib.parse.quote(secret)}@{addr}:{port}?{query_str}#{urllib.parse.quote(name)}"

        if proto == "vmess":
            v_obj = {
                "v": "2",
                "ps": name,
                "add": addr,
                "port": str(port),
                "id": secret,
                "aid": "0",
                "scy": scy or "auto",
                "net": net,
                "type": hdr_type,
                "host": host_hdr,
                "path": path_val,
                "tls": "tls" if sec == "tls" else "",
                "sni": sni,
                "alpn": alpn,
                "fp": fp,
            }
            if insec:
                v_obj["allowInsecure"] = 1
            enc = base64.b64encode(json.dumps(v_obj, ensure_ascii=False).encode("utf-8")).decode("ascii")
            return f"vmess://{enc}"

        if proto in ("ss", "shadowsocks"):
            method = scy if (scy and scy not in ("none", "auto")) else "chacha20-ietf-poly1305"
            userinfo = base64.urlsafe_b64encode(f"{method}:{secret}".encode("utf-8")).decode("ascii").rstrip("=")
            return f"ss://{userinfo}@{addr}:{port}#{urllib.parse.quote(name)}"

        raise ValueError(f"Unsupported protocol: {proto}")

    @staticmethod
    def build_exportable_uri(node: ProfileNode, inject_early_data: int = 0) -> str:
        out_uri = node.uri
        if node.cached_clean_ip:
            out_uri = UriConfigCodec.replace_endpoint_ip(out_uri, node.cached_clean_ip)
        if (inject_early_data > 0) and out_uri.startswith("vless://"):
            parsed = urllib.parse.urlsplit(out_uri)
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("type", ["ws"])[0] == "ws":
                cur_path = params.get("path", ["/"])[0]
                if "ed=" not in cur_path:
                    sep = "&" if "?" in cur_path else "?"
                    params["path"] = [f"{cur_path}{sep}ed={inject_early_data}"]
                    new_q = urllib.parse.urlencode(params, doseq=True)
                    out_uri = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_q, parsed.fragment))
        return UriConfigCodec.update_remark(out_uri, node.name)

    @staticmethod
    def extract_profile_node(uri: str, group_tag: str = "Manual") -> ProfileNode:
        _, meta = UriConfigCodec.compile_xray_config(uri)
        return ProfileNode(
            uri=uri.strip(),
            name=meta["name"],
            protocol=meta["protocol"],
            original_host=meta["remote_host"],
            port=int(meta["remote_port"]),
            sni=meta["sni"],
            group_tag=group_tag,
        )

    @staticmethod
    def _apply_early_data_path(ws_path: str, early_data: int) -> str:
        if (early_data <= 0) or ("ed=" in ws_path):
            return ws_path
        sep = "&" if "?" in ws_path else "?"
        return f"{ws_path}{sep}ed={early_data}"

    @staticmethod
    def compile_xray_config(
        uri: str,
        settings: Optional[EngineSettings] = None,
        use_native_fragment: bool = False,
        socks_port_override: Optional[int] = None,
        http_port_override: Optional[int] = None,
    ) -> Tuple[Dict, Dict]:
        cfg = settings or EngineSettings()
        s_port = int(socks_port_override or cfg.socks_port)
        h_port = int(http_port_override or cfg.http_port)
        uri = uri.strip()

        inbounds = [
            {
                "tag": "socks-in",
                "port": s_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True},
                "settings": {"auth": "noauth", "udp": True},
            },
            {
                "tag": "http-in",
                "port": h_port,
                "listen": "127.0.0.1",
                "protocol": "http",
                "settings": {},
            },
        ]

        base_sockopt: Dict = {
            "tcpKeepAliveInterval": 15,
            "tcpKeepAliveIdle": 11,
            "tcpNoDelay": True,
        }
        if use_native_fragment and cfg.fragment_enabled:
            base_sockopt["dialerProxy"] = "fragment-out"

        mux_block = {"enabled": bool(cfg.mux_enabled), "concurrency": int(cfg.mux_concurrency)}

        def _resolve_alpn(default_list):
            if cfg.alpn_override and (cfg.alpn_override != "auto"):
                return [x.strip() for x in cfg.alpn_override.split(",") if x.strip()]
            return default_list

        outbound: Dict = {}
        meta: Dict = {}

        if uri.startswith("vless://"):
            parsed = urllib.parse.urlsplit(uri)
            uuid_val = urllib.parse.unquote(parsed.username or "")
            remote_host = parsed.hostname or ""
            remote_port = parsed.port or 443
            params = urllib.parse.parse_qs(parsed.query)

            default_sec = "tls" if remote_port in TLS_DEFAULT_PORTS else "none"
            security = params.get("security", [default_sec])[0]
            network = params.get("type", ["tcp"])[0]
            header_type = params.get("headerType", ["none"])[0]
            clean_sni = params.get("sni", [params.get("host", [remote_host])[0]])[0].split("#mut=")[0].strip()
            ws_host = params.get("host", [clean_sni])[0].strip()
            raw_path = params.get("path", ["/"])[0].strip() or "/"
            ws_path = UriConfigCodec._apply_early_data_path(raw_path, cfg.ws_early_data)
            alpn_raw = params.get("alpn", [""])[0]
            alpn_default = ["http/1.1"] if network in ("ws", "httpupgrade") else ["h2", "http/1.1"]
            alpn_list = _resolve_alpn([x.strip() for x in alpn_raw.split(",") if x.strip()] or alpn_default)
            allow_insecure = _is_truthy_param(params.get("allowInsecure", ["0"])[0]) or _is_truthy_param(
                params.get("insecure", ["0"])[0]
            )
            pbk = params.get("pbk", [""])[0]
            sid = params.get("sid", [""])[0]
            spx = params.get("spx", [""])[0]
            flow = params.get("flow", [""])[0]
            encryption = params.get("encryption", ["none"])[0] or "none"
            fp_val = params.get("fp", [cfg.fingerprint])[0] or cfg.fingerprint

            stream_settings: Dict = {"network": network, "security": security, "sockopt": base_sockopt}
            if (network == "tcp") and (header_type == "http"):
                stream_settings["tcpSettings"] = UriConfigCodec._build_http_tcp_settings(ws_host, raw_path)
            elif network == "ws":
                stream_settings["wsSettings"] = {"path": ws_path, "headers": {"Host": ws_host} if ws_host else {}}
            elif network == "httpupgrade":
                stream_settings["httpupgradeSettings"] = {"path": ws_path, "host": ws_host}
            elif network in ("xhttp", "splithttp"):
                key_name = "xhttpSettings" if network == "xhttp" else "splithttpSettings"
                stream_settings[key_name] = {
                    "path": raw_path,
                    "host": ws_host,
                    "mode": params.get("mode", ["auto"])[0],
                }
            elif network == "grpc":
                stream_settings["grpcSettings"] = {
                    "serviceName": params.get("serviceName", [""])[0],
                    "multiMode": (params.get("mode", ["gun"])[0] == "multi"),
                }

            if security == "tls":
                stream_settings["tlsSettings"] = {
                    "serverName": clean_sni,
                    "allowInsecure": allow_insecure,
                    "alpn": alpn_list,
                    "fingerprint": cfg.fingerprint or fp_val,
                }
            elif security == "reality":
                stream_settings["realitySettings"] = {
                    "serverName": clean_sni,
                    "publicKey": pbk,
                    "shortId": sid,
                    "spiderX": spx,
                    "fingerprint": fp_val,
                }

            outbound = {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": cfg.bridge_port,
                            "users": [{"id": uuid_val, "encryption": encryption, "flow": flow}],
                        }
                    ]
                },
                "streamSettings": stream_settings,
            }
            if cfg.mux_enabled and (not flow):
                outbound["mux"] = mux_block

            display_sni = ws_host if ((security == "none") and ws_host) else clean_sni
            meta = {
                "protocol": "VLESS",
                "name": urllib.parse.unquote(parsed.fragment) if parsed.fragment else remote_host,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "sni": display_sni,
                "security": security,
            }

        elif uri.startswith("vmess://"):
            b64 = uri[8:] + ("=" * ((4 - (len(uri[8:]) % 4)) % 4))
            v_data = json.loads(base64.b64decode(b64).decode("utf-8"))

            remote_host = v_data.get("add", "")
            remote_port = int(v_data.get("port", 443))
            clean_sni = v_data.get("sni") or v_data.get("host") or remote_host
            ws_host = v_data.get("host") or clean_sni
            raw_path = v_data.get("path") or "/"
            ws_path = UriConfigCodec._apply_early_data_path(raw_path, cfg.ws_early_data)
            network = v_data.get("net", "tcp")
            header_type = v_data.get("type", "none")
            raw_tls = str(v_data.get("tls", "")).lower()
            security = "tls" if raw_tls == "tls" else "none"
            allow_insecure = _is_truthy_param(str(v_data.get("allowInsecure", "0"))) or (
                v_data.get("verify_cert") is False
            )

            stream_settings = {"network": network, "security": security, "sockopt": base_sockopt}
            if (network == "tcp") and (header_type == "http"):
                stream_settings["tcpSettings"] = UriConfigCodec._build_http_tcp_settings(ws_host, raw_path)
            elif network == "ws":
                stream_settings["wsSettings"] = {"path": ws_path, "headers": {"Host": ws_host} if ws_host else {}}
            elif network == "grpc":
                stream_settings["grpcSettings"] = {"serviceName": raw_path}

            if security == "tls":
                stream_settings["tlsSettings"] = {
                    "serverName": clean_sni,
                    "allowInsecure": allow_insecure,
                    "alpn": _resolve_alpn(["http/1.1"] if network == "ws" else ["h2", "http/1.1"]),
                    "fingerprint": cfg.fingerprint,
                }

            outbound = {
                "tag": "proxy",
                "protocol": "vmess",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": cfg.bridge_port,
                            "users": [
                                {
                                    "id": v_data.get("id"),
                                    "alterId": int(v_data.get("aid", 0)),
                                    "security": v_data.get("scy") or "auto",
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": stream_settings,
                "mux": mux_block,
            }
            meta = {
                "protocol": "VMess",
                "name": v_data.get("ps") or remote_host,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "sni": clean_sni,
                "security": security,
            }

        elif uri.startswith("trojan://"):
            parsed = urllib.parse.urlsplit(uri)
            password = urllib.parse.unquote(parsed.username or "")
            remote_host = parsed.hostname or ""
            remote_port = parsed.port or 443
            params = urllib.parse.parse_qs(parsed.query)

            security = params.get("security", ["tls"])[0]
            network = params.get("type", ["tcp"])[0]
            header_type = params.get("headerType", ["none"])[0]
            clean_sni = params.get("sni", [remote_host])[0].split("#mut=")[0].strip()
            ws_host = params.get("host", [clean_sni])[0].strip()
            raw_path = params.get("path", ["/"])[0].strip() or "/"
            ws_path = UriConfigCodec._apply_early_data_path(raw_path, cfg.ws_early_data)
            alpn_raw = params.get("alpn", [""])[0]
            alpn_default = ["http/1.1"] if network == "ws" else ["h2", "http/1.1"]
            alpn_list = _resolve_alpn([x.strip() for x in alpn_raw.split(",") if x.strip()] or alpn_default)
            allow_insecure = _is_truthy_param(params.get("allowInsecure", ["0"])[0]) or _is_truthy_param(
                params.get("insecure", ["0"])[0]
            )

            stream_settings = {"network": network, "security": security, "sockopt": base_sockopt}
            if (network == "tcp") and (header_type == "http"):
                stream_settings["tcpSettings"] = UriConfigCodec._build_http_tcp_settings(ws_host, raw_path)
            elif network == "ws":
                stream_settings["wsSettings"] = {"path": ws_path, "headers": {"Host": ws_host} if ws_host else {}}
            elif network == "grpc":
                stream_settings["grpcSettings"] = {"serviceName": params.get("serviceName", [""])[0]}

            if security == "tls":
                stream_settings["tlsSettings"] = {
                    "serverName": clean_sni,
                    "allowInsecure": allow_insecure,
                    "alpn": alpn_list,
                    "fingerprint": cfg.fingerprint,
                }
            elif security == "reality":
                stream_settings["realitySettings"] = {
                    "serverName": clean_sni,
                    "publicKey": params.get("pbk", [""])[0],
                    "shortId": params.get("sid", [""])[0],
                    "fingerprint": cfg.fingerprint,
                }

            outbound = {
                "tag": "proxy",
                "protocol": "trojan",
                "settings": {
                    "servers": [{"address": "127.0.0.1", "port": cfg.bridge_port, "password": password}]
                },
                "streamSettings": stream_settings,
                "mux": mux_block,
            }
            meta = {
                "protocol": "Trojan",
                "name": urllib.parse.unquote(parsed.fragment) if parsed.fragment else remote_host,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "sni": clean_sni,
                "security": security,
            }

        elif uri.startswith("ss://"):
            method, password, remote_host, remote_port, remark_name = UriConfigCodec._decode_ss_components(uri)
            outbound = {
                "tag": "proxy",
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [
                        {
                            "address": "127.0.0.1",
                            "port": cfg.bridge_port,
                            "method": method,
                            "password": password,
                            "uot": True,
                        }
                    ]
                },
                "streamSettings": {"network": "tcp", "security": "none", "sockopt": base_sockopt},
            }
            meta = {
                "protocol": "Shadowsocks",
                "name": remark_name,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "sni": remote_host,
                "security": "none",
            }
        else:
            raise ValueError("Unsupported protocol URI (allowed: vless, vmess, trojan, ss).")

        outbounds = [outbound]
        if use_native_fragment and cfg.fragment_enabled:
            outbounds.append({
                "tag": "fragment-out",
                "protocol": "freedom",
                "settings": {
                    "fragment": {
                        "packets": cfg.fragment_packets.strip() or "tlshello",
                        "length": cfg.fragment_length.strip() or "5-16",
                        "interval": cfg.fragment_interval.strip() or "2-3",
                    }
                },
                "streamSettings": {"sockopt": {"tcpNoDelay": True}},
            })

        return {"log": {"loglevel": "warning"}, "inbounds": inbounds, "outbounds": outbounds}, meta


class XrayProcessDriver:
    def __init__(self, core_dir: str, configs_dir: str, log_fn: Optional[Callable[[str], None]] = None):
        self.core_dir = core_dir
        self.configs_dir = configs_dir
        self.proc: Optional[subprocess.Popen] = None
        self._active_digest: str = ""
        self._lock = threading.Lock()
        self._log_fn = log_fn

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)

    @property
    def is_running(self) -> bool:
        return (self.proc is not None) and (self.proc.poll() is None)

    @staticmethod
    def _is_port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                s.bind(("127.0.0.1", int(port)))
                return True
            except OSError:
                return False

    @classmethod
    def _allocate_port(cls, preferred: int, excluded: set) -> int:
        if (preferred not in excluded) and cls._is_port_free(preferred):
            return int(preferred)
        for candidate in range(20810, 20960):
            if (candidate not in excluded) and cls._is_port_free(candidate):
                return candidate
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def ensure_running(
        self,
        uri: str,
        settings: EngineSettings,
        use_native_fragment: bool = False,
    ) -> Dict:
        xray_doc, meta = UriConfigCodec.compile_xray_config(
            uri=uri,
            settings=settings,
            use_native_fragment=use_native_fragment,
        )
        serialized = json.dumps(xray_doc, sort_keys=True, indent=2)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        with self._lock:
            if self.is_running and (digest == self._active_digest):
                return meta

        self.stop()

        reserved = {int(settings.bridge_port)}
        free_socks = self._allocate_port(int(settings.socks_port), reserved)
        reserved.add(free_socks)
        free_http = self._allocate_port(int(settings.http_port), reserved)

        if (free_socks != settings.socks_port) or (free_http != settings.http_port):
            self._log(
                f"[Xray] Port busy; switched local ports to SOCKS={free_socks}, HTTP={free_http}"
            )
            settings.socks_port = free_socks
            settings.http_port = free_http
            xray_doc, meta = UriConfigCodec.compile_xray_config(
                uri=uri,
                settings=settings,
                use_native_fragment=use_native_fragment,
            )
            serialized = json.dumps(xray_doc, sort_keys=True, indent=2)
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        with self._lock:
            cfg_path = os.path.join(self.configs_dir, "active.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(serialized)

            bin_name = "xray.exe" if os.name == "nt" else "xray"
            xray_bin = os.path.join(self.core_dir, bin_name)
            if not os.path.exists(xray_bin):
                raise FileNotFoundError(f"Xray binary missing at {xray_bin}")

            self.proc = subprocess.Popen(
                [xray_bin, "-c", cfg_path],
                cwd=self.core_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._active_digest = digest
            threading.Thread(target=self._pipe_stdout, args=(self.proc,), daemon=True).start()

        time.sleep(0.32)
        if not self.is_running:
            self._active_digest = ""
            raise RuntimeError("Xray process terminated immediately on startup.")

        frag_state = f"{settings.fragment_packets}:{settings.fragment_length}" if use_native_fragment else "BridgeManaged"
        self._log(
            f"[Xray] Online ({meta['protocol']} | SNI={meta['sni']} | SOCKS={settings.socks_port} | HTTP={settings.http_port} | Frag={frag_state})"
        )
        return meta

    def _pipe_stdout(self, proc: subprocess.Popen):
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    clean = line.strip()
                    if clean:
                        self._log(f"[XrayCore] {clean}")
        except Exception:
            pass

    def stop(self):
        with self._lock:
            self._active_digest = ""
            proc_ref = self.proc
            self.proc = None

        if proc_ref:
            try:
                proc_ref.terminate()
                proc_ref.wait(timeout=0.8)
            except Exception:
                try:
                    proc_ref.kill()
                except Exception:
                    pass