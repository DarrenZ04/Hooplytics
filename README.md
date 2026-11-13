# Fantasy Draft Optimizer

## Project Description
Fantasy Draft Optimizer is a Python/Flask web application designed to help users optimize their fantasy basketball draft strategy. It uses real player statistics from the 2025-26 NBA season, loaded from a local CSV file, and applies advanced ranking algorithms, category-based scoring, and injury adjustments. The app simulates draft scenarios, supports punt strategies, and provides a user-friendly web interface for team selection and analysis.

Key Features:
- Loads all NBA player stats from a CSV file (no external API calls required). Rebuild it with `python generate_nba_data_espn.py`, or `generate_nba_data.py` if stats.nba.com is reachable
- Category-based and punt strategy support
- Points leagues: a Categories / Points switch re-ranks everything by average fantasy points per game (ESPN default scoring) instead of the category z-score
- Injury-adjusted player projections from ESPN's live injury report, with a red status tag next to injured players
- Draft simulation for customizable teams and rounds
- Waiver wire help: players outside the top 110 who are trending up in minutes and production over their last 3, 5 or 7 games (injured players excluded)
- Season tracker: add your players to see their 2026-27 per-game stats and rank so far, plus a top performers list (live from ESPN, cached for 10 minutes)
- Interactive web interface

## Live Demo
Try the app here: [https://hooplytics.vercel.app/](https://hooplytics.vercel.app/)
