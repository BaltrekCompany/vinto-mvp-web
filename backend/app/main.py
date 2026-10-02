from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import DatabaseUnavailable, check_database
from app.captures import router as captures_router

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)
app.include_router(captures_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Comprueba la API sin acceder a PostgreSQL."""
    return {"status": "ok"}


@app.get(
    "/api/health",
    responses={503: {"description": "PostgreSQL no disponible"}},
)
def api_health():
    """Psycopg síncrono corre en el thread pool de FastAPI."""
    try:
        check_database()
    except DatabaseUnavailable:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable"},
        )
    return {"status": "ok", "database": "ok"}
