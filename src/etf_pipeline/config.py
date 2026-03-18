import os
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    logger.warning("DATABASE_URL is not set. See .env.example for configuration.")

EDGAR_IDENTITY = os.environ.get("EDGAR_IDENTITY", "etf-pipeline admin@example.com")
