
"""Simulador Montecarlo acoplado para el contrafactual de lesiones de la temporada 2026."""

from dataclasses import dataclass
import numpy as np
import pandas as pd

# Escala oficial ATP (2024-2026) por ronda de eliminación
GS_LOSER_PTS = [10, 50, 100, 200, 400, 800, 1300]  # R128 -> F
GS_CHAMP_PTS = 2000

M1000_LOSER_PTS = [10, 50, 100, 200, 400, 650]     # R64 -> F (cuadro efectivo de 64)
M1000_CHAMP_PTS = 1000

ACTUAL_POINTS_MAP = {
    "G": {"R128": 10, "R64": 50, "R32": 100, "R16": 200, "QF": 400, "SF": 800, "F": 1300, "W": 2000},
    "M": {"R128": 10, "R64": 10, "R32": 50, "R16": 100, "QF": 200, "SF": 400, "F": 650, "W": 1000},
}


@dataclass(frozen=True)
class TournamentSpec:
    """Especificación estructural de un Big Title afectado por lesiones en 2026.

    Attributes
    ----------
    key : str
        Identificador corto del torneo.
    name_pattern : str
        Expresión regular para emparejar `tourney_name` en TennisMyLife.
    level : str
        Categoría del torneo (`"G"` para Grand Slam, `"M"` para Masters 1000).
    surface : str
        Superficie de juego (`"Clay"`, `"Grass"` o `"Hard"`).
    draw_size : int
        Tamaño del cuadro eliminatorio (128 o 64).
    best_of : int
        Formato de partido (5 sets o 3 sets).
    ref_date : str
        Fecha de referencia (`YYYY-MM-DD`) para extraer los ratings pre-torneo.
    alcaraz_missed : bool
        Indica si Carlos Alcaraz causó baja real en este torneo.
    sinner_missed : bool
        Indica si Jannik Sinner causó baja real en este torneo.
    """
    key: str
    name_pattern: str
    level: str          # "G" o "M"
    surface: str        # "Clay", "Grass", "Hard"
    draw_size: int      # 128 para GS, 64 para M1000
    best_of: int        # 5 para GS, 3 para M1000
    ref_date: str       # Fecha de corte aproximada del torneo en 2026
    alcaraz_missed: bool
    sinner_missed: bool


AFFECTED_BIG_TITLES_2026 = [
    # Ventana 1: solo baja Alcaraz (15 abr -> Wimbledon)
    TournamentSpec("madrid", "madrid", "M", "Clay", 64, 3, "2026-04-22", True, False),
    TournamentSpec("rome", "rome", "M", "Clay", 64, 3, "2026-05-06", True, False),
    TournamentSpec("roland_garros", "roland garros", "G", "Clay", 128, 5, "2026-05-24", True, False),
    TournamentSpec("wimbledon", "wimbledon", "G", "Grass", 128, 5, "2026-06-29", True, False),
    # Ventana 2: baja ambos (verano norteamericano)
    TournamentSpec("canada", "canada|montreal|toronto", "M", "Hard", 64, 3, "2026-08-02", True, True),
    TournamentSpec("cincinnati", "cincinnati", "M", "Hard", 64, 3, "2026-08-12", True, True),
    # Ventana 3: solo baja Sinner (US Open -> fin de temporada)
    TournamentSpec("us_open", "us open", "G", "Hard", 128, 5, "2026-08-31", False, True),
    TournamentSpec("shanghai", "shanghai", "M", "Hard", 64, 3, "2026-10-01", False, True),
    TournamentSpec("paris", "paris", "M", "Hard", 64, 3, "2026-10-26", False, True),
]


def bo3_to_bo5_prob(p3: np.ndarray) -> np.ndarray:
    """Convierte probabilidades de victoria al mejor de 3 sets a formato de 5 sets.

    Resuelve primero la probabilidad implícita de ganar un set `q` mediante
    Newton-Raphson sobre `p3 = q^2 * (3 - 2q)` y evalúa la binomial acumulada
    para 5 sets `p5 = q^3 * (10 - 15q + 6q^2)`.

    Parameters
    ----------
    p3 : np.ndarray
        Array de probabilidades de victoria al mejor de 3 sets en (0, 1).

    Returns
    -------
    np.ndarray
        Array con las probabilidades equivalentes al mejor de 5 sets.
    """
    p = np.clip(p3, 1e-6, 1.0 - 1e-6)
    q = p.copy()
    for _ in range(8):
        f = q * q * (3.0 - 2.0 * q) - p
        df = 6.0 * q * (1.0 - q)
        q = np.clip(q - f / np.maximum(df, 1e-9), 1e-6, 1.0 - 1e-6)
    return (q ** 3) * (10.0 - 15.0 * q + 6.0 * q * q)


def get_player_snapshot_elo(
    df_adj: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    surface: str,
    blend_weight: float = 0.5,
) -> pd.DataFrame:
    """Extrae la fotografía del Elo combinado de cada jugador antes de una fecha de corte.

    Si un jugador no tiene historial previo en la superficie solicitada, utiliza
    su Elo general como respaldo.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset histórico con columnas de Elo del Bloque 2.
    cutoff_date : pd.Timestamp
        Fecha límite superior (inclusive) para la consulta.
    surface : str
        Superficie del torneo objetivo (`"Hard"`, `"Clay"` o `"Grass"`).
    blend_weight : float, default=0.5
        Peso del Elo general en el cálculo de `elo_blend`.

    Returns
    -------
    pd.DataFrame
        Tabla por jugador con `player_elo_overall`, `player_elo_surface`,
        `elo_blend` y fecha de último partido (`last_played`).
    """
    hist = df_adj[df_adj["tourney_date"] <= cutoff_date].sort_values(["tourney_date", "match_num"])

    overall = (
        hist.groupby("player_name", as_index=False)
        .last()[["player_name", "player_elo_overall", "tourney_date"]]
        .rename(columns={"tourney_date": "last_played"})
    )

    surf_hist = hist[hist["surface"] == surface]
    surf_elo = (
        surf_hist.groupby("player_name", as_index=False)
        .last()[["player_name", "player_elo_surface"]]
    )

    snap = overall.merge(surf_elo, on="player_name", how="left")
    snap["player_elo_surface"] = snap["player_elo_surface"].fillna(snap["player_elo_overall"])
    snap["elo_blend"] = (
        blend_weight * snap["player_elo_overall"]
        + (1.0 - blend_weight) * snap["player_elo_surface"]
    )
    return snap


def compute_actual_affected_points(
    df_adj: pd.DataFrame,
    players: list[str],
    specs: list[TournamentSpec] = AFFECTED_BIG_TITLES_2026,
) -> pd.DataFrame:
    """Calcula los puntos ATP reales obtenidos en los 9 Big Titles afectados de 2026.

    Permite descontar estos torneos de la Race oficial y fijar los puntos base
    no simulados (primer trimestre y torneos ATP 500/250).

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset jugador-partido que incluye la temporada 2026.
    players : list of str
        Lista de jugadores a auditar.
    specs : list of TournamentSpec, default=AFFECTED_BIG_TITLES_2026
        Especificaciones de los torneos a contabilizar.

    Returns
    -------
    pd.DataFrame
        Matriz con filas por torneo y columnas con los puntos reales por jugador.
    """
    df_2026 = df_adj[df_adj["season"] == 2026].copy()
    round_rank = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}

    rows = []
    for spec in specs:
        sub_t = df_2026[
            (df_2026["tourney_level"] == spec.level)
            & (df_2026["tourney_name"].str.contains(spec.name_pattern, case=False, na=False))
        ]
        row = {"tournament": spec.key}
        for p in players:
            sp = sub_t[sub_t["player_name"] == p].copy()
            if sp.empty:
                row[p] = 0
                continue
            sp["r_ord"] = sp["round"].map(round_rank).fillna(0)
            last_m = sp.sort_values("r_ord").iloc[-1]
            res_key = "W" if (last_m["round"] == "F" and last_m["won"] == 1) else last_m["round"]
            row[p] = ACTUAL_POINTS_MAP[spec.level].get(res_key, 0)
        rows.append(row)

    return pd.DataFrame(rows)


def build_seeded_draws(draw_size: int, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    """Genera cuadros eliminatorios vectorizados respetando la geometría de cabezas de serie.

    Asume que los índices de jugadores están ordenados por rating (0 = cabeza
    de serie #1). Separa los bloques 1-2, 3-4, 5-8 y 9-16 en mitades, cuartos
    y octavos opuestos, y sortea aleatoriamente el resto del cuadro.

    Parameters
    ----------
    draw_size : int
        Número total de jugadores en el cuadro (64 o 128).
    n_sims : int
        Número de universos de simulación.
    rng : np.random.Generator
        Generador aleatorio de NumPy.

    Returns
    -------
    np.ndarray
        Matriz entera de forma `(n_sims, draw_size)` con los índices de jugador
        en cada posición del cuadro.
    """
    draws = np.empty((n_sims, draw_size), dtype=np.int32)

    s1_slot, s2_slot = 0, draw_size - 1
    s34_slots = np.array([draw_size // 2 - 1, draw_size // 2])
    s58_slots = np.array([draw_size // 4 - 1, draw_size // 4, 3 * draw_size // 4 - 1, 3 * draw_size // 4])
    s916_slots = np.array([
        draw_size // 8 - 1, draw_size // 8,
        3 * draw_size // 8 - 1, 3 * draw_size // 8,
        5 * draw_size // 8 - 1, 5 * draw_size // 8,
        7 * draw_size // 8 - 1, 7 * draw_size // 8,
    ])

    seeded_slots = set([s1_slot, s2_slot, *s34_slots, *s58_slots, *s916_slots])
    unseeded_slots = np.array([i for i in range(draw_size) if i not in seeded_slots])

    draws[:, s1_slot] = 0
    draws[:, s2_slot] = 1
    draws[:, s34_slots] = rng.permuted(np.broadcast_to(np.arange(2, 4), (n_sims, 2)), axis=1)
    draws[:, s58_slots] = rng.permuted(np.broadcast_to(np.arange(4, 8), (n_sims, 4)), axis=1)
    draws[:, s916_slots] = rng.permuted(np.broadcast_to(np.arange(8, 16), (n_sims, 8)), axis=1)
    draws[:, unseeded_slots] = rng.permuted(
        np.broadcast_to(np.arange(16, draw_size), (n_sims, draw_size - 16)), axis=1
    )
    return draws


def simulate_knockout_tournament(
    player_names: list[str],
    base_elos: np.ndarray,
    level: str,
    best_of: int,
    n_sims: int,
    rng: np.random.Generator,
    form_sigma: float = 25.0,
) -> dict[str, np.ndarray]:
    """Simula un torneo eliminatorio completo en paralelo para `n_sims` escenarios.

    Incorpora un choque gaussiano semanal de forma por torneo y asigna puntos
    ATP oficiales según la ronda de eliminación o campeonato.

    Parameters
    ----------
    player_names : list of str
        Nombres de los participantes ordenados por Elo descendente.
    base_elos : np.ndarray
        Array 1D de ratings Elo combinados alineado con `player_names`.
    level : str
        `"G"` para Grand Slam o `"M"` para Masters 1000.
    best_of : int
        Formato de sets (5 o 3).
    n_sims : int
        Número de simulaciones de Montecarlo.
    rng : np.random.Generator
        Generador aleatorio de NumPy.
    form_sigma : float, default=25.0
        Desviación estándar del ruido de forma semanal en puntos Elo.

    Returns
    -------
    dict of {str: np.ndarray}
        Mapa de nombre de jugador a array de puntos ganados de longitud `n_sims`.
    """
    draw_size = len(player_names)
    loser_pts = GS_LOSER_PTS if level == "G" else M1000_LOSER_PTS
    champ_pts = GS_CHAMP_PTS if level == "G" else M1000_CHAMP_PTS

    # Choque de forma semanal por torneo (varianza realista)
    sim_elos = base_elos[None, :] + rng.normal(0.0, form_sigma, size=(n_sims, draw_size))
    current = build_seeded_draws(draw_size, n_sims, rng)

    points = np.zeros((n_sims, draw_size), dtype=np.int32)
    sim_idx = np.arange(n_sims)[:, None]

    round_idx = 0
    while current.shape[1] > 1:
        p1 = current[:, 0::2]
        p2 = current[:, 1::2]

        e1 = np.take_along_axis(sim_elos, p1, axis=1)
        e2 = np.take_along_axis(sim_elos, p2, axis=1)
        p_win = 1.0 / (1.0 + 10.0 ** ((e2 - e1) / 400.0))
        if best_of == 5:
            p_win = bo3_to_bo5_prob(p_win)

        p1_wins = rng.random(p_win.shape) < p_win
        winners = np.where(p1_wins, p1, p2)
        losers = np.where(p1_wins, p2, p1)

        points[sim_idx, losers] = loser_pts[round_idx]
        current = winners
        round_idx += 1

    points[np.arange(n_sims), current[:, 0]] = champ_pts
    return {name: points[:, idx] for idx, name in enumerate(player_names)}


def simulate_atp_finals(
    player_names: list[str],
    base_elos: np.ndarray,
    n_sims: int,
    rng: np.random.Generator,
    form_sigma: float = 25.0,
) -> dict[str, np.ndarray]:
    """Simula el formato oficial de las ATP Finals (Round Robin + Semifinales + Final).

    Reparte a los 8 participantes en dos grupos de cuatro por parejas de cabezas
    de serie, suma 200 puntos por victoria en fase de grupos, 400 por semifinal
    ganada y 500 por el título.

    Parameters
    ----------
    player_names : list of str
        Exactamente 8 jugadores ordenados por Elo descendente.
    base_elos : np.ndarray
        Ratings Elo combinados en pista dura para los 8 jugadores.
    n_sims : int
        Número de simulaciones.
    rng : np.random.Generator
        Generador aleatorio de NumPy.
    form_sigma : float, default=25.0
        Desviación estándar del choque semanal de forma en puntos Elo.

    Returns
    -------
    dict of {str: np.ndarray}
        Mapa de nombre de jugador a array de puntos obtenidos en Turín.
    """
    assert len(player_names) == 8
    sim_elos = base_elos[None, :] + rng.normal(0.0, form_sigma, size=(n_sims, 8))
    points = np.zeros((n_sims, 8), dtype=np.int32)
    sim_idx = np.arange(n_sims)

    # Sorteo oficial por parejas: (0,1), (2,3), (4,5), (6,7) van a grupos opuestos
    group_a = np.empty((n_sims, 4), dtype=np.int32)
    group_b = np.empty((n_sims, 4), dtype=np.int32)
    for pair_idx in range(4):
        p_lo, p_hi = 2 * pair_idx, 2 * pair_idx + 1
        flip = rng.random(n_sims) < 0.5
        group_a[:, pair_idx] = np.where(flip, p_lo, p_hi)
        group_b[:, pair_idx] = np.where(flip, p_hi, p_lo)

    def _run_group(grp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        wins = np.zeros((n_sims, 4), dtype=np.int32)
        for i in range(4):
            for j in range(i + 1, 4):
                pi, pj = grp[:, i], grp[:, j]
                p_win = 1.0 / (1.0 + 10.0 ** ((sim_elos[sim_idx, pj] - sim_elos[sim_idx, pi]) / 400.0))
                i_wins = rng.random(n_sims) < p_win
                wins[:, i] += i_wins.astype(np.int32)
                wins[:, j] += (~i_wins).astype(np.int32)
                points[sim_idx, np.where(i_wins, pi, pj)] += 200
        # Desempate aleatorio pequeño en caso de igualdad de victorias RR
        order = np.argsort(-(wins + rng.uniform(0.0, 0.01, size=wins.shape)), axis=1)
        first = grp[sim_idx, order[:, 0]]
        second = grp[sim_idx, order[:, 1]]
        return first, second

    a1, a2 = _run_group(group_a)
    b1, b2 = _run_group(group_b)

    # Semifinales: A1 vs B2 y B1 vs A2
    p_sf1 = 1.0 / (1.0 + 10.0 ** ((sim_elos[sim_idx, b2] - sim_elos[sim_idx, a1]) / 400.0))
    sf1_w = np.where(rng.random(n_sims) < p_sf1, a1, b2)
    points[sim_idx, sf1_w] += 400

    p_sf2 = 1.0 / (1.0 + 10.0 ** ((sim_elos[sim_idx, a2] - sim_elos[sim_idx, b1]) / 400.0))
    sf2_w = np.where(rng.random(n_sims) < p_sf2, b1, a2)
    points[sim_idx, sf2_w] += 400

    # Final
    p_fin = 1.0 / (1.0 + 10.0 ** ((sim_elos[sim_idx, sf2_w] - sim_elos[sim_idx, sf1_w]) / 400.0))
    champ = np.where(rng.random(n_sims) < p_fin, sf1_w, sf2_w)
    points[sim_idx, champ] += 500

    return {name: points[:, idx] for idx, name in enumerate(player_names)}


def run_counterfactual_scenario(
    df_adj: pd.DataFrame,
    baseline_pts: dict[str, int],
    alcaraz_healthy: bool,
    sinner_healthy: bool,
    n_sims: int = 10_000,
    form_sigma: float = 25.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Orquesta la simulación acoplada de los 9 Big Titles y las ATP Finals de 2026.

    Reconstruye cada cuadro activando o excluyendo a Alcaraz y Sinner en sus
    ventanas reales de lesión (congelando su último Elo previo cuando entran en
    el contrafactual) y suma los resultados a los puntos base fijos.

    Parameters
    ----------
    df_adj : pd.DataFrame
        Dataset histórico con ratings Elo del Bloque 2.
    baseline_pts : dict of {str: int}
        Puntos ATP fijos de Zverev, Sinner y Alcaraz fuera de los 9 Big Titles.
    alcaraz_healthy : bool
        Si es True, reincorpora a Alcaraz en los torneos de su baja (abr-ago).
    sinner_healthy : bool
        Si es True, reincorpora a Sinner desde Canadá hasta las ATP Finals.
    n_sims : int, default=10_000
        Número de temporadas completas a simular.
    form_sigma : float, default=25.0
        Volatilidad semanal de forma en puntos Elo.
    seed : int, default=42
        Semilla aleatoria para reproducibilidad.

    Returns
    -------
    pd.DataFrame
        DataFrame de `n_sims` filas con los puntos totales simulados de cada
        miembro del Big 3 y la columna `year_end_no1` indicando el ganador.
    """
    rng = np.random.default_rng(seed)
    big3 = ["Alexander Zverev", "Jannik Sinner", "Carlos Alcaraz"]
    totals = {p: np.full(n_sims, baseline_pts[p], dtype=np.int32) for p in big3}

    # Últimos Elo congelados justo antes de cada lesión
    alcaraz_pre_date = pd.Timestamp("2026-04-15")
    sinner_pre_date = df_adj[
        (df_adj["season"] == 2026) & (df_adj["player_name"] == "Jannik Sinner")
    ]["tourney_date"].max()

    # 1. Simular los 9 Big Titles afectados
    for spec in AFFECTED_BIG_TITLES_2026:
        cutoff = pd.Timestamp(spec.ref_date)
        snap = get_player_snapshot_elo(df_adj, cutoff, spec.surface)

        # Filtrar jugadores activos en los últimos 12 meses para construir el cuadro
        active_cut = cutoff - pd.Timedelta(days=365)
        field = snap[snap["last_played"] >= active_cut].copy()

        # Excluir a lesionados según el escenario elegido
        if spec.alcaraz_missed and not alcaraz_healthy:
            field = field[field["player_name"] != "Carlos Alcaraz"]
        elif spec.alcaraz_missed and alcaraz_healthy:
            alc_snap = get_player_snapshot_elo(df_adj, alcaraz_pre_date, spec.surface)
            alc_row = alc_snap[alc_snap["player_name"] == "Carlos Alcaraz"]
            field = pd.concat([field[field["player_name"] != "Carlos Alcaraz"], alc_row], ignore_index=True)

        if spec.sinner_missed and not sinner_healthy:
            field = field[field["player_name"] != "Jannik Sinner"]
        elif spec.sinner_missed and sinner_healthy:
            sin_snap = get_player_snapshot_elo(df_adj, sinner_pre_date, spec.surface)
            sin_row = sin_snap[sin_snap["player_name"] == "Jannik Sinner"]
            field = pd.concat([field[field["player_name"] != "Jannik Sinner"], sin_row], ignore_index=True)

        field = field.sort_values("elo_blend", ascending=False).head(spec.draw_size).reset_index(drop=True)
        res = simulate_knockout_tournament(
            player_names=field["player_name"].tolist(),
            base_elos=field["elo_blend"].to_numpy(dtype=np.float64),
            level=spec.level,
            best_of=spec.best_of,
            n_sims=n_sims,
            rng=rng,
            form_sigma=form_sigma,
        )
        for p in big3:
            if p in res:
                totals[p] += res[p]

    # 2. Simular las ATP Finals (Turín, Hard indoor)
    turin_snap = get_player_snapshot_elo(df_adj, pd.Timestamp("2026-11-10"), "Hard")
    turin_field = turin_snap[turin_snap["last_played"] >= pd.Timestamp("2026-01-01")].copy()
    if not sinner_healthy:
        turin_field = turin_field[turin_field["player_name"] != "Jannik Sinner"]
    else:
        sin_hard = get_player_snapshot_elo(df_adj, sinner_pre_date, "Hard")
        sin_row = sin_hard[sin_hard["player_name"] == "Jannik Sinner"]
        turin_field = pd.concat([turin_field[turin_field["player_name"] != "Jannik Sinner"], sin_row], ignore_index=True)

    turin_top8 = turin_field.sort_values("elo_blend", ascending=False).head(8).reset_index(drop=True)
    res_turin = simulate_atp_finals(
        player_names=turin_top8["player_name"].tolist(),
        base_elos=turin_top8["elo_blend"].to_numpy(dtype=np.float64),
        n_sims=n_sims,
        rng=rng,
        form_sigma=form_sigma,
    )
    for p in big3:
        if p in res_turin:
            totals[p] += res_turin[p]

    out = pd.DataFrame(totals)
    out["year_end_no1"] = out[big3].idxmax(axis=1)
    return out