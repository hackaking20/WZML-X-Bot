@app.get("/health")
async def health_check():
    return {"bot_responding": True, "status": "ok"}

# Start health checker on app startup
@app.on_event("startup")
async def _us_startup():
    try:
        _us_start_health()
    except Exception as e:
        LOGGER.warning(f"user_stream: health check failed to start: {e}")
