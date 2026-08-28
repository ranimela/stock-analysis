import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
import datetime

sys.path.insert(0, os.path.abspath('.'))

from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor

print('=== ADVERSARIAL SUITE 3: Single Ticker Sync & DuckDB Exchange Integrity ===')

def make_test_df(ticker: str, dates: list[str], price: float = 100.0) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    data = {
        ('Open', ticker): [price]*len(idx),
        ('High', ticker): [price + 2.0]*len(idx),
        ('Low', ticker): [price - 2.0]*len(idx),
        ('Close', ticker): [price + 1.0]*len(idx),
        ('Adj Close', ticker): [price + 1.0]*len(idx),
        ('Volume', ticker): [50000]*len(idx),
    }
    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df

with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = Path(tmp_dir) / 'test_exchange_sync.duckdb'
    db = DatabaseManager(db_path)
    ingestor = DataIngestor(db_manager=db)
    
    dates = ['2026-08-01', '2026-08-02', '2026-08-03']
    
    # 3.1: Sync standard TASE ticker
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('TEVA.TA', dates, 6500.0)):
        ok = ingestor.sync_single_ticker('TEVA.TA')
        assert ok is True, 'TEVA.TA sync returned False'
        
    # 3.2: Sync lowercase with whitespace
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('LUMI.TA', dates, 3200.0)):
        ok = ingestor.sync_single_ticker('  lumi.ta  ')
        assert ok is True, 'lumi.ta sync returned False'
        
    # 3.3: Sync mixed case TASE ticker
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('NICE.TA', dates, 78000.0)):
        ok = ingestor.sync_single_ticker('Nice.Ta')
        assert ok is True, 'Nice.Ta sync returned False'
        
    # 3.4: Sync US Tickers
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('AAPL', dates, 220.0)):
        ok = ingestor.sync_single_ticker('AAPL')
        assert ok is True, 'AAPL sync returned False'
        
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('MSFT', dates, 450.0)):
        ok = ingestor.sync_single_ticker('msft')
        assert ok is True, 'msft sync returned False'

    # 3.5: Sync benchmark ticker
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=make_test_df('^TA125.TA', dates, 2100.0)):
        ok = ingestor.sync_single_ticker('^ta125.ta')
        assert ok is True, '^ta125.ta sync returned False'

    # Verify DuckDB symbol_metadata entries
    meta_rows = db.execute_read('SELECT ticker, exchange, asset_class, is_active FROM symbol_metadata ORDER BY ticker;')
    meta_dict = {r[0]: (r[1], r[2], r[3]) for r in meta_rows}
    
    assert meta_dict['TEVA.TA'] == ('TASE', 'Common Stock', True)
    assert meta_dict['LUMI.TA'] == ('TASE', 'Common Stock', True)
    assert meta_dict['NICE.TA'] == ('TASE', 'Common Stock', True)
    assert meta_dict['^TA125.TA'] == ('TASE', 'Index', True)
    
    assert meta_dict['AAPL'] == ('NASDAQ', 'Common Stock', True)
    assert meta_dict['MSFT'] == ('NASDAQ', 'Common Stock', True)
    
    print(f'[PASS] 3.1-3.5: All {len(meta_dict)} symbol metadata records correctly tagged in DuckDB')
    
    # 3.6: Verify daily_bars row counts and uppercase tickers
    bars_rows = db.execute_read('SELECT ticker, count(*), MIN(close), MAX(close) FROM daily_bars GROUP BY ticker ORDER BY ticker;')
    assert len(bars_rows) == 6, f'Expected 6 tickers in daily_bars, got {len(bars_rows)}'
    for ticker, count, min_c, max_c in bars_rows:
        assert count == 3, f'Expected 3 bars for {ticker}, got {count}'
        assert ticker == ticker.upper(), f'Ticker not uppercase: {ticker}'
    print('[PASS] 3.6: All daily_bars inserted with uppercase tickers and correct bar counts')
    
    # 3.7: Test sync_single_ticker failure resilience (empty response)
    with patch.object(ingestor, 'fetch_ticker_chunk', return_value=pd.DataFrame()):
        fail_ok = ingestor.sync_single_ticker('NONEXISTENT.TA')
        assert fail_ok is False, 'Expected False for empty ticker download'
        
        # Verify daily_bars was not corrupted
        post_fail_count = db.execute_read('SELECT count(*) FROM daily_bars;')[0][0]
        assert post_fail_count == 18, f'Expected 18 bars, got {post_fail_count}'
    print('[PASS] 3.7: sync_single_ticker handles empty responses gracefully without DB corruption')
