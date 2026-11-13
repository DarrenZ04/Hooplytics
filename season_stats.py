"""Current-season (2026-27) player averages and a "top performers" ranking.

Stats come from ESPN's public statistics API (the same source as
generate_nba_data_espn.py) and are cached in memory so the page can reload
without hitting ESPN every time.
"""
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import generate_nba_data_espn as espn
import injuries
from fantasy import fantasy_points

ESPN_SEASON = 2027  # ESPN names a season by the year it ends: 2027 = 2026-27
SEASON_LABEL = '2026-27'
LAST_SEASON_FILE = espn.DATA_DIR / 'nba_player_data_25_26.csv'

CACHE_SECONDS = 600
MIN_REFRESH_SECONDS = 60
SCORE_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M', 'FG_IMPACT', 'FT_IMPACT', 'TOV']
STAT_COLUMNS = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FGM', 'FGA', 'FTM', 'FTA', 'FG3M', 'TOV']

_lock = threading.Lock()
_cache = {'at': 0.0, 'frame': None, 'fetched': None}
_last_season = {}


def _build_frame(athletes, stat_names, known_ids):
    rows = []
    for entry in athletes:
        stats = {c['name']: dict(zip(stat_names[c['name']], c['values'])) for c in entry['categories']}
        general, offense, defense = stats['general'], stats['offensive'], stats['defensive']
        athlete = entry['athlete']
        headshot = athlete.get('headshot') or {}
        rows.append({
            'name': athlete['displayName'],
            'espn_id': str(athlete['id']),
            'player_id': known_ids.get(espn.normalize(athlete['displayName']), 0),
            'headshot': headshot.get('href', ''),
            'team': athlete.get('teamShortName', ''),
            'gp': int(general['gamesPlayed']),
            'MIN': general['avgMinutes'],
            'PTS': offense['avgPoints'],
            'REB': general['avgRebounds'],
            'AST': offense['avgAssists'],
            'STL': defense['avgSteals'],
            'BLK': defense['avgBlocks'],
            'FGM': offense['avgFieldGoalsMade'],
            'FGA': offense['avgFieldGoalsAttempted'],
            'FTM': offense['avgFreeThrowsMade'],
            'FTA': offense['avgFreeThrowsAttempted'],
            'FG3M': offense['avgThreePointFieldGoalsMade'],
            'TOV': offense['avgTurnovers'],
        })
    return pd.DataFrame(rows)


def _load_last_season():
    """Last season's per-game stats by normalized name, for comparison."""
    if _last_season or not LAST_SEASON_FILE.exists():
        return _last_season
    df = pd.read_csv(LAST_SEASON_FILE)
    for record in df.to_dict(orient='records'):
        if not isinstance(record.get('PLAYER_NAME'), str):
            continue
        _last_season[espn.normalize(record['PLAYER_NAME'])] = {
            'gp': int(record['GP']),
            **{col: round(float(record[col]), 1) for col in STAT_COLUMNS},
        }
    return _last_season


def get_frame(refresh=False):
    """Season frame, from cache when fresh. Returns (frame, fetched_at, is_stale)."""
    with _lock:
        age = time.time() - _cache['at']
        if _cache['frame'] is not None:
            limit = MIN_REFRESH_SECONDS if refresh else CACHE_SECONDS
            if age < limit:
                return _cache['frame'], _cache['fetched'], False
        try:
            athletes, stat_names = espn.fetch_all(ESPN_SEASON)
            frame = _build_frame(athletes, stat_names, espn.load_known_ids())
        except Exception:
            if _cache['frame'] is not None:
                return _cache['frame'], _cache['fetched'], True
            raise
        _cache.update(at=time.time(), frame=frame, fetched=datetime.now(timezone.utc))
        return frame, _cache['fetched'], False


def is_ranked(games, name, min_gp, injured):
    """Has enough games to rank, or is on the injury report and has played at all.

    Injuries are why many stars sit under the minimum, so they are never filtered out.
    """
    return games >= min_gp or (games >= 1 and espn.normalize(name) in injured)


def default_min_games(frame):
    """About 40% of the games the busiest player has played, at least 1."""
    return max(1, round(int(frame['gp'].max()) * 0.4)) if len(frame) else 1


def score_reference(frame, min_gp):
    """Means, deviations and league shooting averages from players with at least min_gp games.

    Using only these players keeps a handful of small samples from distorting the scale.
    """
    qualified = frame[frame['gp'] >= min_gp]
    if len(qualified) < 2 or qualified['FGA'].sum() == 0 or qualified['FTA'].sum() == 0:
        return None
    fg_avg = qualified['FGM'].sum() / qualified['FGA'].sum()
    ft_avg = qualified['FTM'].sum() / qualified['FTA'].sum()
    ref = qualified.assign(
        FG_IMPACT=qualified['FGM'] - fg_avg * qualified['FGA'],
        FT_IMPACT=qualified['FTM'] - ft_avg * qualified['FTA'],
    )[SCORE_CATEGORIES]
    return {'fg_avg': fg_avg, 'ft_avg': ft_avg, 'mean': ref.mean(), 'std': ref.std().replace(0, np.nan)}


def total_z(stats, ref):
    """Total z-score across the nine fantasy categories; turnovers count against."""
    work = stats.assign(
        FG_IMPACT=stats['FGM'] - ref['fg_avg'] * stats['FGA'],
        FT_IMPACT=stats['FTM'] - ref['ft_avg'] * stats['FTA'],
    )
    z = (work[SCORE_CATEGORIES] - ref['mean']) / ref['std']
    z['TOV'] = -z['TOV']
    return z.fillna(0).sum(axis=1)


def score_players(frame, min_gp, scoring='categories'):
    """Score every player: total z-score for categories leagues, fantasy points per game for points leagues."""
    work = frame.copy()
    if scoring == 'points':
        work['score'] = fantasy_points(work)
        return work
    ref = score_reference(frame, min_gp)
    work['score'] = 0.0 if ref is None else total_z(work, ref)
    return work


def payload(min_gp=None, refresh=False, scoring='categories'):
    frame, fetched, stale = get_frame(refresh)
    default_min = default_min_games(frame)
    min_gp = default_min if min_gp is None else max(1, min(min_gp, 82))

    scored = score_players(frame, min_gp, scoring).sort_values('score', ascending=False).reset_index(drop=True)
    last_season = _load_last_season()
    injured = injuries.get_map()

    players = []
    rank = 0
    with_min_games = int((scored['gp'] >= min_gp).sum())
    for record in scored.to_dict(orient='records'):
        qualified = is_ranked(record['gp'], record['name'], min_gp, injured)
        if qualified:
            rank += 1
        players.append({
            'name': record['name'],
            'espn_id': record['espn_id'],
            'player_id': int(record['player_id']),
            'headshot': record['headshot'],
            'team': record['team'],
            'gp': record['gp'],
            'min': round(float(record['MIN']), 1),
            'adjusted_z': round(float(record['score']), 2),
            'rank': rank if qualified else None,
            'stats': {col: round(float(record[col]), 1) for col in STAT_COLUMNS},
            'last': last_season.get(espn.normalize(record['name'])),
            'injury': injured.get(espn.normalize(record['name'])),
        })

    return {
        'season': SEASON_LABEL,
        'scoring': scoring,
        'fetched_at': fetched.isoformat(),
        'stale': stale,
        'max_gp': int(frame['gp'].max()) if len(frame) else 0,
        'min_gp': min_gp,
        'default_min_gp': default_min,
        'qualified': rank,
        'with_min_games': with_min_games,
        'players': players,
    }
