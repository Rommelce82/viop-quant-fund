"""
TCMB EVDS Makroekonomik Veri Hattı.

Bu modül, Türkiye Cumhuriyet Merkez Bankası (TCMB) politika faizi,
brüt/net rezervler, enflasyon (TÜFE/ÜFE) ve haftalık menkul kıymet istatistiklerini
Point-in-Time standardında temin eder.
"""

from datetime import datetime
from typing import Dict, List, Optional
from src.core.models import PointInTimeData
from src.data.mcp_client import MCPClient


class TCMBPipeline:
    """
    TCMB EVDS Makro Veri Entegrasyon Modülü.
    """

    def __init__(self, mcp_client: MCPClient) -> None:
        """
        Args:
            mcp_client: MCP haberleşme istemcisi.
        """
        self.mcp = mcp_client
        self._macro_records: List[PointInTimeData] = []

    def load_mock_macro_data(self) -> None:
        """
        Geriye dönük testler için PPK Faiz Kararı ve Makro Verileri yükler.
        PPK kararları saat 14:00'te duyurulur ve gecikme sonrası işlenir.
        """
        # Temmuz 2024 PPK Kararı: 23 Temmuz 2024 14:00 (Faiz %50 sabit tutuldu)
        self._macro_records.append(
            self.mcp.wrap_pit_record(
                record_id="TCMB_PPK_2024_07",
                symbol="TCMB",
                data_type="POLICY_RATE",
                as_of_date=datetime(2024, 7, 23, 14, 0),
                announced_at=datetime(2024, 7, 23, 14, 0),
                payload={
                    "policy_rate": 50.0,
                    "previous_rate": 50.0,
                    "net_reserves_usd_bn": 42.5,
                    "cpi_annual": 61.78,
                    "stance": "HAWKISH"  # Şahin / Sıkı duruş
                }
            )
        )

        # Ağustos 2024 PPK Kararı: 20 Ağustos 2024 14:00
        self._macro_records.append(
            self.mcp.wrap_pit_record(
                record_id="TCMB_PPK_2024_08",
                symbol="TCMB",
                data_type="POLICY_RATE",
                as_of_date=datetime(2024, 8, 20, 14, 0),
                announced_at=datetime(2024, 8, 20, 14, 0),
                payload={
                    "policy_rate": 50.0,
                    "previous_rate": 50.0,
                    "net_reserves_usd_bn": 47.8,
                    "cpi_annual": 51.97,
                    "stance": "HAWKISH"
                }
            )
        )

    def get_latest_macro_state(self, current_time: datetime) -> Optional[PointInTimeData]:
        """
        Belirtilen simülasyon zamanında piyasa tarafından bilinen son makro durumu döner.
        """
        valid_records = [
            rec for rec in self._macro_records
            if rec.is_visible_at(current_time)
        ]
        if not valid_records:
            return None

        valid_records.sort(key=lambda x: x.announced_at, reverse=True)
        return valid_records[0]

    def register_macro_data(self, record: PointInTimeData) -> None:
        """Yeni bir makro veriyi listeye ekler."""
        self._macro_records.append(record)
