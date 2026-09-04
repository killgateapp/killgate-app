from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import web
from app.services import state_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    with TestClient(web.app) as test_client:
        yield test_client


def test_manifest_is_valid_and_all_declared_media_exists(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")

    manifest = response.json()
    assert manifest["id"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["launch_handler"]["client_mode"] == "navigate-existing"
    assert manifest["share_target"]["action"] == "/share"
    assert {item["protocol"] for item in manifest["protocol_handlers"]} == {"web+killgate"}
    assert len(manifest["shortcuts"]) >= 2
    assert len(manifest["screenshots"]) >= 2

    media_urls = [item["src"] for item in manifest["icons"]]
    media_urls += [item["src"] for item in manifest["screenshots"]]
    for media_url in media_urls:
        media_response = client.get(media_url)
        assert media_response.status_code == 200, media_url
        assert int(media_response.headers["content-length"]) > 0


def test_home_registers_pwa_and_sets_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<link rel="manifest" href="/manifest.webmanifest">' in response.text
    assert '<script src="/static/app.js" defer></script>' in response.text
    assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in response.text
    assert '<main id="main-content" tabindex="-1">' in response.text
    assert 'aria-label="Footer"' in response.text
    assert 'href="/privacy">Privacy</a>' in response.text
    assert 'href="/support">Support</a>' in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert worker.headers["cache-control"] == "no-cache"


def test_home_links_sample_report_previews(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "SAMPLE REPORT PREVIEW" in response.text
    assert "SAMPLE REACTIONS" in response.text

    for _, href, _ in web.SAMPLE_REPORTS[:4]:
        assert href in response.text
        report = client.get(href)
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("application/pdf")
        assert int(report.headers["content-length"]) > 0


def test_public_explainer_is_clear_without_exposing_internal_analysis(client):
    home = client.get("/")
    explainer = client.get("/how-it-works")

    assert home.status_code == 200
    assert explainer.status_code == 200
    for phrase in (
        "Describe the idea",
        "See the test plan",
        "Check public reality",
        "Prove it with buyers",
        "does not guarantee success",
    ):
        assert phrase in explainer.text
    assert "HOW KILLGATE WORKS" in home.text
    assert 'href="/how-it-works"' in home.text
    for internal_term in (
        "Query families",
        "hypothesis_fingerprint",
        "Mechanism scoreboard",
        "Evaluator:",
    ):
        assert internal_term not in explainer.text


def test_idea_intake_has_native_and_dynamic_readiness_feedback(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'minlength="10"' in response.text
    assert 'aria-describedby="idea-help idea-count idea-file-status idea-preflight-privacy"' in response.text
    assert 'data-idea-count' in response.text
    assert 'data-idea-submit' in response.text
    assert 'data-idea-preflight-trigger' in response.text
    assert 'data-idea-preflight' in response.text
    assert "This is a writing check, not a demand score." in response.text
    assert "no research is retrieved, nothing is saved" in response.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "updateIdeaInputState" in script.text
    assert "ideaSubmit.disabled" in script.text
    assert "IDEA_PREFLIGHT_CHECKS" in script.text
    assert "updateIdeaPreflight" in script.text
    assert "not an AI assessment or a" in script.text


def test_share_target_prefills_title_text_and_unique_url(client):
    response = client.post(
        "/share",
        data={
            "title": "Mobile groomer scheduling idea",
            "text": "Pet owners cannot find last-minute appointments.",
            "url": "https://example.com/research",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = unquote(response.headers["location"])
    assert location.endswith("#new-idea")

    page = client.get(response.headers["location"])
    assert "Shared idea loaded" in page.text
    assert "Mobile groomer scheduling idea" in page.text
    assert "Pet owners cannot find last-minute appointments." in page.text
    assert page.text.count("https://example.com/research") == 1


def test_custom_protocol_prefills_the_intake(client):
    response = client.get("/", params={"protocol": "web+killgate:Idea for dog walkers"})
    assert response.status_code == 200
    assert "Idea for dog walkers" in response.text
    assert "web+killgate:" not in response.text


def test_user_supplied_idea_is_escaped_everywhere(client):
    malicious = '<script>alert("owned")</script> A painful missed-call problem'
    create = client.post("/new", data={"idea": malicious}, follow_redirects=False)
    assert create.status_code == 303

    venture_page = client.get(create.headers["location"])
    assert venture_page.status_code == 200
    assert "<script>alert" not in venture_page.text
    assert "&lt;script&gt;alert" in venture_page.text

    home_page = client.get("/")
    assert "<script>alert" not in home_page.text
    assert "&lt;script&gt;alert" in home_page.text


def test_new_idea_fails_cleanly_when_distributed_limiter_is_unavailable(client, monkeypatch):
    from app.services.rate_limit import RateLimitUnavailable

    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: (_ for _ in ()).throw(RateLimitUnavailable()))
    response = client.post("/new", data={"idea": "A sufficiently detailed idea for validation"})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.text
    assert 'class="problem-page"' in response.text
    assert 'role="alert"' in response.text
    assert "Back to your workspace" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_recovery_page_escapes_error_text_and_safe_next_action():
    response = web._problem_response(
        status_code=400,
        message='<script>alert("not an error page")</script>',
        action_href="https://outside.example/",
        action_label="Return safely",
    )

    assert response.status_code == 400
    assert "<script>" not in response.body.decode()
    assert "&lt;script&gt;" in response.body.decode()
    assert 'href="/"' in response.body.decode()


def test_browser_navigation_errors_use_a_branded_recovery_page(client):
    response = client.get("/a-route-that-does-not-exist")

    assert response.status_code == 404
    assert 'class="problem-page"' in response.text
    assert "The page or idea you requested is no longer available." in response.text
    assert 'role="alert"' in response.text
    assert 'href="/"' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"

    api_response = client.get("/api/a-route-that-does-not-exist")
    assert api_response.status_code == 404
    assert api_response.json() == {"detail": "Not Found"}


def test_service_worker_cache_version_tracks_release(client):
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert 'killgate-v1.2.0-play-store-visuals-5' in response.text
    assert 'killgate-v1.2.0-polish-3' not in response.text
    assert 'killgate-v1.1.0' not in response.text
    assert 'const CACHE_PREFIX = "killgate-"' in response.text
    assert "key.startsWith(CACHE_PREFIX)" in response.text
    assert "event.waitUntil(" in response.text


def test_play_billing_price_is_loaded_from_store_not_hard_coded(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "app.killgate.mobile")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_pro")
    account = client.get("/account")
    assert account.status_code == 200
    assert 'data-billing-price' in account.text
    assert "14.99" not in account.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "service.getDetails([productId])" in script.text
    assert "Intl.NumberFormat" in script.text


def test_assetlinks_route_is_fail_closed_until_play_identity_is_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    monkeypatch.delenv("PLAY_APP_SIGNING_SHA256", raising=False)
    response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 503


def test_assetlinks_route_uses_play_installed_signing_identity(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "app.killgate.mobile")
    monkeypatch.setenv("PLAY_APP_SIGNING_SHA256", "ab" * 32)
    response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["target"]["package_name"] == "app.killgate.mobile"
    assert payload[0]["target"]["sha256_cert_fingerprints"] == [":".join(["AB"] * 32)]
    assert response.headers["cache-control"] == "public, max-age=300"


def test_oversized_mutation_request_is_rejected_before_form_processing(client):
    response = client.post(
        "/new",
        content=b"x" * (web.MAX_REQUEST_BODY_BYTES + 1),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    assert "too large" in response.text


def test_dynamic_html_and_json_are_not_browser_cacheable(client):
    home = client.get("/")
    assert home.headers["cache-control"] == "no-store"

    entitlement = client.get("/api/entitlement")
    assert entitlement.headers["cache-control"] == "no-store"

    static = client.get("/static/app.css")
    assert static.status_code == 200
    assert static.headers.get("cache-control") != "no-store"


def test_actual_mutation_body_size_is_checked_even_if_header_lies(client):
    response = client.post(
        "/share",
        content=b"x" * (web.MAX_REQUEST_BODY_BYTES + 1),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": "1",
        },
    )
    assert response.status_code == 413
