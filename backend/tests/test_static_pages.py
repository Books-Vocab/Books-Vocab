"""Tests for kg.routers.static_pages."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

from kg.routers.static_pages import get_guide, get_home, get_privacy_policy, get_support, get_terms


class TestStaticPages:
    def _patch_static_root(self, tmp_path: Path, monkeypatch):
        """Point _STATIC_ROOT at tmp_path so tests don't depend on repo root files."""
        import kg.routers.static_pages as mod
        monkeypatch.setattr(mod, "_STATIC_ROOT", tmp_path)
        return tmp_path

    def test_home_returns_file_response_when_index_exists(self, tmp_path, monkeypatch):
        root = self._patch_static_root(tmp_path, monkeypatch)
        (root / "index.html").write_text("<html>home</html>")
        resp = get_home()
        assert isinstance(resp, FileResponse)
        assert str(resp.path) == str(root / "index.html")

    def test_home_returns_404_when_index_missing(self, tmp_path, monkeypatch):
        self._patch_static_root(tmp_path, monkeypatch)
        resp = get_home()
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == 404
        assert "Home Not Found" in resp.body.decode()

    def test_privacy_returns_file_response_when_exists(self, tmp_path, monkeypatch):
        root = self._patch_static_root(tmp_path, monkeypatch)
        (root / "privacy.html").write_text("<html>privacy</html>")
        resp = get_privacy_policy()
        assert isinstance(resp, FileResponse)
        assert str(resp.path) == str(root / "privacy.html")

    def test_privacy_returns_404_when_missing(self, tmp_path, monkeypatch):
        self._patch_static_root(tmp_path, monkeypatch)
        resp = get_privacy_policy()
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == 404
        assert "Privacy Policy Not Found" in resp.body.decode()

    def test_support_returns_file_response_when_exists(self, tmp_path, monkeypatch):
        root = self._patch_static_root(tmp_path, monkeypatch)
        (root / "support.html").write_text("<html>support</html>")
        resp = get_support()
        assert isinstance(resp, FileResponse)
        assert str(resp.path) == str(root / "support.html")

    def test_support_returns_404_when_missing(self, tmp_path, monkeypatch):
        self._patch_static_root(tmp_path, monkeypatch)
        resp = get_support()
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == 404
        assert "Support Page Not Found" in resp.body.decode()

    def test_terms_returns_file_response_when_exists(self, tmp_path, monkeypatch):
        root = self._patch_static_root(tmp_path, monkeypatch)
        (root / "terms.html").write_text("<html>terms</html>")
        resp = get_terms()
        assert isinstance(resp, FileResponse)
        assert str(resp.path) == str(root / "terms.html")

    def test_terms_returns_404_when_missing(self, tmp_path, monkeypatch):
        self._patch_static_root(tmp_path, monkeypatch)
        resp = get_terms()
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == 404
        assert "Terms of Service Not Found" in resp.body.decode()

    def test_guide_returns_file_response_when_exists(self, tmp_path, monkeypatch):
        root = self._patch_static_root(tmp_path, monkeypatch)
        (root / "guide.html").write_text("<html>guide</html>")
        resp = get_guide()
        assert isinstance(resp, FileResponse)
        assert str(resp.path) == str(root / "guide.html")

    def test_guide_returns_404_when_missing(self, tmp_path, monkeypatch):
        self._patch_static_root(tmp_path, monkeypatch)
        resp = get_guide()
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == 404
        assert "Guide Not Found" in resp.body.decode()
