import re
from datetime import datetime
import pandas as pd

# Read the injury report from the text file
with open("inj_rep.txt", "r", encoding="utf-8") as f:
    injury_text = f.read()

# Today's date for year adjustment
today = datetime(2025, 8, 8)

players = []

# Regex pattern to capture: player name + estimated return date (after position)
pattern = re.compile(r"^(.*?)\t(?:PG|SG|SF|PF|C|F|G)\t([A-Za-z]{3} \d+|[A-Za-z]{3}|Out)", re.MULTILINE)

for match in pattern.finditer(injury_text):
    name = match.group(1).strip()
    est_return = match.group(2).strip()

    # Convert "Out" to May 1 of the correct season year
    if est_return.lower() == "out":
        year = today.year if (5, 1) >= (today.month, today.day) else today.year + 1
        est_return_date = datetime(year, 5, 1).strftime("%Y-%m-%d")
    else:
        try:
            # Parse and adjust month/day dates
            date_obj = datetime.strptime(est_return + f" {today.year}", "%b %d %Y")
            if (date_obj.month, date_obj.day) < (today.month, today.day):
                date_obj = date_obj.replace(year=today.year + 1)
            est_return_date = date_obj.strftime("%Y-%m-%d")
        except ValueError:
            est_return_date = est_return

    players.append((name, est_return_date))

# Create DataFrame
df = pd.DataFrame(players, columns=["Player", "Estimated Return Date"])

# Save to CSV
df.to_csv("nba_injuries_full_clean.csv", index=False)

print("Saved cleaned injury report to nba_injuries_full_clean.csv")
print(df.head())