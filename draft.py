from nba_api.stats.endpoints import leaguedashplayerstats
import pandas as pd

def fetch_nba_stats(season='2024-25', per_mode='PerGame'):
    data = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed=per_mode
    )
    return data.get_data_frames()[0]

def standardize_stats(df, categories, invert_categories=None, min_gp=10, punt_categories=None):
    """
    Standardize selected player stats using Z-scores.

    Parameters:
    - df: DataFrame with raw player stats
    - categories: List of stat columns to include (e.g., ['PTS', 'REB', 'AST'])
    - invert_categories: List of categories where lower is better (e.g., ['TOV'])
    - min_gp: Minimum games played to include player
    - punt_categories: Categories to exclude from TOTAL_Z

    Returns:
    - standardized DataFrame with TOTAL_Z score
    """
    # Filter out low-GP players
    df_filtered = df[df['GP'] >= min_gp]

    # Keep only relevant columns
    selected = df_filtered[['PLAYER_NAME', 'GP'] + categories].copy()

    # Standardize
    numeric = selected.drop(columns=['PLAYER_NAME'])
    standardized = (numeric - numeric.mean()) / numeric.std()

    # Invert any "bad" categories
    if invert_categories:
        for col in invert_categories:
            if col in standardized.columns:
                standardized[col] = -standardized[col]

    # Add player name back
    standardized['PLAYER_NAME'] = selected['PLAYER_NAME']

    # Reorder
    cols = ['PLAYER_NAME'] + [col for col in standardized.columns if col != 'PLAYER_NAME']
    standardized = standardized[cols]

    # Punt (remove) unwanted categories from TOTAL_Z
    scoring_cols = [col for col in standardized.columns if col not in ['PLAYER_NAME', 'GP']]
    if punt_categories:
        scoring_cols = [col for col in scoring_cols if col not in punt_categories]

    standardized['TOTAL_Z'] = standardized[scoring_cols].sum(axis=1)

    return standardized.sort_values(by='TOTAL_Z', ascending=False)

# === Example Usage ===

categories = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG_PCT', 'FT_PCT', 'FG3M', 'TOV']
invert_cats = ['TOV']
punt_cats = []  # e.g., ['FT_PCT'] to punt free throws

raw_stats = fetch_nba_stats(season='2024-25')
result = standardize_stats(raw_stats, categories, invert_categories=invert_cats, min_gp=20, punt_categories=punt_cats)

# Display top 10 players
print(result[['PLAYER_NAME', 'TOTAL_Z'] + categories].head(10))