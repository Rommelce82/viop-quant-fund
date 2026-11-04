@echo off
chcp 65001 >nul
title VIOP 15-Dakikalik Arka Plan Veri Hatti Servisi (v4.2)
echo ===============================================================================
echo   VIOP 15-DAKIKALIK PERIYODIK VERI HATTI VE RESAMPLER SERVISI
echo   Fintables Akis + TCMB Kurlar + 120m/240m Barlar + ALE Net Nemasi
echo ===============================================================================
echo.
cd /d "%~dp0"
echo [*] Arka plan senkronizasyon servisi baslatiliyor (15 dakikada 1 periyot)...
python -m src.data.background_feed_worker
pause
