from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.exceptions import AppError
from app.routers import analytics, documents, feedback, organizations, query

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Coverage Q&A Service",
    description=(
        "Multi-tenant coverage document Q&A for DME companies. Upload coverage "
        "PDFs per organization, ask natural-language questions, and get grounded, "
        "trust-checkable answers backed by retrieval + citations."
    ),
    version="0.1.0",
)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(organizations.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(feedback.router)
app.include_router(analytics.router)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


# Mounted last so it only catches requests that don't match an API route
# above - serves the frontend (index.html, app.js, styles.css).
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
