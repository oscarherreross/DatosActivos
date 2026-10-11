"""
DatosActivos - motor de backtesting.

Prueba las estrategias de estrategias.py sobre las velas guardadas en la
carpeta de cada activo (BTC/BTC.db...) y deja los resultados en las tablas
`estrategias`, `backtests` y `operaciones` de la base de datos principal,
backtests.db (ver esquema_backtesting.sql).

Uso (desde la carpeta DatosActivos):
    python codigo/backtesting.py                                  # todas las estrategias, activos y temporalidades
    python codigo/backtesting.py --simbolo BTCUSDT                # solo uno (o varios) activos
    python codigo/backtesting.py --temporalidades 1h 4h           # solo algunas temporalidades
    python codigo/backtesting.py --estrategias rsi_30_70          # solo algunas estrategias
    python codigo/backtesting.py --direccion solo_largos          # largos_y_cortos (por defecto), solo_largos o solo_cortos
    python codigo/backtesting.py --comision 0.1 --capital 10000   # comisión por compra y por venta (%) y capital inicial
    python codigo/backtesting.py --desde 2021-01-01 --hasta 2024-12-31

Reglas de la simulación:
  * La señal se evalúa al cierre de una vela y la orden se ejecuta a la
    apertura de la siguiente: nunca se usan datos del futuro.
  * Comisión en cada entrada y en cada salida; cada entrada usa todo el
    capital disponible, así que los resultados son compuestos.
  * Una señal contraria cierra la posición y abre la opuesta en la misma
    apertura (si la dirección lo permite).
  * La posición que siga abierta al final se cierra al cierre de la última vela.
  * Los cortos se simulan sobre los precios del mercado al contado, sin el
    coste de financiación (funding) que tendrían en futuros.

Si se vuelve a ejecutar, cada backtest con las mismas condiciones (estrategia,
activo, temporalidad, dirección, comisión, capital y fecha de inicio) se
sustituye por el nuevo, junto con sus operaciones.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from cargar_datos import abrir_bd_activo, abrir_principal, activos_registrados
from estrategias import ESTRATEGIAS, FUNCIONES

VERSION_MOTOR = "1.0"

TEMPORALIDADES = ["5m", "15m", "1h", "4h", "1d", "1w"]
DIRECCIONES = ["largos_y_cortos", "solo_largos", "solo_cortos"]
NOTA_CORTOS = "Cortos simulados sobre precios spot, sin costes de financiación (funding)."


def ahora_texto() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------
#  Base de datos
# ---------------------------------------------------------------------
def sincronizar_estrategias(con: sqlite3.Connection) -> dict[str, int]:
    """Da de alta en la tabla `estrategias` las definidas en estrategias.py."""
    ids = {}
    with con:
        for e in ESTRATEGIAS:
            parametros = json.dumps(e["parametros"], ensure_ascii=False, sort_keys=True)
            fila = con.execute("SELECT id, codigo, parametros FROM estrategias WHERE nombre = ?",
                               (e["nombre"],)).fetchone()
            if fila is None:
                cur = con.execute(
                    "INSERT INTO estrategias (nombre, codigo, descripcion, parametros, fecha_creacion_utc) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (e["nombre"], e["codigo"], e["descripcion"], parametros, ahora_texto()))
                ids[e["nombre"]] = cur.lastrowid
            else:
                if (fila[1], fila[2]) != (e["codigo"], parametros):
                    sys.exit(f"La estrategia '{e['nombre']}' ya existe en la base de datos con otro código o "
                             f"parámetros. Si la has cambiado, dale un nombre nuevo en estrategias.py para "
                             f"no mezclar resultados.")
                con.execute("UPDATE estrategias SET descripcion = ? WHERE id = ?", (e["descripcion"], fila[0]))
                ids[e["nombre"]] = fila[0]
    return ids


def leer_velas(con: sqlite3.Connection, activo_id: int, temporalidad: str,
               desde: str | None, hasta: str | None) -> pd.DataFrame:
    consulta = "SELECT * FROM velas WHERE activo_id = ? AND temporalidad = ?"
    parametros: list = [activo_id, temporalidad]
    if desde:
        consulta += " AND fecha_hora_utc >= ?"
        parametros.append(desde)
    if hasta:
        consulta += " AND fecha_cierre_utc <= ?"
        parametros.append(hasta)
    consulta += " ORDER BY fecha_hora_utc"
    return pd.read_sql_query(consulta, con, params=parametros)


# ---------------------------------------------------------------------
#  Simulación
# ---------------------------------------------------------------------
def simular(v: pd.DataFrame, senales: dict, direccion: str, comision_pct: float,
            capital_inicial: float) -> tuple[list[dict], dict]:
    """Recorre las velas en orden y devuelve las operaciones y datos de la curva de capital."""
    f = comision_pct / 100.0
    largos = direccion in ("largos_y_cortos", "solo_largos")
    cortos = direccion in ("largos_y_cortos", "solo_cortos")

    apertura = v["apertura"].to_numpy(float)
    cierre = v["cierre"].to_numpy(float)
    fecha_ap = v["fecha_hora_utc"].to_numpy()
    fecha_ci = v["fecha_cierre_utc"].to_numpy()
    el, sl = senales["entrada_larga"], senales["salida_larga"]
    ec, sc = senales["entrada_corta"], senales["salida_corta"]
    n = len(v)

    capital = capital_inicial
    pos = 0                 # 1 largo, -1 corto, 0 fuera
    invertido = cantidad = 0.0
    abierta: dict | None = None
    pendiente_cerrar: str | None = None   # motivo de salida a ejecutar en la próxima apertura
    pendiente_abrir = 0                   # dirección a abrir en la próxima apertura
    senal_abrir = ""
    operaciones: list[dict] = []
    max_capital, max_dd, velas_dentro = capital, 0.0, 0

    def abrir(i: int, d: int, fecha_senal: str) -> None:
        nonlocal pos, invertido, cantidad, abierta
        pos = d
        invertido = capital * (1 - f)
        cantidad = invertido / apertura[i]
        abierta = {"direccion": "largo" if d == 1 else "corto", "fecha_senal_utc": fecha_senal,
                   "fecha_entrada_utc": fecha_ap[i], "precio_entrada": apertura[i], "indice": i,
                   "capital_entrada": capital, "comisiones": capital * f}

    def cerrar(precio: float, fecha: str, motivo: str, duracion: int) -> None:
        nonlocal pos, capital, abierta
        valor = cantidad * precio
        com = valor * f
        bruto = valor if pos == 1 else invertido + cantidad * (abierta["precio_entrada"] - precio)
        nuevo = max(bruto - com, 0.0)
        abierta.update({"fecha_salida_utc": fecha, "precio_salida": precio, "motivo_salida": motivo,
                        "duracion_velas": duracion, "capital_salida": nuevo,
                        "comisiones": abierta["comisiones"] + com,
                        "beneficio": nuevo - abierta["capital_entrada"],
                        "rentabilidad_pct": (nuevo / abierta["capital_entrada"] - 1) * 100})
        del abierta["indice"]
        operaciones.append(abierta)
        capital, pos, abierta = nuevo, 0, None

    for i in range(n):
        # 1) Apertura de la vela: se ejecutan las órdenes decididas al cierre de la anterior
        if pendiente_cerrar and pos != 0:
            cerrar(apertura[i], fecha_ap[i], pendiente_cerrar, i - abierta["indice"])
        if pendiente_abrir and capital > 0:
            abrir(i, pendiente_abrir, senal_abrir)
        pendiente_cerrar, pendiente_abrir = None, 0

        # 2) Cierre de la vela: capital a precio de mercado y nuevas señales
        if pos == 0:
            valor_actual = capital
        else:
            velas_dentro += 1
            if pos == 1:
                valor_actual = cantidad * cierre[i]
            else:
                valor_actual = invertido + cantidad * (abierta["precio_entrada"] - cierre[i])
            if valor_actual <= 0:   # un corto ha perdido todo el capital
                cerrar(cierre[i], fecha_ci[i], "capital_agotado", i - abierta["indice"] + 1)
                max_dd = 100.0
                break
        max_capital = max(max_capital, valor_actual)
        max_dd = max(max_dd, (1 - valor_actual / max_capital) * 100)

        if i == n - 1:
            if pos != 0:
                cerrar(cierre[i], fecha_ci[i], "fin_periodo", i - abierta["indice"] + 1)
            break

        if pos == 0:
            if largos and el[i]:
                pendiente_abrir = 1
            elif cortos and ec[i]:
                pendiente_abrir = -1
        elif pos == 1:
            giro = cortos and ec[i]
            if sl[i] or giro:
                pendiente_cerrar = "giro" if giro else "senal_salida"
                pendiente_abrir = -1 if giro else 0
        else:
            giro = largos and el[i]
            if sc[i] or giro:
                pendiente_cerrar = "giro" if giro else "senal_salida"
                pendiente_abrir = 1 if giro else 0
        if pendiente_abrir:
            senal_abrir = fecha_ci[i]

    curva = {"capital_final": capital, "max_drawdown_pct": max_dd,
             "tiempo_en_mercado_pct": velas_dentro / n * 100 if n else None}
    return operaciones, curva


# ---------------------------------------------------------------------
#  Métricas
# ---------------------------------------------------------------------
def _compuesta(r: np.ndarray) -> float:
    """Rentabilidad total (%) de encadenar las operaciones con rentabilidades r (%)."""
    return (float(np.prod(1 + r / 100)) - 1) * 100 if len(r) else 0.0


def metricas(ops: list[dict], curva: dict, capital_inicial: float) -> dict:
    r = np.array([o["rentabilidad_pct"] for o in ops], dtype=float)
    pnl = np.array([o["beneficio"] for o in ops], dtype=float)
    dirs = np.array([o["direccion"] for o in ops])
    n = len(r)
    gan, perd = r[r > 0], r[r <= 0]
    k = max(1, math.ceil(0.05 * n)) if n else None
    orden = np.argsort(r, kind="stable")       # de peor a mejor
    suma_gan = gan.sum()
    suma_perd = -perd.sum()
    pnl_gan, pnl_perd = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()

    m = {
        "capital_final": curva["capital_final"],
        "rentabilidad_total_pct": (curva["capital_final"] / capital_inicial - 1) * 100,
        "max_drawdown_pct": curva["max_drawdown_pct"],
        "tiempo_en_mercado_pct": curva["tiempo_en_mercado_pct"],
        "comisiones_totales": float(sum(o["comisiones"] for o in ops)),
        "num_operaciones": n,
        "num_largos": int((dirs == "largo").sum()),
        "num_cortos": int((dirs == "corto").sum()),
        "num_ganadoras": len(gan),
        "num_perdedoras": len(perd),
        "pct_acierto": len(gan) / n * 100 if n else None,
        "rentabilidad_largos_pct": _compuesta(r[dirs == "largo"]) if (dirs == "largo").any() else None,
        "rentabilidad_cortos_pct": _compuesta(r[dirs == "corto"]) if (dirs == "corto").any() else None,
        "ganancia_media_ganadoras_pct": float(gan.mean()) if len(gan) else None,
        "perdida_media_perdedoras_pct": float(perd.mean()) if len(perd) else None,
        "profit_factor": float(pnl_gan / pnl_perd) if pnl_perd > 0 else None,
        "rentabilidad_media_op_pct": float(r.mean()) if n else None,
        "rentabilidad_mediana_op_pct": float(np.median(r)) if n else None,
        "duracion_media_velas": float(np.mean([o["duracion_velas"] for o in ops])) if n else None,
        "num_ops_5pct": k,
        "mejor_op_pct": None, "peso_mejor_op_pct": None, "peso_mejores_5pct_pct": None,
        "rentabilidad_sin_mejor_pct": None, "rentabilidad_sin_mejores_5pct_pct": None,
        "peor_op_pct": None, "peso_peor_op_pct": None, "peso_peores_5pct_pct": None,
        "rentabilidad_sin_peor_pct": None, "rentabilidad_sin_peores_5pct_pct": None,
    }
    if n:
        mejores, peores = orden[::-1][:k], orden[:k]
        m.update({
            "mejor_op_pct": float(r[orden[-1]]),
            "peor_op_pct": float(r[orden[0]]),
            "rentabilidad_sin_mejor_pct": _compuesta(np.delete(r, orden[-1])),
            "rentabilidad_sin_mejores_5pct_pct": _compuesta(np.delete(r, mejores)),
            "rentabilidad_sin_peor_pct": _compuesta(np.delete(r, orden[0])),
            "rentabilidad_sin_peores_5pct_pct": _compuesta(np.delete(r, peores)),
        })
        if suma_gan > 0:
            rm = r[mejores]
            m["peso_mejor_op_pct"] = float(max(r[orden[-1]], 0) / suma_gan * 100)
            m["peso_mejores_5pct_pct"] = float(rm[rm > 0].sum() / suma_gan * 100)
        if suma_perd > 0:
            rp = r[peores]
            m["peso_peor_op_pct"] = float(max(-r[orden[0]], 0) / suma_perd * 100)
            m["peso_peores_5pct_pct"] = float(-rp[rp < 0].sum() / suma_perd * 100)
    return m


# ---------------------------------------------------------------------
#  Guardado
# ---------------------------------------------------------------------
COLUMNAS_OPERACION = ["numero", "direccion", "fecha_senal_utc", "fecha_entrada_utc", "precio_entrada",
                      "fecha_salida_utc", "precio_salida", "motivo_salida", "duracion_velas",
                      "capital_entrada", "capital_salida", "comisiones", "beneficio", "rentabilidad_pct"]


def _sql(x):
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def guardar(con: sqlite3.Connection, condiciones: dict, m: dict, ops: list[dict]) -> int:
    """Guarda un backtest y sus operaciones, sustituyendo el anterior con las mismas condiciones."""
    clave = ["estrategia_id", "activo_id", "temporalidad", "direccion", "comision_pct",
             "capital_inicial", "fecha_inicio_utc"]
    anteriores = con.execute(
        f"SELECT id FROM backtests WHERE {' AND '.join(c + ' = ?' for c in clave)}",
        [condiciones[c] for c in clave]).fetchall()
    for (bid,) in anteriores:
        con.execute("DELETE FROM operaciones WHERE backtest_id = ?", (bid,))
        con.execute("DELETE FROM backtests WHERE id = ?", (bid,))

    fila = {**condiciones, **m}
    columnas = list(fila)
    cur = con.execute(f"INSERT INTO backtests ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
                      [_sql(fila[c]) for c in columnas])
    bid = cur.lastrowid
    con.executemany(
        f"INSERT INTO operaciones (backtest_id, {', '.join(COLUMNAS_OPERACION)}) "
        f"VALUES (?, {', '.join('?' * len(COLUMNAS_OPERACION))})",
        [[bid] + [_sql(num if c == "numero" else o[c]) for c in COLUMNAS_OPERACION]
         for num, o in enumerate(ops, start=1)])
    return bid


# ---------------------------------------------------------------------
#  Programa principal
# ---------------------------------------------------------------------
def fmt(x, dec=1) -> str:
    return "-" if x is None else f"{x:,.{dec}f}"


def main() -> None:
    nombres = [e["nombre"] for e in ESTRATEGIAS]
    parser = argparse.ArgumentParser(description="Prueba las estrategias sobre las velas guardadas.")
    parser.add_argument("--simbolo", "--simbolos", dest="simbolos", nargs="+",
                        help="activos a probar; por defecto, todos los de la base de datos")
    parser.add_argument("--temporalidades", nargs="+", default=TEMPORALIDADES, choices=TEMPORALIDADES)
    parser.add_argument("--estrategias", nargs="+", default=nombres, choices=nombres)
    parser.add_argument("--direccion", default="largos_y_cortos", choices=DIRECCIONES)
    parser.add_argument("--comision", type=float, default=0.1, help="comisión por compra y por venta, en %% (0.1)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="capital inicial en USDT (10000)")
    parser.add_argument("--desde", help="fecha inicial AAAA-MM-DD; por defecto, todo el histórico")
    parser.add_argument("--hasta", help="fecha final AAAA-MM-DD; por defecto, hasta la última vela")
    args = parser.parse_args()

    con = abrir_principal()
    ids_estrategia = sincronizar_estrategias(con)
    if not args.estrategias:
        con.close()
        print("Tablas estrategias, backtests y operaciones listas en la base de datos.\n"
              "Todavía no hay estrategias definidas: añádelas en ESTRATEGIAS, en estrategias.py.")
        return
    definiciones = {e["nombre"]: e for e in ESTRATEGIAS}

    activos = activos_registrados(con, args.simbolos)
    if args.simbolos:
        faltan = {s.upper() for s in args.simbolos} - {s for _, s, _ in activos}
        if faltan:
            sys.exit(f"No hay velas de {', '.join(sorted(faltan))}. Cárgalas antes con cargar_datos.bat.")
    hasta = f"{args.hasta} 23:59:59" if args.hasta and len(args.hasta) == 10 else args.hasta
    f = args.comision / 100

    print(f"Backtesting: {len(args.estrategias)} estrategias, {len(activos)} activos, "
          f"{len(args.temporalidades)} temporalidades | {args.direccion}, comision {args.comision} %, "
          f"capital {args.capital:,.0f} USDT\n")
    cabecera = (f"{'activo':<10}{'temp.':>5}  {'estrategia':<23}{'rentab.%':>12}{'comprar y':>12}"
                f"{'ops':>7}{'acierto%':>9}{'sin 5% mejor':>14}{'max caida%':>11}")
    print(cabecera + f"\n{'':<40}{'':>12}{'mantener%':>12}\n" + "-" * len(cabecera))

    for activo_id, simbolo, base in activos:
        con_velas = abrir_bd_activo(con, activo_id, solo_lectura=True)
        if con_velas is None:
            print(f"{simbolo:<10}todavía no tiene datos en la carpeta {base}")
            continue
        for temporalidad in args.temporalidades:
            v = leer_velas(con_velas, activo_id, temporalidad, args.desde, hasta)
            if len(v) < 2:
                continue
            ap0, ci1 = float(v["apertura"].iloc[0]), float(v["cierre"].iloc[-1])
            comprar_mantener = ((1 - f) * ci1 / ap0 * (1 - f) - 1) * 100
            with con:
                for nombre in args.estrategias:
                    e = definiciones[nombre]
                    senales = FUNCIONES[e["codigo"]](v, e["parametros"])
                    ops, curva = simular(v, senales, args.direccion, args.comision, args.capital)
                    m = metricas(ops, curva, args.capital)
                    m["rentabilidad_comprar_mantener_pct"] = comprar_mantener
                    condiciones = {
                        "estrategia_id": ids_estrategia[nombre], "activo_id": activo_id,
                        "temporalidad": temporalidad, "fecha_ejecucion_utc": ahora_texto(),
                        "version_motor": VERSION_MOTOR,
                        "fecha_inicio_utc": v["fecha_hora_utc"].iloc[0],
                        "fecha_fin_utc": v["fecha_cierre_utc"].iloc[-1], "num_velas": len(v),
                        "direccion": args.direccion, "comision_pct": args.comision,
                        "capital_inicial": args.capital,
                        "notas": NOTA_CORTOS if args.direccion != "solo_largos" else None,
                    }
                    guardar(con, condiciones, m, ops)
                    print(f"{simbolo:<10}{temporalidad:>5}  {nombre:<23}{fmt(m['rentabilidad_total_pct']):>12}"
                          f"{fmt(comprar_mantener):>12}{m['num_operaciones']:>7}{fmt(m['pct_acierto']):>9}"
                          f"{fmt(m['rentabilidad_sin_mejores_5pct_pct']):>14}{fmt(m['max_drawdown_pct']):>11}")
        con_velas.close()
    con.close()
    print("\nResultados guardados en backtests.db, tablas backtests y operaciones (vista v_backtests).")


if __name__ == "__main__":
    main()
