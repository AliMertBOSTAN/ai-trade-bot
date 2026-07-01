"""Saf-Python lojistik regresyon (numpy YOK) — sinyal ağırlıklarını ÖĞRENİR.

El-ayarlı sabit ağırlıklar yerine, geçmiş özellik→sonuç verisinden hangi
göstergelerin yükseliş/düşüşü öngördüğünü öğrenir. Gradyan iniş + L2 + standardize.
Küçük özellik boyutları için yeterli; bağımlılık eklemez.
"""
from __future__ import annotations

import json
import math


def _sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


class LogisticRegression:
    def __init__(self, lr: float = 0.2, epochs: int = 400, l2: float = 1e-3):
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.w: list[float] = []
        self.b = 0.0
        self.mu: list[float] = []
        self.sd: list[float] = []

    def _fit_scaler(self, X: list[list[float]]) -> None:
        n = len(X)
        d = len(X[0])
        self.mu = [sum(r[j] for r in X) / n for j in range(d)]
        self.sd = [
            (sum((r[j] - self.mu[j]) ** 2 for r in X) / n) ** 0.5 or 1.0
            for j in range(d)
        ]

    def _z(self, x: list[float]) -> list[float]:
        return [(x[j] - self.mu[j]) / self.sd[j] for j in range(len(x))]

    def fit(self, X: list[list[float]], y: list[int]) -> "LogisticRegression":
        if not X:
            raise ValueError("boş eğitim verisi")
        self._fit_scaler(X)
        Xs = [self._z(r) for r in X]
        d = len(Xs[0])
        n = len(Xs)
        self.w = [0.0] * d
        self.b = 0.0
        for _ in range(self.epochs):
            dw = [0.0] * d
            db = 0.0
            for xi, yi in zip(Xs, y):
                p = _sigmoid(self.b + sum(self.w[j] * xi[j] for j in range(d)))
                e = p - yi
                for j in range(d):
                    dw[j] += e * xi[j]
                db += e
            for j in range(d):
                self.w[j] -= self.lr * (dw[j] / n + self.l2 * self.w[j])
            self.b -= self.lr * (db / n)
        return self

    def predict_proba(self, x: list[float]) -> float:
        if not self.w:
            return 0.5
        xi = self._z(x)
        return _sigmoid(self.b + sum(self.w[j] * xi[j] for j in range(len(xi))))

    def to_dict(self) -> dict:
        return {"w": self.w, "b": self.b, "mu": self.mu, "sd": self.sd,
                "lr": self.lr, "epochs": self.epochs, "l2": self.l2}

    @classmethod
    def from_dict(cls, d: dict) -> "LogisticRegression":
        m = cls(lr=d.get("lr", 0.2), epochs=d.get("epochs", 400), l2=d.get("l2", 1e-3))
        m.w = list(d["w"])
        m.b = float(d["b"])
        m.mu = list(d["mu"])
        m.sd = list(d["sd"])
        return m

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "LogisticRegression":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
