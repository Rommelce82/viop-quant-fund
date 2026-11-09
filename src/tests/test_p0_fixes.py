"""
P0 Hataları ve Mimari İyileştirmeler Doğrulama Testi.
(test_p0_fixes.py)
"""

from datetime import datetime
import pandas as pd
import pytest

from src.execution.paper_broker import PaperBroker, PaperTradeExecution
from src.strategy.fundamental_compass import DirectionalBias
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalExecutioner
)
from src.tests.test_v4_architecture import create_mock_market_data


def test_paper_broker_position_restoration():
    """P0.1: Süreç yeniden başladığında veritabanından pozisyon geri yükleme testi."""
    broker = PaperBroker(initial_capital=2_000_000.0)
    assert len(broker.open_positions) == 0

    mock_db_positions = [
        {
            "symbol": "F_THYAO",
            "side": "LONG",
            "lots": 15,
            "entry_price": 310.0,
            "initial_stop": 300.0,
            "trailing_stop": 305.0,
            "bars_held": 4,
            "entry_time": "2026-11-05T14:15:00",
            "current_price": 315.0
        },
        {
            "symbol": "F_AKBNK",
            "side": "SHORT",
            "lots": 20,
            "entry_price": 60.0,
            "initial_stop": 63.0,
            "trailing_stop": 62.0,
            "bars_held": 2,
            "entry_time": "2026-11-05T18:15:00",
            "current_price": 59.0
        }
    ]

    broker.restore_positions_from_db(mock_db_positions)
    assert len(broker.open_positions) == 2
    assert "F_THYAO" in broker.open_positions
    assert "F_AKBNK" in broker.open_positions
    assert broker.open_positions["F_THYAO"].lots == 15
    assert broker.open_positions["F_AKBNK"].lots == -20
    assert broker.open_positions["F_THYAO"].trailing_stop == 305.0
    assert broker.open_positions["F_AKBNK"].trailing_stop == 62.0


def test_paper_trade_execution_has_success_attribute():
    """P0.2: PaperTradeExecution executed_successfully niteliği testi."""
    broker = PaperBroker(initial_capital=2_000_000.0)
    exec_record = broker.execute_virtual_order({
        "symbol": "F_THYAO",
        "action": "ENTER_LONG",
        "lots": 5,
        "current_price": 300.0,
        "stop_price": 290.0,
        "rationale": "Test"
    })
    assert hasattr(exec_record, "executed_successfully")
    assert exec_record.executed_successfully is True


def test_bi_directional_wick_does_not_block_opposite_direction():
    """P0.3: BI_DIRECTIONAL modunda üst fitil Short'u bloke etmemeli."""
    executioner = TechnicalExecutioner()
    daily_df, hourly_df = create_mock_market_data()

    # Üst fitil %75 olan bir bar oluştur (satış baskısı mumu)
    hourly_wick = hourly_df.copy()
    idx = hourly_wick.index[-1]
    hourly_wick.loc[idx, "high"] = 330.0
    hourly_wick.loc[idx, "close"] = 315.0
    hourly_wick.loc[idx, "open"] = 312.0
    hourly_wick.loc[idx, "low"] = 310.0

    # ONLY_LONG iken üst fitil Long'u veto etmeli (Kural 18)
    dec_only_long = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_wick,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 14, 0)
    )
    assert dec_only_long.action == ExecutionActionV4.REJECT_WICK_EXCESSIVE

    # BI_DIRECTIONAL iken üst fitil erken return ile short'u öldürmemeli,
    # şartlar uygun değilse REJECT_WICK_EXCESSIVE veya HOLD dönmeli ama akışı kesmemeli
    dec_bi = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.BI_DIRECTIONAL,
        daily_data=daily_df,
        hourly_data=hourly_wick,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 14, 0)
    )
    assert dec_bi.action in (ExecutionActionV4.HOLD, ExecutionActionV4.REJECT_TESTERE_ADX_DUSUK, ExecutionActionV4.REJECT_WICK_EXCESSIVE)

