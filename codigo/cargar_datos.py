"""
DatosActivos - descarga el histórico de velas de Binance y lo guarda en la
base de datos SQLite de cada activo junto con los indicadores al cierre de
cada vela.

Cada activo tiene su carpeta dentro de activos/, con el nombre de su moneda
base (activos/BTC, activos/ETH...), y dentro su base de datos (BTC.db) con
las velas y los indicadores. La lista de activos que se cargan es
activos/activos.txt. La lista de activos registrados, las estrategias y los
backtests están en resultados/backtests.db.

Uso (desde la carpeta DatosActivos):
    python codigo/cargar_datos.py                          # todos los activos de activos.txt
    python codigo/cargar_datos.py --simbolo ETHUSDT        # solo uno (o varios) concretos
    python codigo/cargar_datos.py --temporalidades 1h 4h   # solo algunas temporalidades
    python codigo/cargar_datos.py --desde 2020-01-01       # empezar en una fecha (solo en la primera carga)

Para cada activo descarga las 6 temporalidades desde que empezó a cotizar.
Si se vuelve a ejecutar, solo descarga las velas cerradas posteriores a la
última guardada; las que ya están en la base de datos no se tocan.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from indicadores import COLUMNAS_INDICADORES, calcular_indicadores

CARPETA = Path(__file__).resolve().parent     # codigo/
RAIZ = CARPETA.parent                          # DatosActivos/
CARPETA_ACTIVOS = RAIZ / "activos"             # una subcarpeta por activo
CARPETA_RESULTADOS = RAIZ / "resultados"
BD_PRINCIPAL = CARPETA_RESULTADOS / "backtests.db"  # lista de activos, estrategias y backtests
ESQUEMA = CARPETA / "esquema.sql"              # base de datos de cada activo
ESQUEMA_PRINCIPAL = CARPETA / "esquema_backtesting.sql"
ARCHIVO_ACTIVOS = CARPETA_ACTIVOS / "activos.txt"

EXCHANGE = "Binance"
SERVIDORES = ["https://api.binance.com", "https://data-api.binance.vision"]
VELAS_POR_PETICION = 1000

TEMPORALIDADES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}

COLUMNAS_VELA = ["apertura", "maximo", "minimo", "cierre",
                 "volumen", "volumen_cotizado", "num_operaciones"]
COLUMNAS_INSERCION = (["activo_id", "temporalidad", "fecha_hora_utc", "fecha_cierre_utc"]
                      + COLUMNAS_VELA + COLUMNAS_INDICADORES)

MS_POR_MINUTO = 60_000
EPOCA = pd.Timestamp("1970-01-01", tz="UTC")


# ---------------------------------------------------------------------
#  Utilidades de fechas
# ---------------------------------------------------------------------
def ms_a_texto(ms: pd.Series) -> pd.Series:
    return pd.to_datetime(ms, unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")


def texto_a_ms(texto: pd.Series) -> pd.Series:
    fechas = pd.to_datetime(texto, format="%Y-%m-%d %H:%M:%S", utc=True)
    return ((fechas - EPOCA) // pd.Timedelta(milliseconds=1)).astype("int64")


def ahora_texto() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------
#  Acceso a la API pública de Binance (no necesita clave)
# ---------------------------------------------------------------------
def pedir_json(ruta: str, parametros: dict | None = None, reintentos: int = 5):
    consulta = urllib.parse.urlencode(parametros or {})
    ultimo_error: Exception | None = None
    for intento in range(reintentos):
        for servidor in SERVIDORES:
            url = f"{servidor}{ruta}" + (f"?{consulta}" if consulta else "")
            peticion = urllib.request.Request(url, headers={"User-Agent": "DatosActivos/1.0"})
            try:
                with urllib.request.urlopen(peticion, timeout=30) as respuesta:
                    return json.loads(respuesta.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code in (418, 429):  # límite de peticiones superado
                    espera = int(error.headers.get("Retry-After") or 60)
                    print(f"\n  Binance pide esperar {espera} s por exceso de peticiones...")
                    time.sleep(espera)
                elif error.code == 400:  # petición incorrecta (p. ej. símbolo inexistente)
                    detalle = error.read().decode("utf-8", errors="replace")
                    raise SystemExit(f"Binance rechazó la petición {ruta}: {detalle}")
                ultimo_error = error
            except OSError as error:  # sin conexión, timeout, etc.
                ultimo_error = error
        time.sleep(2 ** intento)
    raise SystemExit(f"No se pudo conectar con Binance tras {reintentos} intentos: {ultimo_error}")


def info_simbolo(simbolo: str) -> tuple[str, str]:
    datos = pedir_json("/api/v3/exchangeInfo", {"symbol": simbolo})
    s = datos["symbols"][0]
    return s["baseAsset"], s["quoteAsset"]


def descargar_velas(simbolo: str, temporalidad: str, desde_ms: int) -> pd.DataFrame:
    """Descarga todas las velas CERRADAS con apertura >= desde_ms."""
    intervalo_ms = TEMPORALIDADES[temporalidad] * MS_POR_MINUTO
    # Hora del servidor al empezar: solo se guardan velas cerradas antes de este
    # momento, así nunca se guarda una vela a medio formar.
    hora_servidor = int(pedir_json("/api/v3/time")["serverTime"])

    filas: list[list] = []
    inicio = desde_ms
    while True:
        lote = pedir_json("/api/v3/klines", {
            "symbol": simbolo, "interval": temporalidad,
            "startTime": inicio, "limit": VELAS_POR_PETICION,
        })
        if not lote:
            break
        filas.extend(lote)
        ultima_apertura = int(lote[-1][0])
        fecha = datetime.fromtimestamp(ultima_apertura / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"\r  {temporalidad:>3}: {len(filas):>9,} velas descargadas (hasta {fecha} UTC)",
              end="", flush=True)
        if len(lote) < VELAS_POR_PETICION or ultima_apertura + intervalo_ms >= hora_servidor:
            break
        inicio = ultima_apertura + 1
        time.sleep(0.1)  # cortesía con la API
    print()

    columnas = ["apertura_ms", "apertura", "maximo", "minimo", "cierre", "volumen",
                "cierre_ms", "volumen_cotizado", "num_operaciones", "_c1", "_c2", "_c3"]
    df = pd.DataFrame(filas, columns=columnas)
    if df.empty:
        return df
    df["apertura_ms"] = df["apertura_ms"].astype("int64")
    df["cierre_ms"] = df["cierre_ms"].astype("int64") + 1  # Binance da el cierre - 1 ms
    for c in ["apertura", "maximo", "minimo", "cierre", "volumen", "volumen_cotizado"]:
        df[c] = df[c].astype(float)
    df["num_operaciones"] = df["num_operaciones"].astype("int64")
    df = df[df["cierre_ms"] <= hora_servidor]
    df = df.drop_duplicates("apertura_ms").sort_values("apertura_ms").reset_index(drop=True)
    return df[["apertura_ms", "cierre_ms"] + COLUMNAS_VELA]


# ---------------------------------------------------------------------
#  Base de datos
# ---------------------------------------------------------------------
def ruta_bd_activo(base: str) -> Path:
    """Base de datos de velas e indicadores de un activo, en su carpeta: activos/BTC/BTC.db."""
    return CARPETA_ACTIVOS / base / f"{base}.db"


def abrir_principal() -> sqlite3.Connection:
    """Base de datos principal: lista de activos, estrategias, backtests y operaciones."""
    CARPETA_RESULTADOS.mkdir(exist_ok=True)
    con = sqlite3.connect(BD_PRINCIPAL)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA_PRINCIPAL.read_text(encoding="utf-8"))
    return con


def activos_registrados(con_principal: sqlite3.Connection,
                        simbolos: list[str] | None = None) -> list[tuple[int, str, str]]:
    """(id, simbolo, base) de los activos dados de alta; solo los de `simbolos` si se indican."""
    filas = con_principal.execute("SELECT id, simbolo, base FROM activos ORDER BY id").fetchall()
    if simbolos:
        pedidos = {s.upper() for s in simbolos}
        filas = [f for f in filas if f[1] in pedidos]
    return filas


def abrir_bd_activo(con_principal: sqlite3.Connection, activo_id: int,
                    solo_lectura: bool = False) -> sqlite3.Connection | None:
    """Abre la base de datos de un activo; la crea, con su carpeta, si aún no existe.
    Con solo_lectura=True no crea nada y devuelve None si el activo todavía no tiene datos."""
    fila = con_principal.execute(
        "SELECT id, exchange, simbolo, base, cotizacion, descripcion FROM activos WHERE id = ?",
        (activo_id,)).fetchone()
    ruta = ruta_bd_activo(fila[3])
    if solo_lectura:
        if not ruta.exists():
            return None
        return sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        con.execute("INSERT OR IGNORE INTO activos (id, exchange, simbolo, base, cotizacion, descripcion) "
                    "VALUES (?, ?, ?, ?, ?, ?)", fila)
    nuevas = asegurar_columnas(con)
    if nuevas:
        print(f"Columnas nuevas añadidas a velas de {fila[2]}: {', '.join(nuevas)}. Para calcularlas en "
              f"las velas que ya estaban, ejecuta recalcular_indicadores.bat.")
    return con


def asegurar_columnas(con: sqlite3.Connection) -> list[str]:
    """Añade a `velas` las columnas de indicadores que falten (BD creada con un esquema anterior)."""
    existentes = {fila[1] for fila in con.execute("PRAGMA table_info(velas)")}
    nuevas = [c for c in COLUMNAS_INDICADORES if c not in existentes]
    with con:
        for columna in nuevas:
            con.execute(f"ALTER TABLE velas ADD COLUMN {columna} REAL")
    return nuevas


def obtener_activo(con: sqlite3.Connection, simbolo: str) -> int:
    fila = con.execute("SELECT id FROM activos WHERE exchange = ? AND simbolo = ?",
                       (EXCHANGE, simbolo)).fetchone()
    if fila:
        return fila[0]
    base, cotizacion = info_simbolo(simbolo)
    with con:
        cursor = con.execute(
            "INSERT INTO activos (exchange, simbolo, base, cotizacion, descripcion) VALUES (?, ?, ?, ?, ?)",
            (EXCHANGE, simbolo, base, cotizacion, f"{base}/{cotizacion} (spot) en {EXCHANGE}"),
        )
    print(f"Activo nuevo registrado: {simbolo} ({base}/{cotizacion}), en la carpeta {base}")
    return cursor.lastrowid


def leer_velas_guardadas(con: sqlite3.Connection, activo_id: int, temporalidad: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT fecha_hora_utc, apertura, maximo, minimo, cierre, volumen FROM velas "
        "WHERE activo_id = ? AND temporalidad = ? ORDER BY fecha_hora_utc",
        con, params=(activo_id, temporalidad),
    )
    df["apertura_ms"] = texto_a_ms(df["fecha_hora_utc"])
    return df.drop(columns="fecha_hora_utc")


def _a_lista_sql(serie: pd.Series) -> list:
    """Convierte una columna a valores de Python, con NaN -> None (NULL)."""
    return [None if v != v else v for v in serie.tolist()]  # v != v solo es cierto para NaN


def insertar_velas(con: sqlite3.Connection, df: pd.DataFrame) -> None:
    columnas = [_a_lista_sql(df[c]) for c in COLUMNAS_INSERCION]
    sql = (f"INSERT OR IGNORE INTO velas ({', '.join(COLUMNAS_INSERCION)}) "
           f"VALUES ({', '.join('?' * len(COLUMNAS_INSERCION))})")
    with con:
        con.executemany(sql, zip(*columnas))


# ---------------------------------------------------------------------
#  Proceso principal
# ---------------------------------------------------------------------
def cargar_temporalidad(con: sqlite3.Connection, activo_id: int, simbolo: str,
                        temporalidad: str, desde_ms: int) -> int:
    intervalo_ms = TEMPORALIDADES[temporalidad] * MS_POR_MINUTO
    ultima = con.execute(
        "SELECT MAX(fecha_hora_utc) FROM velas WHERE activo_id = ? AND temporalidad = ?",
        (activo_id, temporalidad),
    ).fetchone()[0]
    ultima_ms = int(texto_a_ms(pd.Series([ultima])).iloc[0]) if ultima else None

    nuevas = descargar_velas(simbolo, temporalidad,
                             ultima_ms + intervalo_ms if ultima_ms is not None else desde_ms)
    if nuevas.empty:
        print(f"  {temporalidad:>3}: ya estaba al día.")
        return 0

    # Los indicadores necesitan el historial previo: se recalculan sobre la serie
    # completa (guardada + nueva) y solo se insertan las velas nuevas.
    if ultima_ms is not None:
        guardadas = leer_velas_guardadas(con, activo_id, temporalidad)
        serie = pd.concat([guardadas, nuevas], ignore_index=True)
    else:
        serie = nuevas
    serie = serie.sort_values("apertura_ms").reset_index(drop=True)
    serie = pd.concat([serie, calcular_indicadores(serie, temporalidad)], axis=1)

    a_insertar = serie[serie["apertura_ms"] > (ultima_ms if ultima_ms is not None else -1)].copy()
    a_insertar["cierre_ms"] = a_insertar["cierre_ms"].astype("int64")
    a_insertar["num_operaciones"] = a_insertar["num_operaciones"].astype("int64")
    a_insertar["activo_id"] = activo_id
    a_insertar["temporalidad"] = temporalidad
    a_insertar["fecha_hora_utc"] = ms_a_texto(a_insertar["apertura_ms"])
    a_insertar["fecha_cierre_utc"] = ms_a_texto(a_insertar["cierre_ms"])
    insertar_velas(con, a_insertar)

    with con:
        con.execute(
            "INSERT INTO cargas (activo_id, temporalidad, fecha_carga_utc, primera_vela_utc, "
            "ultima_vela_utc, velas_insertadas) VALUES (?, ?, ?, ?, ?, ?)",
            (activo_id, temporalidad, ahora_texto(), a_insertar["fecha_hora_utc"].iloc[0],
             a_insertar["fecha_hora_utc"].iloc[-1], len(a_insertar)),
        )
    print(f"  {temporalidad:>3}: {len(a_insertar):,} velas nuevas guardadas "
          f"({a_insertar['fecha_hora_utc'].iloc[0]} -> {a_insertar['fecha_hora_utc'].iloc[-1]} UTC)")
    return len(a_insertar)


def resumen(con: sqlite3.Connection, activo_id: int, simbolo: str, temporalidades: list[str]) -> None:
    print(f"\nResumen de {simbolo} en la base de datos:")
    print(f"  {'temp.':>5} {'velas':>10}  {'primera vela':19}  {'última vela':19}  huecos")
    for tf in temporalidades:
        fechas = pd.read_sql_query(
            "SELECT fecha_hora_utc FROM velas WHERE activo_id = ? AND temporalidad = ? "
            "ORDER BY fecha_hora_utc", con, params=(activo_id, tf))["fecha_hora_utc"]
        if fechas.empty:
            print(f"  {tf:>5} {0:>10}")
            continue
        saltos = texto_a_ms(fechas).diff().dropna()
        huecos = int((saltos > TEMPORALIDADES[tf] * MS_POR_MINUTO).sum())
        print(f"  {tf:>5} {len(fechas):>10,}  {fechas.iloc[0]}  {fechas.iloc[-1]}  {huecos}")
    print("  (huecos = saltos en la serie, normalmente paradas de mantenimiento de Binance)")


def leer_activos(ruta: Path | None = None) -> list[str]:
    """Lee activos.txt: un par de Binance por línea; lo que va tras '#' es comentario."""
    ruta = ruta or ARCHIVO_ACTIVOS
    if not ruta.exists():
        return ["BTCUSDT"]
    simbolos: list[str] = []
    for linea in ruta.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        simbolo = linea.split("#", 1)[0].strip().upper()
        if simbolo and simbolo not in simbolos:
            simbolos.append(simbolo)
    return simbolos


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga el histórico de velas de Binance con sus indicadores.")
    parser.add_argument("--simbolo", "--simbolos", dest="simbolos", nargs="+",
                        help="pares de Binance, p. ej. AVAXUSDT; por defecto, los de activos.txt")
    parser.add_argument("--temporalidades", nargs="+", default=list(TEMPORALIDADES),
                        choices=list(TEMPORALIDADES), help="por defecto, todas")
    parser.add_argument("--desde", help="fecha inicial AAAA-MM-DD (solo si aún no hay datos); por defecto, todo el histórico")
    args = parser.parse_args()

    simbolos = [s.upper() for s in args.simbolos] if args.simbolos else leer_activos()
    desde_ms = 0
    if args.desde:
        desde_ms = int(datetime.strptime(args.desde, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    print(f"Activos: {', '.join(simbolos)}")
    inicio = time.time()
    total = 0
    fallidos: list[str] = []
    con_principal = abrir_principal()
    try:
        for simbolo in simbolos:
            print(f"\n=== {simbolo} ===")
            try:
                activo_id = obtener_activo(con_principal, simbolo)
                con = abrir_bd_activo(con_principal, activo_id)
            except SystemExit as error:  # error de Binance con este activo: se sigue con el resto
                print(f"\nERROR con {simbolo}: {error}")
                fallidos.append(simbolo)
                continue
            ruta_bd = Path(con.execute("PRAGMA database_list").fetchone()[2])
            try:
                print(f"Base de datos: {ruta_bd}")
                print(f"Descargando {simbolo} de {EXCHANGE}: {', '.join(args.temporalidades)}")
                for tf in args.temporalidades:
                    total += cargar_temporalidad(con, activo_id, simbolo, tf, desde_ms)
                resumen(con, activo_id, simbolo, args.temporalidades)
            except SystemExit as error:
                print(f"\nERROR con {simbolo}: {error}")
                fallidos.append(simbolo)
            finally:
                con.close()
            print(f"Tamaño de {ruta_bd.name}: {ruta_bd.stat().st_size / 1_048_576:,.0f} MB")
    finally:
        con_principal.close()
    print(f"\nListo: {total:,} velas nuevas en {time.time() - inicio:,.0f} s.")
    if fallidos:
        sys.exit(f"No se pudieron cargar: {', '.join(fallidos)}. Vuelve a ejecutar para reintentarlo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido. Lo ya guardado se conserva; vuelve a ejecutar para continuar.")
