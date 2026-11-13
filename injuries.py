"""Live NBA injury report from ESPN's public API, cached in memory.

If ESPN cannot be reached and nothing is cached, the hand-kept
nba_injuries_full_clean.csv is used instead (every player on it counts as Out).
"""
import csv
import threading
import time

import requests

import generate_nba_data_espn as espn

URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries'
CACHE_SECONDS = 300
TIMEOUT_SECONDS = 10
MANUAL_FILE = espn.DATA_DIR / 'nba_injuries_full_clean.csv'

TAGS = {'Out': 'OUT', 'Day-To-Day': 'DTD', 'Suspension': 'SUSP'}

_lock = threading.Lock()
_cache = {'at': 0.0, 'by_name': None}


def _describe(details):
    """'Left Foot Fracture' from ESPN's side / body part / diagnosis fields."""
    parts = []
    for key in ('side', 'type', 'detail'):
        value = (details.get(key) or '').strip()
        if value and value.lower() != 'not specified':
            parts.append(value)
    return ' '.join(parts)


def _parse(data):
    by_name = {}
    for team in data.get('injuries', []):
        for item in team.get('injuries', []):
            name = (item.get('athlete') or {}).get('displayName')
            if not name:
                continue
            details = item.get('details') or {}
            status = item.get('status') or ''
            by_name[espn.normalize(name)] = {
                'status': status,
                'tag': TAGS.get(status, status.upper()[:4]),
                'detail': _describe(details),
                'return_date': details.get('returnDate') or '',
                'comment': item.get('shortComment') or '',
                'team': team.get('displayName', ''),
            }
    return by_name


def _manual_fallback():
    by_name = {}
    try:
        with open(MANUAL_FILE, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                name = (row.get('Player') or '').strip()
                if name:
                    by_name[espn.normalize(name)] = {
                        'status': 'Out',
                        'tag': 'OUT',
                        'detail': '',
                        'return_date': (row.get('Estimated Return Date') or '').strip(),
                        'comment': '',
                        'team': '',
                    }
    except OSError:
        pass
    return by_name


def get_map():
    """Injured players keyed by normalized name."""
    with _lock:
        if _cache['by_name'] is not None and time.time() - _cache['at'] < CACHE_SECONDS:
            return _cache['by_name']
        try:
            response = requests.get(URL, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            by_name = _parse(response.json())
        except (requests.RequestException, ValueError):
            if _cache['by_name'] is not None:
                return _cache['by_name']
            by_name = _manual_fallback()
        _cache.update(at=time.time(), by_name=by_name)
        return by_name


def lookup(name):
    """Injury info for one player, or None when they are not on the report."""
    return get_map().get(espn.normalize(name))
