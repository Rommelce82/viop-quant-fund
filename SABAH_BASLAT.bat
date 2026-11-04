@echo off
chcp 65001 >nul
title VIOP Sabah Baslatma ve Tablo Senkronizasyonu (Fintables.MCP ^& Takasbank)
echo ===============================================================================
echo   VIOP GÜNLÜK SABAH BAŞLATMA VE TABLO SENKRONİZASYON SERVİSİ
echo   Fintables.MCP ^& Takasbank: Sözleşmeler, Teminatlar, Margin Call
echo ===============================================================================
echo.
cd /d "%~dp0"
echo [*] Sabah seans oncesi 3 VIOP tablosu taranıyor ve degisen rakamlar sisteme aktarılıyor...
python -m src.data.morning_startup
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [HATA] Sabah baslatma sırasında bir sorun olustu! Lutfen logları inceleyin.
) else (
    echo.
    echo [BASARILI] Sabah baslatma tamamlandı! Sistem canlı operasyona hazırdır.
)
echo.
pause

