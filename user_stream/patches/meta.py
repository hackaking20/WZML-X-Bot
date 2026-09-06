async def _meta(request):
    token, cid, mid = await _resolve(request)

    # Always try user account first, fall back to bot clients
    try:
        info = await probe_user(cid, mid)
    except StreamGone:
        # User account can't find it — try bot clients
        try:
            info = await probe(cid, mid)
        except StreamGone:
            purge_fid(cid, mid)
            purge_fid_user(cid, mid)
            raise web.HTTPNotFound(text="file is gone") from None
        except NoClientAvailable as e:
            raise web.HTTPServiceUnavailable(text=str(e)) from None
    except NoClientAvailable:
        # User account not configured — try bot clients
        try:
            info = await probe(cid, mid)
        except StreamGone:
            purge_fid(cid, mid)
            raise web.HTTPNotFound(text="file is gone") from None
        except NoClientAvailable as e:
            raise web.HTTPServiceUnavailable(text=str(e)) from None
    except Exception:
        # Any other error — try bot clients as fallback
        try:
            info = await probe(cid, mid)
        except StreamGone:
            purge_fid(cid, mid)
            raise web.HTTPNotFound(text="file is gone") from None
        except NoClientAvailable as e:
            raise web.HTTPServiceUnavailable(text=str(e)) from None

    mime = info["mime"]
    info["playable"] = mime.startswith(_PLAYABLE)
    try:
        nav = await _neighbours(token)
    except Exception as e:
        LOGGER.debug(f"playlist nav unavailable for {token}: {e}")
        nav = None
    if nav:
        info["playlist"] = nav
    return web.json_response(info)