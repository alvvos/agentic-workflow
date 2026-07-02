import gc
import json
import os
from datetime import datetime, timedelta

import holidays
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error

from src.data_processing.supercalendario import CALENDARIO_FEATURE_COLS, get_calendario_features
from src.db.queries import get_active_ext_features, get_org_info

_HOL_CACHE: dict = {}

# Cobertura nominal de los intervalos conformes (90 %)
_CONFORMAL_ALPHA = 0.10


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


def _registry_paths(location_uuid, zone_uuid):
    os.makedirs(_REGISTRY_DIR, exist_ok=True)
    key = f"{location_uuid}_{zone_uuid}"
    return (
        os.path.join(_REGISTRY_DIR, f"{key}.ubj"),
        os.path.join(_REGISTRY_DIR, f"{key}.meta.json"),
    )


def _load_cached_model(location_uuid, zone_uuid, features):
    """Inválido si: no existe, features distintas, o tiene > 7 días."""
    model_path, meta_path = _registry_paths(location_uuid, zone_uuid)
    if not os.path.exists(model_path) or not os.path.exists(meta_path):
        return None, {}, None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get("features") != features:
            return None, {}, None
        age_days = (datetime.now() - datetime.fromisoformat(meta["trained_at"])).days
        if age_days > 7:
            return None, {}, None
        modelo = xgb.XGBRegressor()
        modelo.load_model(model_path)
        return modelo, meta.get("metrics", {}), meta.get("q_conf")
    except Exception:
        return None, {}, None


def _save_model(modelo, location_uuid, zone_uuid, features, metrics, q_conf):
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

        cal_feats = get_calendario_features(current_date, org_config=org_config)
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
                    **cal_feats,
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

        # Join supercalendario
        cal_rows = pd.DataFrame(
            [get_calendario_features(fecha, org_config=org_config) for fecha in train["fecha"]],
            index=train.index,
        )
        for col in CALENDARIO_FEATURE_COLS:
            train[col] = cal_rows[col].values

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
        ] + CALENDARIO_FEATURE_COLS

        _reserved = set(_BASE_FEATURES)
        ext_cols_safe = [c for c in ext_cols if c not in _reserved]
        features = _BASE_FEATURES + ext_cols_safe

        X_train, y_train = train[features], train["total_visits"]

        # 3. MODELO: caché o entrenamiento
        hoy = datetime.today().date()
        es_produccion = abs((pd.to_datetime(falso_hoy).date() - hoy).days) <= 2

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

            # Conformal q — Fase 1: anchura constante para todos los horizontes.
            # El cuantil empírico con corrección de muestra finita garantiza
            # cobertura ≥ 1−α bajo intercambiabilidad (aprox. para series temporales).
            if len(X_cal) > 0:
                resid = np.abs(y_cal.values - np.maximum(0, modelo.predict(X_cal)))
                n_cal = len(resid)
                level = min(np.ceil((n_cal + 1) * (1 - _CONFORMAL_ALPHA)) / n_cal, 1.0)
                q_conf = float(np.quantile(resid, level, method="higher"))

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

        # Bandas conformes
        if q_conf is not None:
            lowers = [int(np.maximum(0, np.round(p - q_conf))) for p in valores_pred]
            uppers = [int(np.round(p + q_conf)) for p in valores_pred]
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
