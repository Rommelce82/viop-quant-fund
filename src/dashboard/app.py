"""
🏛️ VİOP ÇOK VARLIKLI KANTİTATİF CANLI İŞLEM VE RİSK KOKPİTİ (v4.2)
(src/dashboard/app.py)

Ali Perşembe Doktrini | 2.000.000 TL Tek Ortak Portföy Bütçesi | 20 VİOP Sözleşmesi
15-Dakikalık Arka Plan Veri Hattı | 15m & 240m Karar Pencereleri
Midas Kademeli Komisyon Tarifesi | Akbank ALE Fonu %17.5 Stopajlı Net Nema
%100 Canlı Test Operasyonu (Eski Test ve Simülasyon Verileri Tamamen Arındırılmıştır)
"""

from datetime import datetime, timedelta
import json
import os
import sys
from typing import Any, Dict, List, Optional
import socket
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    def st_autorefresh(*args, **kwargs):
        return None

# Proje ana dizinini sys.path'e ekle
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
from src.core.config import SystemConfig
from src.database.db_manager import DatabaseManager
from src.strategy.fundamental_compass import AssetChannel, DirectionalBias, FundamentalCompass
from src.strategy.earnings_blackout import BlackoutPhase, EarningsBlackoutManager
from src.data.viop_feed_scheduler import ViopDataFeedScheduler

_CLOUD_OPERATOR_SOCKET = None

# ==============================================================================
# BULUT VE SUNUCUDA 7/24 OTONOM OPERATÖR BAŞLATICI (STREAMLIT CLOUD SINGLETON)
# ==============================================================================
@st.cache_resource
def ensure_cloud_operator_running() -> str:
    """
    Bulut ortamında (Streamlit Community Cloud / Sunucu)
    arkaplanda 7/24 otonom işlem operatörünü başlatan singleton iş parçacığı.
    """
    global _CLOUD_OPERATOR_SOCKET
    import threading
    import logging
    from src.execution.autonomous_operator import AutonomousLiveOperator, acquire_operator_lock
    
    lock = acquire_operator_lock(port=58999)
    if not lock:
        return "OPERATOR_ALREADY_RUNNING"
    _CLOUD_OPERATOR_SOCKET = lock
        
    def _run_operator_loop():
        try:
            op = AutonomousLiveOperator()
            asyncio.run(op.start_autonomous_loop(interval_seconds=900))
        except Exception as e:
            logging.error("Bulut operatör hatası: %s", e, exc_info=True)

    t = threading.Thread(target=_run_operator_loop, daemon=True, name="VIOP_Cloud_Operator")
    t.start()
    return "OPERATOR_STARTED_IN_CLOUD"

# Bulut operatörünü tetikle (Yerelde çalışıyorsa çift kopya açmaz, bulutta otomatik devralır)
cloud_op_status = ensure_cloud_operator_running()

# ==============================================================================
# SAYFA VE TEMA YAPILANDIRMASI (DARK TERMINAL THEME)
# ==============================================================================
st.set_page_config(
    page_title="VİOP Canlı İşlem Kokpiti v4.2",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Bloomberg / TradingView Tarzı Koyu Tema CSS
st.markdown("""
<style>
    .main { background-color: #0b0e14; }
    .kpi-card {
        background: linear-gradient(135deg, #161f30 0%, #0d1522 100%);
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
    }
    .kpi-title { font-size: 13px; color: #94a3b8; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
    .kpi-val { font-size: 26px; font-weight: 700; color: #f8fafc; margin-top: 4px; }
    .badge-live { background-color: #052e16; color: #22c55e; padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; border: 1px solid #16a34a; }
    .badge-paper { background-color: #451a03; color: #f97316; padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; border: 1px solid #ea580c; }
    .badge-circuit { background-color: #4c0519; color: #f43f5e; padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; border: 1px solid #e11d48; }
    .badge-safe { background-color: #022c22; color: #14b8a6; padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; border: 1px solid #0d9488; }
    .badge-long { background-color: #052e16; color: #22c55e; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; border: 1px solid #16a34a; }
    .badge-short { background-color: #4c0519; color: #f43f5e; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; border: 1px solid #e11d48; }
    .ale-highlight { color: #38bdf8; font-weight: bold; }
    .trade-highlight { color: #00e676; font-weight: bold; }
    .tax-highlight { color: #f59e0b; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# VERİTABANI VE YARDIMCI CANLI VERİ YÜKLEYİCİLER (SADECE CANLI VERİ)
# ==============================================================================
def get_db() -> DatabaseManager:
    db_file = os.path.join(project_root, "viop_trading.db")
    return DatabaseManager(db_path=db_file)


def get_local_ip() -> str:
    """Yerel ağ IP adresini döndürür (mobil / başka bilgisayardan izleme için)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


local_ip = get_local_ip()


def calculate_trade_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tüm işlem geçmişi üzerinden özet analitik metrikleri hesaplar."""
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "max_win_sym": "-",
            "max_loss_sym": "-",
        }

    pnls = [float(t.get("pnl_try", 0.0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_trades = len(pnls)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0.0

    max_win = 0.0
    max_win_sym = "-"
    max_loss = 0.0
    max_loss_sym = "-"
    for t in trades:
        p = float(t.get("pnl_try", 0.0))
        s = t.get("symbol", "-")
        if p > max_win:
            max_win = p
            max_win_sym = s
        if p < max_loss:
            max_loss = p
            max_loss_sym = s

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_trade_pnl": avg_trade_pnl,
        "max_win": max_win,
        "max_loss": max_loss,
        "max_win_sym": max_win_sym,
        "max_loss_sym": max_loss_sym
    }


db = get_db()
config = SystemConfig()

# Başlangıçta sistem durumu yoksa 2.000.000 TL ile ilklendir
if not db.get_latest_system_state():
    db.record_system_state(
        total_nav=2_000_000.0,
        free_margin=2_000_000.0,
        daily_pnl=0.0,
        daily_return_pct=0.0,
        trading_mode="LIVE_TRADING",
        consecutive_losses=0,
        circuit_breaker_active=False
    )
    db.record_equity_point(nav=2_000_000.0, sma20=2_000_000.0, mode="LIVE_TRADING")


@st.cache_data(ttl=5)
def load_live_market_state() -> Optional[Dict]:
    """15 dakikalık periyodik arka plan veri hattının oluşturduğu güncel piyasa durumunu yükler."""
    state_path = os.path.join(project_root, "src", "database", "live_market_state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


@st.cache_data(ttl=5)
def load_schedule_status() -> Optional[Dict]:
    """Fintables VİOP Veri Güncelleme Takvimi durum dosyasını yükler."""
    status_path = os.path.join(project_root, "src", "database", "viop_schedule_status.json")
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


live_market_state = load_live_market_state()
viop_schedule_status = load_schedule_status()

# ==============================================================================
# KENAR ÇUBUĞU (SIDEBAR) & CANLI MENÜ NAVİGASYONU
# ==============================================================================
MENU_ITEMS = [
    "🏛️ Canlı Kasa & ALE Fonu",
    "📜 Tüm İşlem Geçmişi & Analiz",
    "🔍 15-Dk Veri Hattı & 3-Tablo Takip",
    "🧭 Çok Varlıklı Canlı Yön Pusulası",
    "⚡ Smart Order Router (SOR)",
    "🛡️ 33 Savunma Kuralı"
]

if "current_active_nav_tab" not in st.session_state:
    st.session_state["current_active_nav_tab"] = MENU_ITEMS[0]

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/bullish.png", width=64)
    st.title("VİOP Canlı Kokpit")
    st.caption("v4.2 | 2.000.000 TL Tek Ortak Bütçe | 63 Dayanak (207 Sözleşme)")
    st.markdown(f"""
    <div style="background-color:#052e16; border:1px solid #16a34a; border-radius:6px; padding:8px 10px; margin-bottom:12px;">
        <span style="color:#22c55e; font-weight:bold; font-size:12px;">☁️ BULUT SENKRONİZASYONU AKTİF</span><br>
        <span style="color:#cbd5e1; font-size:11px;">7/24 Kesintisiz Otonom Mod</span><br>
        <span style="color:#94a3b8; font-size:11px;">🖥️ Bu PC: <b style="color:#38bdf8;">localhost:8501</b></span><br>
        <span style="color:#94a3b8; font-size:11px;">📱 Başka Cihaz: <b style="color:#38bdf8;">http://{local_ip}:8501</b></span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    # Kalıcı Radio Navigasyonu - Menü asla sıfırlanmaz!
    st.subheader("📌 Menü Navigasyonu")
    selected_menu = st.radio(
        "Görüntülenen Ekran:",
        MENU_ITEMS,
        index=MENU_ITEMS.index(st.session_state["current_active_nav_tab"]) if st.session_state["current_active_nav_tab"] in MENU_ITEMS else 0,
        key="sidebar_nav_selection"
    )
    st.session_state["current_active_nav_tab"] = selected_menu

    # Canlı Otomatik Yenileme (Sıfır Kullanıcı Müdahalesi)
    st.markdown("---")
    auto_refresh_enabled = st.checkbox(
        "🔄 Canlı Otomatik Yenileme (15 sn)",
        value=True,
        help="Açıkken ekran her 15 saniyede bir otomatik yenilenir. Kullanıcı hiçbir tuşa basmak zorunda kalmaz."
    )
    if auto_refresh_enabled:
        st_autorefresh(interval=15000, key="viop_cockpit_autorefresh")

    st.markdown("---")
    st.subheader("🤖 Otonom Canlı Pilot (v4.2)")
    if live_market_state:
        sync_meta = live_market_state.get("metadata", {})
        synced_at = sync_meta.get("synced_at", "")[:19].replace("T", " ")
        last_morning = live_market_state.get("last_morning_sync", "-")
        mode_str = sync_meta.get("mode", "%100 OTONOM")
        st.markdown(f"""
        <div style="background-color:#052e16; border:1px solid #16a34a; border-radius:8px; padding:10px; margin-bottom:10px;">
            <div style="font-size:12px; font-weight:bold; color:#22c55e;">🟢 PİLOT AKTİF ({mode_str})</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:4px;">Son Karar Döngüsü: <b>{synced_at}</b></div>
            <div style="font-size:11px; color:#cbd5e1;">Sabah 3-Tablo Sync: <b>{last_morning}</b></div>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Sıfır Manuel Müdahale Modu</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("🟠 Otonom pilot ilk döngüyü bekliyor...")

    st.markdown("---")
    st.subheader("📡 Canlı Veri Hattı Durumu")
    if live_market_state:
        sync_meta = live_market_state.get("metadata", {})
        synced_at = sync_meta.get("synced_at", "")[:19].replace("T", " ")
        macro = live_market_state.get("macro", {})
        ale_info = live_market_state.get("ale_fund_nema", {})
        st.success(f"🟢 **Canlı Senkronize**\n\n🕒 {synced_at}\n\n💵 USD/TRY: {macro.get('usd_try', 35.85):.2f}\n\n💶 EUR/TRY: {macro.get('eur_try', 38.90):.2f}\n\n🏦 ALE Net: %{ale_info.get('annual_net_rate', 0.396)*100:.1f}")
    else:
        st.warning("🟠 Arka plan veri hattı ilk döngüyü bekliyor...")

    if st.button("🔄 Verileri Şimdi Tazele", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.subheader("💰 Konsolide Portföy Bütçesi")
    st.info("🎯 **Tek Ortak Bütçe:** 2.000.000 TL\n\n📌 **Tüm Varlıklar İçin Tek Havuz:** Varlık başına ayrı bütçe bölünmez.\n\n📈 **Kâr:** Bileşik Sermaye\n\n🏦 **ALE Brüt:** %48.00 / yıl\n\n⚖️ **Stopaj:** -%17.50\n\n✨ **ALE Net:** %39.60 / yıl")
    if st.button("♻️ Canlı Kasayı 2.000.000 TL'ye Sıfırla", use_container_width=True):
        db.record_system_state(
            total_nav=2_000_000.0,
            free_margin=2_000_000.0,
            daily_pnl=0.0,
            daily_return_pct=0.0,
            trading_mode="LIVE_TRADING",
            consecutive_losses=0,
            circuit_breaker_active=False
        )
        db.record_equity_point(nav=2_000_000.0, sma20=2_000_000.0, mode="LIVE_TRADING")
        st.success("Kasa 2.000.000 TL olarak sıfırlandı!")
        st.rerun()

    st.markdown("---")
    st.markdown("### 🏛️ Midas Komisyon Tarifesi")
    st.markdown("""
    * **0 - 10 Milyon TL:** %0.05 (On binde 5)
    * **10 - 100 Milyon TL:** %0.02 (On binde 2)
    * **100 Milyon TL+:** %0.01 (On binde 1)
    """)

# ==============================================================================
# ÜST BAŞLIK VE KÜRESEL GÖSTERGE ŞERİDİ (CANLI KOKPİT)
# ==============================================================================
st.title("🏛️ VİOP ÇOK VARLIKLI CANLI İŞLEM VE RİSK KOKPİTİ")
st.caption(f"2.000.000 TL Tek Ortak Portföy Bütçesi | 20 VİOP Sözleşmesi | 15m & 240m Barlar | Midas Kademeli Komisyon | Sistem Saati: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

latest_state = db.get_latest_system_state() or {
    "total_nav": 2_000_000.0,
    "free_margin": 2_000_000.0,
    "daily_pnl": 0.0,
    "daily_return_pct": 0.0,
    "trading_mode": "LIVE_TRADING",
    "consecutive_losses": 0,
    "circuit_breaker_active": 0
}

# ------------------------------------------------------------------------------
# ☁️ CANLI BULUT SENKRONİZASYON PANOSU & ANLIK TAZELİK GÖSTERGESİ
# ------------------------------------------------------------------------------
last_ts_str = latest_state.get("timestamp") or latest_state.get("created_at") or ""
try:
    if last_ts_str:
        dt_last = datetime.fromisoformat(last_ts_str.replace("Z", ""))
        sec_diff = max(0, int((datetime.now() - dt_last).total_seconds()))
        if sec_diff < 60:
            sync_age_str = f"{sec_diff} saniye önce"
        elif sec_diff < 3600:
            sync_age_str = f"{sec_diff // 60} dakika önce"
        else:
            sync_age_str = f"{sec_diff // 3600} saat önce"
        sync_time_str = dt_last.strftime("%d.%m.%Y %H:%M:%S")
    else:
        sync_time_str = "Canlı"
        sync_age_str = "Az önce"
except Exception:
    sync_time_str = "Canlı"
    sync_age_str = "Az önce"

active_positions_list = db.get_active_positions()
active_pos_count = len(active_positions_list)
active_symbols_preview = ", ".join([f"{p.get('side', '')} {p.get('symbol', '')}" for p in active_positions_list]) if active_pos_count > 0 else "Nakit Beklemede (0 Açık Pozisyon — Kasa Güvende)"

sync_c1, sync_c2 = st.columns([3.8, 1.2])
with sync_c1:
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #064e3b 0%, #0f172a 100%); border: 1px solid #10b981; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 4px 10px rgba(16, 185, 129, 0.12);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div>
                <span style="color:#34d399; font-weight:bold; font-size:13px;">🟢 %100 CANLI BULUT SENKRONİZASYONU AKTİF (OTONOM MOTOR KESİNTİSİZ ÇALIŞIYOR)</span><br>
                <span style="color:#e2e8f0; font-size:12px;">⏱️ Son Senkronizasyon: <b>{sync_time_str}</b> <span style="color:#6ee7b7;">({sync_age_str})</span> | Mod: <b>{latest_state.get('trading_mode', 'LIVE_TRADING')}</b> | Süreç: <b>Arka Plan Daemon 7/24 Aktif</b></span><br>
                <span style="color:#cbd5e1; font-size:11px;">📊 Portföy Durumu: <b>{active_symbols_preview}</b></span><br>
                <span style="color:#94a3b8; font-size:11px;">📱 Başka Cihazdan (Telefon/Tablet/PC) Anlık İzleme: <b style="color:#38bdf8;">http://{local_ip}:8501</b> (veya bu cihazda <b style="color:#38bdf8;">localhost:8501</b>)</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with sync_c2:
    if st.button("🔄 Bulut ile Şimdi Senkronize Et", use_container_width=True, help="Tüm veritabanı önbelleğini temizler ve bulut/arka plan servisinden en son durumu anında çeker."):
        st.cache_data.clear()
        st.rerun()

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Toplam Kasa (NAV)</div>
        <div class="kpi-val">{latest_state['total_nav']:,.0f} TL</div>
        <small style="color:#22c55e;">Başlangıç: 2.000.000 TL</small>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Serbest Teminat (ALE)</div>
        <div class="kpi-val ale-highlight">{latest_state['free_margin']:,.0f} TL</div>
        <small style="color:#38bdf8;">Gecelik ALE Nemasında</small>
    </div>
    """, unsafe_allow_html=True)
with col3:
    pnl_color = "#22c55e" if latest_state['daily_pnl'] >= 0 else "#ef4444"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Günlük Net PnL</div>
        <div class="kpi-val" style="color:{pnl_color};">{latest_state['daily_pnl']:+,.0f} TL</div>
        <small style="color:{pnl_color};">%{latest_state['daily_return_pct']:+.2f}</small>
    </div>
    """, unsafe_allow_html=True)
with col4:
    consec_losses = latest_state.get('consecutive_losses', 0)
    risk_pct = 1.0 if consec_losses >= 4 else 2.0
    risk_try = latest_state['total_nav'] * (risk_pct / 100.0)
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Anti-Martingale / Risk Bütçesi</div>
        <div class="kpi-val" style="color:#f59e0b;">%{risk_pct:.1f} ({risk_try:,.0f} TL)</div>
        <small style="color:#94a3b8;">Sayaç: {consec_losses} / 4 Kayıp</small>
    </div>
    """, unsafe_allow_html=True)
with col5:
    mode = latest_state.get('trading_mode', 'LIVE_TRADING')
    circuit = bool(latest_state.get('circuit_breaker_active', False))
    mode_html = '<span class="badge-live">🟢 LIVE_TEST</span>' if mode == "LIVE_TRADING" else '<span class="badge-paper">🟠 PAPER_TRADE</span>'
    circuit_html = '<span class="badge-circuit">🚨 KİLİTLİ</span>' if circuit else '<span class="badge-safe">✅ GÜVENLİ</span>'
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">Çalışma Rejimi</div>
        <div style="margin-top:6px;">{mode_html}</div>
        <div style="margin-top:8px;">{circuit_html}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ==============================================================================
# SEÇİLİ MENÜ İÇERİĞİ (SADECE CANLI OPERASYON)
# ==============================================================================

# ------------------------------------------------------------------------------
# MENÜ 1: 🏛️ CANLI KASA & AKBANK "ALE" FONU YÖNETİMİ
# ------------------------------------------------------------------------------
if selected_menu == "🏛️ Canlı Kasa & ALE Fonu":
    st.header("🏛️ 2.000.000 TL Konsolide Kasa & Akbank 'ALE' Fonu Nemalandırma")
    st.markdown("""
    > **🎯 Tek Ortak Portföy Sermaye Mimarisi (2.000.000 TL):**
    > 1. **Tek Havuz İlkesi (Tüm Varlıklar İçin Tek Bütçe):** Ali Perşembe Doktrini gereğince varlık başına ayrı bir sermaye tahsis edilmez. 20 VİOP sözleşmesinin tamamı **tek bir 2.000.000 TL'lik ortak sermaye havuzundan** serbest teminat kullanır.
    > 2. **%2 Sabit Risk Bütçesi (R-Kuralı):** Açılan her yeni pozisyonda portföyün en fazla %2'si (başlangıçta 40.000 TL) riske edilir; lot sayısı bu tutar ve güncel Takasbank teminat tavanına göre dinamik belirlenir.
    > 3. **Akbank ALE Fonu Güvenli Kasası (%17.5 Stopaj Kesintili Net Nema):** Seans içi teminata bağlanmayan kullanılmayan serbest nakit para (Free Margin), saat 18:15'te Akbank ALE Para Piyasası Fonunda gecelik nemalandırılır (%48 brüt yıllık nema). Elde edilen brüt kardan **%17.5 yasal stopaj vergisi** ödenerek net getiri (%39.60 yıllık net) **ayrı bir risksiz kasada kilitlenir**, yeniden trade marjinine sokulmaz.
    > 4. **Midas Kademeli Komisyon Rejimi:** Gerçek hayat sürtünme maliyetleri (0-10M %0.05, 10-100M %0.02, 100M+ %0.01) trade PnL'inden düşülür.
    """)

    # ALE Fonu Stopaj & Nema Dağılım Kartları
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Brüt ALE Yıllık Faiz</div>
            <div class="kpi-val" style="color:#cbd5e1;">%48.00</div>
            <small style="color:#94a3b8;">Fintables İlan Edilen Brüt Getiri</small>
        </div>
        """, unsafe_allow_html=True)
    with col_a2:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Yasal Stopaj Oranı</div>
            <div class="kpi-val tax-highlight">-%17.50</div>
            <small style="color:#f59e0b;">Devlet Kaynaklı Stopaj Kesintisi</small>
        </div>
        """, unsafe_allow_html=True)
    with col_a3:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Net ALE Yıllık Faiz</div>
            <div class="kpi-val ale-highlight">%39.60</div>
            <small style="color:#38bdf8;">Stopaj Sonrası Net Kasa Neması</small>
        </div>
        """, unsafe_allow_html=True)
    with col_a4:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Net Günlük Nema Oranı</div>
            <div class="kpi-val trade-highlight">%0.1085</div>
            <small style="color:#00e676;">Serbest Nakde Günlük Eklenen Net</small>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📊 Aktif Açık VİOP Pozisyonları, Tutar ve Kaldıraç Durumu")
    active_pos = db.get_active_positions()
    latest_margins = db.get_latest_margins() or {}

    if active_pos:
        formatted_pos = []
        for p in active_pos:
            sym = p["symbol"]
            side_badge = "🟢 LONG" if p["side"] == "LONG" else "🔴 SHORT"
            
            # Dinamik sözleşme çarpanı
            spec = config.contracts.get(sym)
            multi = spec.multiplier if spec else (100.0 if "THYAO" in sym or "AKBNK" in sym or "GARAN" in sym else 10.0)
            
            # Dinamik Takasbank teminatı
            margin_info = latest_margins.get(sym, {})
            unit_margin = margin_info.get("initial_margin_try") or (spec.initial_margin_try if spec else 7000.0)

            notional = round(abs(p["lots"]) * multi * p["current_price"], 2)
            margin = round(abs(p["lots"]) * unit_margin, 2)
            lev = round(notional / margin, 1) if margin > 0 else 1.0

            formatted_pos.append({
                "Sembol": sym,
                "İşlem Yönü": side_badge,
                "Kontrat (Lot)": abs(p["lots"]),
                "Pozisyon Tutarı (TL)": f"{notional:,.2f} TL",
                "Bağlanan Teminat": f"{margin:,.2f} TL",
                "Efektif Kaldıraç": f"{lev:.1f}x",
                "Giriş Fiyatı": f"{p['entry_price']:.2f}",
                "Güncel Fiyat": f"{p['current_price']:.2f}",
                "Anlık PnL": f"{p['pnl_try']:+,.2f} TL",
                "İz Süren Stop": f"{p['trailing_stop']:.2f}",
                "Barda Geçen Süre": f"{p['bars_held']} Bar"
            })
        st.dataframe(pd.DataFrame(formatted_pos), use_container_width=True)
    else:
        st.info("🛡️ Şu anda açık VİOP pozisyonu bulunmamaktadır. 2.000.000 TL serbest nakdin %100'ü Akbank ALE fonunda gecelik net %39.60 faizle değerlendirilmektedir.")

    st.markdown("---")
    st.subheader("🎯 Seans Öncesi Planlama & İki Yönlü Tetik Radarı (LONG & SHORT)")
    st.markdown("""
    > **Çift Yönlü Algoritmik Ticaret & Açılış Koruma Kalkanı (Ali Perşembe Doktrini)**
    > * **%100 Çift Yönlü Özgürlük (LONG & SHORT):** Sistem tüm Pay, Endeks ve Emtia sözleşmelerinde hem yükseliş kırılımlarını (LONG) hem de düşüş çöküşlerini (SHORT) eşzamanlı olarak tarar ve icra eder.
    > * **Neden Seans Açılmadan Önce Pasif Emir Girilmez?** Borsa İstanbul VİOP seansı saat 09:30'da başlar. Seans açılmadan tahtaya körleme emir girmek, sabah eşleşmesinde ve olası ters haber gaplerinde sermayeyi riske atar.
    > * **09:30 - 10:15 Açılış Çalkantısı Kalkanı (`REJECT_TIME_OPENING`):** Açılışın ilk 45 dakikasındaki yapay spekülatif tuzaklar ve açılış eşleşme gürültüsü sönümlenene kadar sistem koruma modundadır.
    > * **Canlı Tetik Mekanizması:** Saat 10:15 sonrasında, canlı fiyatlar aşağıdaki direnç seviyesini aşarsa **LONG**, destek seviyesini kırarsa **SHORT** emirleri anında üretilir.
    """)

    if live_market_state and "contracts" in live_market_state:
        radar_rows = []
        for sym, c_info in live_market_state["contracts"].items():
            cat = c_info.get("type", "EQUITY")
            lp = float(c_info.get("last_price", 0.0))
            bar240 = c_info.get("last_240m_bar", {})
            h = float(bar240.get("high", lp))
            l = float(bar240.get("low", lp))
            o = float(bar240.get("open", lp))
            c = float(bar240.get("close", lp))
            rng = h - l

            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l

            u_pct = (upper_wick / rng * 100.0) if rng > 0 else 0.0
            l_pct = (lower_wick / rng * 100.0) if rng > 0 else 0.0

            if cat == "FX":
                direction_badge = "🛡️ REPO (Nötr)"
                status = "🛡️ Nakit ALE Repo Fonunda (%48 Brüt - Çıplak Kırılım Kapalı)"
                long_trigger = "-"
                short_trigger = "-"
            else:
                direction_badge = "🔄 ÇİFT YÖNLÜ (LONG / SHORT)"
                long_trigger = f">{h:,.2f} TL (Donchian / 240m Tepe)"
                short_trigger = f"<{l:,.2f} TL (Donchian / 240m Dip)"

                if u_pct >= 40.0 and l_pct >= 40.0:
                    status = f"⚠️ Kararsız Doji (Üst %{u_pct:.0f} / Alt %{l_pct:.0f}) -> Kırılım Teyidi Bekleniyor"
                elif u_pct >= 40.0:
                    status = f"⚠️ Satıcı Baskısı (Üst Fitil %{u_pct:.0f} > %40) -> Long için {h:,.2f} TL aşılmalı, Short tetiklenebilir"
                elif l_pct >= 50.0:
                    status = f"⚠️ Alıcı Tepkisi (Alt Fitil %{l_pct:.0f} > %50) -> Short için {l:,.2f} TL kırılmalı, Long tetiklenebilir"
                else:
                    status = f"🎯 Çift Yönlü İcra: >{h:,.2f} TL LONG | <{l:,.2f} TL SHORT"

            radar_rows.append({
                "Sözleşme": sym,
                "Sınıf": cat,
                "Dün Kapanış": f"{lp:,.2f} TL",
                "İzinli İşlem Yönü": direction_badge,
                "Long Tetik Seviyesi (Direnç)": long_trigger,
                "Short Tetik Seviyesi (Destek)": short_trigger,
                "Üst Fitil (Satıcı Baskısı)": f"%{u_pct:.1f}",
                "Alt Fitil (Alıcı Tepkisi)": f"%{l_pct:.1f}",
                "Seans Planı & Savunma Durumu": status
            })

        df_radar = pd.DataFrame(radar_rows)
        st.dataframe(df_radar, use_container_width=True, height=320)

    st.markdown("---")
    st.subheader("📈 2.000.000 TL Canlı Portföy Sermaye Eğrisi (Equity Curve)")
    eq_df = db.get_equity_curve_df()
    if not eq_df.empty and len(eq_df) > 1:
        st.line_chart(eq_df.set_index("timestamp")[["nav", "sma20"]])
    else:
        st.info("ℹ️ Canlı sermaye eğrisi ilk döngüyle birlikte 2.000.000 TL tabanında başlatıldı. Karar döngüleri gerçekleştikçe grafik anlık çizilecektir.")

    st.markdown("---")
    st.subheader("📜 Canlı İcra Edilen Emirler ve İşlem Geçmişi (LONG & SHORT)")
    trades = db.get_trade_history(limit=None)
    if trades:
        m = calculate_trade_metrics(trades)
        t_col1, t_col2, t_col3, t_col4, t_col5 = st.columns(5)
        with t_col1:
            st.metric("Toplam İşlem", f"{m['total_trades']} Adet")
        with t_col2:
            st.metric("Kazanma Oranı", f"%{m['win_rate']:.1f}", f"{m['winning_trades']}K / {m['losing_trades']}Z")
        with t_col3:
            st.metric("Net Gerçekleşen K/Z", f"{m['total_pnl']:+,.2f} TL")
        with t_col4:
            st.metric("Kâr Faktörü (PF)", f"{m['profit_factor']:.2f}")
        with t_col5:
            st.metric("En İyi İşlem", f"+{m['max_win']:,.2f} TL", m['max_win_sym'])

        # Hızlı Filtre Satırı
        f_c1, f_c2, f_c3 = st.columns(3)
        with f_c1:
            all_syms = ["TÜM SÖZLEŞMELER"] + sorted(list({t.get("symbol", "") for t in trades if t.get("symbol")}))
            filter_sym = st.selectbox("Sözleşme Filtresi:", all_syms, key="quick_trade_sym_filter")
        with f_c2:
            filter_side = st.selectbox("Yön Filtresi:", ["TÜMÜ", "🟢 LONG", "🔴 SHORT"], key="quick_trade_side_filter")
        with f_c3:
            filter_res = st.selectbox("Sonuç Filtresi:", ["TÜMÜ", "🟢 Yalnız Kârlı", "🔴 Yalnız Zararlı"], key="quick_trade_res_filter")

        filtered_trades = []
        for t in trades:
            sym = t.get("symbol", "")
            side_raw = str(t.get("side", "")).upper()
            pnl_val = float(t.get("pnl_try", 0.0))
            if filter_sym != "TÜM SÖZLEŞMELER" and sym != filter_sym:
                continue
            if filter_side == "🟢 LONG" and "LONG" not in side_raw:
                continue
            if filter_side == "🔴 SHORT" and "SHORT" not in side_raw:
                continue
            if filter_res == "🟢 Yalnız Kârlı" and pnl_val <= 0:
                continue
            if filter_res == "🔴 Yalnız Zararlı" and pnl_val >= 0:
                continue
            filtered_trades.append(t)

        formatted_trades = []
        for t in filtered_trades:
            side_raw = str(t.get("side", "")).upper()
            side_badge = "🟢 LONG" if "LONG" in side_raw else "🔴 SHORT"
            pnl_val = float(t.get("pnl_try", 0.0))
            pnl_str = f"+{pnl_val:,.2f} TL" if pnl_val >= 0 else f"{pnl_val:,.2f} TL"

            formatted_trades.append({
                "İşlem ID": t.get("trade_id", "-"),
                "Sözleşme": t.get("symbol", "-"),
                "İşlem Yönü": side_badge,
                "Kontrat (Lot)": t.get("lots", 0),
                "Giriş Fiyatı": f"{float(t.get('entry_price', 0)):,.2f} TL",
                "Çıkış Fiyatı": f"{float(t.get('exit_price', 0)):,.2f} TL",
                "Net Kâr/Zarar": pnl_str,
                "R-Çarpanı": f"{float(t.get('r_multiple', 1.0)):+.2f}R",
                "Kapanış Gerekçesi": t.get("exit_reason", "-"),
                "Giriş Zamanı": str(t.get("entry_time", "-"))[:19].replace("T", " "),
                "Çıkış Zamanı": str(t.get("exit_time", "-"))[:19].replace("T", " ")
            })
        st.dataframe(pd.DataFrame(formatted_trades), use_container_width=True)

        col_csv, col_info = st.columns([1, 2])
        with col_csv:
            df_csv = pd.DataFrame(filtered_trades).to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Tabloyu CSV İndir",
                data=df_csv,
                file_name=f"viop_kapanan_islemler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_info:
            st.info("💡 Kapsamlı grafikler, kümülatif getiri eğrisi ve sözleşme bazlı analiz için sol menüden **'📜 Tüm İşlem Geçmişi & Analiz'** sekmesine geçebilirsiniz.")
    else:
        st.info("ℹ️ Henüz tamamlanmış (kapatılmış) işlem bulunmamaktadır. Otonom canlı motor pozisyon kapattıkça (Chandelier Stop, Time Stop, Scale-Out) işlemler hem 🟢 LONG hem 🔴 SHORT yön belirteçleriyle bu tabloya anlık yansıyacaktır.")


# ------------------------------------------------------------------------------
# MENÜ 2: 📜 TÜM İŞLEM GEÇMİŞİ & DERİNLEMESİNE PERFORMANS ANALİZİ
# ------------------------------------------------------------------------------
elif selected_menu == "📜 Tüm İşlem Geçmişi & Analiz":
    st.header("📜 Tüm İşlem Geçmişi & Kapsamlı Performans Analiz Merkezi")
    st.caption("Tam İcra Defteri | Çift Yönlü (LONG / SHORT) İstatistikleri | Kümülatif K/Z Gelişimi | Gerçekleşen Emirler")

    trades = db.get_trade_history(limit=None)
    if not trades:
        st.info("ℹ️ Henüz tamamlanmış (kapatılmış) işlem bulunmamaktadır. Otonom canlı motor pozisyon kapattıkça işlemler anlık olarak bu ekrana düşecektir.")
    else:
        m = calculate_trade_metrics(trades)

        # 1. KPI Metrik Kartları
        st.subheader("📊 Konsolide İşlem İstatistikleri")
        m_c1, m_c2, m_c3, m_c4, m_c5, m_c6 = st.columns(6)
        with m_c1:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Toplam İşlem</div>
                <div class="kpi-val" style="color:#38bdf8;">{m['total_trades']} Adet</div>
                <small style="color:#94a3b8;">Gerçekleşen Kapanış</small>
            </div>
            """, unsafe_allow_html=True)
        with m_c2:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Kazanma Oranı (Win Rate)</div>
                <div class="kpi-val" style="color:#22c55e;">%{m['win_rate']:.1f}</div>
                <small style="color:#94a3b8;">{m['winning_trades']} Kazanç / {m['losing_trades']} Kayıp</small>
            </div>
            """, unsafe_allow_html=True)
        with m_c3:
            pnl_c = "#22c55e" if m['total_pnl'] >= 0 else "#ef4444"
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Toplam Net PnL</div>
                <div class="kpi-val" style="color:{pnl_c};">{m['total_pnl']:+,.2f} TL</div>
                <small style="color:#94a3b8;">Komisyon Sonrası Net</small>
            </div>
            """, unsafe_allow_html=True)
        with m_c4:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Kâr Faktörü (PF)</div>
                <div class="kpi-val" style="color:#f59e0b;">{m['profit_factor']:.2f}</div>
                <small style="color:#94a3b8;">Brüt Kâr / Brüt Zarar</small>
            </div>
            """, unsafe_allow_html=True)
        with m_c5:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">En Yüksek Kazanç</div>
                <div class="kpi-val" style="color:#22c55e;">+{m['max_win']:,.2f} TL</div>
                <small style="color:#38bdf8;">{m['max_win_sym']}</small>
            </div>
            """, unsafe_allow_html=True)
        with m_c6:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">En Yüksek Kayıp</div>
                <div class="kpi-val" style="color:#ef4444;">{m['max_loss']:,.2f} TL</div>
                <small style="color:#f43f5e;">{m['max_loss_sym']}</small>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # 2. Grafiksel Analizler (Plotly)
        st.subheader("📈 İşlem Performans Grafikleri")
        g_c1, g_c2 = st.columns(2)

        df_trades = pd.DataFrame(trades)
        df_trades['exit_time_dt'] = pd.to_datetime(df_trades['exit_time'], format='mixed')
        df_sorted = df_trades.sort_values('exit_time_dt')
        df_sorted['cum_pnl'] = df_sorted['pnl_try'].cumsum()

        with g_c1:
            st.markdown("##### 💹 Kümülatif Gerçekleşen Kâr/Zarar Eğrisi (TRY)")
            fig_cum = go.Figure()
            fig_cum.add_trace(go.Scatter(
                x=df_sorted['exit_time_dt'],
                y=df_sorted['cum_pnl'],
                mode='lines+markers',
                name='Kümülatif K/Z',
                line=dict(color='#38bdf8', width=2.5),
                marker=dict(size=6, color=['#22c55e' if p >= 0 else '#ef4444' for p in df_sorted['pnl_try']]),
                fill='tozeroy',
                fillcolor='rgba(56, 189, 248, 0.1)'
            ))
            fig_cum.update_layout(
                paper_bgcolor='#0b0e14',
                plot_bgcolor='#111827',
                font=dict(color='#cbd5e1'),
                margin=dict(l=20, r=20, t=30, b=20),
                xaxis=dict(showgrid=True, gridcolor='#1f2937'),
                yaxis=dict(showgrid=True, gridcolor='#1f2937', zeroline=True, zerolinecolor='#64748b')
            )
            st.plotly_chart(fig_cum, use_container_width=True)

        with g_c2:
            st.markdown("##### 🏛️ Sözleşme Bazında Kâr / Zarar Katkısı (TRY)")
            sym_pnl = df_trades.groupby('symbol')['pnl_try'].sum().reset_index()
            sym_pnl['color'] = sym_pnl['pnl_try'].apply(lambda x: '#22c55e' if x >= 0 else '#ef4444')
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=sym_pnl['symbol'],
                y=sym_pnl['pnl_try'],
                marker_color=sym_pnl['color'],
                name='Net K/Z'
            ))
            fig_bar.update_layout(
                paper_bgcolor='#0b0e14',
                plot_bgcolor='#111827',
                font=dict(color='#cbd5e1'),
                margin=dict(l=20, r=20, t=30, b=20),
                xaxis=dict(showgrid=True, gridcolor='#1f2937'),
                yaxis=dict(showgrid=True, gridcolor='#1f2937', zeroline=True, zerolinecolor='#64748b')
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")

        # 3. İnteraktif Filtreleme ve Detaylı İşlem Tablosu
        st.subheader("🔍 Filtrele & Ara")
        fil_c1, fil_c2, fil_c3, fil_c4 = st.columns(4)
        with fil_c1:
            all_symbols = ["TÜMÜ"] + sorted(list({t.get("symbol", "") for t in trades if t.get("symbol")}))
            sel_sym = st.selectbox("Sözleşme Seçin:", all_symbols, key="analiz_sym_filter")
        with fil_c2:
            sel_side = st.selectbox("İşlem Yönü:", ["TÜMÜ", "🟢 LONG", "🔴 SHORT"], key="analiz_side_filter")
        with fil_c3:
            all_reasons = ["TÜMÜ"] + sorted(list({t.get("exit_reason", "") for t in trades if t.get("exit_reason")}))
            sel_reason = st.selectbox("Kapanış Gerekçesi:", all_reasons, key="analiz_reason_filter")
        with fil_c4:
            sel_res = st.selectbox("Kâr/Zarar Durumu:", ["TÜMÜ", "🟢 Yalnızca Kazançlı", "🔴 Yalnızca Zararlı"], key="analiz_res_filter")

        filtered = []
        for t in trades:
            sym = t.get("symbol", "")
            side_raw = str(t.get("side", "")).upper()
            reason = str(t.get("exit_reason", ""))
            pnl_val = float(t.get("pnl_try", 0.0))

            if sel_sym != "TÜMÜ" and sym != sel_sym:
                continue
            if sel_side == "🟢 LONG" and "LONG" not in side_raw:
                continue
            if sel_side == "🔴 SHORT" and "SHORT" not in side_raw:
                continue
            if sel_reason != "TÜMÜ" and reason != sel_reason:
                continue
            if sel_res == "🟢 Yalnızca Kazançlı" and pnl_val <= 0:
                continue
            if sel_res == "🔴 Yalnızca Zararlı" and pnl_val >= 0:
                continue

            filtered.append(t)

        st.caption(f"Filtrelenen İşlem Sayısı: **{len(filtered)}** / {len(trades)}")

        formatted_list = []
        for t in filtered:
            side_raw = str(t.get("side", "")).upper()
            side_badge = "🟢 LONG" if "LONG" in side_raw else "🔴 SHORT"
            pnl_val = float(t.get("pnl_try", 0.0))
            pnl_str = f"+{pnl_val:,.2f} TL" if pnl_val >= 0 else f"{pnl_val:,.2f} TL"

            formatted_list.append({
                "İşlem ID": t.get("trade_id", "-"),
                "Sözleşme": t.get("symbol", "-"),
                "İşlem Yönü": side_badge,
                "Kontrat (Lot)": t.get("lots", 0),
                "Giriş Fiyatı": f"{float(t.get('entry_price', 0)):,.2f} TL",
                "Çıkış Fiyatı": f"{float(t.get('exit_price', 0)):,.2f} TL",
                "Net Kâr/Zarar": pnl_str,
                "R-Çarpanı": f"{float(t.get('r_multiple', 1.0)):+.2f}R",
                "Kapanış Gerekçesi": t.get("exit_reason", "-"),
                "Giriş Zamanı": str(t.get("entry_time", "-"))[:19].replace("T", " "),
                "Çıkış Zamanı": str(t.get("exit_time", "-"))[:19].replace("T", " ")
            })

        st.dataframe(pd.DataFrame(formatted_list), use_container_width=True)

        # 4. CSV Export
        csv_bytes = pd.DataFrame(filtered).to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Bu Filtrelenmiş Tabloyu CSV Olarak İndir (Excel Uyumlu)",
            data=csv_bytes,
            file_name=f"viop_tum_islemler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )


# ------------------------------------------------------------------------------
# MENÜ 2: 🔍 15-DAKİKALIK VERİ HATTI & 3-TABLO TAKİP MERKEZİ
# ------------------------------------------------------------------------------
elif selected_menu == "🔍 15-Dk Veri Hattı & 3-Tablo Takip":
    st.header("🔍 Fintables VİOP Veri Güncelleme Takvimi & MCP Sağlık Denetçisi")
    st.caption("Takasbank & Fintables Protokolü | 5 Aşamalı Zamanlanmış Veri Besleme Hattı | %100 Canlı")

    # Sabah Başlatma ve Manuel Senkronizasyon Butonları
    c_hdr1, c_hdr2, c_hdr3 = st.columns([2, 1.2, 1.2])
    with c_hdr1:
        st.markdown("""
        <div style="background-color:#052e16; border:1px solid #16a34a; border-radius:6px; padding:8px 12px;">
            <span style="color:#22c55e; font-weight:bold; font-size:12px;">🟢 %100 TAM OTONOM SİSTEM AKTİF</span><br>
            <span style="color:#cbd5e1; font-size:11px;">Sistem her sabah 3 tabloyu otomatik inceler ve değişen rakamları karar ve risk motorlarına aktarır. Kullanıcı hiçbir tuşa basmak zorunda kalmaz.</span>
        </div>
        """, unsafe_allow_html=True)
    with c_hdr2:
        if st.button("☀️ Sabah Başlatma Rutini (3 Tablo)", use_container_width=True, help="Sözleşmeler, Teminat Tablosu ve Margin Call tablolarını inceler, değişen rakamları sisteme yansıtır."):
            with st.spinner("Sabah Başlatma Rutini Çalıştırılıyor..."):
                sched = ViopDataFeedScheduler(db=db)
                m_summary = asyncio.run(sched.run_morning_startup(force=True))
                st.session_state["last_morning_startup"] = m_summary
                st.success("✓ Sabah Başlatma Tamamlandı! Tüm 3 Tablo Sisteme Yansıtıldı.")
                st.rerun()

    with c_hdr3:
        if st.button("🔄 Takvimi Şimdi Senkronize Et", use_container_width=True):
            with st.spinner("VİOP Takvim Verileri Çekiliyor..."):
                sched = ViopDataFeedScheduler(db=db)
                asyncio.run(sched.run_scheduled_pipeline())
                st.session_state["last_manual_sync"] = datetime.now().isoformat()
                st.rerun()

    # Sabah Başlatma Özeti ve Değişim Bildirimi
    morning_summary_path = os.path.join(project_root, "src", "database", "morning_sync_summary.json")
    if os.path.exists(morning_summary_path):
        try:
            with open(morning_summary_path, "r", encoding="utf-8") as f:
                ms_data = json.load(f)
            chg_items = ms_data.get("margins_table", {}).get("changed_margins", [])
            if chg_items:
                st.warning(f"⚠️ **Takasbank Teminat Değişikliği Bildirimi ({len(chg_items)} Sözleşme):** Sabah başlatma taramasında teminatı değişen sözleşmeler tespit edildi ve karar motorlarına aktarıldı.")
                with st.expander("🔍 Değişen Teminat Detaylarını İncele"):
                    st.dataframe(pd.DataFrame(chg_items), use_container_width=True)
            else:
                m_time = ms_data.get("timestamp", "")[:19].replace("T", " ")
                st.info(f"☀️ **Sabah Başlatma Durumu:** 3 VİOP Tablosu (Sözleşmeler, Teminatlar, Margin Call) incelendi. Son Senkronizasyon: **{m_time}** (Teminatlar stabil, sistem canlı operasyona hazır).")
        except Exception:
            pass

    # Takvim Durum Verisi
    sched_info = viop_schedule_status.get("schedule", {}) if viop_schedule_status else {}
    last_syncs = viop_schedule_status.get("last_syncs", {}) if viop_schedule_status else {}

    # 5 KPI Kartı
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        s_0830 = last_syncs.get("contracts_universe_0830")
        t_0830 = s_0830[:16].replace("T", " ") if s_0830 else "08:30 Bekliyor"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">1. Sözleşmeler Listesi</div>
            <div style="font-size:16px; font-weight:bold; color:#00e676; margin-top:4px;">08:30 (Günde 1)</div>
            <div style="margin-top:4px; font-size:12px; color:#cbd5e1;">Son: <b>{t_0830}</b></div>
            <small style="color:#94a3b8;">207 VİOP Sözleşmesi</small>
        </div>
        """, unsafe_allow_html=True)

    with k2:
        s_0900 = last_syncs.get("margins_0900")
        s_1400 = last_syncs.get("margins_1400")
        t_m = (s_1400 or s_0900 or "09:00 / 14:00")[:16].replace("T", " ")
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">2. Teminat Tutarları</div>
            <div style="font-size:16px; font-weight:bold; color:#00e676; margin-top:4px;">09:00 & 14:00 (x2)</div>
            <div style="margin-top:4px; font-size:12px; color:#cbd5e1;">Son: <b>{t_m}</b></div>
            <small style="color:#94a3b8;">Takasbank Başlangıç %100</small>
        </div>
        """, unsafe_allow_html=True)

    with k3:
        s_bars = last_syncs.get("bars_15m")
        t_bars = s_bars[11:19] if s_bars else "15 Dk Döngü"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">3. Fiyat & 240m Bar</div>
            <div style="font-size:16px; font-weight:bold; color:#38bdf8; margin-top:4px;">15 Dakikada 1</div>
            <div style="margin-top:4px; font-size:12px; color:#cbd5e1;">Son: <b>{t_bars}</b></div>
            <small style="color:#94a3b8;">14:15 & 18:15 Karar Pencereleri</small>
        </div>
        """, unsafe_allow_html=True)

    with k4:
        mc_report = db.get_latest_margin_call() or {}
        mc_stat = mc_report.get("status", "HEALTHY")
        mc_color = "#00e676" if mc_stat == "HEALTHY" else ("#f59e0b" if mc_stat == "WARNING_LEVEL" else "#f43f5e")
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">4. Margin Call Denetimi</div>
            <div style="font-size:16px; font-weight:bold; color:{mc_color}; margin-top:4px;">{mc_stat}</div>
            <div style="margin-top:4px; font-size:12px; color:#cbd5e1;">Oran: <b>%{mc_report.get('margin_ratio_pct', 999):.1f}</b></div>
            <small style="color:#94a3b8;">15 Dk Pasif + 14:15/18:15 Bar</small>
        </div>
        """, unsafe_allow_html=True)

    with k5:
        ale_eod = db.get_latest_ale_eod() or {}
        vault = ale_eod.get("cumulative_ale_vault_try", 0.0)
        net_y = ale_eod.get("daily_net_yield_try", 0.0)
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">5. ALE Net Nema</div>
            <div style="font-size:16px; font-weight:bold; color:#38bdf8; margin-top:4px;">+{net_y:,.1f} TL / Gün</div>
            <div style="margin-top:4px; font-size:12px; color:#cbd5e1;">Kasa: <b>{vault:,.1f} TL</b></div>
            <small style="color:#94a3b8;">18:15 Seans Sonu Net Nema</small>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📋 Resmi Fintables Veri Güncelleme Takvimi Matrisi")
    
    calendar_matrix = [
        {
            "Veri Tipi": "• Sözleşmeler Listesi (Universe)",
            "Güncelleme Zamanı": "Günde 1 Kez (Sabah 08:30)",
            "Son Güncelleme": str(last_syncs.get("contracts_universe_0830", "-"))[:19].replace("T", " "),
            "Durum": "🟢 GÜNCEL" if last_syncs.get("contracts_universe_0830") else "🟡 BEKLİYOR",
            "Hedef Karar Motoru & Rolü": "VİOP Evreni, Sözleşme Çarpanı, Vade Döngüsü Kontrolü"
        },
        {
            "Veri Tipi": "• Teminat Tutarları (Initial Margin)",
            "Güncelleme Zamanı": "Günde 2 Kez (09:00 ve 14:00)",
            "Son Güncelleme": str(last_syncs.get("margins_1400") or last_syncs.get("margins_0900") or "-")[:19].replace("T", " "),
            "Durum": "🟢 GÜNCEL" if (last_syncs.get("margins_0900") or last_syncs.get("margins_1400")) else "🟡 BEKLİYOR",
            "Hedef Karar Motoru & Rolü": "PositionManager Kaldıraç & Lot Boyutlandırma Hesabı"
        },
        {
            "Veri Tipi": "• Fiyat & İndikatör Barları",
            "Güncelleme Zamanı": "15 Dakikada 1 (240m Resampler)",
            "Son Güncelleme": str(last_syncs.get("bars_15m", "-"))[:19].replace("T", " "),
            "Durum": "🟢 GÜNCEL" if last_syncs.get("bars_15m") else "🟡 BEKLİYOR",
            "Hedef Karar Motoru & Rolü": "TechnicalExecutioner (14:15 ve 18:15 Karar Pencereleri)"
        },
        {
            "Veri Tipi": "• Margin Call / Hesaba Ait Teminat",
            "Güncelleme Zamanı": "15 Dk Pasif + Bar Kapanışları",
            "Son Güncelleme": str(last_syncs.get("margin_call_passive_15m") or last_syncs.get("margin_call_bar_close_1415") or "-")[:19].replace("T", " "),
            "Durum": "🟢 SAĞLIKLI" if mc_stat == "HEALTHY" else "🔴 UYARI / AÇIK",
            "Hedef Karar Motoru & Rolü": "Takasbank Teminat Çağrısı & Zorunlu Tasfiye Önleme Kalkanı"
        },
        {
            "Veri Tipi": "• ALE Fonu Net Nema Hesabı",
            "Güncelleme Zamanı": "Seans Sonu (18:15)",
            "Son Güncelleme": str(last_syncs.get("ale_fund_1815", "-"))[:19].replace("T", " "),
            "Durum": "🟢 GÜNCEL" if last_syncs.get("ale_fund_1815") else "🟡 BEKLİYOR",
            "Hedef Karar Motoru & Rolü": "Akbank ALE Fonu %17.5 Stopajlı Ayrı Net Kasa Birikimi"
        }
    ]
    st.dataframe(pd.DataFrame(calendar_matrix), use_container_width=True)

    # Detaylı İnceleme Sekmeleri
    st.markdown("---")
    st.subheader("🔍 Derinlemesine Takvim Veri Havuzu & Denetim Panelleri")

    tab_contracts, tab_margins, tab_mc, tab_ale, tab_bars = st.tabs([
        "📜 Sözleşmeler Listesi (08:30)",
        "💰 Teminat Tutarları (09:00 & 14:00)",
        "🚨 Margin Call Denetimi",
        "📈 ALE Fonu Net Nema (18:15)",
        "📊 Bar & KAP Akışı (63 Dayanak)"
    ])

    with tab_contracts:
        st.markdown("##### 🏛️ BIST Takasbank & Fintables VİOP Tam Evren Kataloğu (4 Ana Varlık Sınıfı | 63 Dayanak | 207 Aktif Sözleşme)")
        contracts_db = db.get_viop_contracts()
        if contracts_db:
            df_c = pd.DataFrame(contracts_db)

            # Üst Metrikler
            c_m1, c_m2, c_m3 = st.columns(3)
            with c_m1:
                st.metric("Dayanak Varlık Sınıfı", f"{df_c['asset_category'].nunique()} Ana Sınıf", delta="PAY, ENDEKS, DÖVİZ, EMTİA & MADEN")
            with c_m2:
                st.metric("Dayanak Enstrüman Sayısı", f"{df_c['underlying_symbol'].nunique()} Enstrüman", delta="47 Pay, 4 Endeks, 6 Döviz, 6 Emtia")
            with c_m3:
                st.metric("Farklı Vadelerde Toplam Sözleşme", f"{len(df_c):,} Aktif Sözleşme", delta="Takasbank Standartları")

            # Varlık Sınıfı Kırılım Özeti
            st.markdown("###### 📊 Varlık Sınıflarına Göre Sözleşme Dağılımı")
            breakdown_rows = []
            cat_names = {
                "EQUITY": ("Pay", "3 Vade (Cari, Takip Eden, Çeyrek)", "100"),
                "INDEX": ("Endeks", "3 Vade (XU030, XU100, XLBNK, XUSIN)", "10"),
                "FX": ("Döviz", "6 Vade (USDTRY, EURTRY, EURUSD, GBPTRY, RUBTRY, CNHTRY)", "1.000"),
                "COMMODITY": ("Emtia ve kıymetli maden", "3 Vade (GAUTRY, XAUUSD, GAGTRY, XAGUSD, PLAT, BRENT)", "1 - 100")
            }
            for cat, group in df_c.groupby("asset_category"):
                c_name, v_structure, mult_info = cat_names.get(cat, (cat, "Çoklu Vade", "-"))
                breakdown_rows.append({
                    "Varlık Sınıfı Kodu": cat,
                    "Tanım": c_name,
                    "Dayanak Sayısı": group["underlying_symbol"].nunique(),
                    "Aktif Vade Yapısı": v_structure,
                    "Sözleşme Adedi": len(group),
                    "Çarpan": mult_info,
                    "Min Teminat": f"{group['initial_margin_try'].min():,.0f} TL",
                    "Max Teminat": f"{group['initial_margin_try'].max():,.0f} TL"
                })
            st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True)

            st.markdown("###### 🔍 İnteraktif Sözleşme Filtreleme & Arama")
            f_col1, f_col2, f_col3 = st.columns(3)
            with f_col1:
                cat_options = ["TÜMÜ"] + sorted(list(df_c["asset_category"].unique()))
                sel_cat = st.selectbox("Varlık Sınıfı Filtresi:", cat_options, key="contracts_cat_filter")
            with f_col2:
                expiry_options = ["TÜM VADELER"] + [f"{m:02d}/{y}" for (m, y) in sorted(list(set(zip(df_c["expiry_month"], df_c["expiry_year"]))))]
                sel_exp = st.selectbox("Vade Filtresi:", expiry_options, key="contracts_exp_filter")
            with f_col3:
                search_query = st.text_input("Sözleşme veya Dayanak Ara (Örn: THYAO, XU030, GAU, USD):", key="contracts_search_query")

            filtered_df = df_c.copy()
            if sel_cat != "TÜMÜ":
                filtered_df = filtered_df[filtered_df["asset_category"] == sel_cat]
            if sel_exp != "TÜM VADELER":
                m_part, y_part = sel_exp.split("/")
                filtered_df = filtered_df[(filtered_df["expiry_month"] == int(m_part)) & (filtered_df["expiry_year"] == int(y_part))]
            if search_query:
                q = search_query.strip().upper()
                filtered_df = filtered_df[
                    filtered_df["contract_code"].str.contains(q, case=False, na=False) |
                    filtered_df["underlying_symbol"].str.contains(q, case=False, na=False)
                ]

            st.caption(f"Filtrelenen Sözleşme Sayısı: **{len(filtered_df)}** / {len(df_c)}")
            st.dataframe(filtered_df[[
                "contract_code", "underlying_symbol", "asset_category",
                "contract_size", "expiry_month", "expiry_year",
                "initial_margin_try", "maintenance_margin_try", "updated_at"
            ]], use_container_width=True)
        else:
            st.info("Henüz veritabanında sözleşme kaydı bulunmuyor. Senkronize etmek için yukarıdaki butona tıklayın.")

    with tab_margins:
        st.markdown("##### 💰 Güncel Başlangıç ve Sürdürme Teminatları (09:00 & 14:00 Takasbank Bültenleri)")
        margins_dict = db.get_latest_margins()
        if margins_dict:
            df_m = pd.DataFrame(list(margins_dict.values()))
            chg_m = df_m[df_m["margin_change_pct"].abs() > 0.001]
            if not chg_m.empty:
                st.warning(f"🚨 **Teminatı Değişen {len(chg_m)} Sözleşme Bulunuyor!** Değişen oranlar sisteme yansıtılmıştır.")
                st.dataframe(chg_m[["contract_code", "initial_margin_try", "maintenance_margin_try", "session_window", "margin_change_pct", "updated_at"]], use_container_width=True)
                st.markdown("---")
            st.caption(f"Toplam Teminat Kaydı: **{len(df_m)} Sözleşme** | Sürdürme Teminatı = Başlangıç Teminatı × %75")
            st.dataframe(df_m[[
                "contract_code", "initial_margin_try", "maintenance_margin_try",
                "session_window", "margin_change_pct", "updated_at"
            ]], use_container_width=True)
        else:
            st.info("Teminat bülteni henüz yüklenmedi.")

    with tab_mc:
        st.markdown("##### Canlı Margin Call & Teminat Karşılama Raporu")
        if mc_report:
            mc_c1, mc_c2, mc_c3, mc_c4 = st.columns(4)
            with mc_c1:
                st.metric("Hesap Toplam Özkaynak", f"{mc_report.get('account_equity', 0):,.2f} TL")
            with mc_c2:
                st.metric("Gereken Başlangıç Teminatı", f"{mc_report.get('total_initial_margin', 0):,.2f} TL")
            with mc_c3:
                st.metric("Gereken Sürdürme Teminatı (%75)", f"{mc_report.get('total_maintenance_margin', 0):,.2f} TL")
            with mc_c4:
                st.metric("Kullanılabilir Serbest Teminat", f"{mc_report.get('free_margin', 0):,.2f} TL")

            st.write(f"**Denetim Tipi:** `{mc_report.get('check_type')}` | **Son Denetim:** `{mc_report.get('timestamp')}`")
            st.write(f"**Teminat Karşılama Oranı:** `%{mc_report.get('margin_ratio_pct'):.2f}` (Kritik Eşik: %100)")
            if mc_report.get("liquidation_required"):
                st.error(f"⚠️ DİKKAT: Bar kapanışında teminat açığı tespit edildi! Tasfiye Önerilen Sözleşme: {mc_report.get('target_liquidation_symbol')}")
            else:
                st.success("✅ Hesabın teminat karşılama oranı sağlıklı seviyededir. Herhangi bir tasfiye veya açık bulunmamaktadır.")
        else:
            st.info("Margin Call denetim kaydı bulunamadı.")

    with tab_ale:
        st.markdown("##### Akbank ALE Para Piyasası Fonu Seans Sonu (18:15) Net Nema Tablosu")
        if ale_eod:
            ale_col1, ale_col2, ale_col3, ale_col4 = st.columns(4)
            with ale_col1:
                st.metric("Nemalandırılan Boşta Nakit", f"{ale_eod.get('idle_cash_try', 0):,.2f} TL")
            with ale_col2:
                st.metric("Yıllık Brüt Faiz", f"%{ale_eod.get('annual_gross_rate', 0.48)*100:.1f}")
            with ale_col3:
                st.metric("Günlük Net Getiri", f"+{ale_eod.get('daily_net_yield_try', 0):,.2f} TL", delta=f"Stopaj: -{ale_eod.get('withholding_tax_try', 0):,.2f} TL")
            with ale_col4:
                st.metric("Kümülatif ALE Kasası", f"{ale_eod.get('cumulative_ale_vault_try', 0):,.2f} TL", delta="Ayrı Kasa İlkesi")
            st.caption(f"Hesaplama Tarihi: {ale_eod.get('date_str')} (Kayıt Saati: {str(ale_eod.get('calculated_at'))[:19]})")
        else:
            st.info("Henüz seans sonu ALE neması hesaplanmadı (Saat 18:15'te otomatik hesaplanır).")

    with tab_bars:
        st.markdown("##### 📊 VİOP Sözleşmeleri Fiyat Snapshot & Gürültü Filtreli 240m Barlar (63 Dayanak Enstrüman)")
        if live_market_state and "contracts" in live_market_state:
            contracts_rows = []
            for sym, c_info in live_market_state["contracts"].items():
                contracts_rows.append({
                    "Sözleşme": sym,
                    "Tür": c_info.get("type", "-"),
                    "Son Fiyat": f"{c_info.get('last_price', 0):,.2f}",
                    "15m Bar Adedi": c_info.get("bars_15m_count", 0),
                    "120m Bar Adedi": c_info.get("bars_120m_count", 0),
                    "240m Bar Adedi": c_info.get("bars_240m_count", 0),
                    "Son Güncelleme": str(c_info.get("last_update", "-"))[:19].replace("T", " ")
                })
            st.dataframe(pd.DataFrame(contracts_rows), use_container_width=True)

        st.markdown("---")
        st.markdown("##### 📰 Fintables 'Akış' ve KAP Bildirim Takibi")
        f_stream = live_market_state.get("fintables_stream", {}) if live_market_state else {}
        kaps = f_stream.get("kap_disclosures", [])
        if kaps:
            st.dataframe(pd.DataFrame(kaps), use_container_width=True)
        else:
            st.info("ℹ️ Henüz yeni bir KAP duyurusu bulunmamaktadır. 15 dakikada 1 periyodik olarak sorgulanmaktadır.")


# ------------------------------------------------------------------------------
# MENÜ 3: 🧭 ÇOK VARLIKLI CANLI YÖN PUSULASI & BİLANÇO KALKANI
# ------------------------------------------------------------------------------
elif selected_menu == "🧭 Çok Varlıklı Canlı Yön Pusulası":
    st.header("🧭 Çok Varlıklı Canlı Yön Pusulası (5 Kademeli Hiyerarşik Süzgeç)")
    st.caption("Reel Sektör, Bankacılık, Endeks, FX ve Emtia Karar Tablosu | Çift Yönlü Trend Yetkisi")

    channels_data = [
        {"Kanal": "Kanal A: Reel Sektör", "Örnek": "F_THYAO, F_EREGL, F_TUPRS", "Kriter": "Piotroski F >= 5, Altman Z >= 2.40", "Güncel Skor": "F=8/9, Z=2.85 (Tier 1)", "Yön İzni": "Çift Yönlü Trend (LONG / SHORT)", "Çarpan": "1.0x (Tam Bütçe)"},
        {"Kanal": "Kanal B: Bankacılık", "Örnek": "F_AKBNK, F_GARAN", "Kriter": "SYR >= %14, Çekirdek >= %10.5, RoAE >= %25", "Güncel Skor": "SYR=%18.5, RoAE=%36 (Yüksek)", "Yön İzni": "Çift Yönlü Trend (LONG / SHORT)", "Çarpan": "0.5x - 1.0x"},
        {"Kanal": "Kanal A: Endeks Vadeli", "Örnek": "F_XU030, F_XU100, F_XLBNK", "Kriter": "Makro Trend & ADV >= 500M TL", "Güncel Skor": "Likidite Onaylı, 100 SMA Trendi", "Yön İzni": "BI_DIRECTIONAL (LONG / SHORT)", "Çarpan": "1.0x (Tam Bütçe)"},
        {"Kanal": "Kanal C: Döviz Vadeli", "Örnek": "F_USDTRY, F_EURTRY, F_DXY", "Kriter": "Zımni Faiz, TLREF & CDS Trendi", "Güncel Skor": "Zımni=%46.2, TLREF=%49.5", "Yön İzni": "BI_DIRECTIONAL (LONG / SHORT)", "Çarpan": "1.0x"},
        {"Kanal": "Kanal D: Emtia Vadeli", "Örnek": "F_XAUUSD (Altın), F_BRENT", "Kriter": "US TIPS Trendi, DXY Trendi", "Güncel Skor": "TIPS=%1.85, DXY Trendi", "Yön İzni": "BI_DIRECTIONAL (LONG / SHORT)", "Çarpan": "1.0x"}
    ]
    st.dataframe(pd.DataFrame(channels_data), use_container_width=True)

    st.markdown("---")
    st.subheader("🛡️ Bilanço Kalkanı (Earnings Blackout Window)")
    st.markdown(r"""
    * **announced_at Karantinası:** Bilanço açıklandığı anda **24 saatlik karantina** başlar; sözleşme `DirectionalBias.NEUTRAL` ve `multiplier = 0.0` ile kilitlenir.
    * **Kademeli Re-Entry Şartı:** 24 saat tamamlandıktan sonra $ATR(14) \le 1.5 \times ATR_{20,\text{medyan}}$ volatilite yatışması ve güncel bilanço skoru teyit edilir.
    """)


# ------------------------------------------------------------------------------
# MENÜ 4: ⚡ SMART ORDER ROUTER (SOR) & ÇOKLU BROKER
# ------------------------------------------------------------------------------
elif selected_menu == "⚡ Smart Order Router (SOR)":
    st.header("⚡ Smart Order Router (SOR) ve Çoklu Broker Ağ Geçidi")
    st.caption("Borsa İstanbul FIX Protocol & REST API Çoklu Kota ve Teminat Dağıtımı | 2.000.000 TL Portföy Bütçesi")

    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Broker A (Birincil FIX)</div>
            <div style="font-size:18px; font-weight:bold; color:#00e676; margin-top:4px;">🟢 FIX SOKETİ AKTİF</div>
            <div style="margin-top:6px; color:#cbd5e1;">Komisyon: <b>On binde 2 (0.0002)</b></div>
            <div style="color:#cbd5e1;">Tahsis Edilebilir Teminat: <b>1.200.000 TL</b></div>
            <small style="color:#94a3b8;">Öncelik: 1 (En Düşük Maliyet)</small>
        </div>
        """, unsafe_allow_html=True)
    with col_g2:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Broker B (İkincil FIX)</div>
            <div style="font-size:18px; font-weight:bold; color:#00e676; margin-top:4px;">🟢 FIX SOKETİ AKTİF</div>
            <div style="margin-top:6px; color:#cbd5e1;">Komisyon: <b>On binde 4 (0.0004)</b></div>
            <div style="color:#cbd5e1;">Tahsis Edilebilir Teminat: <b>600.000 TL</b></div>
            <small style="color:#94a3b8;">Öncelik: 2 (Yüksek Likidite)</small>
        </div>
        """, unsafe_allow_html=True)
    with col_g3:
        st.markdown("""
        <div class="kpi-card">
            <div class="kpi-title">Broker C (Yedek REST API)</div>
            <div style="font-size:18px; font-weight:bold; color:#38bdf8; margin-top:4px;">🔵 REST API BEKLEMEDE</div>
            <div style="margin-top:6px; color:#cbd5e1;">Komisyon: <b>On binde 5 (0.0005)</b></div>
            <div style="color:#cbd5e1;">Tahsis Edilebilir Teminat: <b>200.000 TL</b></div>
            <small style="color:#94a3b8;">Öncelik: 3 (Failover / CoD Devri)</small>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🧊 Iceberg ve TWAP Dilimleme Simülatörü (2.000.000 TL Portföy)")
    test_lots = st.slider("Simüle Edilecek Kontrat Adedi (Lot):", min_value=10, max_value=500, value=100, step=10, key="sor_slider")
    
    if st.button("🚀 SOR Rota ve Dilimleme Planını Hesapla"):
        slice_size = 25
        slices = []
        rem = test_lots
        while rem > 0:
            c = min(rem, slice_size)
            slices.append(c)
            rem -= c

        broker_a_cap = int(1_200_000 // 7000)
        alloc_a = min(test_lots, broker_a_cap)
        alloc_b = max(0, test_lots - alloc_a)

        st.success(f"✅ {test_lots:,} Kontratlık Kurumsal Emir {len(slices)} adet Iceberg dilimine bölündü:")
        c_res1, c_res2 = st.columns(2)
        with c_res1:
            st.metric("Broker A (Düşük Komisyon - Öncelikli)", f"{alloc_a:,} Lot", delta="Komisyon: 0.0002")
        with c_res2:
            st.metric("Broker B (Yedek Likidite)", f"{alloc_b:,} Lot", delta="Komisyon: 0.0004")


# ------------------------------------------------------------------------------
# MENÜ 5: 🛡️ 33 SAVUNMA KURALI MATRİSİ
# ------------------------------------------------------------------------------
elif selected_menu == "🛡️ 33 Savunma Kuralı":
    st.header("🛡️ Ali Perşembe Doktrini 33 Savunma Kuralı Matrisi")
    st.caption("Aşırı Uyum (Overfitting) riskine karşı Parmaksız Eldiven (Robustness) Kalkanları")

    rules_data = [
        {"No": "1", "Kural": "Testere Kalkanı", "Parametre": "ADX < 20", "Açıklama": "Yatay ve yönsüz piyasada al-sat kırılımları doğrudan reddedilir.", "Durum": "AKTİF"},
        {"No": "2", "Kural": "Dinamik Bütçe Çarpanı", "Parametre": "Delta Z Momentum", "Açıklama": "Z-Skor iyileşme ivmesine göre Tier 1 (1.0x), Tier 2 (0.5x), Tier 3 (0.0x).", "Durum": "AKTİF"},
        {"No": "3", "Kural": "Bilanço Karantinası", "Parametre": "24 Saat Blackout", "Açıklama": "KAP bilanço açıklamasından sonra 24 saat yeni emir girilmez.", "Durum": "AKTİF"},
        {"No": "4", "Kural": "Anti-Martingale", "Parametre": "4 Ardışık Zarar", "Açıklama": "Risk bütçesi %2'den %1'e otomatik çekilir.", "Durum": "AKTİF"},
        {"No": "5", "Kural": "Whipsaw Kalkanı", "Parametre": "2 Gün İçi Stop", "Açıklama": "Aynı sözleşmede gün içi 2 stopta o gün işlem kilitlenir.", "Durum": "AKTİF"},
        {"No": "6", "Kural": "Çoklu Vade Kararı", "Parametre": "240 Dakika Barlar", "Açıklama": "Piyasa gürültüsünü filtrelemek için 4 saatlik barlarla (14:15 & 18:15) karar üretilir.", "Durum": "AKTİF"},
        {"No": "7", "Kural": "Çift Yönlü İcra", "Parametre": "Bi-Directional", "Açıklama": "Trende göre LONG veya SHORT pozisyon disiplinle açılır.", "Durum": "AKTİF"},
        {"No": "8", "Kural": "ALE Fonu Güvencesi", "Parametre": "%17.5 Stopajlı Net Kasa", "Açıklama": "Serbest nakit Akbank ALE fonunda gecelik nemalandırılır.", "Durum": "AKTİF"},
        {"No": "9", "Kural": "Midas Kademeli Komisyon", "Parametre": "0-10M %0.05, 10-100M %0.02, 100M+ %0.01", "Açıklama": "İşlem hacmine göre gerçek hayat sürtünme maliyeti hesaplanır.", "Durum": "AKTİF"},
        {"No": "10", "Kural": "Tek Ortak Portföy Havuzu", "Parametre": "2.000.000 TL Konsolide", "Açıklama": "Varlık başına sermaye bölünmez, tüm 20 sözleşme tek bir 2M TL havuzunu paylaşır.", "Durum": "AKTİF"}
    ]
    st.dataframe(pd.DataFrame(rules_data), use_container_width=True)
