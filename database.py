# ==============================================================================
# DATABASE SESSION MANAGEMENT
# ==============================================================================
# This module is responsible for creating and managing database sessions.
# It provides a dependency (`get_db`) that can be injected into API endpoints
# to ensure that each request gets a dedicated database session that is
# properly closed after the request is complete.
# ------------------------------------------------------------------------------

# --- Imports ---
# SessionLocal is the factory for creating new database session objects.
from models import SessionLocal

def get_db():
    """
    FastAPI dependency to provide a database session per request.

    This function is a generator that yields a database session. The `yield`
    statement passes the session to the calling function (the API endpoint).
    The `try...finally` block ensures that the database session is *always*
    closed, even if an error occurs during the request. This prevents

    database connection leaks.

    Yields:
        sqlalchemy.orm.Session: The database session object for the request.
    """
    # Create a new session from our factory.
    db = SessionLocal()
    try:
        # Yield the session to the endpoint. The code in the endpoint will
        # execute at this point.
        yield db
    finally:
        # After the endpoint has finished its work (or if an error occurred),
        # this block will execute, closing the session.
        db.close()
