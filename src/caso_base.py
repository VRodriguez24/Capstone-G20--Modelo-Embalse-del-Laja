from typing import Tuple, Optional
import os
import sys
import time
import psutil
import gurobipy as gp
from datetime import datetime
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import NODES, ARCS, A_inyeccion, IN, OUT
# --- Datos (CSV) ---
from data_loader import load_caudalmax, load_injections_for_year
# --- Filtraciones y cotas ---
from filt_cota import build_pwl_final_segments
# --- KPIs ---
from kpi import (
    extract_kpis,
    aggregate_kpis,
    print_kpis,
    export_kpis_to_csv,
    generate_historical_plots
)

# =============================
# CONFIGURACIÓN (parámetros)
# =============================
# Detectar rutas automáticamente
if os.path.exists("data/CaudalMax_filtrado.csv"):
    CAUDALMAX_CSV = "data/CaudalMax_filtrado.csv"
    INJ_CSV = "data/Caudales_historicos_filtrado.csv"
else:
    CAUDALMAX_CSV = "../data/CaudalMax_filtrado.csv"
    INJ_CSV = "../data/Caudales_historicos_filtrado.csv"

# Rango de años a correr (el script usará min/max e iterará entre ambos)
YEARS_HORIZON = [1960, 2023]

# Período hidrológico: Diciembre a Noviembre (30 nov = fin de temporada)
T = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# Reglas de riego / ecológico (constantes, mismos valores para todo t)
TUCAPEL_MIN = 90.0     # m3/s
ABANICO_MIN = 47.0     # m3/s
# SALTOS_MIN = 7.0       # m3/s
# SALTOS_MIN_T = {t: SALTOS_MIN for t in T}  # comodidad para indexar por t

# Curvas estacionales para 1° y 2° regantes (factor por mes 1..12).
# Tomadas de la Tabla N°2 (imagen). Valores entre 0 y 1.
# Columnas usadas: 1° Regantes y 2° Regantes
# NOTA: Los factores siguen siendo por mes calendario (1=Ene, 12=Dic)
FIRST_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 1.00, 10: 1.00, 11: 1.00, 12: 1.00
}

# Big-M y conversión
M = 6000                        # Big-M
EPS = 1e-3                      # epsilon para desambiguar límites
Conv = (86400 * 30) / 1e6       # m^3/s x mes -> Hm3

# Volúmenes embalse (Hm3) - Basado en ANEXO N°1
V_0 = 1400.0  # Volumen inicial por defecto
V_min = 0.0     # Volumen mínimo
V_max = 5582.0  # Volumen máximo

# Configuración de filtraciones del embalse El Toro
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")


# =============================
# FUNCIONES DE RENDIMIENTO
# =============================

def get_performance_stats(start_time: float, process: psutil.Process) -> dict:
    """
    Calcula estadísticas de rendimiento del sistema.
    
    Args:
        start_time: Tiempo de inicio de la ejecución (time.time())
        process: Proceso actual de psutil
        
    Returns:
        dict: Estadísticas de rendimiento incluyendo tiempo y memoria
    """
    execution_time = time.time() - start_time
    
    # Obtener información de memoria
    memory_info = process.memory_info()
    memory_percent = process.memory_percent()
    
    # Información del sistema
    system_memory = psutil.virtual_memory()
    
    return {
        "execution_time_seconds": execution_time,
        "execution_time_formatted": format_time(execution_time),
        "memory_rss_mb": memory_info.rss / (1024 * 1024),  # RSS en MB
        "memory_vms_mb": memory_info.vms / (1024 * 1024),  # VMS en MB
        "memory_percent": memory_percent,
        "system_memory_total_gb": system_memory.total / (1024 * 1024 * 1024),
        "system_memory_available_gb": system_memory.available / (1024 * 1024 * 1024),
        "system_memory_used_percent": system_memory.percent
    }

def format_time(seconds: float) -> str:
    """
    Formatea tiempo en segundos a un formato legible.
    
    Args:
        seconds: Tiempo en segundos
        
    Returns:
        str: Tiempo formateado (ej: "2h 15m 30s" o "45.2s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"

def print_performance_stats(stats: dict, context: str = ""):
    """
    Imprime estadísticas de rendimiento en formato legible.
    
    Args:
        stats: Diccionario con estadísticas de rendimiento
        context: Contexto adicional para el título
    """
    print(f"\n{'=' * 60}")
    print(f"⚡ ESTADÍSTICAS TÉCNICAS DE RENDIMIENTO {context}")
    print(f"{'=' * 60}")
    print(f"🕒 Tiempo de ejecución: {stats['execution_time_formatted']}")
    print(f"💾 Memoria RAM utilizada:")
    print(f"   • RSS (Resident Set Size): {stats['memory_rss_mb']:.1f} MB")
    print(f"   • VMS (Virtual Memory Size): {stats['memory_vms_mb']:.1f} MB")
    print(f"   • Porcentaje del sistema: {stats['memory_percent']:.2f}%")
    print(f"🖥️  Memoria del sistema:")
    print(f"   • Total: {stats['system_memory_total_gb']:.1f} GB")
    print(f"   • Disponible: {stats['system_memory_available_gb']:.1f} GB")
    print(f"   • Uso del sistema: {stats['system_memory_used_percent']:.1f}%")
    print(f"{'=' * 60}")


# =============================
# FUNCIONES AUXILIARES PWL
# =============================
def add_pwl_filtration_constraints(
    model,
    Filtr_vars,
    Vprev_vars,
    time_periods: list,
    filtr_arc: tuple,
    segments: dict,
    bigM: float,
    v_max: float,
):
    """
    Agrega restricciones PWL para filtraciones con variables binarias.

    Implementa la linearización de la función no-lineal de filtraciones
    usando segmentación PWL con variables binarias δ_{k,t}.

    Args:
        model: Modelo de Gurobi
        Filtr_vars: Variables de filtración por período
        Vprev_vars: Variables de volumen previo por período
        time_periods: Lista de períodos de tiempo
        filtr_arc: Tupla (origen, destino) del arco de filtración
        segments: Diccionario de segmentos PWL de filt_cota
        bigM: Valor Big-M para linearización
        v_max: Volumen máximo del embalse

    Returns:
        dict: Variables auxiliares creadas (deltas)
    """
    f_i, f_j = filtr_arc

    # Filtrar metadatos y obtener segmentos numéricos
    numeric_segments = {k: v for k, v in segments.items() if isinstance(k, int)}
    seg_ids = list(numeric_segments.keys())

    # Igualar arco de filtración con variable
    for t in time_periods:
        model.addConstr(
            model._y[f_i, f_j, t] == Filtr_vars[t],
            name=f"R5a_filtr_arc_{t}"
        )

    # Variables binarias δ_{k,t} para selección de segmento
    delta = model.addVars(
        seg_ids, time_periods,
        vtype=GRB.BINARY,
        name="delta_pwl_seg"
    )

    # CRITICAL: Update model to commit variables
    model.update()

    for t in time_periods:
        # Un único segmento activo por período
        model.addConstr(
            sum(delta[k, t] for k in seg_ids) == 1,
            name=f"R5b_one_seg_{t}"
        )

        Vprev = Vprev_vars[t]

        # Restricciones por segmento PWL
        for k in seg_ids:
            seg = numeric_segments[k]
            vmin, vmax = seg["v_min"], seg["v_max"]
            slope, b = seg["slope"], seg["intercept"]

            # Volumen debe estar en el rango del segmento cuando δ_k=1
            model.addConstr(
                Vprev >= vmin * delta[k, t],
                name=f"R5c_vol_lb_{k}_{t}"
            )
            model.addConstr(
                Vprev <= vmax * delta[k, t] + v_max * (1 - delta[k, t]),
                name=f"R5d_vol_ub_{k}_{t}"
            )

            # Filtración = función lineal del segmento cuando δ_k=1
            model.addConstr(
                Filtr_vars[t] >= slope * Vprev + b - bigM * (1 - delta[k, t]),
                name=f"R5e_filtr_lb_{k}_{t}"
            )
            model.addConstr(
                Filtr_vars[t] <= slope * Vprev + b + bigM * (1 - delta[k, t]),
                name=f"R5f_filtr_ub_{k}_{t}"
            )

    return {"delta_pwl": delta, "segments_used": numeric_segments}


# =============================
# MODELO
# =============================
def build_model_for_one_year(
    target_year: int,
    V0: Optional[float] = None,
    I_arc_override: Optional[dict] = None,
) -> gp.Model:
    """
    Construye el modelo de optimización del Embalse para un año específico.

    Args:
        target_year: Año objetivo para la optimización
        V0: Volumen inicial opcional (Hm3). Si None, usa V_0 por defecto
        I_arc_override: Diccionario opcional para sobreescribir inyecciones

    Returns:
        gp.Model: Modelo de Gurobi configurado y listo para optimizar
    """

    # 1) Datos iniciales
    eta, cap_max, _ = load_caudalmax(CAUDALMAX_CSV)
    # permitir sobreescribir inyecciones (útil para Monte Carlo)
    if I_arc_override is None:
        I_arc = load_injections_for_year(INJ_CSV, target_year)
    else:
        I_arc = I_arc_override
    V0_eff = V_0 if V0 is None else V0

    # Helpers de balance
    def sum_in(n: str, t: int):
        return gp.quicksum(y[i, n, t] for i in IN[n])

    def sum_out(n: str, t: int):
        return gp.quicksum(y[n, j, t] for j in OUT[n])

    A_ext = {(n, t): 0.0 for n in NODES for t in T}
    for (i, j) in A_inyeccion:
        for t in T:
            A_ext[(i, t)] = (
                I_arc[(i, j, t)]
            )  # fuente externa en el nodo i = afluente_*

    # Aportes naturales para déficit (labels de inyección)
    inj_label = {
        (i, j): i.replace("afluente_", "").lower()
        for (i, j) in A_inyeccion
    }
    excluir_lbls_tucapel = {"laja_i", "abanico", "eltoro"}

    def A_ab_t(t: int) -> float:
        # afluente hacia Abanico (arco afluente_Abanico -> control_Abanico)
        # CORRECCIÓN: Convertir a Hm³/mes para consistencia de unidades
        for (i, j) in A_inyeccion:
            if inj_label[(i, j)] == "abanico":
                return I_arc[(i, j, t)] * Conv  # Hm³/mes
        return 0.0

    def A_nat_tu_t(t: int) -> float:
        # suma de afluentes "naturales" salvo {laja_i, abanico, eltoro}
        # CORRECCIÓN: Convertir a Hm³/mes para consistencia de unidades
        return sum(I_arc[(i, j, t)] * Conv for (i, j) in A_inyeccion
                   if inj_label[(i, j)] not in excluir_lbls_tucapel)  # Hm³/mes

    # 2) Modelo
    m = gp.Model(f"embalse_laja_{target_year}")

    # 3) Variables
    y = m.addVars(ARCS, T, lb=0.0, name="y")
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")
    Filtr = m.addVars(T, lb=0.0, name="Filtr")
    G = m.addVars(T, lb=0.0, name="G")

    # Déficits y binarias (primeros regantes)
    DefAb = m.addVars(T, lb=0.0, name="DeficitAbanico")
    DefTu = m.addVars(T, lb=0.0, name="DeficitTucapel")
    dAb = m.addVars(T, vtype=GRB.BINARY, name="deltaAb")
    dTu = m.addVars(T, vtype=GRB.BINARY, name="deltaTu")

    # "Pseudo-variable" para V0 y selección de colchón z[c]
    Vinit = m.addVar(lb=0.0, name="Vinit")
    m.addConstr(Vinit == V0_eff, name="link_Vinit")

    # 4) Restricciones

    # (R0) Inyección fija en A_inyeccion: y = I_arc
    for (i, j) in A_inyeccion:
        for t in T:
            m.addConstr(
                y[i, j, t] == I_arc[(i, j, t)],
                name=f"R0_inj_{i}_{j}_{t}"
            )

    # (R1) Balance hídrico del embalse
    for i, t in enumerate(T):
        if i == 0:  # Primer mes del período hidrológico (Diciembre)
            m.addConstr(
                V[t] == Vinit
                + (sum_in("Embalse", t) - sum_out("Embalse", t)) * Conv,
                name=f"R1_bal_emb_{t}"
            )
        else:
            prev_t = T[i-1]  # Mes anterior en secuencia hidrológica
            m.addConstr(
                V[t] == V[prev_t]
                + (sum_in("Embalse", t) - sum_out("Embalse", t)) * Conv,
                name=f"R1_bal_emb_{t}"
            )

    # (R2) Conservación de flujo en nodos (excepto sumideros/almacenamiento)
    SKIP_BALANCE = {"Embalse", "NodoMar", "SaltosLaja"}
    for n in NODES:
        if n in SKIP_BALANCE:
            continue
        for t in T:
            m.addConstr(
                sum_in(n, t) + A_ext[(n, t)] == sum_out(n, t),
                name=f"R2_bal_nodo_{n}_{t}"
            )

    # (R5) Filtraciones: PWL final ultra-precisa con 4 segmentos binarios

    # Asignar variables al modelo antes de llamar add_pwl_final_binary
    m._y = y

    # Generar segmentos PWL con parámetros del modelo
    segments = build_pwl_final_segments(V_max=V_max)

    # Preparar variables de volumen previo por período
    Vprev_vars = {}
    for idx, t in enumerate(T):
        if idx == 0:  # Primer período (Diciembre)
            Vprev_vars[t] = Vinit
        else:
            prev_t = T[idx-1]  # Período anterior en secuencia hidrológica
            Vprev_vars[t] = V[prev_t]

    # Agregar restricciones PWL con 4 segmentos y variables binarias
    pwl_vars = add_pwl_filtration_constraints(
        model=m,
        Filtr_vars=Filtr,
        Vprev_vars=Vprev_vars,
        time_periods=T,
        filtr_arc=FILTR_ARC,
        segments=segments,
        bigM=M,
        v_max=V_max
    )

    # (R6) Déficits (MILP) linealizadas y cobertura por El Toro
    # Se calculan dos tipos de déficits independientes:
    # 1) Déficits de primeros regantes (90 m³/s en Tucapel, 47 m³/s en Abanico)
    for t in T:
        # Factores estacionales para el mes t
        first_factor = FIRST_REGANTES_FACTOR.get(t, 1.0)

        # PRIMEROS REGANTES
        # Abanico: DefAb_t = max{0, 47*factor1_t - Filtr_t - A_abanico_t}
        # Convertir demandas a Hm³/mes para consistencia de unidades
        demanda_abanico = ABANICO_MIN * first_factor * Conv  # Hm³/mes
        expr_ab = demanda_abanico - Filtr[t] - A_ab_t(t)
        m.addConstr(DefAb[t] >= expr_ab - M * (1 - dAb[t]), name=f"DAb_lb_{t}")
        m.addConstr(
            DefAb[t] <= expr_ab + M * (1 - dAb[t]), name=f"DAb_ub1_{t}"
            )
        m.addConstr(DefAb[t] <= M * dAb[t], name=f"DAb_ub2_{t}")

        # Tucapel: DefTu_t = max{0, 90*factor1_t - Filtr_t - A_naturales_t}
        # Convertir demandas a Hm³/mes para consistencia de unidades
        demanda_tucapel = TUCAPEL_MIN * first_factor * Conv  # Hm³/mes
        expr_tu = demanda_tucapel - Filtr[t] - A_nat_tu_t(t)
        m.addConstr(DefTu[t] >= expr_tu - M * (1 - dTu[t]), name=f"DTu_lb_{t}")
        m.addConstr(
            DefTu[t] <= expr_tu + M * (1 - dTu[t]), name=f"DTu_ub1_{t}"
            )
        m.addConstr(DefTu[t] <= M * dTu[t], name=f"DTu_ub2_{t}")

        # Cobertura desde Embalse via El Toro (suma de déficits)
        # Q_extraccion_El_Toro >= Q_deficit_1os
        m.addConstr(
            y["Embalse", "ElToro", t] >= DefAb[t] + DefTu[t],
            name=f"D_cover_by_ElToro_{t}"
        )

    # # (R8) Mínimo ecológico en Saltos del Laja
    # for t in T:
    #     m.addConstr(
    #         gp.quicksum(y[i, "SaltosLaja", t] for i in IN["SaltosLaja"])
    #         >= SALTOS_MIN_T[t],
    #         name=f"R8_saltos_min_{t}"
    #     )

    # 5) FO: Mín déficit total
    m.setObjective(gp.quicksum(DefAb[t] + DefTu[t] for t in T), GRB.MINIMIZE)

    # Adjuntar variables y metadatos al modelo para postprocesamiento
    m._y = y
    m._V = V
    m._Filtr = Filtr
    m._G = G
    m._meta = {
        "eta": eta,
        "Conv": Conv,
        "ARCS": ARCS
    }

    # Exponer variables de déficit para postprocesamiento
    m._Def = {
        "DefAb": DefAb,
        "DefTu": DefTu,
    }

    # Indicar que en este modo la generación no se contabiliza como 'uso de agua'
    # (FO está orientada a minimizar déficits). KPIs deben respetar esto.
    m._meta['count_generation_usage'] = False

    return m


# =============================
# INTERFAZ PRINCIPAL SENCILLA
# =============================
if __name__ == "__main__":
    """
    Interfaz sencilla para ejecutar el modelo determinístico.
    Uso: python src/model.py
    """

    def print_simple_menu():
        print("=" * 60)
        print("  🌊 MODELO EMBALSE DEL LAJA - Ejecución Directa")
        print("=" * 60)
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
        print(f"📊 Datos disponibles: {min_year} - {max_year}")
        print("📅 Período hidrológico: Diciembre → Noviembre")
        print("    (fin temporada 30-Nov)")
        print("\n🎯 Opciones:")
        print("1️⃣  Año/Rango específico (ej: '1985' o '1980-1990')")
        print("2️⃣  Todos los años disponibles (1960-2023)")
        print("0️⃣  Salir")
        print("-" * 64)

    def get_input(prompt, default=None, input_type=str):
        while True:
            try:
                if default is not None:
                    value = input(f"{prompt} [{default}]: ").strip()
                    if not value:
                        return default
                else:
                    value = input(f"{prompt}: ").strip()

                if input_type == int:
                    return int(value)
                elif input_type == float:
                    return float(value)
                return value
            except (ValueError, KeyboardInterrupt):
                if input_type == int:
                    print("❌ Ingresa un número entero válido")
                elif input_type == float:
                    print("❌ Ingresa un número decimal válido")
                else:
                    print("❌ Entrada inválida")

    def parse_years_input(years_str):
        """
        Parsea entrada de años: '1985' o '1980-1990'
        Retorna lista de años válidos
        """
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)

        try:
            if '-' in years_str:
                # Formato de rango: "1980-1990"
                parts = years_str.split('-')
                if len(parts) != 2:
                    raise ValueError("Formato de rango inválido")

                start_year = int(parts[0].strip())
                end_year = int(parts[1].strip())

                if start_year > end_year:
                    start_year, end_year = end_year, start_year  # Intercambiar

                # Validar rango
                if start_year < min_year or end_year > max_year:
                    raise ValueError(f"Rango fuera de límites "
                                     f"({min_year}-{max_year})")

                return list(range(start_year, end_year + 1))
            else:
                # Año único: "1985"
                year = int(years_str.strip())
                if year < min_year or year > max_year:
                    raise ValueError(f"Año fuera de rango "
                                     f"({min_year}-{max_year})")
                return [year]

        except ValueError as e:
            if "invalid literal" in str(e):
                raise ValueError("Formato inválido. Use '1985' o '1980-1990'")
            raise e

    def run_custom_range():
        """Ejecuta el modelo para un año específico o rango de años."""
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)

        print("\n📅 AÑO/RANGO ESPECÍFICO")
        print(f"📊 Datos disponibles: {min_year}-{max_year}")
        print("📅 Cada 'año' = período hidrológico Dic→Nov")
        print("    (ej: 1985 = Dic'84 a Nov'85)")
        print("💡 Ejemplos:")
        print("   • Un año: '1985' (Dic'84 → Nov'85)")
        print("   • Rango: '1980-1990' (11 períodos hidrológicos)")
        print("   • Década: '1990-1999' (10 períodos hidrológicos)")

        while True:
            try:
                years_input = get_input("Especifica año(s)")
                years = parse_years_input(years_input)
                break
            except ValueError as e:
                print(f"❌ {e}")
                continue

        V0 = get_input("💧 Volumen inicial V0 (Hm³)", default=1400.0,
                       input_type=float)

        years_count = len(years)
        if years_count == 1:
            print(f"\n🚀 Ejecutando modelo para el año {years[0]}...")
        else:
            print(f"\n🚀 Ejecutando modelo para {years_count} años "
                  f"({years[0]}-{years[-1]})...")

        print(f"💧 Volumen inicial: {V0:,.1f} Hm³")
        print("=" * 60)

        # Inicializar medición de rendimiento
        start_time = time.time()
        process = psutil.Process()

        # Ejecutar simulación
        results = []
        current_V0 = V0
        total_deficit = 0.0
        total_toro_usage = 0.0  # Total de agua por el Toro

        for i, year in enumerate(years):
            print(f"\n📅 Procesando año {year} ({i+1}/{years_count})")
            print(f"💧 V0: {current_V0:,.1f} Hm³")

            try:
                model = build_model_for_one_year(
                    target_year=year,
                    V0=current_V0
                )
                model.optimize()

                if model.status == 2:  # Óptimo
                    # La FO minimiza déficits (DefAb+DefTu sumados por meses)
                    annual_deficit = model.objVal
                    V_vars = model._V
                    final_month = max(T)  # Noviembre (mes 11)
                    v_final = V_vars[final_month].x

                    # Calcular uso del Toro (agua extraída) en Hm³
                    y_vars = model._y
                    toro_usage = sum(
                        y_vars["Embalse", "ElToro", t].x
                        for t in T
                    ) * Conv

                    print(f"✅ Déficit (FO): {annual_deficit:,.3f} Hm³ | "
                          f"V_final: {v_final:,.1f} Hm³ | "
                          f"Uso Toro: {toro_usage:,.1f} Hm³")

                    total_deficit += annual_deficit
                    total_toro_usage += toro_usage
                    current_V0 = v_final  # Recursivo para siguiente año
                    results.append({
                        'year': year, 'deficit': annual_deficit, 'v_final': v_final,
                        'toro_usage': toro_usage, 'status': 'OK'
                    })
                else:
                    print("❌ No factible - usando V0 de seguridad (1400 Hm³)")
                    current_V0 = 1400.0  # Reset a volumen seguro
                    results.append({
                        'year': year, 'deficit': 0.0, 'v_final': None,
                        'toro_usage': 0.0, 'status': 'FAIL'
                    })

                model.dispose()

            except Exception as e:
                print(f"❌ Error en año {year}: {e}")
                results.append({
                    'year': year, 'deficit': 0.0, 'v_final': None,
                    'toro_usage': 0.0, 'status': 'ERROR'
                })

        # Resumen mejorado
        print("\n" + "=" * 60)
        print("📋 RESUMEN DETALLADO")
        print("=" * 60)

        successful = [r for r in results if r['status'] == 'OK']
        success_rate = len(successful) / years_count * 100

        print(f"🎯 Años procesados: {years_count}")
        print(f"✅ Años exitosos: {len(successful)} ({success_rate:.1f}%)")
        print(f"🌊 Uso total El Toro: {total_toro_usage:,.1f} Hm³")
        print(f"📉 Déficit total (suma FO): {total_deficit:,.3f} Hm³")

        if successful:
            avg_deficit = total_deficit / len(successful)
            avg_toro = total_toro_usage / len(successful)
            print(f"📊 Déficit promedio (FO): {avg_deficit:,.3f} Hm³/año")
            print(f"📊 Uso promedio El Toro: {avg_toro:,.1f} Hm³/año")

            # Estadísticas adicionales
            v_initial = V0
            v_final_last = successful[-1]['v_final'] if successful else V0
            volume_change = v_final_last - v_initial
            change_sign = "📈" if volume_change >= 0 else "📉"

            print("\n💧 BALANCE DE VOLUMEN:")
            print(f"   Inicial: {v_initial:,.1f} Hm³")
            print(f"   Final: {v_final_last:,.1f} Hm³")
            print(f"   {change_sign} Cambio: {volume_change:+,.1f} Hm³")

            # KPIs DETALLADOS usando modelos re-ejecutados
            print("\n🔄 Calculando KPIs detallados...")
            kpis_list = []
            for result in successful:
                year = result['year']
                try:
                    # Re-ejecutar modelo para KPIs detallados
                    model = build_model_for_one_year(target_year=year, V0=V0)
                    model.Params.OutputFlag = 0
                    model.optimize()

                    if model.status == 2:
                        kpis = extract_kpis(model)
                        # Ajuste de reporte: ocultar/consolidar uso de generación
                        # (no modificar kpi.py). Ponemos el uso de generación a 0
                        # para que KPI 2 muestre solo riego si así lo deseas.
                        try:
                            if isinstance(kpis, dict):
                                up = kpis.get('uso_presupuestos_%')
                                if isinstance(up, dict) and 'generacion' in up:
                                    up['generacion'] = 0.0
                        except Exception:
                            pass

                        kpis_list.append(kpis)

                        # Mostrar KPIs para primer año como ejemplo
                        if len(kpis_list) == 1:
                            print_kpis(kpis, f"Año {year}")

                    model.dispose()
                except Exception as e:
                    print(f"   ⚠️ Error calculando KPIs para {year}: {e}")

            # KPIs agregados para múltiples años
            if len(kpis_list) > 1:
                print(f"\n KPIs AGREGADOS ({len(kpis_list)} años exitosos):")
                print("=" * 60)

                # Promediar cotas por mes
                from collections import defaultdict
                cota_sums = defaultdict(float)
                cota_counts = defaultdict(int)

                deficit_maxs = []
                deficit_proms = []
                confiabilidades = []

                for kpis in kpis_list:
                    # Cotas mensuales
                    for mes, cota in kpis.get("cota_mensual", {}).items():
                        cota_sums[mes] += cota
                        cota_counts[mes] += 1

                    # Déficits
                    deficit_maxs.append(kpis.get("deficit_max_m3s", 0.0))
                    deficit_proms.append(kpis.get("deficit_prom_m3s", 0.0))
                    confiabilidades.append(kpis.get("confiabilidad_%", 100.0))

                # Cota promedio agregada
                cota_prom_agregada = {
                    mes: cota_sums[mes] / cota_counts[mes]
                    for mes in cota_sums.keys()
                }
                avg_cota_total = (
                    sum(cota_prom_agregada.values()) / len(cota_prom_agregada)
                    if cota_prom_agregada else 0
                )

                print("📏 TRAYECTORIA PROMEDIO AGREGADA:")
                print(f" Cota promedio multi-año: {avg_cota_total:6.1f} msnm")

                # Déficits agregados
                if deficit_maxs:
                    deficit_max_prom = sum(deficit_maxs) / len(deficit_maxs)
                    deficit_max_worst = max(deficit_maxs)
                    deficit_prom_prom = sum(deficit_proms) / len(deficit_proms)
                    confiabilidad_prom = (
                        sum(confiabilidades) / len(confiabilidades)
                    )

                    print("\n🚱 DÉFICITS AGREGADOS:")
                    print(
                        (
                            f"   Déficit máximo promedio: "
                            f"{deficit_max_prom:8.2f} m³/s"
                        )
                    )
                    print(
                        f"   Déficit máximo peor año: "
                        f"{deficit_max_worst:8.2f} m³/s"
                    )
                    print(f"   Déficit promedio: "
                          f"{deficit_prom_prom:8.2f} m³/s")
                    print(
                        (
                            (
                                f"   Confiabilidad promedio: "
                                f"{confiabilidad_prom:8.1f}%"
                            )
                        )
                    )

                # Exportar a CSV con timestamp para evitar sobreescritura
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    export_files = export_kpis_to_csv(
                        {"cota_mensual": cota_prom_agregada,
                         "deficit_max_m3s": deficit_max_prom,
                         "deficit_prom_m3s": deficit_prom_prom,
                         "confiabilidad_%": confiabilidad_prom},
                        prefix=f"agregados_{years[0]}-{years[-1]}",
                        suffix=timestamp
                    )
                    print(
                        f"\n📁 Resultados exportados a: "
                        f"{len(export_files)} archivos CSV"
                    )
                except Exception as e:
                    print(f"   ⚠️ Error exportando: {e}")

        # Tabla detallada si hay múltiples años
        if years_count > 1:
            print("\n📊 DETALLE POR AÑO:")
            print("━" * 80)
            print("Año   Estado  Déficit (Hm³)  V_final (Hm³)  Uso Toro (Hm³)")
            print("━" * 80)

            for r in results:
                status_icon = "✅" if r['status'] == 'OK' else "❌"
                if r['status'] == 'OK':
                    print(
                        f"{r['year']}   {status_icon}    {r['deficit']:>12,.3f}"
                        f"{r['v_final']:>12,.1f}      {r['toro_usage']:>8,.1f}"
                    )
                else:
                    print(
                        f"{r['year']}   {status_icon}       ---          ---"
                        "          ---"
                    )
            print("━" * 80)

        # Imprimir estadísticas de rendimiento
        performance_stats = get_performance_stats(start_time, process)
        context = f"({years_count} años)" if years_count > 1 else f"(año {years[0]})"
        print_performance_stats(performance_stats, context)

    def run_all_years():
        """Ejecuta el modelo para todos los años disponibles."""
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
        total_years = max_year - min_year + 1

        print("\n🚀 SIMULACIÓN COMPLETA")
        print(f"📊 Período: {min_year}-{max_year} ({total_years} períodos)")
        print("📅 Cada período: Diciembre → Noviembre (fin temporada 30-Nov)")

        confirm_msg = f"¿Confirmas ejecutar {total_years} años? [s/N]"
        confirm = get_input(confirm_msg, default="N")
        if confirm.lower() not in ['s', 'sí', 'si', 'y', 'yes']:
            print("❌ Operación cancelada")
            return

        V0 = get_input("💧 Volumen inicial V0 (Hm³)", default=1400.0,
                       input_type=float)

        print("\n🚀 Iniciando simulación completa...")
        print("=" * 60)

        # Inicializar medición de rendimiento
        start_time = time.time()
        process = psutil.Process()

        results = []
        current_V0 = V0
        total_deficit = 0.0
        total_toro_usage = 0.0

        for year in range(min_year, max_year + 1):
            year_num = year - min_year + 1
            print(f"\n📅 Año {year} ({year_num}/{total_years})")
            print(f"💧 V0: {current_V0:,.1f} Hm³")

            try:
                model = build_model_for_one_year(
                    target_year=year,
                    V0=current_V0
                )
                model.optimize()

                if model.status == 2:  # Óptimo
                    annual_deficit = model.objVal
                    V_vars = model._V
                    final_month = max(T)  # Noviembre (mes 11)
                    v_final = V_vars[final_month].x

                    # Calcular uso del Toro
                    y_vars = model._y
                    toro_usage = sum(
                        y_vars["Embalse", "ElToro", t].x
                        for t in T
                    ) * Conv

                    print(f"✅ Déficit (FO): {annual_deficit:,.3f} Hm³ | "
                          f"V_f: {v_final:,.0f} | "
                          f"Toro: {toro_usage:,.1f} Hm³")

                    total_deficit += annual_deficit
                    total_toro_usage += toro_usage
                    current_V0 = v_final  # Recursivo
                    results.append({
                        'year': year, 'deficit': annual_deficit, 'v_final': v_final,
                        'toro_usage': toro_usage, 'status': 'OK'
                    })
                else:
                    print("❌ No factible - reset a 1400 Hm³")
                    current_V0 = 1400.0
                    results.append({
                        'year': year, 'deficit': 0.0, 'v_final': None,
                        'toro_usage': 0.0, 'status': 'FAIL'
                    })

                model.dispose()

            except Exception as e:
                print(f"❌ Error: {e}")
                results.append({
                    'year': year, 'deficit': 0.0, 'v_final': None,
                    'toro_usage': 0.0, 'status': 'ERROR'
                })

        # Cálculos adicionales para análisis
        all_volumes = []
        total_toro_usage_hm3 = []  # Para déficits
        successful = [r for r in results if r['status'] == 'OK']

        # Usar datos ya disponibles de los resultados exitosos
        for result in successful:
            # Aproximación: usar volumen final como representativo del año
            if result['v_final'] is not None:
                all_volumes.append(result['v_final'])
            # Uso del Toro como proxy de déficits (ya está en Hm³)
            total_toro_usage_hm3.append(result['toro_usage'])

        # Resumen completo
        print("\n" + "=" * 60)
        print("📋 RESUMEN SIMULACIÓN COMPLETA (1960-2023)")
        print("=" * 60)

        successful = [r for r in results if r['status'] == 'OK']
        success_rate = len(successful) / total_years * 100

        print(f"🎯 Años procesados: {total_years}")
        print(f"✅ Años exitosos: {len(successful)} ({success_rate:.1f}%)")
        print(f"🌊 Uso total El Toro: {total_toro_usage:,.1f} Hm³")

        if successful:
            avg_deficit = total_deficit / len(successful)
            avg_toro = total_toro_usage / len(successful)
            print(f"📊 Déficit promedio (FO): {avg_deficit:,.3f} Hm³/año")
            print(f"📊 Uso promedio El Toro: {avg_toro:,.1f} Hm³/año")

            # Balance volumétrico histórico
            v_initial = V0
            v_final_last = successful[-1]['v_final'] if successful else V0
            volume_change = v_final_last - v_initial
            change_sign = "📈" if volume_change >= 0 else "📉"

            print("\n💧 BALANCE VOLUMÉTRICO HISTÓRICO:")
            print(f"   Inicial (Dic'59): {v_initial:,.1f} Hm³")
            print(f"   Final (Nov'23): {v_final_last:,.1f} Hm³")
            print(f"   {change_sign} Cambio neto: {volume_change:+,.1f} Hm³")

            # KPIs DETALLADOS HISTÓRICOS (1960-2023)
            print("\n🔄 Calculando KPIs históricos detallados...")
            print("   (Esto puede tomar varios minutos)")

            kpis_historicos = []

            # Procesar TODOS los años para análisis completo
            all_years = list(range(min_year, max_year + 1))

            current_V0_sample = V0
            for year in all_years:
                try:
                    model = build_model_for_one_year(
                        target_year=year,
                        V0=current_V0_sample
                    )
                    model.Params.OutputFlag = 0
                    model.optimize()

                    if model.status == 2:
                        kpis = extract_kpis(model)
                        try:
                            if isinstance(kpis, dict):
                                up = kpis.get('uso_presupuestos_%')
                                if isinstance(up, dict) and 'generacion' in up:
                                    up['generacion'] = 0.0
                        except Exception:
                            pass
                        kpis_historicos.append(kpis)

                        # Actualizar V0 para siguiente muestra
                        if hasattr(model, '_V'):
                            final_month = max(T)
                            current_V0_sample = model._V[final_month].x

                    model.dispose()
                except Exception:
                    current_V0_sample = 1400.0  # Reset en caso de error

            # Análisis agregado con KPIs estratégicos históricos
            if kpis_historicos:
                # Calcular KPIs estratégicos agregados
                kpis_agregados = aggregate_kpis(kpis_historicos)

                # Mostrar los 4 KPIs estratégicos históricos
                print_kpis(kpis_agregados, "Histórico")

                # Exportar resultados históricos con timestamp
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    export_files = export_kpis_to_csv(
                        kpis_agregados,
                        prefix="historicos_1960-2023",
                        suffix=timestamp
                    )
                    print(
                        f"\n📁 KPIs históricos exportados: "
                        f"{len(export_files)} archivos CSV"
                    )
                except Exception as e:
                    print(f"   ⚠️ Error exportando históricos: {e}")

                # Generar gráficos históricos con timestamp
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    plot_files = generate_historical_plots(
                        kpis_historicos,
                        all_years,
                        output_dir="resultados",
                        suffix=timestamp
                    )
                    print(
                        f"📊 Gráficos generados: {len(plot_files)} archivos PNG"
                    )
                except Exception as e:
                    print(f"   ⚠️ Error generando gráficos: {e}")
            else:
                print(
                    "\n⚠️ No se pudieron calcular KPIs históricos detallados"
                )

        # Imprimir estadísticas de rendimiento
        performance_stats = get_performance_stats(start_time, process)
        print_performance_stats(performance_stats, "(simulación completa)")

    # Bucle principal
    while True:
        try:
            print_simple_menu()

            choice = get_input("\nSelecciona una opción", input_type=int)

            if choice == 0:
                print("👋 ¡Hasta luego!")
                break
            elif choice == 1:
                run_custom_range()
            elif choice == 2:
                run_all_years()
            else:
                print("❌ Opción inválida. Selecciona 0, 1 o 2.")

            # Pausa antes de volver al menú
            input("\n⏸️  Presiona Enter para continuar...")
            print("\n")

        except KeyboardInterrupt:
            print("\n\n👋 Saliendo del programa...")
            break
        except Exception as e:
            print(f"❌ Error inesperado: {e}")

    sys.exit(0)
