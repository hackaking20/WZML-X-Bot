

@app.post("/api/stream_auth")
async def stream_auth_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    password = _us_get_pass()
    if not password:
        return JSONResponse({"error": "STREAM_PASS not set"}, status_code=200)
    submitted = body.get("password", "")
    if not submitted or not _us_hmac.compare_digest(submitted, password):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    token = _us_sign(password)
    return JSONResponse({"token": token, "expires": 86400})

# Start health checker on app startup
@app.on_event("startup")
async def _us_startup():
    try:
        _us_start_health()
    except Exception as e:
        LOGGER.warning(f"user_stream: health check failed to start: {e}")

