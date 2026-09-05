async def _meta(request):
    token, cid, mid = await _resolve(request)
    use_user = request.query.get("user") == "1"

    if use_user and not _us_check_auth(request):
        raise web.HTTPUnauthorized(
            text="user stream requires authentication",
            headers={"X-Stream-Auth-Required": "1"},
        )

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
    mime = info["mime"]
    info["playable"] = mime.startswith(_PLAYABLE)
    try:
        nav = await _neighbours(token)
    except Exception:
        nav = None
    if nav:
        info["playlist"] = nav
    return web.json_response(info)
