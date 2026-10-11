"""
Cálculo de indicadores técnicos para DatosActivos.

Todas las fórmulas siguen las de TradingView:
  * EMA y RMA (Wilder) se inicializan con la media simple de las
    primeras `longitud` velas, y a partir de ahí son recursivas.
  * La desviación típica de Bollinger es la poblacional (ddof=0).
  * El True Range de la primera vela es máximo - mínimo.

Cada indicador vale NaN (NULL en la base de datos) mientras no haya
velas suficientes para calcularlo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Columnas de indicadores, en el mismo orden que en esquema.sql
COLUMNAS_INDICADORES = [
    "sma_20", "sma_50", "sma_200",
    "ema_20", "ema_50", "ema_200",
    "rsi_14",
    "macd", "macd_senal", "macd_histograma",
    "bb_superior", "bb_inferior",
    "atr_14",
    "estoc_k", "estoc_d",
    "vol_media_20",
    "vwap",
    "adx_14", "di_mas_14", "di_menos_14",
]

# Temporalidades en las que se calcula el VWAP diario
TEMPORALIDADES_CON_VWAP = {"5m", "15m", "1h", "4h"}


# ---------------------------------------------------------------------
#  Medias
# ---------------------------------------------------------------------
def sma(serie: pd.Series, longitud: int) -> pd.Series:
    """Media móvil simple."""
    return serie.rolling(longitud, min_periods=longitud).mean()


def _media_exponencial(serie: pd.Series, longitud: int, alpha: float) -> pd.Series:
    """
    Media exponencial recursiva inicializada con una SMA:
        m[semilla] = media de las primeras `longitud` velas válidas
        m[t]       = alpha * x[t] + (1 - alpha) * m[t-1]
    Admite NaN iniciales (p. ej. al aplicarla sobre el MACD).
    """
    valores = serie.to_numpy(dtype=float)
    salida = np.full(len(valores), np.nan)
    validos = np.flatnonzero(~np.isnan(valores))
    if len(validos) < longitud:
        return pd.Series(salida, index=serie.index)

    i0 = validos[0]
    semilla = i0 + longitud - 1
    x = valores.copy()
    x[:semilla] = np.nan
    x[semilla] = valores[i0:semilla + 1].mean()

    resultado = pd.Series(x, index=serie.index).ewm(alpha=alpha, adjust=False).mean()
    resultado.iloc[:semilla] = np.nan
    return resultado


def ema(serie: pd.Series, longitud: int) -> pd.Series:
    """Media móvil exponencial (alpha = 2 / (n + 1))."""
    return _media_exponencial(serie, longitud, 2.0 / (longitud + 1))


def rma(serie: pd.Series, longitud: int) -> pd.Series:
    """Media de Wilder (alpha = 1 / n), usada en RSI y ATR."""
    return _media_exponencial(serie, longitud, 1.0 / longitud)


# ---------------------------------------------------------------------
#  Osciladores y volatilidad
# ---------------------------------------------------------------------
def rsi(cierre: pd.Series, longitud: int = 14) -> pd.Series:
    cambio = cierre.diff()
    subidas = rma(cambio.clip(lower=0), longitud)
    bajadas = rma((-cambio).clip(lower=0), longitud)
    with np.errstate(divide="ignore", invalid="ignore"):
        valor = 100 - 100 / (1 + subidas / bajadas)
    valor = np.where(bajadas == 0, 100.0, np.where(subidas == 0, 0.0, valor))
    valor = pd.Series(valor, index=cierre.index)
    valor[subidas.isna() | bajadas.isna()] = np.nan
    return valor


def macd(cierre: pd.Series, rapida: int = 12, lenta: int = 26, senal: int = 9):
    linea = ema(cierre, rapida) - ema(cierre, lenta)
    linea_senal = ema(linea, senal)
    return linea, linea_senal, linea - linea_senal


def bollinger(cierre: pd.Series, longitud: int = 20, desviaciones: float = 2.0):
    media = sma(cierre, longitud)
    desv = cierre.rolling(longitud, min_periods=longitud).std(ddof=0)
    return media + desviaciones * desv, media - desviaciones * desv


def atr(maximo: pd.Series, minimo: pd.Series, cierre: pd.Series, longitud: int = 14) -> pd.Series:
    cierre_previo = cierre.shift(1)
    rango_verdadero = pd.concat(
        [maximo - minimo, (maximo - cierre_previo).abs(), (minimo - cierre_previo).abs()],
        axis=1,
    ).max(axis=1)  # en la primera vela solo existe maximo - minimo
    return rma(rango_verdadero, longitud)


def adx(maximo: pd.Series, minimo: pd.Series, cierre: pd.Series, longitud: int = 14):
    """
    ADX con DI+ y DI- (DMI de Wilder, como ta.dmi de TradingView).
    El ADX mide la fuerza de la tendencia, sin importar su dirección; DI+ y DI-
    dicen si domina la presión compradora o la vendedora.
    """
    subida = maximo.diff()
    bajada = -minimo.diff()
    dm_mas = pd.Series(np.where((subida > bajada) & (subida > 0), subida, 0.0), index=maximo.index)
    dm_menos = pd.Series(np.where((bajada > subida) & (bajada > 0), bajada, 0.0), index=maximo.index)
    cierre_previo = cierre.shift(1)
    rango_verdadero = pd.concat(
        [maximo - minimo, (maximo - cierre_previo).abs(), (minimo - cierre_previo).abs()],
        axis=1,
    ).max(axis=1)
    # En la primera vela no hay vela anterior: ta.dmi la deja en NaN
    dm_mas.iloc[:1] = dm_menos.iloc[:1] = rango_verdadero.iloc[:1] = np.nan

    tr_suave = rma(rango_verdadero, longitud).replace(0, np.nan)
    di_mas = 100 * rma(dm_mas, longitud) / tr_suave
    di_menos = 100 * rma(dm_menos, longitud) / tr_suave
    suma = di_mas + di_menos
    dx = (di_mas - di_menos).abs() / suma.where(suma != 0, 1)
    return 100 * rma(dx, longitud), di_mas, di_menos


def estocastico(maximo: pd.Series, minimo: pd.Series, cierre: pd.Series,
                longitud: int = 14, suavizado_k: int = 3, suavizado_d: int = 3):
    minimo_n = minimo.rolling(longitud, min_periods=longitud).min()
    maximo_n = maximo.rolling(longitud, min_periods=longitud).max()
    rango = (maximo_n - minimo_n).replace(0, np.nan)
    k_rapido = 100 * (cierre - minimo_n) / rango
    # clip: las medias móviles pueden dar 100.00000000000001 por redondeo
    k = k_rapido.rolling(suavizado_k, min_periods=suavizado_k).mean().clip(0, 100)
    d = k.rolling(suavizado_d, min_periods=suavizado_d).mean().clip(0, 100)
    return k, d


def vwap_diario(maximo: pd.Series, minimo: pd.Series, cierre: pd.Series,
                volumen: pd.Series, apertura_ms: pd.Series) -> pd.Series:
    """VWAP que se reinicia cada día a las 00:00 UTC (precio típico = (H+L+C)/3)."""
    dia = apertura_ms // 86_400_000
    precio_tipico = (maximo + minimo + cierre) / 3
    pv = (precio_tipico * volumen).groupby(dia).cumsum()
    vol = volumen.groupby(dia).cumsum().replace(0, np.nan)
    return pv / vol


# ---------------------------------------------------------------------
#  Todo junto
# ---------------------------------------------------------------------
def calcular_indicadores(velas: pd.DataFrame, temporalidad: str) -> pd.DataFrame:
    """
    `velas` debe estar ordenado por fecha y tener las columnas:
        apertura_ms, maximo, minimo, cierre, volumen
    Devuelve un DataFrame con las columnas de COLUMNAS_INDICADORES.
    """
    h, l, c, v = velas["maximo"], velas["minimo"], velas["cierre"], velas["volumen"]
    r = pd.DataFrame(index=velas.index)

    for n in (20, 50, 200):
        r[f"sma_{n}"] = sma(c, n)
    for n in (20, 50, 200):
        r[f"ema_{n}"] = ema(c, n)

    r["rsi_14"] = rsi(c, 14)
    r["macd"], r["macd_senal"], r["macd_histograma"] = macd(c, 12, 26, 9)
    r["bb_superior"], r["bb_inferior"] = bollinger(c, 20, 2.0)
    r["atr_14"] = atr(h, l, c, 14)
    r["estoc_k"], r["estoc_d"] = estocastico(h, l, c, 14, 3, 3)
    r["vol_media_20"] = sma(v, 20)
    r["adx_14"], r["di_mas_14"], r["di_menos_14"] = adx(h, l, c, 14)

    if temporalidad in TEMPORALIDADES_CON_VWAP:
        r["vwap"] = vwap_diario(h, l, c, v, velas["apertura_ms"])
    else:
        r["vwap"] = np.nan

    return r[COLUMNAS_INDICADORES]
