@echo off
chcp 65001 >nul
title VIOP Canli Islem ve Risk Kokpiti (v4.2) - 2.000.000 TL Tek Butce
echo ===============================================================================
echo   VIOP COK VARLIKLI KANTITATIF CANLI ISLEM VE RISK KOKPITI (v4.2)
echo   Ali Persembe Doktrini - 2.000.000 TL TEK ORTAK PORTFOY BUTCESI
echo   %%100 TAM OTONOM CANLI TEST OPERASYONU (Sifir Manuel Mudahale)
echo ===============================================================================
echo.
cd /d "%~dp0"

echo [*] 1. VIOP Otonom Canli Operator arkaplanda baslatiliyor...
echo        - Sabah Baslatma: Fintables.MCP Sozlesmeler, Teminatlar, Margin Call
echo        - 15-Dakikalik Fiyat ve 240m Karar Motoru (Giris, +2R Piramitleme, Stop)
echo        - 18:15 Akbank ALE Seans Sonu Net Nemalandirma
start "VIOP_AUTONOMOUS_OPERATOR" /min cmd.exe /c "python -m src.execution.autonomous_operator"

echo [*] 2. Tarayici aciliyor: http://localhost:8501
start "" http://localhost:8501

echo [*] 3. Streamlit Canli Kokpit baslatiliyor (15 sn Otomatik Yenilemeli)...
echo        (Tum islemleri canli olarak ekrandan izleyebilirsiniz)
echo.
python -m streamlit run src/dashboard/app.py --server.port 8501 --server.headless false --theme.base dark

pause
