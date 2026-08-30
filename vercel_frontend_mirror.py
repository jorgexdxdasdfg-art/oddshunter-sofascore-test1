from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

USER_AGENT = "OddsHunter-Vercel-Frontend-Mirror/1.0"
OLD_LABELS = ("Turso OK · solo lectura", "SQLite OK · solo lectura")
NEW_LABEL = "Datos actualizados en línea"


def clean_path(value: str) -> str | None:
    raw = str(value or "").strip().strip("'\"")
    if not raw or raw.startswith(("data:", "mailto:", "javascript:", "#", "//")):
        return None
    split = urllib.parse.urlsplit(raw)
    if split.scheme or split.netloc or not split.path.startswith("/"):
        return None
    path = split.path
    if path.startswith("/api/") or path == "/api":
        return None
    if path.endswith("/") and path != "/":
        return None
    return path


def output_path(root: Path, url_path: str) -> Path:
    if url_path == "/":
        return root / "index.html"
    relative = url_path.lstrip("/")
    target = (root / relative).resolve()
    base = root.resolve()
    if target != base and base not in target.parents:
        raise RuntimeError(f"Ruta fuera del mirror: {url_path}")
    return target


def fetch(base: str, path: str) -> tuple[bytes, str]:
    url = urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise RuntimeError(f"Archivo demasiado grande: {path}")
        return data, str(response.headers.get("Content-Type") or "")


def discover(path: str, data: bytes, content_type: str) -> set[str]:
    if not any(token in content_type.lower() for token in ("text", "json", "javascript", "manifest")):
        return set()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return set()
    values: set[str] = set()
    patterns = (
        r'''(?:src|href)=["']([^"']+)["']''',
        r'''url\(\s*["']?([^)'"\s]+)''',
        r'''["'](/(?:assets|icons|manifest|sw)[^"']*)["']''',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            found = clean_path(raw)
            if found:
                values.add(found)
    if path in {"/manifest.json", "/manifest.webmanifest"}:
        try:
            manifest = json.loads(text)
            for icon in manifest.get("icons", []):
                found = clean_path(icon.get("src")) if isinstance(icon, dict) else None
                if found:
                    values.add(found)
        except Exception:
            pass
    return values


def patch_text(path: str, data: bytes) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    if path.endswith("/app.js") or path == "/assets/js/app.js":
        for old in OLD_LABELS:
            text = text.replace(old, NEW_LABEL)
    if path == "/":
        text = re.sub(
            r"app\.js\?v=[^\"']+",
            "app.js?v=1.5.3-live-status",
            text,
        )
        text = re.sub(
            r"sw\.js\?v=[^\"']+",
            "sw.js?v=1.5.3-live-status",
            text,
        )
    if path == "/sw.js":
        text = text.replace(
            "oh-mobile-v1-5-1-cloud-reality-crests",
            "oh-mobile-v1-5-3-live-status",
        )
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)

    queue = deque(["/", "/manifest.json", "/sw.js"])
    seen: set[str] = set()
    saved: list[str] = []
    while queue:
        path = queue.popleft()
        if path in seen or len(seen) >= 100:
            continue
        seen.add(path)
        try:
            data, content_type = fetch(args.base, path)
        except urllib.error.HTTPError as exc:
            if path in {"/", "/manifest.json", "/sw.js"}:
                raise
            print(f"MIRROR_SKIP_HTTP path={path} status={exc.code}")
            continue
        for found in sorted(discover(path, data, content_type)):
            if found not in seen:
                queue.append(found)
        patched = patch_text(path, data)
        target = output_path(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched)
        saved.append(path)

    required = {
        "/": root / "index.html",
        "/manifest.json": root / "manifest.json",
        "/sw.js": root / "sw.js",
        "/assets/js/app.js": root / "assets" / "js" / "app.js",
        "/assets/css/app.css": root / "assets" / "css" / "app.css",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Mirror incompleto: {missing}")
    app_text = required["/assets/js/app.js"].read_text(encoding="utf-8")
    if NEW_LABEL not in app_text or any(old in app_text for old in OLD_LABELS):
        raise RuntimeError("La etiqueta del frontend no quedó reemplazada")
    print(f"MIRROR_FILES={len(saved)}")
    print("FRONTEND_LABEL_PATCH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
