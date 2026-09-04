#!/usr/bin/env python3
"""Render Killgate's Bubblewrap and Digital Asset Links files from final owner values."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
HEX64_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,79}$")


def normalize_origin(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Origin must be an HTTPS origin only, for example https://killgate.example.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin contains an invalid port.") from exc
    if port not in (None, 443):
        raise ValueError("Production TWA origin must use standard HTTPS port 443.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Origin must contain a valid hostname.")
    return f"https://{host}", host


def normalize_fingerprint(value: str) -> str:
    value = value.strip()
    if re.search(r"[^0-9A-Fa-f:\s-]", value):
        raise ValueError("Play App Signing SHA-256 may contain only hexadecimal characters and separators.")
    compact = re.sub(r"[:\s-]", "", value)
    if not HEX64_RE.fullmatch(compact):
        raise ValueError("Play App Signing SHA-256 must contain exactly 64 hexadecimal characters.")
    compact = compact.upper()
    return ":".join(compact[i : i + 2] for i in range(0, 64, 2))


def validate_package_id(value: str) -> str:
    value = value.strip()
    if not PACKAGE_RE.fullmatch(value):
        raise ValueError("Android package ID must look like com.company.killgate.")
    return value


def validate_signing_key(path: str, alias: str) -> tuple[str, str]:
    path = path.strip()
    alias = alias.strip()
    if not path or "\x00" in path:
        raise ValueError("Upload signing-key path is required.")
    key_path = Path(path).expanduser()
    if not key_path.is_file():
        raise ValueError("Upload signing-key file does not exist at the supplied path.")
    if not ALIAS_RE.fullmatch(alias):
        raise ValueError("Upload signing-key alias must use letters, digits, dot, underscore, or hyphen.")
    return str(key_path), alias


def validate_version(version: str, version_code: int) -> tuple[str, int]:
    version = version.strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Android app version must be a short release version such as 1.0.0.")
    if version_code < 1 or version_code > 2_100_000_000:
        raise ValueError("Android app version code must be between 1 and 2100000000.")
    return version, version_code


def render(
    origin: str,
    package_id: str,
    play_app_signing_sha256: str,
    out_dir: Path,
    *,
    signing_key_path: str,
    signing_key_alias: str,
    app_version: str = "1.2.0",
    app_version_code: int = 1,
) -> tuple[Path, Path]:
    origin, host = normalize_origin(origin)
    package_id = validate_package_id(package_id)
    fingerprint = normalize_fingerprint(play_app_signing_sha256)
    signing_key_path, signing_key_alias = validate_signing_key(signing_key_path, signing_key_alias)
    app_version, app_version_code = validate_version(app_version, app_version_code)
    out_dir.mkdir(parents=True, exist_ok=True)

    twa = json.loads((ROOT / "twa-manifest.template.json").read_text(encoding="utf-8"))
    twa.update(
        {
            "packageId": package_id,
            "host": host,
            "webManifestUrl": f"{origin}/manifest.webmanifest",
            "iconUrl": f"{origin}/static/icons/killgate-512.png",
            "maskableIconUrl": f"{origin}/static/icons/killgate-maskable-512.png",
            "signingKey": {"path": signing_key_path, "alias": signing_key_alias},
            "appVersion": app_version,
            "appVersionCode": app_version_code,
            "fingerprints": [{"name": "Play App Signing", "value": fingerprint}],
        }
    )

    assetlinks = json.loads((ROOT / "assetlinks.template.json").read_text(encoding="utf-8"))
    target = assetlinks[0]["target"]
    target["package_name"] = package_id
    target["sha256_cert_fingerprints"] = [fingerprint]

    twa_path = out_dir / "twa-manifest.json"
    assetlinks_path = out_dir / "assetlinks.json"
    twa_path.write_text(json.dumps(twa, indent=2) + "\n", encoding="utf-8")
    assetlinks_path.write_text(json.dumps(assetlinks, indent=2) + "\n", encoding="utf-8")
    return twa_path, assetlinks_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Final HTTPS origin, e.g. https://killgate.example")
    parser.add_argument("--package-id", required=True, help="Final Android application ID")
    parser.add_argument(
        "--play-app-signing-sha256",
        required=True,
        help="SHA-256 from Play Console > App integrity > App signing key certificate",
    )
    parser.add_argument("--signing-key-path", required=True, help="Bubblewrap/upload keystore path (never a password)")
    parser.add_argument("--signing-key-alias", required=True, help="Alias inside the Bubblewrap/upload keystore")
    parser.add_argument("--app-version", default="1.2.0", help="Android versionName")
    parser.add_argument("--app-version-code", type=int, default=1, help="Android monotonically increasing versionCode")
    parser.add_argument("--out-dir", default="release-generated", help="Output directory")
    args = parser.parse_args()
    try:
        twa, assetlinks = render(
            args.origin,
            args.package_id,
            args.play_app_signing_sha256,
            Path(args.out_dir),
            signing_key_path=args.signing_key_path,
            signing_key_alias=args.signing_key_alias,
            app_version=args.app_version,
            app_version_code=args.app_version_code,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Rendered {twa}")
    print(f"Rendered {assetlinks}")
    print("Publish assetlinks.json at https://<host>/.well-known/assetlinks.json before TWA verification testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
