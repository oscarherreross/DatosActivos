-- =====================================================================
--  DatosActivos - esquema de la base de datos de UN activo (SQLite)
--
--  Cada activo tiene su carpeta con su propia base de datos, p. ej.
--  BTC/BTC.db, con el histórico de velas en 6 temporalidades
--  (5m, 15m, 1h, 4h, 1d, 1w) junto con el valor de los indicadores
--  técnicos AL CIERRE de cada vela.
--  La tabla activos tiene una sola fila, con el mismo id que el activo
--  tiene en la base de datos principal (backtests.db).
--
--  Convenciones:
--    * Todas las fechas están en UTC, en formato 'YYYY-MM-DD HH:MM:SS'.
--    * fecha_hora_utc   = momento de APERTURA de la vela (como en Binance
--                         y TradingView).
--    * fecha_cierre_utc = momento en que la vela se cierra; es cuando sus
--                         precios e indicadores pasan a estar disponibles.
--                         Úsala en backtesting para no mirar al futuro.
--    * Un indicador vale NULL en las primeras velas de cada serie, hasta
--      que hay suficientes datos para calcularlo (p. ej. 199 velas para
--      la SMA 200).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
--  Activo de esta base de datos (una sola fila)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activos (
    id           INTEGER PRIMARY KEY,
    exchange     TEXT NOT NULL,          -- 'Binance'
    simbolo      TEXT NOT NULL,          -- símbolo en el exchange: 'BTCUSDT'
    base         TEXT NOT NULL,          -- 'BTC'
    cotizacion   TEXT NOT NULL,          -- 'USDT'
    descripcion  TEXT,
    UNIQUE (exchange, simbolo)
);

-- ---------------------------------------------------------------------
--  Temporalidades admitidas
-- ---------------------------------------------------------------------
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
--  Velas + indicadores (una única tabla para todas las temporalidades)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS velas (
    activo_id         INTEGER NOT NULL REFERENCES activos(id),
    temporalidad      TEXT    NOT NULL REFERENCES temporalidades(codigo),
    fecha_hora_utc    TEXT    NOT NULL,  -- apertura de la vela
    fecha_cierre_utc  TEXT    NOT NULL,  -- cierre de la vela

    -- Precio y volumen
    apertura          REAL NOT NULL,
    maximo            REAL NOT NULL,
    minimo            REAL NOT NULL,
    cierre            REAL NOT NULL,
    volumen           REAL NOT NULL,     -- en el activo base (BTC)
    volumen_cotizado  REAL,              -- en la moneda de cotización (USDT)
    num_operaciones   INTEGER,

    -- Medias móviles simples (sobre el cierre)
    sma_20            REAL,
    sma_50            REAL,
    sma_200           REAL,

    -- Medias móviles exponenciales (sobre el cierre)
    ema_20            REAL,
    ema_50            REAL,
    ema_200           REAL,

    -- RSI 14 (Wilder)
    rsi_14            REAL,

    -- MACD 12/26/9
    macd              REAL,              -- EMA12 - EMA26
    macd_senal        REAL,              -- EMA9 del MACD
    macd_histograma   REAL,              -- macd - macd_senal

    -- Bandas de Bollinger 20/2 (la banda media es sma_20)
    bb_superior       REAL,
    bb_inferior       REAL,

    -- ATR 14 (Wilder)
    atr_14            REAL,

    -- Estocástico 14/3/3
    estoc_k           REAL,              -- %K suavizado (SMA 3)
    estoc_d           REAL,              -- %D = SMA 3 de %K

    -- Volumen medio (SMA 20 del volumen)
    vol_media_20      REAL,

    -- VWAP diario (se reinicia cada día a las 00:00 UTC).
    -- Solo en 5m, 15m, 1h y 4h; en 1d y 1w es NULL.
    vwap              REAL,

    -- ADX 14 con DI+ y DI- (DMI de Wilder): fuerza y dirección de la tendencia.
    -- Añadido el 06/10/2026; en una BD anterior lo añade recalcular_indicadores.py
    adx_14            REAL,
    di_mas_14         REAL,
    di_menos_14       REAL,

    PRIMARY KEY (activo_id, temporalidad, fecha_hora_utc)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------
--  Registro de cada carga (cuándo se hizo la "foto" y qué incluyó)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cargas (
    id                INTEGER PRIMARY KEY,
    activo_id         INTEGER NOT NULL REFERENCES activos(id),
    temporalidad      TEXT    NOT NULL REFERENCES temporalidades(codigo),
    fecha_carga_utc   TEXT    NOT NULL,
    primera_vela_utc  TEXT,              -- primera vela insertada en esta carga
    ultima_vela_utc   TEXT,              -- última vela insertada en esta carga
    velas_insertadas  INTEGER NOT NULL
);

-- ---------------------------------------------------------------------
--  Vista de consulta: velas con el símbolo del activo
--  Ejemplo: SELECT * FROM v_velas
--           WHERE simbolo = 'BTCUSDT' AND temporalidad = '1h'
--           ORDER BY fecha_hora_utc;
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_velas AS
SELECT a.exchange, a.simbolo, v.*
FROM velas v
JOIN activos a ON a.id = v.activo_id;
