from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from etf_pipeline.api.deps import get_db
from etf_pipeline.api.schemas.etf import ETFSearchResult
from etf_pipeline.xray import service

router = APIRouter(prefix="/api/v1/etfs", tags=["etfs"])


@router.get("/search", response_model=list[ETFSearchResult])
def search_etfs(q: str = Query(default="", min_length=0), db: Session = Depends(get_db)):
    if not q.strip():
        return []
    results = service.search_etfs(db, q)
    return [ETFSearchResult(ticker=e.ticker, name=e.fund_name or "", cik=e.cik or "") for e in results]
