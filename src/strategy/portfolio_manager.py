"""
Portföy Yöneticisi ve Ali Perşembe Risk Motoru (src/strategy/portfolio_manager.py).

Ali Perşembe Doktrini Risk ve Portföy Kuralları:
1. SECTOR_MAP: Varlık sektör eşleştirmesi (Örn: F_AKBNK -> BANKA, F_THYAO -> HAVACILIK, F_XU030 -> ENDEKS).
2. Korelasyon Sınırı: Toplam portföyde en fazla 5 pozisyon, aynı sektörden en fazla 2 pozisyon.
3. Anti-Martingale (Losing Streak): Üst üste 4 stop varsa risk bütçesi %2'den %1'e düşürülür.
4. Whipsaw Kalkanı: Aynı gün aynı varlıkta hem Long hem Short stop olunursa varlık gün sonuna kadar kilitlenir.
5. Devre Kesici (Circuit Breaker): Günlük NAV düşüşü >= %4 ise tüm yeni işlemler durdurulur.
6. Limit Emir Zaman Aşımı (Cancel-on-Bar-Close): Pasif limit emir bar kapandığında dolmamışsa iptal edilir.
7. Kâr Eğrisi (Equity Curve) ve Otonom Mod Geçişi:
   - Portföy kâr eğrisi SMA20'sinin altına inerse PAPER_TRADE moduna geçer.
   - Sanal kâr eğrisi tekrar SMA20 üzerine çıkarsa LIVE_TRADING moduna döner.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd


class TradingMode(str, Enum):
    """Sistem Çalışma Modu."""
    LIVE_TRADING = "LIVE_TRADING"
    PAPER_TRADE = "PAPER_TRADE"


# Statik Sektör Haritası (Ali Perşembe Doktrini)
SECTOR_MAP: Dict[str, str] = {
    "F_THYAO": "HAVACILIK",
    "F_PGSUS": "HAVACILIK",
    "F_AKBNK": "BANKA",
    "F_GARAN": "BANKA",
    "F_ISCTR": "BANKA",
    "F_YKBNK": "BANKA",
    "F_KCHOL": "HOLDING",
    "F_SAHOL": "HOLDING",
    "F_SISE": "CAM_SANAYI",
    "F_EREGL": "DEMIR_CELIK",
    "F_KRDMD": "DEMIR_CELIK",
    "F_BIMAS": "PERAKENDE",
    "F_TCELL": "TELEKOM",
    "F_TUPRS": "PETROKIMYA",
    "F_PETKM": "PETROKIMYA",
    "F_ASELS": "SAVUNMA",
    "F_XU030": "ENDEKS",
    "USDTRY": "DOVIZ",
    "XAUUSD": "EMTIA"
}


@dataclass
class PendingLimitOrder:
    """Bekleyen Limit Emir Modeli."""
    order_id: str
    symbol: str
    side: str
    price: float
    lots: int
    created_bar_time: datetime
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED


@dataclass
class PortfolioRiskState:
    """Portföy Risk ve Kâr Eğrisi Durumu."""
    current_nav: float = 2_000_000.0
    initial_nav: float = 2_000_000.0
    day_start_nav: float = 2_000_000.0
    current_date: Optional[date] = None
    consecutive_losses: int = 0
    trading_mode: TradingMode = TradingMode.LIVE_TRADING
    
    # Kâr eğrisi geçmişi (SMA20 kontrolü için)
    equity_curve: List[float] = field(default_factory=lambda: [2_000_000.0])
    
    # Whipsaw takibi: (date, symbol) -> set of sides stopped out ("LONG", "SHORT")
    stopped_sides_today: Dict[str, Set[str]] = field(default_factory=dict)
    
    # Aktif açık pozisyonlar: symbol -> position_dict
    active_positions: Dict[str, Dict[str, any]] = field(default_factory=dict)
    
    # Bekleyen limit emirler
    pending_orders: Dict[str, PendingLimitOrder] = field(default_factory=dict)


class PortfolioRiskManager:
    """
    Ali Perşembe Doktrini Portföy ve Risk Yöneticisi (Otonom Algoritmik Mod).
    """

    MAX_TOTAL_POSITIONS = 100  # İnsan sınırlamaları kaldırıldı (Algoritmik tam evren icrası)
    MAX_SECTOR_POSITIONS = 50   # Sektör sınırlamaları serbest bırakıldı
    MAX_DAILY_DRAWDOWN_PCT = 0.04  # %4 Günlük Devre Kesici
    EQUITY_SMA_PERIOD = 20

    def __init__(self, initial_capital: float = 2_000_000.0) -> None:
        self.state = PortfolioRiskState(
            current_nav=initial_capital,
            initial_nav=initial_capital,
            day_start_nav=initial_capital
        )

    def update_day_boundary(self, current_dt: datetime, current_nav: float) -> None:
        """Gün dönümünde günlük sayaçları ve devre kesici referansını günceller."""
        cur_d = current_dt.date() if isinstance(current_dt, datetime) else current_dt
        if self.state.current_date is None or cur_d != self.state.current_date:
            self.state.current_date = cur_d
            self.state.day_start_nav = current_nav
            self.state.stopped_sides_today.clear()

        self.state.current_nav = current_nav
        self.state.equity_curve.append(current_nav)

        # Kâr eğrisi SMA20 kontrolü ve mod geçişi
        self._evaluate_equity_curve_mode()

    def _evaluate_equity_curve_mode(self) -> None:
        """
        Kâr Eğrisi SMA20 Kontrolü:
        - Portföy kâr eğrisi SMA20 altına inerse -> PAPER_TRADE
        - Sanal kâr eğrisi tekrar SMA20 üzerine çıkarsa -> LIVE_TRADING
        """
        curve = self.state.equity_curve
        if len(curve) >= self.EQUITY_SMA_PERIOD:
            sma20 = sum(curve[-self.EQUITY_SMA_PERIOD:]) / float(self.EQUITY_SMA_PERIOD)
            latest_nav = curve[-1]
            if latest_nav < sma20 and self.state.trading_mode == TradingMode.LIVE_TRADING:
                self.state.trading_mode = TradingMode.PAPER_TRADE
            elif latest_nav >= sma20 and self.state.trading_mode == TradingMode.PAPER_TRADE:
                self.state.trading_mode = TradingMode.LIVE_TRADING

    def check_circuit_breaker(self) -> Tuple[bool, str]:
        """
        Günlük NAV Düşüşü Devre Kesici Kontrolü (>= %4).
        """
        if self.state.day_start_nav <= 0:
            return False, "Geçersiz başlangıç NAV."

        daily_drawdown = (self.state.day_start_nav - self.state.current_nav) / self.state.day_start_nav
        if daily_drawdown >= self.MAX_DAILY_DRAWDOWN_PCT:
            return True, f"DEVRE KESİCİ DEVREDE: Günlük düşüş %{daily_drawdown*100:.2f} >= %4.0. Tüm işlemler durduruldu."
        return False, f"Günlük kayıp güvenli sınırda (%{daily_drawdown*100:.2f})."

    def get_risk_budget_pct(self) -> float:
        """
        Anti-Martingale Kuralı:
        Üst üste 4 stop (Losing Streak) varsa risk bütçesi %2'den %1'e düşürülür.
        """
        if self.state.consecutive_losses >= 4:
            return 0.01  # %1
        return 0.02      # %2

    def record_trade_result(self, pnl: float, symbol: str = "", side: str = "", **kwargs: Any) -> None:
        """İşlem sonucunu (kâr/zarar) ve stop serisini günceller."""
        if pnl < 0:
            self.state.consecutive_losses += 1
            # Whipsaw kalkanı için stop yönünü kaydet
            if symbol:
                if symbol not in self.state.stopped_sides_today:
                    self.state.stopped_sides_today[symbol] = set()
                if side:
                    self.state.stopped_sides_today[symbol].add(side.upper())
        else:
            self.state.consecutive_losses = 0

    def is_whipsaw_locked(self, symbol: str) -> Tuple[bool, str]:
        """
        Whipsaw Kalkanı:
        Aynı gün aynı varlıkta hem LONG hem SHORT stop olunmuşsa varlık gün sonuna kadar kilitlenir.
        """
        stopped = self.state.stopped_sides_today.get(symbol, set())
        if "LONG" in stopped and "SHORT" in stopped:
            return True, f"WHIPSAW KALKANI: {symbol} bugün hem Long hem Short stop oldu. Gün sonuna kadar kilitli."
        return False, "Whipsaw kilidi yok."

    def check_sector_correlation(self, symbol: str) -> Tuple[bool, str]:
        """
        Otonom Algoritmik Mod:
        İnsan işlemciler için konulmuş dar kısıtlar (max 5 pozisyon, max 2 sektör) kaldırılmıştır.
        Tüm kararlar serbest teminat (Free Margin) ve %2 risk bütçesi limitlerine göre yönetilir.
        """
        if len(self.state.active_positions) >= self.MAX_TOTAL_POSITIONS:
            return False, f"PORTFÖY KAPASİTE TAVANI: Aktif {len(self.state.active_positions)} pozisyon dolu."

        return True, "Otonom mod: Pozisyon ve sektör kısıtı yok, serbest teminat ile icra edilebilir."

    def cancel_expired_limit_orders(self, current_bar_time: datetime) -> List[str]:
        """
        Limit Emir Zaman Aşımı (Cancel-on-Bar-Close):
        O saatlik bar kapandığında dolmamış tüm PENDING emirleri iptal eder.
        """
        cancelled_ids = []
        for oid, order in list(self.state.pending_orders.items()):
            if order.status == "PENDING" and order.created_bar_time < current_bar_time:
                order.status = "CANCELLED"
                cancelled_ids.append(oid)
                del self.state.pending_orders[oid]
        return cancelled_ids


class PortfolioRiskManagerV4:
    """
    Ali Perşembe Doktrini Kasa ve Teminat Yöneticisi (v4.0).
    - Bileşik Trade Kasası (trade_vault) + Güvenli ALE Repo Kasası (ale_safe_vault)
    - Sabit Fraksiyonel %2 NAV Riski + Volatilite Ölçekleme (vol_scale) + Margin Cap
    """

    def __init__(self, initial_capital: float = 150_000.0, repo_rate_annual: float = 0.48, withholding_tax_pct: float = 0.175):
        self.trade_vault = initial_capital       # İşletilen Bileşik Trade Kasası
        self.ale_safe_vault = 0.0                # Güvenli ALE Repo Net Neması Kasası
        self.total_gross_nema = 0.0              # Brüt ALE Neması
        self.total_tax_paid = 0.0                # Ödenen %17.5 Stopaj
        self.repo_rate_daily = repo_rate_annual / 365.0
        self.withholding_tax_pct = withholding_tax_pct  # %17.5 Yasal Stopaj Kesintisi
        self.RISK_PER_TRADE_PCT = 0.02          # Sabit Fraksiyonel %2 Risk

    def update_overnight_nema(self, total_margin_locked: float) -> float:
        """
        Her seans sonu boştaki serbest nakit ALE fonunda nemalandırılır.
        Brüt getiriden %17.5 yasal stopaj kesilerek NET nema risksiz kasaya eklenir.
        """
        free_cash = max(0.0, self.trade_vault - total_margin_locked)
        daily_gross = free_cash * self.repo_rate_daily
        daily_tax = daily_gross * self.withholding_tax_pct
        daily_net = daily_gross - daily_tax

        self.total_gross_nema += daily_gross
        self.total_tax_paid += daily_tax
        self.ale_safe_vault += daily_net # Yalnızca NET nema risksiz kasaya aktarılır
        return daily_net

    def get_consolidated_nav(self) -> float:
        """Konsolide Toplam Portföy NAV Değeri (Trade Kasası + ALE Net Kasası)."""
        return self.trade_vault + self.ale_safe_vault

    def calculate_lots(
        self,
        entry_price: float,
        stop_price: float,
        contract_multiplier: float,
        initial_margin_try: float,
        vol_scale: float = 1.0
    ) -> int:
        """Sabit Fraksiyonel %2 NAV Lot Formülü + Volatilite Ölçekleme + Margin Cap."""
        consolidated_nav = self.get_consolidated_nav()
        risk_budget_try = consolidated_nav * self.RISK_PER_TRADE_PCT # NAV * 0.02
        
        risk_per_contract = abs(entry_price - stop_price) * contract_multiplier
        if risk_per_contract <= 0:
            return 0

        # Raw Lot Hesabı
        raw_lots = (risk_budget_try / risk_per_contract) * vol_scale
        ideal_lots = math.floor(raw_lots)

        # Margin Cap (Serbest Teminat Sınırı)
        max_lots_by_margin = math.floor(self.trade_vault / initial_margin_try) if initial_margin_try > 0 else 0
        
        # Asgari 1 Lot Güvencesi (%3.5 Cap'i aşmıyorsa)
        if ideal_lots <= 0 and (risk_per_contract <= consolidated_nav * 0.035) and max_lots_by_margin >= 1:
            ideal_lots = 1

        final_lots = min(ideal_lots, max_lots_by_margin)
        return max(0, final_lots)
