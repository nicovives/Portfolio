<a id="top"></a>

<p align="center">
  <strong>🌐 Language / Idioma:</strong>&nbsp;
  <a href="#es">🇪🇸 Español</a> &nbsp;|&nbsp;
  <a href="#en">🇬🇧 English</a>
</p>

---

<a id="es"></a>

# Metodología y Decisiones Técnicas

Este documento detalla las decisiones estadísticas, formulaciones matemáticas y limitaciones asumidas en el estudio de la temporada ATP 2026 de Alexander Zverev.

---

## 1. Preparación de datos (`src/ingestion.py`)

* **Formato largo (*player-match*):** cada partido del esquema original de TennisMyLife (`winner_*` / `loser_*`) se desdobla en dos observaciones independientes (una por jugador), preservando tanto las métricas propias como las del rival (`opp_*`).
* **Filtros de calidad:**
  * Se excluyen *walkovers* y descalificaciones (`W/O`, `DEF`), ya que distorsionan los porcentajes de victoria sin información real de juego.
  * Se excluye Copa Davis (`tourney_level == "D"`) por su calendario, incentivos y formato atípicos frente al circuito ATP regular.
  * Se filtran partidos sin estadísticas válidas de servicio (`svpt > 0` y `opp_svpt > 0`).

---

## 2. Nivel intrínseco e inferencia estadística (`src/metrics.py`)

### Ponderación por volumen
Todas las métricas de temporada (`tpw_pct`, `dominance_ratio`, `hold_pct`, `second_won_pct`, etc.) se calculan agregando primero numeradores y denominadores sobre la temporada completa:

$$\text{DR} = \frac{\sum \text{Puntos ganados al resto} / \sum \text{Puntos jugados al resto}}{1 - \left(\sum \text{Puntos ganados al saque} / \sum \text{Puntos jugados al saque}\right)}$$

Promediar ratios a nivel partido sesgaría el estimador al otorgar el mismo peso a un duelo rápido de dos sets que a una semifinal de Grand Slam a cinco sets.

### Cluster bootstrap a nivel partido
Los puntos dentro de un mismo partido no son observaciones independientes (comparten rival, pista, condiciones y estado físico). Un test $z$ clásico de proporciones sobre miles de puntos inflaría artificialmente la significancia estadística. Para evaluar las diferencias **2026 vs. 2024** y **2026 vs. 2025**, se aplica *bootstrap* no paramétrico remuestreando **partidos completos con reemplazo** ($B = 5.000$ réplicas, `seed=42`), recalculando las ratios ponderadas en cada réplica y extrayendo el intervalo de confianza percentil al 95 % junto con el $p$-valor bilateral.

---

## 3. Rating Elo dinámico y ajuste por calidad del rival (`src/elo.py`)

### Motor Elo híbrido sin *data leakage*
* **Periodo de calentamiento (*burn-in*):** el algoritmo se inicializa en `1500` con la temporada **2018** y se ejecuta sobre 2018–2026, utilizando 2018–2020 únicamente como calentamiento para estabilizar los ratings antes de analizar el periodo 2021–2026.
* **Orden cronológico estricto:** los partidos se ordenan por `tourney_date`, `tourney_id`, jerarquía explícita de ronda (`RR` a `F`) y `match_num`. Para cada encuentro se registran los ratings **antes** del partido y solo después se actualizan.
* **Factor $K$ dinámico (esquema FiveThirtyEight):**

$$K_i = \frac{250}{(N_i + 5)^{0.4}} \cdot m_{\text{nivel}}, \quad m_{\text{nivel}} = \begin{cases} 1{,}1 & \text{si Grand Slam (G)} \\ 1{,}0 & \text{resto del circuito} \end{cases}$$

* **Elo combinado (*Blended Elo* 50/50):** para paliar la escasez muestral en superficies cortas como hierba, cada valoración pre-partido promedia al 50 % el Elo general y el Elo específico de la superficie.

### Modelo WLS de rendimiento ajustado (`adj_tpw_plus`)
Para aislar el nivel del jugador del calendario afrontado, se ajusta una regresión lineal por mínimos cuadrados ponderados (`WLS`, usando `tot_pts_played` como peso) sobre todo el dataset 2021–2026:

$$\text{TPW\%}_{i} = \beta_0 + \beta_1 \cdot \text{opp\_elo\_blend}_{i} + \boldsymbol{\gamma}^\top \text{Superficie}_{i} + \delta \cdot \text{BestOf}_{i} + \varepsilon_{i}$$

* **Diagnóstico del modelo:** `opp_elo_blend` presenta un coeficiente altamente significativo de **$-0{,}0085$** ($t = -44{,}85$, $p < 0{,}001$, IC 95 % $[-0{,}009,\,-0{,}008]$): cada +100 puntos Elo del rival reducen en ~0,85 pp el `TPW%` esperado.
* **Interpretación del $R^2$ (`0,059`):** el $R^2$ bajo es intencionado y deseable en este diseño. El modelo omite deliberadamente el Elo del **propio jugador** precisamente para que su talento intrínseco quede capturado en el residual $\hat{\varepsilon}_i = \text{TPW\%}_i - \widehat{\text{TPW\%}}_i$ (`adj_tpw_plus`). Un `adj_tpw_plus` positivo cuantifica cuántos puntos porcentuales más ganó el jugador respecto a un tenista ATP promedio frente a esos mismos rivales y condiciones.

---

## 4. Simulación de Montecarlo contrafactual (`src/simulation.py`)

### Diseño acoplado y anclaje a la temporada real
Simular por separado cuántos puntos habrían ganado Sinner o Alcaraz ignora que el tenis es un **juego de suma cero**: su presencia en un cuadro reduce simultáneamente los puntos esperados de Zverev al poder eliminarlo en rondas previas. Por ello se simulan cuadros completos con todos los participantes activos compitiendo entre sí ($N = 10.000$ temporadas por escenario).

* **Puntos base fijos (`baseline_pts`):** se parte de la Race oficial previa a Turín (`9.350` Zverev, `7.950` Sinner, `6.100` Alcaraz) y se descuentan los puntos reales sumados en los 9 *Big Titles* afectados (`6.610`, `4.050` y `1.450` respectivamente). Los puntos restantes (`2.740`, `3.900` y `4.650`) fijan de forma exacta el primer trimestre (Australia, Indian Wells, Miami, Montecarlo) y todos los torneos ATP 500/250 realmente disputados.
* **Ventanas de lesión modeladas:**
  1. *Madrid, Roma, Roland Garros y Wimbledon:* baja de Alcaraz (lesión desde el 15 de abril).
  2. *Canadá y Cincinnati:* baja simultánea de Alcaraz y Sinner.
  3. *US Open, Shanghái, París y ATP Finals:* baja de Sinner (lesión tras Wimbledon).
* **Congelación de rating en contrafactuales:** cuando un jugador lesionado se reincorpora a un torneo en un escenario contrafactual, participa con su último `elo_blend` registrado inmediatamente antes de su lesión (`2026-04-15` para Alcaraz; último partido en Wimbledon para Sinner).
* **Geometría de cuadros y ATP Finals:** los torneos eliminatorios respetan la separación oficial de cabezas de serie (`1–2`, `3–4`, `5–8`, `9–16`). Las ATP Finals se simulan con su formato específico (2 grupos de 4 por parejas de cabezas de serie, +200 por victoria en *Round Robin*, +400 en semifinales y +500 en final), usando el corte de Elo a `2026-11-10` para evitar *leakage* de los partidos reales de Turín.
* **Conversión de probabilidad `Bo3 -> Bo5`:** en Grand Slams la probabilidad Elo (calibrada predominantemente en partidos a 3 sets) se transforma a 5 sets resolviendo numéricamente (Newton-Raphson) la probabilidad implícita por set $q$ a partir de $p_3 = q^2(3 - 2q)$ y evaluando $p_5 = q^3(10 - 15q + 6q^2)$.
* **Volatilidad semanal de forma:** en cada torneo cada jugador recibe una perturbación gaussiana independiente $\eta \sim \mathcal{N}(0, 25^2)$ puntos Elo para reflejar fluctuaciones realistas de forma semanal.

---

## 5. Durabilidad y valor acumulado (`src/durability.py`)

Para integrar en una sola métrica el *trade-off* entre **techo de nivel** y **disponibilidad física**, se define la producción neta sobre la media ATP (`net_pts_above_avg`) como la suma acumulada a lo largo de la temporada del volumen de puntos jugados por la ventaja ajustada de cada partido:

$$\text{Valor Acumulado}_{j} = \sum_{i \in \mathcal{M}_j} \text{tot\_pts\_played}_{i} \cdot \frac{\text{adj\_tpw\_plus}_{i}}{100}$$

Se complementa con la disponibilidad sobre el total de *Big Titles* del calendario regular (`big_title_avail_pct`, Grand Slams + Masters 1000) y el rendimiento medio por gran torneo jugado (`pts_per_big_title`).

---

## 6. Limitaciones y supuestos conservadores

1. **Omisión de torneos ATP 500 perdidos por lesión (sesgo conservador a favor de Zverev):** el contrafactual no añade puntos hipotéticos de los ATP 500 que Alcaraz (Barcelona, Queen's) o Sinner (gira asiática/europea) dejaron de jugar. Incluirlos reduciría todavía más la probabilidad simulada de Zverev.
2. **Estacionariedad del Elo durante la baja:** al congelar el Elo previo a la lesión, el modelo asume que un jugador sano habría mantenido su nivel sin caídas de forma prolongadas (ni óxido competitivo, visible en el caso real de Alcaraz en el US Open y Shanghái).
3. **Elo sin ajuste por emparejamientos estilísticos (*matchups*):** la probabilidad logística depende únicamente de la diferencia de Elo combinado por superficie, sin modelar ventajas tácticas específicas cara a cara (H2H).
4. **Inexistencia de datos de *tracking* 3D:** al emplear estadísticas agregadas de partido (*box score*), el Bloque 1 captura resultados del servicio y el resto pero no velocidad de bola, colocación exacta ni posición en pista.

...

<p align="right"><a href="#top">↑ Volver arriba</a> · <a href="#en">Read in English 🇬🇧</a></p>

---

<a id="en"></a>

# Methodology & Technical Design

This document details the statistical modeling choices, mathematical formulations, and key limitations behind the 2026 Alexander Zverev season analysis.

---

## 1. Data Ingestion & Reshaping (`src/ingestion.py`)

* **Long player-match format:** raw TennisMyLife files store one row per match (`winner_*` / `loser_*`). Each match is unpivoted into two player-centric rows (winner and loser), retaining both player statistics and opponent statistics (`opp_*`).
* **Quality filters:**
  * Walkovers and defaults (`W/O`, `DEF`) are excluded to avoid distorting win rates without played-point data.
  * Davis Cup ties (`tourney_level == "D"`) are excluded due to non-standard scheduling, incentives, and match conditions.
  * Matches missing valid service box-score records (`svpt > 0` and `opp_svpt > 0`) are dropped.

---

## 2. Intrinsic Performance & Statistical Inference (`src/metrics.py`)

### Volume-Weighted Aggregation
All season-level metrics (`tpw_pct`, `dominance_ratio`, `hold_pct`, `second_won_pct`, etc.) aggregate numerators and denominators across the full season prior to division:

$$\text{DR} = \frac{\sum \text{Return Points Won} / \sum \text{Return Points Played}}{1 - \left(\sum \text{Service Points Won} / \sum \text{Service Points Played}\right)}$$

Averaging match-level percentages directly would introduce length bias by weighting a brief straight-set match equally to a five-set Grand Slam semifinal.

### Match-Level Cluster Bootstrap
Points within a single match are not independent observations—they share opponent, surface, weather, and physical state. A standard two-proportion $z$-test across thousands of points would severely understate variance and inflate statistical significance. To evaluate **2026 vs. 2024** and **2026 vs. 2025** differences rigorously, we apply a non-parametric cluster bootstrap resampling **entire matches with replacement** ($B = 5,000$ resamples, `seed=42`), recomputing volume-weighted ratios in each draw to derive 95% percentile confidence intervals and two-sided empirical $p$-values.

---

## 3. Dynamic Elo Engine & Opponent-Adjusted WLS (`src/elo.py`)

### Leakage-Free Blended Elo
* **Burn-in period:** ratings initialize at `1500` in **2018** and update across 2018–2026; seasons 2018–2020 serve strictly as burn-in so ratings stabilize before evaluating 2021–2026.
* **Strict chronological ordering:** matches are sorted by `tourney_date`, `tourney_id`, explicit round hierarchy (`RR` through `F`), and `match_num`. Pre-match ratings are logged **before** applying post-match updates, eliminating temporal data leakage.
* **Dynamic $K$-factor (FiveThirtyEight formulation):**

$$K_i = \frac{250}{(N_i + 5)^{0.4}} \cdot m_{\text{level}}, \quad m_{\text{level}} = \begin{cases} 1.1 & \text{if Grand Slam (G)} \\ 1.0 & \text{all other tour levels} \end{cases}$$

* **50/50 Surface-Blended Elo:** to mitigate small-sample noise on shorter swings such as grass, each pre-match rating (`elo_blend`) weights overall Elo and surface-specific Elo equally (50/50).

### Opponent-Adjusted WLS Regression (`adj_tpw_plus`)
To separate player quality from Strength of Schedule (SoS), we fit a Weighted Least Squares (`WLS`) regression across the entire 2021–2026 dataset using `tot_pts_played` as observation weights:

$$\text{TPW\%}_{i} = \beta_0 + \beta_1 \cdot \text{opp\_elo\_blend}_{i} + \boldsymbol{\gamma}^\top \text{Surface}_{i} + \delta \cdot \text{BestOf}_{i} + \varepsilon_{i}$$

* **Model diagnostics:** `opp_elo_blend` yields a highly significant slope of **$-0.0085$** ($t = -44.85$, $p < 0.001$, 95% CI $[-0.009, -0.008]$)—every +100 opponent Elo points lowers expected `TPW%` by roughly 0.85 percentage points.
* **Interpreting $R^2$ (`0.059`):** a low $R^2$ is intentional by construction. The player’s **own** rating is deliberately omitted from the predictors so that intrinsic playing strength flows into the residual $\hat{\varepsilon}_i = \text{TPW\%}_i - \widehat{\text{TPW\%}}_i$ (`adj_tpw_plus`). A positive `adj_tpw_plus` quantifies how many percentage points above an average ATP player the focal player won against the exact same opponents and match conditions.

---

## 4. Coupled Monte Carlo Counterfactual (`src/simulation.py`)

### Zero-Sum Tournament Coupling & Baseline Anchoring
Estimating Sinner’s or Alcaraz’s missed points in isolation violates the zero-sum nature of knockout tennis: reintroducing them into a draw does not merely add points to their ledgers—it also lowers Zverev’s expected points whenever they eliminate him in earlier rounds. Accordingly, full tournament draws are simulated jointly across all active competitors ($N = 10,000$ runs per scenario).

* **Fixed baseline points (`baseline_pts`):** starting from the official pre-Turin ATP Race (`9,350` Zverev, `7,950` Sinner, `6,100` Alcaraz), we subtract actual points earned across the 9 affected Big Titles (`6,610`, `4,050`, and `1,450`, respectively). The remaining fixed baselines (`2,740`, `3,900`, and `4,650`) preserve exact Q1 results (Australian Open, Indian Wells, Miami, Monte Carlo) and all ATP 500/250 points actually earned.
* **Modeled injury windows:**
  1. *Madrid, Rome, Roland Garros, Wimbledon:* Alcaraz absent (injured April 15).
  2. *Canada, Cincinnati:* both Alcaraz and Sinner absent.
  3. *US Open, Shanghai, Paris, ATP Finals:* Sinner absent (injured post-Wimbledon).
* **Rating freeze under counterfactuals:** whenever an injured player is reinstated in a counterfactual scenario, he enters with his last pre-injury `elo_blend` (`2026-04-15` for Alcaraz; final Wimbledon match for Sinner).
* **Draw geometry & ATP Finals rules:** knockout draws enforce official seeding separation (`1–2`, `3–4`, `5–8`, `9–16`). The ATP Finals are simulated using their exact format (two four-player round-robin groups drawn in seeded pairs; +200 per round-robin win, +400 per semifinal win, +500 for the title) using a `2026-11-10` Elo cutoff to prevent leakage from actual Turin matches.
* **`Bo3 -> Bo5` win-probability conversion:** because Elo ratings are calibrated primarily on best-of-three matches, Grand Slam win probabilities are scaled to best-of-five by solving numerically (Newton-Raphson) for the implied single-set win probability $q$ from $p_3 = q^2(3 - 2q)$ and evaluating $p_5 = q^3(10 - 15q + 6q^2)$.
* **Weekly form volatility:** in every simulated tournament, each entrant receives an independent Gaussian form shock $\eta \sim \mathcal{N}(0, 25^2)$ Elo points to reflect realistic week-to-week variance.

---

## 5. Durability & Cumulative Season Value (`src/durability.py`)

To capture the trade-off between **peak level** and **availability** on a single scale, net points above ATP average (`net_pts_above_avg`) integrates volume and opponent-adjusted quality across all matches played in a season:

$$\text{Cumulative Value}_{j} = \sum_{i \in \mathcal{M}_j} \text{tot\_pts\_played}_{i} \cdot \frac{\text{adj\_tpw\_plus}_{i}}{100}$$

This metric is paired with Big Title availability (`big_title_avail_pct`, share of Grand Slams and Masters 1000s contested) and scoring efficiency per Big Title played (`pts_per_big_title`).

---

## 6. Key Limitations & Conservative Assumptions

1. **Omitted ATP 500 events (conservative bias favoring Zverev):** the counterfactual does not credit Alcaraz (e.g., Barcelona, Queen’s) or Sinner (Asian/European indoor 500s) with hypothetical points from missed ATP 500 tournaments. Including them would further reduce Zverev’s simulated Year-End No. 1 odds.
2. **Elo stationarity during injury windows:** freezing pre-injury ratings assumes healthy players would have maintained their baseline level without extended form slumps (or post-layoff rust, as seen in Alcaraz’s actual US Open and Shanghai return).
3. **No matchup-specific adjustments:** win probabilities depend solely on surface-blended Elo differentials and do not explicitly model stylistic head-to-head (H2H) edges.
4. **Box-score granularity:** without proprietary 3D Hawk-Eye tracking data, Module 1 captures serve and return outcomes rather than ball velocity, shot placement, or court positioning.

...

<p align="right"><a href="#top">↑ Back to top</a> · <a href="#es">Leer en español 🇪🇸</a></p>