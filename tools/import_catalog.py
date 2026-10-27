#!/usr/bin/env python3
"""Validate a source-stamped station catalog; apply atomically only with --apply.

This validates structure, not the truth of the supplied source data. No station
adjacency, TOPIS identifier or facility position is guessed from station names.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import uuid
from typing import Any
from urllib.parse import urlparse


def text(value: Any, field: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'Invalid {field}')
    return value


def source(record: dict[str, Any]) -> None:
    url = urlparse(text(record.get('sourceUrl'), 'sourceUrl', 2000))
    if url.scheme != 'https' or not url.netloc or url.username:
        raise ValueError('A public HTTPS provenance URL is required')
    try:
        date = dt.datetime.fromisoformat(text(record.get('verifiedAt'), 'verifiedAt').replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('verifiedAt must be an ISO-8601 timestamp') from exc
    if date.tzinfo is None:
        raise ValueError('verifiedAt must include a timezone')


def validate(data: dict[str, Any]) -> dict[str, int]:
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Catalog version must be 1')
    for name in ('lines', 'stations', 'edges', 'facilities'):
        if not isinstance(data.get(name), list):
            raise ValueError(f'{name} must be an array')
    if not 1 <= len(data['lines']) <= 100 or not 2 <= len(data['stations']) <= 5000:
        raise ValueError('Catalog size is out of range')
    if len(data['edges']) > 20000 or len(data['facilities']) > 50000:
        raise ValueError('Catalog size is out of range')
    lines: set[str] = set()
    for line in data['lines']:
        identity = text(line.get('id'), 'line id', 20)
        if identity in lines or not re.fullmatch(r'\d{4}', identity):
            raise ValueError('Unique TOPIS numeric line IDs are required')
        lines.add(identity)
        for field in ('name', 'topisName', 'upLabel', 'downLabel'):
            text(line.get(field), field)
    stations: dict[str, dict[str, Any]] = {}
    topis_ids: set[tuple[str, str]] = set()
    for station in data['stations']:
        identity = text(station.get('id'), 'station id', 80)
        if identity in stations or not re.fullmatch(r'[A-Za-z0-9:_-]+', identity):
            raise ValueError('Invalid or duplicate station ID')
        line = station.get('lineId')
        if line not in lines:
            raise ValueError('Station references an unknown line')
        topis_id = text(station.get('topisId'), 'topisId', 40)
        if not re.fullmatch(r'\d{8,20}', topis_id) or (line, topis_id) in topis_ids:
            raise ValueError('Invalid or duplicate TOPIS station ID; do not substitute a different operator code')
        topis_ids.add((line, topis_id))
        text(station.get('name'), 'station name', 100)
        attribution = text(station.get('source'), 'source')
        if attribution in ('SYNTHETIC_DEMO', 'EXAMPLE_NOT_FOR_IMPORT'):
            raise ValueError('Synthetic/example records cannot be imported as live data')
        source(station)
        lat, lon = station.get('latitude'), station.get('longitude')
        if (lat is None) != (lon is None):
            raise ValueError('Both coordinates must be present or both null')
        if lat is not None:
            if isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                raise ValueError('Coordinates must be numbers')
            if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                raise ValueError('Coordinate out of range')
        stations[identity] = station
    edges: set[tuple[str, str, str, str]] = set()
    for edge in data['edges']:
        key = tuple(edge.get(k) for k in ('lineId', 'direction', 'from', 'to'))
        line, direction, start, end = key
        if direction not in ('0', '1') or start == end or start not in stations or end not in stations:
            raise ValueError('Invalid directed station edge')
        if stations[start]['lineId'] != line or stations[end]['lineId'] != line or key in edges:
            raise ValueError('Cross-line or duplicate edge')
        edges.add(key)
    for facility in data['facilities']:
        if facility.get('stationId') not in stations or facility.get('kind') not in ('TRANSFER', 'TOILET', 'AMENITY', 'GATE', 'EXIT'):
            raise ValueError('Invalid station facility')
        for field in ('title', 'location'):
            text(facility.get(field), field, 1000)
        source(facility)
        if facility['kind'] == 'TRANSFER':
            for field in ('direction', 'transferLine', 'carDoor'):
                text(facility.get(field), field, 100)
            if not re.fullmatch(r'[1-9]\d?-[1-9]\d?', facility['carDoor']):
                raise ValueError('Transfer carDoor must use a verified car-door pair such as 3-2')
    return {name: len(data[name]) for name in ('lines', 'stations', 'edges', 'facilities')}


def apply(data: dict[str, Any]) -> None:
    import psycopg  # Optional for --apply; install psycopg[binary] separately.
    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        raise ValueError('Set DATABASE_URL in the environment (PostgreSQL URL, not a JDBC URL)')
    # A complete graph snapshot replaces edges only for the supplied lines. Other lines are untouched.
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        for line in data['lines']:
            cursor.execute('INSERT INTO app_private.lines(id,name,topis_name,up_label,down_label,demo) VALUES (%s,%s,%s,%s,%s,false) ON CONFLICT(id) DO UPDATE SET name=excluded.name,topis_name=excluded.topis_name,up_label=excluded.up_label,down_label=excluded.down_label',
                           tuple(line[k] for k in ('id', 'name', 'topisName', 'upLabel', 'downLabel')))
        for station in data['stations']:
            cursor.execute('INSERT INTO app_private.subway_stations(id,line_id,topis_id,name,latitude,longitude,source,source_url,verified_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=excluded.name,latitude=excluded.latitude,longitude=excluded.longitude,source=excluded.source,source_url=excluded.source_url,verified_at=excluded.verified_at',
                           tuple(station.get(k) for k in ('id', 'lineId', 'topisId', 'name', 'latitude', 'longitude', 'source', 'sourceUrl', 'verifiedAt')))
        for line in data['lines']:
            cursor.execute('DELETE FROM app_private.station_edges WHERE line_id=%s', (line['id'],))
        for edge in data['edges']:
            cursor.execute('INSERT INTO app_private.station_edges(line_id,direction,from_id,to_id) VALUES (%s,%s,%s,%s)',
                           tuple(edge[k] for k in ('lineId', 'direction', 'from', 'to')))
        for station in data['stations']:
            cursor.execute('DELETE FROM app_private.station_facilities WHERE station_id=%s', (station['id'],))
        for facility in data['facilities']:
            identity = uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(str(facility.get(k, '')) for k in ('stationId', 'kind', 'title', 'location', 'direction', 'sourceUrl')))
            cursor.execute('INSERT INTO app_private.station_facilities(id,station_id,kind,title,location,gate_side,direction,transfer_line,car_door,source_url,verified_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (identity,) + tuple(facility.get(k) for k in ('stationId', 'kind', 'title', 'location', 'gateSide', 'direction', 'transferLine', 'carDoor', 'sourceUrl', 'verifiedAt')))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write to DATABASE_URL; replaces edges for supplied lines and facilities for supplied stations')
    parser.add_argument('--validate-only', action='store_true', help='Validate without accessing a database (the default)')
    args = parser.parse_args()
    if args.apply and args.validate_only:
        parser.error('Choose --apply or --validate-only, not both')
    if args.catalog.stat().st_size > 10_000_000:
        parser.error('Catalog file exceeds 10 MB')
    try:
        data = json.loads(args.catalog.read_text(encoding='utf-8'))
        counts = validate(data)
        print(json.dumps({'validated': counts}, ensure_ascii=False))
        if args.apply:
            apply(data)
            print('Catalog transaction committed. Validate live TOPIS identifiers before enabling users.')
    except (ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'Invalid catalog: {exc}\n')


if __name__ == '__main__':
    main()
