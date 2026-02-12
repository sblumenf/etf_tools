import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
EDGAR_IDENTITY = os.environ.get("EDGAR_IDENTITY", "")
