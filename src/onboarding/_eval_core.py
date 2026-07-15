"""
Núcleo de evaluación walk-forward de features — utilizado por el Agente 4.

Extraído de src/lab/eval_features.py (que vive en .gitignore) para que el
pipeline de onboarding pueda importarlo en producción sin depender de lab/.
"""

from __future__ import annotations

from datetime import date

import holidays
import numpy as np
import pandas as pd
import xgboost as xgb

# supercalendario removed — calendar features dropped

# ── Constantes ────────────────────────────────────────────────────────────────

MIN_TRAIN_ROWS = 50

BASE_FEATURES: list[str] = [
    "es_finde",
    "es_festivo",
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
]

_FESTIVOS = holidays.ES(years=list(range(2023, 2029)))

_XGB_PARAMS: dict = dict(
    n_estimators=250,
    learning_rate=0.05,
    max_depth=4,
    random_state=42,
    early_stopping_rounds=20,
)


# ── Carga de datos ────────────────────────────────────────────────────────────


def _load_visitas(conn, location_uuid: str) -> pd.DataFrame:
    df = conn.execute(
        """
        SELECT fecha, SUM(total_visitas)::int AS total_visits
        FROM   visitas
        WHERE  ubicacion_id = ?
        GROUP  BY fecha
        ORDER  BY fecha
        """,
        [location_uuid],
    ).df()
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def _load_ext_feature(
    conn,
    location_uuid: str,
    feature_key: str,
    fecha_min: pd.Timestamp,
    fecha_max: pd.Timestamp,
) -> pd.Series:
    """
    Carga una feature de valores_señales con la estrategia de relleno de
    señales.fill_method: 'ffill' (mensual) o 'zero' (eventos sparse).
    """
    df = conn.execute(
        """
        SELECT fecha, valor::double precision AS valor
        FROM   valores_señales
        WHERE  ubicacion_id = ?
          AND  señal_id     = ?
          AND  fecha BETWEEN ? AND ?
        ORDER  BY fecha
        """,
        [location_uuid, feature_key, fecha_min.date(), fecha_max.date()],
    ).df()

    if df.empty:
        return pd.Series(dtype=float, name=feature_key)

    df["fecha"] = pd.to_datetime(df["fecha"])
    serie = df.set_index("fecha")["valor"]
    full_idx = pd.date_range(fecha_min, fecha_max, freq="D")
    return serie.reindex(full_idx).fillna(0.0).rename(feature_key)


# ── Construcción de la matriz de features ─────────────────────────────────────


def _build_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["es_finde"] = df["fecha"].dt.dayofweek.isin([5, 6]).astype(int)
    df["es_festivo"] = df["fecha"].apply(lambda d: int(d in _FESTIVOS))
    df["dia_semana"] = df["fecha"].dt.dayofweek
    df["dia_mes"] = df["fecha"].dt.day
    df["mes"] = df["fecha"].dt.month
    df["quincena"] = (df["dia_mes"] > 15).astype(int)
    df["vispera_festivo"] = df["fecha"].apply(
        lambda d: int((d + pd.Timedelta(days=1)) in _FESTIVOS)
    )
    df["lag_1d"] = df["total_visits"].shift(1)
    df["lag_7d"] = df["total_visits"].shift(7)
    df["lag_14d"] = df["total_visits"].shift(14)
    df["media_7d"] = df["total_visits"].rolling(7).mean()
    df["media_14d"] = df["total_visits"].rolling(14).mean()
    df["std_7d"] = df["total_visits"].rolling(7).std().fillna(0)

    return df.dropna(subset=BASE_FEATURES).reset_index(drop=True)


# ── Entrenamiento y evaluación ────────────────────────────────────────────────


def _wmape(reales: np.ndarray, preds: np.ndarray) -> float:
    s = float(reales.sum())
    return float(np.sum(np.abs(reales - preds)) / s) if s > 0 else float("nan")


def _fit_eval(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_eval: pd.DataFrame,
    y_eval: pd.Series,
) -> float:
    split = int(len(X_train) * 0.85)
    modelo = xgb.XGBRegressor(**_XGB_PARAMS)
    modelo.fit(
        X_train.iloc[:split],
        y_train.iloc[:split],
        eval_set=[
            (X_train.iloc[:split], y_train.iloc[:split]),
            (X_train.iloc[split:], y_train.iloc[split:]),
        ],
        verbose=False,
    )
    preds = np.maximum(0, modelo.predict(X_eval))
    return _wmape(y_eval.values, preds)


def _evaluate_feature(
    conn,
    feature_key: str,
    location_uuid: str,
    fecha_corte: date,
    horizonte: int,
    n_splits: int,
) -> list[dict]:
    df_vis = _load_visitas(conn, location_uuid)
    if df_vis.empty:
        print(f"    ⚠  Sin datos en visitas para {location_uuid[:8]}")
        return []

    df_full = _build_matrix(df_vis)
    fc = pd.Timestamp(fecha_corte)
    all_base = BASE_FEATURES

    feat_series = _load_ext_feature(
        conn,
        location_uuid,
        feature_key,
        df_full["fecha"].min(),
        fc,
    )
    if feat_series.empty:
        print(
            f"    ⚠  Sin datos en valores_señales para '{feature_key}' "
            "— ejecuta ingest_features.py"
        )
        return []

    results: list[dict] = []

    for k in range(n_splits):
        eval_end = fc - pd.Timedelta(days=k * horizonte)
        eval_start = eval_end - pd.Timedelta(days=horizonte - 1)
        train_end = eval_start - pd.Timedelta(days=1)

        df_train = df_full[df_full["fecha"] <= train_end]
        df_eval = df_full[(df_full["fecha"] >= eval_start) & (df_full["fecha"] <= eval_end)]

        if len(df_train) < MIN_TRAIN_ROWS or df_eval.empty:
            print(
                f"    ⚠  Split {k}: train={len(df_train)} filas — "
                f"saltando (mínimo {MIN_TRAIN_ROWS})"
            )
            continue

        w_base = _fit_eval(
            df_train[all_base],
            df_train["total_visits"],
            df_eval[all_base],
            df_eval["total_visits"],
        )

        df_train_f = df_train.copy()
        df_eval_f = df_eval.copy()
        df_train_f[feature_key] = df_train_f["fecha"].map(feat_series)
        df_eval_f[feature_key] = df_eval_f["fecha"].map(feat_series)

        n_nan_train = df_train_f[feature_key].isna().sum()
        n_nan_eval = df_eval_f[feature_key].isna().sum()
        if n_nan_train > 0 or n_nan_eval > 0:
            print(
                f"    ⚠  Split {k}: {feature_key} tiene NaN "
                f"(train={n_nan_train}, eval={n_nan_eval}) — cobertura insuficiente"
            )
            continue

        all_with_feat = all_base + [feature_key]
        w_feat = _fit_eval(
            df_train_f[all_with_feat],
            df_train_f["total_visits"],
            df_eval_f[all_with_feat],
            df_eval_f["total_visits"],
        )

        delta = w_feat - w_base
        print(
            f"    Split {k}  [{eval_start.date()} → {eval_end.date()}]"
            f"  base={w_base * 100:.2f}%  +feat={w_feat * 100:.2f}%"
            f"  delta={delta * 100:+.2f}pp"
        )

        results.append(
            {
                "señal_id": feature_key,
                "ubicacion_id": location_uuid,
                "indice_split": k,
                "fecha_eval_ini": eval_start.date(),
                "fecha_eval_fin": eval_end.date(),
                "n_entrenamiento": len(df_train),
                "n_evaluacion": len(df_eval),
                "wmape_baseline": w_base,
                "wmape_con_feat": w_feat,
                "wmape_delta": delta,
                "horizonte": horizonte,
            }
        )

    return results


# ── Escritura en DB ───────────────────────────────────────────────────────────


def _write_results(conn, results: list[dict]) -> None:
    conn.executemany(
        """
        INSERT INTO evaluaciones_señales
            (señal_id, ubicacion_id, indice_split,
             fecha_eval_ini, fecha_eval_fin,
             n_entrenamiento, n_evaluacion,
             wmape_baseline, wmape_con_feat, wmape_delta, horizonte)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["señal_id"],
                r["ubicacion_id"],
                r["indice_split"],
                r["fecha_eval_ini"],
                r["fecha_eval_fin"],
                r["n_entrenamiento"],
                r["n_evaluacion"],
                r["wmape_baseline"],
                r["wmape_con_feat"],
                r["wmape_delta"],
                r["horizonte"],
            )
            for r in results
        ],
    )


def _write_flags(conn, results: list[dict]) -> None:
    by_loc: dict[tuple, list] = {}
    for r in results:
        by_loc.setdefault((r["señal_id"], r["ubicacion_id"]), []).append(r["wmape_delta"])

    for (feat_key, loc_uuid), deltas in by_loc.items():
        conn.execute(
            """
            INSERT INTO activacion_señales (señal_id, ubicacion_id, status, evaluado_en)
            VALUES (?, ?, 'inactive', NOW())
            ON CONFLICT (señal_id, ubicacion_id) DO UPDATE
                SET evaluado_en = NOW()
            """,
            [feat_key, loc_uuid],
        )
