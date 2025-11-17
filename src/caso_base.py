from typing import Tuple, Optional
import os
import gurobipy as gp
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import NODES, ARCS, A_inyeccion, IN, OUT
# --- Datos (CSV) ---
from data_loader import load_caudalmax, load_injections_for_year
# --- Filtraciones y cotas ---
from filt_cota import (
    build_pwl_final_segments,
    add_pwl_filtration_constraints
)
# --- KPIs y UI (importados por run_model.py) ---
# from kpi import extract_kpis, aggregate_kpis, print_kpis, ...
# from ui_helpers import get_performance_stats, print_performance_stats

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
# NOTA: Funciones de rendimiento movidas a ui_helpers.py


# =============================
# FUNCIONES AUXILIARES PWL
# =============================
# NOTA: add_pwl_filtration_constraints movida a filt_cota.py
# Importar desde: from filt_cota import add_pwl_filtration_constraints


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
    add_pwl_filtration_constraints(
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

    # En este modo la generación no se contabiliza como 'uso'
    # (FO minimiza déficits). KPIs deben respetar esto.
    m._meta['count_generation_usage'] = False

    return m


# =============================
# INTERFAZ PRINCIPAL
# =============================
if __name__ == "__main__":
    """
    Interfaz para ejecutar el modelo caso base (sin reparto por colchones).
    Uso: python src/caso_base.py
    """
    from ui_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Caso Base - Sin Colchones",
        default_v0=V_0
    )
