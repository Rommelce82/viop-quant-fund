"""
VİOP Nihai Orkestratör Modülü (v4.0).

Bu modül;
1. Temel Analiz ve Yön Pusulası (FundamentalCompass - v4.0) ile
2. Teknik İcra ve Mutlak Otoriteyi (TechnicalExecutioner - v4.0)
birbirine bağlar.

Çalışma Sırası:
1. Temel Pusula: Likidite, Çok Varlıklı Yön Analizi ve Taşıma Maliyeti (Cost of Carry) süzgeçlerinden
   geçerek ONLY_LONG, ONLY_SHORT veya NEUTRAL üretir.
2. Teknik İcra Otoritesi: Yön iznini alır; 60 dakikalık veride rejim, Donchian shift(1) kırılımı,
   hacim patlaması ve R/K barajını denetler; serbest teminat kısıtıyla lot hesaplar veya
   açık pozisyonda zaman stopu/scale-out/chandelier exit kararlarını uygular.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import pandas as pd

from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import (
    AssetChannel,
    BankMetricsInput,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput,
    MacroTrendsInput
)
from src.strategy.position_manager import PositionState
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalDecisionV4,
    TechnicalExecutioner
)


@dataclass
class OrchestratorVerdictV4:
    """Nihai Sistem Kararı ve Denetim Özeti."""
    symbol: str
    compass_bias: DirectionalBias
    compass_rationale: str
    technical_decision: TechnicalDecisionV4
    compass_multiplier: float = 1.0


class StrategyOrchestratorV4:
    """
    VİOP v4.0 Birleşik Strateji Orkestratörü (Ali Perşembe Doktrini).
    """

    def __init__(
        self,
        compass: Optional[FundamentalCompass] = None,
        executioner: Optional[TechnicalExecutioner] = None
    ) -> None:
        self.compass = compass or FundamentalCompass()
        self.executioner = executioner or TechnicalExecutioner()

    def run_strategy_cycle(
        self,
        symbol: str,
        channel: AssetChannel,
        daily_data: pd.DataFrame,
        hourly_data: pd.DataFrame,
        microstructure: MarketMicrostructureInput,
        cost_of_carry: CostOfCarryInput,
        portfolio_nav: float,
        free_margin: float,
        position_state: Optional[PositionState] = None,
        fundamental_data: Optional[FundamentalData] = None,
        previous_fundamental_data: Optional[FundamentalData] = None,
        bank_input: Optional[BankMetricsInput] = None,
        macro_input: Optional[MacroTrendsInput] = None,
        tcmb_policy_rate: float = 0.50,
        sector_average_z: Optional[float] = None
    ) -> OrchestratorVerdictV4:
        """
        Uçtan uca v4.0 karar ve icra döngüsünü koordine eder.
        """
        # 1. ADIM: Temel Pusula Yön ve Dinamik Bütçe Çarpanı Değerlendirmesi
        compass_res, compass_msg = self.compass.get_compass_verdict(
            channel=channel,
            micro=microstructure,
            carry=cost_of_carry,
            fundamental_data=fundamental_data,
            previous_fundamental_data=previous_fundamental_data,
            bank_input=bank_input,
            macro_input=macro_input,
            tcmb_policy_rate=tcmb_policy_rate,
            sector_average_z=sector_average_z
        )

        direction_str = compass_res.get("direction", "NEUTRAL")
        compass_bias = DirectionalBias(direction_str) if direction_str in DirectionalBias.__members__ else DirectionalBias.NEUTRAL
        compass_multiplier = float(compass_res.get("multiplier", 0.0))

        # 2. ADIM: Teknik İcra ve Otorite Kararı
        tech_decision = self.executioner.evaluate(
            symbol=symbol,
            compass_bias=compass_bias,
            daily_data=daily_data,
            hourly_data=hourly_data,
            position_state=position_state,
            portfolio_nav=portfolio_nav,
            free_margin=free_margin,
            compass_multiplier=compass_multiplier
        )

        return OrchestratorVerdictV4(
            symbol=symbol,
            compass_bias=compass_bias,
            compass_rationale=compass_msg,
            technical_decision=tech_decision,
            compass_multiplier=compass_multiplier
        )
