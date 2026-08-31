from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from vercel_backend_data_patch import patch_backend

USER_AGENT = "OddsHunter-Vercel-Source-Recover/1.0"
OLD_LABELS = ("Turso OK · solo lectura", "SQLite OK · solo lectura")
NEW_LABEL = "Datos actualizados en línea"
DETAIL_MARKER = "OH_MATCH_SUMMARY_FIXES_V11"
BALL_ASSET_NAME = "ball-3d-v10.png"
BRAND_ASSET_NAME = "oddshunter-brand-logo.png"
LEGACY_DETAIL_MARKERS = (
    "OH_MATCH_SUMMARY_REFERENCE_V2",
    "OH_MATCH_SUMMARY_EXACT_V3",
    "OH_MATCH_ICONS_3D_V4",
    "OH_MATCH_HEADER_SAFEAREA_V5",
    "OH_MATCH_REFINEMENTS_V6",
    "OH_MATCH_ICONS_CONTAINED_V7",
    "OH_MATCH_BALL_3D_V8",
    "OH_MATCH_BALL_SIZE_V9",
    "OH_MATCH_BALL_IMAGE_V10",
    DETAIL_MARKER,
)
ASSET_ROOT = Path(__file__).resolve().parent / "vercel_assets"


def api_request(token: str, team_id: str, path: str, params: dict[str, str] | None = None) -> tuple[bytes, str]:
    query = urllib.parse.urlencode({**(params or {}), "teamId": team_id})
    request = urllib.request.Request(
        f"https://api.vercel.com{path}?{query}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(16 * 1024 * 1024 + 1), str(response.headers.get("Content-Type") or "")


def decode_file_response(raw: bytes, content_type: str) -> bytes:
    if len(raw) > 16 * 1024 * 1024:
        raise RuntimeError("Vercel devolvió un archivo mayor de 16 MiB")
    if "json" not in content_type.lower() and not raw.lstrip().startswith((b"{", b"[")):
        return raw
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, str):
        return base64.b64decode(payload)
    if not isinstance(payload, dict):
        raise RuntimeError("Respuesta de archivo Vercel no reconocida")
    value: Any = payload.get("data", payload.get("content"))
    if not isinstance(value, str):
        raise RuntimeError(f"Respuesta de archivo Vercel sin contenido; claves={sorted(payload)}")
    encoding = str(payload.get("encoding") or "base64").lower()
    return base64.b64decode(value) if encoding == "base64" else value.encode("utf-8")


def safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise RuntimeError(f"Ruta Vercel insegura: {relative!r}")
    target = (root / Path(*pure.parts)).resolve()
    base = root.resolve()
    if base not in target.parents:
        raise RuntimeError(f"Ruta fuera del destino: {relative!r}")
    return target


def flatten(entries: list[dict[str, Any]], prefix: PurePosixPath = PurePosixPath()) -> list[tuple[str, str, str | None]]:
    found: list[tuple[str, str, str | None]] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        kind = str(entry.get("type") or "invalid")
        if not name or "/" in name or name in {".", ".."}:
            raise RuntimeError(f"Entrada Vercel inválida: {entry!r}")
        path = prefix / name
        if kind == "directory":
            children = entry.get("children") or []
            if not isinstance(children, list):
                raise RuntimeError(f"Directorio sin hijos válidos: {path}")
            found.extend(flatten(children, path))
        elif kind == "file":
            uid = entry.get("uid")
            if not isinstance(uid, str) or not uid:
                raise RuntimeError(f"Archivo sin uid: {path}")
            found.append((path.as_posix(), kind, uid))
        else:
            found.append((path.as_posix(), kind, None))
    return found


def patch_frontend(root: Path) -> dict[str, list[str]]:
    patched_backend = patch_backend(root)
    app_candidates = sorted(root.glob("**/assets/js/app.js"))
    if not app_candidates:
        raise RuntimeError("No se encontró assets/js/app.js en la fuente recuperada")
    patched_apps: list[str] = []
    for path in app_candidates:
        text = path.read_text(encoding="utf-8")
        original = text
        for old in OLD_LABELS:
            text = text.replace(old, NEW_LABEL)
        detail_js = (ASSET_ROOT / "match_summary_v2.js").read_text(encoding="utf-8")
        marker_positions = [text.find(f"/* {marker} */") for marker in LEGACY_DETAIL_MARKERS]
        marker_positions = [position for position in marker_positions if position >= 0]
        if marker_positions:
            text = text[: min(marker_positions)].rstrip()
        text = text.rstrip() + "\n\n" + detail_js.rstrip() + "\n"
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
        patched_apps.append(path.relative_to(root).as_posix())

    patched_styles: list[str] = []
    detail_css = (ASSET_ROOT / "match_summary_v2.css").read_text(encoding="utf-8")
    for path in sorted(root.glob("**/assets/css/app.css")):
        text = path.read_text(encoding="utf-8")
        original = text
        marker_positions = [text.find(f"/* {marker} */") for marker in LEGACY_DETAIL_MARKERS]
        marker_positions = [position for position in marker_positions if position >= 0]
        if marker_positions:
            text = text[: min(marker_positions)].rstrip()
        updated = text.rstrip() + "\n\n" + detail_css.rstrip() + "\n"
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
        patched_styles.append(path.relative_to(root).as_posix())
    if not patched_styles:
        raise RuntimeError("No se encontró assets/css/app.css")

    ball_source = ASSET_ROOT / "ball_3d_v10.png"
    if not ball_source.is_file():
        raise RuntimeError(f"No se encontró el balón 3D: {ball_source}")
    ball_bytes = ball_source.read_bytes()
    brand_source = ASSET_ROOT / "oddshunter_brand_logo.png"
    if not brand_source.is_file():
        raise RuntimeError(f"No se encontró el logo de OddsHunter: {brand_source}")
    brand_bytes = brand_source.read_bytes()
    patched_icons: list[str] = []
    for static_root in sorted({path.parents[2] for path in app_candidates}):
        target = static_root / "assets" / "icons" / BALL_ASSET_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != ball_bytes:
            target.write_bytes(ball_bytes)
        patched_icons.append(target.relative_to(root).as_posix())
        brand_target = static_root / "assets" / "icons" / BRAND_ASSET_NAME
        if not brand_target.is_file() or brand_target.read_bytes() != brand_bytes:
            brand_target.write_bytes(brand_bytes)
        patched_icons.append(brand_target.relative_to(root).as_posix())

    patched_indexes: list[str] = []
    for path in sorted(root.glob("**/index.html")):
        text = path.read_text(encoding="utf-8")
        updated = re.sub(r"app\.css\?v=[^\"']+", "app.css?v=1.14.0-home-compact", text)
        updated = re.sub(r"app\.js\?v=[^\"']+", "app.js?v=1.14.0-home-compact", updated)
        updated = re.sub(r"sw\.js\?v=[^\"']+", "sw.js?v=1.14.0-home-compact", updated)
        updated = re.sub(r'(<div class="logo-box"><img\s+)src="[^"]+"', rf'\1src="/assets/icons/{BRAND_ASSET_NAME}"', updated)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            patched_indexes.append(path.relative_to(root).as_posix())

    patched_workers: list[str] = []
    for path in sorted(root.glob("**/sw.js")):
        text = path.read_text(encoding="utf-8")
        updated = re.sub(r"oh-mobile-v[^\"']+", "oh-mobile-v1-14-0-home-compact", text)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            patched_workers.append(path.relative_to(root).as_posix())

    for path in app_candidates:
        text = path.read_text(encoding="utf-8")
        if any(old in text for old in OLD_LABELS) or NEW_LABEL not in text or DETAIL_MARKER not in text or "OH_EXPECTED_REAL_COMPARISON_V16" not in text:
            raise RuntimeError(f"El parche de frontend quedó incompleto en {path}")
    return {"backend": patched_backend, "app_js": patched_apps, "app_css": patched_styles, "icon_assets": patched_icons, "index_html": patched_indexes, "service_worker": patched_workers}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--team-id", default=os.environ.get("VERCEL_ORG_ID", ""))
    parser.add_argument("--token-env", default="VERCEL_TOKEN")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    team_id = str(args.team_id or "").strip()
    deployment_id = str(args.deployment_id or "").strip()
    if not token or not team_id or not deployment_id:
        raise SystemExit("Faltan token, team id o deployment id")

    raw_tree, content_type = api_request(
        token,
        team_id,
        f"/v6/deployments/{urllib.parse.quote(deployment_id, safe='')}/files",
    )
    if "json" not in content_type.lower() and not raw_tree.lstrip().startswith(b"["):
        raise RuntimeError("Vercel no devolvió un árbol JSON")
    tree = json.loads(raw_tree.decode("utf-8"))
    if not isinstance(tree, list):
        raise RuntimeError("El árbol de Vercel no es una lista")
    entries = flatten(tree)
    files = [(path, uid) for path, kind, uid in entries if kind == "file" and uid]
    if not files:
        raise RuntimeError("El despliegue no expone archivos fuente recuperables")

    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative, uid in files:
        raw, response_type = api_request(
            token,
            team_id,
            f"/v8/deployments/{urllib.parse.quote(deployment_id, safe='')}/files/{urllib.parse.quote(uid, safe='')}",
            {"path": relative},
        )
        target = safe_target(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decode_file_response(raw, response_type))

    patches = patch_frontend(root)
    safe_manifest = {
        "deployment_id": deployment_id,
        "file_count": len(files),
        "paths": [path for path, _ in files],
        "skipped_non_files": [path for path, kind, _ in entries if kind != "file"],
        "patches": patches,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(safe_manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"RECOVERED_SOURCE_FILES={len(files)}")
    print("RECOVERED_FRONTEND_LABEL_PATCH=PASS")
    for path in patches["app_js"]:
        print(f"PATCHED_APP_JS={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
