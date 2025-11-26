"""
KPIs - Embalse del Laja
========================

Extracción de KPIs usando directamente las variables y lógica del
modelo de optimización.

KPIs Implementados:
1. Tiempo en colchones operativos (%)
2. Uso de presupuestos riego/generación (%)
3. Déficits de riego (Hm³ y %)
4. Factor de utilización del sistema (%)
"""

from typing import Dict, List, Any, Optional
import numpy as np

from filt_cota import cota_from_volumen


# Constantes del modelo (importadas localmente para evitar imports globales)
def _get_model_constants():
    """Importa constantes del modelo de forma controlada."""
    from model import T, Conv, COLCHONES, C_LABELS, V_max
    return T, Conv, COLCHONES, C_LABELS, V_max


# ===================================================================
# EXTRACCIÓN PRINCIPAL DE KPIS
# ===================================================================

def extract_kpis(model, include_detailed: bool = True) -> Dict[str, Any]:
    """
    Extrae KPIs del modelo optimizado usando sus variables directamente.

    Args:
        model: Modelo Gurobi optimizado
        include_detailed: Incluir series mensuales (compatibilidad)

    Returns:
        Dict con KPIs calculados
    """
    # Validación básica
    if not hasattr(model, 'status') or model.status != 2:
        return _empty_kpis()

    T, Conv, COLCHONES, C_LABELS, _ = _get_model_constants()

    # KPIs básicos
    kpis = {
        'status': 2,
        'obj_MWh': model.objVal,
        'V_end': model._V[11].x  # Volumen final (noviembre)
    }

    # KPI 1: Tiempo en colchones (basado en volúmenes)
    kpis['tiempo_colchones_%'] = _calc_tiempo_colchones(
        model, T, COLCHONES, C_LABELS
    )

    # KPI 2: Uso de presupuestos (extrae directamente del modelo)
    kpis['uso_presupuestos_%'] = _calc_uso_presupuestos(
        model, T, Conv, C_LABELS, COLCHONES
    )

    # KPI 3: Déficits (usa variables Def1 y Def2 del modelo)
    deficit_kpis = _calc_deficits(model, T, Conv)
    kpis.update(deficit_kpis)

    # KPI 4: Factor de utilización (usa G[t] del modelo, solo si existe)
    if hasattr(model, '_G'):
        kpis['factor_utilizacion_%'] = _calc_factor_utilizacion(model, T)
        # Generación energética total anual (MWh): G[t] en MW → MWh
        horas_mes = 720  # 30 días × 24h
        kpis['generacion_total'] = sum(
            model._G[t].x * horas_mes for t in T
        )
    else:
        kpis['factor_utilizacion_%'] = {'sistema': 0.0}
        kpis['generacion_total'] = 0.0

    # Agua total extraída por El Toro (Hm³)
    # Interpretación: Flujo_Total = Riego + Generación_Agua
    kpis['agua_eltoro_total'] = sum(
        model._x['Embalse', 'ElToro', t].x * Conv for t in T
    )

    # Agua del lago usada para RIEGO (cubrir déficits)
    if hasattr(model, '_Def2'):
        kpis['agua_riego_hm3'] = (
            sum(model._Def1[t].x for t in T) +
            sum(model._Def2[t].x for t in T)
        )
    else:
        kpis['agua_riego_hm3'] = sum(model._Def1[t].x for t in T)

    # Agua EXCEDENTE del lago usada para GENERACIÓN (después de riego)
    kpis['agua_generacion_hm3'] = (
        kpis['agua_eltoro_total'] - kpis['agua_riego_hm3']
    )

    # Series mensuales
    kpis['volumenes_mensuales'] = {t: model._V[t].x for t in T}
    kpis['cota_mensual'] = {
        t: cota_from_volumen(model._V[t].x) for t in T
    }

    return kpis


def _empty_kpis() -> Dict[str, Any]:
    """KPIs vacíos para modelos no óptimos."""
    return {
        'status': -1,
        'obj_MWh': 0.0,
        'V_end': 0.0,
        'tiempo_colchones_%': {},
        'uso_presupuestos_%': {'riego': '0.0%', 'generacion': '0.0%'},
        'deficit_sum_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_prom_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_max_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_pct': {'1R': 0.0, '2R': 0.0},
        'factor_utilizacion_%': {'sistema': 0.0},
        'volumenes_mensuales': {},
        'cota_mensual': {}
    }


# ===================================================================
# KPI 1: TIEMPO EN COLCHONES
# ===================================================================

def _calc_tiempo_colchones(
    model,
    time_periods: List[int],
    colchones_def: Dict,
    colchon_labels: List[str]
) -> Dict[str, float]:
    """
    Calcula distribución de tiempo en colchones desde volúmenes.

    Usa directamente V[t] del modelo y rangos de COLCHONES.
    """
    if not hasattr(model, '_V') or not colchon_labels:
        return {c: 0.0 for c in ['Inferior', 'Transicion',
                                 'Intermedio', 'Superior']}

    tiempo_colchones = {c: 0 for c in colchon_labels}

    for t in time_periods:
        volumen = model._V[t].x
        for c in colchon_labels:
            v_min = colchones_def[c]["lo"]
            v_max = colchones_def[c]["hi"]
            if v_min <= volumen < v_max:
                tiempo_colchones[c] += 1
                break

    return {
        c: (count / len(time_periods)) * 100.0
        for c, count in tiempo_colchones.items()
    }


# ===================================================================
# KPI 2: USO DE PRESUPUESTOS
# ===================================================================

def _calc_uso_presupuestos(
    model,
    time_periods: List[int],
    conv_factor: float,
    colchon_labels: List[str],
    colchones_def: Dict
) -> Dict[str, Any]:
    """
    Calcula uso de presupuestos como porcentajes y diferencias absolutas.

    Método simplificado: calcula presupuesto disponible y uso real,
    luego deriva porcentajes y diferencias como parámetros normales.

    Returns:
        Dict con porcentajes, valores absolutos y diferencias
    """
    try:
        # =====================================================================
        # 1. CALCULAR PRESUPUESTO DISPONIBLE (según colchón activo)
        # =====================================================================

        # Identificar colchón activo
        colchon_activo = None
        for c in colchon_labels:
            z_var = model.getVarByName(f"z[{c}]")
            if z_var and z_var.x > 0.5:
                colchon_activo = c
                break

        if not colchon_activo:
            return {'riego': 'N/A', 'generacion': 'N/A'}

        # V0 real del modelo
        vinit_var = model.getVarByName("Vinit")
        v0_real = vinit_var.x if vinit_var else 1400.0

        # Presupuestos según definición del colchón activo
        shares = colchones_def[colchon_activo]["shares"]
        r_share, g_share = shares[0], shares[1]

        # Presupuesto RIEGO disponible
        if r_share > 1.0:  # Valor fijo (ej. 600 Hm³ en Inferior)
            presupuesto_riego = r_share
        else:  # Porcentaje de V0 (ej. 40% en Intermedio)
            presupuesto_riego = r_share * v0_real

        # Presupuesto GENERACIÓN disponible (base)
        if g_share > 1.0:  # Valor fijo
            presupuesto_gen_base = g_share
        else:  # Porcentaje de V0
            presupuesto_gen_base = g_share * v0_real

        # Aplicar tope 1200 Hm³ SOLO en Superior
        if colchon_activo == "Superior":
            presupuesto_gen = min(presupuesto_gen_base, 1200.0)
        else:
            presupuesto_gen = presupuesto_gen_base

        # =====================================================================
        # 2. CALCULAR USO REAL (desde variables del modelo)
        # =====================================================================

        # Uso RIEGO: agua para déficits (Hm³/año)
        riego_usado = sum(
            model._Def1[t].x + model._Def2[t].x
            for t in time_periods
        )

        # Uso GENERACIÓN: agua excedente post-riego (Hm³/año)
        extraccion_total = sum(
            model._x['Embalse', 'ElToro', t].x * conv_factor
            for t in time_periods
        )
        generacion_usada = extraccion_total - riego_usado

        # =====================================================================
        # 3. CALCULAR MÉTRICAS FINALES
        # =====================================================================

        # Porcentajes de utilización
        pct_riego = (riego_usado / presupuesto_riego * 100.0) \
            if presupuesto_riego > 0 else 0.0
        pct_gen = (generacion_usada / presupuesto_gen * 100.0) \
            if presupuesto_gen > 0 else 0.0

        # Diferencias absolutas (uso - disponible)
        diff_riego = riego_usado - presupuesto_riego
        diff_gen = generacion_usada - presupuesto_gen

        # =====================================================================
        # 4. RETORNO COMPLETO
        # =====================================================================

        return {
            # Formato tradicional (compatibilidad)
            'riego': f"{pct_riego:.1f}%",
            'generacion': f"{pct_gen:.1f}%",

            # Presupuestos disponibles
            'presupuesto_riego_hm3': presupuesto_riego,
            'presupuesto_gen_hm3': presupuesto_gen,
            'colchon_activo': colchon_activo,
            'v0_real_hm3': v0_real,

            # Uso real
            'riego_usado_hm3': riego_usado,
            'gen_usada_hm3': generacion_usada,
            'extraccion_total_hm3': extraccion_total,

            # Porcentajes (valores numéricos)
            'uso_riego_pct': pct_riego,
            'uso_gen_pct': pct_gen,

            # Diferencias absolutas (+ = exceso, - = subutilización)
            'diferencia_riego_hm3': diff_riego,
            'diferencia_gen_hm3': diff_gen,

            # Estado de cumplimiento
            'cumple_riego': diff_riego <= 0.0,  # True si no excede
            'cumple_gen': diff_gen <= 0.0,      # True si no excede
        }

    except (KeyError, AttributeError) as e:
        print(f"⚠️  Error calculando presupuestos: {e}")
        return {'riego': 'N/A', 'generacion': 'N/A'}


# ===================================================================
# KPI 3: DÉFICITS DE RIEGO
# ===================================================================

def _calc_deficits(
    model,
    time_periods: List[int],
    conv_factor: float
) -> Dict[str, Any]:
    """
    Calcula déficits desde variables Def1 y Def2 del modelo.

    Nota: Déficits ya están en Hm³ (no requieren conversión).
    """
    # Extraer demandas desde metadata del modelo
    demandas = model._meta.get('demandas_mensuales', {})

    deficit_1R = []
    deficit_2R = []
    demanda_1R_total = 0.0
    demanda_2R_total = 0.0

    for t in time_periods:
        # Déficits desde modelo (ya en Hm³)
        def1_val = model._Def1[t].x if hasattr(model, '_Def1') else 0.0
        def2_val = model._Def2[t].x if hasattr(model, '_Def2') else 0.0

        deficit_1R.append(def1_val)
        deficit_2R.append(def2_val)

        # Demandas mensuales
        dem_tuc = demandas.get('tucapel', {}).get(t, 0.0)
        dem_ab = demandas.get('abanico', {}).get(t, 0.0)
        dem_2r = demandas.get('segundos', {}).get(t, 0.0)

        demanda_1R_total += dem_tuc + dem_ab
        demanda_2R_total += dem_2r

    # Métricas agregadas
    def1_sum = float(np.sum(deficit_1R))
    def2_sum = float(np.sum(deficit_2R))
    def1_prom = float(np.mean(deficit_1R))
    def2_prom = float(np.mean(deficit_2R))
    def1_max = float(np.max(deficit_1R))
    def2_max = float(np.max(deficit_2R)) if deficit_2R else 0.0

    # Porcentajes
    pct_def1 = (def1_sum / demanda_1R_total * 100.0) \
        if demanda_1R_total > 0 else 0.0
    pct_def2 = (def2_sum / demanda_2R_total * 100.0) \
        if demanda_2R_total > 0 else 0.0

    # Agua total El Toro (para composición)
    agua_total_eltoro = sum(
        model._x['Embalse', 'ElToro', t].x * conv_factor
        for t in time_periods
    )

    # Composición flujo El Toro
    composicion = _calc_composicion_eltoro(
        agua_total_eltoro, def1_sum, def2_sum
    )

    return {
        'deficit_sum_hm3': {'1R': def1_sum, '2R': def2_sum},
        'deficit_prom_hm3': {'1R': def1_prom, '2R': def2_prom},
        'deficit_max_hm3': {'1R': def1_max, '2R': def2_max},
        'deficit_pct': {'1R': pct_def1, '2R': pct_def2},
        'demanda_1R_tot': demanda_1R_total,
        'demanda_2R_tot': demanda_2R_total,
        'agua_eltoro_total': agua_total_eltoro,
        'agua_eltoro_deficit_1r': def1_sum,
        'agua_eltoro_deficit_2r': def2_sum,
        'composicion_eltoro_%': composicion
    }


def _calc_composicion_eltoro(
    agua_total: float,
    def1: float,
    def2: float
) -> Dict[str, float]:
    """Calcula composición porcentual del flujo de El Toro."""
    if agua_total == 0:
        return {'deficit_1r': 0.0, 'deficit_2r': 0.0, 'transito': 0.0}

    pct_1r = (def1 / agua_total) * 100.0
    pct_2r = (def2 / agua_total) * 100.0
    pct_transito = 100.0 - pct_1r - pct_2r

    return {
        'deficit_1r': pct_1r,
        'deficit_2r': pct_2r,
        'transito': pct_transito
    }


# ===================================================================
# KPI 4: FACTOR DE UTILIZACIÓN
# ===================================================================

def _calc_factor_utilizacion(
    model,
    time_periods: List[int]
) -> Dict[str, float]:
    """
    Calcula factor de utilización del sistema usando G[t] del modelo.

    Factor = (Energía Real Total) / (Energía Teórica) × 100%

    Capacidad instalada total: 1,136.22 MW (7 centrales)
    Energía Teórica = 1,136.22 MW × 8,760 h/año
    """
    try:
        # Capacidades según CaudalMax_filtrado.csv
        cap_total_mw = (
            437.2715 +  # ElToro
            93.0 +      # Abanico
            320.0 +     # Antuco
            178.4 +     # Rucue
            70.0 +      # Quilleco
            34.30368 +  # Laja_I
            3.25        # ElDiuto
        )  # Total: 1,136.22 MW

        # Energía real total (MWh): G[t] en MW → MWh
        horas_mes = 720  # 30 días × 24h
        energia_real_total = sum(
            model._G[t].x * horas_mes for t in time_periods
        )

        # Energía teórica máxima anual (MWh)
        horas_año = 8760  # 365 días × 24h
        energia_teorica = cap_total_mw * horas_año

        # Factor de utilización (%)
        fu_sistema = (energia_real_total / energia_teorica * 100.0) \
            if energia_teorica > 0 else 0.0

        return {'sistema': fu_sistema}

    except (KeyError, AttributeError):
        return {'sistema': 0.0}


# ===================================================================
# AGREGACIÓN MULTI-AÑO
# ===================================================================

def aggregate_kpis(
    kpis_list: List[Dict[str, Any]],
    years: Optional[List[int]] = None,
    v0_values: Optional[List[float]] = None,
    identifiers: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Agrega KPIs de múltiples años con estadísticas detalladas.

    Args:
        kpis_list: Lista de KPIs individuales
        years: Lista de años correspondientes (DEPRECATED: usar identifiers)
        v0_values: Lista de valores V0 iniciales
        identifiers: Lista de identificadores (años, escenarios, etc.)

    Returns:
        KPIs agregados con totales, promedios, máx/mín
    """
    # Compatibilidad: usar years si identifiers no está especificado
    if identifiers is None:
        identifiers = years
    if not kpis_list:
        return _empty_kpis()

    # Filtrar solo óptimos
    valid_kpis = [k for k in kpis_list if k.get('status') == 2]

    if not valid_kpis:
        return _empty_kpis()

    T, _, _, _, _ = _get_model_constants()

    # KPI 1: Promedio tiempo en colchones
    colchones_agg = {
        c: np.mean([
            kpi.get('tiempo_colchones_%', {}).get(c, 0.0)
            for kpi in valid_kpis
        ])
        for c in ['Inferior', 'Transicion', 'Intermedio', 'Superior']
    }

    # KPI 2: Promedio uso presupuestos
    presup_vals = []
    gen_vals = []

    for kpi in valid_kpis:
        presup_data = kpi.get('uso_presupuestos_%', {})
        riego_val = presup_data.get('riego', 'N/A')
        gen_val = presup_data.get('generacion', 'N/A')

        # Convertir strings "X.X%" a float
        if isinstance(riego_val, str) and '%' in riego_val:
            riego_val = float(riego_val.replace('%', ''))
        if isinstance(gen_val, str) and '%' in gen_val:
            gen_val = float(gen_val.replace('%', ''))

        if riego_val != 'N/A':
            presup_vals.append(riego_val)
        if gen_val != 'N/A':
            gen_vals.append(gen_val)

    presup_agg = {
        'riego': f"{np.mean(presup_vals):.1f}%"
        if presup_vals else 'N/A',
        'generacion': f"{np.mean(gen_vals):.1f}%"
        if gen_vals else 'N/A'
    }

    # KPI 3: Déficits agregados
    deficits_1r = [
        kpi.get('deficit_sum_hm3', {}).get('1R', 0.0)
        for kpi in valid_kpis
    ]
    deficits_2r = [
        kpi.get('deficit_sum_hm3', {}).get('2R', 0.0)
        for kpi in valid_kpis
    ]

    deficit_acum_1r = sum(deficits_1r)
    deficit_acum_2r = sum(deficits_2r)
    deficit_prom_1r = np.mean(deficits_1r)
    deficit_prom_2r = np.mean(deficits_2r)
    deficit_max_1r = max(deficits_1r) if deficits_1r else 0.0
    deficit_max_2r = max(deficits_2r) if deficits_2r else 0.0
    deficit_min_1r = min(deficits_1r) if deficits_1r else 0.0
    deficit_min_2r = min(deficits_2r) if deficits_2r else 0.0
    deficit_std_1r = np.std(deficits_1r) if len(deficits_1r) > 1 else 0.0
    deficit_std_2r = np.std(deficits_2r) if len(deficits_2r) > 1 else 0.0

    # Identificar años/escenarios críticos
    idx_max_1r = deficits_1r.index(max(deficits_1r)) \
        if deficits_1r else -1
    idx_min_1r = deficits_1r.index(min(deficits_1r)) \
        if deficits_1r else -1
    idx_max_2r = deficits_2r.index(max(deficits_2r)) \
        if deficits_2r else -1
    idx_min_2r = deficits_2r.index(min(deficits_2r)) \
        if deficits_2r else -1

    id_max_1r = identifiers[idx_max_1r] \
        if identifiers and idx_max_1r >= 0 else None
    id_min_1r = identifiers[idx_min_1r] \
        if identifiers and idx_min_1r >= 0 else None
    id_max_2r = identifiers[idx_max_2r] \
        if identifiers and idx_max_2r >= 0 else None
    id_min_2r = identifiers[idx_min_2r] \
        if identifiers and idx_min_2r >= 0 else None

    v0_max_1r = v0_values[idx_max_1r] \
        if v0_values and idx_max_1r >= 0 else None
    v0_min_1r = v0_values[idx_min_1r] \
        if v0_values and idx_min_1r >= 0 else None
    v0_max_2r = v0_values[idx_max_2r] \
        if v0_values and idx_max_2r >= 0 else None
    v0_min_2r = v0_values[idx_min_2r] \
        if v0_values and idx_min_2r >= 0 else None

    # Demandas totales acumuladas
    demanda_1r_total = sum(
        kpi.get('demanda_1R_tot', 0.0) for kpi in valid_kpis
    )
    demanda_2r_total = sum(
        kpi.get('demanda_2R_tot', 0.0) for kpi in valid_kpis
    )

    # Porcentajes acumulados
    deficit_pct_1r = (deficit_acum_1r / demanda_1r_total * 100.0) \
        if demanda_1r_total > 0 else 0.0
    deficit_pct_2r = (deficit_acum_2r / demanda_2r_total * 100.0) \
        if demanda_2r_total > 0 else 0.0

    # KPI 4: Factor utilización total
    energia_real_total = sum(
        kpi.get('generacion_total', 0.0) for kpi in valid_kpis
    )
    cap_total_mw = 1136.22
    horas_año = 8760
    n_años = len(valid_kpis)
    energia_teorica_total = cap_total_mw * horas_año * n_años

    fu_sistema = (energia_real_total / energia_teorica_total * 100.0) \
        if energia_teorica_total > 0 else 0.0

    # Trayectoria mensual promedio (cota)
    cota_mensual_agg = {
        t: np.mean([
            kpi.get('cota_mensual', {}).get(t, 0.0)
            for kpi in valid_kpis
        ])
        for t in T
    }

    # Agua El Toro para déficits (validación)
    agua_eltoro_1r = sum(
        kpi.get('agua_eltoro_deficit_1r', 0.0) for kpi in valid_kpis
    )
    agua_eltoro_2r = sum(
        kpi.get('agua_eltoro_deficit_2r', 0.0) for kpi in valid_kpis
    )

    return {
        'status': 2,
        'tiempo_colchones_%': colchones_agg,
        'uso_presupuestos_%': presup_agg,
        'deficit_acumulado_hm3': {
            '1R': deficit_acum_1r, '2R': deficit_acum_2r
        },
        'deficit_promedio_anual_hm3': {
            '1R': deficit_prom_1r, '2R': deficit_prom_2r
        },
        'deficit_max_anual_hm3': {
            '1R': deficit_max_1r, '2R': deficit_max_2r
        },
        'deficit_min_anual_hm3': {
            '1R': deficit_min_1r, '2R': deficit_min_2r
        },
        'deficit_std_hm3': {'1R': deficit_std_1r, '2R': deficit_std_2r},
        'deficit_pct': {'1R': deficit_pct_1r, '2R': deficit_pct_2r},
        'demanda_1R_tot': demanda_1r_total,
        'demanda_2R_tot': demanda_2r_total,
        'agua_eltoro_deficit_1r': agua_eltoro_1r,
        'agua_eltoro_deficit_2r': agua_eltoro_2r,
        'id_max_deficit': {'1R': id_max_1r, '2R': id_max_2r},
        'id_min_deficit': {'1R': id_min_1r, '2R': id_min_2r},
        'v0_max_deficit': {'1R': v0_max_1r, '2R': v0_max_2r},
        'v0_min_deficit': {'1R': v0_min_1r, '2R': v0_min_2r},
        'factor_utilizacion_%': {'sistema': fu_sistema},
        'cota_mensual': cota_mensual_agg,
        'num_kpis': len(valid_kpis),
        'num_total': len(kpis_list),
        'is_multi_year': True
    }


# ===================================================================
# VISUALIZACIÓN
# ===================================================================

def print_kpis(
    kpis: Dict[str, Any],
    context: str = "",
    years: Optional[List[int]] = None
) -> None:
    """
    Imprime KPIs en formato limpio y profesional.

    Args:
        kpis: KPIs calculados
        context: Contexto (año, histórico, etc.)
        years: Lista de años (para años críticos)
    """
    if not kpis or kpis.get('status') != 2:
        print("\n❌ No hay KPIs válidos para mostrar")
        return

    # Detectar si es multi-año
    is_multi_year = kpis.get('is_multi_year', False)

    print("=" * 79)
    print("📊 INDICADORES CLAVE DE DESEMPEÑO (KPIs)")
    if context:
        print(f"   {context}")
    print("=" * 79)

    # KPI 1: Colchones
    print("\n🧭 KPI 1 - TIEMPO EN COLCHONES OPERATIVOS:")
    colchones = kpis.get('tiempo_colchones_%', {})
    emojis = {
        'Inferior': '🔴', 'Transicion': '🟡',
        'Intermedio': '🟢', 'Superior': '🔵'
    }
    for colchon, pct in colchones.items():
        emoji = emojis.get(colchon, '⚪')
        print(f"   {emoji} {colchon:12s}: {pct:6.1f}%")

    # KPI 2: Presupuestos (con descomposición y diferencias)
    print("\n💰 KPI 2 - USO DE PRESUPUESTOS (Convenio 2017):")
    presup = kpis.get('uso_presupuestos_%', {})
    print(f"   🌾 Riego (déficits):         {presup.get('riego', 'N/A'):>8}")
    generacion_str = presup.get('generacion', 'N/A')
    print(f"   ⚡ Generación (excedente):    {generacion_str:>8}")

    # # Mostrar presupuestos disponibles y diferencias
    # presup_riego_abs = presup.get('presupuesto_riego_hm3', 0.0)
    # presup_gen_abs = presup.get('presupuesto_gen_hm3', 0.0)
    # diff_riego = presup.get('diferencia_riego_hm3', 0.0)
    # diff_gen = presup.get('diferencia_gen_hm3', 0.0)
    # cumple_riego = presup.get('cumple_riego', True)
    # cumple_gen = presup.get('cumple_gen', True)
    # colchon_activo = presup.get('colchon_activo', 'N/A')

    # if presup_riego_abs > 0 or presup_gen_abs > 0:
    #     print(f"\n   📋 Colchón Activo: {colchon_activo}")
    #     print("   💧 Presupuestos vs Uso:")

    #     if presup_riego_abs > 0:
    #         estado_riego = "✅" if cumple_riego else "❌"
    #         signo_riego = "+" if diff_riego > 0 else ""
    #         print(f"      • Riego:      {presup_riego_abs:>7.1f} Hm³/año "
    #               f"({signo_riego}{diff_riego:>+6.1f}) {estado_riego}")

    #     if presup_gen_abs > 0:
    #         estado_gen = "✅" if cumple_gen else "❌"
    #         signo_gen = "+" if diff_gen > 0 else ""
    #         print(f"      • Generación: {presup_gen_abs:>7.1f} Hm³/año "
    #               f"({signo_gen}{diff_gen:>+6.1f}) {estado_gen}")

    # # Mostrar descomposición del flujo El Toro si está disponible
    # agua_total = kpis.get('agua_eltoro_total', 0.0)
    # agua_riego = kpis.get('agua_riego_hm3', 0.0)
    # agua_gen = kpis.get('agua_generacion_hm3', 0.0)
    # if agua_total > 0:
    #     print("\n   📊 Descomposición Flujo El Toro:")
    #     print(f"      • Total:      {agua_total:>8.2f} Hm³/año")
    #     pct_riego = agua_riego / agua_total * 100
    #     pct_gen = agua_gen / agua_total * 100
    #     print(f"      • Riego:      {agua_riego:>8.2f} Hm³ "
    #           f"({pct_riego:>5.1f}%)")
    #     print(f"      • Generación: {agua_gen:>8.2f} Hm³ "
    #           f"({pct_gen:>5.1f}%)")

    # KPI 3: Déficits
    print("\n📉 KPI 3 - DÉFICITS DE RIEGO:")
    if is_multi_year:
        _print_deficits_multiyear(kpis)
    else:
        _print_deficits_single_year(kpis)

    # KPI 4: Factor utilización
    print("\n🏭 KPI 4 - FACTOR DE UTILIZACIÓN:")
    fu = kpis.get('factor_utilizacion_%', {})
    print(f"   🏭 Sistema:   {fu.get('sistema', 0.0):6.1f}%")

    # Resumen operacional
    print("\n📋 RESUMEN OPERACIONAL:")
    cota_data = kpis.get('cota_mensual', {})
    if cota_data:
        cotas = list(cota_data.values())
        cota_prom = np.mean(cotas)
        cota_min, cota_max = np.min(cotas), np.max(cotas)
        print(
            f"   📏 Cota: {cota_prom:.1f} msnm "
            f"[{cota_min:.1f}-{cota_max:.1f}]"
        )
    print()


def _print_deficits_single_year(kpis: Dict[str, Any]) -> None:
    """Imprime déficits para un año individual."""
    deficit_sum = kpis.get('deficit_sum_hm3', {})
    deficit_max = kpis.get('deficit_max_hm3', {})
    deficit_pct = kpis.get('deficit_pct', {})
    demanda_1r = kpis.get('demanda_1R_tot', 0.0)
    demanda_2r = kpis.get('demanda_2R_tot', 0.0)

    def1_total = deficit_sum.get('1R', 0.0)
    def2_total = deficit_sum.get('2R', 0.0)

    if def1_total > 0.01 or def2_total > 0.01:
        if def1_total > 0.01:
            print("📍 Primeros Regantes (1R):")
            print(f"   • Déficit total:  {def1_total:7.2f} Hm³/año")
            print(
                f"   • Déficit máximo: "
                f"{deficit_max.get('1R', 0.0):7.2f} Hm³/mes"
            )
            print(f"   • Demanda total:  {demanda_1r:7.2f} Hm³/año")
            print(
                f"   • % de demanda:   "
                f"{deficit_pct.get('1R', 0.0):6.2f}%"
            )

        if def2_total > 0.01:
            print("📍 Segundos Regantes (2R):")
            print(f"   • Déficit total:  {def2_total:7.2f} Hm³/año")
            print(
                f"   • Déficit máximo: "
                f"{deficit_max.get('2R', 0.0):7.2f} Hm³/mes"
            )
            print(f"   • Demanda total:  {demanda_2r:7.2f} Hm³/año")
            print(
                f"   • % de demanda:   "
                f"{deficit_pct.get('2R', 0.0):6.2f}%"
            )
    else:
        print("   ✅ Sin déficits registrados")


def _print_deficits_multiyear(kpis: Dict[str, Any]) -> None:
    """Imprime déficits para múltiples años."""
    deficit_acum = kpis.get('deficit_acumulado_hm3', {})
    deficit_prom = kpis.get('deficit_promedio_anual_hm3', {})
    deficit_max = kpis.get('deficit_max_anual_hm3', {})
    deficit_min = kpis.get('deficit_min_anual_hm3', {})
    deficit_std = kpis.get('deficit_std_hm3', {})
    deficit_pct = kpis.get('deficit_pct', {})

    # Usar id_max_deficit (genérico) con fallback a year_max_deficit (legacy)
    id_max = kpis.get('id_max_deficit', kpis.get('year_max_deficit', {}))
    id_min = kpis.get('id_min_deficit', kpis.get('year_min_deficit', {}))
    v0_max = kpis.get('v0_max_deficit', {})
    v0_min = kpis.get('v0_min_deficit', {})

    num_years = kpis.get('num_kpis', 0)

    def1_acum = deficit_acum.get('1R', 0.0)
    def2_acum = deficit_acum.get('2R', 0.0)

    if def1_acum > 0.01 or def2_acum > 0.01:
        if def1_acum > 0.01:
            print("📍 Primeros Regantes (1R):")
            print(
                f"   Déficit: {def1_acum:.2f} Hm³ ({num_years} años) "
                f"= {deficit_pct.get('1R', 0.0):.1f}% demanda"
            )
            print(
                f"   Promedio: {deficit_prom.get('1R', 0.0):.2f} Hm³/año "
                f"± {deficit_std.get('1R', 0.0):.2f} (desv. estándar)"
            )

            # Identificadores críticos (años o escenarios)
            max_str = f"{deficit_max.get('1R', 0.0):.2f} Hm³"
            if id_max.get('1R') is not None:
                max_str += f" ({id_max['1R']}"
                if v0_max.get('1R'):
                    max_str += f", V0={v0_max['1R']:.0f} Hm³"
                max_str += ")"

            min_str = f"{deficit_min.get('1R', 0.0):.2f} Hm³"
            if id_min.get('1R') is not None:
                min_str += f" ({id_min['1R']}"
                if v0_min.get('1R'):
                    min_str += f", V0={v0_min['1R']:.0f} Hm³"
                min_str += ")"

            print(f"   Máximo: {max_str}")
            print(f"   Mínimo: {min_str}")

            # Validación
            agua_eltoro_1r = kpis.get('agua_eltoro_deficit_1r', 0.0)
            tol = 0.001 * def1_acum
            if abs(agua_eltoro_1r - def1_acum) < tol:
                print("   └─ ✅ Embalse compensó 100% del déficit")

        if def2_acum > 0.01:
            print("📍 Segundos Regantes (2R):")
            print(
                f"   Déficit: {def2_acum:.2f} Hm³ ({num_years} años) "
                f"= {deficit_pct.get('2R', 0.0):.1f}% demanda"
            )
            print(
                f"   Promedio: {deficit_prom.get('2R', 0.0):.2f} Hm³/año "
                f"± {deficit_std.get('2R', 0.0):.2f} (desv. estándar)"
            )

            max_str = f"{deficit_max.get('2R', 0.0):.2f} Hm³"
            if id_max.get('2R') is not None:
                max_str += f" ({id_max['2R']}"
                if v0_max.get('2R'):
                    max_str += f", V0={v0_max['2R']:.0f} Hm³"
                max_str += ")"

            min_str = f"{deficit_min.get('2R', 0.0):.2f} Hm³"
            if id_min.get('2R') is not None:
                min_str += f" ({id_min['2R']}"
                if v0_min.get('2R'):
                    min_str += f", V0={v0_min['2R']:.0f} Hm³"
                min_str += ")"

            print(f"   Máximo: {max_str}")
            print(f"   Mínimo: {min_str}")

            # Validación compensación 2R
            agua_eltoro_2r = kpis.get('agua_eltoro_deficit_2r', 0.0)
            tol = 0.001 * def2_acum
            if abs(agua_eltoro_2r - def2_acum) < tol:
                print("   └─ ✅ Embalse compensó 100% del déficit")
    else:
        print("   ✅ Sin déficits naturales")


def export_kpis_to_csv(
    kpis_historicos: List[Dict[str, Any]],
    years: List[int],
    output_file: str = "resultados/kpis_historicos.csv"
) -> None:
    """
    Exporta KPIs históricos a CSV para análisis posterior.

    Args:
        kpis_historicos: Lista de diccionarios de KPIs por año
        years: Lista de años correspondientes
        output_file: Ruta del archivo CSV de salida
    """
    import csv
    from pathlib import Path

    if not kpis_historicos or not years:
        print("⚠️ No hay KPIs para exportar")
        return

    # Crear directorio de salida si no existe
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Definir columnas del CSV
    fieldnames = [
        'year',
        'v0_hm3',
        'v_final_hm3',
        'colchon',
        'generacion_mwh',
        'agua_eltoro_hm3',
        'deficit_1r_hm3',
        'deficit_2r_hm3',
        'presupuesto_riego_hm3',
        'presupuesto_gen_hm3',
        'presupuesto_lago_hm3',
        'uso_riego_pct',
        'uso_gen_pct',
        'cumple_lago',
        'tiempo_inferior_meses',
        'tiempo_transicion_meses',
        'tiempo_intermedio_meses',
        'tiempo_superior_meses',
        'factor_utilizacion_pct',
        'energia_teorica_mwh',
        'cota_promedio_msnm',
        'cota_max_msnm',
        'cota_min_msnm'
    ]

    # Escribir CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for year, kpi in zip(years, kpis_historicos):
            # Extraer valores con manejo de None/missing
            tiempo_colchones = kpi.get('tiempo_colchones', {})
            uso_presupuestos = kpi.get('uso_presupuestos', {})
            factor_util = kpi.get('factor_utilizacion', {})
            cota_mensual = kpi.get('cota_mensual', {})

            # Construir fila
            row = {
                'year': year,
                'v0_hm3': kpi.get('V0', 0.0),
                'v_final_hm3': kpi.get('V_end', 0.0),
                'colchon': kpi.get('colchon', 'N/A'),
                'generacion_mwh': kpi.get('generacion_total', 0.0),
                'agua_eltoro_hm3': kpi.get('agua_eltoro_total', 0.0),
                'deficit_1r_hm3': kpi.get('deficit_1r_hm3', 0.0),
                'deficit_2r_hm3': kpi.get('deficit_2r_hm3', 0.0),
                'presupuesto_riego_hm3': uso_presupuestos.get(
                    'presupuesto_riego', 0.0
                ),
                'presupuesto_gen_hm3': uso_presupuestos.get(
                    'presupuesto_gen', 0.0
                ),
                'presupuesto_lago_hm3': uso_presupuestos.get(
                    'presupuesto_lago', 0.0
                ),
                'uso_riego_pct': uso_presupuestos.get('uso_riego_pct', 0.0),
                'uso_gen_pct': uso_presupuestos.get('uso_gen_pct', 0.0),
                'cumple_lago': uso_presupuestos.get('cumple_lago', False),
                'tiempo_inferior_meses': tiempo_colchones.get('Inferior', 0),
                'tiempo_transicion_meses': tiempo_colchones.get(
                    'Transicion', 0
                ),
                'tiempo_intermedio_meses': tiempo_colchones.get(
                    'Intermedio', 0
                ),
                'tiempo_superior_meses': tiempo_colchones.get('Superior', 0),
                'factor_utilizacion_pct': factor_util.get(
                    'factor_utilizacion_pct', 0.0
                ),
                'energia_teorica_mwh': factor_util.get(
                    'energia_teorica_total', 0.0
                ),
                'cota_promedio_msnm': (
                    sum(cota_mensual.values()) / len(cota_mensual)
                    if cota_mensual else 0.0
                ),
                'cota_max_msnm': max(cota_mensual.values())
                if cota_mensual else 0.0,
                'cota_min_msnm': min(cota_mensual.values())
                if cota_mensual else 0.0
            }

            writer.writerow(row)

    print(f"✅ KPIs exportados a: {output_file}")
