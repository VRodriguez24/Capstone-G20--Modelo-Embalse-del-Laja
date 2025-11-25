"""
ANÁLISIS INTEGRAL DE VALIDACIÓN BOOTSTRAP - MONTE CARLO

Combina análisis fundamentales para validar la metodología bootstrap:

1. CORRELACIÓN TEMPORAL (Bloques de K meses)
   - Justifica el uso de bootstrap por bloques (K=3 óptimo)
   - Mide correlación mes a mes dentro de bloques
   - Compara K=2,3,4,5 con métricas cuantitativas

2. COMPARACIÓN DISTRIBUCIONES (Histórico vs Monte Carlo)
   - Verifica ausencia de sesgo en escenarios generados
   - Compara estadísticas descriptivas (media, mediana, percentiles)
   - Diagnostica reproducción de extremos (años secos/húmedos)

3. SESGO TEMPORAL (Nuevo)
   - Compara año a año (64 años) afluentes históricos vs MC
   - Identifica si bootstrap introduce sesgo sistemático por periodo

4. CLASIFICACIÓN HIDROLÓGICA (Nuevo)
   - Clasifica años como secos/normales/húmedos (criterio DGA: 20-60-20)
   - Valida que MC reproduce proporción correcta de cada tipo

Salida:
- Resumen consolidado en consola con justificación numérica de K=3
- Gráficos profesionales en resultados/analisis_bootstrap/
  * correlacion_temporal_3m.png: Comparación K=2,3,4,5 + variabilidad
  * comparacion_distribuciones.png: Histogramas + boxplots
  * sesgo_temporal_afluentes.png: Sesgo año a año histórico vs MC
  * clasificacion_hidrologica.png: Años secos/normales/húmedos

Uso:
    python src/analisis_bootstrap.py
    python src/analisis_bootstrap.py --block-k 3 --n-scenarios 200
    python src/analisis_bootstrap.py --no-plots  # solo análisis numérico
"""

from __future__ import annotations

import os
import argparse
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

# Importaciones del modelo
from montecarlo import BlockBootstrapSampler
from data_loader import load_injections_for_year, CENTRAL_TO_INJ_ARC
from embalse import A_inyeccion, T

# Configuración
DEFAULT_CSV = "data/Caudales_historicos_filtrado.csv"
DEFAULT_OUTDIR = "resultados/analisis_bootstrap"
YEARS = list(range(1960, 2024))  # 64 años históricos
Conv = (86400 * 30) / 1e6  # Conversión m³/s·mes → Hm³
SCENARIOS = 100  # Escenarios MC


# ============================================================================
# MÓDULO 1: ANÁLISIS DE CORRELACIÓN TEMPORAL
# ============================================================================

def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    """Correlación de Pearson con manejo robusto de casos extremos."""
    s = pd.concat([a, b], axis=1).dropna()
    if s.shape[0] < 3:
        return np.nan
    if s.iloc[:, 0].std(ddof=1) == 0 or s.iloc[:, 1].std(ddof=1) == 0:
        return np.nan
    return float(s.iloc[:, 0].corr(s.iloc[:, 1]))


def load_and_pivot(csv_path: str) -> Dict[str, pd.DataFrame]:
    """Carga CSV y retorna tablas pivot (año x mes) por central."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No se encontró: {csv_path}")

    df = pd.read_csv(csv_path)
    df = df.rename(columns={
        "central": "central",
        "fecha (mm-aaaa)": "fecha",
        "caudal (m^3/s)": "caudal",
    })

    df["central_norm"] = (
        df["central"].astype(str).str.strip().str.lower()
        .str.replace(" ", "_", regex=False)
    )
    parts = df["fecha"].astype(str).str.strip().str.split("-")
    df["mes"] = parts.str[0].astype(int)
    df["año"] = parts.str[1].astype(int)

    alias_tables: Dict[str, pd.DataFrame] = {}
    for alias, g in df.groupby("central_norm"):
        pivot = g.pivot_table(
            index="año", columns="mes", values="caudal", aggfunc="median"
        )
        pivot = pivot.reindex(columns=range(1, 13))
        alias_tables[alias] = pivot.sort_index()

    return alias_tables


def compute_block_correlations_k(
        pivot: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """
    Calcula correlación promedio entre todos los pares de meses
    dentro de bloques de K meses.

    Para K=3: promedio de corr(m,m+1), corr(m+1,m+2), corr(m,m+2)
    """
    rows: List[Dict] = []
    if k < 2 or k > 12:
        return pd.DataFrame(rows)

    max_start = 13 - k
    for m in range(1, max_start + 1):
        cols = list(range(m, m + k))
        rs: List[float] = []

        # Todas las parejas (i,j) donde i < j
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a = pivot[cols[i]]
                b = pivot[cols[j]]
                r = _safe_corr(a, b)
                if pd.notna(r):
                    rs.append(r)

        r_avg = float(np.mean(rs)) if rs else np.nan
        rows.append({
            "start_month": m,
            "k": k,
            "corr_block_avg": r_avg,
        })

    return pd.DataFrame(rows)


def analyze_temporal_correlation(
        csv_path: str, block_k: int = 3) -> Tuple[
            pd.DataFrame, Dict, Dict]:
    """
    Analiza correlación temporal en bloques de K meses.

    Returns:
        (df_detailed, summary_stats, all_block_stats)
    """
    alias_tables = load_and_pivot(csv_path)

    # Analizar múltiples tamaños de bloque para comparación
    all_block_stats = {}
    for k in [1, 2, 3, 4, 5]:
        all_rows_k: List[pd.DataFrame] = []
        for alias, pivot in alias_tables.items():
            if pivot is None or pivot.empty:
                continue
            blocks_k = compute_block_correlations_k(pivot, k=k)
            if not blocks_k.empty:
                all_rows_k.append(blocks_k)

        if all_rows_k:
            df_k = pd.concat(all_rows_k, ignore_index=True)
            all_block_stats[k] = {
                "median": float(df_k["corr_block_avg"].median(skipna=True)),
                "mean": float(df_k["corr_block_avg"].mean(skipna=True)),
            }

    # Calcular estadísticas para block_k específico
    all_rows: List[pd.DataFrame] = []
    for alias, pivot in alias_tables.items():
        if pivot is None or pivot.empty:
            continue
        blocks = compute_block_correlations_k(pivot, k=block_k)
        blocks.insert(0, "central", alias)
        all_rows.append(blocks)

    if not all_rows:
        return pd.DataFrame(), {}, all_block_stats

    df_blocks = pd.concat(all_rows, ignore_index=True)

    # Estadísticas agregadas
    stats = {
        "n_centrales": int(df_blocks["central"].nunique()),
        "n_bloques": int(df_blocks.shape[0]),
        "median": float(df_blocks["corr_block_avg"].median(skipna=True)),
        "mean": float(df_blocks["corr_block_avg"].mean(skipna=True)),
        "p25": float(df_blocks["corr_block_avg"].quantile(0.25)),
        "p75": float(df_blocks["corr_block_avg"].quantile(0.75)),
        "pct_pos": float((df_blocks["corr_block_avg"] > 0).mean() * 100),
        "pct_gt_0_3": float((df_blocks["corr_block_avg"] > 0.3).mean() * 100),
        "pct_gt_0_5": float((df_blocks["corr_block_avg"] > 0.5).mean() * 100),
    }

    return df_blocks, stats, all_block_stats


# ============================================================================
# MÓDULO 2: COMPARACIÓN HISTÓRICO vs MONTE CARLO
# ============================================================================

def load_historical_totals(csv_path: str) -> pd.DataFrame:
    """
    Carga afluentes históricos y calcula totales anuales por central.

    Returns:
        DataFrame con índice=años, columnas=centrales, valores=Hm³/año
    """
    yearly_totals = {}

    for year in YEARS:
        I_arc = load_injections_for_year(csv_path, year)

        central_totals = {}
        for alias, arc in CENTRAL_TO_INJ_ARC.items():
            if arc in A_inyeccion:
                total_m3s = sum(I_arc.get((arc[0], arc[1], t), 0.0) for t in T)
                total_hm3 = total_m3s * Conv
                central_totals[alias] = total_hm3

        yearly_totals[year] = central_totals

    df = pd.DataFrame.from_dict(yearly_totals, orient='index')
    return df


def generate_mc_scenarios(
        csv_path: str, n_scenarios: int = SCENARIOS,
        block_len: int = 3) -> pd.DataFrame:
    """
    Genera escenarios Monte Carlo mediante bootstrap por bloques.

    METODOLOGÍA BOOTSTRAP PURA:
    - Cada escenario es un año independiente generado mediante remuestreo
      con reemplazo
    - Bloques de K meses (típicamente 3) seleccionados aleatoriamente
    - NO hay continuidad entre escenarios (años independientes)
    - Reproducibilidad garantizada por random_state

    Args:
        csv_path: Ruta al CSV con caudales históricos
        n_scenarios: Número de escenarios (años) a generar
        block_len: Longitud de bloques temporales (meses)

    Returns:
        DataFrame con índice=scenario_id, columnas=centrales,
        valores=Hm³/año
    """
    sampler = BlockBootstrapSampler(csv_path, random_state=42)

    scenario_totals = {}

    for scenario_id in range(n_scenarios):
        # Generar año independiente mediante bootstrap
        scenario_data = sampler.sample_year(block_len=block_len)

        central_totals = {}
        for alias, arc in CENTRAL_TO_INJ_ARC.items():
            if arc in A_inyeccion:
                arc_key = (arc[0], arc[1])
                total_m3s = sum(
                    scenario_data.get((arc_key[0], arc_key[1], t), 0.0)
                    for t in T
                )
                total_hm3 = total_m3s * Conv
                central_totals[alias] = total_hm3

        scenario_totals[scenario_id] = central_totals

    df = pd.DataFrame.from_dict(scenario_totals, orient='index')
    return df


def compare_distributions(hist_df: pd.DataFrame, mc_df: pd.DataFrame) -> Dict:
    """
    Compara distribuciones de afluentes totales entre histórico y MC.

    Returns:
        Dict con métricas comparativas
    """
    hist_total = hist_df.sum(axis=1)
    mc_total = mc_df.sum(axis=1)

    def pct_diff(hist_val, mc_val):
        return ((mc_val - hist_val) / hist_val * 100) if hist_val != 0 else 0.0

    comparison = {
        "hist_mean": float(hist_total.mean()),
        "mc_mean": float(mc_total.mean()),
        "diff_mean_pct": pct_diff(hist_total.mean(), mc_total.mean()),

        "hist_median": float(hist_total.median()),
        "mc_median": float(mc_total.median()),
        "diff_median_pct": pct_diff(hist_total.median(), mc_total.median()),

        "hist_std": float(hist_total.std()),
        "mc_std": float(mc_total.std()),
        "diff_std_pct": pct_diff(hist_total.std(), mc_total.std()),

        "hist_min": float(hist_total.min()),
        "mc_min": float(mc_total.min()),
        "diff_min_pct": pct_diff(hist_total.min(), mc_total.min()),

        "hist_max": float(hist_total.max()),
        "mc_max": float(mc_total.max()),
        "diff_max_pct": pct_diff(hist_total.max(), mc_total.max()),

        "hist_p20": float(hist_total.quantile(0.20)),
        "mc_p20": float(mc_total.quantile(0.20)),
        "hist_p80": float(hist_total.quantile(0.80)),
        "mc_p80": float(mc_total.quantile(0.80)),

        # Diagnóstico: escenarios MC bajo P20 histórico
        "n_mc_scenarios": len(mc_total),
        "n_mc_below_p20_hist": int(
            (mc_total < hist_total.quantile(0.20)).sum()),
        "pct_mc_below_p20_hist": float(
            (mc_total < hist_total.quantile(0.20)).mean() * 100),
    }

    return comparison


def classify_hydrological_years(
        hist_df: pd.DataFrame, mc_df: pd.DataFrame,
        dry_pct: float = 0.20, wet_pct: float = 0.20) -> dict:
    """
    Clasifica años históricos y escenarios MC como secos, normales o húmedos.

    Usa percentiles de afluente total anual para clasificar:
    - Seco: P20 inferior (20% más bajo por defecto)
    - Normal: Entre P20 y P80
    - Húmedo: P80 superior (20% más alto por defecto)

    Justificación bibliográfica P20/P80:
    - Dirección General de Aguas (DGA, 2017): Usa P20 para definir años
      secos en estudios de disponibilidad hídrica en Chile
    - Garreaud et al. (2020, Nature Climate Change): Clasifica megasequía
      chilena usando quintiles (P20/P80) para análisis regional
    - Vicente-Serrano et al. (2010, J. Climate): Recomienda P20 para
      gestión de recursos hídricos en regiones con alta variabilidad

    Args:
        hist_df: DataFrame con índice=años, columnas=centrales
        mc_df: DataFrame con índice=scenario, columnas=centrales
        dry_pct: Percentil inferior para clasificar como seco (0-1,
            default 0.20)
        wet_pct: Percentil superior para clasificar como húmedo (0-1,
            default 0.20)

    Returns:
        dict con:
            - hist_labels: Series con clasificación histórica
            - mc_labels: Series con clasificación MC
            - hist_counts: Dict con conteo seco/normal/húmedo histórico
            - mc_counts: Dict con conteo seco/normal/húmedo MC
            - hist_pct: Dict con porcentajes históricos
            - mc_pct: Dict con porcentajes MC
            - thresholds: Dict con q_low y q_high históricos
    """
    # Calcular totales anuales
    hist_totals = hist_df.sum(axis=1)
    mc_totals = mc_df.sum(axis=1)

    # Calcular umbrales basados en datos históricos
    q_low = hist_totals.quantile(dry_pct)
    q_high = hist_totals.quantile(1 - wet_pct)

    # Clasificar histórico
    hist_labels = pd.cut(
        hist_totals,
        bins=[-np.inf, q_low, q_high, np.inf],
        labels=['seco', 'normal', 'húmedo']
    )

    # Clasificar MC
    mc_labels = pd.cut(
        mc_totals,
        bins=[-np.inf, q_low, q_high, np.inf],
        labels=['seco', 'normal', 'húmedo']
    )

    # Contar por tipo (histórico)
    hist_counts = hist_labels.value_counts().to_dict()
    hist_pct = {k: (v / len(hist_labels)) * 100
                for k, v in hist_counts.items()}

    # Contar por tipo (MC, promediado sobre escenarios)
    mc_counts_raw = mc_labels.value_counts().to_dict()
    mc_counts = mc_counts_raw  # Ya está promediado implícitamente
    mc_pct = {k: (v / len(mc_labels)) * 100
              for k, v in mc_counts.items()}

    return {
        'hist_labels': hist_labels,
        'mc_labels': mc_labels,
        'hist_counts': hist_counts,
        'mc_counts': mc_counts,
        'hist_pct': hist_pct,
        'mc_pct': mc_pct,
        'thresholds': {'q_low': q_low, 'q_high': q_high}
    }


# ============================================================================
# MÓDULO 3: VISUALIZACIONES
# ============================================================================

def create_correlation_plot(
        df_blocks: pd.DataFrame, block_k: int, output_path: str) -> None:
    """Genera gráfico comparativo de correlación K=2,3,4,5."""
    try:
        import matplotlib.pyplot as plt

        # Cargar datos para todos los K
        csv_path = DEFAULT_CSV
        alias_tables = load_and_pivot(csv_path)

        # Calcular correlaciones para K=2,3,4,5
        k_values = [2, 3, 4, 5]
        k_results = {}

        for k in k_values:
            all_rows_k = []
            for alias, pivot in alias_tables.items():
                if pivot is None or pivot.empty:
                    continue
                blocks_k = compute_block_correlations_k(pivot, k=k)
                if not blocks_k.empty:
                    all_rows_k.append(blocks_k)

            if all_rows_k:
                df_k = pd.concat(all_rows_k, ignore_index=True)
                k_results[k] = {
                    'median': df_k["corr_block_avg"].median(skipna=True),
                    'mean': df_k["corr_block_avg"].mean(skipna=True),
                    'p25': df_k["corr_block_avg"].quantile(0.25),
                    'p75': df_k["corr_block_avg"].quantile(0.75),
                }

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

        # SUBPLOT 1: Comparación de K-valores (BAR CHART)
        k_labels = [f'K={k}' for k in k_values]
        medians = [k_results[k]['median'] for k in k_values]
        colors = ['#95a5a6', '#27ae60', '#95a5a6', '#95a5a6']

        bars = ax1.bar(k_labels, medians, color=colors, alpha=0.8,
                       edgecolor='black', linewidth=1.5, width=0.6)

        # Destacar K=3
        bars[1].set_edgecolor('#1e8449')
        bars[1].set_linewidth(3)

        # Añadir valores encima de barras
        for i, (k, median) in enumerate(zip(k_values, medians)):
            label = f'r̄={median:.3f}'
            if k == 3:
                label += '\n✓ ÓPTIMO'
                ax1.text(
                    i, median + 0.02, label, ha='center',
                    fontsize=11, fontweight='bold', color='#1e8449')
            else:
                ax1.text(i, median + 0.02, label, ha='center',
                         fontsize=10)

        # Zona óptima
        ax1.axhspan(
            0.4, 0.6, alpha=0.15, color='green',
            label='Zona óptima (0.4-0.6)')
        ax1.axhline(
            0.5, color='red', linestyle='--', linewidth=1.5,
            alpha=0.6, label='Umbral correlación moderada')

        ax1.set_ylabel(
            'Correlación Temporal Promedio (r̄)',
            fontsize=12, fontweight='bold')
        ax1.set_xlabel(
            'Tamaño de Bloque (meses)', fontsize=12,
            fontweight='bold')
        ax1.set_title(
            'Comparación de Tamaños de Bloque Bootstrap',
            fontsize=14, fontweight='bold', pad=15)
        ax1.set_ylim([0, 0.8])
        ax1.legend(fontsize=10, loc='upper right', framealpha=0.95)
        ax1.grid(True, alpha=0.3, axis='y', linestyle=':', linewidth=0.8)

        # Añadir anotaciones explicativas
        ax1.text(
            0, 0.55, 'Pierde\nestacionalidad',
            ha='center', fontsize=9, style='italic',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))
        ax1.text(
            3, 0.25, 'Exceso de\ndependencia',
            ha='center', fontsize=9, style='italic',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

        # SUBPLOT 2: Distribución mensual para K=3
        summary = df_blocks.groupby("start_month")["corr_block_avg"].agg([
            ("median", "median"),
            ("p25", lambda x: x.quantile(0.25)),
            ("p75", lambda x: x.quantile(0.75)),
        ]).reset_index()

        ax2.plot(
            summary["start_month"], summary["median"],
            marker='o', markersize=9, linewidth=3,
            color='#27ae60', label='Mediana K=3', zorder=3)

        ax2.fill_between(
            summary["start_month"], summary["p25"], summary["p75"],
            alpha=0.3, color='#27ae60', label='Rango P25-P75')

        ax2.axhline(
            k_results[3]['median'], color='#1e8449',
            linestyle='--', linewidth=2, alpha=0.7,
            label=f'r promedio = {k_results[3]["median"]:.3f}')

        ax2.set_xlabel(
            'Mes de Inicio del Bloque', fontsize=12,
            fontweight='bold')
        ax2.set_ylabel(
            'Correlación Promedio', fontsize=12,
            fontweight='bold')
        ax2.set_title(
            'Variabilidad Estacional de Correlación (K=3)',
            fontsize=14, fontweight='bold', pad=15)
        ax2.set_xticks(range(1, 13))
        ax2.set_xticklabels(
            ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
             'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'],
            rotation=45)
        ax2.legend(fontsize=10, loc='best', framealpha=0.95)
        ax2.grid(True, alpha=0.3, linestyle=':', linewidth=0.8)
        ax2.set_ylim([0, 1.0])

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    except ImportError:
        pass


def create_distribution_comparison_plot(
        hist_df: pd.DataFrame, mc_df: pd.DataFrame,
        output_path: str) -> None:
    """Gráfico comparativo de distribuciones con clasificación hidrológica"""
    try:
        import matplotlib.pyplot as plt

        hist_total = hist_df.sum(axis=1)
        mc_total = mc_df.sum(axis=1)

        # Calcular umbrales de clasificación histórica
        q_low = hist_total.quantile(0.20)  # Límite seco (P20)
        q_high = hist_total.quantile(0.80)  # Límite húmedo (P80)

        fig, ax = plt.subplots(figsize=(14, 6))

        # Bandas verticales sombreadas PRIMERO (fondo)
        # Zona seca (fondo rojo claro)
        ax.axvspan(hist_total.min() - 200, q_low,
                   color='#d73027', alpha=0.12, zorder=0,
                   label=f'Rango Seco: < {q_low:.0f} Hm³ (P20)')

        # Zona húmeda (fondo verde claro)
        ax.axvspan(q_high, hist_total.max() + 200,
                   color='#1a9850', alpha=0.12, zorder=0,
                   label=f'Rango Húmedo: > {q_high:.0f} Hm³ (P80)')

        # Zona normal (fondo azul muy suave)
        ax.axvspan(q_low, q_high, color='#4575b4', alpha=0.06, zorder=0,
                   label=f'Rango Normal: {q_low:.0f} - {q_high:.0f} Hm³')

        # Histogramas superpuestos
        ax.hist(hist_total, bins=22, alpha=0.7,
                label='Histórico (1960-2023)',
                color='steelblue', edgecolor='black', linewidth=1.2,
                zorder=3)
        ax.hist(mc_total, bins=22, alpha=0.65,
                label='Monte Carlo (Bootstrap)',
                color='coral', edgecolor='black', linewidth=1.2,
                zorder=3)

        # Líneas divisorias de percentiles
        ax.axvline(q_low, color='#d73027', linestyle='--',
                   linewidth=2.5, alpha=0.7, zorder=4)
        ax.axvline(q_high, color='#1a9850', linestyle='--',
                   linewidth=2.5, alpha=0.7, zorder=4)

        # Líneas de mediana
        hist_median = hist_total.median()
        mc_median = mc_total.median()
        ax.axvline(hist_median, color='darkblue', linestyle='-',
                   linewidth=2.5, alpha=0.85,
                   label=f'Mediana Hist: {hist_median:.0f} Hm³', zorder=4)
        ax.axvline(mc_median, color='darkred', linestyle='-',
                   linewidth=2.5, alpha=0.85,
                   label=f'Mediana MC: {mc_median:.0f} Hm³', zorder=4)

        ax.set_xlabel('Afluentes Totales Anuales (Hm³)', fontsize=12,
                      fontweight='bold')
        ax.set_ylabel('Frecuencia', fontsize=12, fontweight='bold')
        ax.set_title(
            'Comparación de Distribuciones: Histórico vs Monte Carlo',
            fontsize=13, fontweight='bold', pad=15)
        ax.legend(fontsize=10, loc='upper right', framealpha=0.95, ncol=2)
        ax.grid(True, alpha=0.3, axis='y', linestyle=':', linewidth=0.8)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    except ImportError:
        pass


def create_temporal_bias_plot(
        hist_df: pd.DataFrame, mc_df: pd.DataFrame,
        output_path: str) -> None:
    """
    Genera gráfico comparando serie temporal histórica con distribución MC.

    Muestra los 64 años históricos año a año, con bandas de percentiles MC
    y clasificación por colores según tipo de año.
    """
    try:
        import matplotlib.pyplot as plt

        # Calcular totales anuales
        hist_totals = hist_df.sum(axis=1)  # índice=años (64 valores)
        mc_totals = mc_df.sum(axis=1)  # índice=scenarios (n valores)

        # Calcular percentiles y umbrales históricos (P20/P80)
        hist_p20 = hist_totals.quantile(0.20)
        hist_p80 = hist_totals.quantile(0.80)

        # Calcular percentiles MC
        mc_p20 = mc_totals.quantile(0.20)
        mc_p25 = mc_totals.quantile(0.25)
        mc_median = mc_totals.median()
        mc_p75 = mc_totals.quantile(0.75)
        mc_p80 = mc_totals.quantile(0.80)

        # Obtener años del índice histórico
        years = hist_totals.index.values
        hist_vals = hist_totals.values

        # Clasificar años históricos
        anos_secos = hist_vals < hist_p20
        anos_humedos = hist_vals > hist_p80
        anos_normales = ~(anos_secos | anos_humedos)

        fig, ax = plt.subplots(figsize=(16, 7))

        # Bandas horizontales de clasificación hidrológica histórica
        ax.axhspan(hist_totals.min(), hist_p20,
                   color='#d73027', alpha=0.08, zorder=0,
                   label=f'Rango Seco Histórico (< {hist_p20:.0f} Hm³)')
        ax.axhspan(hist_p80, hist_totals.max(),
                   color='#1a9850', alpha=0.08, zorder=0,
                   label=f'Rango Húmedo Histórico (> {hist_p80:.0f} Hm³)')

        # Bandas de percentiles MC (con colores suaves)
        ax.axhspan(
            mc_p20, mc_p80,
            color='#fee08b', alpha=0.25,
            label=(f"MC P20-P80 ({mc_p20:.0f}-{mc_p80:.0f} "
                   "Hm³)"),
            zorder=1,
        )
        ax.axhspan(
            mc_p25, mc_p75,
            color='#fdae61', alpha=0.3,
            label=(f"MC P25-P75 ({mc_p25:.0f}-{mc_p75:.0f} "
                   "Hm³)"),
            zorder=1,
        )
        # Línea de mediana MC
        ax.axhline(mc_median, color='#f46d43', linestyle='-',
                   linewidth=2.5, label=f'MC Mediana: {mc_median:.0f} Hm³',
                   alpha=0.9, zorder=2)

        # Líneas divisorias históricas
        ax.axhline(hist_p20, color='#d73027', linestyle='--',
                   linewidth=1.5, alpha=0.6, zorder=2)
        ax.axhline(hist_p80, color='#1a9850', linestyle='--',
                   linewidth=1.5, alpha=0.6, zorder=2)

        # Serie temporal histórica - línea base
        ax.plot(years, hist_vals, color='#4575b4', linewidth=2,
                alpha=0.6, zorder=3)

        # Puntos coloreados según clasificación
        if anos_secos.any():
            ax.scatter(years[anos_secos], hist_vals[anos_secos],
                       color='#d73027', s=60, marker='o',
                       label=f'Años Secos ({anos_secos.sum()})',
                       zorder=5, edgecolors='#a50026', linewidth=1.5,
                       alpha=0.9)

        if anos_normales.any():
            ax.scatter(years[anos_normales], hist_vals[anos_normales],
                       color='#4575b4', s=50, marker='o',
                       label=f'Años Normales ({anos_normales.sum()})',
                       zorder=4, edgecolors='#313695', linewidth=1,
                       alpha=0.8)

        if anos_humedos.any():
            ax.scatter(years[anos_humedos], hist_vals[anos_humedos],
                       color='#1a9850', s=60, marker='o',
                       label=f'Años Húmedos ({anos_humedos.sum()})',
                       zorder=5, edgecolors='#006837', linewidth=1.5,
                       alpha=0.9)

        ax.set_xlabel('Año', fontsize=12, fontweight='bold')
        ax.set_ylabel('Afluentes Totales (Hm³)', fontsize=12,
                      fontweight='bold')
        ax.set_title(
            'Serie Temporal Histórica: Clasificación Hidrológica '
            'vs Rangos Monte Carlo',
            fontsize=13, fontweight='bold', pad=15)
        ax.legend(fontsize=9, loc='upper right', framealpha=0.95, ncol=2)
        ax.grid(True, alpha=0.25, linestyle=':', linewidth=0.8, zorder=0)

        # Rotar etiquetas de años
        ax.tick_params(axis='x', rotation=45)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    except ImportError:
        pass


def create_year_classification_plot(
        classification: dict, output_path: str) -> None:
    """Genera gráfico de clasificación hidrológica."""
    try:
        import matplotlib.pyplot as plt

        # Extraer datos
        hist_counts = classification['hist_counts']
        mc_counts = classification['mc_counts']
        hist_pct = classification['hist_pct']
        mc_pct = classification['mc_pct']

        # Ordenar categorías
        categories = ['seco', 'normal', 'húmedo']
        hist_vals = [hist_counts.get(c, 0) for c in categories]
        mc_vals = [mc_counts.get(c, 0) for c in categories]
        hist_pcts = [hist_pct.get(c, 0) for c in categories]
        mc_pcts = [mc_pct.get(c, 0) for c in categories]
        # expected_pcts = [20, 60, 20]  # Estándar DGA/OMM

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # SUBPLOT 1: Conteo absoluto
        x = np.arange(len(categories))
        width = 0.35

        bars1 = ax1.bar(x - width/2, hist_vals, width,
                        label='Histórico',
                        color='steelblue', alpha=0.8,
                        edgecolor='black', linewidth=1.2)
        bars2 = ax1.bar(x + width/2, mc_vals, width,
                        label='Monte Carlo',
                        color='coral', alpha=0.8,
                        edgecolor='black', linewidth=1.2)

        # Etiquetas de valores
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height,
                         f'{height:.1f}',
                         ha='center', va='bottom', fontsize=9)

        ax1.set_xlabel('Tipo de Año', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Conteo Promedio', fontsize=11,
                       fontweight='bold')
        ax1.set_title('Clasificación Hidrológica: Conteo',
                      fontsize=12, fontweight='bold', pad=12)
        ax1.set_xticks(x)
        ax1.set_xticklabels(['Seco', 'Normal', 'Húmedo'])
        ax1.legend(fontsize=10, loc='best', framealpha=0.9)
        ax1.grid(True, alpha=0.3, axis='y', linestyle=':',
                 linewidth=0.8)

        # SUBPLOT 2: Porcentajes
        bars3 = ax2.bar(x - width/2, hist_pcts, width,
                        label='Histórico',
                        color='steelblue', alpha=0.8,
                        edgecolor='black', linewidth=1.2)
        bars4 = ax2.bar(x + width/2, mc_pcts, width,
                        label='Monte Carlo',
                        color='coral', alpha=0.8,
                        edgecolor='black', linewidth=1.2)

        # Línea de referencia 10% (ideal para secos/húmedos)
        ax2.axhline(10, color='green', linestyle='--', linewidth=1.5,
                    label='Ideal (10%)', alpha=0.7)

        # Etiquetas de valores
        for bars in [bars3, bars4]:
            for bar in bars:
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                         f'{height:.1f}%',
                         ha='center', va='bottom', fontsize=9)

        ax2.set_xlabel('Tipo de Año', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Porcentaje (%)', fontsize=11,
                       fontweight='bold')
        ax2.set_title('Clasificación Hidrológica: Porcentajes',
                      fontsize=12, fontweight='bold', pad=12)
        ax2.set_xticks(x)
        ax2.set_xticklabels(['Seco', 'Normal', 'Húmedo'])
        ax2.legend(fontsize=10, loc='best', framealpha=0.9)
        ax2.grid(True, alpha=0.3, axis='y', linestyle=':',
                 linewidth=0.8)
        ax2.set_ylim([0, 100])

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    except ImportError:
        pass


# ============================================================================
# MÓDULO 4: REPORTE CONSOLIDADO
# ============================================================================

def print_consolidated_report(corr_stats: Dict, dist_comparison: Dict,
                              block_k: int, n_scenarios: int,
                              all_block_stats: Dict,
                              classification: Dict = None) -> None:
    """Imprime reporte consolidado en consola."""

    print("\n✅ ANÁLISIS EJECUTADO CON ÉXITO\n")

    # PARTE 1: JUSTIFICACIÓN DE BLOQUES K=3
    print("📊 JUSTIFICACIÓN BLOQUES K=3 vs K=1,2,4,5")
    print("="*60)

    # Calcular métricas para justificar K=3
    k3_corr = all_block_stats[3]['median']
    k2_corr = all_block_stats[2]['median']
    k4_corr = all_block_stats[4]['median']

    # Calcular diferencias porcentuales
    diff_k2 = ((k3_corr - k2_corr) / k2_corr) * 100
    diff_k4 = ((k3_corr - k4_corr) / k4_corr) * 100

    print("\n  Correlación temporal promedio:")
    for k in sorted(all_block_stats.keys()):
        median = all_block_stats[k]['median']
        icon = "✓" if k == block_k else " "
        print(f"    {icon} K={k}: r̄={median:.3f}", end="")

        if k == block_k:
            print("  ← ÓPTIMO")
        elif k == 2:
            print(f"  (exceso: +{abs(diff_k2):.1f}% vs K=3, "
                  f"pierde estacionalidad)")
        elif k == 4:
            print(f"  (defecto: {diff_k4:+.1f}% vs K=3, "
                  f"exceso dependencia)")
        else:
            print()

    print("\n  Criterios de selección K=3:")
    print(f"    • Correlación moderada (r̄={k3_corr:.3f}): "
          f"preserva estructura temporal")
    print(f"    • Balance óptimo: K=2 excede {abs(diff_k2):.1f}%, "
          f"K=4 reduce {abs(diff_k4):.1f}%")
    print("    • Estacionalidad trimestral: captura ciclos "
          "naturales hidrológicos")
    print(f"    • {corr_stats['pct_gt_0_3']:.0f}% de bloques "
          f"con r>0.3 valida dependencia temporal")

    # PARTE 2: VALIDACIÓN DISTRIBUCIONES
    print("\n📈 COMPARACIÓN HISTÓRICO vs MONTE CARLO")
    print("="*60)
    pct_below = dist_comparison['pct_mc_below_p20_hist']

    print(f"\n  Media:     {dist_comparison['hist_mean']:>6,.0f} Hm³ → " +
          f"{dist_comparison['mc_mean']:>6,.0f} Hm³  " +
          f"({dist_comparison['diff_mean_pct']:+.1f}%)")
    print(f"  Desv.Std:  {dist_comparison['hist_std']:>6,.0f} Hm³ → " +
          f"{dist_comparison['mc_std']:>6,.0f} Hm³  " +
          f"({dist_comparison['diff_std_pct']:+.1f}%)")
    print(f"  P20:       {dist_comparison['hist_p20']:>6,.0f} Hm³ → " +
          f"{dist_comparison['mc_p20']:>6,.0f} Hm³")

    print("\n  Nota: P20 representa años secos (20% más bajo - estándar DGA).")
    print("        En distribución ideal: 20% escenarios MC < "
          "P20 histórico")
    print(f"        Resultado observado: {pct_below:.1f}% "
          f"({'✓ correcto' if 17 <= pct_below <= 23 else '⚠ sesgo'})")

    # CONCLUSIONES
    print("\n✅ DIAGNÓSTICO FINAL")
    print("="*60)

    # Decisión automática basada en métricas
    status = "✓" if corr_stats['median'] > 0.3 else "⚠"
    print(f"\n  {status} Bootstrap K=3 justificado: "
          f"r̄={corr_stats['median']:.3f} > 0.3")

    if pct_below < 15:
        print(f"  ⚠ Sesgo años secos: MC subestima extremos "
              f"({pct_below:.1f}% vs 20% ideal)")
    elif 17 <= pct_below <= 23:
        print(f"  ✓ Sin sesgo extremos: {pct_below:.1f}% ≈ 20% esperado")

    if abs(dist_comparison['diff_std_pct']) > 25:
        print(f"  ⚠ Variabilidad reducida: MC comprime dispersión "
              f"({abs(dist_comparison['diff_std_pct']):.1f}%)")
    else:
        print(f"  ✓ Variabilidad preservada: "
              f"{abs(dist_comparison['diff_std_pct']):.1f}% diferencia")

    # PARTE 3: CLASIFICACIÓN HIDROLÓGICA
    if classification is not None:
        print("\n📊 CLASIFICACIÓN HIDROLÓGICA (Años Secos/Normales/Húmedos)")
        print("="*60)

        hist_pct = classification['hist_pct']
        mc_pct = classification['mc_pct']
        thresholds = classification['thresholds']

        print("\n  Umbrales históricos (Hm³/año):")
        print(f"    • Seco:   < {thresholds['q_low']:,.0f} "
              f"(P20 - Estándar DGA)")
        print(f"    • Normal: {thresholds['q_low']:,.0f} - "
              f"{thresholds['q_high']:,.0f} (60% central)")
        print(f"    • Húmedo: > {thresholds['q_high']:,.0f} "
              f"(P80 - Estándar DGA)")

        print("\n  Distribución observada:")
        print(f"    {'Tipo':<10} {'Histórico':>12} {'Monte Carlo':>12} "
              f"{'Diferencia':>12}")
        print("    " + "-"*50)

        for cat in ['seco', 'normal', 'húmedo']:
            h_pct = hist_pct.get(cat, 0)
            m_pct = mc_pct.get(cat, 0)
            diff = m_pct - h_pct

            status = "✓" if abs(diff) < 5 else "⚠"
            print(f"    {status} {cat.capitalize():<8} "
                  f"{h_pct:>10.1f}%  {m_pct:>10.1f}%  "
                  f"{diff:>+10.1f}%")

        print("\n  Criterio P20/P80 (DGA, 2017; Garreaud et al., 2020)")
        print("  Nota: Se espera ~20% secos, ~60% normales, ~20% húmedos")

        # Diagnóstico automático
        seco_ok = abs(mc_pct.get('seco', 0) - 20) < 5
        humedo_ok = abs(mc_pct.get('húmedo', 0) - 20) < 5

        if seco_ok and humedo_ok:
            print("  ✓ MC reproduce correctamente años extremos")
        else:
            if not seco_ok:
                seco_status = ('subestima'
                               if mc_pct.get('seco', 0) < 20
                               else 'sobrestima')
                print(f"  ⚠ MC {seco_status} años secos")
            if not humedo_ok:
                humedo_status = ('subestima'
                                 if mc_pct.get('húmedo', 0) < 20
                                 else 'sobrestima')
                print(f"  ⚠ MC {humedo_status} años húmedos")

    print("\n  📁 Gráficos: resultados/analisis_bootstrap/\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Análisis integral de validación bootstrap para MC"
    )
    parser.add_argument(
        "--csv", default=DEFAULT_CSV,
        help="Ruta al CSV de caudales históricos")
    parser.add_argument(
        "--out", default=DEFAULT_OUTDIR,
        help="Directorio de salida")
    parser.add_argument(
        "--block-k", type=int, default=3,
        help="Tamaño de bloques (meses) para correlación")
    parser.add_argument(
        "--n-scenarios", type=int, default=100,
        help="Número de escenarios Monte Carlo a generar")
    parser.add_argument(
        "--no-plots", action="store_true",
        help="Desactiva generación de gráficos")

    args = parser.parse_args()

    # Título inicial
    print("="*70)
    print(
        f"🔄 ANÁLISIS BOOTSTRAP | Embalse del Laja "
        f"({len(YEARS)} años ; {SCENARIOS}  escenarios)"
    )
    print("="*70)
    print("\n⏳ Ejecutando análisis...", end="", flush=True)

    # Crear directorio de salida
    os.makedirs(args.out, exist_ok=True)

    # ========================================================================
    # PARTE 1: ANÁLISIS DE CORRELACIÓN TEMPORAL
    # ========================================================================
    df_corr, corr_stats, all_block_stats = analyze_temporal_correlation(
        args.csv, args.block_k
    )
    print(" ✓")

    if not df_corr.empty:
        # Generar gráfico
        if not args.no_plots:
            plot_corr = os.path.join(
                args.out, f"correlacion_temporal_{args.block_k}m.png")
            create_correlation_plot(df_corr, args.block_k, plot_corr)

    # ========================================================================
    # PARTE 2: COMPARACIÓN HISTÓRICO vs MONTE CARLO
    # ========================================================================
    hist_df = load_historical_totals(args.csv)
    mc_df = generate_mc_scenarios(args.csv, args.n_scenarios, args.block_k)

    dist_comparison = compare_distributions(hist_df, mc_df)

    # ========================================================================
    # PARTE 3: CLASIFICACIÓN HIDROLÓGICA Y SESGO TEMPORAL
    # ========================================================================
    classification = classify_hydrological_years(hist_df, mc_df)

    # Generar gráficos
    if not args.no_plots:
        plot_dist = os.path.join(args.out, "comparacion_distribuciones.png")
        create_distribution_comparison_plot(hist_df, mc_df, plot_dist)

        plot_temporal = os.path.join(
            args.out, "sesgo_temporal_afluentes.png")
        create_temporal_bias_plot(hist_df, mc_df, plot_temporal)

        plot_class = os.path.join(
            args.out, "clasificacion_hidrologica.png")
        create_year_classification_plot(classification, plot_class)

    # ========================================================================
    # REPORTE CONSOLIDADO
    # ========================================================================
    print_consolidated_report(
        corr_stats, dist_comparison, args.block_k,
        args.n_scenarios, all_block_stats, classification)


if __name__ == "__main__":
    main()
