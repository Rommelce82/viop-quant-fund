"""
Fintables PRO Point-in-Time Temel Analiz Veri Hattı.

Bu modül, şirket bilançolarını, gelir tablolarını ve rasyoları (F/K, PD/DD, FD/FAVÖK, ROE)
'Point-in-Time' esasına göre alır. Asla bilançonun KAP'a açıklanmasından önceki
tarihlerde bu verinin strateji tarafından okunmasına izin vermez (Data Leakage & Lookahead Bias önleme).
"""

from datetime import datetime
from typing import Dict, List, Optional
from src.core.models import PointInTimeData
from src.data.mcp_client import MCPClient


class FintablesPipeline:
    """
    Fintables PRO Temel Analiz Veri Entegrasyonu.
    """

    def __init__(self, mcp_client: MCPClient) -> None:
        """
        Args:
            mcp_client: MCP haberleşme istemcisi.
        """
        self.mcp = mcp_client
        self._historical_records: List[PointInTimeData] = []

    def load_mock_financials(self) -> None:
        """
        Test ve geriye dönük doğrulama için örnek Point-in-Time bilanço verilerini yükler.
        Her bilanço için dönem tarihi (as_of_date) ile KAP bildirim tarihi (announced_at)
        arasındaki gerçek farkı modeller.
        """
        # Örnek 1: THYAO 2024/06 Bilançosu (Dönem: 30 Haziran, KAP İlanı: 15 Ağustos 2024 18:30)
        self._historical_records.append(
            self.mcp.wrap_pit_record(
                record_id="THYAO_2024Q2",
                symbol="THYAO",
                data_type="FINANCIAL_STATEMENT",
                as_of_date=datetime(2024, 6, 30, 0, 0),
                announced_at=datetime(2024, 8, 15, 18, 30),
                payload={
                    "pe_ratio": 4.8,          # F/K
                    "pb_ratio": 0.85,         # PD/DD
                    "ev_ebitda": 3.9,         # FD/FAVÖK
                    "roe": 0.28,              # Özsermaye Karlılığı %28
                    "net_debt_ebitda": 1.1,   # Net Borç / FAVÖK
                    "net_profit_growth": 0.35 # Yıllık Kar Büyümesi %35
                }
            )
        )

        # Örnek 2: GARAN 2024/06 Bilançosu (KAP İlanı: 29 Temmuz 2024 18:05)
        self._historical_records.append(
            self.mcp.wrap_pit_record(
                record_id="GARAN_2024Q2",
                symbol="GARAN",
                data_type="FINANCIAL_STATEMENT",
                as_of_date=datetime(2024, 6, 30, 0, 0),
                announced_at=datetime(2024, 7, 29, 18, 5),
                payload={
                    "pe_ratio": 3.7,
                    "pb_ratio": 1.15,
                    "ev_ebitda": 0.0,
                    "roe": 0.38,
                    "net_debt_ebitda": 0.0,
                    "net_profit_growth": 0.42
                }
            )
        )

        # Örnek 3: EREGL 2024/06 Bilançosu (KAP İlanı: 8 Ağustos 2024 19:15)
        self._historical_records.append(
            self.mcp.wrap_pit_record(
                record_id="EREGL_2024Q2",
                symbol="EREGL",
                data_type="FINANCIAL_STATEMENT",
                as_of_date=datetime(2024, 6, 30, 0, 0),
                announced_at=datetime(2024, 8, 8, 19, 15),
                payload={
                    "pe_ratio": 14.5,
                    "pb_ratio": 1.40,
                    "ev_ebitda": 8.5,
                    "roe": 0.09,
                    "net_debt_ebitda": 2.8,
                    "net_profit_growth": -0.15
                }
            )
        )

    def get_latest_statement(
        self,
        symbol: str,
        current_time: datetime
    ) -> Optional[PointInTimeData]:
        """
        Belirli bir sembol için 'current_time' anında bilinen EN GÜNCEL bilançoyu döndürür.
        
        KESİNLİKLE LOOKAHEAD BİAS İÇERMEZ:
        Eğer bilanço açıklanmış olsa bile 'current_time' henüz 'available_at'e ulaşmadıysa,
        asla o bilanço dönülmez.
        """
        valid_records = [
            rec for rec in self._historical_records
            if rec.symbol == symbol and rec.is_visible_at(current_time)
        ]
        if not valid_records:
            return None

        # En son açıklanan geçerli bilançoyu seç
        valid_records.sort(key=lambda x: x.announced_at, reverse=True)
        return valid_records[0]

    def register_financial_statement(self, record: PointInTimeData) -> None:
        """Yeni bir bilanço kaydını Point-in-Time veritabanına ekler."""
        self._historical_records.append(record)
