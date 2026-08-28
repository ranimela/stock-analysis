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

print('=== ADVERSARIAL SUITE 4: Malformed Bar Ingestion and Parquet Delta Integrity ===')

with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = Path(tmp_dir) / 'test_malformed.duckdb'
    db = DatabaseManager(db_path)
    ingestor = DataIngestor(db_manager=db)

    # 4.1: MultiIndex DataFrame with partial NaNs
    dates = pd.date_range('2026-08-01', periods=4)
    data = {
        ('Open', 'TEVA.TA'): [100.0, None, 102.0, 103.0],
        ('High', 'TEVA.TA'): [105.0, 106.0, None, 108.0],
        ('Low', 'TEVA.TA'): [95.0, 96.0, 97.0, None],
        ('Close', 'TEVA.TA'): [101.0, 102.0, 103.0, None],
        ('Adj Close', 'TEVA.TA'): [101.0, 102.0, 103.0, None],
        ('Volume', 'TEVA.TA'): [50000, None, 60000, 70000],
    }
    df_multi = pd.DataFrame(data, index=dates)
    df_multi.columns = pd.MultiIndex.from_tuples(df_multi.columns)

    inserted = ingestor.parse_and_store_bars(df_multi, ['TEVA.TA'])
    assert inserted == 3, f'Expected 3 valid rows inserted, got {inserted}'
    
    rows = db.execute_read('SELECT trade_date, open, high, low, close, volume FROM daily_bars WHERE ticker = ? ORDER BY trade_date;', ['TEVA.TA'])
    assert len(rows) == 3
    assert rows[1][1] == 102.0, f'Expected fallback open 102.0, got {rows[1][1]}'
    assert rows[1][5] == 0, f'Expected fallback volume 0, got {rows[1][5]}'
    print('[PASS] 4.1: Handled partial NaNs and fallback logic cleanly (skipped NaN close, filled missing OH/vol)')

    # 4.2: SingleIndex DataFrame with minimal columns matching date range
    df_single = pd.DataFrame({
        'Close': [500.0, 510.0, 520.0],
    }, index=pd.date_range('2026-08-01', periods=3))
    
    inserted_single = ingestor.parse_and_store_bars(df_single, ['LUMI.TA'])
    assert inserted_single == 3, f'Expected 3 rows, got {inserted_single}'
    rows_single = db.execute_read('SELECT ticker, close, open, volume FROM daily_bars WHERE ticker = ? ORDER BY trade_date;', ['LUMI.TA'])
    assert len(rows_single) == 3
    assert rows_single[0] == ('LUMI.TA', 500.0, 500.0, 0)
    print('[PASS] 4.2: Handled SingleIndex minimal DataFrame with graceful column fallbacks')

    # 4.3: Parquet delta export & sync round-trip with TASE tickers
    parquet_dir = Path(tmp_dir) / 'deltas'
    exported_file = ingestor.export_daily_delta_parquet(output_dir=str(parquet_dir))
    assert exported_file is not None, 'Export parquet failed'
    assert Path(exported_file).exists(), f'Parquet file not found: {exported_file}'
    
    p_df = pd.read_parquet(exported_file)
    assert not p_df.empty
    assert set(p_df['ticker'].unique()) == {'TEVA.TA', 'LUMI.TA'}
    print(f'[PASS] 4.3: Exported parquet delta file with {len(p_df)} rows containing both TASE tickers on latest date')

    # Create fresh secondary DB and sync from parquet
    db2_path = Path(tmp_dir) / 'test_replica.duckdb'
    db2 = DatabaseManager(db2_path)
    ingestor2 = DataIngestor(db_manager=db2)
    
    synced_dates = ingestor2.sync_local_db_from_parquet(deltas_dir=str(parquet_dir))
    assert synced_dates == 1, f'Expected 1 synced date, got {synced_dates}'
    
    replica_rows = db2.execute_read('SELECT ticker, count(*) FROM daily_bars GROUP BY ticker ORDER BY ticker;')
    assert len(replica_rows) == 2
    assert replica_rows[0] == ('LUMI.TA', 1)
    assert replica_rows[1] == ('TEVA.TA', 1)
    print('[PASS] 4.4: Parquet delta sync round-trip successfully merged TASE bars into secondary DuckDB')
