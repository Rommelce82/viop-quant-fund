"""
Makine Öğrenmesi (ML) - Walk-Forward Optimizasyon Altyapısı.

Bu modül;
- Zaman serisi verilerini ileriye dönük kayan pencerelere (Rolling Walk-Forward Windows) böler,
- Overfitting (Aşırı Uyum) ve Lookahead Bias riskini önlemek için Purged Cross-Validation uygular:
  Train (Eğitim) ve Test (Doğrulama) pencereleri arasına 'purge_bars' kadar boşluk ekler.
- ML hiperparametre taramaları (Grid/Bayesian) için eğitim ve test veri dilimlerini deterministik sunar.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple
import pandas as pd


@dataclass(frozen=True)
class WalkForwardFold:
    """Tekil Walk-Forward Dilimi (Fold)."""
    fold_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_data: pd.DataFrame
    test_data: pd.DataFrame


class WalkForwardOptimizer:
    """
    Zaman Serisi Purged Walk-Forward Optimizatörü.
    """

    def __init__(
        self,
        train_window_bars: int = 480,   # ~60 işlem günü (Günde 8 saatlik bar)
        test_window_bars: int = 160,    # ~20 işlem günü (1 ay test)
        purge_window_bars: int = 2,     # Veri sızıntısını önleyen 2 barlık tampon (Purge)
        step_size_bars: Optional[int] = None
    ) -> None:
        """
        Args:
            train_window_bars: Eğitim penceresi uzunluğu (bar adedi).
            test_window_bars: Doğrulama penceresi uzunluğu (bar adedi).
            purge_window_bars: Train ile Test arasındaki karantina boşluğu.
            step_size_bars: Her adımda ileriye kayma miktarı (Varsayılan: test_window_bars).
        """
        self.train_window = train_window_bars
        self.test_window = test_window_bars
        self.purge_window = purge_window_bars
        self.step_size = step_size_bars or test_window_bars

    def split(
        self,
        df: pd.DataFrame,
        time_column: str = "timestamp"
    ) -> Generator[WalkForwardFold, None, None]:
        """
        Veri setini Purged Walk-Forward katmanlarına böler.
        """
        df_sorted = df.sort_values(time_column).reset_index(drop=True)
        total_rows = len(df_sorted)
        fold_idx = 1
        current_train_start = 0

        while True:
            current_train_end = current_train_start + self.train_window
            current_test_start = current_train_end + self.purge_window
            current_test_end = current_test_start + self.test_window

            if current_test_end > total_rows:
                # Kalan veri test penceresinden küçükse sonlandır
                break

            train_df = df_sorted.iloc[current_train_start:current_train_end].copy()
            test_df = df_sorted.iloc[current_test_start:current_test_end].copy()

            fold = WalkForwardFold(
                fold_index=fold_idx,
                train_start=train_df[time_column].iloc[0],
                train_end=train_df[time_column].iloc[-1],
                test_start=test_df[time_column].iloc[0],
                test_end=test_df[time_column].iloc[-1],
                train_data=train_df,
                test_data=test_df
            )
            yield fold

            fold_idx += 1
            current_train_start += self.step_size

    # Ali Perşembe Doktrini - Parmaksız Eldiven Sert Sınırları (Guardrails)
    GUARDRAILS = {
        "atr_multiplier": (1.5, 3.5),
        "adx_threshold": (15.0, 30.0),
        "time_stop_bars": (5, 20)
    }

    @classmethod
    def apply_guardrails(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parametreleri Ali Perşembe sert sınırları içinde kırpar veya doğrular.
        """
        clipped = dict(params)
        for key, (low, high) in cls.GUARDRAILS.items():
            if key in clipped:
                val = clipped[key]
                if isinstance(low, int) and isinstance(high, int):
                    clipped[key] = int(max(low, min(high, round(val))))
                else:
                    clipped[key] = float(max(low, min(high, val)))
        return clipped

    def evaluate_parameter_grid(
        self,
        df: pd.DataFrame,
        param_grid: List[Dict[str, Any]],
        evaluation_fn: Any
    ) -> List[Dict[str, Any]]:
        """
        Belirtilen parametre kombinasyonlarını tüm Walk-Forward katmanlarında dener.
        """
        results: List[Dict[str, Any]] = []

        # Guardrails uygula
        sanitized_grid = [self.apply_guardrails(p) for p in param_grid]

        for fold in self.split(df):
            for params in sanitized_grid:
                train_score = evaluation_fn(fold.train_data, **params)
                test_score = evaluation_fn(fold.test_data, **params)

                results.append({
                    "fold": fold.fold_index,
                    "train_period": f"{fold.train_start.strftime('%Y-%m-%d')} - {fold.train_end.strftime('%Y-%m-%d')}",
                    "test_period": f"{fold.test_start.strftime('%Y-%m-%d')} - {fold.test_end.strftime('%Y-%m-%d')}",
                    "params": params,
                    "train_score": train_score,
                    "test_score": test_score,
                    "overfitting_ratio": (train_score / test_score) if test_score != 0 else 0.0
                })

        return results

    def find_sweet_spot_plateau(
        self,
        grid_results: List[Dict[str, Any]],
        metric_key: str = "test_score",
        neighbor_tolerance: float = 0.25
    ) -> Dict[str, Any]:
        """
        Ali Perşembe Doktrini - Plato Seçimi (Plateau Selection) Algoritması:
        
        Optimizasyon sonucunda en yüksek PnL'i veren 'Sivri Tepe (Peak)' tekil parametreyi SEÇMEZ.
        Bunun yerine, komşu parametrelerin (Örn: ATR 2.4, 2.5, 2.6) ortalama ve medyan
        performansını hesaplayarak varyansı en düşük, en istikrarlı 'Geniş Plato'yu (Sweet Spot) seçer.
        
        Returns:
            {
                "best_plateau_params": Dict[str, Any],
                "plateau_mean_score": float,
                "plateau_std": float,
                "peak_score": float,
                "robustness_score": float,
                "plateau_candidates_count": int
            }
        """
        if not grid_results:
            return {
                "best_plateau_params": {"atr_multiplier": 2.5, "adx_threshold": 20.0, "time_stop_bars": 12},
                "plateau_mean_score": 0.0,
                "plateau_std": 0.0,
                "peak_score": 0.0,
                "robustness_score": 0.0,
                "plateau_candidates_count": 0
            }

        # Parametre setlerine göre sonuçları grupla (Folds ortalaması)
        param_aggregates: Dict[str, Dict[str, Any]] = {}
        for res in grid_results:
            p = res["params"]
            p_key = f"atr:{p.get('atr_multiplier')}_adx:{p.get('adx_threshold')}_time:{p.get('time_stop_bars')}"
            if p_key not in param_aggregates:
                param_aggregates[p_key] = {
                    "params": p,
                    "scores": []
                }
            param_aggregates[p_key]["scores"].append(res.get(metric_key, 0.0))

        summary_list = []
        for k, v in param_aggregates.items():
            scores = v["scores"]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            summary_list.append({
                "key": k,
                "params": v["params"],
                "avg_score": avg_score
            })

        # Tekil Tepe Skoru (Peak)
        summary_list.sort(key=lambda x: x["avg_score"], reverse=True)
        peak_score = summary_list[0]["avg_score"] if summary_list else 0.0

        best_plateau = None
        best_plateau_metric = -float("inf")

        for candidate in summary_list:
            c_p = candidate["params"]
            c_atr = float(c_p.get("atr_multiplier", 2.5))
            c_adx = float(c_p.get("adx_threshold", 20.0))
            c_time = int(c_p.get("time_stop_bars", 12))

            # Komşu parametreleri topla (Civardaki parametreler)
            neighbors = []
            for other in summary_list:
                o_p = other["params"]
                o_atr = float(o_p.get("atr_multiplier", 2.5))
                o_adx = float(o_p.get("adx_threshold", 20.0))
                o_time = int(o_p.get("time_stop_bars", 12))

                # Komşuluk kriteri (ATR +-0.5, ADX +-5, Time +-3)
                if (abs(o_atr - c_atr) <= 0.55 and
                    abs(o_adx - c_adx) <= 5.5 and
                    abs(o_time - c_time) <= 4):
                    neighbors.append(other["avg_score"])

            if not neighbors:
                continue

            plateau_mean = sum(neighbors) / len(neighbors)
            # Standart sapma (Stabilite göstergesi)
            variance = sum((x - plateau_mean) ** 2 for x in neighbors) / len(neighbors)
            plateau_std = variance ** 0.5

            # Plato Skoru = Ortalama - (0.5 * Ceza_Std) (Ali Perşembe İstikrar Ağırlığı)
            plateau_fitness = plateau_mean - (0.5 * plateau_std)

            if plateau_fitness > best_plateau_metric:
                best_plateau_metric = plateau_fitness
                best_plateau = {
                    "best_plateau_params": candidate["params"],
                    "plateau_mean_score": round(plateau_mean, 2),
                    "plateau_std": round(plateau_std, 2),
                    "peak_score": round(peak_score, 2),
                    "robustness_score": round(plateau_fitness, 2),
                    "plateau_candidates_count": len(neighbors)
                }

        return best_plateau or {
            "best_plateau_params": summary_list[0]["params"],
            "plateau_mean_score": summary_list[0]["avg_score"],
            "plateau_std": 0.0,
            "peak_score": peak_score,
            "robustness_score": peak_score,
            "plateau_candidates_count": 1
        }

