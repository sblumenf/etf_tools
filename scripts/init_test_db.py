"""Create SQLite tables for manual testing. Run once before using CLI commands."""
import os

os.environ["DATABASE_URL"] = "sqlite:///test_etf.db"

from sqlalchemy import create_engine
from etf_pipeline.models import Base

engine = create_engine(os.environ["DATABASE_URL"])
Base.metadata.create_all(engine)
engine.dispose()
print("Created test_etf.db with all tables.")
