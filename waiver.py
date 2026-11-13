"""Waiver wire help: players outside the top 110 whose recent games beat their season averages.

A good pickup is trending up in both minutes and production. Recent form comes
from each player's game log on ESPN's public API (cached), and production is
scored on the same total z-score scale as the season ranking. Anyone on the
injury report is left out.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests

import generate_nba_data_espn as espn
import injuries
import season_stats
from fantasy import fantasy_points

GAMELOG_URL = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog'

RANK_CUTOFF = 110          # only players ranked below this are considered
MIN_SEASON_MINUTES = 12    # season minutes per game: skip players who barely play
MIN_RECENT_MINUTES = 15    # recent minutes per game: skip garbage-time spikes
MIN_MINUTES_GAIN = 1.0     # recent minutes must beat the season average by this much
MIN_RECENT_GAMES = 3
MAX_RESULTS = 40
WINDOWS = (3, 5, 7)
DEFAULT_WINDOW = 5

LOG_CACHE_SECONDS = 900
REFRESH_LOG_SECONDS = 60
WORKERS = 12
TIMEOUT_SECONDS = 20

_logs = {}                 # espn_id -> (fetched_at, games oldest first)
_logs_lock = threading.Lock()

AVERAGED = ['MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M', 'TOV', 'FGM', 'FGA', 'FTM', 'FTA']
SHOWN = ['MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M', 'TOV']


def _made(text):
    """'9-20' -> 9."""
    return float(str(text).split('-')[0])


def _parse_gamelog(data):
    seasons = [s for s in data.get('seasonTypes', []) if 'Regular Season' in s.get('displayName', '')]
    if not seasons:
        return []
    dates = {key: (event.get('gameDate') or '') for key, event in (data.get('events') or {}).items()}
    games = []
    for category in seasons[0].get('categories', []):
        for event in category.get('events', []):
            stats = event.get('stats') or []
            if len(stats) < 14:
                continue
            try:
                minutes = float(stats[0])
                if minutes <= 0:
                    continue
                fgm, fga = (float(x) for x in str(stats[1]).split('-'))
                ftm, fta = (float(x) for x in str(stats[5]).split('-'))
                games.append({
                    'date': dates.get(event.get('eventId'), ''),
                    'MIN': minutes,
                    'FGM': fgm, 'FGA': fga,
                    'FG3M': _made(stats[3]),
                    'FTM': ftm, 'FTA': fta,
                    'REB': float(stats[7]), 'AST': float(stats[8]),
                    'BLK': float(stats[9]), 'STL': float(stats[10]),
                    'TOV': float(stats[12]), 'PTS': float(stats[13]),
                })
            except (ValueError, TypeError):
                continue
    games.sort(key=lambda g: g['date'])
    return games


def _fetch_games(espn_id, max_age=LOG_CACHE_SECONDS):
    """Game log for one player, from cache when fresh. None if ESPN could not be reached."""
    with _logs_lock:
        cached = _logs.get(espn_id)
    if cached and time.time() - cached[0] < max_age:
        return cached[1]
    for attempt in range(2):
        try:
            response = requests.get(GAMELOG_URL.format(id=espn_id), params={'season': season_stats.ESPN_SEASON}, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            games = _parse_gamelog(response.json())
            with _logs_lock:
                _logs[espn_id] = (time.time(), games)
            return games
        except (requests.RequestException, ValueError):
            if attempt == 1:
                return cached[1] if cached else None
    return None


def _averages(games):
    return {key: sum(g[key] for g in games) / len(games) for key in AVERAGED}


def payload(window=DEFAULT_WINDOW, refresh=False, scoring='categories'):
    if window not in WINDOWS:
        window = DEFAULT_WINDOW
    points = scoring == 'points'
    frame, fetched, stale = season_stats.get_frame(refresh)
    min_gp = season_stats.default_min_games(frame)
    ref = season_stats.score_reference(frame, min_gp)

    scored = season_stats.score_players(frame, min_gp, scoring).sort_values('score', ascending=False).reset_index(drop=True)
    injured = injuries.get_map()
    scored['norm'] = scored['name'].map(espn.normalize)
    ranked = (scored['gp'] >= min_gp) | ((scored['gp'] >= 1) & scored['norm'].isin(injured))
    scored['rank'] = ranked.cumsum().where(ranked)
    pool = scored[
        (scored['rank'] > RANK_CUTOFF)
        & (scored['MIN'] >= MIN_SEASON_MINUTES)
        & ~scored['norm'].isin(injured)
    ]
    candidates = pool.to_dict(orient='records')

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        max_age = REFRESH_LOG_SECONDS if refresh else LOG_CACHE_SECONDS
        logs = list(executor.map(lambda c: _fetch_games(c['espn_id'], max_age), candidates))

    rows = []
    failed = 0
    for candidate, games in zip(candidates, logs):
        if games is None:
            failed += 1
            continue
        recent = games[-window:]
        if len(recent) < MIN_RECENT_GAMES:
            continue
        rows.append((candidate, recent, _averages(recent)))

    results = []
    if rows and (points or ref is not None):
        recent_frame = pd.DataFrame([avg for _, _, avg in rows])
        recent_z = fantasy_points(recent_frame) if points else season_stats.total_z(recent_frame, ref)
        for (candidate, recent, avg), z in zip(rows, recent_z):
            gain = avg['MIN'] - float(candidate['MIN'])
            trend = float(z) - float(candidate['score'])
            if avg['MIN'] < MIN_RECENT_MINUTES or gain < MIN_MINUTES_GAIN or trend <= 0:
                continue
            season_avg = {key: float(candidate[key]) for key in SHOWN}
            results.append({
                'name': candidate['name'],
                'espn_id': candidate['espn_id'],
                'player_id': int(candidate['player_id']),
                'headshot': candidate['headshot'],
                'team': candidate['team'],
                'gp': candidate['gp'],
                'rank': int(candidate['rank']),
                'score': round(float(z), 2),
                'season_score': round(float(candidate['score']), 2),
                'trend': round(trend, 2),
                'games': len(recent),
                'recent': {key: round(avg[key], 1) for key in SHOWN},
                'season': {key: round(season_avg[key], 1) for key in SHOWN},
                'change': {key: round(avg[key] - season_avg[key], 1) for key in SHOWN},
            })
        results.sort(key=lambda r: r['score'], reverse=True)

    return {
        'season': season_stats.SEASON_LABEL,
        'scoring': scoring,
        'window': window,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'stale': stale,
        'rank_cutoff': RANK_CUTOFF,
        'min_minutes_gain': MIN_MINUTES_GAIN,
        'examined': len(candidates),
        'failed': failed,
        'matches': len(results),
        'players': results[:MAX_RESULTS],
    }
