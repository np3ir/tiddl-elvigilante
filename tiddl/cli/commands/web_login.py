"""
tiddl auth web-login — Playwright-based token capture.

Opens a persistent browser session at listen.tidal.com, intercepts the first
Bearer token from api.tidal.com requests, and saves it to auth.json.

Session is persisted between runs — the user only logs in once.
Silent mode: if a browser session already exists, runs headless and auto-closes.
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


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.b64decode(payload).decode())
    except Exception:
        return {}


def _session_exists() -> bool:
    """Returns True if a saved browser session exists."""
    return SESSION_DIR.exists() and any(SESSION_DIR.iterdir())


async def _capture_token(silent: bool = False) -> AuthData | None:
    """
    Capture a Bearer token from tidal.com.

    silent=True: headless mode, expects a saved session. Used for auto-refresh.
                 Falls back to headful if token not captured within 15s.
    silent=False: visible browser, waits up to 3 minutes (for manual login).
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

            # After page loads, trigger a known API call to force token emission
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
        log.debug("Auto-refresh: trying headless mode...")
        success = await _run(headless=True, timeout=15)
        if not success:
            # Session may have expired — fall back to visible browser
            log.debug("Headless failed, falling back to visible browser")
            console.print("[yellow]Token expirado — abriendo browser para re-autenticar...[/]")
            await _run(headless=False, timeout=180)
    else:
        console.print("[cyan]Browser abierto.[/] Inicia sesión si es necesario...")
        console.print("[dim]Esperando token de api.tidal.com...[/]")
        await _run(headless=False, timeout=180)

    if not captured:
        if not silent:
            console.print("[red]No se capturó ningún token.[/]")
        return None

    token = captured["token"]
    payload = _decode_jwt_payload(token)

    if not payload:
        if not silent:
            console.print("[red]Token inválido — no se pudo decodificar.[/]")
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
    Called automatically before downloads start.
    Refreshes the token silently if it expires within threshold_minutes.
    Returns True if a refresh was performed.
    """
    from tiddl.cli.utils.auth.core import load_auth_data

    auth = load_auth_data()
    if not auth.token:
        return False

    minutes_left = (auth.expires_at - time.time()) / 60
    if minutes_left > threshold_minutes:
        return False

    if not _session_exists():
        log.warning(f"Token expira en {minutes_left:.0f}min pero no hay sesión guardada — corre 'tiddl auth web-login'")
        return False

    log.info(f"Token expira en {minutes_left:.0f}min — auto-refresh...")
    console.print(f"[yellow]Token expira en {minutes_left:.0f} min — refrescando...[/]")

    auth_data = await _capture_token(silent=True)
    if auth_data:
        save_auth_data(auth_data)
        exp_dt = time.strftime("%H:%M", time.localtime(auth_data.expires_at))
        console.print(f"[green]Token renovado automáticamente (expira {exp_dt})[/]")
        return True

    console.print("[red]Auto-refresh falló — corre 'tiddl auth web-login' manualmente.[/]")
    return False


def web_login():
    """Login automático via browser — captura token de tidal.com."""
    console.print("[bold cyan]Abriendo browser para capturar token...[/]\n")

    auth_data = asyncio.run(_capture_token(silent=False))

    if not auth_data:
        raise typer.Exit(1)

    save_auth_data(auth_data)

    exp_dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(auth_data.expires_at))
    console.print(f"\n[bold green]Token capturado![/]")
    console.print(f"  Usuario: [cyan]{auth_data.user_id}[/]  País: [cyan]{auth_data.country_code}[/]")
    console.print(f"  Expira: [yellow]{exp_dt}[/]")
