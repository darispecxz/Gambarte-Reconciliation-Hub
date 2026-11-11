from fastapi import FastAPI
from app.api.routes import router
from app.core.config import get_settings

production = get_settings().environment != "development"
app = FastAPI(title="Gambarte Reconciliation Hub", version="0.1.0",
              docs_url=None if production else "/docs",
              openapi_url=None if production else "/openapi.json",
              redoc_url=None)
app.include_router(router)
