from app.db.session import engine
from sqlalchemy import text

def check():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print(f"Connectivity check: SUCCESS ({result.scalar()})")
    except Exception as e:
        print(f"Connectivity check: FAILED - {type(e).__name__}")
        exit(1)

if __name__ == "__main__":
    check()
