# DatosActivos

Histórico de velas de varios criptoactivos de Binance en 6 temporalidades (5m, 15m, 1h, 4h,
1d y 1w), en bases de datos SQLite. Ahora tiene datos de **BTC, AVAX, LINK y NEAR**, todos
contra USDT, y carpetas preparadas para **ETH, ONDO y XRP**. Cada vela guarda, además del
precio y el volumen, el valor que tenían los indicadores técnicos **al cierre de esa vela**.

## Organización de la carpeta

```
DatosActivos/
├── cargar_datos.bat            doble clic: descarga o amplía las velas
├── recalcular_indicadores.bat  doble clic: recalcula los indicadores
├── ejecutar_backtests.bat      doble clic: prueba las estrategias
├── dashboard.bat               doble clic: compara estrategias en un gráfico
├── README.md
├── activos/
│   ├── activos.txt                lista de activos que se cargan
│   ├── COMO_AÑADIR_UN_ACTIVO.txt  pasos para añadir uno nuevo
│   ├── BTC/BTC.db                 velas e indicadores de BTC
│   ├── ETH/ETH.db                 (se crea con la primera carga)
│   └── AVAX/  LINK/  NEAR/  ONDO/  XRP/
├── codigo/                     scripts de Python (.py) y esquemas (.sql)
└── resultados/
    ├── backtests.db            lista de activos, estrategias, backtests y operaciones
    └── estudio_tendencias/     resultados del estudio de tendencias (CSV)
```

Lo que es de un solo activo (sus velas y sus indicadores) está en su carpeta dentro de
`activos/`. Lo que mezcla varios activos está en `resultados/`. En la raíz solo quedan los
cuatro .bat que se usan con doble clic.

**Para añadir un activo** basta con escribir su par en `activos/activos.txt` y ejecutar
`cargar_datos.bat`; su carpeta se crea sola. Los pasos están en
`activos/COMO_AÑADIR_UN_ACTIVO.txt`.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `cargar_datos.bat` | Doble clic para descargar o ampliar las velas de los activos |
| `recalcular_indicadores.bat` | Doble clic para recalcular los indicadores de las velas ya guardadas (p. ej. tras añadir uno nuevo) |
| `ejecutar_backtests.bat` | Doble clic para probar las estrategias y guardar los resultados |
| `dashboard.bat` | Doble clic para abrir el dashboard que compara estrategias en un gráfico |
| `activos/activos.txt` | Lista de activos que se cargan (un par de Binance por línea) |
| `activos/BTC/BTC.db`, `activos/AVAX/AVAX.db`... | Base de datos de cada activo; se crean la primera vez que se carga ese activo |
| `resultados/backtests.db` | Base de datos principal: activos, estrategias, backtests y operaciones |
| `resultados/estudio_tendencias/` | Resultados del estudio de tendencias |
| `codigo/cargar_datos.py` | Descarga las velas de Binance, calcula los indicadores y los guarda |
| `codigo/indicadores.py` | Fórmulas de los indicadores (las mismas que usa TradingView) |
| `codigo/recalcular_indicadores.py` | Lo que ejecuta `recalcular_indicadores.bat` |
| `codigo/backtesting.py` | Motor de backtesting: simula las estrategias sobre las velas guardadas |
| `codigo/estrategias.py` | Definición de las estrategias y sus parámetros |
| `codigo/dashboard.py` | Lo que abre `dashboard.bat`: casillas de estrategias, gráfico del capital y tabla de métricas |
| `codigo/estudio_tendencias.py` | Estudio de qué situaciones de los indicadores precedieron a subidas |
| `codigo/esquema.sql` | Estructura de la base de datos de cada activo |
| `codigo/esquema_backtesting.sql` | Estructura de `backtests.db` |

## Cómo cargar los datos

1. Necesitas Python 3.9 o posterior. Si no lo tienes, instálalo desde
   <https://www.python.org/downloads/> y marca **"Add python.exe to PATH"** durante la instalación.
2. Haz doble clic en **`cargar_datos.bat`**. Instala pandas si hace falta y, para cada activo
   de `activos/activos.txt`, descarga todo su histórico: desde que empezó a cotizar en Binance hasta la
   última vela cerrada. Cada activo se guarda en su carpeta (`activos/BTC/BTC.db`...), que se crea sola.
   - Cada activo tarda unos 5–15 minutos, según los años de historia que tenga. BTC, que empieza
     en 2017, ocupa unos 400 MB.
   - No necesitas cuenta ni clave de Binance: se usa su API pública de datos.
3. Si lo vuelves a ejecutar más adelante, solo añade las velas cerradas desde la última guardada.
   Lo que ya estaba no se modifica. Así todos los activos quedan actualizados hasta el mismo momento.

También se puede ejecutar desde una consola en la carpeta DatosActivos:

```
python codigo/cargar_datos.py                              # todos los activos de activos.txt
python codigo/cargar_datos.py --simbolo ETHUSDT            # solo un activo concreto
python codigo/cargar_datos.py --simbolo LINKUSDT NEARUSDT  # varios concretos
python codigo/cargar_datos.py --temporalidades 1h 4h       # solo algunas temporalidades
python codigo/cargar_datos.py --desde 2020-01-01           # empezar en una fecha (solo en la primera carga)
```

Para ver los datos sin programar puedes usar **DB Browser for SQLite** (gratuito) o DBeaver. En
DBeaver crea una conexión SQLite por cada archivo que quieras ver: `activos/BTC/BTC.db` para las velas de
BTC, `resultados/backtests.db` para los resultados de los backtests, etc. Para consultar varios a la vez
desde una misma conexión puedes adjuntarlos con `ATTACH`, por ejemplo
`ATTACH 'C:\Users\Oscar\Desktop\DatosActivos\ETH\ETH.db' AS eth;` y luego `SELECT ... FROM eth.velas`.

## Estructura

Base de datos de cada activo (`activos/BTC/BTC.db`, `activos/ETH/ETH.db`...):

| Tabla | Contenido |
|---|---|
| `activos` | Una sola fila: el activo de esa carpeta (con el mismo `id` que en `backtests.db`) |
| `temporalidades` | 5m, 15m, 1h, 4h, 1d, 1w y su duración en minutos |
| `velas` | Una fila por temporalidad y vela, con precios, volumen e indicadores |
| `cargas` | Registro de cada ejecución: cuándo se hizo y qué velas añadió |
| `v_velas` (vista) | `velas` con el símbolo del activo, para consultar más cómodamente |

Base de datos principal (`resultados/backtests.db`):

| Tabla | Contenido |
|---|---|
| `activos` | Un activo por fila (exchange, símbolo, moneda base y de cotización). La moneda base es el nombre de su carpeta |
| `temporalidades` | Las mismas 6 temporalidades |
| `estrategias` | Cada estrategia: nombre, descripción y parámetros (JSON) |
| `backtests` | Cada prueba de una estrategia en un activo y una temporalidad, con sus condiciones y resultados |
| `operaciones` | Cada entrada de cada backtest: fechas, precios, motivo de salida y resultado |
| `v_backtests` (vista) | `backtests` con el nombre de la estrategia y el símbolo del activo |

### Columnas de `velas`

| Columna | Descripción |
|---|---|
| `activo_id`, `temporalidad`, `fecha_hora_utc` | Clave de la vela. `fecha_hora_utc` es la **apertura** |
| `fecha_cierre_utc` | Cierre de la vela: momento en que la vela y sus indicadores se conocen |
| `apertura`, `maximo`, `minimo`, `cierre` | Precios en USDT |
| `volumen` | Volumen en el propio activo (BTC, AVAX, LINK o NEAR) |
| `volumen_cotizado` | Volumen en USDT |
| `num_operaciones` | Número de operaciones en la vela |
| `sma_20`, `sma_50`, `sma_200` | Medias simples del cierre |
| `ema_20`, `ema_50`, `ema_200` | Medias exponenciales del cierre |
| `rsi_14` | RSI de 14 periodos (Wilder) |
| `macd`, `macd_senal`, `macd_histograma` | MACD 12/26/9 |
| `bb_superior`, `bb_inferior` | Bandas de Bollinger 20/2 (la banda media es `sma_20`) |
| `atr_14` | ATR de 14 periodos (Wilder) |
| `estoc_k`, `estoc_d` | Estocástico 14/3/3 |
| `vol_media_20` | Media simple de 20 velas del volumen |
| `vwap` | VWAP diario, que se reinicia a las 00:00 UTC. Solo en 5m, 15m, 1h y 4h; en 1d y 1w es NULL |
| `adx_14`, `di_mas_14`, `di_menos_14` | ADX 14 con DI+ y DI- (DMI de Wilder). El ADX mide la fuerza de la tendencia (por encima de 25, tendencia clara; por debajo de 20, lateral) y DI+ / DI- dicen si domina la compra o la venta |

## Cosas a tener en cuenta

- **Los precios están en USDT, no en USD.** USDT es una moneda estable que vale prácticamente
  1 dólar. Binance no tiene pares contra el dólar, pero de las fuentes gratuitas habituales es
  la que da las 6 temporalidades directamente y con todo el histórico.
- **Cada activo empieza en una fecha distinta**: la de su salida a cotizar en Binance.
- **Todas las fechas están en UTC.** La vela semanal empieza el lunes a las 00:00 UTC y la
  diaria a las 00:00 UTC (las 01:00 o 02:00 en hora de Madrid).
- **Los indicadores son los del cierre de la vela.** En un backtest, una vela y sus indicadores
  solo se pueden usar a partir de `fecha_cierre_utc`, nunca desde `fecha_hora_utc`.
  Si no, estarías usando datos del futuro.
- **Solo se guardan velas cerradas.** La vela que está en curso al hacer la carga no se guarda.
- **Las primeras velas de cada serie tienen indicadores en NULL**, porque todavía no hay
  historial suficiente. Por ejemplo, la SMA 200 empieza en la vela 200, el RSI en la 15 y la
  señal del MACD en la 34. En 1w eso supone casi 4 años sin SMA 200 desde que empieza cada activo.
- **Comparación con TradingView**: las fórmulas son las mismas. Al principio de cada serie puede
  haber pequeñas diferencias en las medias exponenciales mientras se estabilizan, y después
  coinciden.
- **Huecos**: Binance tuvo algunas paradas de mantenimiento, y en esos periodos no hay velas
  intradía. La mayor duró 33 horas, en febrero de 2018, y casi todas son de 2017 a 2020. El
  resumen de la carga indica cuántos huecos hay en cada temporalidad.
- **Primeros meses de cada activo**: algunas velas de 1h, 4h o 1d tienen una apertura, un máximo
  o un mínimo algo distintos de los que salen al agregar las de 5m. Viene así de Binance y solo
  ocurre al principio (hasta 2017 en BTC, hasta 2019–2020 en los demás). Los cierres y los
  volúmenes coinciden siempre.
- **Velas cortadas por una parada**: unas pocas velas (unas 70 en BTC, de 1,38 millones)
  terminan antes de lo normal porque Binance detuvo el mercado a mitad de vela. Su `fecha_cierre_utc` es el momento
  real de la parada, no apertura + duración.

## Consultas de ejemplo

Estas consultas se hacen en la base de datos del activo (aquí `activos/BTC/BTC.db`).

Últimas 100 velas de 1 hora:

```sql
SELECT fecha_hora_utc, apertura, maximo, minimo, cierre, volumen, rsi_14, macd, ema_200
FROM v_velas
WHERE simbolo = 'BTCUSDT' AND temporalidad = '1h'
ORDER BY fecha_hora_utc DESC
LIMIT 100;
```

Cada vela de 1h junto al RSI diario que se conocía en ese momento, sin mirar al futuro.
Se toma la última vela diaria ya cerrada:

```sql
SELECT h.fecha_hora_utc, h.cierre, h.rsi_14 AS rsi_1h,
       (SELECT d.rsi_14 FROM velas d
         WHERE d.activo_id = h.activo_id AND d.temporalidad = '1d'
           AND d.fecha_hora_utc <= datetime(h.fecha_cierre_utc, '-1 day')
         ORDER BY d.fecha_hora_utc DESC LIMIT 1) AS rsi_1d
FROM velas h
WHERE h.activo_id = (SELECT id FROM activos WHERE simbolo = 'BTCUSDT')
  AND h.temporalidad = '1h'
ORDER BY h.fecha_hora_utc;
```

Lo mismo desde Python, que es lo más cómodo para hacer backtesting:

```python
import sqlite3
import pandas as pd

con = sqlite3.connect("activos/BTC/BTC.db")   # cada activo en su carpeta

def velas(temporalidad, simbolo="BTCUSDT"):
    return pd.read_sql_query(
        "SELECT * FROM v_velas WHERE simbolo = ? AND temporalidad = ? ORDER BY fecha_hora_utc",
        con, params=(simbolo, temporalidad),
        parse_dates=["fecha_hora_utc", "fecha_cierre_utc"])

h1 = velas("1h")
d1 = velas("1d")

# A cada vela de 1h le une la última vela diaria ya CERRADA en ese momento
mtf = pd.merge_asof(
    h1,
    d1[["fecha_cierre_utc", "rsi_14", "ema_50"]].add_suffix("_1d"),
    left_on="fecha_cierre_utc", right_on="fecha_cierre_utc_1d",
)
```

## Backtesting

Haz doble clic en **`ejecutar_backtests.bat`** (con DBeaver o DB Browser cerrados). Prueba las
estrategias de `codigo/estrategias.py` en todos los activos y temporalidades, leyendo las velas de la
carpeta de cada activo, y guarda los resultados en `backtests` y `operaciones`, dentro de
`backtests.db`. Con cuatro estrategias tarda alrededor de un minuto. Si lo vuelves a ejecutar, cada
backtest con las mismas condiciones se sustituye por el nuevo.

También se puede ejecutar desde una consola en la carpeta DatosActivos:

```
python codigo/backtesting.py                                 # todo
python codigo/backtesting.py --simbolo BTCUSDT --temporalidades 1h 4h 1d
python codigo/backtesting.py --estrategias cruce_ema_20_50 rsi_30_70
python codigo/backtesting.py --direccion solo_largos         # largos_y_cortos (por defecto), solo_largos o solo_cortos
python codigo/backtesting.py --comision 0.1 --capital 10000  # comisión por compra y por venta (%) y capital inicial (USDT)
python codigo/backtesting.py --desde 2021-01-01 --hasta 2024-12-31
```

### Reglas de la simulación

- **Sin datos del futuro**: la señal se calcula al cierre de una vela y la orden se ejecuta a la
  apertura de la siguiente.
- **Comisión del 0,1 %** en cada compra y en cada venta.
- **Todo el capital en cada entrada** (10.000 USDT al empezar), así que los resultados son compuestos.
- **Largos y cortos**. Una señal contraria cierra la posición y abre la opuesta en la misma apertura.
  Los cortos se simulan sobre los precios del mercado al contado, **sin el coste de financiación
  (funding)** que tendrían en futuros. Si un corto llega a perder todo el capital, el backtest se
  detiene con el motivo `capital_agotado`.
- La posición que siga abierta al final se cierra al cierre de la última vela (`fin_periodo`).

### Estrategias

**Pendiente de decidir con qué estrategias empezar.** Mientras la lista `ESTRATEGIAS` de
`estrategias.py` esté vacía, `ejecutar_backtests.bat` solo crea las tablas vacías.

`estrategias.py` ya trae las reglas de las cuatro ideas propuestas, listas para activar copiando su
definición (está comentada en el propio archivo) a `ESTRATEGIAS`:

| Nombre | Regla |
|---|---|
| `cruce_ema_20_50` | Largo cuando la EMA 20 cruza al alza la EMA 50; corto cuando la cruza a la baja |
| `rsi_30_70` | Largo cuando el RSI 14 sube de 30, hasta que llega a 70; corto cuando baja de 70, hasta que llega a 30 |
| `cruce_macd_senal` | Largo cuando el MACD cruza al alza su señal; corto cuando la cruza a la baja |
| `rebote_bollinger_20_2` | Largo cuando el cierre vuelve a entrar sobre la banda inferior, hasta la media; corto al revés desde la superior |

Para crear otra, escribe su función en `estrategias.py`, regístrala en `FUNCIONES` y añádela a
`ESTRATEGIAS` con un nombre nuevo. Si cambias los parámetros de una que ya existe, dale un nombre
nuevo para no mezclar resultados.

### Métricas de `backtests`

Los porcentajes están en tanto por cien (5,2 = 5,2 %) y las rentabilidades por operación son netas
de comisiones.

| Columnas | Significado |
|---|---|
| `rentabilidad_total_pct`, `capital_final` | Resultado de la estrategia en todo el periodo |
| `rentabilidad_comprar_mantener_pct` | Comprar en la primera vela y vender en la última, con comisiones |
| `max_drawdown_pct` | Mayor caída del capital desde un máximo, con precios de cierre |
| `tiempo_en_mercado_pct` | % de velas con una posición abierta |
| `num_operaciones`, `num_largos`, `num_cortos`, `num_ganadoras`, `num_perdedoras`, `pct_acierto` | Recuento de entradas |
| `rentabilidad_largos_pct`, `rentabilidad_cortos_pct` | Resultado compuesto de solo los largos o solo los cortos |
| `ganancia_media_ganadoras_pct`, `perdida_media_perdedoras_pct` | Resultado medio de las ganadoras y de las perdedoras |
| `profit_factor` | Suma de ganancias entre suma de pérdidas, en USDT. Por encima de 1, gana más de lo que pierde |
| `rentabilidad_media_op_pct`, `rentabilidad_mediana_op_pct` | Si la media es mucho mayor que la mediana, el resultado lo sostienen unas pocas operaciones |
| `mejor_op_pct`, `peso_mejor_op_pct` | Mejor operación y qué parte de la suma de ganancias aporta |
| `num_ops_5pct`, `peso_mejores_5pct_pct` | Cuántas operaciones son el 5 % (mínimo 1) y qué parte de las ganancias aportan las mejores |
| `rentabilidad_sin_mejor_pct`, `rentabilidad_sin_mejores_5pct_pct` | Resultado total quitando la mejor o el 5 % mejor. **Si pasa a negativo, la estrategia es frágil** |
| `peor_op_pct`, `peso_peor_op_pct`, `peso_peores_5pct_pct`, `rentabilidad_sin_peor_pct`, `rentabilidad_sin_peores_5pct_pct` | Lo mismo por el lado de las pérdidas |

Ranking de estrategias por activo y temporalidad, con su fragilidad (en `backtests.db`):

```sql
SELECT simbolo, temporalidad, estrategia, num_operaciones,
       round(rentabilidad_total_pct, 1)            AS rentab,
       round(rentabilidad_comprar_mantener_pct, 1) AS comprar_mantener,
       round(pct_acierto, 1)                       AS acierto,
       round(profit_factor, 2)                     AS pf,
       round(peso_mejor_op_pct, 1)                 AS peso_mejor,
       round(rentabilidad_sin_mejores_5pct_pct, 1) AS sin_5pct_mejor,
       round(max_drawdown_pct, 1)                  AS max_caida
FROM v_backtests
ORDER BY rentabilidad_total_pct DESC;
```

Operaciones de un backtest concreto:

```sql
SELECT o.*
FROM operaciones o JOIN v_backtests b ON b.id = o.backtest_id
WHERE b.simbolo = 'BTCUSDT' AND b.temporalidad = '1d' AND b.estrategia = 'cruce_ema_20_50'
ORDER BY o.numero;
```

## Dashboard

Haz doble clic en **`dashboard.bat`**. Instala streamlit y plotly si hace falta y abre el dashboard en el
navegador. Se marcan las estrategias y el gráfico muestra al momento cómo habría evolucionado el capital
de cada una con todo el histórico, junto a comprar y mantener. Para cerrarlo, cierra la ventana negra.

También se puede abrir desde una consola en la carpeta DatosActivos: `streamlit run codigo/dashboard.py`.

- **Condiciones** (a la izquierda): activo, temporalidad, dirección, periodo, comisión, capital inicial y
  aportación mensual. Si `Desde` y `Hasta` se dejan vacíos se usa todo el histórico. Empieza en solo largos.
- **Aportación mensual**: con 0 solo se invierte el capital inicial. Con otra cantidad, se añade en la
  apertura de la primera vela de cada mes (en semanal, la del primer lunes). Si la estrategia está dentro
  del mercado, compra más en ese momento, con comisión; si está fuera, espera en liquidez y entra con el
  resto en la siguiente señal. En comprar y mantener cada aportación compra al momento. La rentabilidad y
  la columna `Sin el 5 % mejor` pasan a ser sobre todo lo aportado; la caída máxima, las operaciones, el
  acierto, el profit factor y el tiempo en mercado siguen siendo los de la estrategia con un único capital
  inicial. Con cortos, una aportación que llega con un corto abierto se reparte como el capital que ya
  había en él, y si la estrategia ha agotado el capital las aportaciones posteriores se quedan sin invertir.
- **Casillas**: dos cruces de medias (EMA 20/50 y EMA 50/200), RSI 30/70, cruce del MACD y rebote en
  Bollinger. En `Parámetros` se cambian el tipo y los periodos de las medias y los niveles del RSI. Las
  medias que no están guardadas en la base de datos (por ejemplo una EMA 30) se calculan al momento.
- **Gráfico**: capital al cierre de cada vela. La línea de puntos es el capital inicial o, con aportaciones
  mensuales, lo aportado hasta cada momento. Con más de 4.000 velas dibuja 4.000 repartidas por igual. En
  escala logarítmica el eje no baja de una milésima del capital inicial; una estrategia que lo pierde casi
  todo se sale por abajo.
- **Tabla**: total aportado, capital final y rentabilidad, y las mismas métricas que `backtests`,
  calculadas con todas las velas. `Sin el 5 % mejor` da el capital final que habría, y su rentabilidad, si
  la estrategia se hubiera quedado fuera en el 5 % de las operaciones con mejor resultado. Se ordena
  pulsando en la cabecera de una columna (esa, al llevar dos cifras, se ordena como texto). Debajo de la
  tabla se explica qué representa cada columna.

Usa el mismo motor y las mismas reglas que `ejecutar_backtests.bat`, así que las cifras coinciden. Solo
lee las bases de datos de los activos: no guarda nada en `backtests.db`. La primera vez que se elige una
temporalidad de 5m tarda unos 15 segundos en leer las velas; después responde al momento.

Para añadir una estrategia a las casillas, escribe su función en `estrategias.py`, regístrala en
`FUNCIONES` y añádela a `CATALOGO` y a `TITULOS`, en `codigo/dashboard.py`.

## Estudio de tendencias

`python codigo/estudio_tendencias.py` mira, para cada vela de 1w, 1d y 4h, en qué situación estaban los
indicadores y qué hizo el precio después (comprando en la apertura de la vela siguiente). Compara cada
situación con comprar en cualquier vela del mismo activo, por activo y en dos periodos (antes y
desde 2023). Solo lee las bases de datos de los activos y deja `resultados/estudio_tendencias/resumen.csv` y
`resultados/estudio_tendencias/resultados.csv` (se abren en Excel; separador punto y coma). Necesita el ADX,
así que ejecuta antes `recalcular_indicadores.bat`.

## Ampliaciones

- **Otro activo**: añade su par en `activos/activos.txt` (por ejemplo `SOLUSDT`) y ejecuta
  `cargar_datos.bat`. Vale cualquier par spot de Binance. Se crea su carpeta (`activos/SOL/SOL.db`) y
  los activos que ya estaban solo reciben las velas nuevas.
- **Otro indicador**:
  1. Añade la columna en `codigo/esquema.sql`.
  2. Añade el nombre en `COLUMNAS_INDICADORES` y el cálculo en `calcular_indicadores()`, los dos en `codigo/indicadores.py`.
  3. Ejecuta `recalcular_indicadores.bat`: añade la columna a la base de datos de cada activo y la calcula en todas las
     velas guardadas, sin volver a descargarlas (unos 2 minutos).
