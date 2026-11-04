from __future__ import annotations

from dataclasses import dataclass, asdict
from ftplib import FTP, FTP_TLS
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET


@dataclass
class RemoteFile:
    provider: str
    remote_id: str
    name: str
    size: int
    url: str = ""
    removed: bool = False

    def json(self):
        return asdict(self)


class Provider:
    name = "provider"

    def list_files(self) -> list[RemoteFile]:
        raise NotImplementedError

    def upload(self, local_path: Path, remote_name: str) -> RemoteFile:
        raise NotImplementedError


class UnsupportedProvider(Provider):
    def __init__(self, name: str):
        self.name = name

    def list_files(self):
        raise RuntimeError(f"{self.name}: upload API zatím není ověřené; provider ponechte vypnutý.")

    def upload(self, local_path: Path, remote_name: str):
        return self.list_files()


class WebshareProvider(Provider):
    name = "webshare"
    base = "https://webshare.cz/api"

    def __init__(self, config: dict, env: dict | None = None, session=None):
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("Chybí requests. Spusťte: pip install -r requirements.txt") from exc
        self.requests = requests
        self.config = config
        self.env = env or os.environ
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "text/xml", "User-Agent": "X360Archive/0.1"})
        self._token = self.env.get("WEBSHARE_WST", "").strip()

    def _xml(self, endpoint: str, data: dict | None = None, url: str | None = None, files=None) -> ET.Element:
        payload = dict(data or {})
        if self.token:
            payload.setdefault("wst", self.token)
        response = self.session.post(url or f"{self.base}/{endpoint}/", data=payload, files=files, timeout=120)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        if root.findtext("status") != "OK":
            code = root.findtext("code", "UNKNOWN")
            message = root.findtext("message", "Neznámá chyba Webshare")
            raise RuntimeError(f"Webshare {endpoint}: {code}: {message}")
        return root

    def _xml_public(self, endpoint: str, data: dict | None = None) -> ET.Element:
        response = self.session.post(f"{self.base}/{endpoint}/", data=data or {}, timeout=120)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        if root.findtext("status") != "OK":
            code = root.findtext("code", "UNKNOWN")
            message = root.findtext("message", "Neznámá chyba Webshare")
            raise RuntimeError(f"Webshare {endpoint}: {code}: {message}")
        return root

    @property
    def token(self) -> str:
        if not self._token:
            self._token = self._login()
        return self._token

    def _login(self) -> str:
        username = self.env.get("WEBSHARE_USERNAME", "").strip()
        password = self.env.get("WEBSHARE_PASSWORD", "")
        if not username or not password:
            raise RuntimeError("Webshare: nastavte WEBSHARE_WST nebo WEBSHARE_USERNAME a WEBSHARE_PASSWORD.")
        salt_root = self._xml_unauthenticated("salt", {"username_or_email": username})
        salt = salt_root.findtext("salt")
        if not salt:
            raise RuntimeError("Webshare: server nevrátil salt pro přihlášení.")
        try:
            from passlib.hash import md5_crypt
        except ImportError as exc:
            raise RuntimeError("Pro login heslem chybí passlib. Spusťte: pip install -r requirements.txt") from exc
        password_digest = hashlib.sha1(md5_crypt.hash(password, salt=salt).encode()).hexdigest()
        root = self._xml_unauthenticated("login", {
            "username_or_email": username,
            "password": password_digest,
            "keep_logged_in": 1,
        })
        token = root.findtext("token", "")
        if not token:
            raise RuntimeError("Webshare: login nevrátil session token.")
        return token

    def _xml_unauthenticated(self, endpoint: str, data: dict) -> ET.Element:
        response = self.session.post(f"{self.base}/{endpoint}/", data=data, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        if root.findtext("status") != "OK":
            raise RuntimeError(f"Webshare {endpoint}: {root.findtext('code', 'UNKNOWN')}: {root.findtext('message', '')}")
        return root

    def list_files(self) -> list[RemoteFile]:
        folder_path = self.config.get("folder_path", "").strip()
        if folder_path:
            return self._list_account_files()
        public_folder_id = self.config.get("public_folder_id", "").strip()
        if not public_folder_id:
            raise RuntimeError("Webshare: chybí folder_path nebo public_folder_id.")
        return self._list_public_folder(public_folder_id)

    def _list_public_folder(self, folder_id: str) -> list[RemoteFile]:
        result = {}
        pending = [folder_id]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            offset = 0
            while True:
                root = self._xml_public("folder", {"ident": current, "offset": offset,
                                                    "limit": 100, "subfolders": 1})
                entries = [entry for entry in root if entry.tag in {"file", "folder"}]
                for entry in entries:
                    ident = entry.findtext("ident", "")
                    if entry.tag == "folder":
                        if ident:
                            pending.append(ident)
                        continue
                    result[ident] = RemoteFile(
                        provider=self.name,
                        remote_id=ident,
                        name=entry.findtext("name", ident),
                        size=int(entry.findtext("size", "0")),
                        url=f"https://webshare.cz/#/file/{ident}" if ident else "",
                    )
                offset += len(entries)
                total = int(root.findtext("total", str(offset)))
                if not entries or offset >= total:
                    break
        return list(result.values())

    def _list_account_files(self) -> list[RemoteFile]:
        path = self.config.get("folder_path", "/XBOX360CZ")
        private = int(self.config.get("private", 0))
        result = []
        offset = 0
        while True:
            root = self._xml("files", {
                "path": path,
                "private": private,
                "include_removed": 1,
                "sort_by": "name",
                "sort_order": "asc",
                "limit": 100,
                "offset": offset,
            })
            entries = root.findall("file")
            for entry in entries:
                ident = entry.findtext("ident", "")
                result.append(RemoteFile(
                    provider=self.name,
                    remote_id=ident,
                    name=entry.findtext("name", ident),
                    size=int(entry.findtext("size", "0")),
                    url=f"https://webshare.cz/#/file/{ident}" if ident else "",
                    removed=entry.findtext("removed", "0") == "1",
                ))
            offset += len(entries)
            total_text = root.findtext("total")
            if not entries or len(entries) < 100 or (total_text and offset >= int(total_text)):
                break
        return result

    def upload(self, local_path: Path, remote_name: str) -> RemoteFile:
        if not self.config.get("upload_enabled", False):
            raise RuntimeError("Webshare upload je bezpečnostně vypnutý. Nejdřív ověřte cílový účet a nastavte upload_enabled na true.")
        upload_root = self._xml("upload_url")
        upload_url = upload_root.findtext("url")
        if not upload_url:
            raise RuntimeError("Webshare: upload_url nevrátil URL.")
        total = local_path.stat().st_size
        chunk_size = int(self.config.get("chunk_size_mb", 16)) * 1024 * 1024
        ident = ""
        offset = 0
        with local_path.open("rb") as stream:
            while offset < total:
                chunk = stream.read(chunk_size)
                data = {"total": str(total), "offset": str(offset)}
                if ident:
                    data["ident"] = ident
                root = self._xml("upload", data=data, url=upload_url,
                                 files={"file": (remote_name, chunk, "application/x-7z-compressed")})
                ident = root.findtext("ident", ident)
                if not ident:
                    raise RuntimeError("Webshare: upload nevrátil ID souboru.")
                offset += len(chunk)
                progress = self.config.get("progress_callback")
                if progress:
                    progress(local_path, offset, total)
        folder_path = self.config.get("folder_path", "").strip()
        if folder_path and folder_path != "/":
            self._xml("move_file", {"src": "/" + remote_name, "dest": folder_path,
                                     "src_private": 0, "dest_private": int(self.config.get("private", 0))})
        return RemoteFile(self.name, ident, remote_name, total, f"https://webshare.cz/#/file/{ident}")


class EdiskFtpProvider(Provider):
    name = "edisk"

    def __init__(self, config: dict, env: dict | None = None):
        self.config = config
        self.env = env or os.environ

    def _connect(self):
        username = self.env.get("EDISK_USERNAME", "").strip()
        password = self.env.get("EDISK_PASSWORD", "")
        if not username or not password:
            raise RuntimeError("eDisk: nastavte EDISK_USERNAME a EDISK_PASSWORD.")
        cls = FTP_TLS if self.config.get("tls") else FTP
        ftp = cls()
        ftp.connect(self.config.get("host", "ftp.edisk.cz"), int(self.config.get("port", 21)), timeout=60)
        ftp.login(username, password)
        if isinstance(ftp, FTP_TLS):
            ftp.prot_p()
        remote_dir = self.config.get("remote_dir", "/XBOX360CZ")
        self._ensure_dir(ftp, remote_dir)
        ftp.cwd(remote_dir)
        return ftp

    @staticmethod
    def _ensure_dir(ftp, remote_dir: str):
        ftp.cwd("/")
        for part in PurePosixPath(remote_dir).parts:
            if part in {"/", ""}:
                continue
            try:
                ftp.cwd(part)
            except Exception:
                ftp.mkd(part)
                ftp.cwd(part)

    def list_files(self) -> list[RemoteFile]:
        ftp = self._connect()
        result = []
        try:
            for name, facts in ftp.mlsd():
                if facts.get("type") != "file":
                    continue
                result.append(RemoteFile(self.name, name, name, int(facts.get("size", 0))))
        finally:
            ftp.quit()
        return result

    def upload(self, local_path: Path, remote_name: str) -> RemoteFile:
        ftp = self._connect()
        try:
            with local_path.open("rb") as stream:
                ftp.storbinary(f"STOR {remote_name}", stream, blocksize=1024 * 1024)
        finally:
            ftp.quit()
        return RemoteFile(self.name, remote_name, remote_name, local_path.stat().st_size)


def build_providers(config: dict, env: dict | None = None) -> dict[str, Provider]:
    providers = {}
    for name, item in config.get("providers", {}).items():
        if not item.get("enabled", False):
            continue
        if name == "webshare":
            providers[name] = WebshareProvider(item, env=env)
        elif name == "edisk":
            providers[name] = EdiskFtpProvider(item, env=env)
        else:
            providers[name] = UnsupportedProvider(name)
    return providers
