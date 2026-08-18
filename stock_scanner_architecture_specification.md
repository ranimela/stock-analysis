# US Equity Stage-2 Momentum Scanner & Point-in-Time Backtest Engine
## System Architecture & Technical Specification

---

## 1. Executive Summary & Objective

This document defines the end-to-end technical architecture, mathematical screening criteria, data engineering pipeline, and simulation/validation models for an automated, free-source **US Equity Stage-2 Momentum Scanner and Point-in-Time Backtesting Engine**.

The system executes batch End-of-Day (EOD) screening across active common equities listed on NYSE and NASDAQ. Its primary output is a prioritized **Top-10 actionable stock recommendation list** optimized for multi-week position holding (3 to 12 weeks), coupled with a **Point-in-Time validation engine** simulating historical scanner output from $T_{-5}$ (1 week ago) and $T_{-22}$ (1 month ago) trading days to track forward alpha against the S&P 500 benchmark (`SPY`).

```
+---------------------------------------------------------------------------------------------------+
|                                     DATA INGESTION LAYER                                          |
|  - NASDAQ Trader FTP (Universe & Metadata)                                                        |
|  - yfinance / EOD Price-Volume Feed (2-Year Adjusted OHLCV)                                       |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                 STAGE 1: HARD UNIVERSE GATE                                       |
|  - Asset Class Filter (Common Stock Only)                                                         |
|  - Price Floor: Close >= $10.00                                                                   |
|  - Liquidity Floor: 20-Day ADV * Close >= $20,000,000                                             |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                             STAGE 2: MINERVINI TREND TEMPLATE                                     |
|  - Moving Average Stack: Close > SMA50 > SMA150 > SMA200                                          |
|  - Structural Slope: SMA200(t) > SMA200(t-20)                                                     |
|  - Range Proximity: Close >= 1.30 * 52W Low AND Close >= 0.75 * 52W High                          |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                         STAGE 3: VOLATILITY CONTRACTION (VCP) SETUP                               |
|  - Tightness Ratio: (10-Day High - 10-Day Low) / ATR14 <= 2.0                                     |
|  - Volume Dry-Up (VDU): Volume(1D) <= 0.60 * SMA(Volume, 50)                                      |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                          STAGE 4: COMPOSITE RANKING & SELECTION                                   |
|  - Relative Strength (Mansfield vs SPY): 60% Weight                                               |
|  - Consolidation Tightness Score: 40% Weight                                                      |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                    EXECUTION & OUTPUT LAYER                                       |
|  +-------------------------------------+     +-------------------------------------------------+  |
|  |     Live Signal Engine (T_0)        |     |      Point-in-Time Backtest Engine              |  |
|  |  Top 10 High-Probability Breakouts  |     |  - T-5 Days Simulation & Forward Performance    |  |
|  |  (Entry, Stop-Loss, ATR Targets)    |     |  - T-22 Days Simulation & Forward Alpha vs SPY  |  |
|  +-------------------------------------+     +-------------------------------------------------+  |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Quantitative Screening Engine

The quantitative pipeline applies four sequential filter stages to eliminate noise, illiquid micro-caps, structural downtrends, and extended price runs.

### 2.1 Stage 1: Liquidity & Asset Class Gatekeeper
* **Data Sources:** NASDAQ Trader FTP directory (`nasdaqlisted.txt`, `otherlisted.txt`).
* **Asset Class Exclusions:** Exclude ETFs, Closed-End Funds (CEFs), American Depositary Receipts (ADRs), warrants, preferred shares, structured notes, and acquisition vehicles (SPACs).
* **Price Minimum:** 
  $$	ext{Close}_t \ge \$10.00$$
* **Average Daily Dollar Volume (20-Day ADV):**
  $$	ext{ADV}_{20} = rac{1}{20} \sum_{i=0}^{19} \left(	ext{Close}_{t-i} 	imes 	ext{Volume}_{t-i}ight) \ge \$20,000,000$$

### 2.2 Stage 2: Stage-2 Structural Trend Template
Based on quantitative parameters derived from the [Minervini Trend Template](https://www.finermarketpoints.com/post/mark-minervini-s-stock-screener-what-indicators-and-criteria-does-he-use):

1. **Moving Average Alignment:**
   $$	ext{Close}_t > 	ext{SMA}_{50}(t) > 	ext{SMA}_{150}(t) > 	ext{SMA}_{200}(t)$$
2. **200-Day SMA Trajectory:**
   $$	ext{SMA}_{200}(t) > 	ext{SMA}_{200}(t-20)$$
3. **52-Week Range Boundaries:**
   $$	ext{Close}_t \ge 1.30 	imes \min_{i \in [0, 251]}(	ext{Low}_{t-i})$$
   $$	ext{Close}_t \ge 0.75 	imes \max_{i \in [0, 251]}(	ext{High}_{t-i})$$

### 2.3 Stage 3: Setup Trigger (Volatility & Volume Contraction)
Identifies coiled consolidations ready for expansion while minimizing downside risk:

* **Consolidation Tightness Ratio:**
  $$	ext{TR}_{10	ext{D}} = rac{\max_{i \in [0,9]}(	ext{High}_{t-i}) - \min_{i \in [0,9]}(	ext{Low}_{t-i})}{	ext{ATR}_{14}(t)} \le 2.0$$
* **Average True Range ($	ext{ATR}_{14}$):**
  $$	ext{TR}_t = \max\left(	ext{High}_t - 	ext{Low}_t, \, |	ext{High}_t - 	ext{Close}_{t-1}|, \, |	ext{Low}_t - 	ext{Close}_{t-1}|ight)$$
  $$	ext{ATR}_{14}(t) = rac{1}{14} \sum_{i=0}^{13} 	ext{TR}_{t-i}$$
* **Volume Dry-Up (VDU):**
  $$	ext{Volume}_t \le 0.60 	imes 	ext{SMA}_{	ext{Vol}, 50}(t)$$

### 2.4 Stage 4: Composite Scoring & Top-10 Selection
All candidate equities clearing Stages 1–3 are ranked using a normalized composite score $S_i \in [0, 100]$:

$$S_i = 0.60 \cdot \mathcal{P}\left(	ext{RS}_iight) + 0.40 \cdot \mathcal{P}\left(rac{1}{	ext{TR}_{10	ext{D}, i}}ight)$$

Where $\mathcal{P}(X)$ is the empirical percentile rank of variable $X$ across the passing universe, and Relative Strength ($	ext{RS}$) relative to `SPY` is defined as:

$$	ext{RS}_i = 0.70 \cdot \left(rac{	ext{Stock}_{i, t} / 	ext{Stock}_{i, t-63}}{	ext{SPY}_t / 	ext{SPY}_{t-63}} - 1ight) + 0.30 \cdot \left(rac{	ext{Stock}_{i, t} / 	ext{Stock}_{i, t-252}}{	ext{SPY}_t / 	ext{SPY}_{t-252}} - 1ight)$$

The top 10 ranked symbols ($i = 1, \dots, 10$) are extracted as the daily recommendation portfolio.

---

## 3. Point-in-Time Simulation & Validation Engine

To validate screening performance and prevent lookahead bias, the engine runs point-in-time backtests at two historical intervals.

```
Lookback Window: 2 Years Historical Data
=========================================================================================> Time

[----------------- T-22 Data Window -----------------]
                                                     |
                                            Run Scan at T-22 ---> Track Performance to T_0 (1 Month Forward)

[----------------------- T-5 Data Window -----------------------]
                                                                |
                                                       Run Scan at T-5 ---> Track Performance to T_0 (1 Week Forward)

[----------------------------- Full Dataset to T_0 -----------------------------]
                                                                                |
                                                                       Run Live Scan at T_0 (Today's Top 10)
```

### 3.1 Point-in-Time Array Slicing
For a test execution at cutoff date $T_{	ext{cut}} \in \{T_{-5}, T_{-22}\}$:
1. Slice price matrix: $D_{	ext{sim}} = D[:, :T_{	ext{cut}}]$.
2. Compute all technical indicators (SMAs, ATR, High/Low lookbacks, RS against benchmark) exclusively on $D_{	ext{sim}}$.
3. Isolate the historical Top-10 recommendation basket $\mathcal{B}(T_{	ext{cut}})$.

### 3.2 Performance & Alpha Metrics
Track forward returns from signal generation date $T_{	ext{cut}}$ to the current evaluation date $T_0$:

* **Individual Forward Return:**
  $$R_i(T_{	ext{cut}} 	o T_0) = rac{	ext{Close}_i(T_0) - 	ext{Close}_i(T_{	ext{cut}})}{	ext{Close}_i(T_{	ext{cut}})}$$
* **Portfolio Mean Return:**
  $$ar{R}_{\mathcal{B}}(T_{	ext{cut}} 	o T_0) = rac{1}{10} \sum_{i=1}^{10} R_i(T_{	ext{cut}} 	o T_0)$$
* **Benchmark Forward Return:**
  $$R_{	ext{SPY}}(T_{	ext{cut}} 	o T_0) = rac{	ext{Close}_{	ext{SPY}}(T_0) - 	ext{Close}_{	ext{SPY}}(T_{	ext{cut}})}{	ext{Close}_{	ext{SPY}}(T_{	ext{cut}})}$$
* **Basket Alpha:**
  $$lpha(T_{	ext{cut}} 	o T_0) = ar{R}_{\mathcal{B}}(T_{	ext{cut}} 	o T_0) - R_{	ext{SPY}}(T_{	ext{cut}} 	o T_0)$$
* **Win Rate:**
  $$	ext{WR} = rac{\sum_{i=1}^{10} \mathbb{I}\left(R_i(T_{	ext{cut}} 	o T_0) > 0ight)}{10} 	imes 100\%$$
* **Maximum In-Period Drawdown:**
  $$	ext{MDD}_i = \min_{t \in [T_{	ext{cut}}, T_0]} \left( rac{	ext{Low}_i(t) - 	ext{Close}_i(T_{	ext{cut}})}{	ext{Close}_i(T_{	ext{cut}})} ight)$$

---

## 4. Free & Open-Source Tech Stack Specification

| Component | Technology | Purpose / Configuration |
| :--- | :--- | :--- |
| **Runtime** | Python 3.11+ | Core calculation and orchestration engine |
| **Market Directory** | [NASDAQ Trader FTP](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs) | Public daily raw symbol lists (`nasdaqlisted.txt`, `otherlisted.txt`) |
| **Price/Volume Feed** | [yfinance](https://github.com/ranaroussi/yfinance) / [OpenBB](https://github.com/OpenBB-finance/OpenBB) | 2-year EOD adjusted OHLCV data ingestion |
| **Analytics Engine** | `pandas`, `numpy`, `pandas-ta` | Vectorized indicator math and matrix operations |
| **Local Storage** | SQLite (`market_cache.db`) | Local caching of daily bars to prevent rate limiting |
| **Presentation Layer** | [Streamlit](https://streamlit.io/) | Interactive dashboard with tabular metrics & equity curves |
| **Scheduler** | Cron / Windows Task Scheduler | Automated execution at 5:00 PM EST (Post-market close) |

---

## 5. Data Flow & Batch Processing Architecture

```
                                  [ CRON TRIGGER: 17:00 EST ]
                                                |
                                                v
                             +-------------------------------------+
                             | 1. Download Master Symbol Directory |
                             |    (NASDAQ FTP / SEC Listings)      |
                             +------------------+------------------+
                                                |
                                                v
                             +-------------------------------------+
                             | 2. Sync Local SQLite Cache          |
                             |    - Identify missing dates         |
                             |    - Chunked batch API downloads    |
                             |      (100 tickers / request)        |
                             +------------------+------------------+
                                                |
                                                v
                             +-------------------------------------+
                             | 3. Vectorized Indicator Matrix      |
                             |    - Compute SMAs (50, 150, 200)    |
                             |    - Compute ATR14, 52W High/Low    |
                             |    - Compute 10-Day Tightness       |
                             |    - Compute Relative Strength vs SPY|
                             +------------------+------------------+
                                                |
                                                v
                             +-------------------------------------+
                             | 4. Execute Point-in-Time Runs       |
                             |    - T_0   (Live Recommendations)   |
                             |    - T-5   (1-Week Validation)      |
                             |    - T-22  (1-Month Validation)     |
                             +------------------+------------------+
                                                |
                                                v
                             +-------------------------------------+
                             | 5. Generate UI & Alert Artifacts    |
                             |    - Render Streamlit Dashboard     |
                             |    - Export CSV / JSON Summary      |
                             +-------------------------------------+
```

---

## 6. Output Schemas & UI Dashboard Mockups

### 6.1 View A: Live Top-10 Recommendations ($T_0$)
*Sorted by Composite Score ($S_i$)*

| Rank | Ticker | Sector | Close ($) | 20D ADV ($M) | RS Score (Percentile) | Tightness Ratio | % Off 52W High | Setup Notes |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `SYM1` | Technology | 142.50 | $85.4M | 99.2 | 0.82 | -2.1% | VCP 3rd Contraction |
| 2 | `SYM2` | Industrials | 68.20 | $34.1M | 98.5 | 0.95 | -1.4% | Consolidation at 52W High |
| 3 | `SYM3` | Energy | 94.10 | $52.0M | 97.1 | 1.10 | -3.8% | 50-Day SMA Pullback |
| 4 | `SYM4` | Health Care | 215.00 | $120.5M | 96.4 | 1.15 | -0.8% | Multi-Month Cup Base |
| 5 | `SYM5` | Technology | 55.40 | $28.3M | 95.8 | 1.22 | -4.5% | Tight Flag Pattern |
| 6 | `SYM6` | Consumer Disc | 182.30 | $64.0M | 94.9 | 1.28 | -3.2% | Volume Dry-Up on Handle |
| 7 | `SYM7` | Financials | 88.90 | $41.2M | 94.1 | 1.35 | -2.7% | Stage 2 MA Alignment |
| 8 | `SYM8` | Industrials | 112.75 | $39.8M | 93.5 | 1.40 | -4.9% | Bollinger Squeeze in Band |
| 9 | `SYM9` | Technology | 310.20 | $210.0M | 92.8 | 1.44 | -1.9% | Institutional Accumulation |
| 10 | `SYM10`| Basic Materials| 47.60 | $22.4M | 91.9 | 1.48 | -5.1% | High Relative Volume |

### 6.2 View B: 1-Week-Ago Simulation ($T_{-5}$)
*Validation of scan results generated exactly 5 trading days ago.*

| Rank | Ticker | Entry Price ($T_{-5}$) | Current Price ($T_0$) | Return (%) | SPY Return (%) | Alpha (%) | Max Drawdown (%) | Win/Loss |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `T5_A` | $105.00 | $112.35 | +7.00% | +1.20% | +5.80% | -1.10% | Win |
| 2 | `T5_B` | $42.50 | $44.20 | +4.00% | +1.20% | +2.80% | -0.50% | Win |
| 3 | `T5_C` | $88.10 | $86.50 | -1.82% | +1.20% | -3.02% | -2.40% | Loss |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |
| 10 | `T5_J` | $230.00 | $241.50 | +5.00% | +1.20% | +3.80% | -0.80% | Win |
| **Avg**| **Top 10** | -- | -- | **+4.25%** | **+1.20%** | **+3.05%** | **-1.22%** | **80% Win Rate** |

### 6.3 View C: 1-Month-Ago Simulation ($T_{-22}$)
*Validation of scan results generated exactly 22 trading days ago.*

| Rank | Ticker | Entry Price ($T_{-22}$) | Current Price ($T_0$) | Return (%) | SPY Return (%) | Alpha (%) | Max Drawdown (%) | Win/Loss |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `T22_A` | $85.00 | $102.00 | +20.00% | +3.50% | +16.50% | -2.80% | Win |
| 2 | `T22_B` | $150.00 | $163.50 | +9.00% | +3.50% | +5.50% | -3.10% | Win |
| 3 | `T22_C` | $35.20 | $33.00 | -6.25% | +3.50% | -9.75% | -7.50% | Loss |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |
| 10 | `T22_J` | $190.00 | $212.80 | +12.00% | +3.50% | +8.50% | -4.00% | Win |
| **Avg**| **Top 10** | -- | -- | **+11.40%** | **+3.50%** | **+7.90%** | **-3.85%** | **70% Win Rate** |

---

## 7. Engineering & Implementation Roadmap

1. **Sprint 1: Universe & Ingestion Pipeline**
   * Implement automated parser for NASDAQ FTP ticker symbols (`nasdaqlisted.txt`, `otherlisted.txt`).
   * Build multi-threaded, rate-limited batch downloader with `yfinance` caching into local SQLite database.
   * Write validation tests for non-operating stock filtering (ignoring warrants, units, test tickets).

2. **Sprint 2: Vectorized Screening & Ranking Engine**
   * Implement Stage 1–3 criteria with vectorized `pandas` operations.
   * Build Relative Strength vs. `SPY` multi-timeframe scoring matrix.
   * Implement Composite Score sorting to yield top 10 recommendations.

3. **Sprint 3: Point-in-Time Simulation Framework**
   * Build the time-sliced indexer enforcing zero lookahead bias at $T_{-5}$ and $T_{-22}$.
   * Implement forward return and benchmark alpha tracking calculators.
   * Compute portfolio win-rate and max drawdown statistics.

4. **Sprint 4: Streamlit UI & Automated Reporting**
   * Build clean Streamlit frontend rendering View A (Today's Top 10), View B (1-Week Backtest), and View C (1-Month Backtest).
   * Add color-coded indicators for outperforming alpha.
   * Implement automated local CSV export for offline review.
