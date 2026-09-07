async def _serve(request, kind):
    _, cid, mid = await _resolve(request)
    inline = kind == "playback"
    viewer = request.headers.get("X-Viewer") or request.remote
    use_user = request.query.get("user") == "1"

    def _retry_url():
        p, qs = request.path, request.query_string
        # Strip leading underscore: aiohttp internal path is /_dl/TOKEN
        # but FastAPI public route is /dl/TOKEN
        if p.startswith("/_"):
            p = "/" + p[2:]
        if not qs:
            return p + "?user=1"
        if "user=" in qs:
            return p + "?" + qs
        return p + "?" + qs + "&user=1"

    def _dl_error_html(title, msg):
        return web.Response(
            text=(
                '<!DOCTYPE html><html><head><meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
                '<title>' + title + ' &mdash; WZML-X</title>'
                '<style>'
                '*{box-sizing:border-box;margin:0;padding:0}'
                'body{background:#0a0a0a;color:#e0e0e0;font-family:system-ui,-apple-system,sans-serif;'
                'display:flex;align-items:center;justify-content:center;min-height:100vh}'
                '.box{text-align:center;max-width:420px;padding:32px 24px}'
                '.box h2{color:#ff6b6b;font-size:20px;margin-bottom:10px}'
                '.box p{color:#888;font-size:14px;line-height:1.5;margin-bottom:24px}'
                '.btn{display:inline-block;padding:12px 28px;border-radius:8px;text-decoration:none;'
                'font-weight:600;font-size:14px;transition:all .2s}'
                '.btn-retry{background:rgba(255,165,0,.12);border:1px solid rgba(255,165,0,.4);color:#ffa500}'
                '.btn-retry:hover{background:rgba(255,165,0,.22)}'
                '.btn-back{background:rgba(93,157,255,.12);border:1px solid rgba(93,157,255,.4);color:#5b9dff;margin-top:12px}'
                '.btn-back:hover{background:rgba(93,157,255,.22)}'
                '</style></head><body><div class="box">'
                '<h2>&#9888; ' + title + '</h2>'
                '<p>' + msg + '</p>'
                '<a class="btn btn-retry" href="' + _retry_url() + '">Download with user account (Risky)</a>'
                '<br><a class="btn btn-back" href="/">Back to WZML-X</a>'
                '</div></body></html>'
            ),
            content_type="text/html",
            status=404,
            headers={"Cache-Control": "no-store"},
        )

    if request.method == "HEAD":
        try:
            if use_user:
                info = await probe_user(cid, mid)
            else:
                info = await probe(cid, mid)
        except StreamGone:
            purge_fid(cid, mid)
            if use_user:
                purge_fid_user(cid, mid)
            raise web.HTTPNotFound(text="file is gone") from None
        except NoClientAvailable as e:
            raise web.HTTPServiceUnavailable(text=str(e), headers={"Retry-After": "10"}) from None
        return web.Response(
            status=200,
            headers={
                "Content-Length": str(info["size"]),
                "Content-Type": info["mime"] or "application/octet-stream",
                "Accept-Ranges": "bytes",
                "Content-Disposition": _disposition(info["name"], inline),
                "Cache-Control": "private, max-age=86400, immutable",
                "ETag": f'"{info["unique_id"]}"',
            },
        )

    try:
        if use_user:
            st = await open_stream_user(cid, mid, kind, viewer=viewer)
        else:
            st = await open_stream(cid, mid, kind, viewer=viewer)
    except StreamGone:
        purge_fid(cid, mid)
        if use_user:
            purge_fid_user(cid, mid)
        if not use_user and not inline:
            return _dl_error_html("File is gone", "The file is no longer available via the bot account. You can try downloading it with your personal Telegram account.")
        raise web.HTTPNotFound(text="file is gone") from None
    except NoClientAvailable as e:
        if not use_user and not inline:
            return _dl_error_html("No bot available", "No bot client is currently available to serve this file. You can try downloading it with your personal Telegram account.")
        raise web.HTTPServiceUnavailable(text=str(e), headers={"Retry-After": "10"}) from None
    except StreamAbort as e:
        raise web.HTTPBadGateway(text=str(e)) from None

    rng = parse_range(request.headers.get("Range"), st.size)
    if rng is None:
        await st._release()
        return web.Response(
            status=416,
            headers={
                "Content-Range": f"bytes */{st.size}",
                "Accept-Ranges": "bytes",
                "Content-Length": "0",
            },
        )
    partial = rng is not FULL
    start, end = rng if partial else (0, st.size - 1)

    headers = {
        "Content-Type": st.mime or "application/octet-stream",
        "Content-Length": str(end - start + 1),
        "Accept-Ranges": "bytes",
        "Content-Disposition": _disposition(st.name, inline),
        "Cache-Control": "private, max-age=86400, immutable",
    }
    if st.unique_id:
        headers["ETag"] = f'"{st.unique_id}"'
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{st.size}"

    resp = web.StreamResponse(status=206 if partial else 200, headers=headers)
    resp.enable_compression(False)
    await resp.prepare(request)

    gen = st.iter_range(start, end)
    try:
        async for piece in gen:
            await resp.write(piece)
        await resp.write_eof()
    except (ConnectionResetError, ConnectionError, CancelledError):
        LOGGER.debug(f"stream aborted by client: {cid}/{mid}")
    except StreamGone:
        purge_fid(cid, mid)
        if use_user:
            purge_fid_user(cid, mid)
    except StreamAbort as e:
        LOGGER.error(f"stream failed {cid}/{mid}: {e}")
    finally:
        await gen.aclose()
    return resp
