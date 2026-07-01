"""ML sinyal modeli: eğitim, tahmin ve kural-tabanlı güvenle harmanlama.

Kural motoru (engine/signals/engine.py) tek başına çalışmaya devam eder. ML
katmanı OPSİYONELdir: eğitilmiş bir model varsa, yükseliş olasılığını üretir ve
kuralın güvenini hafifçe modüle eder (aşırı-uyumu önlemek için sınırlı etki).
"""
from __future__ import annotations

from engine.ml.features import FEATURE_NAMES, feature_vector, make_dataset
from engine.ml.logistic import LogisticRegression
from engine.models import TechnicalSnapshot


class MLSignal:
    """Eğitilmiş modeli sarar; TechnicalSnapshot -> yükseliş olasılığı."""

    def __init__(self, model: LogisticRegression):
        self.model = model

    def predict_up(self, tech: TechnicalSnapshot) -> float:
        """horizon-bar sonra fiyatın yükselme olasılığı [0,1]."""
        return self.model.predict_proba(feature_vector(tech))

    def feature_importance(self) -> list[tuple[str, float]]:
        pairs = list(zip(FEATURE_NAMES, self.model.w))
        return sorted(pairs, key=lambda kv: abs(kv[1]), reverse=True)

    def save(self, path: str) -> None:
        self.model.save(path)

    @classmethod
    def load(cls, path: str) -> "MLSignal":
        return cls(LogisticRegression.load(path))


def train_from_candles(candles: list[dict], horizon: int = 4,
                       warmup: int = 40, epochs: int = 400) -> MLSignal:
    """Geçmiş mumlardan model eğit."""
    X, y = make_dataset(candles, horizon=horizon, warmup=warmup)
    if len(X) < 20 or len(set(y)) < 2:
        raise ValueError("Eğitim için yetersiz/tek-sınıflı veri")
    model = LogisticRegression(epochs=epochs).fit(X, y)
    return MLSignal(model)


def walk_forward_models(candles: list[dict], folds: int = 4, horizon: int = 4,
                        warmup: int = 40) -> list[dict]:
    """Walk-forward: her parçada önceki veriyle eğit, sonraki parçada doğrula.

    Aşırı-uyumu ölçer. Her fold için doğruluk (accuracy) döner.
    """
    n = len(candles)
    if n < warmup + folds * 20:
        raise ValueError("Walk-forward için yetersiz mum")
    seg = n // (folds + 1)
    results = []
    for k in range(1, folds + 1):
        train = candles[: seg * k]
        test = candles[seg * k: seg * (k + 1)]
        if len(test) < horizon + 5:
            continue
        try:
            ml = train_from_candles(train, horizon=horizon, warmup=warmup)
        except ValueError:
            continue
        Xte, yte = make_dataset(test, horizon=horizon, warmup=min(warmup, len(test) // 3))
        if not Xte:
            continue
        correct = sum(1 for x, yy in zip(Xte, yte)
                      if (ml.model.predict_proba(x) >= 0.5) == bool(yy))
        results.append({"fold": k, "n_test": len(Xte),
                        "accuracy": round(correct / len(Xte), 4)})
    return results


def blend_confidence(rule_conf: float, ml_prob: float, action: str,
                     weight: float = 0.25) -> float:
    """Kural güvenini ML olasılığıyla harmanla (sınırlı etki).

    action BUY ise ml_prob (yükseliş) güveni destekler; SELL ise (1-ml_prob).
    weight=0.25 -> ML en fazla %25 ağırlık. HOLD'a dokunmaz.
    """
    if action not in ("BUY", "SELL"):
        return rule_conf
    ml_support = ml_prob if action == "BUY" else (1.0 - ml_prob)
    blended = (1.0 - weight) * rule_conf + weight * ml_support
    return max(0.0, min(1.0, blended))
