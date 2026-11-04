"""
Veritabanı Yöneticisi (src/database/db_manager.py).

Sistemin durumunu, açık pozisyonlarını, kâr eğrisini ve işlem geçmişini
SQLite üzerinde kalıcı olarak saklar. 7/24 bulut ortamında Dashboard ve
çalışma döngüleri bu veritabanı üzerinden senkronize olur.
"""

from datetime import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd


class DatabaseManager:
    """
    SQLite Tabanlı Kalıcı Durum ve Metrik Yöneticisi.
    """

    def __init__(self, db_path: str = "viop_trading.db") -> None:
        self.db_path = db_path
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        """Tabloları oluşturur."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Sistem Durumu Tablosu (NAV, Serbest Teminat, Mod, Devre Kesici)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_nav REAL NOT NULL,
                    free_margin REAL NOT NULL,
                    daily_pnl REAL NOT NULL,
                    daily_return_pct REAL NOT NULL,
                    trading_mode TEXT NOT NULL,
                    consecutive_losses INTEGER NOT NULL,
                    circuit_breaker_active INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 2. Açık Pozisyonlar Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    initial_stop REAL NOT NULL,
                    trailing_stop REAL NOT NULL,
                    pnl_try REAL NOT NULL,
                    r_multiple REAL NOT NULL,
                    bars_held INTEGER NOT NULL,
                    entry_time TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 3. Kâr Eğrisi Geçmişi (Equity Curve)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equity_curve (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    nav REAL NOT NULL,
                    sma20 REAL NOT NULL,
                    mode TEXT NOT NULL
                )
            """)

            # 4. Kapanan İşlem Geçmişi (Trade History)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    pnl_try REAL NOT NULL,
                    r_multiple REAL NOT NULL,
                    exit_reason TEXT NOT NULL
                )
            """)

            # 5. Bekleyen Limit Emirler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    lots INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL
                )
            """)

            # 6. VİOP Sözleşmeler Listesi (Günde 1 Kez - Sabah 08:30)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS viop_contracts (
                    contract_code TEXT PRIMARY KEY,
                    underlying_symbol TEXT NOT NULL,
                    asset_category TEXT NOT NULL,
                    contract_size REAL NOT NULL,
                    expiry_month INTEGER NOT NULL,
                    expiry_year INTEGER NOT NULL,
                    initial_margin_try REAL NOT NULL,
                    maintenance_margin_try REAL NOT NULL,
                    is_active INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 7. VİOP Teminat Tutarları (Günde 2 Kez - 09:00 ve 14:00)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS viop_margins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_code TEXT NOT NULL,
                    initial_margin_try REAL NOT NULL,
                    maintenance_margin_try REAL NOT NULL,
                    session_window TEXT NOT NULL,
                    margin_change_pct REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 8. Margin Call / Teminat Tamamlama Çağrıları (15 Dk Pasif + Bar Kapanışları)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS viop_margin_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    account_equity REAL NOT NULL,
                    total_initial_margin REAL NOT NULL,
                    total_maintenance_margin REAL NOT NULL,
                    free_margin REAL NOT NULL,
                    margin_ratio_pct REAL NOT NULL,
                    margin_deficit_try REAL NOT NULL,
                    status TEXT NOT NULL,
                    check_type TEXT NOT NULL,
                    liquidation_required INTEGER NOT NULL,
                    target_liquidation_symbol TEXT
                )
            """)

            # 9. ALE Fonu Net Nema Hesabı (Seans Sonu 18:15)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ale_fund_eod (
                    date_str TEXT PRIMARY KEY,
                    idle_cash_try REAL NOT NULL,
                    annual_gross_rate REAL NOT NULL,
                    daily_gross_yield_try REAL NOT NULL,
                    withholding_tax_try REAL NOT NULL,
                    daily_net_yield_try REAL NOT NULL,
                    cumulative_ale_vault_try REAL NOT NULL,
                    calculated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def record_system_state(
        self,
        total_nav: float,
        free_margin: float,
        daily_pnl: float,
        daily_return_pct: float,
        trading_mode: str,
        consecutive_losses: int,
        circuit_breaker_active: bool,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Sistem anlık durumunu kaydeder."""
        ts_str = (timestamp or datetime.now()).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO system_state (
                    timestamp, total_nav, free_margin, daily_pnl,
                    daily_return_pct, trading_mode, consecutive_losses,
                    circuit_breaker_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts_str, total_nav, free_margin, daily_pnl,
                daily_return_pct, trading_mode, consecutive_losses,
                1 if circuit_breaker_active else 0, ts_str
            ))
            conn.commit()

    def record_equity_point(
        self,
        nav: float,
        sma20: float,
        mode: str,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Kâr eğrisi noktası kaydeder."""
        ts_str = (timestamp or datetime.now()).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO equity_curve (timestamp, nav, sma20, mode)
                VALUES (?, ?, ?, ?)
            """, (ts_str, nav, sma20, mode))
            conn.commit()

    def sync_active_positions(self, positions: List[Dict[str, Any]]) -> None:
        """Açık pozisyonlar tablosunu günceller."""
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM active_positions")
            for p in positions:
                cursor.execute("""
                    INSERT OR REPLACE INTO active_positions (
                        symbol, side, lots, entry_price, current_price,
                        initial_stop, trailing_stop, pnl_try, r_multiple,
                        bars_held, entry_time, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["symbol"], p["side"], p["lots"], p["entry_price"],
                    p["current_price"], p["initial_stop"], p["trailing_stop"],
                    p["pnl_try"], p["r_multiple"], p["bars_held"],
                    str(p.get("entry_time", now_str)), now_str
                ))
            conn.commit()

    def record_trade(self, trade_data: Dict[str, Any]) -> None:
        """Kapanan işlemi kaydeder."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_history (
                    trade_id, symbol, side, lots, entry_price, exit_price,
                    entry_time, exit_time, pnl_try, r_multiple, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data["trade_id"], trade_data["symbol"], trade_data["side"],
                trade_data["lots"], trade_data["entry_price"], trade_data["exit_price"],
                str(trade_data["entry_time"]), str(trade_data["exit_time"]),
                trade_data["pnl_try"], trade_data["r_multiple"], trade_data["exit_reason"]
            ))
            conn.commit()

    def get_latest_system_state(self) -> Optional[Dict[str, Any]]:
        """En son sistem durumunu döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM system_state ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Mevcut açık pozisyonları döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_positions ORDER BY symbol ASC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_equity_curve_df(self, limit: int = 100) -> pd.DataFrame:
        """Kâr eğrisi verisini DataFrame olarak döner."""
        with self._get_connection() as conn:
            query = f"SELECT timestamp, nav, sma20, mode FROM equity_curve ORDER BY id DESC LIMIT {limit}"
            df = pd.read_sql_query(query, conn)
            if not df.empty:
                df = df.iloc[::-1].reset_index(drop=True)
            return df

    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Geçmiş işlemleri döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM trade_history ORDER BY exit_time DESC LIMIT {limit}")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def record_viop_contracts(self, contracts: List[Dict[str, Any]], purge_missing: bool = True) -> None:
        """VİOP sözleşmeler listesini günceller (08:30)."""
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if purge_missing and contracts:
                valid_codes = [c["contract_code"] for c in contracts]
                placeholders = ",".join(["?"] * len(valid_codes))
                cursor.execute(f"UPDATE viop_contracts SET is_active = 0 WHERE contract_code NOT IN ({placeholders})", valid_codes)
            for c in contracts:
                cursor.execute("""
                    INSERT OR REPLACE INTO viop_contracts (
                        contract_code, underlying_symbol, asset_category,
                        contract_size, expiry_month, expiry_year,
                        initial_margin_try, maintenance_margin_try, is_active, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c["contract_code"], c["underlying_symbol"], c["asset_category"],
                    c["contract_size"], c["expiry_month"], c["expiry_year"],
                    c["initial_margin_try"], c["maintenance_margin_try"],
                    1 if c.get("is_active", True) else 0, now_str
                ))
            conn.commit()

    def get_viop_contracts(self) -> List[Dict[str, Any]]:
        """Tüm aktif VİOP sözleşmelerini döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM viop_contracts WHERE is_active = 1 ORDER BY asset_category, contract_code")
            return [dict(r) for r in cursor.fetchall()]

    def record_viop_margins(self, margins: List[Dict[str, Any]], session_window: str = "09:00_OPEN") -> None:
        """VİOP teminat tutarlarını kaydeder (09:00 ve 14:00)."""
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for m in margins:
                cursor.execute("""
                    INSERT INTO viop_margins (
                        contract_code, initial_margin_try, maintenance_margin_try,
                        session_window, margin_change_pct, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    m["contract_code"], m["initial_margin_try"], m["maintenance_margin_try"],
                    session_window, m.get("margin_change_pct", 0.0), now_str
                ))
            conn.commit()

    def get_latest_margins(self) -> Dict[str, Dict[str, Any]]:
        """Her aktif sözleşme için en güncel teminat bilgisini döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.* FROM viop_margins m
                INNER JOIN (
                    SELECT contract_code, MAX(id) as max_id
                    FROM viop_margins
                    GROUP BY contract_code
                ) latest ON m.id = latest.max_id
                LEFT JOIN viop_contracts vc ON m.contract_code = vc.contract_code
                WHERE vc.is_active = 1 OR vc.is_active IS NULL
            """)
            rows = cursor.fetchall()
            return {r["contract_code"]: dict(r) for r in rows}

    def record_margin_call_event(self, report: Dict[str, Any]) -> None:
        """Margin Call denetim raporunu kaydeder."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO viop_margin_calls (
                    timestamp, account_equity, total_initial_margin,
                    total_maintenance_margin, free_margin, margin_ratio_pct,
                    margin_deficit_try, status, check_type,
                    liquidation_required, target_liquidation_symbol
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(report.get("timestamp", datetime.now().isoformat())),
                report["account_equity"], report["total_initial_margin"],
                report["total_maintenance_margin"], report["free_margin"],
                report["margin_ratio_pct"], report.get("margin_deficit_try", 0.0),
                report["status"], report["check_type"],
                1 if report.get("liquidation_required", False) else 0,
                report.get("target_liquidation_symbol")
            ))
            conn.commit()

    def get_latest_margin_call(self) -> Optional[Dict[str, Any]]:
        """En son Margin Call denetimini döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM viop_margin_calls ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def record_ale_eod(self, report: Dict[str, Any]) -> None:
        """Seans sonu (18:15) ALE net nema raporunu kaydeder."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ale_fund_eod (
                    date_str, idle_cash_try, annual_gross_rate,
                    daily_gross_yield_try, withholding_tax_try,
                    daily_net_yield_try, cumulative_ale_vault_try, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report["date_str"], report["idle_cash_try"], report["annual_gross_rate"],
                report["daily_gross_yield_try"], report["withholding_tax_try"],
                report["daily_net_yield_try"], report["cumulative_ale_vault_try"],
                str(report.get("calculated_at", datetime.now().isoformat()))
            ))
            conn.commit()

    def get_latest_ale_eod(self) -> Optional[Dict[str, Any]]:
        """En son gün sonu ALE nema kaydını döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ale_fund_eod ORDER BY date_str DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

