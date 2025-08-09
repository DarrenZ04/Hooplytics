from flask import Flask, request, jsonify, render_template
from nba_api.stats.endpoints import leaguedashplayerstats
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime

import os
app = Flask(__name__)
if 'SECRET_KEY' in os.environ:
    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']

def fetch_and_rank_players(categories, invert_categories=None, min_gp=10, punt_categories=None):
    data = leaguedashplayerstats.LeagueDashPlayerStats(season='2024-25', per_mode_detailed='PerGame')
    df = data.get_data_frames()[0]
    # NBA team IDs for 2024–25 season
    nba_team_ids = [1610612737, 1610612738, 1610612739, 1610612740, 1610612741, 1610612742, 1610612743, 1610612744,
                   1610612745, 1610612746, 1610612747, 1610612748, 1610612749, 1610612750, 1610612751, 1610612752,
                   1610612753, 1610612754, 1610612755, 1610612756, 1610612757, 1610612758, 1610612759, 1610612760,
                   1610612761, 1610612762, 1610612763, 1610612764, 1610612765, 1610612766]
    if 'TEAM_ID' in df.columns:
        df = df[df['TEAM_ID'].isin(nba_team_ids)]
    elif 'LEAGUE_ID' in df.columns:
        df = df[df['LEAGUE_ID'] == '00']

    df_filtered = df[df['GP'] >= min_gp].copy()

    # Load injury data and calculate penalty
    injury_penalty = {}
    try:
        DATA_DIR = Path(__file__).resolve().parent
        inj_df = pd.read_csv(DATA_DIR / 'nba_injuries_full_clean.csv')
        # NBA season: Oct 1 to Apr 15
        season_start = datetime(2024, 10, 1)
        season_end = datetime(2025, 4, 15)
        season_days = (season_end - season_start).days
        for _, row in inj_df.iterrows():
            player = row['Player']
            try:
                ret_date = datetime.strptime(str(row['Estimated Return Date']), '%Y-%m-%d')
                if ret_date > season_end:
                    fraction_missed = 1.0
                elif ret_date < season_start:
                    fraction_missed = 0.0
                else:
                    fraction_missed = (ret_date - season_start).days / season_days
                # If missing > 80% of season, set a large negative penalty
                if fraction_missed > 0.8:
                    penalty = -100
                else:
                    penalty = -fraction_missed
                injury_penalty[player] = penalty
            except Exception:
                continue
    except Exception:
        pass

    # Weighted FG contribution
    league_avg_fg_pct = df_filtered['FGM'].sum() / df_filtered['FGA'].sum()
    df_filtered['FG_CONTRIB'] = df_filtered['FGM'] - league_avg_fg_pct * df_filtered['FGA']

    # Weighted FT contribution
    league_avg_ft_pct = df_filtered['FTM'].sum() / df_filtered['FTA'].sum()
    df_filtered['FT_CONTRIB'] = df_filtered['FTM'] - league_avg_ft_pct * df_filtered['FTA']

    # Replace raw percentages with contribution stats
    categories = [c for c in categories if c not in ['FG_PCT', 'FGA', 'FGM', 'FT_PCT', 'FTA', 'FTM']]
    categories += ['FG_CONTRIB', 'FT_CONTRIB']

    # Keep GP separate from stat standardization
    # Use robust path for database CSV if needed elsewhere
    # db_df = pd.read_csv(DATA_DIR / 'database_24_25.csv')
    selected = df_filtered[['PLAYER_NAME', 'GP'] + categories].copy()
    numeric = selected.drop(columns=['PLAYER_NAME', 'GP'])

    # Standardize fantasy stats only (not GP)
    standardized_stats = (numeric - numeric.mean()) / numeric.std()

    if invert_categories:
        for col in invert_categories:
            if col in standardized_stats.columns:
                standardized_stats[col] = -standardized_stats[col]

    # Merge back non-standardized fields
    standardized_stats['PLAYER_NAME'] = selected['PLAYER_NAME']
    standardized_stats['GP'] = selected['GP']
    # Add volume columns for FG and FT
    if 'FG_PCT' in categories:
        standardized_stats['FGA'] = df_filtered['FGA']
    if 'FT_PCT' in categories:
        standardized_stats['FTA'] = df_filtered['FTA']

    # Reorder columns
    cols = ['PLAYER_NAME', 'GP'] + [col for col in standardized_stats.columns if col not in ['PLAYER_NAME', 'GP']]
    standardized = standardized_stats[cols].copy()

    # Compute total score
    scoring_cols = [col for col in standardized.columns if col not in ['PLAYER_NAME', 'GP', 'FGA', 'FTA']]
    if punt_categories:
        # If FG_PCT is punted, use only FG_PCT and weight by FGA
        if 'FG_PCT' in punt_categories and 'FG_PCT' in scoring_cols:
            scoring_cols = [col for col in scoring_cols if col not in ['FG_CONTRIB', 'FGM', 'FGA']]
            standardized['FG_PCT_SCORE'] = standardized['FG_PCT'] * df_filtered['FGA']
            scoring_cols = [col for col in scoring_cols if col != 'FG_PCT'] + ['FG_PCT_SCORE']
        # If FT_PCT is punted, use only FT_PCT and weight by FTA
        if 'FT_PCT' in punt_categories and 'FT_PCT' in scoring_cols:
            scoring_cols = [col for col in scoring_cols if col not in ['FT_CONTRIB', 'FTM', 'FTA']]
            standardized['FT_PCT_SCORE'] = standardized['FT_PCT'] * df_filtered['FTA']
            scoring_cols = [col for col in scoring_cols if col != 'FT_PCT'] + ['FT_PCT_SCORE']
        # Remove FG/FT made/attempted/contrib if punted
        for cat in ['FG_PCT', 'FT_PCT']:
            if cat in punt_categories:
                for remove_col in ['FG_CONTRIB', 'FGM', 'FGA', 'FT_CONTRIB', 'FTM', 'FTA']:
                    if remove_col in scoring_cols:
                        scoring_cols.remove(remove_col)
    standardized['TOTAL_Z'] = standardized[scoring_cols].sum(axis=1)

    gp_weight = 0.3
    standardized['ADJUSTED_Z'] = standardized['TOTAL_Z'] * np.power(standardized['GP'] / standardized['GP'].max(), gp_weight)

    # Apply injury penalty to ADJUSTED_Z
    for player_name, penalty in injury_penalty.items():
        if penalty == -100:
            standardized.loc[standardized['PLAYER_NAME'] == player_name, 'ADJUSTED_Z'] += penalty
        else:
            standardized.loc[standardized['PLAYER_NAME'] == player_name, 'ADJUSTED_Z'] *= max(0, 1 + penalty)

    return standardized.sort_values(by='ADJUSTED_Z', ascending=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/simulate_draft', methods=['POST'])
def simulate_draft():
    data = request.json
    categories = data.get('categories', [])
    invert = data.get('invert', [])
    punt = data.get('punt', [])
    min_gp = int(data.get('min_gp', 20))
    user_pick = int(data.get('user_pick'))
    num_teams = int(data.get('num_teams'))
    num_rounds = int(data.get('num_rounds'))

    global_ranked = fetch_and_rank_players(categories, invert, min_gp, punt_categories=None).reset_index(drop=True)
    user_ranked = fetch_and_rank_players(categories, invert, min_gp, punt_categories=punt).reset_index(drop=True)

    raw_data = leaguedashplayerstats.LeagueDashPlayerStats(season='2024-25', per_mode_detailed='PerGame')
    raw_df = raw_data.get_data_frames()[0]
    nba_team_ids = [1610612737, 1610612738, 1610612739, 1610612740, 1610612741, 1610612742, 1610612743, 1610612744,
                   1610612745, 1610612746, 1610612747, 1610612748, 1610612749, 1610612750, 1610612751, 1610612752,
                   1610612753, 1610612754, 1610612755, 1610612756, 1610612757, 1610612758, 1610612759, 1610612760,
                   1610612761, 1610612762, 1610612763, 1610612764, 1610612765, 1610612766]
    if 'TEAM_ID' in raw_df.columns:
        raw_df = raw_df[raw_df['TEAM_ID'].isin(nba_team_ids)]
    elif 'LEAGUE_ID' in raw_df.columns:
        raw_df = raw_df[raw_df['LEAGUE_ID'] == '00']
    # Include PLAYER_ID for headshots
    raw_df = raw_df[['PLAYER_NAME', 'PLAYER_ID', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FGM', 'FGA', 'FTM', 'FTA', 'FG3M', 'TOV']]

    draft_order = []
    for rnd in range(num_rounds):
        order = list(range(num_teams))
        draft_order += order if rnd % 2 == 0 else order[::-1]

    team_rosters = {i: [] for i in range(num_teams)}

    # Track drafted players
    drafted_players = set()
    for pick_num in range(num_rounds * num_teams):
        team_idx = draft_order[pick_num]
        # User's pick: select highest available from user_ranked
        if team_idx == user_pick - 1:
            available_user = user_ranked[~user_ranked['PLAYER_NAME'].isin(drafted_players)]
            if available_user.empty:
                continue
            player = available_user.iloc[0]
        else:
            available_global = global_ranked[~global_ranked['PLAYER_NAME'].isin(drafted_players)]
            if available_global.empty:
                continue
            player = available_global.iloc[0]
        player_name = player['PLAYER_NAME']
        drafted_players.add(player_name)

        raw_stats = raw_df[raw_df['PLAYER_NAME'] == player_name].to_dict(orient='records')[0]
        player_id = raw_stats.get('PLAYER_ID', 0)

        if team_idx == user_pick - 1:
            user_score = player['ADJUSTED_Z']
        else:
            user_score = player['ADJUSTED_Z']

        team_rosters[team_idx].append({
            'name': player_name,
            'player_id': player_id,
            'adjusted_z': round(user_score, 2),
            'gp': int(player['GP']),
            'stats': {k: round(v, 1) for k, v in raw_stats.items() if k not in ['PLAYER_NAME', 'PLAYER_ID']}
        })

    user_team = team_rosters[user_pick - 1]

    full_draft_list = []
    for i in range(num_teams * num_rounds):
        if i >= len(global_ranked):
            break
        player = global_ranked.iloc[i]
        raw_stats = raw_df[raw_df['PLAYER_NAME'] == player['PLAYER_NAME']].to_dict(orient='records')[0]
        player_id = raw_stats.get('PLAYER_ID', 0)
        user_score = user_ranked[user_ranked['PLAYER_NAME'] == player['PLAYER_NAME']]['ADJUSTED_Z'].values[0]

        full_draft_list.append({
            'name': player['PLAYER_NAME'],
            'player_id': player_id,
            'adjusted_z': round(user_score, 2),
            'gp': int(player['GP']),
            'stats': {k: round(v, 1) for k, v in raw_stats.items() if k not in ['PLAYER_NAME', 'PLAYER_ID']}
        })

    return jsonify({
        'your_team': user_team,
        'top_draft_pool': full_draft_list
    })

if __name__ == '__main__':
    import os
    app.config['DEBUG'] = os.getenv('FLASK_ENV') == 'development'
    app.run()
