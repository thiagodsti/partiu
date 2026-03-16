"""
Airport lookup routes.
"""

from fastapi import APIRouter, HTTPException

from ..database import db_conn

router = APIRouter(prefix='/api/airports', tags=['airports'])


@router.get('/{iata}')
def get_airport(iata: str):
    """Return airport info including coordinates."""
    with db_conn() as conn:
        row = conn.execute(
            'SELECT iata_code, name, city_name, country_code, latitude, longitude '
            'FROM airports WHERE iata_code = ?',
            (iata.upper(),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Airport not found')
    return dict(row)
