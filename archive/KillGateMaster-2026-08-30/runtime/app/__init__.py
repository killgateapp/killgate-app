"""Killgate application package and local developer configuration."""

from pathlib import Path

from dotenv import load_dotenv

# Real deployments inject secrets through the hosting platform. On a developer
# workstation, allow the ignored .env.local requested by the owner, with normal
# process environment variables retaining higher precedence.
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env.local", override=False)
load_dotenv(_ROOT / ".env", override=False)
