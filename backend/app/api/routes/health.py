import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/ready", tags=["Health"])
async def database_ready(db: Session = Depends(get_db)):
    """
    Check if the database is reachable and responsive.
    """
    try:
        # Execute a simple query to verify connectivity
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception:
        # We return 503 Service Unavailable if DB is down
        logger.exception("Database readiness check failed")
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
