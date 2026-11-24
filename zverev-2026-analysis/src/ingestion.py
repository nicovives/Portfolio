
"""Ingesta y transformación de los CSV anuales de TennisMyLife a formato jugador-partido."""

from pathlib import Path
import pandas as pd

# Aces
# Double Faults
# Service Points Played
# First Serves In
# First Serves Won
# Second Serves Won
# Service Games Played
# Break Points Saved
# Break Points Faced

STAT_COLS = [
    "ace", "df", "svpt", "1stIn", "1stWon", "2ndWon",
    "SvGms", "bpSaved", "bpFaced"
]

def load_tml_seasons(raw_dir: str | Path, years: range = range(2021, 2027)) -> pd.DataFrame:
    """Carga y concatena los archivos CSV anuales de TennisMyLife.

    Añade la columna `season` correspondiente a cada archivo y convierte
    `tourney_date` a formato datetime.

    Parameters
    ----------
    raw_dir : str or Path
        Directorio que contiene los archivos `<año>.csv`.
    years : range, default=range(2021, 2027)
        Rango de temporadas a cargar.

    Returns
    -------
    pd.DataFrame
        Tabla consolidada de partidos (una fila por partido).
    """
    raw_path = Path(raw_dir)
    frames = []
    for year in years:
        file_path = raw_path / f"{year}.csv"
        df = pd.read_csv(file_path, low_memory=False)
        df["season"] = year
        frames.append(df)

    matches = pd.concat(frames, ignore_index=True)
    matches["tourney_date"] = pd.to_datetime(
        matches["tourney_date"].astype(str), format="%Y%m%d", errors="coerce"
    )
    return matches


def to_player_match_long(matches: pd.DataFrame, exclude_davis_cup: bool = True) -> pd.DataFrame:
    """Convierte el dataset de partidos a formato largo jugador-partido.

    Desdobla cada partido en dos filas (ganador y perdedor), descarta
    walkovers/descalificaciones y partidos sin estadísticas de servicio,
    y calcula totales derivados de puntos y juegos.

    Parameters
    ----------
    matches : pd.DataFrame
        DataFrame crudo de TennisMyLife con prefijos `winner_`/`loser_`.
    exclude_davis_cup : bool, default=True
        Si es True, excluye partidos con `tourney_level == "D"`.

    Returns
    -------
    pd.DataFrame
        Dataset ordenado cronológicamente con dos filas por partido,
        indicador binario `won`, estadísticas propias, del rival (`opp_*`)
        y variables agregables (`sv_pts_won`, `ret_pts_won`, `tot_pts_played`, etc.).
    """
    df = matches.copy()

    # Filtrar walkovers y opcionalmente Copa Davis
    df = df[~df["score"].fillna("").str.contains("W/O|DEF", case=False)]
    if exclude_davis_cup and "tourney_level" in df.columns:
        df = df[df["tourney_level"] != "D"]

    common_cols = [
        "season", "tourney_id", "tourney_name", "surface",
        "tourney_level", "tourney_date", "match_num", "round",
        "best_of", "minutes", "score"
    ]
    common_cols = [c for c in common_cols if c in df.columns]

    def build_side(prefix: str, opp_prefix: str, won: int) -> pd.DataFrame:
        role = "winner" if prefix == "w" else "loser"
        opp_role = "loser" if prefix == "w" else "winner"

        rename_map = {
            f"{role}_id": "player_id",
            f"{role}_name": "player_name",
            f"{role}_rank": "player_rank",
            f"{opp_role}_id": "opp_id",
            f"{opp_role}_name": "opp_name",
            f"{opp_role}_rank": "opp_rank",
        }
        for col in STAT_COLS:
            rename_map[f"{prefix}_{col}"] = col
            rename_map[f"{opp_prefix}_{col}"] = f"opp_{col}"

        available = [c for c in rename_map if c in df.columns]
        side = df[common_cols + available].rename(columns=rename_map).copy()
        side["won"] = won
        return side

    long_df = pd.concat(
        [build_side("w", "l", won=1), build_side("l", "w", won=0)],
        ignore_index=True
    )

    # Limpieza de partidos sin box score de saque válido
    valid_stats = (
        long_df["svpt"].notna() & (long_df["svpt"] > 0) &
        long_df["opp_svpt"].notna() & (long_df["opp_svpt"] > 0)
    )
    long_df = long_df[valid_stats].copy()

    # Variables derivadas por partido (útiles para agregación y bootstrap)
    long_df["sv_pts_won"] = long_df["1stWon"] + long_df["2ndWon"]
    long_df["ret_pts_won"] = long_df["opp_svpt"] - (long_df["opp_1stWon"] + long_df["opp_2ndWon"])
    long_df["tot_pts_won"] = long_df["sv_pts_won"] + long_df["ret_pts_won"]
    long_df["tot_pts_played"] = long_df["svpt"] + long_df["opp_svpt"]
    long_df["2nd_svpt"] = long_df["svpt"] - long_df["1stIn"]
    long_df["sv_gms_won"] = long_df["SvGms"] - (long_df["bpFaced"] - long_df["bpSaved"])
    long_df["breaks_won"] = long_df["opp_bpFaced"] - long_df["opp_bpSaved"]

    return long_df.sort_values(["tourney_date", "match_num"]).reset_index(drop=True)