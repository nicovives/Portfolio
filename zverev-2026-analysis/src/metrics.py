
"""Métricas intrínsecas ponderadas por volumen y contrastes bootstrap por temporada."""

import numpy as np
import pandas as pd


def aggregate_intrinsic_metrics(df: pd.DataFrame) -> pd.Series:
    """Calcula el perfil estadístico agregado ponderado por volumen de puntos y juegos.

    Suma numeradores y denominadores antes de dividir para evitar el sesgo
    de promediar porcentajes de partidos con distinta duración.

    Parameters
    ----------
    df : pd.DataFrame
        Subconjunto de partidos en formato jugador-partido de un tenista.

    Returns
    -------
    pd.Series
        Serie con métricas clave: `matches`, `win_pct`, `tpw_pct`,
        `dominance_ratio`, porcentajes de 1.er y 2.º saque, `hold_pct`,
        `break_pct`, `hold_plus_break`, conversión/salvado de break points,
        `ace_pct` y `df_pct`.
    """
    svpt = df["svpt"].sum()
    opp_svpt = df["opp_svpt"].sum()
    first_in = df["1stIn"].sum()
    second_svpt = df["2nd_svpt"].sum()
    sv_gms = df["SvGms"].sum()
    opp_sv_gms = df["opp_SvGms"].sum()
    bp_faced = df["bpFaced"].sum()
    opp_bp_faced = df["opp_bpFaced"].sum()

    sv_won_pct = df["sv_pts_won"].sum() / svpt
    ret_won_pct = df["ret_pts_won"].sum() / opp_svpt
    sv_lost_pct = 1.0 - sv_won_pct

    hold_pct = df["sv_gms_won"].sum() / sv_gms if sv_gms > 0 else np.nan
    break_pct = df["breaks_won"].sum() / opp_sv_gms if opp_sv_gms > 0 else np.nan

    return pd.Series({
        "matches": len(df), # Número de partidos en la muestra
        "win_pct": df["won"].mean() * 100, # Porcentaje de victorias
        "tpw_pct": (df["tot_pts_won"].sum() / df["tot_pts_played"].sum()) * 100, # Porcentaje de puntos ganados
        "dominance_ratio": ret_won_pct / sv_lost_pct if sv_lost_pct > 0 else np.nan, # Proporción de dominancia
        "first_in_pct": (first_in / svpt) * 100, # Porcentaje de primeros servicios en
        "first_won_pct": (df["1stWon"].sum() / first_in) * 100 if first_in > 0 else np.nan, # Porcentaje de primeros servicios ganados
        "second_won_pct": (df["2ndWon"].sum() / second_svpt) * 100 if second_svpt > 0 else np.nan, # Porcentaje de segundos servicios ganados  
        "sv_won_pct": sv_won_pct * 100, # Porcentaje de servicios ganados
        "ret_won_pct": ret_won_pct * 100, # Porcentaje de puntos de devolución ganados
        "hold_pct": hold_pct * 100, # Porcentaje de juegos de servicio ganados
        "break_pct": break_pct * 100, # Porcentaje de puntos de ruptura ganados
        "hold_plus_break": (hold_pct + break_pct) * 100, # Suma de porcentajes de juegos de servicio y ruptura ganados
        "bp_saved_pct": (df["bpSaved"].sum() / bp_faced) * 100 if bp_faced > 0 else np.nan, # Porcentaje de puntos de ruptura salvados
        "bp_conv_pct": (df["breaks_won"].sum() / opp_bp_faced) * 100 if opp_bp_faced > 0 else np.nan, # Porcentaje de puntos de ruptura convertidos
        "ace_pct": (df["ace"].sum() / svpt) * 100, # Porcentaje de aces
        "df_pct": (df["df"].sum() / svpt) * 100, # Porcentaje de dobles faltas
    })


def season_profile(long_df: pd.DataFrame, player_name: str, group_cols: list[str] = ["season"]) -> pd.DataFrame:
    """Construye la tabla de evolución de métricas intrínsecas de un jugador.

    Parameters
    ----------
    long_df : pd.DataFrame
        Dataset en formato jugador-partido generado por `to_player_match_long`.
    player_name : str
        Nombre exacto del jugador tal como aparece en `player_name`.
    group_cols : list of str, default=["season"]
        Columnas de agrupación (por ejemplo, `["season", "surface"]`).

    Returns
    -------
    pd.DataFrame
        Tabla agregada con una fila por combinación de `group_cols`.
    """
    sub = long_df[long_df["player_name"] == player_name]
    return sub.groupby(group_cols, as_index=False).apply(
        aggregate_intrinsic_metrics, include_groups=False
    )


def bootstrap_season_diff(
    long_df: pd.DataFrame,
    player_name: str,
    season_a: int,
    season_b: int,
    metrics: list[str],
    n_boot: int = 5000,
    seed: int = 42,
) -> pd.DataFrame:
    """Estima la diferencia entre dos temporadas y su significancia mediante cluster bootstrap.

    Remuestrea partidos completos con reemplazo dentro de cada temporada para
    respetar la correlación interna de los puntos dentro de un mismo partido.

    Parameters
    ----------
    long_df : pd.DataFrame
        Dataset en formato jugador-partido.
    player_name : str
        Nombre exacto del jugador a evaluar.
    season_a : int
        Temporada de referencia (base).
    season_b : int
        Temporada objetivo a comparar (`season_b - season_a`).
    metrics : list of str
        Nombres de las métricas devueltas por `aggregate_intrinsic_metrics`.
    n_boot : int, default=5000
        Número de réplicas bootstrap.
    seed : int, default=42
        Semilla del generador aleatorio para reproducibilidad.

    Returns
    -------
    pd.DataFrame
        Tabla resumen con valores observados, diferencia (`diff`), intervalo
        de confianza al 95 % (`ci_95_low`, `ci_95_high`), `p_value` bilateral
        y bandera booleana `significant_95`.
    """
    rng = np.random.default_rng(seed)
    df_a = long_df[(long_df["player_name"] == player_name) & (long_df["season"] == season_a)]
    df_b = long_df[(long_df["player_name"] == player_name) & (long_df["season"] == season_b)]

    obs_a = aggregate_intrinsic_metrics(df_a)
    obs_b = aggregate_intrinsic_metrics(df_b)

    idx_a = np.arange(len(df_a))
    idx_b = np.arange(len(df_b))

    boot_diffs = {m: np.empty(n_boot) for m in metrics}
    for i in range(n_boot):
        samp_a = df_a.iloc[rng.choice(idx_a, size=len(idx_a), replace=True)]
        samp_b = df_b.iloc[rng.choice(idx_b, size=len(idx_b), replace=True)]
        res_a = aggregate_intrinsic_metrics(samp_a)
        res_b = aggregate_intrinsic_metrics(samp_b)
        for m in metrics:
            boot_diffs[m][i] = res_b[m] - res_a[m]

    rows = []
    for m in metrics:
        arr = boot_diffs[m]
        ci_low, ci_high = np.percentile(arr, [2.5, 97.5])
        # p-valor bilateral aproximado
        p_val = 2 * min(np.mean(arr <= 0), np.mean(arr >= 0))
        rows.append({
            "metric": m,
            f"val_{season_a}": round(obs_a[m], 2),
            f"val_{season_b}": round(obs_b[m], 2),
            "diff": round(obs_b[m] - obs_a[m], 2),
            "ci_95_low": round(ci_low, 2),
            "ci_95_high": round(ci_high, 2),
            "p_value": round(p_val, 4),
            "significant_95": not (ci_low <= 0 <= ci_high),
        })

    return pd.DataFrame(rows)