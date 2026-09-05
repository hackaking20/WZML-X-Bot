async def xstrm_page(token: str, request: Request):
    if not _SAFE_TOKEN.match(token or ""):
        raise HTTPException(status_code=404, detail="Unknown link")
    # Render template eagerly via Jinja2 (avoids TemplateResponse.body lazy issue)
    template = templates.get_template("stream.html")
    content = template.render({"request": request})
    # Inject stall_ui.js before </body>
    from pathlib import Path as _P
    js_path = _P(__file__).resolve().parent / "templates" / "stall_ui.js"
    if js_path.exists():
        js_code = js_path.read_text(encoding="utf-8")
        if "</body>" in content:
            inject = "<script>\n" + js_code + "\n</script>\n</body>"
            content = content.replace("</body>", inject, 1)
        else:
            content += "\n<script>\n" + js_code + "\n</script>\n"
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
