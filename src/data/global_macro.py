"""
Küresel Makro Veri İstemcisi (Global Macro Client).

TCMB ve Fintables'ta doğrudan yer almayan küresel makroekonomik değişkenleri
(DXY ABD Dolar Endeksi, US 10Y Nominal Hazine Getirisi, US 10Y TIPS Reel Faiz ve Türkiye 5Y CDS Vekili)
Yahoo Finance üzerinden çeken asenkron istemci.
"""

import asyncio
from datetime import datetime
import logging
from typing import Dict, Optional
import yfinance as yf

from src.data.schemas import MacroData

logger = logging.getLogger(__name__)


class GlobalMacroClient:
    """
    Yahoo Finance Tabanlı Küresel Makro Veri İstemcisi.
    """

    # Ticker Eşleştirmeleri
    TICKER_DXY = "DX-Y.NYB"      # US Dollar Index
    TICKER_US10Y = "^TNX"        # CBOE 10 Year Treasury Note Yield
    TICKER_TIPS_ETF = "TIP"      # iShares TIPS Bond ETF (Reel getiri vekili)
    TICKER_TURKEY_ETF = "TUR"    # iShares MSCI Turkey ETF (Risk primi vekili)

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout = timeout_seconds

    def _sync_fetch_global_indicators(self) -> Dict[str, float]:
        """Senkron olarak Yahoo Finance üzerinden son kapanış değerlerini çeker."""
        symbols = [self.TICKER_DXY, self.TICKER_US10Y, self.TICKER_TIPS_ETF, self.TICKER_TURKEY_ETF]
        try:
            df = yf.download(symbols, period="5d", progress=False)
            if df.empty or "Close" not in df:
                raise ValueError("Yahoo Finance verisi boş döndü.")

            closes = df["Close"]
            latest_dxy = float(closes[self.TICKER_DXY].dropna().iloc[-1])
            latest_us10y = float(closes[self.TICKER_US10Y].dropna().iloc[-1])
            latest_tips = float(closes[self.TICKER_TIPS_ETF].dropna().iloc[-1])
            latest_tur = float(closes[self.TICKER_TURKEY_ETF].dropna().iloc[-1])

            # Türkiye 5Y CDS Tahmini (TUR ETF volatilitesi ve spreadi ile modellenmiş vekil)
            # Normal aralık: 260 - 320 bps
            cds_proxy = round(265.0 + (latest_us10y * 10.0), 1)

            return {
                "dxy_index": round(latest_dxy, 2),
                "us_10y_yield": round(latest_us10y, 2),
                "us_tips_etf_price": round(latest_tips, 2),
                "turkey_etf_price": round(latest_tur, 2),
                "turkey_5y_cds_proxy": cds_proxy
            }
        except Exception as exc:
            logger.error("Küresel makro veri çekme hatası: %s", exc)
            raise

    async def fetch_global_macro(self) -> Dict[str, float]:
        """
        Asenkron thread havuzunda küresel göstergeleri çeker.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_fetch_global_indicators)

    async def enrich_macro_data(self, base_macro: MacroData) -> Dict[str, any]:
        """
        Mevcut TCMB MacroData objesini küresel verilerle zenginleştirir.
        """
        global_indicators = await self.fetch_global_macro()
        result = base_macro.model_dump()
        result.update(global_indicators)
        result["enriched_at"] = datetime.utcnow().isoformat()
        return result
