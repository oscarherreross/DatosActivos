"""
DatosActivos - definición de las estrategias que prueba backtesting.py.

Cada estrategia es una función que recibe las velas de un activo en una
temporalidad (un DataFrame ordenado por fecha, con los indicadores de la
tabla `velas`) y sus parámetros, y devuelve cuatro señales, una por vela:

    entrada_larga, salida_larga, entrada_corta, salida_corta

Cada señal se evalúa con los datos de la vela YA CERRADA; el motor ejecuta
la orden en la apertura de la vela siguiente. Una señal nunca debe mirar
velas posteriores (nada de shift(-1)).

Para añadir una estrategia:
  1. Escribe su función aquí y regístrala en FUNCIONES.
  2. Añádela a ESTRATEGIAS con un nombre único y sus parámetros.
  3. Ejecuta ejecutar_backtests.bat.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _cruza_arriba(a: pd.Series, b: pd.Series) -> np.ndarray:
    """a pasa de estar por debajo (o igual) de b a estar por encima en esta vela."""
    return ((a > b) & (a.shift(1) <= b.shift(1))).to_numpy()


def _cruza_abajo(a: pd.Series, b: pd.Series) -> np.ndarray:
    return ((a < b) & (a.shift(1) >= b.shift(1))).to_numpy()


def cruce_medias(v: pd.DataFrame, p: dict) -> dict:
    """Largo cuando la media rápida cruza al alza la lenta; corto al cruzar a la baja."""
    rapida, lenta = v[p["media_rapida"]], v[p["media_lenta"]]
    alcista, bajista = _cruza_arriba(rapida, lenta), _cruza_abajo(rapida, lenta)
    return {"entrada_larga": alcista, "salida_larga": bajista,
            "entrada_corta": bajista, "salida_corta": alcista}


def rsi_extremos(v: pd.DataFrame, p: dict) -> dict:
    """Largo cuando el RSI sale de sobreventa (cruza al alza el nivel bajo) y se cierra
    al llegar a sobrecompra. Corto cuando sale de sobrecompra y se cierra al llegar a
    sobreventa."""
    rsi = v["rsi_14"]
    bajo = pd.Series(float(p["sobreventa"]), index=v.index)
    alto = pd.Series(float(p["sobrecompra"]), index=v.index)
    return {"entrada_larga": _cruza_arriba(rsi, bajo),
            "salida_larga": (rsi >= alto).to_numpy(),
            "entrada_corta": _cruza_abajo(rsi, alto),
            "salida_corta": (rsi <= bajo).to_numpy()}


def cruce_macd(v: pd.DataFrame, p: dict) -> dict:
    """Largo cuando el MACD cruza al alza su señal; corto al cruzar a la baja."""
    alcista = _cruza_arriba(v["macd"], v["macd_senal"])
    bajista = _cruza_abajo(v["macd"], v["macd_senal"])
    return {"entrada_larga": alcista, "salida_larga": bajista,
            "entrada_corta": bajista, "salida_corta": alcista}


def rebote_bollinger(v: pd.DataFrame, p: dict) -> dict:
    """Largo cuando el cierre vuelve a entrar por encima de la banda inferior; se cierra
    al llegar a la banda media (SMA 20). Corto cuando vuelve a entrar por debajo de la
    banda superior; se cierra al llegar a la media."""
    cierre, media = v["cierre"], v["sma_20"]
    return {"entrada_larga": _cruza_arriba(cierre, v["bb_inferior"]),
            "salida_larga": (cierre >= media).to_numpy(),
            "entrada_corta": _cruza_abajo(cierre, v["bb_superior"]),
            "salida_corta": (cierre <= media).to_numpy()}


FUNCIONES = {
    "cruce_medias": cruce_medias,
    "rsi_extremos": rsi_extremos,
    "cruce_macd": cruce_macd,
    "rebote_bollinger": rebote_bollinger,
}

# Estrategias que se guardan en la tabla `estrategias` y se prueban.
# PENDIENTE: todavía no se ha decidido con cuáles empezar, así que la lista está vacía.
# Para activar una, añade aquí su definición. Ejemplos con las ideas propuestas
# (cruce de EMA 20/50, RSI 30/70, cruce del MACD y rebote en Bollinger):
#
#     {"nombre": "cruce_ema_20_50", "codigo": "cruce_medias",
#      "descripcion": "Largo cuando la EMA 20 cruza al alza la EMA 50; corto cuando la cruza a la baja. "
#                     "Siempre está dentro del mercado tras el primer cruce.",
#      "parametros": {"media_rapida": "ema_20", "media_lenta": "ema_50"}},
#     {"nombre": "rsi_30_70", "codigo": "rsi_extremos",
#      "descripcion": "Largo cuando el RSI 14 sube de 30 y se cierra al llegar a 70; "
#                     "corto cuando baja de 70 y se cierra al llegar a 30.",
#      "parametros": {"sobreventa": 30, "sobrecompra": 70}},
#     {"nombre": "cruce_macd_senal", "codigo": "cruce_macd",
#      "descripcion": "Largo cuando el MACD 12/26 cruza al alza su señal (9); corto cuando la cruza a la baja.",
#      "parametros": {}},
#     {"nombre": "rebote_bollinger_20_2", "codigo": "rebote_bollinger",
#      "descripcion": "Largo cuando el cierre vuelve a entrar por encima de la banda inferior de Bollinger 20/2 "
#                     "y se cierra en la media; corto cuando vuelve a entrar por debajo de la superior "
#                     "y se cierra en la media.",
#      "parametros": {}},
ESTRATEGIAS: list[dict] = []
