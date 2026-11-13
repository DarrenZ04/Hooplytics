"""Fantasy points per game under ESPN's default points-league scoring."""

WEIGHTS = {
    'PTS': 1,
    'REB': 1,
    'AST': 2,
    'STL': 4,
    'BLK': 4,
    'TOV': -2,
    'FG3M': 1,
    'FGM': 2,
    'FGA': -1,
    'FTM': 1,
    'FTA': -1,
}


def fantasy_points(stats):
    """Weighted sum of per-game stats. `stats` is a DataFrame, Series or dict with the WEIGHTS columns."""
    return sum(stats[column] * weight for column, weight in WEIGHTS.items())
