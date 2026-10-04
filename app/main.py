import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import check_and_recover_database, create_daily_backup, init_db
from app.routes import router
from app.logger import configure_logging, CorrelationIdMiddleware, get_correlation_id
from app.network_guard import LoopbackOnlyMiddleware

# Configure structured JSON logging on load
configure_logging()
logger = logging.getLogger("autoro.app")


def run_startup_tasks() -> None:
    recovery_status = check_and_recover_database()
    init_db()
    backup_path = create_daily_backup()
    logger.info("Database startup status=%s backup=%s", recovery_status, backup_path)

    # Storage cleanup is deliberately non-blocking so the local UI can open promptly.
    from app.cleanup import run_auto_cleanup

    threading.Thread(target=run_auto_cleanup, daemon=True).start()

    from app import database

    with database.get_db() as conn:
        conn.execute(
            "UPDATE advisor_translation_queue "
            "SET status = 'failed', error = 'Interrupted by server restart' "
            "WHERE status = 'translating'"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_startup_tasks()
    yield


app = FastAPI(title="AutoRO Communication Layer", lifespan=lifespan)

# Register correlation ID tracking middleware
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(LoopbackOnlyMiddleware)

# Global unhandled exception handler to catch and log errors securely
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception occurred: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "correlation_id": get_correlation_id()
        }
    )

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
