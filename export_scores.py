import pandas as pd
from src.db.db_manager import DatabaseManager
from src.engine.screener_queries import run_screener

db = DatabaseManager(read_only=True)
dates = db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
latest_date = str(dates[0][0])

all_tickers = [r[0] for r in db.execute_read("SELECT DISTINCT ticker FROM daily_bars;")]

df = run_screener(db, cutoff_date=latest_date, manual_tickers=all_tickers)
df_sorted = df.sort_values(by="composite_score", ascending=False)

lines = []
lines.append("Rank | Ticker | Company Name                             | Market Cap   | Composite Score (Mansfield RS vs SPY)\n")
lines.append("=" * 105 + "\n")

for idx, row in df_sorted.reset_index(drop=True).iterrows():
    rank = idx + 1
    t = str(row["ticker"])
    n = str(row.get("name") if row.get("name") else t)
    mc = row["market_cap"]
    
    if pd.isna(mc) or mc is None:
        mc_formatted = "N/A"
    else:
        v = float(mc)
        if v >= 1e9:
            mc_formatted = f"${v / 1e9:.2f}B"
        elif v >= 1e6:
            mc_formatted = f"${v / 1e6:.1f}M"
        else:
            mc_formatted = f"${v:,.0f}"
            
    cs = float(row["composite_score"])
    line_str = f"{rank:4d} | {t:6s} | {n[:40]:40s} | {mc_formatted:12s} | {cs:.4f}\n"
    lines.append(line_str)

with open("all_stocks_composite_scores.txt", "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Exported all_stocks_composite_scores.txt with explicit dollar numbers!")
