"""Prueba aislada de SofaScore para Google Colab.

Instalacion en una celda anterior de Colab:

    !pip -q install playwright
    !python -m playwright install --with-deps chromium

Ejecutar este archivo en un proceso separado (evita conflictos con el loop
asyncio de Jupyter/Colab):

    !python colab_sofascore_hybrid_test.py

Esta prueba NO escribe en oddshunter.db y NO intenta superar verificaciones.
Guarda unicamente JSON de diagnostico dentro de /content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import (
    APIResponse,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


DEFAULT_EVENT_IDS = [16283049]
SOFASCORE_ORIGIN = "https://www.sofascore.com"
FALLBACK_STATUSES = {401, 403, 404, 429}
REQUEST_TIMEOUT_MS = 30_000
PAGE_TIMEOUT_MS = 45_000

# Identidad conocida en el inventario local de OddsHunter. Si se prueba otro
# event_id, el script sigue funcionando, pero solo valida el ID y muestra la
# identidad encontrada.
EXPECTED_EVENTS: dict[int, dict[str, Any]] = {
    16283049: {
        "home_team": "Bologna",
        "away_team": "Lazio",
        "tournament_id": 23,
        "season_id": 95836,
    }
}

OUTPUT_ROOT = Path(
    os.environ.get("ODDSHUNTER_COLAB_OUTPUT", "/content/oddshunter_colab_test")
)
PROFILE_DIR = Path(
    os.environ.get(
        "ODDSHUNTER_COLAB_PROFILE",
        "/content/oddshunter_sofascore_profile",
    )
)

API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{SOFASCORE_ORIGIN}/",
}

CHALLENGE_MARKERS = (
    "verify you are human",
    "verification required",
    "access denied",
    "checking your browser",
    "just a moment",
    "captcha",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.stem}_",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def read_cached_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) and document else None


def endpoint_urls(event_id: int) -> dict[str, str]:
    base = f"{SOFASCORE_ORIGIN}/api/v1/event/{int(event_id)}"
    return {
        "event": base,
        "statistics": f"{base}/statistics",
        "shotmap": f"{base}/shotmap",
    }


def result_template(*, url: str, transport: str) -> dict[str, Any]:
    return {
        "url": url,
        "transport": transport,
        "ok": False,
        "status": None,
        "content_type": None,
        "json": None,
        "error": None,
        "attempts": [],
    }


async def response_document(response: APIResponse) -> tuple[str, dict[str, Any] | None]:
    text = await response.text()
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    return text, document if isinstance(document, dict) else None


async def direct_fetch(context: BrowserContext, url: str) -> dict[str, Any]:
    result = result_template(url=url, transport="direct")
    response: APIResponse | None = None
    try:
        response = await context.request.get(
            url,
            headers=API_HEADERS,
            timeout=REQUEST_TIMEOUT_MS,
            fail_on_status_code=False,
        )
        text, document = await response_document(response)
        result.update(
            {
                "ok": bool(response.ok and document is not None),
                "status": int(response.status),
                "content_type": response.headers.get("content-type"),
                "json": document,
                "body_preview": text[:500] if document is None else None,
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if response is not None:
            try:
                await response.dispose()
            except Exception:
                pass
    return result


async def browser_fetch(page: Page, url: str) -> dict[str, Any]:
    result = result_template(url=url, transport="browser")
    try:
        raw = await page.evaluate(
            """
            async ({url, timeoutMs}) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const response = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        cache: 'no-store',
                        signal: controller.signal,
                        headers: {
                            'Accept': 'application/json, text/plain, */*',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });
                    const text = await response.text();
                    let document = null;
                    try { document = JSON.parse(text); } catch (_) {}
                    return {
                        ok: response.ok && document !== null,
                        status: response.status,
                        contentType: response.headers.get('content-type'),
                        json: document,
                        bodyPreview: document === null ? text.slice(0, 500) : null
                    };
                } catch (error) {
                    return {
                        ok: false,
                        status: null,
                        error: String(error)
                    };
                } finally {
                    clearTimeout(timer);
                }
            }
            """,
            {"url": url, "timeoutMs": REQUEST_TIMEOUT_MS},
        )
        if not isinstance(raw, dict):
            result["error"] = "Brave/Chromium devolvio una respuesta invalida."
            return result
        document = raw.get("json")
        result.update(
            {
                "ok": bool(raw.get("ok") and isinstance(document, dict)),
                "status": raw.get("status"),
                "content_type": raw.get("contentType"),
                "json": document if isinstance(document, dict) else None,
                "body_preview": raw.get("bodyPreview"),
                "error": raw.get("error"),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def prepare_sofascore_page(page: Page) -> dict[str, Any]:
    health: dict[str, Any] = {
        "home_status": None,
        "final_url": page.url,
        "title": None,
        "challenge_detected": False,
        "challenge_markers": [],
        "error": None,
    }
    try:
        response = await page.goto(
            f"{SOFASCORE_ORIGIN}/",
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1_500)
        health["home_status"] = response.status if response else None
        health["final_url"] = page.url
        health["title"] = await page.title()
        try:
            body = (await page.locator("body").inner_text(timeout=5_000)).casefold()
        except Exception:
            body = ""
        markers = [marker for marker in CHALLENGE_MARKERS if marker in body]
        health["challenge_markers"] = markers
        health["challenge_detected"] = bool(markers)
    except Exception as exc:
        health["error"] = f"{type(exc).__name__}: {exc}"
        health["final_url"] = page.url
    return health


async def fetch_with_fallback(
    context: BrowserContext,
    page: Page,
    *,
    endpoint_name: str,
    url: str,
    cache_path: Path,
    browser_allowed: bool,
) -> dict[str, Any]:
    """Directo -> navegador inmediato -> cache, sin repetir un 403."""

    direct = await direct_fetch(context, url)
    attempts = [
        {
            "transport": "direct",
            "status": direct.get("status"),
            "ok": direct.get("ok"),
            "error": direct.get("error"),
        }
    ]
    if direct.get("ok"):
        direct["attempts"] = attempts
        atomic_write_json(cache_path, direct["json"])
        return direct

    direct_status = direct.get("status")
    should_use_browser = (
        browser_allowed
        and (
            direct_status in FALLBACK_STATUSES
            or direct_status is None
            or direct_status == 0
            or not direct.get("ok")
        )
    )
    if should_use_browser:
        browser = await browser_fetch(page, url)
        attempts.append(
            {
                "transport": "browser",
                "status": browser.get("status"),
                "ok": browser.get("ok"),
                "error": browser.get("error"),
            }
        )
        if browser.get("ok"):
            browser["attempts"] = attempts
            atomic_write_json(cache_path, browser["json"])
            return browser

    cached = read_cached_json(cache_path)
    if cached is not None:
        attempts.append(
            {
                "transport": "cache",
                "status": None,
                "ok": True,
                "error": None,
            }
        )
        result = result_template(url=url, transport="cache")
        result.update({"ok": True, "json": cached, "attempts": attempts})
        return result

    result = result_template(url=url, transport="unavailable")
    result.update(
        {
            "status": direct_status,
            "error": direct.get("error") or f"{endpoint_name} no disponible",
            "attempts": attempts,
        }
    )
    return result


def tournament_id(event: dict[str, Any]) -> int | None:
    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    value = unique.get("id") or tournament.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def season_id(event: dict[str, Any]) -> int | None:
    season = event.get("season") or {}
    try:
        value = season.get("id")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def validate_event_identity(event_id: int, document: dict[str, Any]) -> dict[str, Any]:
    event = document.get("event")
    if not isinstance(event, dict):
        return {
            "ok": False,
            "errors": ["La respuesta no contiene un objeto event."],
        }

    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    status = event.get("status") or {}
    home_score = event.get("homeScore") or {}
    away_score = event.get("awayScore") or {}
    actual = {
        "event_id": event.get("id"),
        "home_team_id": home.get("id"),
        "home_team": home.get("name"),
        "away_team_id": away.get("id"),
        "away_team": away.get("name"),
        "tournament_id": tournament_id(event),
        "season_id": season_id(event),
        "status": status.get("type"),
        "status_description": status.get("description"),
        "home_score": home_score.get("current"),
        "away_score": away_score.get("current"),
        "start_timestamp": event.get("startTimestamp"),
    }

    errors: list[str] = []
    try:
        actual_event_id = int(event.get("id"))
    except (TypeError, ValueError):
        actual_event_id = None
    if actual_event_id != int(event_id):
        errors.append(
            f"event_id incorrecto: esperado={event_id}, actual={actual_event_id}"
        )

    expected = EXPECTED_EVENTS.get(int(event_id))
    if expected:
        for side in ("home", "away"):
            expected_name = expected[f"{side}_team"]
            actual_name = actual[f"{side}_team"]
            if normalize_name(expected_name) != normalize_name(actual_name):
                errors.append(
                    f"{side} incorrecto: esperado={expected_name}, actual={actual_name}"
                )
        for field in ("tournament_id", "season_id"):
            if actual[field] != int(expected[field]):
                errors.append(
                    f"{field} incorrecto: esperado={expected[field]}, actual={actual[field]}"
                )

    return {
        "ok": not errors,
        "errors": errors,
        "expected": expected,
        "actual": actual,
    }


def endpoint_summary(name: str, result: dict[str, Any]) -> str:
    if result.get("ok"):
        return f"{name:12} PASS ({result.get('transport')})"
    return (
        f"{name:12} N/D "
        f"(HTTP {result.get('status')}, {result.get('error') or 'sin JSON'})"
    )


async def run_event(
    context: BrowserContext,
    page: Page,
    *,
    event_id: int,
    browser_allowed: bool,
) -> dict[str, Any]:
    print("\n" + "=" * 78)
    print(f"EVENT_ID={event_id}")
    print("=" * 78)

    event_dir = OUTPUT_ROOT / str(event_id)
    urls = endpoint_urls(event_id)
    results: dict[str, dict[str, Any]] = {}

    for name, url in urls.items():
        result = await fetch_with_fallback(
            context,
            page,
            endpoint_name=name,
            url=url,
            cache_path=event_dir / f"{name}.json",
            browser_allowed=browser_allowed,
        )
        results[name] = result
        print(endpoint_summary(name, result))

    event_result = results["event"]
    event_document = event_result.get("json")
    identity = (
        validate_event_identity(event_id, event_document)
        if isinstance(event_document, dict)
        else {"ok": False, "errors": ["No se obtuvo el JSON del evento."]}
    )

    event_available_from_cloud = bool(
        event_result.get("ok") and event_result.get("transport") in {"direct", "browser"}
    )
    event_available_from_cache = bool(
        event_result.get("ok") and event_result.get("transport") == "cache"
    )

    if event_available_from_cloud and identity.get("ok"):
        final_state = "PASS"
    elif event_available_from_cache and identity.get("ok"):
        final_state = "CACHE_ONLY"
    elif event_result.get("ok") and not identity.get("ok"):
        final_state = "IDENTITY_MISMATCH"
    else:
        final_state = "SOURCE_UNAVAILABLE"

    report = {
        "generated_at": utc_now(),
        "event_id": int(event_id),
        "final_state": final_state,
        "identity": identity,
        "endpoints": {
            name: {
                key: value
                for key, value in result.items()
                if key not in {"json", "body_preview"}
            }
            for name, result in results.items()
        },
        "required_endpoint": "event",
        "optional_endpoints": ["statistics", "shotmap"],
        "downstream_action": (
            "Continuar normalmente."
            if final_state == "PASS"
            else "Usar cache solo como diagnostico; no certifica acceso cloud."
            if final_state == "CACHE_ONLY"
            else "Rechazar por identidad; no guardar el partido."
            if final_state == "IDENTITY_MISMATCH"
            else "En OddsHunter real: continuar con Futbol24 y Flashscore."
        ),
    }
    atomic_write_json(event_dir / "report.json", report)

    print("IDENTITY   ", "PASS" if identity.get("ok") else "FAIL")
    if identity.get("actual"):
        actual = identity["actual"]
        print(
            "PARTIDO     ",
            f"{actual.get('home_team')} vs {actual.get('away_team')}",
        )
        print(
            "CONTEXTO    ",
            f"tournament={actual.get('tournament_id')} "
            f"season={actual.get('season_id')} status={actual.get('status')}",
        )
    for error in identity.get("errors", []):
        print("ERROR       ", error)
    print("RESULTADO   ", final_state)
    print("REPORTE     ", event_dir / "report.json")
    return report


async def run(event_ids: list[int], *, headed: bool = False) -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    session_report: dict[str, Any] = {
        "generated_at": utc_now(),
        "environment": "google_colab_test",
        "profile_dir": str(PROFILE_DIR),
        "output_root": str(OUTPUT_ROOT),
        "event_ids": event_ids,
        "page_health": {},
        "events": [],
    }

    print("=" * 78)
    print("ODDSHUNTER / SOFASCORE HYBRID COLAB TEST")
    print("=" * 78)
    print("Esta prueba no modifica SQLite y no intenta superar verificaciones.")

    async with async_playwright() as playwright:
        context: BrowserContext | None = None
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=not headed,
                locale="es-ES",
                viewport={"width": 1365, "height": 900},
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                ],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            page_health = await prepare_sofascore_page(page)
            session_report["page_health"] = page_health

            print("HOME HTTP   ", page_health.get("home_status"))
            print("FINAL URL   ", page_health.get("final_url"))
            print("TITLE       ", page_health.get("title"))
            if page_health.get("challenge_detected"):
                print(
                    "VERIFICACION",
                    page_health.get("challenge_markers"),
                    "- no se intentara superar.",
                )
            elif page_health.get("error"):
                print("HOME ERROR  ", page_health["error"])
            else:
                print("ORIGEN      PASS")

            browser_allowed = bool(
                not page_health.get("challenge_detected")
                and str(page.url).startswith(SOFASCORE_ORIGIN)
            )

            # Un fallo de un evento queda reportado y no impide probar el siguiente.
            for event_id in event_ids:
                try:
                    event_report = await run_event(
                        context,
                        page,
                        event_id=int(event_id),
                        browser_allowed=browser_allowed,
                    )
                except Exception as exc:
                    event_report = {
                        "generated_at": utc_now(),
                        "event_id": int(event_id),
                        "final_state": "TECHNICAL_ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    print(
                        f"EVENT_ID={event_id} TECHNICAL_ERROR: "
                        f"{event_report['error']}"
                    )
                session_report["events"].append(event_report)
        except PlaywrightTimeoutError as exc:
            session_report["fatal_error"] = f"PlaywrightTimeoutError: {exc}"
        except Exception as exc:
            session_report["fatal_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass

    states = [row.get("final_state") for row in session_report["events"]]
    session_report["completed_at"] = utc_now()
    session_report["summary"] = {
        "passed": states.count("PASS"),
        "cache_only": states.count("CACHE_ONLY"),
        "identity_mismatch": states.count("IDENTITY_MISMATCH"),
        "source_unavailable": states.count("SOURCE_UNAVAILABLE"),
        "technical_errors": states.count("TECHNICAL_ERROR"),
    }
    session_path = OUTPUT_ROOT / "session_report.json"
    atomic_write_json(session_path, session_report)

    print("\n" + "=" * 78)
    print("RESUMEN FINAL")
    print("=" * 78)
    print(json.dumps(session_report["summary"], ensure_ascii=False, indent=2))
    if session_report.get("fatal_error"):
        print("FATAL ERROR  ", session_report["fatal_error"])
    print("REPORTE     ", session_path)

    return 0 if states and all(state == "PASS" for state in states) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueba hibrida SofaScore para Google Colab."
    )
    parser.add_argument(
        "--event-id",
        action="append",
        type=int,
        dest="event_ids",
        help="Event ID; puede repetirse para probar varios partidos.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Ejecutar Chromium visible; usar con Xvfb en Linux CI.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    event_ids = list(dict.fromkeys(args.event_ids or DEFAULT_EVENT_IDS))
    return asyncio.run(
        run(event_ids, headed=bool(args.headed))
    )


if __name__ == "__main__":
    raise SystemExit(main())
