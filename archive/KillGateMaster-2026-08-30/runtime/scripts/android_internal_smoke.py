#!/usr/bin/env python3
"""Capture repeatable Android/TWA smoke evidence from a Play-installed Killgate build."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PACKAGE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
COMPONENT_RE = re.compile(
    rf"{PACKAGE_RE.pattern}/(?:\.[A-Za-z_$][A-Za-z0-9_$.]*|[A-Za-z_$][A-Za-z0-9_$.]*)"
)
SERIAL_RE = re.compile(r"[A-Za-z0-9._:-]{1,200}")
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
TOKEN_RE = re.compile(r"(?i)(bearer\s+|purchase[_ -]?token[=: ]+)([^\s,;\"']+)")


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def redact(value: str, *, limit: int = 500_000) -> str:
    value = EMAIL_RE.sub("[redacted-email]", value)
    value = TOKEN_RE.sub(lambda match: match.group(1) + "[redacted-token]", value)
    return value[-limit:]


def resolve_adb(explicit: str) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise ValueError("--adb must name an existing adb executable.")

    roots = [os.getenv("ANDROID_SDK_ROOT", ""), os.getenv("ANDROID_HOME", "")]
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        roots.append(str(Path(local_app_data) / "Android" / "Sdk"))
    executable = "adb.exe" if os.name == "nt" else "adb"
    for raw_root in dict.fromkeys(root for root in roots if root):
        root = Path(raw_root).expanduser().resolve()
        candidate = (root / "platform-tools" / executable).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return candidate
    raise ValueError(
        "adb was not found beneath ANDROID_SDK_ROOT/ANDROID_HOME. Select the trusted SDK with --adb if needed."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-id", required=True, help="Final Android package ID")
    parser.add_argument("--serial", default="", help="adb device serial; omit when exactly one device is attached")
    parser.add_argument("--adb", default="", help="Explicit trusted adb executable path")
    parser.add_argument("--out-dir", default="", help="Directory for minimized QA evidence")
    parser.add_argument(
        "--capture-private-ui",
        action="store_true",
        help="also capture screenshot and UI hierarchy; use only with a dedicated test account/device",
    )
    args = parser.parse_args()

    try:
        adb = str(resolve_adb(args.adb))
    except ValueError as exc:
        parser.error(str(exc))

    prefix = [adb]
    if args.serial:
        if not SERIAL_RE.fullmatch(args.serial):
            parser.error("--serial contains characters outside the adb serial grammar.")
        prefix += ["-s", args.serial]

    devices = run([adb, "devices"]).stdout
    attached = [line.split()[0] for line in devices.splitlines()[1:] if line.strip().endswith("\tdevice")]
    if args.serial and args.serial not in attached:
        parser.error(f"adb device {args.serial!r} is not attached and authorized.")
    if not args.serial and len(attached) != 1:
        parser.error(f"Expected exactly one authorized adb device, found {len(attached)}. Use --serial.")

    package_id = args.package_id.strip()
    if not PACKAGE_RE.fullmatch(package_id):
        parser.error("--package-id must match the Android package-name grammar.")

    out = Path(args.out_dir) if args.out_dir else Path("artifacts") / f"android-qa-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)

    installed = run(prefix + ["shell", "pm", "path", package_id], check=False)
    if installed.returncode != 0 or not installed.stdout.strip().startswith("package:"):
        parser.error("Package is not installed on the selected device. Install it from the Play internal track first.")

    resolved = run(prefix + ["shell", "cmd", "package", "resolve-activity", "--brief", package_id], check=False)
    activity = resolved.stdout.strip().splitlines()[-1] if resolved.stdout.strip() else ""
    if resolved.returncode != 0 or not COMPONENT_RE.fullmatch(activity):
        parser.error("Could not resolve the package launch activity.")

    run(prefix + ["logcat", "-c"], check=False)
    launched = run(prefix + ["shell", "am", "start", "-W", "-n", activity], check=False)
    (out / "launch.txt").write_text(redact(launched.stdout + launched.stderr), encoding="utf-8")
    if launched.returncode != 0:
        print("Launch failed; see launch.txt", file=sys.stderr)
        return 2

    time.sleep(2)
    artifacts = ["launch.txt", "crash-log.txt", "logcat.txt"]
    if args.capture_private_ui:
        screenshot = subprocess.run(prefix + ["exec-out", "screencap", "-p"], capture_output=True, check=False)
        (out / "landing.png").write_bytes(screenshot.stdout)
        ui = run(prefix + ["exec-out", "uiautomator", "dump", "/dev/tty"], check=False)
        (out / "ui.xml").write_text(redact(ui.stdout + ui.stderr), encoding="utf-8")
        artifacts.extend(["landing.png", "ui.xml"])

    pid_result = run(prefix + ["shell", "pidof", package_id], check=False)
    pid = pid_result.stdout.strip().split()[0] if pid_result.stdout.strip() else ""
    if not pid.isdigit():
        print("Could not resolve the launched app PID.", file=sys.stderr)
        return 3
    crashes = run(prefix + ["logcat", "-b", "crash", "--pid", pid, "-d", "-t", "500"], check=False)
    (out / "crash-log.txt").write_text(redact(crashes.stdout + crashes.stderr), encoding="utf-8")
    logs = run(prefix + ["logcat", "--pid", pid, "-d", "-t", "1000"], check=False)
    (out / "logcat.txt").write_text(redact(logs.stdout + logs.stderr), encoding="utf-8")

    metadata = {
        "package_id": package_id,
        "device_serial": args.serial or attached[0],
        "resolved_activity": activity,
        "installed_path": installed.stdout.strip(),
        "private_ui_captured": args.capture_private_ui,
        "artifacts": artifacts,
    }
    (out / "qa-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if args.capture_private_ui and not (out / "landing.png").stat().st_size:
        print("Screenshot capture was empty.", file=sys.stderr)
        return 3
    print(f"Android smoke evidence written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
