import json
from pathlib import Path

import pytest

from scripts.render_play_release import (
    normalize_fingerprint,
    normalize_origin,
    render,
    validate_package_id,
)


def test_release_renderer_uses_play_app_signing_fingerprint(tmp_path):
    fingerprint = "AA" * 32
    signing_key = tmp_path / "upload.jks"
    signing_key.write_bytes(b"test-keystore-placeholder")
    twa_path, assetlinks_path = render(
        "https://killgate.example",
        "app.killgate.mobile",
        fingerprint,
        tmp_path,
        signing_key_path=str(signing_key),
        signing_key_alias="killgate-upload",
        app_version="1.0.0",
        app_version_code=1,
    )
    twa = json.loads(twa_path.read_text())
    assetlinks = json.loads(assetlinks_path.read_text())
    assert twa["host"] == "killgate.example"
    assert twa["packageId"] == "app.killgate.mobile"
    assert twa["iconUrl"] == "https://killgate.example/static/icons/killgate-512.png"
    assert twa["maskableIconUrl"] == "https://killgate.example/static/icons/killgate-maskable-512.png"
    assert twa["signingKey"] == {"path": str(signing_key), "alias": "killgate-upload"}
    assert twa["appVersion"] == "1.0.0"
    assert twa["appVersionCode"] == 1
    assert twa["features"]["playBilling"]["enabled"] is True
    assert twa["alphaDependencies"]["enabled"] is True
    assert twa["fingerprints"][0]["value"] == normalize_fingerprint(fingerprint)
    assert assetlinks[0]["target"]["package_name"] == "app.killgate.mobile"
    assert assetlinks[0]["target"]["sha256_cert_fingerprints"][0] == normalize_fingerprint(fingerprint)
    assert "REPLACE_WITH" not in twa_path.read_text()
    assert "REPLACE_WITH" not in assetlinks_path.read_text()


def test_release_renderer_rejects_non_https_origin():
    with pytest.raises(ValueError):
        normalize_origin("http://killgate.example")


def test_release_renderer_rejects_invalid_package_and_fingerprint():
    with pytest.raises(ValueError):
        validate_package_id("killgate")
    with pytest.raises(ValueError):
        normalize_fingerprint("AA:BB")


def test_release_renderer_rejects_missing_signing_key(tmp_path):
    with pytest.raises(ValueError):
        render(
            "https://killgate.example",
            "app.killgate.mobile",
            "AA" * 32,
            tmp_path,
            signing_key_path="",
            signing_key_alias="killgate-upload",
        )


def test_release_renderer_rejects_userinfo_origin():
    with pytest.raises(ValueError):
        normalize_origin("https://user:pass@killgate.example")


def test_twa_template_contains_current_bubblewrap_required_release_fields():
    template = json.loads((Path(__file__).resolve().parents[1] / "twa-manifest.template.json").read_text())
    required = {
        "packageId", "host", "name", "themeColor", "navigationColor",
        "backgroundColor", "enableNotifications", "startUrl", "iconUrl",
        "splashScreenFadeOutDuration", "signingKey", "appVersion",
    }
    assert required <= set(template)
    assert template["features"]["playBilling"]["enabled"] is True
    assert template["alphaDependencies"]["enabled"] is True
    assert template["enableNotifications"] is True


def test_release_renderer_rejects_nonstandard_https_port():
    with pytest.raises(ValueError, match="port 443"):
        normalize_origin("https://killgate.example:8443")


def test_release_renderer_normalizes_explicit_443_port():
    assert normalize_origin("https://KILLGATE.EXAMPLE:443") == ("https://killgate.example", "killgate.example")


def test_release_renderer_rejects_fingerprint_with_nonseparator_characters():
    with pytest.raises(ValueError, match="only hexadecimal"):
        normalize_fingerprint(("AA" * 31) + "AA/")


def test_release_renderer_requires_existing_signing_key_file(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        render(
            "https://killgate.example",
            "app.killgate.mobile",
            "AA" * 32,
            tmp_path,
            signing_key_path=str(tmp_path / "missing-upload.jks"),
            signing_key_alias="killgate-upload",
        )


def test_production_container_is_non_root_and_serves_fastapi():
    from pathlib import Path
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "USER 10001:10001" in dockerfile
    assert "uvicorn app.web:app" in dockerfile
    assert "--host 0.0.0.0" in dockerfile
    assert "COPY .env " not in dockerfile and "COPY .env\n" not in dockerfile


def test_dockerignore_excludes_secrets_and_signing_material():
    from pathlib import Path
    content = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text()
    for required in (".env", "*.jks", "*.keystore", "*.pem", "*.key"):
        assert required in content


def test_android_smoke_script_has_no_shell_command_construction():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "scripts" / "android_internal_smoke.py").read_text()
    assert "shell=True" not in source
    assert 'PACKAGE_RE.fullmatch(package_id)' in source
    assert 'COMPONENT_RE.fullmatch(activity)' in source
    assert 'shutil.which("adb")' not in source
    assert '"--capture-private-ui"' in source
    assert '"--pid", pid' in source
    assert 'capture_output=True' in source


def test_release_ci_runs_dependency_and_source_security_gates():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-ci.yml").read_text()
    assert "pip-audit -r requirements.lock" in workflow
    assert "bandit -q -ll -r app scripts" in workflow
    assert "ruff check app scripts tests --select F,B" in workflow
    assert 'sdkmanager "platforms;android-36" "build-tools;36.0.0"' in workflow
    assert "pip install --require-hashes -r requirements-dev.lock" in workflow
    assert "pip install pip-audit bandit ruff" not in workflow


def test_production_container_installs_the_reviewed_dependency_lock():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    workflow = (root / ".github" / "workflows" / "release-ci.yml").read_text()
    assert "COPY requirements.txt requirements.lock ./" in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert (root / "requirements.lock").is_file()
    assert "python:3.12-slim@sha256:" in dockerfile
    assert "pytest -q" in workflow
    assert "docker build --pull" in workflow
