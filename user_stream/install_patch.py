#!/usr/bin/env python3
"""
install_patch.py — Build-time / boot-time patcher for WZML-X user-account streaming.

Run after update.py pulls upstream code:
    python3 user_stream/install_patch.py /usr/src/app

Or during Docker build:
    RUN python3 /app/user_stream/install_patch.py /app

Patches are idempotent — running twice is safe.
"""

import sys
from pathlib import Path


def main():
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    if not (repo / "bot" / "core").is_dir():
        print(f"ERROR: {repo} does not look like a WZML-X repo (no bot/core/)")
        sys.exit(1)

    print(f"=== Patching WZML-X at {repo} ===")
    copy_module(repo)
    copy_stall_ui(repo)
    patch_config(repo)
    patch_stream_server(repo)
    patch_wserver(repo)
    patch_config_load_dict(repo)
    print("=== All patches applied successfully ===")


def copy_module(repo):
    src = Path(__file__).resolve().parent / "user_stream_module.py"
    dst = repo / "bot" / "helper" / "user_stream_module.py"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [ok] Copied user_stream_module.py -> {dst}")


def copy_stall_ui(repo):
    src = Path(__file__).resolve().parent / "stall_ui.js"
    dst = repo / "web" / "templates" / "stall_ui.js"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [ok] Copied stall_ui.js -> {dst}")


def patch_config(repo):
    f = repo / "bot" / "core" / "config_manager.py"
    content = f.read_text(encoding="utf-8")
    if "STREAM_PASS" in content:
        print("  [skip] config_manager.py already has STREAM_PASS")
        return
    marker = "    DISABLE_STREAM = False\n"
    insertion = (
        "    DISABLE_STREAM = False\n"
        '    STREAM_PASS = ""\n'
        "    STREAM_DEBUG = False\n"
        "    STREAM_HEALTH_INTERVAL = 1800\n"
    )
    content = content.replace(marker, insertion, 1)
    f.write_text(content, encoding="utf-8")
    print("  [ok] Patched config_manager.py — added STREAM_PASS, STREAM_DEBUG, STREAM_HEALTH_INTERVAL")


def patch_stream_server(repo):
    f = repo / "bot" / "core" / "stream_server.py"
    content = f.read_text(encoding="utf-8")
    if "# USER_STREAM_PATCHED" in content:
        print("  [skip] stream_server.py already patched")
        return

    # Add import after tg_stream import block
    import_marker = "from ..helper.telegram_helper.tg_stream import ("
    if import_marker in content:
        import_end = content.find(")", content.find(import_marker))
        new_import = (
            "\nfrom ..helper.user_stream_module import (\n"
            "    open_stream_user,\n"
            "    probe_user,\n"
            "    purge_fid_user,\n"
            "    check_auth as _us_check_auth,\n"
            ")\n"
            "# USER_STREAM_PATCHED"
        )
        content = content[:import_end + 1] + new_import + content[import_end + 1:]

    # Replace _serve function
    old_serve_start = content.find("async def _serve(request, kind):")
    old_serve_end = content.find("\n\nasync def _stream(")
    if old_serve_start < 0 or old_serve_end < 0:
        print("  [ERROR] Could not find _serve function boundaries")
        return
    content = content[:old_serve_start] + _NEW_SERVE + content[old_serve_end:]

    # Replace _meta function
    old_meta_start = content.find("async def _meta(request):")
    old_meta_end = content.find("\n\nasync def _serve(")
    if old_meta_start < 0 or old_meta_end < 0:
        print("  [ERROR] Could not find _meta function boundaries")
        return
    content = content[:old_meta_start] + _NEW_META + content[old_meta_end:]

    f.write_text(content, encoding="utf-8")
    print("  [ok] Patched stream_server.py — _serve() and _meta() with ?user=1 routing")


def patch_wserver(repo):
    f = repo / "web" / "wserver.py"
    content = f.read_text(encoding="utf-8")
    if "# USER_STREAM_PATCHED" in content:
        print("  [skip] wserver.py already patched")
        return

    # Add import
    import_marker = "from aiohttp import ClientSession"
    if import_marker in content:
        us_import = (
            import_marker +
            "\nfrom bot.helper.user_stream_module import ("
            "\n    _get_stream_pass as _us_get_pass,"
            "\n    _sign_token as _us_sign,"
            "\n    _verify_token as _us_verify,"
            "\n    start_health_check as _us_start_health,"
            "\n    get_last_result as _us_health_result,"
            "\n)"
            "\nimport hmac as _us_hmac"
            "\n# USER_STREAM_PATCHED"
        )
        content = content.replace(import_marker, us_import, 1)

    # Replace stream_proxy
    old_proxy_start = content.find("async def stream_proxy(")
    old_proxy_end = content.find('\n\n@app.api_route("/stream/')
    if old_proxy_start < 0 or old_proxy_end < 0:
        print("  [ERROR] Could not find stream_proxy boundaries")
        return
    content = content[:old_proxy_start] + _NEW_PROXY + content[old_proxy_end:]

    # Replace stream_meta
    old_smeta_start = content.find("async def stream_meta(")
    old_smeta_end = content.find("\n\n@app.exception_handler")
    if old_smeta_start < 0 or old_smeta_end < 0:
        print("  [ERROR] Could not find stream_meta boundaries")
        return
    content = content[:old_smeta_start] + _NEW_SMETA + content[old_smeta_end:]

    # Replace xstrm_page
    old_xstrm_start = content.find("async def xstrm_page(")
    old_xstrm_end = content.find('\n\n@app.get("/api/stream/')
    if old_xstrm_start < 0 or old_xstrm_end < 0:
        print("  [ERROR] Could not find xstrm_page boundaries")
        return
    content = content[:old_xstrm_start] + _NEW_XSTRM + content[old_xstrm_end:]

    # Add /api/stream_auth route + health startup
    exc_idx = content.find("@app.exception_handler")
    if exc_idx >= 0:
        content = content[:exc_idx] + _AUTH_ROUTE + content[exc_idx:]

    f.write_text(content, encoding="utf-8")
    print("  [ok] Patched wserver.py — stream_proxy, stream_meta, xstrm_page, /api/stream_auth, health startup")


def patch_config_load_dict(repo):
    f = repo / "bot" / "core" / "config_manager.py"
    content = f.read_text(encoding="utf-8")
    if "# USER_STREAM_BASEURL_GUARD" in content:
        print("  [skip] config_manager.py load_dict already guarded")
        return

    marker = "    @classmethod\n    def load_dict(cls, config_dict):"
    if marker not in content:
        print("  [WARN] Could not find load_dict in config_manager.py")
        return

    validation_marker = '        for key in ["BOT_TOKEN"'
    val_idx = content.find(validation_marker, content.find(marker))
    if val_idx < 0:
        print("  [WARN] Could not find validation block in load_dict")
        return

    guard = (
        "        # USER_STREAM_BASEURL_GUARD\n"
        '        _current_base = getattr(cls, "BASE_URL", "") or ""\n'
        '        _new_base = getattr(cls, "BASE_URL", "") or ""\n'
        '        if "trycloudflare.com" in _new_base and "trycloudflare.com" not in _current_base and _current_base:\n'
        "            cls.BASE_URL = _current_base\n"
        '            LOGGER.info(f"config_manager: keeping stable BASE_URL={_current_base}, ignoring MongoDB value={_new_base}")\n'
    )

    content = content[:val_idx] + guard + content[val_idx:]
    f.write_text(content, encoding="utf-8")
    print("  [ok] Patched config_manager.py — BASE_URL guard in load_dict()")


# ═════════════════════════════════════════════════════════════════
# Replacement function bodies (loaded from external files to avoid
# quoting issues with f-strings inside triple-quoted strings)
# ═════════════════════════════════════════════════════════════════

def _load_template(name):
    p = Path(__file__).resolve().parent / "patches" / name
    return p.read_text(encoding="utf-8")


_NEW_SERVE = None
_NEW_META = None
_NEW_PROXY = None
_NEW_SMETA = None
_NEW_XSTRM = None
_AUTH_ROUTE = None


def _init_templates():
    global _NEW_SERVE, _NEW_META, _NEW_PROXY, _NEW_SMETA, _NEW_XSTRM, _AUTH_ROUTE
    _NEW_SERVE = _load_template("serve.py")
    _NEW_META = _load_template("meta.py")
    _NEW_PROXY = _load_template("proxy.py")
    _NEW_SMETA = _load_template("smeta.py")
    _NEW_XSTRM = _load_template("xstrm.py")
    _AUTH_ROUTE = _load_template("auth_route.py")


_init_templates()


if __name__ == "__main__":
    main()
