"""
Dinamik Pozisyon Boyutlandırma Motoru (Dynamic Position Sizer).

Bu modül;
- Portföy riski yüzdesi (% Risk-per-trade),
- Piyasa Rejimi (Trend, Yatay, Şok Volatilite),
- ATR (Volatilite) ve stop mesafesi,
- Takasbank Başlangıç Teminatı kısıtlarını
bütünleştirerek girilecek kesin kontrat adedini hesaplar.
"""

from typing import Dict
from src.core.config import SystemConfig
from src.core.models import ConsensusDecision, MarketBar, MarketRegime, Position
from src.risk.viop_margin import ViopMarginManager


class DynamicPositionSizer:
    """
    Volatilite ve Teminat Kısıtlı Pozisyon Boyutlandırıcı.
    """

    def __init__(self, config: SystemConfig, margin_manager: ViopMarginManager) -> None:
        """
        Args:
            config: Sistem konfigürasyonu.
            margin_manager: VİOP teminat hesaplayıcı.
        """
        self.config = config
        self.margin_manager = margin_manager

    def calculate_order_contracts(
        self,
        decision: ConsensusDecision,
        current_bar: MarketBar,
        positions: Dict[str, Position],
        cash_balance: float,
        stop_distance_points: float
    ) -> int:
        """
        Açılacak kontrat adedini hesaplar.
        
        Args:
            decision: Konsensüs strateji kararı.
            current_bar: Güncel piyasa fiyatı/barı.
            positions: Mevcut açık pozisyonlar tablosu.
            cash_balance: Mevcut nakit bakiye.
            stop_distance_points: Stop mesafesi (TL fiyat farkı).
            
        Returns:
            int: Açılması önerilen kontrat adedi (0 ise işlem açılmaz).
        """
        if decision.target_action.name == "NEUTRAL" or decision.allocated_weight <= 0.05:
            return 0

        contract_spec = self.config.contracts.get(decision.symbol)
        if not contract_spec:
            return 0

        margins = self.margin_manager.calculate_portfolio_margins(positions, cash_balance)
        equity = margins["total_equity"]
        free_margin = margins["free_margin"]

        if free_margin <= contract_spec.initial_margin_try:
            return 0  # 1 kontrat teminatına dahi yetecek serbest bakiye yok

        # 1. Portföy Risk Tutarı Hesabı (Örn: %2 risk)
        risk_budget_try = equity * self.config.max_risk_per_trade * decision.allocated_weight

        # Rejim Çarpanı: Şok volatilitede risk bütçesini %70 kıs
        if decision.regime == MarketRegime.HIGH_VOLATILITY:
            risk_budget_try *= 0.30
        elif decision.regime == MarketRegime.RANGING_LOW_VOL:
            risk_budget_try *= 0.70

        # 2. Risk Bazlı Kontrat Adedi:
        # 1 Kontrat Riski = stop_distance_points * multiplier
        risk_per_contract = max(1.0, stop_distance_points * contract_spec.multiplier)
        risk_based_contracts = int(risk_budget_try / risk_per_contract)

        # 3. Teminat Bazlı Maksimum Kontrat Adedi (Free Margin Kısıtı):
        margin_based_contracts = int(free_margin / contract_spec.initial_margin_try)

        # 4. İki kısıtın en güvenlisini (küçüğünü) seç
        optimal_contracts = min(risk_based_contracts, margin_based_contracts)

        # 5. Yön Belirleme (Long = Pozitif, Short = Negatif)
        if "SELL" in decision.target_action.name:
            optimal_contracts = -optimal_contracts

        # Nihai teminat denetimi
        can_open, _ = self.margin_manager.can_open_position(
            symbol=decision.symbol,
            additional_contracts=optimal_contracts,
            positions=positions,
            cash_balance=cash_balance
        )

        return optimal_contracts if can_open else 0
