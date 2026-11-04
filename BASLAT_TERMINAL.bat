@echo off
chcp 65001 >nul
title VIOP Canlı İşlem ve Risk Kokpiti (v4.2) - 2.000.000 TL Tek Bütçe
echo ===============================================================================
echo   🏛️ VIOP ÇOK VARLIKLI KANTİTATİF CANLI İŞLEM VE RİSK KOKPİTİ (v4.2)
echo   Ali Perşembe Doktrini | 2.000.000 TL TEK ORTAK PORTFÖY BÜTÇESİ
echo   %%100 TAM OTONOM CANLI TEST OPERASYONU (Sıfır Manuel Müdahale)
echo ===============================================================================
echo.
cd /d "%~dp0"

echo [*] 1. VİOP Otonom Canlı Operatör arkaplanda başlatılıyor...
echo        • Sabah Başlatma: Fintables.MCP Sözleşmeler, Teminatlar, Margin Call
echo        • 15-Dakikalık Fiyat & 240m Karar Motoru (Giriş, +2R Piramitleme, Stop)
echo        • 18:15 Akbank ALE Seans Sonu Net Nemalandırma
start "VIOP_AUTONOMOUS_OPERATOR" /min python -m src.execution.autonomous_operator

echo [*] 2. Tarayıcı açılıyor: http://localhost:8501
start "" http://localhost:8501

echo [*] 3. Streamlit Canlı Kokpit başlatılıyor (15 sn Otomatik Yenilemeli)...
echo        (Tüm işlemleri canlı olarak ekrandan izleyebilirsiniz)
echo.
python -m streamlit run src/dashboard/app.py --server.port 8501 --server.headless false --theme.base dark

pause
