import os
import json
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
import holidays
import gc
from datetime import datetime, timedelta
from src.data_processing.geo_enrichment import get_geo_vals, GEO_FEATURE_COLS

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

# ── Registro de modelos ──────────────────────────────────────────────────────
_REGISTRY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'registry')

def _registry_paths(location_uuid, zone_uuid):
    os.makedirs(_REGISTRY_DIR, exist_ok=True)
    key = f"{location_uuid}_{zone_uuid}"
    return (
        os.path.join(_REGISTRY_DIR, f"{key}.ubj"),
        os.path.join(_REGISTRY_DIR, f"{key}.meta.json"),
    )

def _current_geo_version(location_uuid):
    """Devuelve valid_from del snapshot activo, o None si no hay datos Esri."""
    try:
        from src.data_processing.geo_enrichment import _GEO_PATH
        with open(_GEO_PATH, 'r', encoding='utf-8') as f:
            store = json.load(f)
        snapshots = store.get(location_uuid, [])
        activo = next((s for s in snapshots if isinstance(s, dict) and s.get('valid_to') is None), None)
        return activo.get('valid_from') if activo else None
    except Exception:
        return None

def _load_cached_model(location_uuid, zone_uuid, geo_version, features):
    """
    Carga modelo en caché si es válido.
    Inválido si: no existe, geo_version ha cambiado, features distintas, o tiene > 7 días.
    Devuelve (modelo, metrics_dict) o (None, {}).
    """
    model_path, meta_path = _registry_paths(location_uuid, zone_uuid)
    if not os.path.exists(model_path) or not os.path.exists(meta_path):
        return None, {}
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get('geo_snapshot_version') != geo_version:
            return None, {}
        if meta.get('features') != features:
            return None, {}
        age_days = (datetime.now() - datetime.fromisoformat(meta['trained_at'])).days
        if age_days > 7:
            return None, {}
        modelo = xgb.XGBRegressor()
        modelo.load_model(model_path)
        return modelo, meta.get('metrics', {})
    except Exception:
        return None, {}

def _save_model(modelo, location_uuid, zone_uuid, features, metrics, geo_version):
    model_path, meta_path = _registry_paths(location_uuid, zone_uuid)
    modelo.save_model(model_path)
    with open(meta_path, 'w') as f:
        json.dump({
            'location_uuid': location_uuid,
            'zone_uuid': zone_uuid,
            'trained_at': datetime.now().isoformat(),
            'geo_snapshot_version': geo_version,
            'features': features,
            'metrics': metrics,
        }, f, indent=2)

def invalidar_modelos_location(location_uuid):
    """
    Elimina todos los modelos en caché de una ubicación.
    Llamado automáticamente tras ingestar_snapshot_esri().
    """
    if not os.path.exists(_REGISTRY_DIR):
        return
    prefix = location_uuid
    eliminados = 0
    for fname in os.listdir(_REGISTRY_DIR):
        if fname.startswith(prefix):
            os.remove(os.path.join(_REGISTRY_DIR, fname))
            eliminados += 1
    return eliminados


# ── Predicción ───────────────────────────────────────────────────────────────

def ejecutar_auditoria_predictiva(df_master, location_uuid, zone_uuid, falso_hoy, horizonte_dias):
    modelo = None
    try:
        # 1. EXTRACCIÓN DE HISTÓRICO
        df_tienda = df_master[
            (df_master['location_id'] == location_uuid) &
            (df_master['zone_uuid'] == zone_uuid)
        ].copy()

        if df_tienda.empty:
            return {"error": "No hay datos históricos para esta zona."}

        df_tienda['fecha'] = pd.to_datetime(df_tienda['fecha'])
        df_tienda = df_tienda.groupby('fecha').agg({
            'total_visits': 'sum',
            'llueve': 'max',
            'temp_max': 'max',
            'temp_min': 'min',
            'es_festivo': 'max'
        }).reset_index().sort_values('fecha').reset_index(drop=True)

        geo_vals_pred = get_geo_vals(location_uuid)

        # 2. SEPARACIÓN DEL PASADO (TRAIN SET)
        fecha_corte = pd.to_datetime(falso_hoy)
        train = df_tienda[df_tienda['fecha'] < fecha_corte].copy()

        if len(train) < 30:
            return {"error": "Muestra histórica insuficiente para entrenar (mínimo 30 días previos)."}

        train['es_finde'] = train['fecha'].dt.dayofweek.isin([5, 6]).astype(int)
        train['dia_semana'] = train['fecha'].dt.dayofweek
        train['dia_mes'] = train['fecha'].dt.day
        train['mes'] = train['fecha'].dt.month
        train['quincena'] = (train['dia_mes'] > 15).astype(int)
        train['vispera_festivo'] = train['fecha'].apply(
            lambda d: 1 if (d + timedelta(days=1)) in festivos_espana else 0
        )
        train['mucho_calor'] = (train['temp_max'] >= 32.0).astype(int)
        train['mucho_frio'] = (train['temp_min'] <= 8.0).astype(int)
        train['clima_ideal'] = (
            (train['temp_max'] >= 18.0) & (train['temp_max'] <= 26.0) & (train['llueve'] == 0)
        ).astype(int)
        train['finde_lluvioso'] = train['es_finde'] * train['llueve']
        train['lag_1d'] = train['total_visits'].shift(1)
        train['lag_7d'] = train['total_visits'].shift(7)
        train['media_7d'] = train['total_visits'].rolling(7).mean()
        train['lag_14d'] = train['total_visits'].shift(14)
        train['media_14d'] = train['total_visits'].rolling(14).mean()
        train['std_7d'] = train['total_visits'].rolling(7).std().fillna(0)
        train = train.dropna().reset_index(drop=True)

        # Join temporal geoespacial
        geo_rows = pd.DataFrame(
            [get_geo_vals(location_uuid, fecha) for fecha in train['fecha']],
            index=train.index
        )
        geo_features_activos = [c for c in GEO_FEATURE_COLS if geo_rows[c].notna().any()]
        for col in geo_features_activos:
            train[col] = geo_rows[col].values

        features = [
            'es_finde', 'es_festivo', 'llueve', 'dia_semana', 'dia_mes', 'mes',
            'lag_1d', 'lag_7d', 'media_7d', 'quincena', 'vispera_festivo',
            'lag_14d', 'media_14d', 'std_7d', 'finde_lluvioso',
            'mucho_calor', 'mucho_frio', 'clima_ideal'
        ] + geo_features_activos

        X_train, y_train = train[features], train['total_visits']

        # 3. MODELO: caché o entrenamiento
        # Solo usamos caché en modo producción (falso_hoy ~ hoy).
        # En backtesting (falso_hoy en el pasado) siempre reentrenamos.
        hoy = datetime.today().date()
        es_produccion = abs((pd.to_datetime(falso_hoy).date() - hoy).days) <= 2
        geo_version = _current_geo_version(location_uuid) if es_produccion else None

        cache_hit = False
        cached_metrics = {}
        if es_produccion:
            modelo, cached_metrics = _load_cached_model(location_uuid, zone_uuid, geo_version, features)
            if modelo is not None:
                cache_hit = True

        if not cache_hit:
            split_idx = int(len(X_train) * 0.85)
            X_t, y_t = X_train.iloc[:split_idx], y_train.iloc[:split_idx]
            X_v, y_v = X_train.iloc[split_idx:], y_train.iloc[split_idx:]
            modelo = xgb.XGBRegressor(
                n_estimators=250,
                learning_rate=0.05,
                max_depth=4,
                random_state=42,
                early_stopping_rounds=20,
            )
            modelo.fit(X_t, y_t, eval_set=[(X_t, y_t), (X_v, y_v)], verbose=False)

        # 4. PREDICCIÓN AUTORREGRESIVA
        df_work = df_tienda[df_tienda['fecha'] < fecha_corte].copy()
        fechas_pred, valores_pred, valores_reales = [], [], []

        for i in range(horizonte_dias):
            current_date = fecha_corte + timedelta(days=i)
            fechas_pred.append(current_date.strftime('%Y-%m-%d'))

            real_row = df_tienda[df_tienda['fecha'] == current_date]
            tiene_real = not real_row.empty

            llueve = real_row['llueve'].values[0] if tiene_real else 0
            t_max = real_row['temp_max'].values[0] if tiene_real else 22.0
            t_min = real_row['temp_min'].values[0] if tiene_real else 12.0
            real_visits = real_row['total_visits'].values[0] if tiene_real else None
            valores_reales.append(real_visits)

            es_festivo = 1 if current_date in festivos_espana else 0
            es_finde = 1 if current_date.dayofweek in [5, 6] else 0

            visits_array = df_work['total_visits'].values
            lag_1d = visits_array[-1] if len(visits_array) >= 1 else 0
            lag_7d = visits_array[-7] if len(visits_array) >= 7 else 0
            lag_14d = visits_array[-14] if len(visits_array) >= 14 else 0
            media_7d = np.mean(visits_array[-7:]) if len(visits_array) >= 7 else 0
            media_14d = np.mean(visits_array[-14:]) if len(visits_array) >= 14 else 0
            std_7d = np.std(visits_array[-7:]) if len(visits_array) >= 7 else 0

            row = pd.DataFrame([{
                'es_finde': es_finde, 'es_festivo': es_festivo, 'llueve': llueve,
                'dia_semana': current_date.dayofweek, 'dia_mes': current_date.day,
                'mes': current_date.month, 'lag_1d': lag_1d, 'lag_7d': lag_7d,
                'media_7d': media_7d, 'quincena': 1 if current_date.day > 15 else 0,
                'vispera_festivo': 1 if (current_date + timedelta(days=1)) in festivos_espana else 0,
                'lag_14d': lag_14d, 'media_14d': media_14d, 'std_7d': std_7d,
                'finde_lluvioso': es_finde * llueve,
                'mucho_calor': 1 if t_max >= 32.0 else 0,
                'mucho_frio': 1 if t_min <= 8.0 else 0,
                'clima_ideal': 1 if (18.0 <= t_max <= 26.0 and llueve == 0) else 0,
                **{col: geo_vals_pred[col] for col in geo_features_activos}
            }])

            pred = np.maximum(0, np.round(modelo.predict(row[features])[0]))
            valores_pred.append(pred)
            new_row = pd.DataFrame({'fecha': [current_date], 'total_visits': [pred]})
            df_work = pd.concat([df_work, new_row], ignore_index=True)

        # 5. MÉTRICAS
        reales_validos = [r for r in valores_reales if pd.notna(r)]
        pred_validos = valores_pred[:len(reales_validos)]

        if reales_validos:
            mae = mean_absolute_error(reales_validos, pred_validos)
            sum_reales = np.sum(reales_validos)
            wmape = np.sum(np.abs(np.array(reales_validos) - np.array(pred_validos))) / sum_reales if sum_reales > 0 else 0
            acc_val = round((1 - wmape) * 100, 2)
            mae_val = round(mae, 1)
            wmape_val = round(wmape * 100, 2)
        else:
            acc_val = mae_val = wmape_val = "N/A"

        best_iter = cached_metrics.get('best_iteration') if cache_hit else getattr(modelo, 'best_iteration', None)

        # Persistir el modelo recién entrenado
        if not cache_hit and es_produccion and geo_version is not None:
            _save_model(
                modelo, location_uuid, zone_uuid, features,
                {"accuracy": acc_val, "mae": mae_val, "wmape_pct": wmape_val, "best_iteration": best_iter},
                geo_version,
            )

        return {
            "status": "success",
            "cache_hit": cache_hit,
            "metricas": {"accuracy": acc_val, "mae": mae_val, "wmape_pct": wmape_val, "arboles_optimos": best_iter},
            "grafica": {"fechas": fechas_pred, "reales": valores_reales, "predichos": valores_pred},
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        del modelo
        gc.collect()
