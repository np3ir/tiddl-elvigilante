"""
tiddl auth web-login — Token capture via existing Chrome (CDP) or Playwright fallback.

Primary method: connects to Chrome running with --remote-debugging-port=9222.
No new browser opened, no bot detection risk — uses the real Chrome session.

Fallback: launches Playwright Chromium with persistent session.

Run Chrome with debugging:
  chrome.exe --remote-debugging-port=9222 --user-data-dir=<any-dir>
Or use the helper: tiddl auth launch-chrome
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
import typer
from rich.console import Console

from tiddl.cli.const import APP_PATH
from tiddl.cli.utils.auth.core import save_auth_data
from tiddl.cli.utils.auth.models import AuthData

console = Console()
log = logging.getLogger(__name__)

SESSION_DIR = APP_PATH / "browser_session"
CDP_URL = "http://127.0.0.1:9222"


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.b64decode(payload).decode())
    except Exception:
        return {}


def _session_exists() -> bool:
    return SESSION_DIR.exists() and any(SESSION_DIR.iterdir())


def _is_chrome_debugging_available() -> bool:
    """Check if Chrome is running with --remote-debugging-port=9222."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1)
        return True
    except Exception:
        return False


async def _capture_via_cdp() -> AuthData | None:
    """
    Capture token from existing Chrome via CDP Network events.
    Chrome must be running with --remote-debugging-port=9222.

    Uses CDP Network.requestWillBeSent to intercept Authorization headers
    from the real Chrome session — no new browser, no bot detection.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    captured: dict = {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            contexts = browser.contexts
            if not contexts:
                await browser.close()
                return None

            context = contexts[0]
            page = next(
                (pg for pg in context.pages if "tidal.com" in pg.url),
                None,
            )
            if not page:
                page = await context.new_page()

            # CDP Network domain — intercepts real browser requests
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")

            def on_network_request(event):
                url = event.get("request", {}).get("url", "")
                headers = event.get("request", {}).get("headers", {})
                if "api.tidal.com" in url and not captured:
                    auth = (headers.get("authorization") or
                            headers.get("Authorization", ""))
                    if auth.startswith("Bearer "):
                        captured["token"] = auth[7:]

            cdp.on("Network.requestWillBeSent", on_network_request)

            # Navigate to web app — fires API requests on load
            await page.goto("https://listen.tidal.com/")

            for i in range(20):
                if captured:
                    break
                if i == 5:
                    try:
                        await page.evaluate(
                            "() => fetch('https://api.tidal.com/v1/sessions',"
                            " {credentials: 'include'})"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1)

            await cdp.detach()
            await browser.close()

    except Exception as e:
        log.debug(f"CDP capture failed: {e}")
        return None

    if not captured:
        return None

    return _build_auth_data(captured["token"])


async def _capture_via_playwright(silent: bool = False) -> AuthData | None:
    """
    Fallback: launch Playwright Chromium with persistent session.
    Used when Chrome CDP is not available.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        console.print("[red]Playwright no instalado. Corre: pip install playwright && playwright install chromium[/]")
        return None

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    captured: dict = {}

    async def _run(headless: bool, timeout: int) -> bool:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                no_viewport=True if not headless else None,
                viewport={"width": 1280, "height": 800} if headless else None,
            )

            page = context.pages[0] if context.pages else await context.new_page()

            def on_request(request):
                if "api.tidal.com" in request.url and not captured:
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer "):
                        captured["token"] = auth[7:]

            context.on("request", on_request)
            await page.goto("https://listen.tidal.com/")

            for i in range(timeout):
                if captured:
                    break
                if i == 3:
                    try:
                        await page.evaluate(
                            "() => fetch('https://api.tidal.com/v1/sessions', "
                            "{credentials: 'include'})"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1)

            await context.close()
        return bool(captured)

    if silent:
        success = await _run(headless=True, timeout=15)
        if not success:
            console.print("[yellow]Token expirado — abriendo browser para re-autenticar...[/]")
            await _run(headless=False, timeout=180)
    else:
        console.print("[dim]Esperando token de api.tidal.com...[/]")
        await _run(headless=False, timeout=180)

    if not captured:
        return None

    return _build_auth_data(captured["token"])


def _build_auth_data(token: str) -> AuthData | None:
    payload = _decode_jwt_payload(token)
    if not payload:
        return None
    return AuthData(
        token=token,
        refresh_token=None,
        expires_at=payload.get("exp", int(time.time()) + 14400),
        user_id=str(payload.get("uid", "")),
        country_code=payload.get("cc", "US"),
        client_id=None,
    )


async def auto_refresh_if_needed(threshold_minutes: int = 30) -> bool:
    """
    Called automatically before downloads.
    Refreshes the token silently if it expires within threshold_minutes.
    Tries CDP first, then Playwright fallback.
    """
    from tiddl.cli.utils.auth.core import load_auth_data

    auth = load_auth_data()
    if not auth.token:
        return False

    minutes_left = (auth.expires_at - time.time()) / 60
    if minutes_left > threshold_minutes:
        return False

    log.info(f"Token expira en {minutes_left:.0f}min — auto-refresh...")
    console.print(f"[yellow]Token expira en {minutes_left:.0f} min — refrescando...[/]")

    auth_data = None

    if _is_chrome_debugging_available():
        log.debug("Auto-refresh via CDP...")
        auth_data = await _capture_via_cdp()

    if not auth_data and _session_exists():
        log.debug("CDP failed or unavailable, trying Playwright...")
        auth_data = await _capture_via_playwright(silent=True)

    if auth_data:
        save_auth_data(auth_data)
        exp_dt = time.strftime("%H:%M", time.localtime(auth_data.expires_at))
        console.print(f"[green]Token renovado (expira {exp_dt})[/]")
        return True

    console.print("[red]Auto-refresh falló — corre 'tiddl auth web-login' manualmente.[/]")
    return False


def web_login():
    """Login automático via browser — captura token de tidal.com."""

    # Try CDP first (existing Chrome)
    if _is_chrome_debugging_available():
        console.print("[bold cyan]Chrome detectado — capturando token via CDP...[/]\n")
        auth_data = asyncio.run(_capture_via_cdp())
        if auth_data:
            _save_and_print(auth_data)
            return
        console.print(
            "[yellow]CDP conectó pero no capturó token.[/]\n"
            "[dim]Si es la primera vez, inicia sesión en tidal.com en la ventana de Chrome\n"
            "que abrió 'tiddl auth launch-chrome' y vuelve a correr este comando.[/]\n"
        )

    else:
        console.print("[dim]Chrome no está en modo debug. Para evitar detección futura:[/]")
        console.print("[dim]  tiddl auth launch-chrome   → abre Chrome debug[/]")
        console.print("[dim]  Inicia sesión en tidal.com en esa ventana[/]")
        console.print("[dim]  tiddl auth web-login       → captura sin bot detection[/]\n")
        console.print("[cyan]Abriendo Chromium (fallback)...[/]\n")

    # Fallback: Playwright Chromium
    auth_data = asyncio.run(_capture_via_playwright(silent=False))

    if not auth_data:
        console.print("[red]No se pudo capturar token.[/]")
        raise typer.Exit(1)

    _save_and_print(auth_data)


def _save_and_print(auth_data: AuthData):
    save_auth_data(auth_data)
    exp_dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(auth_data.expires_at))
    console.print(f"\n[bold green]Token capturado![/]")
    console.print(f"  Usuario: [cyan]{auth_data.user_id}[/]  País: [cyan]{auth_data.country_code}[/]")
    console.print(f"  Expira:  [yellow]{exp_dt}[/]")


def launch_chrome():
    """Lanza Chrome con remote debugging en puerto 9222."""
    import subprocess, shutil, sys
    from pathlib import Path

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome") or "",
        shutil.which("google-chrome") or "",
    ]

    chrome = next((p for p in chrome_paths if p and Path(p).exists()), None)

    if not chrome:
        console.print("[red]Chrome no encontrado. Instálalo o añade la ruta manualmente.[/]")
        raise typer.Exit(1)

    debug_profile = APP_PATH / "chrome_debug_profile"
    debug_profile.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        f"--remote-debugging-port=9222",
        f"--user-data-dir={debug_profile}",
        "https://listen.tidal.com/",
    ]

    console.print(f"[green]Lanzando Chrome con debugging en puerto 9222...[/]")
    console.print(f"[dim]{' '.join(cmd[:2])}...[/]")
    console.print("\n[yellow]Inicia sesión en tidal.com si es necesario, luego corre:[/]")
    console.print("[bold]  tiddl auth web-login[/]")

    subprocess.Popen(cmd)
