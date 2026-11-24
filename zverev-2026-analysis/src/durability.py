
"""Métricas de carga física, disponibilidad en Big Titles y valor acumulado de temporada."""

import numpy as np
import pandas as pd

ROUND_ORDER = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}

BIG_TITLE_PTS = {
    "G": {"R128": 10, "R64": 50, "R32": 100, "R16": 200, "QF": 400, "SF": 800, "F": 1300, "W": 2000},
    "M": {"R128": 10, "R64": 10, "R32": 50, "R16": 100, "QF": 200, "SF": 400, "F": 650, "W": 1000},
}


def compute_big_title_efficiency(df_season: pd.DataFrame) -> pd.DataFrame:
    """Calcula la disponibilidad y eficiencia anotadora en Grand Slams y Masters 1000.

    Identifica la ronda máxima alcanzada por cada jugador en cada Big Title de
    la temporada para cuantificar presencia y puntos medios por torneo jugado.

    Parameters
    ----------
    df_season : pd.DataFrame
        Dataset jugador-partido filtrado a una única temporada.

    Returns
    -------
    pd.DataFrame
        Tabla por jugador con `big_titles_played`, `big_title_pts`,
        `big_title_avail_pct` y `pts_per_big_title`.
    """
    big = df_season[df_season["tourney_level"].isin(["G", "M"])].copy()
    total_big_events = max(big["tourney_id"].nunique(), 1)
    big["r_ord"] = big["round"].map(ROUND_ORDER).fillna(0)

    # Quedarse con la ronda más profunda de cada jugador por torneo
    deepest = (
        big.sort_values("r_ord")
        .groupby(["player_name", "tourney_id", "tourney_level"], as_index=False)
        .last()
    )

    def _pts(row) -> int:
        res_key = "W" if (row["round"] == "F" and row["won"] == 1) else row["round"]
        return BIG_TITLE_PTS[row["tourney_level"]].get(res_key, 0)

    deepest["bt_pts"] = deepest.apply(_pts, axis=1)

    summary = (
        deepest.groupby("player_name", as_index=False)
        .agg(
            big_titles_played=("tourney_id", "nunique"),
            big_title_pts=("bt_pts", "sum"),
        )
    )
    summary["big_title_avail_pct"] = (summary["big_titles_played"] / total_big_events) * 100.0
    summary["pts_per_big_title"] = summary["big_title_pts"] / summary["big_titles_played"]
    return summary


def build_durability_table(
    df_adj: pd.DataFrame,
    season: int = 2026,
    min_matches: int = 25,
) -> pd.DataFrame:
    """Integra volumen competitivo, techo de nivel y valor acumulado por jugador.

    Combina métricas de disponibilidad con `peak_elo`, `dominance_ratio` y
    `net_pts_above_avg` (integral de puntos jugados multiplicados por la ventaja
    ajustada `adj_tpw_plus / 100`), ordenando por producción total descendente.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset jugador-partido con Elo y residuales del Bloque 2.
    season : int, default=2026
        Temporada a evaluar.
    min_matches : int, default=25
        Umbral mínimo de partidos disputados para entrar en la cohorte.

    Returns
    -------
    pd.DataFrame
        Tabla consolidada de techo vs. durabilidad con una fila por jugador.
    """
    df_s = df_adj[df_adj["season"] == season].copy()

    def _agg_player(g: pd.DataFrame) -> pd.Series:
        svpt = g["svpt"].sum()
        opp_svpt = g["opp_svpt"].sum()
        sv_won_pct = g["sv_pts_won"].sum() / svpt
        ret_won_pct = g["ret_pts_won"].sum() / opp_svpt
        sv_lost_pct = 1.0 - sv_won_pct
        dr = ret_won_pct / sv_lost_pct if sv_lost_pct > 0 else np.nan

        w = g["tot_pts_played"]
        adj_tpw = np.average(g["adj_tpw_plus"], weights=w)
        # Integral de temporada: volumen de puntos x ventaja ajustada por rival
        net_pts_above_avg = (w * (g["adj_tpw_plus"] / 100.0)).sum()

        return pd.Series({
            "matches": len(g),
            "wins": int(g["won"].sum()),
            "win_pct": g["won"].mean() * 100.0,
            "tournaments": g["tourney_id"].nunique(),
            "hours_on_court": g["minutes"].fillna(0).sum() / 60.0,
            "peak_elo": g["player_elo_overall"].max(),
            "avg_elo": g["player_elo_overall"].mean(),
            "dominance_ratio": dr,
            "adj_tpw_plus": adj_tpw,
            "net_pts_above_avg": net_pts_above_avg,
        })

    base = (
        df_s.groupby("player_name", as_index=False)
        .apply(_agg_player, include_groups=False)
    )
    base = base[base["matches"] >= min_matches].copy()

    bt = compute_big_title_efficiency(df_s)
    out = base.merge(bt, on="player_name", how="left")
    out[["big_titles_played", "big_title_pts", "big_title_avail_pct", "pts_per_big_title"]] = (
        out[["big_titles_played", "big_title_pts", "big_title_avail_pct", "pts_per_big_title"]].fillna(0.0)
    )
    return out.sort_values("net_pts_above_avg", ascending=False).reset_index(drop=True)


def player_durability_history(df_adj: pd.DataFrame, player_name: str) -> pd.DataFrame:
    """Extrae la evolución interanual de durabilidad y techo de un jugador específico.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset multitemporada con Elo y residuales del Bloque 2.
    player_name : str
        Nombre exacto del jugador a consultar.

    Returns
    -------
    pd.DataFrame
        Serie histórica (una fila por temporada disponible) con las mismas
        métricas generadas por `build_durability_table`.
    """
    frames = []
    for yr in sorted(df_adj["season"].unique()):
        tbl = build_durability_table(df_adj, season=int(yr), min_matches=1)
        row = tbl[tbl["player_name"] == player_name].copy()
        if not row.empty:
            row.insert(0, "season", int(yr))
            frames.append(row)
    return pd.concat(frames, ignore_index=True)