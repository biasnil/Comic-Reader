"""Installing / updating / removing plugins from this repo's GitHub Releases.

A release carries each plugin as two assets: <spec.asset> (the built worker folder, zipped) and
the same name + ".sha256". The zip is checked against it and unpacked into DATA_DIR/plugins/<id>/.
Nothing here touches tkinter; the dialog runs these functions in a worker thread.
"""
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from ..core.plugins import GITHUB_REPO, PluginSpec

API = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
HEADERS = {"User-Agent": "ComicReader", "Accept": "application/vnd.github+json"}


class InstallError(Exception):
    pass


def supported() -> bool:
    """Released plugin builds are Windows x64 only (from source, use the repo's plugin folder)."""
    return sys.platform == "win32"


def installed_version(spec: PluginSpec) -> str | None:
    try:
        return json.loads((spec.dir / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None if not (spec.dir / spec.exe).exists() else "unknown"


def latest_release(spec: PluginSpec) -> dict:
    """{'tag', 'version', 'url', 'sha_url', 'size'} of the newest release with the plugin zip."""
    req = urllib.request.Request(API, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise InstallError(f"Can't reach GitHub: {exc}") from exc
    for rel in releases:
        if rel.get("draft"):
            continue
        assets = {a["name"]: a for a in rel.get("assets", [])}
        if spec.asset in assets and spec.asset + ".sha256" in assets:
            tag = rel["tag_name"]
            return {"tag": tag, "version": tag.rsplit("v", 1)[-1],
                    "url": assets[spec.asset]["browser_download_url"],
                    "sha_url": assets[spec.asset + ".sha256"]["browser_download_url"],
                    "size": assets[spec.asset]["size"]}
    raise InstallError(f"No release of {GITHUB_REPO} contains {spec.asset} yet")


def _fetch(url: str, dest: Path, progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": "ComicReader"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def install(spec: PluginSpec, release: dict, progress=None):
    """Download, verify and unpack the plugin. progress(done_bytes, total_bytes) is optional."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath, spath = tmp / spec.asset, tmp / (spec.asset + ".sha256")
        try:
            _fetch(release["sha_url"], spath)
            _fetch(release["url"], zpath, progress)
        except OSError as exc:
            raise InstallError(f"Download failed: {exc}") from exc
        expected = spath.read_text(encoding="utf-8", errors="replace").split()[0].lower()
        digest = hashlib.sha256()
        with open(zpath, "rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise InstallError("The download is corrupt (checksum mismatch); nothing was changed")

        staging = tmp / "unpacked"
        with zipfile.ZipFile(zpath) as zf:
            for name in zf.namelist():  # refuse paths that would escape the folder
                target = (staging / name).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise InstallError(f"Unsafe path in the plugin zip: {name}")
            zf.extractall(staging)
        if not (staging / spec.exe).exists():
            raise InstallError(f"The plugin zip has no {spec.exe}")
        (staging / "plugin.json").write_text(
            json.dumps({"version": release["version"], "tag": release["tag"]}), encoding="utf-8")

        target = spec.dir
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.with_name(target.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        shutil.move(str(staging), str(target))
        shutil.rmtree(old, ignore_errors=True)


def remove(spec: PluginSpec):
    shutil.rmtree(spec.dir, ignore_errors=True)
