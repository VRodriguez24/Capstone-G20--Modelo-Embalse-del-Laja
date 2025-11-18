"""
Módulo de KPIs para el Embalse del Laja
=======================================

Implementa 4 KPIs estratégicos para evaluar la operación del Embalse del Laja.

📊 KPIs ESTRATÉGICOS:

1. TIEMPO EN COLCHONES OPERATIVOS (%)
   - Distribución temporal por rangos de volumen
   - Rangos: Inferior, Transición, Intermedio, Superior

2. USO DE PRESUPUESTOS RIEGO/GENERACIÓN (%)
   - Eficiencia en asignación de recursos hídricos
   - (Uso_real / Presupuesto_asignado) x 100

3. DÉFICITS DE RIEGO (Hm³ y %)
   - Déficit consolidado primeros regantes (min{Tucapel, Abanico})
   - Déficit segundos regantes
   - Demanda 1R extraída directamente del modelo (RHS restricciones balance)
   - Métricas: máximo, promedio, total anual, % demanda

4. FACTOR DE UTILIZACIÓN (%)
   - Eficiencia hidráulica ponderada por capacidad instalada
   - Σ(FU_central x Cap_central) / Σ(Cap_central)

📈 FUNCIONES:
- extract_kpis(model): Extrae KPIs de modelo optimizado
- aggregate_kpis(kpis_list): Agrega KPIs multi-año/Monte Carlo
- print_kpis(kpis, context): Formato legible console
- export_kpis_to_csv(kpis, output_dir, year): Solo muestra en consola
"""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np

# Importar conversión volumen→cota
from filt_cota import cota_from_volumen


# ============================================================================
# EXTRACCIÓN DE KPIs INDIVIDUALES
# ============================================================================

def extract_kpis(model, include_detailed: bool = True) -> Dict[str, Any]:
    """
    Extrae KPIs estratégicos de un modelo optimizado.

    Args:
        model: Modelo Gurobi optimizado con variables del embalse
        include_detailed: Incluir métricas detalladas (compatibilidad)

    Returns:
        Dict con estructura:
            - status: Estado optimización (2=óptimo)
            - obj_MWh: Energía total generada
            - V_end: Volumen final (Hm³)
            - tiempo_colchones_%: % tiempo por colchón
            - uso_presupuestos_%: % uso riego/generación
            - deficit_max_hm3: Déficit máximo 1R/2R
            - deficit_prom_hm3: Déficit promedio mensual 1R/2R
            - deficit_sum_hm3: Déficit total anual 1R/2R
            - deficit_pct: Déficit como % demanda 1R/2R
            - factor_utilizacion_%: Factor utilización sistema
            - cota_mensual: Cotas por mes (msnm)
            - volumenes_mensuales: Volúmenes por mes (Hm³)
    """
    # Validación básica
    if not hasattr(model, 'status'):
        return _empty_kpis()

    # KPIs básicos
    basic_kpis = {
        'status': model.status,
        'obj_MWh': model.objVal if hasattr(model, 'objVal') else None,
        'V_end': None
    }

    # Extraer volumen final
    if hasattr(model, '_V'):
        from model import T
        final_month = max(T)
        basic_kpis['V_end'] = model._V[final_month].x

    # Si no es óptimo, retornar solo básicos
    if model.status != 2:
        basic_kpis.update(_empty_kpis())
        return basic_kpis

    # Calcular KPIs estratégicos completos
    strategic_kpis = _calculate_strategic_kpis(model)
    basic_kpis.update(strategic_kpis)

    return basic_kpis


def _empty_kpis() -> Dict[str, Any]:
    """Retorna estructura vacía de KPIs para casos no óptimos."""
    return {
        'tiempo_colchones_%': {},
        'uso_presupuestos_%': {'riego': 0.0, 'generacion': 0.0},
        'deficit_max_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_prom_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_sum_hm3': {'1R': 0.0, '2R': 0.0},
        'deficit_pct': {'1R': 0.0, '2R': 0.0},
        'factor_utilizacion_%': {'sistema': 0.0},
        'cota_mensual': {},
        'volumenes_mensuales': {}
    }


def _calculate_strategic_kpis(model) -> Dict[str, Any]:
    """
    Calcula los 4 KPIs estratégicos del modelo optimizado.

    KPI 3 - Extracción exacta de demandas desde metadata del modelo:
    - Demandas almacenadas en model._meta['demandas_mensuales']
    - Garantiza coincidencia exacta con restricciones del modelo
    - Demanda total 1R = Demanda_Tucapel + Demanda_Abanico
    - Def1 = min{DefTu, DefAb} (déficit consolidado que El Toro compensa)
    - % Déficit = (Def1_total / Demanda_total_1R) × 100

    Args:
        model: Modelo optimizado (status=2)

    Returns:
        Dict con KPIs calculados
    """
    from model import T, Conv, COLCHONES, C_LABELS

    # ========================================================================
    # PASO 1: Extraer datos base del modelo
    # ========================================================================

    volumenes_mensuales = {}
    cota_mensual = {}

    for t in T:
        volumen_hm3 = model._V[t].x
        volumenes_mensuales[t] = volumen_hm3
        cota_mensual[t] = cota_from_volumen(volumen_hm3)

    # ========================================================================
    # KPI 1: TIEMPO EN COLCHONES
    # ========================================================================

    tiempo_colchones = {c: 0 for c in C_LABELS}

    for t in T:
        volumen = volumenes_mensuales[t]
        for c in C_LABELS:
            lo = COLCHONES[c]["lo"]
            hi = COLCHONES[c]["hi"]
            eps = 1e-3 if c != "Inferior" else 0.0
            if lo + eps <= volumen <= hi:
                tiempo_colchones[c] += 1
                break

    tiempo_colchones_pct = {
        c: (count / len(T)) * 100.0
        for c, count in tiempo_colchones.items()
    }

    # ========================================================================
    # KPI 2: USO DE PRESUPUESTOS
    # ========================================================================
    # CÁLCULO BASADO EN RESTRICCIONES R7e y R7f DEL MODELO:
    # - Budget: Según colchón activo (R7), valor fijo o % de V_inicial
    # - Uso riego: Σ(Def1 + Def2) para todo t (cobertura desde El Toro)
    # - Uso generación: Total El Toro - Uso riego
    # - Fórmula: (Uso / Budget) × 100

    # 1. Identificar colchón activo y calcular presupuestos
    budget_riego = 0.0
    budget_gen = 0.0
    v_inicial = model.getVarByName("Vinit")
    v_init_val = v_inicial.x if v_inicial else 1400.0

    for c in C_LABELS:
        z_var = model.getVarByName(f"z[{c}]")
        if z_var and z_var.x > 0.5:
            r_share, g_share, _ = COLCHONES[c]["shares"]

            # Budget riego
            if r_share > 1.0:
                budget_riego = r_share
            else:
                budget_riego = r_share * v_init_val

            # Budget generación (con cap de 1200 Hm³ si Superior)
            if g_share > 1.0:
                budget_gen = g_share
            else:
                budget_gen = g_share * v_init_val

            if c == "Superior":
                budget_gen = min(budget_gen, 1200.0)

            break

    # 2. Calcular uso real desde variables del modelo
    # Uso RIEGO: Σ(Def1 + Def2) - cobertura de déficits desde El Toro
    uso_riego_hm3 = 0.0
    for t in T:
        try:
            def1 = model.getVarByName(f"Deficit1erosRegantes[{t}]")
            def2 = model.getVarByName(f"Deficit2dosRegantes[{t}]")
            if def1 and def2:
                uso_riego_hm3 += def1.x + def2.x
        except Exception:
            pass

    # Uso GENERACIÓN: Total El Toro - Uso riego (compatibilidad _x o _y)
    uso_toro_total = 0.0
    if hasattr(model, '_x'):
        for t in T:
            x_var = model._x.get(("Embalse", "ElToro", t))
            if x_var:
                uso_toro_total += x_var.x * Conv
    elif hasattr(model, '_y'):
        for t in T:
            y_var = model._y.get(("Embalse", "ElToro", t))
            if y_var:
                uso_toro_total += y_var.x * Conv

    # CORRECCIÓN: Detectar si es modelo con generación
    # Solo calcular uso_gen si existe variable _G (modelo con generación)
    if hasattr(model, '_G'):
        uso_gen_hm3 = uso_toro_total - uso_riego_hm3
    else:
        # Caso base: todo el agua de El Toro va a riego, no hay generación
        uso_gen_hm3 = 0.0
        uso_riego_hm3 = uso_toro_total  # Corregir: todo es para riego

    # 3. Calcular porcentajes
    if budget_riego > 0:
        uso_riego_pct = (uso_riego_hm3 / budget_riego) * 100.0
    else:
        uso_riego_pct = 0.0

    if budget_gen > 0:
        uso_gen_pct = (uso_gen_hm3 / budget_gen) * 100.0
    else:
        uso_gen_pct = 0.0

    uso_presupuestos_pct = {
        "riego": uso_riego_pct,
        "generacion": uso_gen_pct
    }

    # ========================================================================
    # KPI 3: DÉFICITS DE RIEGO
    # ========================================================================
    # CORRECCIÓN CRÍTICA: Usar Def1 (consolidado) en lugar de DefTu + DefAb

    deficit_mensual_1R = {}  # Déficit consolidado primeros regantes
    deficit_mensual_2R = {}  # Déficit segundos regantes
    demanda_1R_mensual = {}  # Demanda base primeros (Tucapel como referencia)
    demanda_2R_mensual = {}  # Demanda segundos

    for t in T:
        # ====================================================================
        # EXTRACCIÓN EXACTA DESDE METADATA DEL MODELO
        # ====================================================================
        # Las demandas se calculan en model.py y se almacenan en _meta
        # Esto garantiza que usamos exactamente los mismos valores que
        # el modelo utilizó en las restricciones de balance

        demandas = model._meta.get('demandas_mensuales', {})
        dem_tucapel = demandas.get('tucapel', {}).get(t, 0.0)
        dem_abanico = demandas.get('abanico', {}).get(t, 0.0)
        dem_2r = demandas.get('segundos', {}).get(t, 0.0)

        # Demanda TOTAL primeros regantes = Tucapel + Abanico
        # (ambas demandas independientes según restricciones R6.1a y R6.1b)
        dem_1r = dem_tucapel + dem_abanico

        demanda_1R_mensual[t] = dem_1r
        demanda_2R_mensual[t] = dem_2r

        # ====================================================================
        # DÉFICITS: Extraer valores de variables del modelo
        # ====================================================================
        def_1r = 0.0
        def_2r = 0.0

        try:
            # Def1 = min{DefTu, DefAb} - variable consolidada del modelo
            v = model.getVarByName(f"Deficit1erosRegantes[{t}]")
            if v:
                def_1r = v.x
        except Exception:
            pass

        try:
            # Def2 = déficit segundos regantes - variable directa del modelo
            v = model.getVarByName(f"Deficit2dosRegantes[{t}]")
            if v:
                def_2r = v.x
        except Exception:
            pass

        deficit_mensual_1R[t] = def_1r
        deficit_mensual_2R[t] = def_2r

    # Métricas agregadas
    def1_values = list(deficit_mensual_1R.values())
    def2_values = list(deficit_mensual_2R.values())

    def1_sum = float(np.sum(def1_values)) if def1_values else 0.0
    def2_sum = float(np.sum(def2_values)) if def2_values else 0.0
    def1_prom = float(np.mean(def1_values)) if def1_values else 0.0
    def2_prom = float(np.mean(def2_values)) if def2_values else 0.0
    def1_max = float(np.max(def1_values)) if def1_values else 0.0
    def2_max = float(np.max(def2_values)) if def2_values else 0.0

    # Demandas totales anuales
    demanda_1R_tot = float(np.sum(list(demanda_1R_mensual.values())))
    demanda_2R_tot = float(np.sum(list(demanda_2R_mensual.values())))

    # Porcentajes de déficit respecto demanda
    if demanda_1R_tot > 0:
        pct_def1 = def1_sum / demanda_1R_tot * 100.0
    else:
        pct_def1 = 0.0

    if demanda_2R_tot > 0:
        pct_def2 = def2_sum / demanda_2R_tot * 100.0
    else:
        pct_def2 = 0.0

    # ========================================================================
    # KPI 4: FACTOR DE UTILIZACIÓN
    # ========================================================================

    factor_utilizacion = _calculate_utilization_factor(model, T)

    # ========================================================================
    # RETORNAR KPIS COMPLETOS
    # ========================================================================

    return {
        'tiempo_colchones_%': tiempo_colchones_pct,
        'uso_presupuestos_%': uso_presupuestos_pct,
        'deficit_max_hm3': {'1R': def1_max, '2R': def2_max},
        'deficit_prom_hm3': {'1R': def1_prom, '2R': def2_prom},
        'deficit_sum_hm3': {'1R': def1_sum, '2R': def2_sum},
        'deficit_pct': {'1R': pct_def1, '2R': pct_def2},
        'deficit_mensual_1R': deficit_mensual_1R,
        'deficit_mensual_2R': deficit_mensual_2R,
        'demanda_1R_tot': demanda_1R_tot,
        'demanda_2R_tot': demanda_2R_tot,
        'factor_utilizacion_%': factor_utilizacion,
        'cota_mensual': cota_mensual,
        'volumenes_mensuales': volumenes_mensuales
    }


# ============================================================================
# FUNCIONES AUXILIARES DE CÁLCULO
# ============================================================================

def _calculate_water_usage(
        model, T: List[int], Conv: float) -> Tuple[float, float]:
    """
    Calcula uso real de agua para riego y generación (Hm³).
    
    CORRECCIÓN: Detecta automáticamente si es modelo con generación.
    - Modelo con generación (_G): Calcula riego y generación separado
    - Caso base (sin _G): Todo el agua de El Toro es para riego
    """
    uso_riego_hm3 = 0.0
    uso_gen_hm3 = 0.0

    # Detectar tipo de modelo
    is_energy_model = hasattr(model, '_G')

    if is_energy_model:
        # Modelo con generación: importar A_generacion
        try:
            from model import A_generacion
            
            # GENERACIÓN: Agua usada en centrales hidroeléctricas
            if hasattr(model, '_x'):
                for (i, j) in A_generacion:
                    try:
                        for t in T:
                            if (i, j, t) in model._x:
                                uso_gen_hm3 += model._x[i, j, t].x * Conv
                    except Exception:
                        pass
            elif hasattr(model, '_y'):
                for (i, j) in A_generacion:
                    try:
                        for t in T:
                            if (i, j, t) in model._y:
                                uso_gen_hm3 += model._y[i, j, t].x * Conv
                    except Exception:
                        pass
        except ImportError:
            pass  # Si no existe A_generacion, no hay generación

        # RIEGO: Extracción total desde El Toro menos generación
        try:
            total_toro = 0.0
            for t in T:
                toro_key = ("Embalse", "ElToro", t)
                if hasattr(model, '_x') and toro_key in model._x:
                    total_toro += model._x[toro_key].x * Conv
                elif hasattr(model, '_y') and toro_key in model._y:
                    total_toro += model._y[toro_key].x * Conv
            
            uso_riego_hm3 = max(0.0, total_toro - uso_gen_hm3)
        except Exception:
            pass
    else:
        # Caso base: TODO el agua de El Toro es para riego
        try:
            for t in T:
                toro_key = ("Embalse", "ElToro", t)
                if hasattr(model, '_y') and toro_key in model._y:
                    uso_riego_hm3 += model._y[toro_key].x * Conv
        except Exception:
            pass

    return uso_riego_hm3, uso_gen_hm3


def _calculate_budgets(
        model, C_LABELS: List[str],
        COLCHONES: Dict) -> Tuple[float, float]:
    """Calcula presupuestos de riego y generación según colchón activo."""
    v_inicial = model.getVarByName("Vinit")
    v_init_val = v_inicial.x if v_inicial else 1400.0

    presupuesto_riego = 0.0
    presupuesto_gen = 0.0

    # Identificar colchón activo (z[c]=1)
    for c in C_LABELS:
        z_var = model.getVarByName(f"z[{c}]")
        if z_var and z_var.x > 0.5:
            r_share, g_share, _ = COLCHONES[c]["shares"]
            if r_share > 1.0:
                presupuesto_riego = r_share
            else:
                presupuesto_riego = r_share * v_init_val

            if g_share > 1.0:
                presupuesto_gen = g_share
            else:
                presupuesto_gen = g_share * v_init_val
            break

    return presupuesto_riego, presupuesto_gen


def _calculate_utilization_factor(model, T: List[int]) -> Dict[str, float]:
    """Calcula factor de utilización ponderado por capacidad instalada."""
    factor_utilizacion = {"sistema": 0.0}

    try:
        # Obtener cap_max desde model._meta
        if not hasattr(model, '_meta') or 'cap_max' not in model._meta:
            return factor_utilizacion

        cap_max = model._meta['cap_max']
        A_generacion = model._meta.get('A_generacion', [])

        if cap_max and (hasattr(model, '_x') or hasattr(model, '_y')):
            uso_total_ponderado = 0.0
            capacidad_total_ponderada = 0.0

            for (i, j) in A_generacion:
                if (i, j) in cap_max and cap_max[(i, j)] is not None:
                    capacidad_max = cap_max[(i, j)]

                    # Uso real anual (m³/s)
                    uso_central = 0.0
                    if hasattr(model, '_x'):
                        uso_central = sum(
                            model._x[i, j, t].x for t in T
                            if (i, j, t) in model._x
                        )
                    elif hasattr(model, '_y'):
                        uso_central = sum(
                            model._y[i, j, t].x for t in T
                            if (i, j, t) in model._y
                        )

                    # Capacidad disponible anual (m³/s * 12 meses)
                    capacidad_anual = capacidad_max * len(T)

                    # Factor utilización individual
                    if capacidad_anual > 0:
                        fu_central = uso_central / capacidad_anual
                    else:
                        fu_central = 0.0

                    # Ponderar por capacidad
                    peso = capacidad_max
                    uso_total_ponderado += fu_central * peso
                    capacidad_total_ponderada += peso

            # Factor del sistema (promedio ponderado)
            if capacidad_total_ponderada > 0:
                factor_utilizacion["sistema"] = (
                    uso_total_ponderado / capacidad_total_ponderada * 100.0
                )
    except Exception:
        pass

    return factor_utilizacion


# ============================================================================
# AGREGACIÓN DE KPIs MULTI-AÑO / MONTE CARLO
# ============================================================================

def aggregate_kpis(kpis_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Agrega múltiples KPIs para análisis Monte Carlo o histórico.

    Args:
        kpis_list: Lista de KPIs individuales (uno por simulación/año)

    Returns:
        Dict con KPIs agregados:
            - Promedios de KPIs estratégicos
            - Trayectorias promedio mensuales
            - Metadata (num_kpis, num_total)
    """
    if not kpis_list:
        return {}

    # Filtrar solo KPIs válidos (status=2 óptimo)
    valid_kpis = [
        kpi for kpi in kpis_list
        if kpi.get('status') == 2 and kpi.get('tiempo_colchones_%')
    ]

    if not valid_kpis:
        return {"error": "No hay KPIs válidos para agregar"}

    from model import T

    # KPI 1: Promedio tiempo en colchones
    colchones_agregados = _aggregate_dict_values(
        valid_kpis, 'tiempo_colchones_%',
        ["Inferior", "Transicion", "Intermedio", "Superior"]
    )

    # KPI 2: Promedio uso de presupuestos (normalizado por años)
    uso_presupuestos_agregado = _aggregate_dict_values(
        valid_kpis, 'uso_presupuestos_%',
        ["riego", "generacion"]
    )
    # Normalizar: el agregado ya promedia correctamente
    # (cada año calcula su % individual, luego se promedian)

    # KPI 3: Déficits agregados
    deficit_max_agregado = {
        '1R': _aggregate_max(valid_kpis, 'deficit_max_hm3', '1R'),
        '2R': _aggregate_max(valid_kpis, 'deficit_max_hm3', '2R')
    }

    deficit_prom_agregado = {
        '1R': _aggregate_mean(valid_kpis, 'deficit_prom_hm3', '1R'),
        '2R': _aggregate_mean(valid_kpis, 'deficit_prom_hm3', '2R')
    }

    deficit_sum_agregado = {
        '1R': _aggregate_sum(valid_kpis, 'deficit_sum_hm3', '1R'),
        '2R': _aggregate_sum(valid_kpis, 'deficit_sum_hm3', '2R')
    }

    # Recalcular porcentajes sobre demandas totales
    total_demand_1R = sum(kpi.get('demanda_1R_tot', 0.0) for kpi in valid_kpis)
    total_demand_2R = sum(kpi.get('demanda_2R_tot', 0.0) for kpi in valid_kpis)

    deficit_pct_agregado = {
        '1R': (deficit_sum_agregado['1R'] / total_demand_1R * 100.0
               if total_demand_1R > 0 else 0.0),
        '2R': (deficit_sum_agregado['2R'] / total_demand_2R * 100.0
               if total_demand_2R > 0 else 0.0)
    }

    # KPI 4: Promedio factor utilización
    factor_utilizacion_agregado = _aggregate_dict_values(
        valid_kpis, 'factor_utilizacion_%',
        ["sistema"]
    )

    # Trayectorias mensuales
    cota_mensual_agregada = _aggregate_monthly_values(
        valid_kpis, 'cota_mensual', T
    )

    return {
        'tiempo_colchones_%': colchones_agregados,
        'uso_presupuestos_%': uso_presupuestos_agregado,
        'deficit_max_hm3': deficit_max_agregado,
        'deficit_prom_hm3': deficit_prom_agregado,
        'deficit_sum_hm3': deficit_sum_agregado,
        'deficit_pct': deficit_pct_agregado,
        'factor_utilizacion_%': factor_utilizacion_agregado,
        'cota_mensual': cota_mensual_agregada,
        'num_kpis': len(valid_kpis),
        'num_total': len(kpis_list)
    }


def _aggregate_dict_values(kpis_list: List[Dict], key: str,
                           subkeys: List[str]) -> Dict[str, float]:
    """Agrega valores de diccionario anidado promediando."""
    result = {}
    for subkey in subkeys:
        valores = [
            kpi.get(key, {}).get(subkey, 0.0)
            for kpi in kpis_list
        ]
        result[subkey] = np.mean(valores) if valores else 0.0
    return result


def _aggregate_max(kpis_list: List[Dict], key: str, subkey: str) -> float:
    """Agrega tomando el máximo."""
    valores = [kpi.get(key, {}).get(subkey, 0.0) for kpi in kpis_list]
    return float(np.max(valores)) if valores else 0.0


def _aggregate_mean(kpis_list: List[Dict], key: str, subkey: str) -> float:
    """Agrega tomando el promedio."""
    valores = [kpi.get(key, {}).get(subkey, 0.0) for kpi in kpis_list]
    return float(np.mean(valores)) if valores else 0.0


def _aggregate_sum(kpis_list: List[Dict], key: str, subkey: str) -> float:
    """Agrega tomando la suma."""
    return sum(kpi.get(key, {}).get(subkey, 0.0) for kpi in kpis_list)


def _aggregate_monthly_values(kpis_list: List[Dict], key: str,
                              T: List[int]) -> Dict[int, float]:
    """Agrega valores mensuales promediando por mes."""
    result = {}
    for t in T:
        valores_mes = [
            kpi.get(key, {}).get(t, 0.0)
            for kpi in kpis_list if kpi.get(key)
        ]
        result[t] = np.mean(valores_mes) if valores_mes else 0.0
    return result


# ============================================================================
# VISUALIZACIÓN Y EXPORTACIÓN
# ============================================================================

def print_kpis(kpis: Dict[str, Any], context: str = "",
               is_caso_base: bool = False) -> None:
    """
    Imprime KPIs en formato legible para análisis operacional.

    Args:
        kpis: Diccionario con KPIs calculados
        context: Contexto del análisis ("año XXXX", "histórico", etc.)
        is_caso_base: Si True, oculta KPI 2 y muestra solo 1R en KPI 3
    """
    if not kpis or 'tiempo_colchones_%' not in kpis:
        print("⚠️ No hay KPIs válidos para mostrar")
        return

    # Detectar automáticamente si es caso base
    # (generación = 0% indica modelo sin generación)
    presupuestos = kpis.get('uso_presupuestos_%', {})
    gen_pct = presupuestos.get('generacion', 0)
    if gen_pct == 0.0:
        is_caso_base = True

    # Título
    titulo = "📊 KPIs ESTRATÉGICOS"
    if context:
        titulo += f" - {context}"

    num_kpis = kpis.get('num_kpis')
    if num_kpis:
        titulo += f" ({num_kpis} casos)"

    print("=" * len(titulo))
    print(f"{titulo}")
    print("=" * len(titulo))

    # KPI 1: Tiempo en colchones
    print("\n🏗️  KPI 1 - TIEMPO EN COLCHONES OPERATIVOS:")
    colchones_data = kpis.get('tiempo_colchones_%', {})
    for colchon, porcentaje in colchones_data.items():
        emoji = {"Inferior": "🔴", "Transicion": "🟡",
                 "Intermedio": "🟢", "Superior": "🔵"}.get(colchon, "⚪")
        print(f"   {emoji} {colchon:12s}: {porcentaje:6.1f}%")

    # KPI 2: Uso de presupuestos (solo para modelo con generación)
    if not is_caso_base:
        print("\n💰 KPI 2 - USO DE PRESUPUESTOS:")
        print(f"   🌾 Riego:      {presupuestos.get('riego', 0):6.1f}%")
        print(f"   ⚡ Generación: {gen_pct:6.1f}%")

    # KPI 3: Déficits (solo 1R para caso base)
    print("\n📉 KPI 3 - DÉFICITS DE RIEGO:")
    dm = kpis.get('deficit_max_hm3', {})
    dp = kpis.get('deficit_prom_hm3', {})
    ds = kpis.get('deficit_sum_hm3', {})
    pct = kpis.get('deficit_pct', {})

    print("📍 Primeros Regantes (1R):")
    print(f"      • Déficit máximo:  {dm.get('1R', 0.0):7.2f} Hm³")
    print(f"      • Déficit promedio: {dp.get('1R', 0.0):7.3f} Hm³/mes")
    print(f"      • Déficit total:    {ds.get('1R', 0.0):7.2f} Hm³ "
          f"({pct.get('1R', 0.0):5.2f}% demanda)")

    if not is_caso_base:
        print("📍 Segundos Regantes (2R):")
        print(f"      • Déficit máximo:  {dm.get('2R', 0.0):7.2f} Hm³")
        print(f"      • Déficit promedio: {dp.get('2R', 0.0):7.3f} Hm³/mes")
        print(f"      • Déficit total:    {ds.get('2R', 0.0):7.2f} Hm³ "
              f"({pct.get('2R', 0.0):5.2f}% demanda)")

    # KPI 4: Factor utilización (solo para modelo con generación)
    if not is_caso_base:
        print("\n🏗️  KPI 4 - FACTOR DE UTILIZACIÓN:")
        fu_data = kpis.get('factor_utilizacion_%', {})
        print(f"   🏭 Sistema: {fu_data.get('sistema', 0):6.1f}%")

    # Resumen operacional
    print("\n📋 RESUMEN OPERACIONAL:")
    cota_data = kpis.get('cota_mensual', {})
    if cota_data:
        cota_promedio = sum(cota_data.values()) / len(cota_data)
        cota_min = min(cota_data.values())
        cota_max = max(cota_data.values())
        print(f"   📏 Cota promedio: {cota_promedio:6.1f} msnm")
        print(f"   📏 Rango: [{cota_min:6.1f}, {cota_max:6.1f}] msnm")


def export_kpis_to_csv(kpis: Dict[str, Any],
                       output_dir: str = "resultados/kpis",
                       year: Optional[int] = None,
                       scenario: str = "") -> List[str]:
    """
    Muestra KPIs en consola (sin generar archivos).

    NOTA: Función renombrada pero mantiene firma para compatibilidad.
    Solo imprime KPIs en consola, no genera archivos Excel.

    Args:
        kpis: Diccionario con KPIs calculados
        output_dir: (Ignorado - compatibilidad)
        year: Año de análisis (para contexto en consola)
        scenario: Escenario (para contexto en consola)

    Returns:
        Lista vacía (compatibilidad con código existente)
    """
    if not kpis or 'tiempo_colchones_%' not in kpis:
        return []

    # Construir contexto para print_kpis
    context_parts = []
    if year:
        context_parts.append(f"Año {year}")
    if scenario:
        context_parts.append(scenario)
    context = " - ".join(context_parts) if context_parts else ""

    # Mostrar KPIs en consola
    print_kpis(kpis, context=context)

    # No generar archivos, retornar lista vacía
    return []


def generate_historical_plots(
    kpis_historicos: List[Dict[str, Any]],
    years: List[int],
    output_dir: str = "resultados",
    plot_name: str = "evolucion_historica_lago"
) -> List[str]:
    """
    Genera gráficos de evolución histórica para análisis visual.
    
    Args:
        kpis_historicos: Lista de KPIs calculados por año
        years: Lista de años correspondientes
        output_dir: Directorio donde guardar los gráficos
        plot_name: Nombre del archivo PNG (sin extensión)
        
    Returns:
        List[str]: Lista de rutas de archivos PNG generados
    """
    from pathlib import Path
    import matplotlib.pyplot as plt
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    files_created = []

    if not kpis_historicos or not years:
        return files_created

    # Configurar matplotlib
    plt.rcParams['font.size'] = 10
    plt.rcParams['figure.figsize'] = (12, 8)

    # Crear figura con 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # Extraer datos anuales
    cotas_anuales = []
    dependencias_anuales = []

    for kpis in kpis_historicos:
        cota_data = kpis.get('cota_mensual', {})
        cota_promedio = (
            sum(cota_data.values()) / len(cota_data)
            if cota_data else 0.0
        )
        cotas_anuales.append(cota_promedio)

        dependencia_data = kpis.get('dependencia_lago_m3s', {})
        dependencia_total = (
            sum(dependencia_data.values())
            if dependencia_data else 0.0
        )
        dependencias_anuales.append(dependencia_total)

    # Subplot 1: Evolución de cota
    ax1.plot(years, cotas_anuales, 'b-o', linewidth=2, markersize=4)
    ax1.set_title('Evolución Histórica del Nivel del Lago',
                  fontweight='bold')
    ax1.set_xlabel('Año')
    ax1.set_ylabel('Cota promedio [msnm]')
    ax1.grid(True, alpha=0.3)

    # Subplot 2: Dependencia del lago
    ax2.bar(years, dependencias_anuales, alpha=0.7, color='coral')
    ax2.set_title('Dependencia Anual del Embalse para Cubrir Déficits',
                  fontweight='bold')
    ax2.set_xlabel('Año')
    ax2.set_ylabel('Déficit total anual [m³/s]')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # Guardar gráfico
    plot_file = output_path / f"{plot_name}.png"
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    plt.close()
    files_created.append(str(plot_file))

    return files_created
