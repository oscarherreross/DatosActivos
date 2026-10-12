"""
DatosActivos - dashboard para comparar estrategias.

Se marcan las estrategias y el gráfico muestra al momento cómo habría
evolucionado el capital de cada una con todo el histórico del activo, junto
a comprar y mantener, con un único capital inicial o añadiendo además una
aportación cada mes. Usa el mismo motor que backtesting.py (simular y
metricas) y las funciones de estrategias.py. Solo lee las bases de datos:
no guarda nada en ellas.

Uso (desde la carpeta DatosActivos):
    streamlit run codigo/dashboard.py        # o doble clic en dashboard.bat

Para añadir una estrategia a las casillas:
  1. Escribe su función en estrategias.py y regístrala en FUNCIONES.
  2. Añádela a CATALOGO con su título en TITULOS.
  3. Si tiene parámetros que se quieran cambiar desde la pantalla, añade sus
     controles en pedir_parametros y su nombre en nombre_estrategia.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import indicadores
from backtesting import DIRECCIONES, NOTA_CORTOS, TEMPORALIDADES, leer_velas, metricas, simular
from cargar_datos import BD_PRINCIPAL, ruta_bd_activo
from estrategias import FUNCIONES

# Casillas del dashboard: función de estrategias.py (FUNCIONES), parámetros con los que
# aparece y si sale marcada al abrir.
CATALOGO = [
    {"codigo": "cruce_medias", "parametros": {"tipo": "ema", "rapida": 20, "lenta": 50}, "marcada": True},
    {"codigo": "cruce_medias", "parametros": {"tipo": "ema", "rapida": 50, "lenta": 200}, "marcada": False},
    {"codigo": "rsi_extremos", "parametros": {"sobreventa": 30, "sobrecompra": 70}, "marcada": True},
    {"codigo": "cruce_macd", "parametros": {}, "marcada": True},
    {"codigo": "rebote_bollinger", "parametros": {}, "marcada": True},
]
TITULOS = {"cruce_medias": "Cruce de medias", "rsi_extremos": "RSI: salida de extremos",
           "cruce_macd": "Cruce del MACD", "rebote_bollinger": "Rebote en Bollinger"}

# Un color fijo por casilla, en el orden de CATALOGO. Comprar y mantener va en gris.
COLORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
COLOR_REFERENCIA = "#898781"

ETIQUETAS_DIRECCION = {"largos_y_cortos": "Largos y cortos", "solo_largos": "Solo largos",
                       "solo_cortos": "Solo cortos"}
MAX_PUNTOS = 4000   # puntos que se dibujan por curva; las métricas usan todas las velas


# ---------------------------------------------------------------------
#  Datos
# ---------------------------------------------------------------------
def activos_con_datos() -> list[tuple[int, str, str]]:
    """(id, simbolo, base) de los activos registrados que ya tienen su base de datos de velas."""
    if not BD_PRINCIPAL.exists():
        return []
    con = sqlite3.connect(f"file:{BD_PRINCIPAL.as_posix()}?mode=ro", uri=True)
    filas = con.execute("SELECT id, simbolo, base FROM activos ORDER BY id").fetchall()
    con.close()
    return [f for f in filas if ruta_bd_activo(f[2]).exists()]


@st.cache_resource(max_entries=3, show_spinner="Leyendo las velas...")
def cargar_velas(base: str, activo_id: int, temporalidad: str, modificada: float) -> pd.DataFrame:
    """Velas de un activo en una temporalidad, con sus indicadores. `modificada` (fecha del
    archivo) hace que se vuelvan a leer después de una carga nueva. El resultado se comparte
    entre ejecuciones: no hay que modificarlo."""
    con = sqlite3.connect(f"file:{ruta_bd_activo(base).as_posix()}?mode=ro", uri=True)
    try:
        return leer_velas(con, activo_id, temporalidad, None, None)
    finally:
        con.close()


# ---------------------------------------------------------------------
#  Estrategias
# ---------------------------------------------------------------------
def nombre_estrategia(codigo: str, p: dict) -> str:
    """Nombre con el que aparece en el gráfico y en la tabla."""
    if codigo == "cruce_medias":
        return f"Cruce {p['tipo'].upper()} {p['rapida']}/{p['lenta']}"
    if codigo == "rsi_extremos":
        return f"RSI {p['sobreventa']}/{p['sobrecompra']}"
    return {"cruce_macd": "Cruce MACD/señal", "rebote_bollinger": "Rebote Bollinger 20/2"}.get(codigo, codigo)


def pedir_parametros(i: int, codigo: str, p: dict) -> dict:
    """Controles para cambiar los parámetros de la casilla i; devuelve los elegidos."""
    if codigo == "cruce_medias":
        tipo = st.radio("Tipo de media", ["ema", "sma"], index=["ema", "sma"].index(p["tipo"]),
                        format_func=str.upper, horizontal=True, key=f"tipo_{i}")
        rapida = st.number_input("Media rápida (velas)", 2, 500, p["rapida"], key=f"rapida_{i}")
        lenta = st.number_input("Media lenta (velas)", 3, 1000, p["lenta"], key=f"lenta_{i}")
        return {"tipo": tipo, "rapida": int(rapida), "lenta": int(lenta)}
    if codigo == "rsi_extremos":
        sobreventa = st.slider("Sobreventa: entra al subir de", 5, 45, p["sobreventa"], key=f"sobreventa_{i}")
        sobrecompra = st.slider("Sobrecompra: sale al llegar a", 55, 95, p["sobrecompra"], key=f"sobrecompra_{i}")
        return {"sobreventa": sobreventa, "sobrecompra": sobrecompra}
    return p


def preparar(velas: pd.DataFrame, codigo: str, p: dict) -> tuple[pd.DataFrame, dict]:
    """Deja las velas y los parámetros como los espera la función de estrategias.py. Las medias
    que no están guardadas en la base de datos se calculan aquí, con todo el histórico."""
    if codigo != "cruce_medias":
        return velas, p
    columnas = {n: f"{p['tipo']}_{n}" for n in (p["rapida"], p["lenta"])}
    nuevas = {col: getattr(indicadores, p["tipo"])(velas["cierre"], n)
              for n, col in columnas.items() if col not in velas.columns}
    return velas.assign(**nuevas), {"media_rapida": columnas[p["rapida"]], "media_lenta": columnas[p["lenta"]]}


def puntos_a_dibujar(n: int) -> np.ndarray:
    """Índices de las velas que se dibujan: todas si caben; si no, MAX_PUNTOS repartidas por
    igual, siempre con la primera y la última."""
    if n <= MAX_PUNTOS:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, MAX_PUNTOS).round().astype(int))


@st.cache_data(max_entries=300, show_spinner=False)
def calcular(_velas: pd.DataFrame, clave_velas: tuple, i0: int, i1: int, codigo: str, parametros: dict,
             direccion: str, comision: float, capital: float) -> dict:
    """Simula una estrategia en las velas i0..i1 con un único capital inicial. Devuelve:
      valores       su curva de capital, solo en los puntos que se dibujan
      metricas      las de backtesting.metricas
      aportaciones  lo que compraría cada aportación mensual (ver participaciones)
      sin_mejores   lo mismo, si no hubiera hecho el 5 % de las operaciones con mejor resultado;
                    None si no hay operaciones
    _velas no cuenta para la caché: la identifica clave_velas."""
    v, p = preparar(_velas, codigo, parametros)
    v = v.iloc[i0:i1]
    ops, curva = simular(v, FUNCIONES[codigo](v, p), direccion, comision, capital)
    cambios, f = cambios_de_mes(v), comision / 100
    return {"valores": curva["valores"][puntos_a_dibujar(len(v))], "metricas": metricas(ops, curva, capital),
            "aportaciones": participaciones(curva["valores"], curva["posiciones"], cambios, f),
            "sin_mejores": participaciones(*sin_mejores(v, ops, curva), cambios, f) if ops else None}


def sin_mejores(v: pd.DataFrame, ops: list[dict], curva: dict) -> tuple[np.ndarray, np.ndarray]:
    """Curva de capital y posiciones que habría habido si la estrategia se hubiera quedado fuera
    del mercado en el 5 % de las operaciones con mejor resultado (como mínimo una): las mismas que
    quita metricas para calcular rentabilidad_sin_mejores_5pct_pct."""
    r = np.array([o["rentabilidad_pct"] for o in ops])
    quitadas = [ops[i] for i in np.sort(np.argsort(r, kind="stable")[::-1][:max(1, math.ceil(0.05 * len(r)))])]
    # Cada operación va de la apertura de la vela `entradas` a la de la vela `salidas`
    aperturas = v["fecha_hora_utc"].to_numpy()
    entradas = np.searchsorted(aperturas, [o["fecha_entrada_utc"] for o in quitadas])
    salidas = np.searchsorted(aperturas, [o["fecha_salida_utc"] for o in quitadas])
    antes = np.array([o["capital_entrada"] for o in quitadas])
    despues = np.array([o["capital_salida"] for o in quitadas])

    # Desde que acaba una operación quitada, el capital es el que había antes de entrar en ella
    n = len(aperturas)
    acabada = despues > 0            # la que agota el capital es la última: después no hay nada
    factor = np.ones(n + 1)
    factor[salidas[acabada]] = antes[acabada] / despues[acabada]
    escala = np.cumprod(factor)[:n]
    valores, posiciones = curva["valores"] * escala, curva["posiciones"].copy()
    for entrada, salida, previo, sigue in zip(entradas, salidas, antes, acabada):
        fin = salida if sigue else n
        valores[entrada:fin] = escala[entrada] * previo
        posiciones[entrada:fin] = 0
    return valores, posiciones


# ---------------------------------------------------------------------
#  Aportaciones mensuales
# ---------------------------------------------------------------------
def cambios_de_mes(velas: pd.DataFrame) -> np.ndarray:
    """Índices de la primera vela de cada mes, sin contar la primera de la serie. En la apertura
    de cada una entra una aportación."""
    mes = velas["fecha_hora_utc"].str[:7].to_numpy()
    return np.flatnonzero(mes[1:] != mes[:-1]) + 1


def participaciones(valores: np.ndarray, posiciones: np.ndarray, cambios: np.ndarray,
                    f: float) -> tuple[np.ndarray, np.ndarray]:
    """Lo que compra cada USDT aportado en las velas de `cambios`. La curva de un único capital
    inicial (`valores`) hace de precio de una participación en la estrategia:
      * si la estrategia está fuera, o entra en esa misma apertura, la aportación se suma a la
        liquidez y entra con el resto;
      * si sigue dentro, compra más al cierre de la vela anterior, pagando comisión.
    Devuelve, acumulados tras 0, 1, 2... aportaciones, las participaciones compradas por USDT y
    las aportaciones que se quedan sin invertir porque la estrategia ya había agotado el capital."""
    antes = cambios - 1
    sigue = (posiciones[cambios] != 0) & (posiciones[cambios] == posiciones[antes])
    precio = np.where(posiciones[cambios] == 0, valores[cambios], valores[antes])
    viva = precio > 0
    compradas = np.where(viva, np.where(sigue, 1 - f, 1.0) / np.where(viva, precio, 1.0), 0.0)
    return np.concatenate([[0.0], np.cumsum(compradas)]), np.concatenate([[0.0], np.cumsum(~viva)])


def con_aportaciones(capital, aportacion: float, compradas: np.ndarray, sin_invertir: np.ndarray, hechas):
    """Capital que habría en vez de `capital` (el de un único capital inicial) después de `hechas`
    aportaciones mensuales. Vale para un punto o para toda la curva."""
    return capital * (1 + aportacion * compradas[hechas]) + aportacion * sin_invertir[hechas]


# ---------------------------------------------------------------------
#  Presentación
# ---------------------------------------------------------------------
def miles(x: float) -> str:
    """12345.6 -> '12.346'."""
    return f"{x:,.0f}".replace(",", ".")


def numero(x: float, decimales: int = 0) -> str:
    """Número como los escribe la tabla en un navegador en español: 7034, 35.940, 259,4."""
    texto = f"{x:,.{decimales}f}" if abs(x) >= 10_000 else f"{x:.{decimales}f}"
    return texto.translate(str.maketrans(",.", ".,"))


def fecha_corta(texto: str) -> str:
    """'2017-08-17 00:00:00' -> '17/08/2017'."""
    return f"{texto[8:10]}/{texto[5:7]}/{texto[:4]}"


def marcas_log(minimo: float, maximo: float) -> tuple[list[float], list[str]]:
    """Marcas del eje logarítmico entre el mínimo y el máximo: 1, 2 y 5 de cada potencia de 10
    (solo las potencias de 10 si el rango es muy amplio)."""
    e0, e1 = int(np.floor(np.log10(minimo))), int(np.ceil(np.log10(maximo)))
    marcas = [m * 10.0 ** e for e in range(e0, e1 + 1) for m in ((1, 2, 5) if e1 - e0 <= 3 else (1,))]
    return marcas, [miles(t) if t >= 1 else f"{t:g}".replace(".", ",") for t in marcas]


def main() -> None:
    st.set_page_config(page_title="DatosActivos - estrategias", layout="wide")
    activos = activos_con_datos()
    if not activos:
        st.error("No hay datos todavía: ejecuta antes cargar_datos.bat.")
        st.stop()

    with st.sidebar:
        st.header("Condiciones")
        activo_id, simbolo, base = st.selectbox("Activo", activos, format_func=lambda a: a[1])
        temporalidad = st.selectbox("Temporalidad", TEMPORALIDADES, index=TEMPORALIDADES.index("1d"))
        direccion = st.selectbox("Dirección", DIRECCIONES, index=DIRECCIONES.index("solo_largos"),
                                 format_func=ETIQUETAS_DIRECCION.get)
        c1, c2 = st.columns(2)
        desde = c1.date_input("Desde", value=None, min_value=date(2017, 1, 1), max_value=date.today(),
                              format="DD/MM/YYYY", help="Vacío: desde la primera vela.")
        hasta = c2.date_input("Hasta", value=None, min_value=date(2017, 1, 1), max_value=date.today(),
                              format="DD/MM/YYYY", help="Vacío: hasta la última vela.")
        comision = st.number_input("Comisión por compra y por venta (%)", 0.0, 5.0, 0.1, step=0.05, format="%.2f")
        capital = st.number_input("Capital inicial (USDT)", 100.0, value=10_000.0, step=1_000.0, format="%.0f")
        aportacion = st.number_input("Aportación mensual (USDT)", 0.0, value=0.0, step=100.0, format="%.0f",
                                     help="Se añade en la apertura de la primera vela de cada mes. "
                                          "Con 0 solo se invierte el capital inicial.")
        logaritmica = st.toggle("Escala logarítmica", value=True,
                                help="Hace que una subida del 10 % mida lo mismo en cualquier punto del gráfico.")

    # Velas del periodo elegido, con el mismo criterio que --desde y --hasta en backtesting.py
    modificada = ruta_bd_activo(base).stat().st_mtime
    velas = cargar_velas(base, activo_id, temporalidad, modificada)
    i0 = int(velas["fecha_hora_utc"].searchsorted(desde.isoformat())) if desde else 0
    i1 = (int(velas["fecha_cierre_utc"].searchsorted(f"{hasta.isoformat()} 23:59:59", side="right"))
          if hasta else len(velas))
    tramo = velas.iloc[i0:i1]

    st.title(f"{simbolo} · {temporalidad}")
    if len(tramo) < 2:
        st.warning("No hay velas en ese periodo.")
        st.stop()
    cambios = cambios_de_mes(tramo)
    aportado = capital + aportacion * len(cambios)
    comision_texto = f"{comision:g}".replace(".", ",")
    st.caption(f"{miles(len(tramo))} velas, del {fecha_corta(tramo['fecha_hora_utc'].iloc[0])} al "
               f"{fecha_corta(tramo['fecha_cierre_utc'].iloc[-1])} · {ETIQUETAS_DIRECCION[direccion].lower()} · "
               f"comisión {comision_texto} % · capital inicial {miles(capital)} USDT"
               + (f" · {len(cambios)} aportaciones de {miles(aportacion)} USDT · {miles(aportado)} USDT aportados"
                  if aportacion else ""))

    # Casillas de las estrategias
    elegidas: dict[str, tuple[int, str, dict]] = {}
    for i, (columna, e) in enumerate(zip(st.columns(len(CATALOGO)), CATALOGO)):
        with columna:
            marcada = st.checkbox(TITULOS[e["codigo"]], value=e["marcada"], key=f"marcada_{i}")
            etiqueta = st.empty()   # el nombre va antes que los parámetros, pero depende de ellos
            p = e["parametros"]
            if p:
                with st.popover("Parámetros"):
                    p = pedir_parametros(i, e["codigo"], p)
            nombre = nombre_estrategia(e["codigo"], p)
            etiqueta.markdown(f"<span style='color:{COLORES[i % len(COLORES)]}'>&#9632;</span> {nombre}",
                              unsafe_allow_html=True)
            if e["codigo"] == "cruce_medias" and p["rapida"] >= p["lenta"]:
                st.warning("La media rápida tiene que ser más corta que la lenta.")
            elif marcada:
                elegidas.setdefault(nombre, (i, e["codigo"], p))   # la misma dos veces se dibuja una

    f = comision / 100
    idx = puntos_a_dibujar(len(tramo))
    fechas = pd.to_datetime(tramo["fecha_cierre_utc"].iloc[idx])
    hechas = np.searchsorted(cambios, idx, side="right")   # aportaciones hechas hasta cada punto dibujado
    fig = go.Figure()
    dibujado = []
    if aportacion:
        dibujado.append(capital + aportacion * hechas)
        fig.add_scatter(x=fechas, y=dibujado[-1], name="Aportado", mode="lines", hovertemplate="%{y:,.0f} USDT",
                        line=dict(color=COLOR_REFERENCIA, width=1, dash="dot", shape="hv"))
    else:
        fig.add_hline(y=capital, line_width=1, line_dash="dot", line_color=COLOR_REFERENCIA)

    # Comprar y mantener: compra en la primera apertura (y con cada aportación) y vende en el
    # último cierre, con comisiones
    referencia = capital * (1 - f) * tramo["cierre"].to_numpy(float) / float(tramo["apertura"].iloc[0])
    compradas, sin_invertir = participaciones(referencia, np.ones(len(tramo), dtype=np.int8), cambios, f)
    final = con_aportaciones(referencia[-1] * (1 - f), aportacion, compradas, sin_invertir, len(cambios))
    filas = [{"Estrategia": "Comprar y mantener", "Total aportado": aportado,
              "Capital final": final, "Rentabilidad %": (final / aportado - 1) * 100,
              "Máx. caída %": float(((1 - referencia / np.maximum.accumulate(referencia)) * 100).max()),
              "Operaciones": 1, "En mercado %": 100.0}]
    dibujado.append(con_aportaciones(referencia[idx], aportacion, compradas, sin_invertir, hechas))
    fig.add_scatter(x=fechas, y=dibujado[-1], name="Comprar y mantener", mode="lines",
                    line=dict(color=COLOR_REFERENCIA, width=2, dash="dash"), hovertemplate="%{y:,.0f} USDT")

    clave_velas = (base, temporalidad, modificada)
    for nombre, (i, codigo, p) in elegidas.items():
        with st.spinner(f"Simulando {nombre}..."):
            r = calcular(velas, clave_velas, i0, i1, codigo, p, direccion, comision, capital)
        m = r["metricas"]
        final = con_aportaciones(m["capital_final"], aportacion, *r["aportaciones"], len(cambios))
        dibujado.append(con_aportaciones(r["valores"], aportacion, *r["aportaciones"], hechas))
        sin_mejor = None
        if r["sin_mejores"]:
            sin_mejor = con_aportaciones(capital * (1 + m["rentabilidad_sin_mejores_5pct_pct"] / 100),
                                         aportacion, *r["sin_mejores"], len(cambios))
            sin_mejor = f"{numero(sin_mejor)} USDT ({numero((sin_mejor / aportado - 1) * 100, 1)} %)"
        fig.add_scatter(x=fechas, y=dibujado[-1], name=nombre, mode="lines",
                        line=dict(color=COLORES[i % len(COLORES)], width=2), hovertemplate="%{y:,.0f} USDT")
        filas.append({"Estrategia": nombre, "Total aportado": aportado,
                      "Capital final": final, "Rentabilidad %": (final / aportado - 1) * 100,
                      "Máx. caída %": m["max_drawdown_pct"],
                      "Operaciones": m["num_operaciones"], "Acierto %": m["pct_acierto"],
                      "Profit factor": m["profit_factor"],
                      "Sin el 5 % mejor": sin_mejor,
                      "En mercado %": m["tiempo_en_mercado_pct"]})

    eje_y: dict = {"title": "Capital (USDT)", "tickformat": ",.0f"}
    if logaritmica:
        # El eje no baja de una milésima del capital inicial: una estrategia que lo pierde casi
        # todo se sale por abajo en vez de aplastar las demás curvas.
        todo = np.concatenate(dibujado)
        minimo = max(todo[todo > 0].min(), capital / 1000)
        marcas, textos = marcas_log(minimo, todo.max())
        eje_y.update(type="log", tickvals=marcas, ticktext=textos,
                     range=[np.log10(minimo * 0.85), np.log10(todo.max() * 1.15)])
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=40, b=0), hovermode="x unified", separators=",.",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), yaxis=eje_y,
                      xaxis=dict(hoverformat="%d/%m/%Y" if temporalidad in ("1d", "1w") else "%d/%m/%Y %H:%M"))
    st.plotly_chart(fig, config={"displaylogo": False})
    if len(tramo) > MAX_PUNTOS:
        st.caption(f"El gráfico dibuja {miles(len(idx))} de las {miles(len(tramo))} velas, repartidas por igual. "
                   "Las cifras de la tabla se calculan con todas.")

    # Columnas de la tabla: decimales y explicación, que sale al pasar por la cabecera y en la
    # lista de debajo de la tabla. Los números se escriben como en el navegador.
    columnas = {
        "Estrategia": (None, "Estrategia marcada, con sus parámetros. Comprar y mantener es la referencia: compra "
                             "al principio y con cada aportación, y no vende hasta el final."),
        "Total aportado": (0, "Dinero puesto en total, en USDT: el capital inicial más todas las aportaciones "
                              "mensuales del periodo. Es el mismo en todas las filas."),
        "Capital final": (0, "Lo que habría al final del periodo, en USDT, con las comisiones descontadas y la "
                             "posición que siga abierta cerrada al último precio."),
        "Rentabilidad %": (1, "Ganancia o pérdida sobre el total aportado: capital final entre total aportado, "
                              "menos 1."),
        "Sin el 5 % mejor": (None, "Capital final, y entre paréntesis su rentabilidad sobre el total aportado, si la "
                                   "estrategia se hubiera quedado fuera del mercado en el 5 % de las operaciones con "
                                   "mejor resultado (como mínimo, una). Si queda por debajo del total aportado, el "
                                   "resultado depende de unas pocas operaciones y la estrategia es frágil."),
        "Máx. caída %": (1, "Mayor caída del capital desde un máximo anterior, con precios de cierre y sin contar "
                            "las aportaciones."),
        "Operaciones": (0, "Veces que la estrategia entra en el mercado."),
        "Acierto %": (1, "Porcentaje de operaciones que acaban en ganancia, con las comisiones descontadas."),
        "Profit factor": (2, "Suma de las ganancias entre suma de las pérdidas, en USDT. Por encima de 1 gana más "
                             "de lo que pierde."),
        "En mercado %": (1, "Porcentaje de velas con una posición abierta."),
    }
    tabla = pd.DataFrame(filas, columns=list(columnas))
    tabla = tabla.round({c: dec for c, (dec, _) in columnas.items() if dec is not None})
    st.dataframe(tabla, hide_index=True, placeholder="-", column_config={
        c: (st.column_config.TextColumn(help=texto) if dec is None
            else st.column_config.NumberColumn(format="localized", help=texto))
        for c, (dec, texto) in columnas.items()})
    st.markdown("**Qué representa cada columna**\n\n"
                + "\n".join(f"- **{c}**: {texto}" for c, (_, texto) in columnas.items())
                + "\n\nDe la caída máxima en adelante, las columnas describen la estrategia con un único capital "
                  "inicial: las aportaciones mensuales solo cambian las columnas anteriores.")
    st.caption("La señal se calcula al cierre de una vela y la orden se ejecuta en la apertura de la siguiente. "
               "Cada entrada usa todo el capital. " + (NOTA_CORTOS if direccion != "solo_largos" else ""))
    if aportacion:
        st.caption("Cada aportación entra en la apertura de la primera vela del mes: si la estrategia está dentro "
                   "del mercado compra más en ese momento, con comisión; si está fuera, espera en liquidez hasta la "
                   "siguiente entrada.")


if __name__ == "__main__":
    main()
