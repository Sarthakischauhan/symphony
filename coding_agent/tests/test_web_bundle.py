"""Symphony Web bundle install: checksum, atomic switch, prune, rollback, and
where the server reads its assets from."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path

import pytest

from coding_agent.web import server
from coding_agent.web.bundle import (
    INSTALL_HINT,
    PINNED,
    BundleError,
    asset_url,
    install,
    resolve_static,
    rollback,
)


def bundle(text: str) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for name, body in {"index.html": text, "assets/app.js": f"// {text}"}.items():
            encoded = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(encoded)
            tar.addfile(info, io.BytesIO(encoded))
    return data.getvalue()


class Releases:
    """Serves web-<version>.tar.gz and its .sha256 from memory."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fetched: list[str] = []

    def publish(self, version: str, archive: bytes, digest: str | None = None) -> None:
        url = asset_url(version)
        self.files[url] = archive
        checksum = digest or hashlib.sha256(archive).hexdigest()
        self.files[url + ".sha256"] = f"{checksum}  web-{version}.tar.gz\n".encode()

    def fetch(self, url: str, dest: Path) -> None:
        self.fetched.append(url)
        if url not in self.files:
            raise BundleError(f"download failed: {url}")
        dest.write_bytes(self.files[url])


def entries(root: Path) -> set[str]:
    return {entry.name for entry in root.iterdir()}


def test_install_extracts_switches_and_records_the_digest(tmp_path: Path) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    target = install("0.0.1", tmp_path, fetch=releases.fetch)
    assert target == tmp_path / "0.0.1"
    assert os.readlink(tmp_path / "current") == "0.0.1"
    assert (tmp_path / "current" / "index.html").read_text() == "one"
    assert (tmp_path / "current" / "assets" / "app.js").is_file()
    assert entries(tmp_path) == {"0.0.1", "current"}
    # Same version again: the checksum matches the recorded one, so no re-download.
    releases.fetched.clear()
    install("0.0.1", tmp_path, fetch=releases.fetch)
    assert releases.fetched == [asset_url("0.0.1") + ".sha256"]


def test_checksum_mismatch_keeps_the_current_bundle(tmp_path: Path) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    releases.publish("0.0.2", bundle("two"), digest="0" * 64)
    with pytest.raises(BundleError, match="checksum mismatch"):
        install("0.0.2", tmp_path, fetch=releases.fetch)
    assert os.readlink(tmp_path / "current") == "0.0.1"
    assert entries(tmp_path) == {"0.0.1", "current"}


def test_failed_download_leaves_no_partial_state(tmp_path: Path) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    releases.publish("0.0.2", bundle("two"))
    del releases.files[asset_url("0.0.2")]
    with pytest.raises(BundleError, match="download failed"):
        install("0.0.2", tmp_path, fetch=releases.fetch)
    assert entries(tmp_path) == {"0.0.1", "current"}
    # A killed install's leftovers are swept on the next run.
    (tmp_path / ".tmp-dead").mkdir()
    (tmp_path / ".tmp-dead" / "web.tar.gz").write_bytes(b"partial")
    releases.publish("0.0.2", bundle("two"))
    install("0.0.2", tmp_path, fetch=releases.fetch)
    assert ".tmp-dead" not in entries(tmp_path)


def test_unsafe_archive_is_rejected(tmp_path: Path) -> None:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escape.html")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    releases = Releases()
    releases.publish("0.0.1", data.getvalue())
    with pytest.raises(BundleError, match="unsafe path"):
        install("0.0.1", tmp_path / "web", fetch=releases.fetch)
    assert not (tmp_path / "escape.html").exists()
    assert entries(tmp_path / "web") == set()


def test_switch_is_a_symlink_rename_and_prunes_to_current_and_previous(tmp_path: Path) -> None:
    releases = Releases()
    for version in ("0.0.1", "0.0.2", "0.0.3"):
        releases.publish(version, bundle(version))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    install("0.0.2", tmp_path, fetch=releases.fetch)
    current_inode = (tmp_path / "current").lstat().st_ino
    install("0.0.3", tmp_path, fetch=releases.fetch)
    # current was replaced (a new link renamed over it), not edited in place.
    assert (tmp_path / "current").is_symlink()
    assert (tmp_path / "current").lstat().st_ino != current_inode
    assert os.readlink(tmp_path / "current") == "0.0.3"
    assert os.readlink(tmp_path / "previous") == "0.0.2"
    assert entries(tmp_path) == {"0.0.2", "0.0.3", "current", "previous"}


def test_rollback_swaps_current_and_previous(tmp_path: Path) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    releases.publish("0.0.2", bundle("two"))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    with pytest.raises(BundleError, match="no previous"):
        rollback(tmp_path)
    install("0.0.2", tmp_path, fetch=releases.fetch)
    assert rollback(tmp_path) == "0.0.1"
    assert (tmp_path / "current" / "index.html").read_text() == "one"
    assert os.readlink(tmp_path / "previous") == "0.0.2"
    # Rolling back again returns to the newer bundle; nothing was pruned and
    # the choice stays pinned.
    assert rollback(tmp_path) == "0.0.2"
    assert entries(tmp_path) == {"0.0.1", "0.0.2", "current", "previous", PINNED}


# server path resolution


def site(path: Path, text: str) -> Path:
    path.mkdir(parents=True)
    (path / "index.html").write_text(text)
    return path


def test_server_prefers_the_installed_bundle(tmp_path: Path) -> None:
    root = tmp_path / "web"
    site(root / "0.0.1", "installed")
    (root / "current").symlink_to("0.0.1")
    source = tmp_path / "web-ui"
    site(source / "dist", "dev")
    (source / "package.json").write_text("{}")
    assert resolve_static(root, source) == (root / "0.0.1").resolve()


def test_server_falls_back_to_a_source_build(tmp_path: Path) -> None:
    source = tmp_path / "web-ui"
    site(source / "dist", "dev")
    (source / "package.json").write_text("{}")
    assert resolve_static(tmp_path / "web", source) == source / "dist"


def test_server_without_bundle_or_source_names_the_update_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(BundleError, match="symphony web --update"):
        resolve_static(tmp_path / "web", tmp_path / "missing")
    # An unbuilt checkout without permission to build is the same error.
    (tmp_path / "web-ui").mkdir()
    (tmp_path / "web-ui" / "package.json").write_text("{}")
    with pytest.raises(BundleError, match="symphony web --update"):
        resolve_static(tmp_path / "web", tmp_path / "web-ui", build=False)
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(server, "resolve_static", lambda root, **_: resolve_static(root, tmp_path / "missing"))
    assert server.main(["--no-browser"]) == 1
    assert INSTALL_HINT in capsys.readouterr().err


def test_cli_update_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    releases.publish("0.0.2", bundle("two"))
    monkeypatch.setenv("SYMPHONY_HOME", str(tmp_path))

    def fetching(version: str, root: Path, *, pin: bool = False) -> Path:
        return install(version, root, fetch=releases.fetch, pin=pin)

    monkeypatch.setattr(server, "install", fetching)
    monkeypatch.setattr(server, "installed_version", lambda: "0.0.2")
    web = tmp_path / "web"
    # A release other than the installed one is pinned; the installed one is not.
    assert server.main(["--update", "--bundle-version", "0.0.1"]) == 0
    assert (web / PINNED).read_text().strip() == "0.0.1"
    assert server.main(["--update"]) == 0
    assert os.readlink(web / "current") == "0.0.2" and not (web / PINNED).exists()
    assert server.main(["--rollback"]) == 0
    assert "rolled back to 0.0.1" in capsys.readouterr().out
    assert os.readlink(web / "current") == "0.0.1" and (web / PINNED).is_file()
    # Without an installed release (source checkout, local wheel) nothing syncs, so nothing pins.
    monkeypatch.setattr(server, "installed_version", lambda: None)
    assert server.main(["--update", "--bundle-version", "0.0.1"]) == 0
    assert not (web / PINNED).exists()


# serving the installed release's bundle


def test_clean_start_installs_the_installed_release(tmp_path: Path) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    root = tmp_path / "web"
    served = resolve_static(root, tmp_path / "missing", version="0.0.1", fetch=releases.fetch)
    assert served == (root / "0.0.1").resolve()
    assert (served / "index.html").read_text() == "one"
    # Already on the installed release: nothing is fetched.
    releases.fetched.clear()
    assert resolve_static(root, tmp_path / "missing", version="0.0.1", fetch=releases.fetch) == served
    assert releases.fetched == []


def test_start_after_a_package_upgrade_switches_and_keeps_the_previous(tmp_path: Path) -> None:
    releases = Releases()
    for version in ("0.0.1", "0.0.2"):
        releases.publish(version, bundle(version))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    served = resolve_static(tmp_path, tmp_path / "missing", version="0.0.2", fetch=releases.fetch)
    assert served == (tmp_path / "0.0.2").resolve()
    assert os.readlink(tmp_path / "previous") == "0.0.1"
    assert entries(tmp_path) == {"0.0.1", "0.0.2", "current", "previous"}


def test_rollback_is_pinned_until_the_next_install(tmp_path: Path) -> None:
    releases = Releases()
    for version in ("0.0.1", "0.0.2"):
        releases.publish(version, bundle(version))
    install("0.0.1", tmp_path, fetch=releases.fetch)
    install("0.0.2", tmp_path, fetch=releases.fetch)
    assert not (tmp_path / PINNED).exists()
    rollback(tmp_path)
    releases.fetched.clear()
    served = resolve_static(tmp_path, tmp_path / "missing", version="0.0.2", fetch=releases.fetch)
    assert served == (tmp_path / "0.0.1").resolve() and releases.fetched == []
    install("0.0.2", tmp_path, fetch=releases.fetch)
    assert not (tmp_path / PINNED).exists()
    assert os.readlink(tmp_path / "current") == "0.0.2"


def test_failed_sync_serves_the_installed_bundle_but_a_clean_start_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    releases = Releases()
    releases.publish("0.0.1", bundle("one"))
    root = tmp_path / "web"
    install("0.0.1", root, fetch=releases.fetch)
    served = resolve_static(root, tmp_path / "missing", version="0.0.2", fetch=releases.fetch)
    assert served == (root / "0.0.1").resolve()
    assert "serving 0.0.1 instead" in capsys.readouterr().err
    assert entries(root) == {"0.0.1", "current"}
    with pytest.raises(BundleError, match="download failed") as failure:
        resolve_static(tmp_path / "clean", tmp_path / "missing", version="0.0.2", fetch=releases.fetch)
    assert INSTALL_HINT in str(failure.value)
