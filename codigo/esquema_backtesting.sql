-- =====================================================================
--  DatosActivos - base de datos principal: backtests.db (SQLite)
--
--  Está en la carpeta principal y guarda lo que no es de un solo activo.
--  Las velas e indicadores de cada activo están en su carpeta (BTC/BTC.db...).
--
--    activos      : lista de activos; cada uno tiene su carpeta con su nombre
--                   (columna base). La rellena cargar_datos.py.
--    estrategias  : (las rellena backtesting.py) qué es cada estrategia y con qué parámetros.
--    backtests    : cada prueba de una estrategia en un activo y una
--                   temporalidad, con sus condiciones y resultados.
--    operaciones  : cada entrada de cada backtest, una a una.
--
--  Convenciones:
--    * Fechas en UTC, formato 'YYYY-MM-DD HH:MM:SS'.
--    * Los porcentajes se guardan en tanto por cien (5.2 = 5,2 %).
--    * La señal se evalúa al CIERRE de una vela y la orden se ejecuta a la
--      APERTURA de la vela siguiente, así nunca se usan datos del futuro.
--    * Comisión aplicada en la entrada y en la salida de cada operación.
--    * Cada entrada usa todo el capital disponible (resultados compuestos).
--    * Los cortos se simulan sobre los precios del mercado al contado, sin
--      costes de financiación (funding) de los futuros.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
--  Activos: uno por fila. Su carpeta se llama como la columna base
--  (BTC, ETH...) y dentro está su base de datos BASE.db
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activos (
    id           INTEGER PRIMARY KEY,
    exchange     TEXT NOT NULL,          -- 'Binance'
    simbolo      TEXT NOT NULL,          -- símbolo en el exchange: 'BTCUSDT'
    base         TEXT NOT NULL,          -- 'BTC' (también es el nombre de su carpeta)
    cotizacion   TEXT NOT NULL,          -- 'USDT'
    descripcion  TEXT,
    UNIQUE (exchange, simbolo)
);

CREATE TABLE IF NOT EXISTS temporalidades (
    codigo   TEXT PRIMARY KEY,           -- '5m', '15m', '1h', '4h', '1d', '1w'
    minutos  INTEGER NOT NULL UNIQUE
);

INSERT OR IGNORE INTO temporalidades (codigo, minutos) VALUES
    ('5m',     5),
    ('15m',   15),
    ('1h',    60),
    ('4h',   240),
    ('1d',  1440),
    ('1w', 10080);

-- ---------------------------------------------------------------------
--  Estrategias: definición y parámetros
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS estrategias (
    id                  INTEGER PRIMARY KEY,
    nombre              TEXT NOT NULL UNIQUE,   -- 'cruce_ema_20_50'
    codigo              TEXT NOT NULL,          -- función de estrategias.py que la ejecuta
    descripcion         TEXT,
    parametros          TEXT NOT NULL,          -- JSON, p. ej. {"media_lenta": "ema_50", "media_rapida": "ema_20"}
    fecha_creacion_utc  TEXT NOT NULL
);

-- ---------------------------------------------------------------------
--  Backtests: una fila por estrategia + activo + temporalidad + condiciones
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtests (
    id                          INTEGER PRIMARY KEY,
    estrategia_id               INTEGER NOT NULL REFERENCES estrategias(id),
    activo_id                   INTEGER NOT NULL REFERENCES activos(id),
    temporalidad                TEXT    NOT NULL REFERENCES temporalidades(codigo),
    fecha_ejecucion_utc         TEXT    NOT NULL,
    version_motor               TEXT    NOT NULL,

    -- Condiciones de la prueba
    fecha_inicio_utc            TEXT NOT NULL,  -- apertura de la primera vela del periodo
    fecha_fin_utc               TEXT NOT NULL,  -- cierre de la última vela del periodo
    num_velas                   INTEGER NOT NULL,
    direccion                   TEXT NOT NULL CHECK (direccion IN ('largos_y_cortos', 'solo_largos', 'solo_cortos')),
    comision_pct                REAL NOT NULL,  -- por cada compra y cada venta (0.1 = 0,1 %)
    capital_inicial             REAL NOT NULL,
    notas                       TEXT,

    -- Resultado global
    capital_final               REAL NOT NULL,
    rentabilidad_total_pct      REAL NOT NULL,
    rentabilidad_comprar_mantener_pct REAL,     -- comprar al inicio y vender al final, con comisiones
    max_drawdown_pct            REAL,           -- mayor caída desde un máximo del capital (con precios de cierre)
    tiempo_en_mercado_pct       REAL,           -- % de velas con una posición abierta
    comisiones_totales          REAL,           -- en USDT

    -- Operaciones
    num_operaciones             INTEGER NOT NULL,
    num_largos                  INTEGER NOT NULL,
    num_cortos                  INTEGER NOT NULL,
    num_ganadoras               INTEGER NOT NULL,
    num_perdedoras              INTEGER NOT NULL,
    pct_acierto                 REAL,
    rentabilidad_largos_pct     REAL,           -- resultado compuesto solo de los largos
    rentabilidad_cortos_pct     REAL,           -- resultado compuesto solo de los cortos
    ganancia_media_ganadoras_pct REAL,
    perdida_media_perdedoras_pct REAL,
    profit_factor               REAL,           -- ganancias / pérdidas, en USDT
    rentabilidad_media_op_pct   REAL,
    rentabilidad_mediana_op_pct REAL,
    duracion_media_velas        REAL,

    -- Concentración del beneficio (por el lado de las ganadoras)
    mejor_op_pct                REAL,           -- rentabilidad de la mejor operación
    peso_mejor_op_pct           REAL,           -- % de la suma de ganancias que aporta la mejor
    num_ops_5pct                INTEGER,        -- cuántas operaciones son el 5 % (mínimo 1)
    peso_mejores_5pct_pct       REAL,           -- % de la suma de ganancias que aporta el 5 % mejor
    rentabilidad_sin_mejor_pct  REAL,           -- rentabilidad total quitando la mejor
    rentabilidad_sin_mejores_5pct_pct REAL,     -- rentabilidad total quitando el 5 % mejor

    -- Concentración de las pérdidas (por el lado de las perdedoras)
    peor_op_pct                 REAL,
    peso_peor_op_pct            REAL,           -- % de la suma de pérdidas que aporta la peor
    peso_peores_5pct_pct        REAL,
    rentabilidad_sin_peor_pct   REAL,
    rentabilidad_sin_peores_5pct_pct REAL,

    UNIQUE (estrategia_id, activo_id, temporalidad, direccion, comision_pct, capital_inicial, fecha_inicio_utc)
);

CREATE INDEX IF NOT EXISTS ix_backtests_activo ON backtests (activo_id, temporalidad);

-- ---------------------------------------------------------------------
--  Operaciones: cada entrada de cada backtest
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operaciones (
    id                   INTEGER PRIMARY KEY,
    backtest_id          INTEGER NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    numero               INTEGER NOT NULL,      -- 1, 2, 3... dentro del backtest
    direccion            TEXT    NOT NULL CHECK (direccion IN ('largo', 'corto')),

    fecha_senal_utc      TEXT NOT NULL,         -- cierre de la vela que dio la señal de entrada
    fecha_entrada_utc    TEXT NOT NULL,         -- apertura de la vela en la que se entra
    precio_entrada       REAL NOT NULL,
    fecha_salida_utc     TEXT NOT NULL,         -- apertura de la vela en la que se sale (o cierre de la última)
    precio_salida        REAL NOT NULL,
    motivo_salida        TEXT NOT NULL,         -- 'senal_salida', 'giro', 'fin_periodo', 'capital_agotado'
    duracion_velas       INTEGER NOT NULL,

    capital_entrada      REAL NOT NULL,         -- capital antes de entrar
    capital_salida       REAL NOT NULL,         -- capital después de salir, ya descontadas comisiones
    comisiones           REAL NOT NULL,         -- en USDT
    beneficio            REAL NOT NULL,         -- capital_salida - capital_entrada, en USDT
    rentabilidad_pct     REAL NOT NULL,         -- neta de comisiones

    UNIQUE (backtest_id, numero)
);

-- ---------------------------------------------------------------------
--  Vista de consulta: resultados con el nombre de la estrategia y el activo
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_backtests AS
SELECT e.nombre AS estrategia, a.simbolo, b.*
FROM backtests b
JOIN estrategias e ON e.id = b.estrategia_id
JOIN activos a ON a.id = b.activo_id;
