from __future__ import annotations

import hashlib
import struct
import subprocess
import zlib
from pathlib import Path

from scripts.build_preview_apk import (
    android_build_tool,
    build_apk,
    build_dex,
    build_manifest,
    make_preview_html,
)


def _read_u8_len(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos]
    pos += 1
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[pos], pos + 1
    return first, pos


def _manifest_strings(axml: bytes) -> list[str]:
    top_type, top_hsize, top_size = struct.unpack_from("<HHI", axml, 0)
    assert (top_type, top_hsize, top_size) == (0x0003, 8, len(axml))
    pos = 8
    chunks: list[tuple[int, int, int, int]] = []
    while pos < len(axml):
        chunk_type, hsize, size = struct.unpack_from("<HHI", axml, pos)
        assert hsize >= 8
        assert size >= hsize
        assert pos + size <= len(axml)
        chunks.append((pos, chunk_type, hsize, size))
        pos += size
    assert pos == len(axml)

    pool_pos, pool_type, pool_hsize, _ = chunks[0]
    assert pool_type == 0x0001
    assert pool_hsize == 28
    string_count, _, flags, strings_start, _ = struct.unpack_from("<IIIII", axml, pool_pos + 8)
    assert flags & 0x100  # UTF-8 pool
    offsets = [struct.unpack_from("<I", axml, pool_pos + 28 + i * 4)[0] for i in range(string_count)]
    base = pool_pos + strings_start
    strings: list[str] = []
    for offset in offsets:
        cursor = base + offset
        _, cursor = _read_u8_len(axml, cursor)  # UTF-16 code unit count
        utf8_len, cursor = _read_u8_len(axml, cursor)
        strings.append(axml[cursor : cursor + utf8_len].decode("utf-8"))

    stack: list[str] = []
    for chunk_pos, chunk_type, _, _ in chunks:
        if chunk_type == 0x0102:  # RES_XML_START_ELEMENT_TYPE
            _, name_idx = struct.unpack_from("<II", axml, chunk_pos + 16)
            stack.append(strings[name_idx])
        elif chunk_type == 0x0103:  # RES_XML_END_ELEMENT_TYPE
            _, name_idx = struct.unpack_from("<II", axml, chunk_pos + 16)
            assert stack.pop() == strings[name_idx]
    assert not stack
    return strings


def test_preview_dex_header_signature_checksum_and_map_are_valid():
    dex = build_dex()
    assert dex[:8] == b"dex\n035\0"
    assert struct.unpack_from("<I", dex, 32)[0] == len(dex)
    assert struct.unpack_from("<I", dex, 36)[0] == 0x70
    assert struct.unpack_from("<I", dex, 40)[0] == 0x12345678
    assert dex[12:32] == hashlib.sha1(dex[32:]).digest()
    assert struct.unpack_from("<I", dex, 8)[0] == (zlib.adler32(dex[12:]) & 0xFFFFFFFF)

    map_off = struct.unpack_from("<I", dex, 52)[0]
    assert 0 < map_off < len(dex) - 4
    map_size = struct.unpack_from("<I", dex, map_off)[0]
    assert map_size >= 1
    for index in range(map_size):
        _, _, item_count, item_off = struct.unpack_from("<HHII", dex, map_off + 4 + index * 12)
        assert item_count >= 1
        assert 0 <= item_off < len(dex)


def test_preview_manifest_has_current_identity_sdk_and_launcher_activity():
    strings = _manifest_strings(build_manifest())
    required = {
        "manifest",
        "uses-sdk",
        "application",
        "activity",
        "intent-filter",
        "action",
        "category",
        "com.killgate.preview",
        "com.killgate.preview.MainActivity",
        "1.2.0-v1.5-engine-preview",
        "Killgate Preview",
        "android.intent.action.MAIN",
        "android.intent.category.LAUNCHER",
    }
    assert required <= set(strings)


def test_preview_html_is_explicitly_offline_and_exercises_core_states():
    css = Path(__file__).resolve().parents[1] / "app/static/app.css"
    html = make_preview_html(css)
    assert "LOCAL UI PREVIEW" in html
    assert "backend/AI/billing are not connected" in html
    assert "VALIDATION CONTRACT" in html
    assert "Test a critical capability first" in html
    assert "CRITICAL CAPABILITY TEST" in html
    assert "Mechanism scoreboard" not in html
    assert "Preview capability test passed" in html
    assert "CONTINUE TESTING" in html
    assert ">GO BUILD<" in html
    assert ">STOP<" in html


def test_preview_apk_uses_modern_android_signature_scheme(tmp_path):
    root = Path(__file__).resolve().parents[1]
    apk = build_apk(root, tmp_path / "killgate-preview.apk")
    verified = subprocess.run(
        [str(android_build_tool("apksigner")), "verify", "--verbose", str(apk)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Verified using v2 scheme (APK Signature Scheme v2): true" in verified.stdout
