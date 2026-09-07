from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: se esperaba una coincidencia y hubo {text.count(old)}")
    return text.replace(old, new, 1)


def patch(root: Path) -> None:
    daemon = root / "stage8_daemon.py"
    installer = root / "stage8_install.sh"
    daemon_text = daemon.read_text(encoding="utf-8")
    if "ODDS_VALUE_SYNC_V1" not in daemon_text:
        daemon_text = replace_once(
            daemon_text,
            '    required_env = ["TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"]\n',
            '    required_env = ["TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "FIVE_DOLLAR_FOOTBALL_API_KEY"]\n',
            "variables del proveedor",
        )
        anchor = '    env["ODDSHUNTER_STAGE6_ALLOW_TURSO_WRITE"] = "1"\n'
        block = '''    # ODDS_VALUE_SYNC_V1: calcula una vez y publica el mismo documento para PC/Mobile.
    odds = run_streamed(
        "ODDS_VALUE",
        [py, "-u", str(ROOT / "five_dollar_odds_sync.py"), "--root", str(ROOT), "--days", "3", "--max-age-minutes", "45"],
        env,
        int(os.environ.get("ODDSHUNTER_ODDS_TIMEOUT_SECONDS", "900")),
    )
    if odds["returncode"] != 0:
        raise RuntimeError(f"Odds value rc={odds['returncode']}")

''' + anchor
        daemon_text = replace_once(daemon_text, anchor, block, "ejecución antes de publicar")
        daemon_text = replace_once(
            daemon_text,
            '        "stage6_process": s6,\n',
            '        "stage6_process": s6,\n        "odds_value_process": odds,\n',
            "estado del ciclo",
        )
    compile(daemon_text, str(daemon), "exec")
    daemon.write_text(daemon_text, encoding="utf-8", newline="\n")

    install_text = installer.read_text(encoding="utf-8")
    if "ODDS_VALUE_INSTALL_V1" not in install_text:
        install_text = replace_once(
            install_text,
            '[[ -n "${TURSO_AUTH_TOKEN:-}" ]] || { echo "TURSO_AUTH_TOKEN_EMPTY" >&2; exit 1; }\n',
            '[[ -n "${TURSO_AUTH_TOKEN:-}" ]] || { echo "TURSO_AUTH_TOKEN_EMPTY" >&2; exit 1; }\n[[ -n "${FIVE_DOLLAR_FOOTBALL_API_KEY:-}" ]] || { echo "FIVE_DOLLAR_FOOTBALL_API_KEY_EMPTY" >&2; exit 1; }\n',
            "validación de clave",
        )
        install_text = replace_once(
            install_text,
            'cp -a "$PKG_DIR/README_CLOUD_STAGE8.md" "$RELEASE/"\n',
            'cp -a "$PKG_DIR/README_CLOUD_STAGE8.md" "$RELEASE/"\n# ODDS_VALUE_INSTALL_V1\ncp -a "$BUNDLE_ROOT/odds_value_engine.py" "$RELEASE/"\ncp -a "$BUNDLE_ROOT/five_dollar_odds_sync.py" "$RELEASE/"\n',
            "instalación de módulos",
        )
        install_text = replace_once(
            install_text,
            'python3 -m py_compile "$RELEASE/stage8_daemon.py" "$RELEASE/stage8_health.py" "$RELEASE/cloud_stage6_publish.py"\n',
            'python3 -m py_compile "$RELEASE/stage8_daemon.py" "$RELEASE/stage8_health.py" "$RELEASE/cloud_stage6_publish.py" "$RELEASE/odds_value_engine.py" "$RELEASE/five_dollar_odds_sync.py"\n',
            "compilación de módulos",
        )
    installer.write_text(install_text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    patch(Path(sys.argv[1]).resolve())
    print("STAGE8_ODDS_PATCH=PASS")
