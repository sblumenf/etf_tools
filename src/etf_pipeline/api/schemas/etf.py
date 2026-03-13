from pydantic import BaseModel


class ETFSearchResult(BaseModel):
    ticker: str
    name: str
    cik: str
