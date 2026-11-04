"""
VİOP Takasbank Teminatlandırma ve Margin Call Risk Hesaplama Modülü.

Bu modül;
- Başlangıç Teminatı (Initial Margin),
- Sürdürme Teminatı (Maintenance Margin),
- Teminat Tamamlama Çağrısı (Margin Call) seviyelerini,
- Kaldıraç katsayılarını ve serbest teminatı kesinlikle VİOP mikro-yapısına uygun hesaplar.
"""

from typing import Dict, List, Tuple
from src.core.config import ContractSpecification, SystemConfig
from src.core.models import Position


class ViopMarginManager:
    """
    Takasbank Standartlarında VİOP Teminat Yönetim Motoru.
    """

    def __init__(self, config: SystemConfig) -> None:
        """
        Args:
            config: Sistem genel parametreleri ve VİOP kontrat tanımları.
        """
        self.config = config

    def calculate_portfolio_margins(
        self,
        positions: Dict[str, Position],
        cash_balance: float
    ) -> Dict[str, float]:
        """
        Açık portföy için Takasbank teminat durumunu detaylı hesaplar.
        
        Returns:
            Dict: Toplam teminat gereksinimi, sürdürme teminatı, net özkaynak,
                  serbest teminat ve margin call durumu.
        """
        total_initial_margin_required = 0.0
        total_maintenance_margin_required = 0.0
        total_unrealized_pnl = 0.0
        total_notional_value = 0.0

        for symbol, pos in positions.items():
            if pos.quantity == 0:
                continue

            contract_spec = self.config.contracts.get(symbol)
            if not contract_spec:
                continue

            abs_contracts = abs(pos.quantity)
            im_required = abs_contracts * contract_spec.initial_margin_try
            mm_required = im_required * contract_spec.maintenance_margin_ratio

            total_initial_margin_required += im_required
            total_maintenance_margin_required += mm_required
            total_unrealized_pnl += pos.unrealized_pnl
            total_notional_value += pos.market_value

        # Toplam Varlık (Net Equity) = Nakit + Gerçekleşmemiş Kar/Zarar
        total_equity = cash_balance + total_unrealized_pnl

        # Serbest Teminat (Free Margin) = Toplam Özkaynak - Bağlı Başlangıç Teminatı
        free_margin = total_equity - total_initial_margin_required

        # Teminat Karşılama Oranı (Margin Health Ratio)
        margin_health_ratio = (
            (total_equity / total_initial_margin_required)
            if total_initial_margin_required > 0 else 999.0
        )

        # Margin Call (Teminat Tamamlama Çağrısı) Kontrolü
        # Özkaynak, sürdürme teminatının altına düşerse Takasbank Margin Call üretir!
        is_margin_call = (total_equity < total_maintenance_margin_required) and (total_initial_margin_required > 0)
        margin_call_deficit = max(0.0, total_initial_margin_required - total_equity) if is_margin_call else 0.0

        current_leverage = (total_notional_value / total_equity) if total_equity > 0 else 0.0

        return {
            "cash_balance": cash_balance,
            "total_equity": total_equity,
            "total_initial_margin_required": total_initial_margin_required,
            "total_maintenance_margin_required": total_maintenance_margin_required,
            "free_margin": free_margin,
            "unrealized_pnl": total_unrealized_pnl,
            "total_notional_value": total_notional_value,
            "current_leverage": current_leverage,
            "margin_health_ratio": margin_health_ratio,
            "is_margin_call": float(is_margin_call),
            "margin_call_deficit": margin_call_deficit
        }

    def can_open_position(
        self,
        symbol: str,
        additional_contracts: int,
        positions: Dict[str, Position],
        cash_balance: float
    ) -> Tuple[bool, str]:
        """
        Yeni bir pozisyon açılmadan önce kaldıraç ve serbest teminat yeterliliğini denetler.
        """
        contract_spec = self.config.contracts.get(symbol)
        if not contract_spec:
            return False, f"Bilinmeyen sözleşme: {symbol}"

        required_margin = abs(additional_contracts) * contract_spec.initial_margin_try
        margins = self.calculate_portfolio_margins(positions, cash_balance)

        if margins["free_margin"] < required_margin:
            return False, (
                f"Yetersiz Serbest Teminat! Gerekli: {required_margin:,.2f} TL, "
                f"Mevcut Serbest Teminat: {margins['free_margin']:,.2f} TL"
            )

        # Gelecekteki tahmini kaldıraç kontrolü
        potential_notional = margins["total_notional_value"] + (
            abs(additional_contracts) * contract_spec.multiplier * 100.0  # Yaklaşık nominal
        )
        potential_leverage = potential_notional / margins["total_equity"] if margins["total_equity"] > 0 else 999.0
        
        if potential_leverage > self.config.max_portfolio_leverage:
            return False, f"Maksimum kaldıraç sınırı ({self.config.max_portfolio_leverage}x) aşılacak! Tahmini: {potential_leverage:.2f}x"

        return True, "Onaylandı"
