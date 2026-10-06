import psycopg
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.config import settings
from app.database import UNAVAILABLE_BODY, DatabaseUnavailable, check_database, logger
from app.captures import router as captures_router
from app.work_orders.errors import WorkOrderError
from app.work_orders.router import router as work_orders_router

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # cookie de sesión; los orígenes son explícitos, nunca "*"
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(captures_router)
app.include_router(auth_router)
app.include_router(work_orders_router)

UNAVAILABLE = UNAVAILABLE_BODY


@app.exception_handler(DatabaseUnavailable)
async def database_unavailable_handler(request: Request, error: DatabaseUnavailable):
    return JSONResponse(status_code=503, content=UNAVAILABLE)


@app.exception_handler(WorkOrderError)
async def work_order_error_handler(request: Request, error: WorkOrderError):
    """Mensaje público sin SQL. Los 422 de datos devuelven su detalle (texto propio); el resto, un mensaje genérico."""
    message = error.detail if error.http_status == 422 and error.detail else error.public_message
    return JSONResponse(status_code=error.http_status, content={"detail": message, "code": error.code})


@app.exception_handler(psycopg.Error)
async def postgres_error_handler(request: Request, error: psycopg.Error):
    # Solo el tipo: str(error) podría incluir SQL, la URL o datos de la consulta.
    logger.warning("PostgreSQL: error durante %s (%s)", request.url.path, type(error).__name__)
    return JSONResponse(status_code=503, content=UNAVAILABLE)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    """Los 422 de /api/auth/* no repiten la entrada (podría contener una contraseña); el resto conserva el formato de FastAPI."""
    if request.url.path.startswith("/api/auth/"):
        return JSONResponse(status_code=422, content={"detail": "Solicitud inválida"})
    return await request_validation_exception_handler(request, error)


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
