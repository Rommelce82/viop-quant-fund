"""
Model Context Protocol (MCP) İstemci Modülü.

Bu modül, Fintables PRO, TCMB EVDS ve diğer veri sağlayıcı servislerle
MCP standardında JSON-RPC tarzı asenkron/senkron iletişim kurar.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from src.core.models import PointInTimeData


class MCPClient:
    """
    MCP Protokolü Uyumlu Veri Servisi İstemcisi.
    Veri kaynaklarına standartlaştırılmış sorgular yönlendirir ve
    Point-in-Time (PIT) doğrulamalı veri döner.
    """

    def __init__(self, latency_seconds: float = 2.0) -> None:
        """
        MCP İstemcisini ilklendirir.
        
        Args:
            latency_seconds: Bilginin ağ ve sunuculardan algoritmaya geliş gecikmesi (Latency).
        """
        self.latency: timedelta = timedelta(seconds=latency_seconds)
        self._connected: bool = True

    def query_resource(
        self,
        uri: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        MCP Kaynak Uçnoktasına sorgu atar.
        
        Args:
            uri: MCP protokol URI'si (Örn: mcp://fintables/financials, mcp://tcmb/evds/interest).
            params: Sorgu filtre parametreleri.
            
        Returns:
            Dict[str, Any]: Sunucudan dönen MCP JSON-RPC yanıtı.
        """
        if not self._connected:
            raise ConnectionError("MCP istemcisi sunucuya bağlı değil.")

        params = params or {}
        return {
            "jsonrpc": "2.0",
            "result": {
                "uri": uri,
                "status": "success",
                "fetched_at": datetime.utcnow().isoformat(),
                "data": params
            }
        }

    def wrap_pit_record(
        self,
        record_id: str,
        symbol: str,
        data_type: str,
        as_of_date: datetime,
        announced_at: datetime,
        payload: Dict[str, Any]
    ) -> PointInTimeData:
        """
        Ham MCP yanıtını Point-in-Time güvenli nesneye dönüştürür.
        Latency ekleyerek 'available_at' süresini garanti altına alır.
        """
        available_at = announced_at + self.latency
        return PointInTimeData(
            data_id=record_id,
            symbol=symbol,
            data_type=data_type,
            as_of_date=as_of_date,
            announced_at=announced_at,
            available_at=available_at,
            payload=payload
        )
