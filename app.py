from flask import Flask, request, jsonify, render_template
from nba_api.stats.endpoints import leaguedashplayerstats
import numpy as np
import pandas as pd

app = Flask(__name__)

def fetch_and_rank_players(categories, invert_categories=None, min_gp=10, punt_categories=None):
    data = leaguedashplayerstats.LeagueDashPlayerStats(season='2023-24', per_mode_detailed='PerGame')
    df = data.get_data_frames()[0]

    df_filtered = df[df['GP'] >= min_gp]
    selected = df_filtered[['PLAYER_NAME', 'GP'] + categories].copy()
    numeric = selected.drop(columns=['PLAYER_NAME'])

    standardized = (numeric - numeric.mean()) / numeric.std()

    if invert_categories:
        for col in invert_categories:
            if col in standardized.columns:
                standardized[col] = -standardized[col]

    standardized['PLAYER_NAME'] = selected['PLAYER_NAME']
    cols = ['PLAYER_NAME'] + [col for col in standardized.columns if col != 'PLAYER_NAME']
    standardized = standardized[cols]

    scoring_cols = [col for col in standardized.columns if col not in ['PLAYER_NAME', 'GP']]
    if punt_categories:
        scoring_cols = [col for col in scoring_cols if col not in punt_categories]

    standardized['TOTAL_Z'] = standardized[scoring_cols].sum(axis=1)

    standardized['ADJUSTED_Z'] = standardized['TOTAL_Z'] * np.sqrt(standardized['GP'] / standardized['GP'].max())

    # Sort by adjusted score
    return standardized.sort_values(by='ADJUSTED_Z', ascending=False)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/rank', methods=['POST'])
def rank():
    data = request.json
    categories = data.get('categories', [])
    invert = data.get('invert', [])
    punt = data.get('punt', [])
    min_gp = int(data.get('min_gp', 10))

    result = fetch_and_rank_players(categories, invert, min_gp, punt)
    return result.head(20).to_json(orient='records')

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

    # Get ranked players
    ranked = fetch_and_rank_players(categories, invert, min_gp, punt).reset_index(drop=True)

    # Get original (unstandardized) stats for reference
    raw_data = leaguedashplayerstats.LeagueDashPlayerStats(season='2023-24', per_mode_detailed='PerGame')
    raw_df = raw_data.get_data_frames()[0]
    raw_df = raw_df[['PLAYER_NAME'] + categories]

    # Build draft order
    draft_order = []
    for rnd in range(num_rounds):
        order = list(range(num_teams))
        draft_order += order if rnd % 2 == 0 else order[::-1]

    # Draft players
    team_rosters = {i: [] for i in range(num_teams)}
    for pick_num in range(min(len(ranked), num_rounds * num_teams)):
        team_idx = draft_order[pick_num]
        player = ranked.iloc[pick_num]
        player_name = player['PLAYER_NAME']

        # Get unstandardized stats for this player
        raw_stats = raw_df[raw_df['PLAYER_NAME'] == player_name].to_dict(orient='records')[0]

        team_rosters[team_idx].append({
            'name': player_name,
            'adjusted_z': round(player['ADJUSTED_Z'], 2),
            'gp': int(player['GP']),
            'stats': {k: round(v, 1) for k, v in raw_stats.items() if k != 'PLAYER_NAME'}
        })

    user_team = team_rosters[user_pick - 1]
    return jsonify({'your_team': user_team})

if __name__ == '__main__':
    app.run(debug=True)