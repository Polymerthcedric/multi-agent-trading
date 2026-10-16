#!/usr/bin/env python3
"""
One-Command Start — Kenya Simple Edition
No Docker. No VPS. No credit card.
Just: python3 start.py

Requirements: Python 3.10+, pip
"""
import os
import sys
import subprocess
import threading
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent


def check_python():
    if sys.version_info < (3, 10):
        print(f"ERROR: Need Python 3.10+ (you have {sys.version})")
        print("Install: sudo apt install python3.12 python3.12-venv")
        sys.exit(1)


def setup_venv():
    venv = ROOT / ".venv"
    if not venv.exists():
        print("[1/4] Creating virtual environment...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    else:
        print("[1/4] Virtual environment exists")

    pip = venv / "bin" / "pip"
    req = ROOT / "requirements.txt"
    if req.exists():
        print("[2/4] Installing dependencies...")
        subprocess.check_call([str(pip), "install", "-q", "-r", str(req)])

    return venv


def setup_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        print("[3/4] Creating .env (first time setup)...")
        env_file.write_text("""# === Kenya Simple Setup ===
# WhatsApp Alerts (see KENYA.md for how to get your API key)
WHATSAPP_API_KEY=
WHATSAPP_PHONE=254
TRADINGVIEW_WEBHOOK_SECRET=

# Bind to this computer only. Set to 0.0.0.0 to allow other devices on your LAN.
DASHBOARD_ADDRESS=127.0.0.1
WEBHOOK_HOST=127.0.0.1
""")
        print("")
        print("  FIRST TIME? Edit .env to add:")
        print("  - Your WhatsApp phone number (254XXXXXXXXX)")
        print("  - Your WhatsApp API key (see KENYA.md)")
        print("")
        print("  nano .env")
        print("")
    else:
        print("[3/4] .env exists")
    load_dotenv(env_file, override=True)


def run_webhook(venv):
    webhook = venv / "bin" / "python"
    try:
        subprocess.run(
            [str(webhook), str(ROOT / "webhook_server.py")],
            cwd=str(ROOT),
            env={**os.environ},
            capture_output=True,
        )
    except Exception:
        pass


def run_dashboard(venv):
    dashboard_address = os.environ.get("DASHBOARD_ADDRESS", "127.0.0.1")
    print("[4/4] Starting dashboard...")
    print("")
    print("=" * 50)
    print("  MULTI-AGENT TRADING BOT")
    print("  Dashboard: http://localhost:8501")
    print("  Webhooks:  http://localhost:8000")
    print("  Mode: PAPER TRADING (safe)")
    print("=" * 50)
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print("")

    streamlit = venv / "bin" / "streamlit"

    webhook_thread = threading.Thread(
        target=run_webhook, args=(venv,), daemon=True
    )
    webhook_thread.start()

    try:
        subprocess.run(
            [
                str(streamlit), "run", str(ROOT / "dashboard.py"),
                "--server.headless", "true",
                "--server.port", "8501",
                "--server.address", dashboard_address,
                "--browser.serverAddress", "localhost",
            ],
            cwd=str(ROOT),
        )
    except KeyboardInterrupt:
        print("\nStopping...")


def main():
    print("")
    print("  Multi-Agent Trading Bot")
    print("  Kenya Simple Edition")
    print("")

    check_python()
    venv = setup_venv()
    setup_env()
    run_dashboard(venv)


if __name__ == "__main__":
    main()
