#!/usr/bin/env python3
"""Build a self-contained Killgate UI preview APK without Gradle.

This is intentionally NOT the Play release wrapper. It creates a tiny Android
WebView shell around bundled preview HTML so the owner can inspect the current
mobile UI before the production HTTPS/TWA identity exists.

The production app remains Bubblewrap/TWA + Google Play Billing.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

NO_INDEX = 0xFFFFFFFF


def uleb128(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def align(data: bytearray, alignment: int = 4) -> None:
    while len(data) % alignment:
        data.append(0)


def _ins_10x(op: int) -> list[int]:
    return [op]


def _ins_11x(op: int, a: int) -> list[int]:
    return [op | (a << 8)]


def _ins_11n(op: int, a: int, literal4: int) -> list[int]:
    return [op | ((a & 0xF) << 8) | ((literal4 & 0xF) << 12)]


def _ins_21c(op: int, a: int, index: int) -> list[int]:
    return [op | (a << 8), index]


def _ins_invoke(op: int, method_idx: int, regs: list[int]) -> list[int]:
    count = len(regs)
    if count > 5 or any(r < 0 or r > 15 for r in regs):
        raise ValueError("35c register constraint violated")
    padded = regs + [0] * (5 - count)
    c, d, e, f, g = padded
    first = op | (g << 8) | (count << 12)
    third = c | (d << 4) | (e << 8) | (f << 12)
    return [first, method_idx, third]


def build_dex(package: str = "com.killgate.preview") -> bytes:
    main_desc = "L" + package.replace(".", "/") + "/MainActivity;"

    # Descriptors and strings referenced by the class/method/proto tables and code.
    string_values = {
        "<init>",
        "onCreate",
        "requestWindowFeature",
        "setContentView",
        "getSettings",
        "setJavaScriptEnabled",
        "setDomStorageEnabled",
        "loadUrl",
        "V", "Z", "I",
        "L", "VL", "VI", "VZ",
        "Landroid/app/Activity;",
        "Landroid/content/Context;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/webkit/WebSettings;",
        "Landroid/webkit/WebView;",
        "Ljava/lang/String;",
        main_desc,
        "file:///android_asset/index.html",
    }
    strings = sorted(string_values)
    sidx = {s: i for i, s in enumerate(strings)}

    type_descs = [
        "V", "Z", "I",
        "Landroid/app/Activity;",
        "Landroid/content/Context;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/webkit/WebSettings;",
        "Landroid/webkit/WebView;",
        "Ljava/lang/String;",
        main_desc,
    ]
    # type_ids sorted by descriptor_idx (which follows sorted string order).
    type_descs = sorted(type_descs, key=lambda d: sidx[d])
    tidx = {d: i for i, d in enumerate(type_descs)}

    # Proto key: (return descriptor, tuple(param descriptors))
    proto_keys = {
        ("V", ()),
        ("V", ("Landroid/os/Bundle;",)),
        ("V", ("Landroid/content/Context;",)),
        ("Landroid/webkit/WebSettings;", ()),
        ("Z", ("I",)),
        ("V", ("Z",)),
        ("V", ("Ljava/lang/String;",)),
        ("V", ("Landroid/view/View;",)),
    }

    def shorty(ret: str, params: tuple[str, ...]) -> str:
        def ch(desc: str) -> str:
            return "L" if desc.startswith(("L", "[")) else desc
        return ch(ret) + "".join(ch(p) for p in params)

    # Ensure all shorty strings exist. We intentionally rebuild indexes if needed.
    missing = {shorty(r, p) for r, p in proto_keys} - set(strings)
    if missing:
        strings = sorted(set(strings) | missing)
        sidx = {s: i for i, s in enumerate(strings)}
        type_descs = sorted(type_descs, key=lambda d: sidx[d])
        tidx = {d: i for i, d in enumerate(type_descs)}

    def proto_sort_key(k):
        r, p = k
        return (tidx[r], tuple(tidx[x] for x in p))

    protos = sorted(proto_keys, key=proto_sort_key)
    pidx = {p: i for i, p in enumerate(protos)}

    methods_unsorted = [
        ("Landroid/app/Activity;", "<init>", ("V", ())),
        ("Landroid/app/Activity;", "onCreate", ("V", ("Landroid/os/Bundle;",))),
        ("Landroid/app/Activity;", "requestWindowFeature", ("Z", ("I",))),
        ("Landroid/app/Activity;", "setContentView", ("V", ("Landroid/view/View;",))),
        ("Landroid/webkit/WebView;", "<init>", ("V", ("Landroid/content/Context;",))),
        ("Landroid/webkit/WebView;", "getSettings", ("Landroid/webkit/WebSettings;", ())),
        ("Landroid/webkit/WebView;", "loadUrl", ("V", ("Ljava/lang/String;",))),
        ("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", ("V", ("Z",))),
        ("Landroid/webkit/WebSettings;", "setDomStorageEnabled", ("V", ("Z",))),
        (main_desc, "<init>", ("V", ())),
        (main_desc, "onCreate", ("V", ("Landroid/os/Bundle;",))),
    ]
    methods = sorted(methods_unsorted, key=lambda m: (tidx[m[0]], sidx[m[1]], pidx[m[2]]))
    midx = {m: i for i, m in enumerate(methods)}

    # Fixed table offsets.
    header_size = 0x70
    string_ids_off = header_size
    type_ids_off = string_ids_off + 4 * len(strings)
    proto_ids_off = type_ids_off + 4 * len(type_descs)
    method_ids_off = proto_ids_off + 12 * len(protos)
    class_defs_off = method_ids_off + 8 * len(methods)
    data_off = class_defs_off + 32
    if data_off % 4:
        data_off = (data_off + 3) & ~3

    data = bytearray()

    # Type lists for proto parameters.
    proto_param_offs: dict[tuple[str, tuple[str, ...]], int] = {}
    type_list_first_off = None
    type_list_count = 0
    for proto in protos:
        _, params = proto
        if not params:
            proto_param_offs[proto] = 0
            continue
        align(data, 4)
        off = data_off + len(data)
        if type_list_first_off is None:
            type_list_first_off = off
        type_list_count += 1
        data.extend(struct.pack("<I", len(params)))
        for p in params:
            data.extend(struct.pack("<H", tidx[p]))
        align(data, 4)
        proto_param_offs[proto] = off

    # Code item builder helper.
    code_offsets: dict[str, int] = {}

    def add_code(name: str, registers: int, ins_size: int, outs_size: int, insns: list[int]) -> None:
        align(data, 4)
        off = data_off + len(data)
        code_offsets[name] = off
        data.extend(struct.pack("<HHHHII", registers, ins_size, outs_size, 0, 0, len(insns)))
        data.extend(struct.pack("<" + "H" * len(insns), *insns))
        # No tries; code item alignment is handled before the next item.

    # Constructor: p0/v0 -> invoke Activity.<init>(); return.
    init_super = midx[("Landroid/app/Activity;", "<init>", ("V", ()))]
    init_insns = []
    init_insns += _ins_invoke(0x70, init_super, [0])  # invoke-direct
    init_insns += _ins_10x(0x0E)  # return-void
    add_code("init", registers=1, ins_size=1, outs_size=1, insns=init_insns)

    # onCreate has two incoming registers p0/p1. Use v0..v2 locals and p0=v3,p1=v4.
    m_super_oncreate = midx[("Landroid/app/Activity;", "onCreate", ("V", ("Landroid/os/Bundle;",)))]
    m_request_no_title = midx[("Landroid/app/Activity;", "requestWindowFeature", ("Z", ("I",)))]
    m_web_init = midx[("Landroid/webkit/WebView;", "<init>", ("V", ("Landroid/content/Context;",)))]
    m_get_settings = midx[("Landroid/webkit/WebView;", "getSettings", ("Landroid/webkit/WebSettings;", ()))]
    m_js = midx[("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", ("V", ("Z",)))]
    m_dom = midx[("Landroid/webkit/WebSettings;", "setDomStorageEnabled", ("V", ("Z",)))]
    m_load = midx[("Landroid/webkit/WebView;", "loadUrl", ("V", ("Ljava/lang/String;",)))]
    m_set_content = midx[("Landroid/app/Activity;", "setContentView", ("V", ("Landroid/view/View;",)))]
    webview_type = tidx["Landroid/webkit/WebView;"]
    url_string = sidx["file:///android_asset/index.html"]

    oc = []
    oc += _ins_invoke(0x6F, m_super_oncreate, [3, 4])  # invoke-super
    # requestWindowFeature(FEATURE_NO_TITLE == 1); result deliberately ignored.
    oc += _ins_11n(0x12, 2, 1)  # const/4 v2, #1
    oc += _ins_invoke(0x6E, m_request_no_title, [3, 2])
    oc += _ins_21c(0x22, 0, webview_type)  # new-instance v0, WebView
    oc += _ins_invoke(0x70, m_web_init, [0, 3])
    oc += _ins_invoke(0x6E, m_get_settings, [0])
    oc += _ins_11x(0x0C, 1)  # move-result-object v1
    oc += _ins_11n(0x12, 2, 1)
    oc += _ins_invoke(0x6E, m_js, [1, 2])
    oc += _ins_invoke(0x6E, m_dom, [1, 2])
    oc += _ins_21c(0x1A, 2, url_string)  # const-string v2
    oc += _ins_invoke(0x6E, m_load, [0, 2])
    oc += _ins_invoke(0x6E, m_set_content, [3, 0])
    oc += _ins_10x(0x0E)
    add_code("onCreate", registers=5, ins_size=2, outs_size=2, insns=oc)

    # String data items.
    string_data_offsets: list[int] = [0] * len(strings)
    string_data_first_off = None
    for i, s in enumerate(strings):
        off = data_off + len(data)
        if string_data_first_off is None:
            string_data_first_off = off
        string_data_offsets[i] = off
        encoded = s.encode("utf-8")
        # All strings here are ASCII, so UTF-16 length equals Python length.
        data.extend(uleb128(len(s)))
        data.extend(encoded)
        data.append(0)

    # Class data (references known code offsets).
    class_data_off = data_off + len(data)
    init_idx = midx[(main_desc, "<init>", ("V", ()))]
    oncreate_idx = midx[(main_desc, "onCreate", ("V", ("Landroid/os/Bundle;",)))]
    class_data = bytearray()
    class_data += uleb128(0)  # static fields
    class_data += uleb128(0)  # instance fields
    class_data += uleb128(1)  # direct methods
    class_data += uleb128(1)  # virtual methods
    class_data += uleb128(init_idx)
    class_data += uleb128(0x10001)  # public | constructor
    class_data += uleb128(code_offsets["init"])
    class_data += uleb128(oncreate_idx)  # first virtual method diff from 0
    class_data += uleb128(0x0001)  # public
    class_data += uleb128(code_offsets["onCreate"])
    data.extend(class_data)

    # Map list last.
    align(data, 4)
    map_off = data_off + len(data)

    map_entries = [
        (0x0000, 1, 0),
        (0x0001, len(strings), string_ids_off),
        (0x0002, len(type_descs), type_ids_off),
        (0x0003, len(protos), proto_ids_off),
        (0x0005, len(methods), method_ids_off),
        (0x0006, 1, class_defs_off),
    ]
    if type_list_count:
        map_entries.append((0x1001, type_list_count, type_list_first_off))
    map_entries += [
        (0x2001, 2, code_offsets["init"]),
        (0x2002, len(strings), string_data_first_off),
        (0x2000, 1, class_data_off),
        (0x1000, 1, map_off),
    ]
    # Map entries are sorted by file offset.
    map_entries.sort(key=lambda x: x[2])
    data.extend(struct.pack("<I", len(map_entries)))
    for typ, size, off in map_entries:
        data.extend(struct.pack("<HHII", typ, 0, size, off))

    file_size = data_off + len(data)
    data_size = file_size - data_off

    # Build fixed sections.
    out = bytearray(b"\x00" * header_size)
    # string_ids
    for off in string_data_offsets:
        out.extend(struct.pack("<I", off))
    # type_ids
    for d in type_descs:
        out.extend(struct.pack("<I", sidx[d]))
    # proto_ids
    for ret, params in protos:
        out.extend(struct.pack("<III", sidx[shorty(ret, params)], tidx[ret], proto_param_offs[(ret, params)]))
    # method_ids
    for cls, name, proto in methods:
        out.extend(struct.pack("<HHI", tidx[cls], pidx[proto], sidx[name]))
    # class_def
    out.extend(struct.pack(
        "<IIIIIIII",
        tidx[main_desc],
        0x0001,  # public
        tidx["Landroid/app/Activity;"],
        0,
        NO_INDEX,
        0,
        class_data_off,
        0,
    ))
    while len(out) < data_off:
        out.append(0)
    out.extend(data)
    assert len(out) == file_size

    # Header without checksum/signature, then hash/fix them.
    header = struct.pack(
        "<8sI20s20I",
        b"dex\n035\x00",
        0,
        b"\x00" * 20,
        file_size,
        header_size,
        0x12345678,
        0, 0,
        map_off,
        len(strings), string_ids_off,
        len(type_descs), type_ids_off,
        len(protos), proto_ids_off,
        0, 0,
        len(methods), method_ids_off,
        1, class_defs_off,
        data_size, data_off,
    )
    assert len(header) == header_size
    out[:header_size] = header
    # The DEX file format mandates SHA-1 here; this is not a security signature.
    signature = hashlib.sha1(out[32:], usedforsecurity=False).digest()
    out[12:32] = signature
    checksum = zlib.adler32(out[12:]) & 0xFFFFFFFF
    out[8:12] = struct.pack("<I", checksum)
    return bytes(out)


# ---- Binary Android XML -------------------------------------------------

RES_STRING_POOL_TYPE = 0x0001
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_RESOURCE_MAP_TYPE = 0x0180
TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12
UTF8_FLAG = 0x00000100

ANDROID_URI = "http://schemas.android.com/apk/res/android"

# Stable framework attr IDs used by binary AndroidManifest.xml.
ATTR_IDS = {
    "label": 0x01010001,
    "name": 0x01010003,
    "exported": 0x01010010,
    "minSdkVersion": 0x0101020C,
    "targetSdkVersion": 0x01010270,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
}


def _utf8_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x8000:
        return bytes([0x80 | (n >> 8), n & 0xFF])
    raise ValueError("string too long")


def string_pool(strings: list[str]) -> bytes:
    offsets = []
    payload = bytearray()
    for s in strings:
        offsets.append(len(payload))
        raw = s.encode("utf-8")
        payload += _utf8_len(len(s))
        payload += _utf8_len(len(raw))
        payload += raw + b"\x00"
    while len(payload) % 4:
        payload.append(0)
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    size = strings_start + len(payload)
    out = bytearray(struct.pack(
        "<HHIIIIII",
        RES_STRING_POOL_TYPE, header_size, size,
        len(strings), 0, UTF8_FLAG, strings_start, 0,
    ))
    out.extend(struct.pack("<" + "I" * len(offsets), *offsets) if offsets else b"")
    out.extend(payload)
    assert len(out) == size
    return bytes(out)


def xml_node_header(chunk_type: int, size: int, line: int = 1) -> bytes:
    return struct.pack("<HHIII", chunk_type, 16, size, line, NO_INDEX)


def ns_chunk(start: bool, prefix_idx: int, uri_idx: int) -> bytes:
    typ = RES_XML_START_NAMESPACE_TYPE if start else RES_XML_END_NAMESPACE_TYPE
    return xml_node_header(typ, 24) + struct.pack("<II", prefix_idx, uri_idx)


def attr(ns_idx: int, name_idx: int, raw_idx: int, data_type: int, data: int) -> bytes:
    return struct.pack("<IIIHBBI", ns_idx, name_idx, raw_idx, 8, 0, data_type, data)


def start_element(name_idx: int, attrs: list[bytes], ns_idx: int = NO_INDEX, line: int = 1) -> bytes:
    size = 36 + 20 * len(attrs)
    ext = struct.pack("<IIHHHHHH", ns_idx, name_idx, 20, 20, len(attrs), 0, 0, 0)
    return xml_node_header(RES_XML_START_ELEMENT_TYPE, size, line) + ext + b"".join(attrs)


def end_element(name_idx: int, ns_idx: int = NO_INDEX, line: int = 1) -> bytes:
    return xml_node_header(RES_XML_END_ELEMENT_TYPE, 24, line) + struct.pack("<II", ns_idx, name_idx)


def build_manifest(package: str = "com.killgate.preview") -> bytes:
    # Keep all strings in one pool. Resource map can contain 0 entries for strings
    # that are not framework attribute names.
    values = [
        "android", ANDROID_URI,
        "manifest", "uses-sdk", "application", "activity", "intent-filter", "action", "category",
        "package", package,
        "versionCode", "versionName", "1.2.0-v1.5-engine-preview",
        "minSdkVersion", "targetSdkVersion",
        "label", "Killgate Preview",
        "name", f"{package}.MainActivity",
        "exported",
        "android.intent.action.MAIN", "android.intent.category.LAUNCHER",
    ]
    strings = []
    for v in values:
        if v not in strings:
            strings.append(v)
    idx = {s: i for i, s in enumerate(strings)}

    sp = string_pool(strings)
    resource_ids = [0] * len(strings)
    for name, rid in ATTR_IDS.items():
        if name in idx:
            resource_ids[idx[name]] = rid
    rm_size = 8 + 4 * len(resource_ids)
    resource_map = struct.pack("<HHI", RES_XML_RESOURCE_MAP_TYPE, 8, rm_size) + struct.pack(
        "<" + "I" * len(resource_ids), *resource_ids
    )

    android = idx[ANDROID_URI]
    chunks = bytearray()
    chunks += ns_chunk(True, idx["android"], android)

    # <manifest package=... android:versionCode=120 android:versionName="1.2.0-v1.5-engine-preview">
    manifest_attrs = [
        attr(NO_INDEX, idx["package"], idx[package], TYPE_STRING, idx[package]),
        attr(android, idx["versionCode"], NO_INDEX, TYPE_INT_DEC, 120),
        attr(android, idx["versionName"], idx["1.2.0-v1.5-engine-preview"], TYPE_STRING, idx["1.2.0-v1.5-engine-preview"]),
    ]
    chunks += start_element(idx["manifest"], manifest_attrs, line=2)

    # <uses-sdk android:minSdkVersion=24 android:targetSdkVersion=36/>
    sdk_attrs = [
        attr(android, idx["minSdkVersion"], NO_INDEX, TYPE_INT_DEC, 24),
        attr(android, idx["targetSdkVersion"], NO_INDEX, TYPE_INT_DEC, 36),
    ]
    chunks += start_element(idx["uses-sdk"], sdk_attrs, line=3)
    chunks += end_element(idx["uses-sdk"], line=3)

    app_attrs = [
        attr(android, idx["label"], idx["Killgate Preview"], TYPE_STRING, idx["Killgate Preview"]),
    ]
    chunks += start_element(idx["application"], app_attrs, line=4)

    activity_attrs = [
        attr(android, idx["name"], idx[f"{package}.MainActivity"], TYPE_STRING, idx[f"{package}.MainActivity"]),
        attr(android, idx["exported"], NO_INDEX, TYPE_INT_BOOLEAN, 0xFFFFFFFF),
    ]
    chunks += start_element(idx["activity"], activity_attrs, line=5)
    chunks += start_element(idx["intent-filter"], [], line=6)
    chunks += start_element(idx["action"], [
        attr(android, idx["name"], idx["android.intent.action.MAIN"], TYPE_STRING, idx["android.intent.action.MAIN"])
    ], line=7)
    chunks += end_element(idx["action"], line=7)
    chunks += start_element(idx["category"], [
        attr(android, idx["name"], idx["android.intent.category.LAUNCHER"], TYPE_STRING, idx["android.intent.category.LAUNCHER"])
    ], line=8)
    chunks += end_element(idx["category"], line=8)
    chunks += end_element(idx["intent-filter"], line=9)
    chunks += end_element(idx["activity"], line=10)
    chunks += end_element(idx["application"], line=11)
    chunks += end_element(idx["manifest"], line=12)
    chunks += ns_chunk(False, idx["android"], android)

    total_size = 8 + len(sp) + len(resource_map) + len(chunks)
    return struct.pack("<HHI", RES_XML_TYPE, 8, total_size) + sp + resource_map + chunks


def make_preview_html(css_path: Path) -> str:
    css = css_path.read_text(encoding="utf-8")
    # Small preview-only additions; all core visual styling comes from the current app.css.
    preview_css = """
    .preview-ribbon{position:sticky;top:0;z-index:50;background:#f59e0b;color:#111827;padding:calc(.55rem + 24px) 1rem .55rem;text-align:center;font-weight:800;letter-spacing:.04em}
    .preview-only{display:none}.preview-only.active{display:block}.preview-actions{display:flex;gap:.7rem;flex-wrap:wrap;margin-top:1rem}
    .preview-actions button.secondary{background:#374151}.fake-input{pointer-events:none;opacity:.92}.preview-note{border:1px solid #374151;border-radius:14px;padding:1rem;margin:1rem 0;background:#111827}
    .gate-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}.gate-grid>div{padding:.9rem;border:1px solid #273449;border-radius:12px;background:#0b1220}.gate-grid span{display:block;color:#94a3b8;font-size:.78rem}.gate-grid strong{display:block;margin-top:.25rem}
    @media(max-width:700px){.gate-grid{grid-template-columns:1fr}}
    """
    # Inline current SVG mark.
    mark = (css_path.parent / "icons" / "killgate-mark.svg").read_text(encoding="utf-8")
    # Keep it valid inside a div and strip XML declaration if any.
    mark = mark.replace('<?xml version="1.0" encoding="UTF-8"?>', '')
    return f'''<!doctype html>
<html lang="en-US"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="dark"><title>Killgate Preview</title><style>{css}\n{preview_css}</style></head>
<body class="home-page">
<div class="preview-ribbon">LOCAL UI PREVIEW · backend/AI/billing are not connected in this APK</div>
<header class="app-header"><div class="brand"><span style="width:42px;height:42px;display:block">{mark}</span><span><strong>Killgate</strong><small>Idea Validation</small></span></div><div class="header-actions"><span class="status status-checking">Product preview</span></div></header>
<main>
<section id="screen-home" class="preview-only active">
<section class="hero"><span class="eyebrow">KILLGATE</span><h1>Ideas are easy.<br><span class="brand-accent">Evidence is rare.</span></h1><p>KillGate tests your idea against real-world reality.</p></section>
<section class="panel intake-panel"><div class="section-heading"><span class="step-number">01</span><div><h2>What's your idea?</h2><p>Describe your business idea and we'll turn it into a testable hypothesis.</p></div></div>
<label>Describe the customer, the problem, and what you want to sell.</label><textarea rows="5" class="fake-input" placeholder="Example: An app that uses AI to help homeowners find and book trusted contractors.">Independent collision shops with 3–20 technicians and recurring supplement delays pay $249/month for a tool that predicts likely hidden estimate omissions before teardown and gives the estimator a prioritized review packet.</textarea><div class="form-footer"><span class="muted small">Preview example</span><button onclick="showScreen('contract')">Start Validation <span aria-hidden="true">→</span></button></div></section>
<section><div class="section-heading list-heading"><span class="step-number">02</span><div><h2>Your ideas</h2><p>Reopen an idea to review its validation plan, evidence, next action, or decision.</p></div></div><div class="venture-grid"><article class="venture-card"><div class="venture-topline"><strong>V-PREVIEW</strong><span class="status status-checking">Validation active</span></div><p>Pre-teardown supplement prediction for collision shops...</p><span class="muted small">Day 1</span></article></div></section>
</section>

<section id="screen-contract" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('home');return false">← All ideas</a></nav>
<section class="venture-hero"><span class="eyebrow">VENTURE V-PREVIEW</span><h1>Pre-teardown supplement prediction for independent collision shops</h1><div class="metrics"><div><span>Stage</span><strong>Validation</strong></div><div><span>Decision</span><strong>Pending</strong></div><div><span>Day</span><strong>1</strong></div></div></section>
<section class="panel contract-panel"><div class="contract-titleline"><div><span class="eyebrow">VALIDATION CONTRACT</span><h2>The evidence standard was locked before results arrived.</h2></div><span class="lock-badge">LOCKED</span></div><p class="muted">This keeps a promising result from lowering the bar and a disappointing result from quietly changing the question.</p><div class="contract-thresholds"><div><span>Public evidence</span><strong>Enough relevant, independent sources to justify buyer testing</strong></div><div><span>Buyer conversations</span><strong>Qualified buyers with recent real examples</strong></div><div><span>Problem strength</span><strong>Strong pain confirmed by buyer evidence</strong></div><div><span>Payment proof</span><strong>Verified paid pilots</strong></div></div><details><summary>What the locked plan protects</summary><h3>Evidence that does not count</h3><ul><li>AI personas or simulated demand.</li><li>Founder claims about willingness to pay.</li><li>Likes, compliments, or generic “sounds useful” reactions.</li><li>Hypothetical payment statements without a real offer.</li></ul><h3>Possible decisions</h3><ul><li><strong>Go Build:</strong> the required public and buyer evidence has cleared the standard.</li><li><strong>Continue:</strong> important proof is still missing.</li><li><strong>Pivot:</strong> the buyer, offer, price, or approach should change.</li><li><strong>Stop:</strong> strong negative evidence says more investment is not justified.</li></ul></details></section>
<div class="preview-actions"><button onclick="showScreen('research')">Run public research →</button><button class="danger" onclick="showScreen('killed')">Stop this idea</button></div>
</section>

<section id="screen-research" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('contract');return false">← Venture</a></nav>
<section class="venture-hero"><span class="eyebrow">VENTURE V-PREVIEW</span><h1>Pre-teardown supplement prediction for independent collision shops</h1><div class="metrics"><div><span>Stage</span><strong>Validation</strong></div><div><span>Decision</span><strong>Pending</strong></div><div><span>Day</span><strong>1</strong></div></div></section>
<section class="panel research-result"><span class="eyebrow">PUBLIC EVIDENCE RESULT</span><h2 class="verdict-caution">Test a critical capability first</h2><p class="muted">Illustrative preview result — this local APK does not run live research.</p><p class="callout caution">Public evidence suggests the problem is real enough to keep testing, but the offer depends on a capability that has not yet been proven. Prove that capability before asking buyers to pay.</p><h3>What this means</h3><ul><li>There is enough background evidence to avoid stopping immediately.</li><li>The most important product promise is still uncertain.</li><li>A focused capability test is the safest next step.</li></ul><div class="preview-actions"><button onclick="showScreen('feasibility')">Open capability test →</button></div></section>
</section>

<section id="screen-feasibility" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('research');return false">← Research verdict</a></nav>
<section class="panel feasibility-panel"><span class="eyebrow">CRITICAL CAPABILITY TEST</span><h2>Can the offer deliver its most important promise?</h2><p class="callout caution">Use only information that would actually be available when a customer uses the product.</p><h3>What to test</h3><p>Whether the proposed product can identify costly omissions early enough to change an estimator's action.</p><h3>What to measure</h3><ul><li>How often useful issues are found</li><li>How often the product raises a false alarm</li><li>Whether a correct result would change the buyer's workflow</li></ul><h3>What happens next</h3><p>A pass opens buyer and price testing. A failure means the approach should change or the idea should stop.</p><div class="preview-actions"><button onclick="showScreen('reality')">Preview capability test passed →</button><button class="danger" onclick="showScreen('killed')">Preview failed test / stop</button></div></section>
</section>

<section id="screen-reality" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('feasibility');return false">← Capability test</a></nav>
<section class="panel reality-panel"><span class="eyebrow">BUYER PROOF</span><h2>Capability passed. Now test what only real customers can prove.</h2><p>Interview qualified buyers and record recent examples, current workarounds, reactions to the actual offer, objections, commitments, and payment evidence.</p><div class="gate-grid"><div><span>Qualified buyers</span><strong>0 / 8</strong></div><div><span>Strong pain</span><strong>0% / 30%</strong></div><div><span>Price-positive</span><strong>0 / 4</strong></div><div><span>Paid pilots</span><strong>0 / 2</strong></div></div><div class="preview-actions"><button onclick="showScreen('evidence')">Record buyer evidence →</button></div></section>
</section>

<section id="screen-evidence" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('reality');return false">← Human reality check</a></nav>
<section class="panel reality-panel"><span class="eyebrow">BUYER EVIDENCE</span><h2>Record what a real buyer actually did and said.</h2><div class="form-grid"><div><label>Buyer/company label</label><input value="Collision shop estimator #1" class="fake-input"></div><div><label>Buyer role</label><input value="Estimator / owner purchase influencer" class="fake-input"></div></div><label>Recent real example of the problem</label><textarea rows="3" class="fake-input">A hidden bracket and calibration operation were found after teardown, triggering a supplement that held production for two days.</textarea><label>What they do today</label><textarea rows="3" class="fake-input">Estimator manually reviews the insurer estimate and photos, then relies on teardown to reveal hidden damage and missed operations.</textarea><div class="form-grid"><div><label>Pain strength</label><select class="fake-input"><option>Strong</option></select></div><div><label>Pilot price actually offered</label><input value="$249/month" class="fake-input"></div></div><label>Exact reaction to price</label><textarea rows="2" class="fake-input">If it catches even one delay-causing omission before teardown each month, $249 is easy to justify — but I need to see it work on our estimates.</textarea><div class="preview-actions"><button onclick="showScreen('progress')">Save buyer evidence and update the decision</button></div></section>
</section>

<section id="screen-progress" class="preview-only">
<nav class="back-nav"><a href="#" onclick="showScreen('research');return false">← Venture</a></nav>
<section class="panel"><span class="eyebrow">BUYER EVIDENCE PROGRESS</span><h2 class="verdict-caution">CONTINUE TESTING</h2><div class="gate-grid"><div><span>Qualified buyers</span><strong>1 / 8</strong></div><div><span>Strong pain</span><strong>100% / 30%</strong></div><div><span>Price-positive</span><strong>1 / 4</strong></div><div><span>Paid pilots</span><strong>0 / 2</strong></div></div><p class="callout caution">One encouraging conversation is not enough. More independent buyer evidence is still needed.</p><div class="preview-actions"><button onclick="showScreen('evidence')">Add another buyer</button><button class="secondary" onclick="showScreen('go')">Preview completed Go Build state</button></div></section>
</section>

<section id="screen-go" class="preview-only"><nav class="back-nav"><a href="#" onclick="showScreen('progress');return false">← Buyer evidence progress</a></nav><section class="panel"><span class="eyebrow">FINAL DECISION</span><h1 class="verdict-pass">GO BUILD</h1><p>Preview of the state Killgate reaches only after every required piece of evidence is satisfied.</p><div class="gate-grid"><div><span>Qualified buyers</span><strong>8 / 8 ✓</strong></div><div><span>Strong pain</span><strong>50% / 30% ✓</strong></div><div><span>Price-positive</span><strong>4 / 4 ✓</strong></div><div><span>Paid pilots</span><strong>2 / 2 ✓</strong></div></div><div class="go-notice"><strong>Go Build recorded.</strong><span>The required evidence passed and the decision was explicitly approved.</span></div></section></section>

<section id="screen-killed" class="preview-only"><nav class="back-nav"><a href="#" onclick="showScreen('contract');return false">← Idea</a></nav><section class="panel"><span class="eyebrow">FINAL DECISION</span><h1 class="verdict-kill">STOP</h1><div class="killed-notice"><strong>Idea stopped.</strong><span>This idea will not advance because the evidence does not justify more time or money.</span></div><div class="preview-actions"><button onclick="showScreen('home')">Back to ideas</button></div></section></section>
</main><footer><span>Kill weak ideas early. Build the survivors.</span><span class="version">v1.5 engine preview</span></footer>
<script>
function showScreen(name){{document.querySelectorAll('.preview-only').forEach(e=>e.classList.remove('active'));const el=document.getElementById('screen-'+name);if(el){{el.classList.add('active');window.scrollTo(0,0)}}}}
document.querySelectorAll('.fake-input').forEach(e=>e.addEventListener('click',ev=>ev.preventDefault()));
</script></body></html>'''


def ensure_keystore(path: Path, password: str, keytool: Path) -> None:
    if path.exists():
        return
    subprocess.run([
        str(keytool), "-genkeypair", "-noprompt", "-storetype", "PKCS12",
        "-keystore", str(path), "-storepass", password, "-keypass", password,
        "-alias", "killgate-preview", "-keyalg", "RSA", "-keysize", "2048",
        "-validity", "3650", "-dname", "CN=Killgate Preview,O=Killgate,C=US",
    ], check=True, capture_output=True)


def android_build_tool(name: str) -> Path:
    """Locate a current Android build tool strictly beneath a selected SDK root."""
    executable_names = [f"{name}.bat", f"{name}.exe", name] if os.name == "nt" else [name]

    sdk_roots = [
        os.getenv("ANDROID_SDK_ROOT", ""),
        os.getenv("ANDROID_HOME", ""),
    ]
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        sdk_roots.append(str(Path(local_app_data) / "Android" / "Sdk"))

    def version_key(path: Path) -> tuple[int, ...]:
        parts = []
        for value in path.name.split("."):
            try:
                parts.append(int(value))
            except ValueError:
                parts.append(-1)
        return tuple(parts)

    for raw_root in dict.fromkeys(value for value in sdk_roots if value):
        sdk_root = Path(raw_root).expanduser().resolve()
        build_tools = sdk_root / "build-tools"
        if not build_tools.is_dir():
            continue
        for version_dir in sorted(
            (path for path in build_tools.iterdir() if path.is_dir()),
            key=version_key,
            reverse=True,
        ):
            for executable_name in executable_names:
                candidate = version_dir / executable_name
                if candidate.is_file():
                    resolved = candidate.resolve()
                    if resolved.is_relative_to(sdk_root):
                        return resolved
    raise RuntimeError(
        f"Android build tool {name!r} was not found. Install current Android SDK Build Tools first."
    )


def java_build_tool(name: str) -> Path:
    """Resolve a JDK executable beneath JAVA_HOME; never select it from PATH."""
    java_home = os.getenv("JAVA_HOME", "").strip()
    if not java_home:
        raise RuntimeError("JAVA_HOME must select a trusted JDK 17 installation.")
    root = Path(java_home).expanduser().resolve()
    executable = f"{name}.exe" if os.name == "nt" else name
    candidate = (root / "bin" / executable).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root):
        raise RuntimeError(f"JDK tool {name!r} was not found beneath JAVA_HOME.")
    return candidate


def compile_preview_dex(package: str) -> bytes:
    """Compile the preview Activity with javac and D8.

    The original transfer used a hand-assembled DEX to avoid an Android toolchain.
    That artifact installed but left an empty WebView on Android 16. The release
    workstation now has the official SDK, so use the platform compiler and keep
    explicit WebView diagnostics in logcat.
    """
    d8 = android_build_tool("d8")
    sdk_root = d8.parents[2]
    android_jar = sdk_root / "platforms" / "android-36" / "android.jar"
    if not android_jar.is_file():
        raise RuntimeError(f"Android 36 platform was not found at {android_jar}")

    javac = java_build_tool("javac")

    source = """package __PACKAGE__;

import android.app.Activity;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.webkit.ConsoleMessage;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public final class MainActivity extends Activity {
    private static final String TAG = "KillgatePreview";

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);

        WebView webView = new WebView(this);
        webView.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override
            public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                view.setPadding(
                    0,
                    insets.getSystemWindowInsetTop(),
                    0,
                    insets.getSystemWindowInsetBottom()
                );
                return insets;
            }
        });
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                Log.i(TAG, "Page started: " + url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                Log.i(TAG, "Page finished: " + url + "; title=" + view.getTitle());
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                Log.e(TAG, "WebView error " + error.getErrorCode() + ": " + error.getDescription());
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage message) {
                Log.i(TAG, "Console: " + message.message());
                return true;
            }
        });
        setContentView(webView);
        webView.loadUrl("file:///android_asset/index.html");
    }
}
""".replace("__PACKAGE__", package)

    with tempfile.TemporaryDirectory(prefix="killgate-preview-build-") as raw_temp:
        temp = Path(raw_temp)
        source_root = temp / "source" / Path(*package.split("."))
        source_root.mkdir(parents=True)
        java_file = source_root / "MainActivity.java"
        java_file.write_text(source, encoding="utf-8")
        classes = temp / "classes"
        classes.mkdir()
        compiled = subprocess.run(
            [
                str(javac), "-encoding", "UTF-8", "-source", "8", "-target", "8",
                "-bootclasspath", str(android_jar), "-d", str(classes), str(java_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            raise RuntimeError(f"javac failed:\n{compiled.stdout}{compiled.stderr}")

        dex_output = temp / "dex"
        dex_output.mkdir()
        class_files = sorted(classes.rglob("*.class"))
        dexed = subprocess.run(
            [
                str(d8), "--lib", str(android_jar), "--min-api", "24",
                "--output", str(dex_output), *(str(path) for path in class_files),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if dexed.returncode:
            raise RuntimeError(f"D8 failed:\n{dexed.stdout}{dexed.stderr}")
        return (dex_output / "classes.dex").read_bytes()


def build_apk(repo_root: Path, output: Path) -> Path:
    package = "com.killgate.preview"
    dex = compile_preview_dex(package)
    manifest = build_manifest(package)
    html = make_preview_html(repo_root / "app/static/app.css")

    output.parent.mkdir(parents=True, exist_ok=True)
    unsigned = output.with_suffix(".unsigned.apk")
    with zipfile.ZipFile(unsigned, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", manifest, compress_type=zipfile.ZIP_STORED)
        zf.writestr("classes.dex", dex, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("assets/index.html", html, compress_type=zipfile.ZIP_DEFLATED)

    # targetSdk 36 requires APK Signature Scheme v2 or newer. Align before
    # signing, then have apksigner verify the exact artifact we return.
    keystore = output.parent / ".killgate-preview-signing.p12"
    password = "killgate-preview-local-only"
    ensure_keystore(keystore, password, java_build_tool("keytool"))
    signed = output
    aligned = output.with_suffix(".aligned.apk")
    if signed.exists():
        signed.unlink()
    zipalign = android_build_tool("zipalign")
    apksigner = android_build_tool("apksigner")
    try:
        subprocess.run(
            [str(zipalign), "-f", "4", str(unsigned), str(aligned)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                str(apksigner), "sign",
                "--ks", str(keystore),
                "--ks-key-alias", "killgate-preview",
                "--ks-pass", f"pass:{password}",
                "--key-pass", f"pass:{password}",
                "--out", str(signed),
                str(aligned),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [str(apksigner), "verify", "--verbose", str(signed)],
            check=True,
            capture_output=True,
        )
    finally:
        unsigned.unlink(missing_ok=True)
        aligned.unlink(missing_ok=True)
    return signed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/mnt/data/Killgate-v1.5-PATCHED-UI-PREVIEW.apk")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    apk = build_apk(root, Path(args.output))
    print(apk)
    print("sha256", hashlib.sha256(apk.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
