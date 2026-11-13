"""Build nba_player_data_25_26.csv from ESPN's public statistics API.

Use this when stats.nba.com is unreachable (generate_nba_data.py). ESPN has no
NBA player IDs, so they are copied by name from the CSVs already in this folder;
players it cannot match get PLAYER_ID 0 and the site shows their initials.
"""
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

URL = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete'
SEASON = 2026  # ESPN names a season by the year it ends: 2026 = 2025-26
SEASON_TYPE = 2  # regular season
OUT_FILE = 'nba_player_data_25_26.csv'
ID_SOURCES = ['nba_top100_2024.csv', 'nba_player_data_24_25.csv', 'nba_player_data_25_26.csv']
MIN_EXPECTED_PLAYERS = 300

DATA_DIR = Path(__file__).resolve().parent


def normalize(name):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    name = re.sub(r"[.'’,\-]", '', name)
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def fetch_page(page, season=SEASON):
    params = {
        'region': 'us', 'lang': 'en', 'contentorigin': 'espn', 'isqualified': 'false',
        'limit': 200, 'sort': 'offensive.avgPoints:desc',
        'season': season, 'seasontype': SEASON_TYPE, 'page': page,
    }
    for attempt in range(3):
        try:
            response = requests.get(URL, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            if attempt == 2:
                raise
            print(f'page {page} failed ({error}); retrying')
            time.sleep(2)


def fetch_all(season=SEASON):
    first = fetch_page(1, season)
    stat_names = {c['name']: c['names'] for c in first['categories']}
    athletes = list(first['athletes'])
    for page in range(2, first['pagination']['pages'] + 1):
        athletes += fetch_page(page, season)['athletes']
        time.sleep(0.5)
    print(f"season: {first['requestedSeason']['displayName']} ({first['requestedSeason']['type']['name']})")
    return athletes, stat_names


def load_known_ids():
    ids = {}
    for filename in ID_SOURCES:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for name, player_id in zip(df['PLAYER_NAME'], df['PLAYER_ID']):
            if isinstance(name, str) and player_id and normalize(name) not in ids:
                ids[normalize(name)] = int(player_id)
    return ids


def build_rows(athletes, stat_names, known_ids):
    rows = []
    for entry in athletes:
        stats = {c['name']: dict(zip(stat_names[c['name']], c['values'])) for c in entry['categories']}
        general, offense, defense = stats['general'], stats['offensive'], stats['defensive']
        name = entry['athlete']['displayName']
        fgm, fga = offense['avgFieldGoalsMade'], offense['avgFieldGoalsAttempted']
        ftm, fta = offense['avgFreeThrowsMade'], offense['avgFreeThrowsAttempted']
        rows.append({
            'PLAYER_NAME': name,
            'PLAYER_ID': known_ids.get(normalize(name), 0),
            'GP': int(general['gamesPlayed']),
            'PTS': offense['avgPoints'],
            'REB': general['avgRebounds'],
            'AST': offense['avgAssists'],
            'STL': defense['avgSteals'],
            'BLK': defense['avgBlocks'],
            'FGM': fgm,
            'FGA': fga,
            'FG_PCT': fgm / fga if fga else 0,
            'FTM': ftm,
            'FTA': fta,
            'FT_PCT': ftm / fta if fta else 0,
            'FG3M': offense['avgThreePointFieldGoalsMade'],
            'TOV': offense['avgTurnovers'],
        })
    return pd.DataFrame(rows).round(3).sort_values('PLAYER_NAME').reset_index(drop=True)


def main():
    known_ids = load_known_ids()
    athletes, stat_names = fetch_all()
    df = build_rows(athletes, stat_names, known_ids)

    if len(df) < MIN_EXPECTED_PLAYERS:
        raise SystemExit(f'only {len(df)} players returned; not overwriting {OUT_FILE}')

    df.to_csv(DATA_DIR / OUT_FILE, index=False)
    regulars = df[df['GP'] >= 20]
    missing = regulars[regulars['PLAYER_ID'] == 0]['PLAYER_NAME'].tolist()
    print(f'saved {len(df)} players to {OUT_FILE}')
    print(f'players with 20+ games: {len(regulars)}, without an NBA id (initials shown): {missing}')


if __name__ == '__main__':
    main()
