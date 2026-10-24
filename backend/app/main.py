import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.routes import health as health_router
from app.api.routes import auth as auth_router
from app.api.routes import applications as app_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="VIGILANT AI API",
    version="0.1.0",
    description="AI-Powered Application Validation and Regulatory Compliance Verification"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health_router.router, prefix="/api")
app.include_router(auth_router.router, prefix="/api/auth")
app.include_router(app_router.router, prefix="/api/applications", tags=["Applications"])

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception while processing request",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )

@app.get("/api/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "vigilant-ai-api"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
