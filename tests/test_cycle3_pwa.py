import pytest


class TestCycle3PWA:

    def test_pwa_home_page_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "InstaVerify" in response.text
        assert "Live Pending Watchlist" in response.text

    def test_pwa_manifest_served(self, client):
        response = client.get("/manifest.json")
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        data = response.json()
        assert any(b in data["name"] for b in ["Motaaked", "InstaTakeed", "InstaVerify"])
        assert data["display"] == "standalone"

    def test_pwa_service_worker_served(self, client):
        response = client.get("/sw.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "instapay-pwa" in response.text
