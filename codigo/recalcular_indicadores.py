"""
DatosActivos - recalcula los indicadores de las velas que ya están guardadas.

Sirve para añadir un indicador nuevo (como el ADX) a una base de datos que ya
tiene velas, sin volver a descargarlas de Binance. Para cada activo y
temporalidad lee las velas de su base de datos (BTC/BTC.db...), calcula todos los indicadores de indicadores.py
sobre la serie completa y actualiza sus columnas. Los precios no se tocan.

Uso (desde la carpeta DatosActivos):
    python codigo/recalcular_indicadores.py                       # todo
    python codigo/recalcular_indicadores.py --simbolo BTCUSDT     # solo uno (o varios) activos
    python codigo/recalcular_indicadores.py --temporalidades 1d   # solo algunas temporalidades
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from cargar_datos import (TEMPORALIDADES, _a_lista_sql, abrir_bd_activo, abrir_principal,
                          activos_registrados, ruta_bd_activo, texto_a_ms)
from indicadores import COLUMNAS_INDICADORES, calcular_indicadores


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcula los indicadores de las velas guardadas.")
    parser.add_argument("--simbolo", "--simbolos", dest="simbolos", nargs="+",
                        help="activos a recalcular; por defecto, todos")
    parser.add_argument("--temporalidades", nargs="+", default=list(TEMPORALIDADES),
                        choices=list(TEMPORALIDADES), help="por defecto, todas")
    args = parser.parse_args()

    con_principal = abrir_principal()
    activos = activos_registrados(con_principal, args.simbolos)
    if not activos:
        con_principal.close()
        sys.exit("No hay activos que recalcular. Ejecuta antes cargar_datos.bat.")

    sql = (f"UPDATE velas SET {', '.join(c + ' = ?' for c in COLUMNAS_INDICADORES)} "
           f"WHERE activo_id = ? AND temporalidad = ? AND fecha_hora_utc = ?")
    inicio = time.time()
    total = 0
    try:
        for activo_id, simbolo, base in activos:
            if not ruta_bd_activo(base).exists():
                print(f"{simbolo}: todavía no tiene datos en la carpeta {base}.")
                continue
            print(f"{simbolo}:")
            con = abrir_bd_activo(con_principal, activo_id)
            try:
                for tf in args.temporalidades:
                    v = pd.read_sql_query(
                        "SELECT fecha_hora_utc, maximo, minimo, cierre, volumen FROM velas "
                        "WHERE activo_id = ? AND temporalidad = ? ORDER BY fecha_hora_utc",
                        con, params=(activo_id, tf))
                    if v.empty:
                        continue
                    v["apertura_ms"] = texto_a_ms(v["fecha_hora_utc"])
                    r = calcular_indicadores(v, tf)
                    columnas = [_a_lista_sql(r[c]) for c in COLUMNAS_INDICADORES]
                    n = len(v)
                    with con:
                        con.executemany(sql, zip(*columnas, [activo_id] * n, [tf] * n, v["fecha_hora_utc"]))
                    total += n
                    print(f"  {tf:>3}: {n:,} velas actualizadas")
            finally:
                con.close()
    finally:
        con_principal.close()
    print(f"\nListo: {total:,} velas recalculadas en {time.time() - inicio:,.0f} s.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido. Lo ya recalculado se conserva; vuelve a ejecutar para terminar.")
