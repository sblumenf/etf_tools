from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from etf_pipeline.api.routes import etf, xray


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="ETF X-Ray API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(etf.router)
app.include_router(xray.router)


@app.get("/health")
def health():
    return {"status": "ok"}
