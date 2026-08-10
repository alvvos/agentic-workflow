import gc
import json
import logging
import os
from datetime import datetime, timedelta

import holidays
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error

from src.db.queries import get_active_ext_features, get_org_info

log = logging.getLogger("ml_predictivo")

_HOL_CACHE: dict = {}

# Cobertura nominal de los intervalos conformes (90 %)
_CONFORMAL_ALPHA = 0.10
# Decay exponencial para ponderar residuos de calibración: residuos recientes pesan más.
# Con decay=0.04 y n=60 días de calibración, el día más reciente pesa ~11× el más antiguo.
_CONFORMAL_DECAY = 0.04
# Factor de crecimiento logarítmico de la banda con el horizonte.
# Con beta=0.15: día 1 → ×1.00, día 7 → ×1.29, día 14 → ×1.40.
_HORIZON_BETA = 0.15
# TTL del modelo en caché: 14 días = 2 ciclos semanales completos.
# El XGBoost aprende patrones día-de-semana; con <2 semanas puede no haber visto
# suficientes repeticiones de cada día. Más de 14 días arriesga drift estacional.
_MODEL_CACHE_TTL_DAYS = 14


def _weighted_conformal_quantile(resid: np.ndarray, level: float) -> float:
    """Cuantil empírico con pesos exponenciales por recencia.

    El set de calibración está ordenado cronológicamente: índice 0 = más antiguo.
    Los residuos recientes reciben más peso porque el régimen actual de volatilidad
    es más relevante para el futuro inmediato que el de hace meses.
    Resuelve parcialmente la violación de intercambiabilidad por autocorrelación.
    """
    n = len(resid)
    weights = np.exp(_CONFORMAL_DECAY * np.arange(n))
    weights /= weights.sum()
    sorted_idx = np.argsort(resid)
    cumw = np.cumsum(weights[sorted_idx])
    idx = int(np.searchsorted(cumw, level))
    return float(resid[sorted_idx[min(idx, n - 1)]])


def _get_festivos(pais_codigo: str, years: list) -> object:
    key = (pais_codigo, tuple(sorted(years)))
    if key not in _HOL_CACHE:
        try:
            if pais_codigo == "MX":
                _HOL_CACHE[key] = holidays.Mexico(years=years)
            else:
                _HOL_CACHE[key] = holidays.ES(years=years)
        except Exception:
            _HOL_CACHE[key] = {}
    return _HOL_CACHE[key]


# Keep the global ES calendar as a backward-compatible fallback
festivos_espana = holidays.ES(years=[2024, 2025, 2026])

# ── Registro de modelos ──────────────────────────────────────────────────────
_REGISTRY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "registry")
_REGISTRY_PURGED = False  # guard: la purga ocurre una sola vez por proceso


def _registry_paths(location_uuid, zone_uuid):
    os.makedirs(_REGISTRY_DIR, exist_ok=True)
    key = f"{location_uuid}_{zone_uuid}"
    return (
        os.path.join(_REGISTRY_DIR, f"{key}.ubj"),
        os.path.join(_REGISTRY_DIR, f"{key}.meta.json"),
    )


def _load_cached_model(location_uuid, zone_uuid, features):
    """Inválido si: no existe, features distintas, tiene > _MODEL_CACHE_TTL_DAYS, o sin q_conf."""
    model_path, meta_path = _registry_paths(location_uuid, zone_uuid)
    _key = f"{location_uuid[:8]}_{zone_uuid[:8]}"
    if not os.path.exists(model_path) or not os.path.exists(meta_path):
        log.info("CACHE MISS [%s] — archivos no encontrados", _key)
        return None, {}, None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get("features") != features:
            log.warning(
                "CACHE MISS [%s] — feature mismatch. cached=%s  current=%s",
                _key,
                meta.get("features"),
                features,
            )
            return None, {}, None
        age_days = (datetime.now() - datetime.fromisoformat(meta["trained_at"])).days
        if age_days > _MODEL_CACHE_TTL_DAYS:
            log.info("CACHE MISS [%s] — modelo caducado (%d días)", _key, age_days)
            return None, {}, None
        if meta.get("q_conf") is None:
            log.info("CACHE MISS [%s] — q_conf ausente", _key)
            return None, {}, None
        modelo = xgb.XGBRegressor()
        modelo.load_model(model_path)
        log.info("CACHE HIT  [%s] — modelo cargado (%d días)", _key, age_days)
        return modelo, meta.get("metrics", {}), meta.get("q_conf")
    except Exception as e:
        log.warning("CACHE MISS [%s] — excepción al cargar: %s", _key, e)
        return None, {}, None


def _purge_stale_registry() -> None:
    """Borra pares .ubj + .meta.json cuyo trained_at supera el TTL.

    Se llama una vez por proceso (guard _REGISTRY_PURGED) desde _save_model,
    de modo que la limpieza ocurre justo después de guardar un modelo fresco
    sin añadir latencia a las peticiones de lectura.
    """
    cutoff = datetime.now() - timedelta(days=_MODEL_CACHE_TTL_DAYS + 1)
    try:
        entries = os.listdir(_REGISTRY_DIR)
    except FileNotFoundError:
        return
    for fname in entries:
        if not fname.endswith(".meta.json"):
            continue
        meta_path = os.path.join(_REGISTRY_DIR, fname)
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if datetime.fromisoformat(meta["trained_at"]) < cutoff:
                os.remove(meta_path)
                ubj = os.path.join(_REGISTRY_DIR, fname.replace(".meta.json", ".ubj"))
                if os.path.exists(ubj):
                    os.remove(ubj)
        except Exception:
            pass


def _save_model(modelo, location_uuid, zone_uuid, features, metrics, q_conf):
    global _REGISTRY_PURGED
    model_path, meta_path = _registry_paths(location_uuid, zone_uuid)
    modelo.save_model(model_path)
    with open(meta_path, "w") as f:
        json.dump(
            {
                "location_uuid": location_uuid,
                "zone_uuid": zone_uuid,
                "trained_at": datetime.now().isoformat(),
                "features": features,
                "metrics": metrics,
                "q_conf": q_conf,
            },
            f,
            indent=2,
        )
    if not _REGISTRY_PURGED:
        _purge_stale_registry()
        _REGISTRY_PURGED = True


# ── Loop autorregresivo ───────────────────────────────────────────────────────


def _loop_prediccion(
    modelo,
    df_hist,
    df_tienda,
    fecha_corte,
    horizonte,
    features,
    festivos,
    ext_df,
    ext_cols_safe,
    org_config,
):
    """
    Ejecuta el loop autorregresivo multi-step desde fecha_corte.

    df_hist   — histórico hasta fecha_corte (exclusive); proporciona los lags iniciales.
    df_tienda — serie completa; permite recuperar ground truth para días ya transcurridos
                dentro del horizonte (útil en backtesting y cálculo de métricas).

    Devuelve (fechas_str, predichos, reales).
    """
    df_work = df_hist.copy()
    fechas_pred, valores_pred, valores_reales = [], [], []

    for i in range(horizonte):
        current_date = fecha_corte + timedelta(days=i)
        fechas_pred.append(current_date.strftime("%Y-%m-%d"))

        real_row = df_tienda[df_tienda["fecha"] == current_date]
        tiene_real = not real_row.empty

        llueve = real_row["llueve"].values[0] if tiene_real else 0
        t_max = real_row["temp_max"].values[0] if tiene_real else 22.0
        t_min = real_row["temp_min"].values[0] if tiene_real else 12.0
        real_visits = real_row["total_visits"].values[0] if tiene_real else None
        valores_reales.append(real_visits)

        es_festivo = 1 if current_date in festivos else 0
        es_finde = 1 if current_date.dayofweek in [5, 6] else 0

        visits_array = df_work["total_visits"].values
        lag_1d = visits_array[-1] if len(visits_array) >= 1 else 0
        lag_7d = visits_array[-7] if len(visits_array) >= 7 else 0
        lag_14d = visits_array[-14] if len(visits_array) >= 14 else 0
        media_7d = np.mean(visits_array[-7:]) if len(visits_array) >= 7 else 0
        media_14d = np.mean(visits_array[-14:]) if len(visits_array) >= 14 else 0
        std_7d = np.std(visits_array[-7:]) if len(visits_array) >= 7 else 0

        pred_ts = pd.Timestamp(current_date)
        ext_feats: dict = {}
        for col in ext_cols_safe:
            if pred_ts not in ext_df.index:
                ext_feats[col] = 0.0
                continue
            val = ext_df.loc[pred_ts, col]
            if isinstance(val, (pd.Series, pd.DataFrame)):
                val = float(val.iloc[0]) if len(val) > 0 else 0.0
            ext_feats[col] = 0.0 if pd.isna(val) else float(val)

        row = pd.DataFrame(
            [
                {
                    "es_finde": es_finde,
                    "es_festivo": es_festivo,
                    "llueve": llueve,
                    "dia_semana": current_date.dayofweek,
                    "dia_mes": current_date.day,
                    "mes": current_date.month,
                    "lag_1d": lag_1d,
                    "lag_7d": lag_7d,
                    "media_7d": media_7d,
                    "quincena": 1 if current_date.day > 15 else 0,
                    "vispera_festivo": (1 if (current_date + timedelta(days=1)) in festivos else 0),
                    "lag_14d": lag_14d,
                    "media_14d": media_14d,
                    "std_7d": std_7d,
                    "finde_lluvioso": es_finde * llueve,
                    "mucho_calor": 1 if t_max >= 32.0 else 0,
                    "mucho_frio": 1 if t_min <= 8.0 else 0,
                    "clima_ideal": 1 if (18.0 <= t_max <= 26.0 and llueve == 0) else 0,
                    "es_gap": 0,
                    **ext_feats,
                }
            ]
        )

        pred = np.maximum(0, np.round(modelo.predict(row[features])[0]))
        valores_pred.append(pred)
        df_work = pd.concat(
            [df_work, pd.DataFrame({"fecha": [current_date], "total_visits": [pred]})],
            ignore_index=True,
        )

    return fechas_pred, valores_pred, valores_reales


# ── Predicción ───────────────────────────────────────────────────────────────


def ejecutar_auditoria_predictiva(df_master, location_uuid, zone_uuid, falso_hoy, horizonte_dias):
    modelo = None
    try:
        # Org context (pais, calendar config) — graceful degradation if DB unavailable
        try:
            org = get_org_info(location_uuid)
            pais_codigo = org["pais_codigo"]
            org_config = org["config_calendario"]
        except Exception:
            pais_codigo = "ES"
            org_config = {}

        años = list({2024, 2025, 2026, datetime.today().year})
        festivos = _get_festivos(pais_codigo, años)

        # 1. EXTRACCIÓN DE HISTÓRICO
        df_tienda = df_master[
            (df_master["location_id"] == location_uuid) & (df_master["zona_id"] == zone_uuid)
        ].copy()

        if df_tienda.empty:
            return {"error": "No hay datos históricos para esta zona."}

        df_tienda["fecha"] = pd.to_datetime(df_tienda["fecha"])
        df_tienda = (
            df_tienda.groupby("fecha")
            .agg(
                {
                    "total_visits": "sum",
                    "llueve": "max",
                    "temp_max": "max",
                    "temp_min": "min",
                    "es_festivo": "max",
                }
            )
            .reset_index()
            .sort_values("fecha")
            .reset_index(drop=True)
        )

        # Gap handling: reindex al rango de fechas completo para que shift(n)
        # opere sobre días calendario y no sobre posiciones. Sin esto, un agujero
        # de 7 días consecutivos hace que lag_7d apunte al día anterior al hueco,
        # no al día equivalente de la semana anterior.
        _full_idx = pd.date_range(df_tienda["fecha"].min(), df_tienda["fecha"].max(), freq="D")
        df_tienda = (
            df_tienda.set_index("fecha").reindex(_full_idx).rename_axis("fecha").reset_index()
        )
        df_tienda["es_gap"] = df_tienda["total_visits"].isna().astype(int)
        df_tienda["total_visits"] = df_tienda["total_visits"].fillna(0)
        df_tienda["temp_max"] = df_tienda["temp_max"].ffill().bfill().fillna(22.0)
        df_tienda["temp_min"] = df_tienda["temp_min"].ffill().bfill().fillna(15.0)
        df_tienda["llueve"] = df_tienda["llueve"].ffill().bfill().fillna(0).astype(int)
        # Recompute es_festivo for all rows including gap days
        df_tienda["es_festivo"] = df_tienda["fecha"].apply(
            lambda d: 1 if d.date() in festivos else 0
        )

        # 2. SEPARACIÓN DEL PASADO (TRAIN SET)
        fecha_corte = pd.to_datetime(falso_hoy)
        train = df_tienda[df_tienda["fecha"] < fecha_corte].copy()

        if len(train) < 30:
            return {
                "error": "Muestra histórica insuficiente para entrenar (mínimo 30 días previos)."
            }

        train["es_finde"] = train["fecha"].dt.dayofweek.isin([5, 6]).astype(int)
        train["dia_semana"] = train["fecha"].dt.dayofweek
        train["dia_mes"] = train["fecha"].dt.day
        train["mes"] = train["fecha"].dt.month
        train["quincena"] = (train["dia_mes"] > 15).astype(int)
        train["vispera_festivo"] = train["fecha"].apply(
            lambda d: 1 if (d + timedelta(days=1)) in festivos else 0
        )
        train["mucho_calor"] = (train["temp_max"] >= 32.0).astype(int)
        train["mucho_frio"] = (train["temp_min"] <= 8.0).astype(int)
        train["clima_ideal"] = (
            (train["temp_max"] >= 18.0) & (train["temp_max"] <= 26.0) & (train["llueve"] == 0)
        ).astype(int)
        train["finde_lluvioso"] = train["es_finde"] * train["llueve"]
        train["lag_1d"] = train["total_visits"].shift(1)
        train["lag_7d"] = train["total_visits"].shift(7)
        train["media_7d"] = train["total_visits"].rolling(7).mean()
        train["lag_14d"] = train["total_visits"].shift(14)
        train["media_14d"] = train["total_visits"].rolling(14).mean()
        train["std_7d"] = train["total_visits"].rolling(7).std().fillna(0)
        train = train.dropna().reset_index(drop=True)

        # Features externas activas
        ext_df = get_active_ext_features(
            location_uuid,
            train["fecha"].min(),
            train["fecha"].max(),
        )
        ext_cols = [c for c in ext_df.columns if ext_df[c].notna().any()]

        if ext_cols:
            ext_aligned = (
                ext_df[ext_cols].reindex(pd.DatetimeIndex(train["fecha"].values)).fillna(0.0)
            )
            ext_aligned.index = train.index
            for col in ext_cols:
                train[col] = ext_aligned[col]

        # Liberar conexión antes del entrenamiento
        try:
            from src.db.store import close_conn

            close_conn()
        except Exception:
            pass

        _BASE_FEATURES = [
            "es_finde",
            "es_festivo",
            "llueve",
            "dia_semana",
            "dia_mes",
            "mes",
            "lag_1d",
            "lag_7d",
            "media_7d",
            "quincena",
            "vispera_festivo",
            "lag_14d",
            "media_14d",
            "std_7d",
            "finde_lluvioso",
            "mucho_calor",
            "mucho_frio",
            "clima_ideal",
            "es_gap",
        ]

        _reserved = set(_BASE_FEATURES)
        ext_cols_safe = [c for c in ext_cols if c not in _reserved]
        features = _BASE_FEATURES + ext_cols_safe

        X_train, y_train = train[features], train["total_visits"]

        # 3. MODELO: caché o entrenamiento
        hoy = datetime.today().date()
        delta_dias = abs((pd.to_datetime(falso_hoy).date() - hoy).days)
        es_produccion = delta_dias <= 2

        if not es_produccion:
            log.info(
                "TRAIN [%s/%s] — backtest (falso_hoy=%s, delta=%d d) — sin caché",
                location_uuid[:8],
                zone_uuid[:8],
                falso_hoy,
                delta_dias,
            )

        cache_hit = False
        cached_metrics = {}
        q_conf = None
        if es_produccion:
            modelo, cached_metrics, q_conf = _load_cached_model(location_uuid, zone_uuid, features)
            if modelo is not None:
                cache_hit = True

        if not cache_hit:
            n = len(X_train)
            # Split temporal 70 / 15 / 15:
            #   train puro → ajuste de árboles
            #   calibración → cálculo conformal
            #   validación → early stopping
            split_train = int(n * 0.70)
            split_cal = int(n * 0.85)

            X_t, y_t = X_train.iloc[:split_train], y_train.iloc[:split_train]
            X_cal, y_cal = X_train.iloc[split_train:split_cal], y_train.iloc[split_train:split_cal]
            X_v, y_v = X_train.iloc[split_cal:], y_train.iloc[split_cal:]

            modelo = xgb.XGBRegressor(
                n_estimators=250,
                learning_rate=0.05,
                max_depth=4,
                random_state=42,
                early_stopping_rounds=20,
            )
            modelo.fit(X_t, y_t, eval_set=[(X_t, y_t), (X_v, y_v)], verbose=False)

            # Conformal q con pesos exponenciales por recencia (EnbPI adaptado).
            # El cuantil con corrección (n+1) garantiza cobertura ≥ 1−α; el weighting
            # exponencial hace que el régimen reciente de volatilidad domine sobre el
            # histórico lejano, atenuando el problema de autocorrelación en la calibración.
            if len(X_cal) > 0:
                resid = np.abs(y_cal.values - np.maximum(0, modelo.predict(X_cal)))
                n_cal = len(resid)
                level = min(np.ceil((n_cal + 1) * (1 - _CONFORMAL_ALPHA)) / n_cal, 1.0)
                q_conf = _weighted_conformal_quantile(resid, level)

        # 4. PREDICCIÓN AUTORREGRESIVA
        df_hist = df_tienda[df_tienda["fecha"] < fecha_corte].copy()
        fechas_pred, valores_pred, valores_reales = _loop_prediccion(
            modelo=modelo,
            df_hist=df_hist,
            df_tienda=df_tienda,
            fecha_corte=fecha_corte,
            horizonte=horizonte_dias,
            features=features,
            festivos=festivos,
            ext_df=ext_df,
            ext_cols_safe=ext_cols_safe,
            org_config=org_config,
        )

        # Bandas conformes con crecimiento logarítmico por horizonte.
        # En la predicción autorregresiva cada paso h usa h predicciones propias como lags,
        # acumulando error. q_h = q_conf × (1 + β·ln(h+1)) captura ese crecimiento
        # sin explotar: día 1 ×1.00, día 7 ×1.29, día 14 ×1.40.
        if q_conf is not None:
            lowers, uppers = [], []
            for h, p in enumerate(valores_pred):
                q_h = q_conf * (1 + _HORIZON_BETA * np.log1p(h))
                lowers.append(int(np.maximum(0, np.round(p - q_h))))
                uppers.append(int(np.round(p + q_h)))
        else:
            lowers = uppers = None

        # 5. MÉTRICAS
        reales_validos = [r for r in valores_reales if pd.notna(r)]
        pred_validos = valores_pred[: len(reales_validos)]

        if reales_validos:
            mae = mean_absolute_error(reales_validos, pred_validos)
            sum_reales = np.sum(reales_validos)
            wmape = (
                np.sum(np.abs(np.array(reales_validos) - np.array(pred_validos))) / sum_reales
                if sum_reales > 0
                else 0
            )
            acc_val = round((1 - wmape) * 100, 2)
            mae_val = round(mae, 1)
            wmape_val = round(wmape * 100, 2)
        else:
            acc_val = mae_val = wmape_val = "N/A"

        best_iter = (
            cached_metrics.get("best_iteration")
            if cache_hit
            else getattr(modelo, "best_iteration", None)
        )

        if not cache_hit and es_produccion:
            _save_model(
                modelo,
                location_uuid,
                zone_uuid,
                features,
                {
                    "accuracy": acc_val,
                    "mae": mae_val,
                    "wmape_pct": wmape_val,
                    "best_iteration": best_iter,
                },
                q_conf=q_conf,
            )

        return {
            "status": "success",
            "cache_hit": cache_hit,
            "metricas": {
                "accuracy": acc_val,
                "mae": mae_val,
                "wmape_pct": wmape_val,
                "arboles_optimos": best_iter,
                "q_conf": round(q_conf, 1) if q_conf is not None else None,
            },
            "grafica": {
                "fechas": fechas_pred,
                "reales": valores_reales,
                "predichos": valores_pred,
                "lower": lowers,
                "upper": uppers,
            },
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        del modelo
        gc.collect()
