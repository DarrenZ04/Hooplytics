import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats
from pathlib import Path

# Fetch NBA player stats for 2024-25 season
stats = leaguedashplayerstats.LeagueDashPlayerStats(season='2025-26', per_mode_detailed='PerGame')
df = stats.get_data_frames()[0]

# Filter to NBA teams only
nba_team_ids = [1610612737, 1610612738, 1610612739, 1610612740, 1610612741, 1610612742, 1610612743, 1610612744,
               1610612745, 1610612746, 1610612747, 1610612748, 1610612749, 1610612750, 1610612751, 1610612752,
               1610612753, 1610612754, 1610612755, 1610612756, 1610612757, 1610612758, 1610612759, 1610612760,
               1610612761, 1610612762, 1610612763, 1610612764, 1610612765, 1610612766]
if 'TEAM_ID' in df.columns:
    df = df[df['TEAM_ID'].isin(nba_team_ids)]
elif 'LEAGUE_ID' in df.columns:
    df = df[df['LEAGUE_ID'] == '00']

# Select only needed columns for your app
columns_needed = ['PLAYER_NAME', 'PLAYER_ID', 'TEAM_ID', 'GP', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FGM', 'FGA', 'FG_PCT', 'FTM', 'FTA', 'FT_PCT', 'FG3M', 'TOV']
df = df[columns_needed]

# Save to CSV in project directory
DATA_DIR = Path(__file__).resolve().parent
df.to_csv(DATA_DIR / 'nba_player_data_25_26.csv', index=False)

print('NBA player data saved to nba_player_data_25_26.csv')
