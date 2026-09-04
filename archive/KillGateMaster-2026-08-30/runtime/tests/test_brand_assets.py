from fastapi.testclient import TestClient

from app.web import STATIC_DIR, app


def test_brand_files_exist():
    required = [
        "icons/killgate-mark.svg",
        "icons/killgate-store-512.png",
        "icons/killgate-192.png",
        "icons/killgate-512.png",
        "icons/killgate-maskable-512.png",
        "icons/apple-touch-180.png",
        "icons/favicon-32.png",
        "brand/hero-atmosphere.jpg",
        "brand/killgate-play-store-feature.png",
        "brand/empty-arena.jpg",
        "brand/brief-document.jpg",
        "brand/og-gate.jpg",
        "brand/offline-room.jpg",
        "brand/gate-go.jpg",
        "brand/gate-kill.jpg",
        "brand/gate-pivot.jpg",
        "brand/pass-card.jpg",
    ]
    for rel in required:
        path = STATIC_DIR / rel
        assert path.is_file(), rel
        assert path.stat().st_size > 800, rel


def test_chrome_uses_supplied_play_store_mark():
    client = TestClient(app)
    page = client.get("/offline")
    assert page.status_code == 200
    assert "/static/icons/killgate-store-512.png" in page.text
    assert "/static/brand/offline-room.jpg" in page.text
    assert "otter" not in page.text.lower()
    assert (STATIC_DIR / "icons/killgate-store-512.png").stat().st_size > 800
