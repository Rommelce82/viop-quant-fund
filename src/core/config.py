"""
Yapılandırma ve Sabitler Modülü.

Bu modül, VİOP sözleşme spesifikasyonlarını, teminat katsayılarını,
risk limitlerini ve sistem parametrelerini içerir.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ContractSpecification:
    """
    VİOP Sözleşme Özellikleri Tanımı.

    Attributes:
        symbol: Sözleşme ana sembolü (Örn: F_XU030, F_THYAO).
        underlying: Dayanak varlık kodu.
        multiplier: Sözleşme büyüklüğü / çarpanı (Örn: F_XU030 için 10, hisse için 100).
        initial_margin_try: Kontrat başına Takasbank başlangıç teminatı (TL).
        maintenance_margin_ratio: Başlangıç teminatına oranla sürdürme teminatı oranı (genellikle 0.75 - 1.00).
        tick_size: Minimum fiyat adımı.
        commission_rate: Aracı kurum + Borsa komisyon oranı (Örn: 0.00015 = On binde 1.5).
    """
    symbol: str
    underlying: str
    multiplier: float
    initial_margin_try: float
    maintenance_margin_ratio: float = 0.75
    tick_size: float = 0.25
    commission_rate: float = 0.00018


@dataclass
class SystemConfig:
    """
    Sistem Global Yapılandırma Parametreleri.
    """
    base_currency: str = "TRY"
    initial_capital: float = 2_000_000.0  # 2 Milyon TL tek ortak portföy büyüklüğü (tüm varlıklar için)
    max_portfolio_leverage: float = 3.0   # Maksimum izin verilen kaldıraç oranı
    max_risk_per_trade: float = 0.02      # İşlem başına riske edilen portföy yüzdesi (%2)
    margin_call_threshold: float = 0.80   # Toplam teminat / Başlangıç teminatı oranı eşiği
    data_latency_seconds: float = 2.0     # Haber/KAP ve makro veri piyasaya yansıma gecikmesi (Latency)
    
    # Standart VİOP Sözleşme Kütüphanesi
    contracts: Dict[str, ContractSpecification] = field(default_factory=lambda: {
        "F_XU030": ContractSpecification(
            symbol="F_XU030",
            underlying="XU030",
            multiplier=10.0,
            initial_margin_try=17500.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.25,
            commission_rate=0.00012
        ),
        "F_THYAO": ContractSpecification(
            symbol="F_THYAO",
            underlying="THYAO",
            multiplier=100.0,
            initial_margin_try=6500.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.10,
            commission_rate=0.00018
        ),
        "F_GARAN": ContractSpecification(
            symbol="F_GARAN",
            underlying="GARAN",
            multiplier=100.0,
            initial_margin_try=2300.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.05,
            commission_rate=0.00018
        ),
        "F_AKBNK": ContractSpecification(
            symbol="F_AKBNK",
            underlying="AKBNK",
            multiplier=100.0,
            initial_margin_try=1450.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.05,
            commission_rate=0.00018
        ),
        "F_EREGL": ContractSpecification(
            symbol="F_EREGL",
            underlying="EREGL",
            multiplier=100.0,
            initial_margin_try=950.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.05,
            commission_rate=0.00018
        ),
        "F_TUPRS": ContractSpecification(
            symbol="F_TUPRS",
            underlying="TUPRS",
            multiplier=100.0,
            initial_margin_try=2400.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.10,
            commission_rate=0.00018
        ),
        "F_BRENT": ContractSpecification(
            symbol="F_BRENT",
            underlying="BRENT",
            multiplier=1.0,
            initial_margin_try=6500.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.05,
            commission_rate=0.00018
        ),
        "F_XAUUSD": ContractSpecification(
            symbol="F_XAUUSD",
            underlying="ALTIN",
            multiplier=1.0,
            initial_margin_try=7200.0,
            maintenance_margin_ratio=0.75,
            tick_size=0.10,
            commission_rate=0.00018
        ),
    })

    def update_contract_spec(
        self,
        symbol: str,
        underlying: Optional[str] = None,
        multiplier: Optional[float] = None,
        initial_margin_try: Optional[float] = None,
        maintenance_margin_ratio: Optional[float] = None,
        tick_size: Optional[float] = None,
        commission_rate: Optional[float] = None
    ) -> ContractSpecification:
        """Belirli bir sözleşmenin parametrelerini veya teminatını dinamik günceller."""
        existing = self.contracts.get(symbol)
        new_spec = ContractSpecification(
            symbol=symbol,
            underlying=underlying if underlying is not None else (existing.underlying if existing else symbol),
            multiplier=multiplier if multiplier is not None else (existing.multiplier if existing else 100.0),
            initial_margin_try=initial_margin_try if initial_margin_try is not None else (existing.initial_margin_try if existing else 6500.0),
            maintenance_margin_ratio=maintenance_margin_ratio if maintenance_margin_ratio is not None else (existing.maintenance_margin_ratio if existing else 0.75),
            tick_size=tick_size if tick_size is not None else (existing.tick_size if existing else 0.10),
            commission_rate=commission_rate if commission_rate is not None else (existing.commission_rate if existing else 0.00018),
        )
        self.contracts[symbol] = new_spec
        return new_spec

    def update_from_margins(self, margins_dict: Dict[str, Any]) -> int:
        """
        Fintables / Takasbank teminat bülteninden gelen güncel teminatları
        mevcut sözleşme kütüphanesine ve kök sembollere yansıtır.
        Dönen değer güncellenen sözleşme sayısıdır.
        """
        updated_count = 0
        for code, info in margins_dict.items():
            if not isinstance(info, dict):
                continue
            init_m = float(info.get("initial_margin_try", 0.0))
            if init_m <= 0.0:
                continue
            maint_m = float(info.get("maintenance_margin_try", init_m * 0.75))
            ratio = (maint_m / init_m) if init_m > 0 else 0.75

            # 1. Tam kod ile güncelle (Örn: F_THYAO1026)
            self.update_contract_spec(
                symbol=code,
                initial_margin_try=init_m,
                maintenance_margin_ratio=ratio
            )
            updated_count += 1

            # 2. Kök sembolü türet ve varsa güncelle (Örn: F_THYAO)
            # F_ sembollerinde sondaki 4 haneli vade (1026) çıkarılabilir
            if len(code) > 6 and code.startswith("F_") and code[-4:].isdigit():
                root_sym = code[:-4]
                self.update_contract_spec(
                    symbol=root_sym,
                    initial_margin_try=init_m,
                    maintenance_margin_ratio=ratio
                )
                updated_count += 1

        return updated_count

    def load_from_db(self, db: Any) -> int:
        """
        DatabaseManager üzerinden aktif sözleşmeleri ve en güncel teminatları yükler.
        """
        contracts_db = db.get_viop_contracts()
        latest_margins = db.get_latest_margins()

        loaded_count = 0
        for c in contracts_db:
            code = c["contract_code"]
            m_info = latest_margins.get(code, {})
            init_m = float(m_info.get("initial_margin_try", c["initial_margin_try"]))
            maint_m = float(m_info.get("maintenance_margin_try", c["maintenance_margin_try"]))
            ratio = (maint_m / init_m) if init_m > 0 else 0.75

            self.update_contract_spec(
                symbol=code,
                underlying=c["underlying_symbol"],
                multiplier=float(c["contract_size"]),
                initial_margin_try=init_m,
                maintenance_margin_ratio=ratio
            )
            loaded_count += 1

            # Kök sembol desteği
            if len(code) > 6 and code.startswith("F_") and code[-4:].isdigit():
                root_sym = code[:-4]
                self.update_contract_spec(
                    symbol=root_sym,
                    underlying=c["underlying_symbol"],
                    multiplier=float(c["contract_size"]),
                    initial_margin_try=init_m,
                    maintenance_margin_ratio=ratio
                )

        return loaded_count
