import json
import os

res_file = "src/database/comparative_timeframe_results.json"
if not os.path.exists(res_file):
    print("Results file not found")
    exit(1)

with open(res_file, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"TOPLAM ANALİZ EDİLEN VARLIK SAYISI: {len(data['assets'])}")
print("=" * 140)
print(f"{'VARLIK':<10} | {'VADE':<6} | {'IN TRADE PNL':<13} | {'IN ALE NET':<13} | {'IN NAV':<13} | {'TR':<4} | {'KÖR TRADE PNL':<14} | {'KÖR ALE NET':<13} | {'KÖR NAV':<13} | {'TR':<4} | {'KOMİSYON (TL)':<13}")
print("=" * 140)

modes = [
    ("60m (Eski)", "baseline_60m"),
    ("120m", "timeframe_120m"),
    ("240m", "timeframe_240m")
]

totals = {
    "60m (Eski)": {"in_pnl": 0.0, "in_ale": 0.0, "in_nav": 0.0, "in_tr": 0, "out_pnl": 0.0, "out_ale": 0.0, "out_nav": 0.0, "out_tr": 0, "comm": 0.0},
    "120m": {"in_pnl": 0.0, "in_ale": 0.0, "in_nav": 0.0, "in_tr": 0, "out_pnl": 0.0, "out_ale": 0.0, "out_nav": 0.0, "out_tr": 0, "comm": 0.0},
    "240m": {"in_pnl": 0.0, "in_ale": 0.0, "in_nav": 0.0, "in_tr": 0, "out_pnl": 0.0, "out_ale": 0.0, "out_nav": 0.0, "out_tr": 0, "comm": 0.0},
}

for sym, d in data["assets"].items():
    in_dict = d.get("in_sample", {})
    out_dict = d.get("out_of_sample", {})

    for mode_label, mode_key in modes:
        in_s = in_dict.get(mode_key, {})
        out_s = out_dict.get(mode_key, {})

        # 60m baseline might use different key names
        in_pnl = in_s.get("trade_net_pnl", in_s.get("total_net_pnl", 0.0))
        in_ale = in_s.get("ale_net_income", in_s.get("ale_income_try", 0.0))
        in_nav = in_s.get("consolidated_nav", in_s.get("consolidated_nav_try", 0.0))
        in_tr = in_s.get("total_trades", 0)

        out_pnl = out_s.get("trade_net_pnl", out_s.get("total_net_pnl", 0.0))
        out_ale = out_s.get("ale_net_income", out_s.get("ale_income_try", 0.0))
        out_nav = out_s.get("consolidated_nav", out_s.get("consolidated_nav_try", 0.0))
        out_tr = out_s.get("total_trades", 0)

        comm = in_s.get("total_commissions", in_s.get("total_commissions_paid", 0.0)) + \
               out_s.get("total_commissions", out_s.get("total_commissions_paid", 0.0))

        totals[mode_label]["in_pnl"] += in_pnl
        totals[mode_label]["in_ale"] += in_ale
        totals[mode_label]["in_nav"] += in_nav
        totals[mode_label]["in_tr"] += in_tr
        totals[mode_label]["out_pnl"] += out_pnl
        totals[mode_label]["out_ale"] += out_ale
        totals[mode_label]["out_nav"] += out_nav
        totals[mode_label]["out_tr"] += out_tr
        totals[mode_label]["comm"] += comm

        print(f"{sym:<10} | {mode_label:<10} | {in_pnl:>+10,.0f} TL | {in_ale:>10,.0f} TL | {in_nav:>10,.0f} TL | {in_tr:>4} | {out_pnl:>+11,.0f} TL | {out_ale:>10,.0f} TL | {out_nav:>10,.0f} TL | {out_tr:>4} | {comm:>11,.0f} TL")
    print("-" * 140)

print("\n" + "=" * 140)
print("PORTFÖY GENEL TOPLAMLARI (20 SÖZLEŞME KONSOLİDE):")
print("=" * 140)
for m, _ in modes:
    t = totals[m]
    print(f"[{m:<10}] In-Sample Trade: {t['in_pnl']:>+12,.0f} TL | ALE Net: {t['in_ale']:>11,.0f} TL | Toplam NAV: {t['in_nav']:>12,.0f} TL | İşlem: {t['in_tr']:>5}")
    print(f"             Kör Test Trade  : {t['out_pnl']:>+12,.0f} TL | ALE Net: {t['out_ale']:>11,.0f} TL | Toplam NAV: {t['out_nav']:>12,.0f} TL | İşlem: {t['out_tr']:>5}")
    print(f"             Toplam Komisyon : {t['comm']:>12,.0f} TL")
    print("-" * 140)
