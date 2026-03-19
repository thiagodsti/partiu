"""
Airport lookup routes.
"""

from fastapi import APIRouter, HTTPException

from ..database import db_conn

router = APIRouter(prefix="/api/airports", tags=["airports"])


@router.get("/search")
def search_airports(q: str = "", limit: int = 10):
    """Search airports by IATA code prefix, name, or city (max 10 results)."""
    q = q.strip()
    if not q:
        return []
    pattern = f"%{q}%"
    prefix = f"{q}%"
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT iata_code, name, city_name, country_code
            FROM airports
            WHERE iata_code LIKE ? OR name LIKE ? OR city_name LIKE ?
            ORDER BY
                CASE WHEN upper(iata_code) = upper(?) THEN 0
                     WHEN upper(iata_code) LIKE upper(?) THEN 1
                     ELSE 2 END,
                iata_code
            LIMIT ?
            """,
            (prefix, pattern, pattern, q, prefix, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{iata}")
def get_airport(iata: str):
    """Return airport info including coordinates."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT iata_code, name, city_name, country_code, latitude, longitude "
            "FROM airports WHERE iata_code = ?",
            (iata.upper(),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Airport not found")
    return dict(row)
