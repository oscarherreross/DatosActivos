"""
DatosActivos - estudio estadístico de tendencias para comprar en spot.

Para cada vela mira en qué situación estaban los indicadores al cierre y qué
hizo después el precio: la rentabilidad comprando en la apertura de la vela
siguiente y vendiendo N velas más tarde, y la caída máxima por el camino.
Compara cada situación con la media de todas las velas del mismo activo
(la "base") para ver cuáles precedieron a subidas mejores que la media.

Solo lee las bases de datos de cada activo (no escribe nada en ellas). Deja los resultados en
la carpeta resultados/estudio_tendencias/:
    resultados.csv   una fila por situación, activo, temporalidad, horizonte y periodo
    resumen.csv      las situaciones ordenadas por su ventaja media frente a la base

Uso (desde la carpeta DatosActivos):
    python codigo/estudio_tendencias.py
    python codigo/estudio_tendencias.py --corte 2023-01-01   # fecha que separa los dos periodos
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backtesting import leer_velas
from cargar_datos import BD_PRINCIPAL, CARPETA_RESULTADOS, ruta_bd_activo

SALIDA = CARPETA_RESULTADOS / "estudio_tendencias"

# Horizontes en velas y su nombre
HORIZONTES = {
    "1w": {"4 semanas": 4, "13 semanas": 13, "26 semanas": 26},
    "1d": {"7 días": 7, "30 días": 30, "90 días": 90},
    "4h": {"1 día": 6, "7 días": 42, "30 días": 180},
}


def leer(con, activo_id: int, tf: str) -> pd.DataFrame:
    # leer_velas deja como número (NaN) los indicadores que un activo con pocas velas tiene
    # en NULL en toda la serie, como la EMA 200 semanal; si no, no se podrían comparar.
    v = leer_velas(con, activo_id, tf, None, None)
    v["fecha_cierre"] = pd.to_datetime(v["fecha_cierre_utc"], utc=True)
    return v


def situaciones(v: pd.DataFrame, diaria: pd.DataFrame | None) -> dict[str, tuple[str, pd.Series]]:
    """Devuelve {nombre: (familia, condición booleana por vela)}. Todo con datos ya cerrados."""
    c, e20, e50, e200 = v["cierre"], v["ema_20"], v["ema_50"], v["ema_200"]
    adx, dip, dim = v["adx_14"], v["di_mas_14"], v["di_menos_14"]
    rsi = v["rsi_14"]
    pctb = (c - v["bb_inferior"]) / (v["bb_superior"] - v["bb_inferior"])
    dist200 = (c / e200 - 1) * 100
    alcista = (c > e200) & (e50 > e200)
    bajista = (c < e200) & (e50 < e200)
    s: dict[str, tuple[str, pd.Series]] = {}

    def add(familia, nombre, cond):
        s[nombre] = (familia, cond.fillna(False).astype(bool))

    add("Tendencia", "Precio sobre EMA 200", c > e200)
    add("Tendencia", "Precio bajo EMA 200", c < e200)
    add("Tendencia", "EMA 50 sobre EMA 200", e50 > e200)
    add("Tendencia", "EMA 50 bajo EMA 200", e50 < e200)
    add("Tendencia", "EMA 200 subiendo (vs 20 velas antes)", e200 > e200.shift(20))
    add("Tendencia", "EMA 200 bajando (vs 20 velas antes)", e200 < e200.shift(20))
    add("Tendencia", "Medias alineadas al alza (precio > EMA20 > EMA50 > EMA200)", (c > e20) & (e20 > e50) & (e50 > e200))
    add("Tendencia", "Medias alineadas a la baja", (c < e20) & (e20 < e50) & (e50 < e200))
    cruce_dorado = (e50 > e200) & (e50.shift(1) <= e200.shift(1))
    add("Tendencia", "Cruce dorado en las últimas 10 velas", cruce_dorado.rolling(10, min_periods=1).max() > 0)
    cruce_muerte = (e50 < e200) & (e50.shift(1) >= e200.shift(1))
    add("Tendencia", "Cruce de la muerte en las últimas 10 velas", cruce_muerte.rolling(10, min_periods=1).max() > 0)

    add("ADX", "ADX < 20 (sin tendencia)", adx < 20)
    add("ADX", "ADX 20-25", (adx >= 20) & (adx < 25))
    add("ADX", "ADX > 25 con DI+ > DI- (tendencia alcista fuerte)", (adx > 25) & (dip > dim))
    add("ADX", "ADX > 25 con DI- > DI+ (tendencia bajista fuerte)", (adx > 25) & (dim > dip))
    add("ADX", "ADX > 40 con DI+ > DI-", (adx > 40) & (dip > dim))
    add("ADX", "ADX > 40 con DI- > DI+", (adx > 40) & (dim > dip))
    add("ADX", "ADX subiendo y DI+ > DI-", (adx > adx.shift(3)) & (dip > dim) & (adx > 20))
    add("ADX", "DI+ cruza al alza DI- (últimas 3 velas)",
        (((dip > dim) & (dip.shift(1) <= dim.shift(1))).rolling(3, min_periods=1).max() > 0))

    for a, b in [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 101)]:
        add("RSI", f"RSI {a}-{min(b, 100)}", (rsi >= a) & (rsi < b))
    add("MACD", "MACD > señal y > 0", (v["macd"] > v["macd_senal"]) & (v["macd"] > 0))
    add("MACD", "MACD > señal y < 0 (giro desde abajo)", (v["macd"] > v["macd_senal"]) & (v["macd"] < 0))
    add("MACD", "MACD < señal y > 0", (v["macd"] < v["macd_senal"]) & (v["macd"] > 0))
    add("MACD", "MACD < señal y < 0", (v["macd"] < v["macd_senal"]) & (v["macd"] < 0))
    add("Bollinger", "Cierre bajo la banda inferior", pctb < 0)
    add("Bollinger", "Cierre sobre la banda superior", pctb > 1)
    add("Estocástico", "Estocástico %K < 20", v["estoc_k"] < 20)
    add("Estocástico", "Estocástico %K > 80", v["estoc_k"] > 80)
    for a, b in [(-1000, -30), (-30, -10), (-10, 0), (0, 10), (10, 30), (30, 60), (60, 10000)]:
        etiqueta = (f"menos de {a if b != -30 else -30} %" if a == -1000 else
                    f"más de +{a} %" if b == 10000 else f"{a:+d} % a {b:+d} %")
        add("Distancia a EMA 200", f"Precio {etiqueta} de la EMA 200", (dist200 >= a) & (dist200 < b))
    add("Volumen", "Volumen > 2 x su media", v["volumen"] > 2 * v["vol_media_20"])

    # Combinaciones pensadas para comprar en spot
    add("Combinación", "Tendencia alcista + RSI < 40 (retroceso)", alcista & (rsi < 40))
    add("Combinación", "Tendencia alcista + RSI < 50", alcista & (rsi < 50))
    add("Combinación", "Tendencia alcista + toca la EMA 50", alcista & (v["minimo"] <= e50) & (c > e50))
    add("Combinación", "Tendencia alcista + ADX > 25 con DI+ > DI-", alcista & (adx > 25) & (dip > dim))
    add("Combinación", "Tendencia alcista + ADX < 20", alcista & (adx < 20))
    add("Combinación", "Tendencia alcista + bajo banda inferior", alcista & (pctb < 0))
    add("Combinación", "Tendencia bajista + RSI < 30 (capitulación)", bajista & (rsi < 30))
    add("Combinación", "Tendencia bajista + ADX > 25 con DI- > DI+", bajista & (adx > 25) & (dim > dip))
    add("Combinación", "Tendencia bajista + ADX < 20 (suelo lateral)", bajista & (adx < 20))
    add("Combinación", "Bajo EMA 200 + MACD gira al alza", (c < e200) & (v["macd"] > v["macd_senal"])
        & (v["macd"].shift(1) <= v["macd_senal"].shift(1)))

    # Temporalidad baja dentro de la tendencia diaria (última vela diaria ya cerrada)
    if diaria is not None:
        d = diaria[["fecha_cierre", "cierre", "ema_50", "ema_200", "adx_14", "di_mas_14", "di_menos_14"]]
        d = d.assign(alcista_d=(d["cierre"] > d["ema_200"]) & (d["ema_50"] > d["ema_200"]),
                     bajista_d=(d["cierre"] < d["ema_200"]) & (d["ema_50"] < d["ema_200"]),
                     fuerte_d=(d["adx_14"] > 25) & (d["di_mas_14"] > d["di_menos_14"]))
        m = pd.merge_asof(v[["fecha_cierre"]], d[["fecha_cierre", "alcista_d", "bajista_d", "fuerte_d"]],
                          on="fecha_cierre", direction="backward")
        ad = m["alcista_d"].eq(True).to_numpy()
        bd = m["bajista_d"].eq(True).to_numpy()
        fd = m["fuerte_d"].eq(True).to_numpy()
        add("Multitemporal", "Diario alcista", pd.Series(ad, index=v.index))
        add("Multitemporal", "Diario bajista", pd.Series(bd, index=v.index))
        add("Multitemporal", "Diario alcista + RSI 4h < 30", pd.Series(ad, index=v.index) & (rsi < 30))
        add("Multitemporal", "Diario alcista + RSI 4h < 40", pd.Series(ad, index=v.index) & (rsi < 40))
        add("Multitemporal", "Diario bajista + RSI 4h < 30", pd.Series(bd, index=v.index) & (rsi < 30))
        add("Multitemporal", "Diario alcista + 4h toca la EMA 50", pd.Series(ad, index=v.index)
            & (v["minimo"] <= e50) & (c > e50))
        add("Multitemporal", "Diario con ADX > 25 y DI+ > DI- + RSI 4h < 40", pd.Series(fd, index=v.index) & (rsi < 40))
    return s


def episodios(cond: np.ndarray) -> int:
    """Número de rachas de velas consecutivas que cumplen la condición."""
    return int(np.sum(cond[1:] & ~cond[:-1]) + cond[0]) if len(cond) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Estudio de tendencias para comprar en spot.")
    parser.add_argument("--corte", default="2023-01-01", help="fecha que separa los periodos A (antes) y B (después)")
    args = parser.parse_args()

    if not BD_PRINCIPAL.exists():
        raise SystemExit("No hay datos todavía: ejecuta antes cargar_datos.bat.")
    principal = sqlite3.connect(f"file:{BD_PRINCIPAL.as_posix()}?mode=ro", uri=True)
    activos = principal.execute("SELECT id, simbolo, base FROM activos ORDER BY id").fetchall()
    principal.close()
    corte = pd.Timestamp(args.corte, tz="UTC")
    filas = []
    for activo_id, simbolo, base in activos:
        ruta = ruta_bd_activo(base)
        if not ruta.exists():
            print(f"{simbolo}: todavía no tiene datos en la carpeta {base}, se omite.")
            continue
        con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
        if "adx_14" not in {f[1] for f in con.execute("PRAGMA table_info(velas)")}:
            raise SystemExit(f"{base}/{ruta.name} aún no tiene el ADX: ejecuta antes recalcular_indicadores.bat.")
        diaria = leer(con, activo_id, "1d")
        for tf, horizontes in HORIZONTES.items():
            v = diaria if tf == "1d" else leer(con, activo_id, tf)
            s = situaciones(v, diaria if tf == "4h" else None)
            ap, ci, mi = v["apertura"].to_numpy(), v["cierre"].to_numpy(), v["minimo"].to_numpy()
            n = len(v)
            periodo = np.where(v["fecha_cierre"] < corte, "A", "B")
            for hnombre, h in horizontes.items():
                # Compra en la apertura de la vela siguiente y venta al cierre h velas después
                rent = np.full(n, np.nan)
                caida = np.full(n, np.nan)
                entrada = ap[1:n - h + 1] if n > h else np.array([])
                if len(entrada):
                    rent[:n - h] = (ci[h:] / entrada - 1) * 100
                    minimos = pd.Series(mi).rolling(h).min().shift(-h).to_numpy()
                    caida[:n - h] = (minimos[:n - h] / entrada - 1) * 100
                valida = ~np.isnan(rent)
                for per in ("A", "B", "Todo"):
                    sel = valida & ((periodo == per) if per != "Todo" else True)
                    if sel.sum() < 30:
                        continue
                    base_media = rent[sel].mean()
                    base_mediana = np.median(rent[sel])
                    base_pos = (rent[sel] > 0).mean() * 100
                    for nombre, (familia, cond) in s.items():
                        cnd = cond.to_numpy() & sel
                        k = int(cnd.sum())
                        if k == 0:
                            continue
                        r = rent[cnd]
                        filas.append({
                            "simbolo": simbolo, "temporalidad": tf, "horizonte": hnombre, "periodo": per,
                            "familia": familia, "situacion": nombre, "velas": k,
                            "episodios": episodios(cnd), "pct_velas": k / sel.sum() * 100,
                            "rent_media": r.mean(), "rent_mediana": np.median(r),
                            "pct_positivas": (r > 0).mean() * 100, "caida_media": caida[cnd].mean(),
                            "base_media": base_media, "base_mediana": base_mediana,
                            "base_pct_positivas": base_pos,
                            "ventaja_media": r.mean() - base_media,
                            "ventaja_mediana": np.median(r) - base_mediana,
                            "ventaja_pct_positivas": (r > 0).mean() * 100 - base_pos,
                        })
        con.close()
    res = pd.DataFrame(filas)
    SALIDA.mkdir(exist_ok=True)
    res.to_csv(SALIDA / "resultados.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")

    # Resumen: por situación, temporalidad y horizonte, media de los activos y consistencia
    clave = ["temporalidad", "horizonte", "familia", "situacion"]
    t = res[res["periodo"] == "Todo"].groupby(clave).agg(
        activos=("simbolo", "nunique"), velas=("velas", "sum"), episodios=("episodios", "sum"),
        pct_velas=("pct_velas", "mean"), rent_media=("rent_media", "mean"),
        base_media=("base_media", "mean"), ventaja_media=("ventaja_media", "mean"),
        rent_mediana=("rent_mediana", "mean"), ventaja_mediana=("ventaja_mediana", "mean"),
        pct_positivas=("pct_positivas", "mean"), ventaja_pct_positivas=("ventaja_pct_positivas", "mean"),
        caida_media=("caida_media", "mean"))
    # Un "caso" es un activo en un periodo; gana si supera a la base en media y en mediana
    pos = res[res["periodo"].isin(["A", "B"])].assign(
        gana=lambda x: (x["ventaja_media"] > 0) & (x["ventaja_mediana"] > 0))
    consist = pos.groupby(clave).agg(casos_ganadores=("gana", "sum"), casos=("gana", "size"))
    porper = pos.pivot_table(index=clave, columns="periodo", values=["ventaja_media", "ventaja_mediana"],
                             aggfunc="mean")
    porper.columns = [f"{v}_{p}" for v, p in porper.columns]
    resumen = t.join(consist).join(porper).reset_index().sort_values(
        ["temporalidad", "horizonte", "ventaja_media"], ascending=[True, True, False])
    resumen.to_csv(SALIDA / "resumen.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    print(f"Hecho: {len(res):,} filas en {SALIDA / 'resultados.csv'} y resumen en {SALIDA / 'resumen.csv'}")


if __name__ == "__main__":
    main()
