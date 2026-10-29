"""
Módulo de análisis de consumo de agua y detección de excesos / fugas.
"""

from dataclasses import dataclass
from statistics import mean, median
from typing import List
from .client import MeterReading


@dataclass
class ConsumptionAlert:
    date: str
    daily_liters: float
    daily_m3: float
    reasons: List[str]


@dataclass
class AnalysisReport:
    latest: MeterReading
    history: List[MeterReading]
    mean_liters: float
    median_liters: float
    threshold_liters: float
    multiplier_mean: float
    is_latest_excessive: bool
    latest_alerts: List[str]
    historical_alerts: List[ConsumptionAlert]


def analyze_consumptions(
    readings: List[MeterReading],
    threshold_liters: float = 1000.0,
    multiplier_mean: float = 2.0,
) -> AnalysisReport:
    """
    Analiza la serie de consumos diarios y comprueba si el último día (o días previos)
    supera el umbral fijo por defecto (`threshold_liters`) y/o el multiplicador sobre
    la media histórica (`multiplier_mean`).
    """
    if not readings:
        raise ValueError("No hay lecturas disponibles para analizar.")

    latest = readings[-1]
    all_liters = [r.daily_liters for r in readings]

    # Calculamos tanto la media aritmética como la mediana (habitual sin picos extremos)
    avg_liters = round(mean(all_liters), 1)
    med_liters = round(median(all_liters), 1)

    # Para la comparación con la media histórica sin incluir el propio día evaluado si hay histórico suficiente
    prev_liters = [r.daily_liters for r in readings[:-1]] if len(readings) > 1 else all_liters
    baseline_mean = round(mean(prev_liters), 1)

    historical_alerts: List[ConsumptionAlert] = []
    for r in readings:
        reasons = []
        if r.daily_liters > threshold_liters:
            reasons.append(
                f"Supera el umbral máximo fijo ({r.daily_liters:.1f} L > {threshold_liters:.1f} L)"
            )
        if baseline_mean > 0 and r.daily_liters > (baseline_mean * multiplier_mean):
            reasons.append(
                f"Supera {multiplier_mean}x la media histórica ({r.daily_liters:.1f} L > {baseline_mean * multiplier_mean:.1f} L)"
            )
        if med_liters > 0 and r.daily_liters > (med_liters * multiplier_mean) and r.daily_liters <= (baseline_mean * multiplier_mean):
            reasons.append(
                f"Supera {multiplier_mean}x el consumo mediano habitual ({r.daily_liters:.1f} L > {med_liters * multiplier_mean:.1f} L)"
            )

        if reasons:
            historical_alerts.append(
                ConsumptionAlert(
                    date=r.date,
                    daily_liters=r.daily_liters,
                    daily_m3=r.daily_m3,
                    reasons=reasons,
                )
            )

    latest_alerts = []
    if historical_alerts and historical_alerts[-1].date == latest.date:
        latest_alerts = historical_alerts[-1].reasons

    return AnalysisReport(
        latest=latest,
        history=readings,
        mean_liters=avg_liters,
        median_liters=med_liters,
        threshold_liters=threshold_liters,
        multiplier_mean=multiplier_mean,
        is_latest_excessive=len(latest_alerts) > 0,
        latest_alerts=latest_alerts,
        historical_alerts=historical_alerts,
    )
