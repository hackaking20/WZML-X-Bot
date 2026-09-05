async def stream_meta(token: str, request: Request):
    if not _SAFE_TOKEN.match(token or ""):
        raise HTTPException(status_code=404, detail="Unknown link")
    meta_params = {}
    if request.query_params.get("user") == "1":
        meta_params["user"] = "1"
    auth_val = request.query_params.get("auth")
    if auth_val:
        meta_params["auth"] = auth_val
    try:
        async with http_session.get(
            f"{STREAM_BASE}/_meta/{token}", params=meta_params or None
        ) as upstream:
            body = await upstream.read()
            status = upstream.status
    except ClientError as e:
        raise _stream_offline() from e
    return Response(
        content=body,
        status_code=status,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
