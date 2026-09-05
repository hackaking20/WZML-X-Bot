async def stream_proxy(
    token: str, request: Request, upstream_path: str, params: dict = None
):
    if not _SAFE_TOKEN.match(token or ""):
        raise HTTPException(status_code=404, detail="Unknown link")
    merged_params = dict(params or {})
    if request.query_params.get("user") == "1":
        merged_params["user"] = "1"
    auth_val = request.query_params.get("auth")
    if auth_val:
        merged_params["auth"] = auth_val
    headers = {}
    rng = request.headers.get("range")
    if rng:
        headers["Range"] = rng
    if inm := request.headers.get("if-range"):
        headers["If-Range"] = inm
    headers["X-Viewer"] = _client_ip(request)
    try:
        upstream = await http_session.request(
            request.method,
            f"{STREAM_BASE}{upstream_path}/{token}",
            headers=headers,
            params=merged_params if merged_params else None,
            allow_redirects=False,
        )
    except ClientError as e:
        raise _stream_offline() from e
    out = {
        k: v for k, v in upstream.headers.items() if k.lower() not in _HOP
    }
    out.setdefault("Accept-Ranges", "bytes")
    out.setdefault("Cache-Control", "private, max-age=86400, immutable")
    out["Referrer-Policy"] = "no-referrer"
    out["X-Content-Type-Options"] = "nosniff"
    if request.method == "HEAD" or upstream.status in (204, 304, 416):
        body = await upstream.read()
        upstream.release()
        return Response(
            content=body if request.method != "HEAD" else b"",
            status_code=upstream.status,
            headers=out,
        )
    async def _pump():
        try:
            async for chunk in upstream.content.iter_chunked(262144):
                yield chunk
        finally:
            upstream.release()
    return StreamingResponse(_pump(), status_code=upstream.status, headers=out)
