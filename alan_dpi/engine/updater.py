import re
from typing import Tuple
import requests


class GithubUpdateChecker:
    REPO_SLUG = "DrAlanK/Alan-RIP-Dpi-Windows"

    @staticmethod
    def _parse_semver(tag: str) -> Tuple[int, ...]:
        nums = re.findall(r"\d+", str(tag or "0"))
        return tuple(int(x) for x in nums[:4]) if nums else (0,)

    @classmethod
    def check_latest_release(cls, current_version: str, proxy_http_port: int = 0) -> dict:
        api_url = f"https://api.github.com/repos/{cls.REPO_SLUG}/releases/latest"
        sess = requests.Session()
        sess.trust_env = False
        sess.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "Alan-RIP-Dpi-Updater"})
        if proxy_http_port and proxy_http_port > 0:
            px = f"http://127.0.0.1:{int(proxy_http_port)}"
            sess.proxies = {"http": px, "https": px}

        try:
            try:
                resp = sess.get(api_url, timeout=9.0)
            except Exception:
                sess.proxies = {}
                resp = sess.get(api_url, timeout=9.0)

            if resp.status_code != 200:
                return {
                    "ok": False,
                    "has_update": False,
                    "current_version": current_version,
                    "latest_version": current_version,
                    "release_url": f"https://github.com/{cls.REPO_SLUG}/releases",
                    "download_url": "",
                    "notes": "",
                    "error": f"GitHub HTTP {resp.status_code}",
                }

            data = resp.json()
            tag = str(data.get("tag_name") or "").strip()
            latest_clean = tag.lstrip("vV") or current_version
            rel_url = str(data.get("html_url") or f"https://github.com/{cls.REPO_SLUG}/releases")
            notes = str(data.get("body") or "").strip()
            dl_url = rel_url
            for asset in data.get("assets") or []:
                aname = str(asset.get("name") or "").lower()
                if aname.endswith(".zip") or aname.endswith(".exe"):
                    dl_url = str(asset.get("browser_download_url") or rel_url)
                    break

            has_upd = cls._parse_semver(latest_clean) > cls._parse_semver(current_version)
            return {
                "ok": True,
                "has_update": has_upd,
                "current_version": current_version,
                "latest_version": latest_clean,
                "release_url": rel_url,
                "download_url": dl_url,
                "notes": notes[:900],
                "error": "",
            }
        except Exception as exc:
            return {
                "ok": False,
                "has_update": False,
                "current_version": current_version,
                "latest_version": current_version,
                "release_url": f"https://github.com/{cls.REPO_SLUG}/releases",
                "download_url": "",
                "notes": "",
                "error": str(exc)[:100],
            }
        finally:
            sess.close()
