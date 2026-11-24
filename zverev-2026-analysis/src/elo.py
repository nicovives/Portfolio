
"""Motor de rating Elo dinámico por superficie y modelo WLS ajustado por calidad del rival."""

from collections import defaultdict
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROUND_ORDER = {
    "RR": 1, "R128": 2, "R64": 3, "R32": 4, "R16": 5,
    "QF": 6, "SF": 7, "BR": 8, "F": 9,
}

BASE_ELO = 1500.0


def expected_win_prob(elo_a: float, elo_b: float) -> float:
    """Calcula la probabilidad logística de victoria del jugador A frente a B.

    Parameters
    ----------
    elo_a : float
        Rating Elo pre-partido del jugador A.
    elo_b : float
        Rating Elo pre-partido del jugador B.

    Returns
    -------
    float
        Probabilidad esperada de victoria en el intervalo (0, 1).
    """
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def dynamic_k(matches_played: int, tourney_level: str) -> float:
    """Calcula el factor de actualización K decreciente estilo FiveThirtyEight.

    Reduce la sensibilidad del rating a medida que el jugador acumula historial
    y aplica un multiplicador de 1.1 en torneos de Grand Slam.

    Parameters
    ----------
    matches_played : int
        Número de partidos previos disputados por el jugador en la serie.
    tourney_level : str
        Código de categoría del torneo (`"G"` para Grand Slam).

    Returns
    -------
    float
        Factor K aplicable a la actualización del partido actual.
    """
    k = 250.0 / ((matches_played + 5.0) ** 0.4)
    return k * 1.1 if tourney_level == "G" else k


def compute_dynamic_elo(
    matches: pd.DataFrame,
    blend_weight: float = 0.5,
    exclude_davis_cup: bool = True,
) -> pd.DataFrame:
    """Calcula ratings Elo generales, por superficie y combinados sin data leakage.

    Recorre los partidos en orden cronológico estricto (fecha, torneo, jerarquía
    de ronda y número de partido). Almacena los ratings pre-partido antes de
    aplicar la actualización post-resultado.

    Parameters
    ----------
    matches : pd.DataFrame
        DataFrame crudo de partidos (se recomienda incluir 2018-2020 como burn-in).
    blend_weight : float, default=0.5
        Peso asignado al Elo general frente al Elo de superficie en `elo_blend`.
    exclude_davis_cup : bool, default=True
        Si es True, excluye partidos de Copa Davis.

    Returns
    -------
    pd.DataFrame
        Tabla por partido con los Elo pre-partido de ganador (`w_*`) y perdedor
        (`l_*`), el Elo combinado y la probabilidad pre-partido del ganador.
    """
    df = matches.copy()
    df = df[~df["score"].fillna("").str.contains("W/O|DEF", case=False)]
    if exclude_davis_cup and "tourney_level" in df.columns:
        df = df[df["tourney_level"] != "D"]

    df["round_num"] = df["round"].map(ROUND_ORDER).fillna(0).astype(int)
    df["surface"] = df["surface"].fillna("Hard")
    df = df.sort_values(
        ["tourney_date", "tourney_id", "round_num", "match_num"]
    ).reset_index(drop=True)

    overall_elo = defaultdict(lambda: BASE_ELO)
    overall_n = defaultdict(int)
    surface_elo = defaultdict(lambda: defaultdict(lambda: BASE_ELO))
    surface_n = defaultdict(lambda: defaultdict(int))

    records = []
    for row in df.itertuples(index=False):
        w_id, l_id = row.winner_id, row.loser_id
        surf = row.surface
        lvl = getattr(row, "tourney_level", "A")

        # 1. Guardar ratings PRE-partido (cero leakage)
        w_ov, l_ov = overall_elo[w_id], overall_elo[l_id]
        w_sf, l_sf = surface_elo[surf][w_id], surface_elo[surf][l_id]

        w_blend = blend_weight * w_ov + (1.0 - blend_weight) * w_sf
        l_blend = blend_weight * l_ov + (1.0 - blend_weight) * l_sf

        records.append({
            "tourney_id": row.tourney_id,
            "match_num": row.match_num,
            "winner_id": w_id,
            "loser_id": l_id,
            "w_elo_overall": w_ov,
            "l_elo_overall": l_ov,
            "w_elo_surface": w_sf,
            "l_elo_surface": l_sf,
            "w_elo_blend": w_blend,
            "l_elo_blend": l_blend,
            "w_win_prob": expected_win_prob(w_blend, l_blend),
        })

        # 2. Actualizar Elo general
        p_ov = expected_win_prob(w_ov, l_ov)
        overall_elo[w_id] = w_ov + dynamic_k(overall_n[w_id], lvl) * (1.0 - p_ov)
        overall_elo[l_id] = l_ov + dynamic_k(overall_n[l_id], lvl) * (0.0 - (1.0 - p_ov))
        overall_n[w_id] += 1
        overall_n[l_id] += 1

        # 3. Actualizar Elo de superficie
        p_sf = expected_win_prob(w_sf, l_sf)
        surface_elo[surf][w_id] = w_sf + dynamic_k(surface_n[surf][w_id], lvl) * (1.0 - p_sf)
        surface_elo[surf][l_id] = l_sf + dynamic_k(surface_n[surf][l_id], lvl) * (0.0 - (1.0 - p_sf))
        surface_n[surf][w_id] += 1
        surface_n[surf][l_id] += 1

    return pd.DataFrame(records)


def attach_elo_to_long(long_df: pd.DataFrame, elo_matches: pd.DataFrame) -> pd.DataFrame:
    """Incorpora los ratings Elo pre-partido al dataset largo jugador-partido.

    Parameters
    ----------
    long_df : pd.DataFrame
        Tabla jugador-partido del Bloque 1.
    elo_matches : pd.DataFrame
        Salida de `compute_dynamic_elo`.

    Returns
    -------
    pd.DataFrame
        Dataset enriquecido con `player_elo_*`, `opp_elo_*`,
        `expected_win_prob` y `tpw_pct` por partido.
    """
    winners = elo_matches[[
        "tourney_id", "match_num", "winner_id", "loser_id",
        "w_elo_overall", "l_elo_overall", "w_elo_surface", "l_elo_surface",
        "w_elo_blend", "l_elo_blend", "w_win_prob",
    ]].rename(columns={
        "winner_id": "player_id",
        "loser_id": "opp_id",
        "w_elo_overall": "player_elo_overall",
        "l_elo_overall": "opp_elo_overall",
        "w_elo_surface": "player_elo_surface",
        "l_elo_surface": "opp_elo_surface",
        "w_elo_blend": "player_elo_blend",
        "l_elo_blend": "opp_elo_blend",
        "w_win_prob": "expected_win_prob",
    })

    losers = elo_matches[[
        "tourney_id", "match_num", "loser_id", "winner_id",
        "l_elo_overall", "w_elo_overall", "l_elo_surface", "w_elo_surface",
        "l_elo_blend", "w_elo_blend", "w_win_prob",
    ]].rename(columns={
        "loser_id": "player_id",
        "winner_id": "opp_id",
        "l_elo_overall": "player_elo_overall",
        "w_elo_overall": "opp_elo_overall",
        "l_elo_surface": "player_elo_surface",
        "w_elo_surface": "opp_elo_surface",
        "l_elo_blend": "player_elo_blend",
        "w_elo_blend": "opp_elo_blend",
    })
    losers["expected_win_prob"] = 1.0 - losers.pop("w_win_prob")

    elo_long = pd.concat([winners, losers], ignore_index=True)
    merged = long_df.merge(
        elo_long,
        on=["tourney_id", "match_num", "player_id", "opp_id"],
        how="inner",
        validate="one_to_one",
    )
    merged["tpw_pct"] = (merged["tot_pts_won"] / merged["tot_pts_played"]) * 100.0
    return merged


def fit_opponent_adjusted_tpw(long_with_elo: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    """Ajusta un modelo WLS para aislar el rendimiento del sesgo de calidad del rival.

    Modela `tpw_pct ~ opp_elo_blend + C(surface) + C(best_of)` ponderando cada
    observación por `tot_pts_played`. El residual (`adj_tpw_plus`) mide cuántos
    puntos porcentuales más ganó el jugador respecto a un tenista ATP medio
    frente al mismo calendario.

    Parameters
    ----------
    long_with_elo : pd.DataFrame
        Dataset jugador-partido devuelto por `attach_elo_to_long`.

    Returns
    -------
    df_adj : pd.DataFrame
        Copia del DataFrame con `expected_tpw_pct` y `adj_tpw_plus`.
    model : statsmodels.regression.linear_model.RegressionResultsWrapper
        Objeto del modelo WLS ajustado para diagnóstico de coeficientes y R².
    """
    df = long_with_elo.dropna(
        subset=["tpw_pct", "opp_elo_blend", "surface", "best_of", "tot_pts_played"]
    ).copy()

    model = smf.wls(
        formula="tpw_pct ~ opp_elo_blend + C(surface) + C(best_of)",
        data=df,
        weights=df["tot_pts_played"],
    ).fit()

    df["expected_tpw_pct"] = model.predict(df)
    df["adj_tpw_plus"] = df["tpw_pct"] - df["expected_tpw_pct"]
    return df, model


def summarize_sos_and_adjusted(
    df_adj: pd.DataFrame,
    player_name: str,
    group_cols: list[str] = ["season"],
) -> pd.DataFrame:
    """Resume dureza de calendario (SoS), Elo pico y rendimiento ajustado por temporada.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset con residuales devuelto por `fit_opponent_adjusted_tpw`.
    player_name : str
        Nombre exacto del jugador a auditar.
    group_cols : list of str, default=["season"]
        Columnas de agrupación.

    Returns
    -------
    pd.DataFrame
        Resumen con volumen de partidos, Elo pico y final, `avg_opp_elo`,
        balance frente a rivales de élite (Elo >= 2000), `raw_tpw_pct`,
        `expected_tpw_pct` y `adj_tpw_plus`.
    """
    sub = df_adj[df_adj["player_name"] == player_name]

    def _agg(g: pd.DataFrame) -> pd.Series:
        w = g["tot_pts_played"]
        raw_tpw = (g["tot_pts_won"].sum() / w.sum()) * 100.0
        exp_tpw = np.average(g["expected_tpw_pct"], weights=w)
        adj_tpw = np.average(g["adj_tpw_plus"], weights=w)
        elite = g[g["opp_elo_blend"] >= 2000]
        return pd.Series({
            "matches": len(g),
            "peak_elo_overall": g["player_elo_overall"].max(),
            "end_elo_overall": g.sort_values("tourney_date")["player_elo_overall"].iloc[-1],
            "avg_opp_elo": g["opp_elo_blend"].mean(),
            "elite_matches_2000p": len(elite),
            "elite_win_pct": elite["won"].mean() * 100.0 if len(elite) > 0 else np.nan,
            "raw_tpw_pct": raw_tpw,
            "expected_tpw_pct": exp_tpw,
            "adj_tpw_plus": adj_tpw,
        })

    return sub.groupby(group_cols, as_index=False).apply(_agg, include_groups=False)


def bootstrap_adjusted_diff(
    df_adj: pd.DataFrame,
    player_name: str,
    season_a: int,
    season_b: int,
    n_boot: int = 5000,
    seed: int = 42,
) -> dict:
    """Evalúa la significancia del cambio en `adj_tpw_plus` entre dos temporadas.

    Aplica cluster bootstrap a nivel partido manteniendo la ponderación por
    puntos jugados en cada réplica.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset con residuales ajustados por rival.
    player_name : str
        Nombre exacto del jugador.
    season_a : int
        Temporada base.
    season_b : int
        Temporada objetivo (`season_b - season_a`).
    n_boot : int, default=5000
        Número de réplicas bootstrap.
    seed : int, default=42
        Semilla aleatoria.

    Returns
    -------
    dict
        Diccionario con el `adj_tpw_plus` de cada temporada, diferencia en
        puntos porcentuales (`diff_pp`), tupla `ci_95`, `p_value` y
        `significant_95`.
    """
    rng = np.random.default_rng(seed)
    a = df_adj[(df_adj["player_name"] == player_name) & (df_adj["season"] == season_a)]
    b = df_adj[(df_adj["player_name"] == player_name) & (df_adj["season"] == season_b)]

    val_a = np.average(a["adj_tpw_plus"], weights=a["tot_pts_played"])
    val_b = np.average(b["adj_tpw_plus"], weights=b["tot_pts_played"])

    diffs = np.empty(n_boot)
    for i in range(n_boot):
        sa = a.iloc[rng.integers(0, len(a), size=len(a))]
        sb = b.iloc[rng.integers(0, len(b), size=len(b))]
        diffs[i] = (
            np.average(sb["adj_tpw_plus"], weights=sb["tot_pts_played"])
            - np.average(sa["adj_tpw_plus"], weights=sa["tot_pts_played"])
        )

    ci_low, ci_high = np.percentile(diffs, [2.5, 97.5])
    p_val = 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0))
    return {
        f"adj_tpw_{season_a}": round(val_a, 2),
        f"adj_tpw_{season_b}": round(val_b, 2),
        "diff_pp": round(val_b - val_a, 2),
        "ci_95": (round(ci_low, 2), round(ci_high, 2)),
        "p_value": round(p_val, 4),
        "significant_95": not (ci_low <= 0 <= ci_high),
    }