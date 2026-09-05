async def _serve(request, kind):
    _, cid, mid = await _resolve(request)
    inline = kind == "playback"
    viewer = request.headers.get("X-Viewer") or request.remote
    use_user = request.query.get("user") == "1"

    if use_user and not _us_check_auth(request):
        raise web.HTTPUnauthorized(
            text="user stream requires authentication",
            headers={"X-Stream-Auth-Required": "1"},
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
            if not use_user:
                raise web.HTTPNotFound(text="file is gone", headers={"X-Stream-Retry": "1"}) from None
            raise web.HTTPNotFound(text="file is gone") from None
        except NoClientAvailable as e:
            if not use_user:
                raise web.HTTPServiceUnavailable(text=str(e), headers={"X-Stream-Retry": "1"}) from None
            raise web.HTTPServiceUnavailable(text=str(e)) from None
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
        if not use_user:
            raise web.HTTPNotFound(text="file is gone", headers={"X-Stream-Retry": "1"}) from None
        raise web.HTTPNotFound(text="file is gone") from None
    except NoClientAvailable as e:
        if not use_user:
            raise web.HTTPServiceUnavailable(text=str(e), headers={"Retry-After": "10", "X-Stream-Retry": "1"}) from None
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
