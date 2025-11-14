from typing import Tuple, Optional
import os
import gurobipy as gp
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import NODES, ARCS, A_inyeccion, A_generacion, IN, OUT
# --- Datos (CSV) ---
from data_loader import load_caudalmax, load_injections_for_year
# --- Filtraciones y cotas ---
from filt_cota import (
    build_pwl_final_segments,
    add_pwl_filtration_constraints
)

# =============================
# CONFIGURACIÓN (parámetros)
# =============================
# Detectar rutas relativas
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
SALTOS_MIN = 7.0       # m3/s

# Curvas estacionales para 1°, 2° regantes y caudal ecologico (por mes 1..12)
# Tomadas de la Tabla N°2 (imagen). Valores entre 0 y 1
# NOTA: Los factores siguen siendo por mes calendario (1=Ene, 12=Dic)
FIRST_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 1.00, 10: 1.00, 11: 1.00, 12: 1.00
}
SECOND_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 0.80, 4: 0.50,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 0.30, 10: 0.65, 11: 0.85, 12: 1.00
}
SALTOS_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 0.00, 4: 0.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 0.00, 10: 0.00, 11: 0.00, 12: 0.50
}
# Base para cálculo de déficit de 2dos regantes (según enunciado: 53 m3/s)
SECOND_REGANTES_BASE = 53.0

# Big-M y conversión
M = 6000                        # Big-M
EPS = 1e-3                      # epsilon para desambiguar límites
Conv = (86400 * 30) / 1e6       # m^3/s x mes -> Hm3

# Volúmenes embalse (Hm3) - Basado en ANEXO N°1
V_0 = 1400.0  # Volumen inicial por defecto
V_min = 0.0     # Volumen mínimo
V_max = 5582.0  # Volumen máximo

# --- Colchones según configuración definitiva operacional ---
# (ANEXO 1 Convenio) Riego puede ser valor fijo en Hm³ o porcentaje
# Generación y Lago en %
COLCHONES = {
    # R=600 Hm³, G=5%, L=0%
    "Inferior": {"lo": 0.0, "hi": 1200.0, "shares": (600.0, 0.05, 0.0)},
    # R=40%, G=5%, L=55%
    "Transicion": {"lo": 1200.0, "hi": 1370.0, "shares": (0.40, 0.05, 0.55)},
    # R=40%, G=40%, L=20%
    "Intermedio": {"lo": 1370.0, "hi": 1900.0, "shares": (0.40, 0.40, 0.20)},
    # R=25%, G=65%, L=10%
    "Superior":   {"lo": 1900.0, "hi": 5582.0, "shares": (0.25, 0.65, 0.10)},
}
C_LABELS = list(COLCHONES.keys())

# Configuración de filtraciones del embalse El Toro
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")


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
        return gp.quicksum(y[i, n, t] for i in IN[n]) \
             + gp.quicksum(x[i, n, t] for i in IN[n] if (i, n) in A_generacion)

    def sum_out(n: str, t: int):
        return gp.quicksum(y[n, j, t] for j in OUT[n]) \
             + gp.quicksum(
                 x[n, j, t] for j in OUT[n] if (n, j) in A_generacion
             )
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
    x = m.addVars(A_generacion, T, lb=0.0, name="x")
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")
    Filtr = m.addVars(T, lb=0.0, name="Filtr")
    G = m.addVars(T, lb=0.0, name="G")

    # Déficits y binarias (primeros regantes)
    # Tucapel: max{0, 90*factor1_t - Filtr_t - A_naturales_t}
    # Abanico: max{0, 47*factor1_t - Filtr_t - A_abanico_t}
    DefAb = m.addVars(T, lb=0.0, name="DeficitAbanico")
    DefTu = m.addVars(T, lb=0.0, name="DeficitTucapel")
    dAb = m.addVars(T, vtype=GRB.BINARY, name="deltaAb")
    dTu = m.addVars(T, vtype=GRB.BINARY, name="deltaTu")

    # Déficit consolidado primeros regantes: min{DefTu, DefAb}
    # Déficit que El Toro debe compensar
    Def1 = m.addVars(T, lb=0.0, name="Deficit1erosRegantes")
    dMin = m.addVars(T, vtype=GRB.BINARY, name="deltaMin")

    # Excedente de primeros regantes y su binaria
    # Exc1_t = max{0, (Filtr_t + A_naturales_t) - 90*factor1_t}
    Exc1 = m.addVars(T, lb=0.0, name="ExcedentePrimeros")
    dExc1 = m.addVars(T, vtype=GRB.BINARY, name="deltaExc1")

    # Déficit y binaria para los segundos regantes
    # Def2_t = max{0, SECOND_REGANTES_BASE*factor2_t - Excedente_1os}
    Def2 = m.addVars(T, lb=0.0, name="Deficit2dosRegantes")
    d2 = m.addVars(T, vtype=GRB.BINARY, name="delta2")

    # "Pseudo-variable" para V0 y selección de colchón z[c]
    Vinit = m.addVar(lb=0.0, name="Vinit")
    m.addConstr(Vinit == V0_eff, name="link_Vinit")

    z = m.addVars(C_LABELS, vtype=GRB.BINARY, name="z")
    m.addConstr(gp.quicksum(z[c] for c in C_LABELS) == 1, name="C_sum_z")

    # Selección por rangos con Big-M: lo_c + EPS <= Vinit <= hi_c si z[c]=1
    for c in C_LABELS:
        lo = COLCHONES[c]["lo"]
        hi = COLCHONES[c]["hi"]
        eps_lo = EPS if c != "Inferior" else 0.0   # no excluye 0 del inferior
        m.addConstr(Vinit >= (lo + eps_lo) - M * (1 - z[c]), name=f"C_{c}_lo")
        m.addConstr(Vinit <= hi + M * (1 - z[c]), name=f"C_{c}_hi")

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

    # (R3) Capacidad máxima para arcos de generación
    for (i, j) in A_generacion:
        for t in T:
            m.addConstr(y[i, j, t] == 0.0, name=f"R3_y0_gen_{i}_{j}_{t}")
            cap = cap_max.get((i, j))
            if cap is not None:
                m.addConstr(x[i, j, t] <= cap, name=f"R3_cap_{i}_{j}_{t}")

    # (R4) Energía mensual: G_t = sum{ eta_e * x_e,t }
    for t in T:
        m.addConstr(G[t] == gp.quicksum(eta.get((i, j), 0.0) * x[i, j, t]
                                        for (i, j) in A_generacion),
                    name=f"R4_energy_{t}")

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
    # 2) Déficits de segundos regantes (53 m³/s, basado en excedente de 1os)
    for t in T:
        # Factores estacionales para el mes t
        first_factor = FIRST_REGANTES_FACTOR.get(t, 1.0)
        second_factor = SECOND_REGANTES_FACTOR.get(t, 1.0)

        # PRIMEROS REGANTES
        # Tucapel: DefTu_t = max{0, 90*factor1_t - Filtr_t - A_naturales_t}
        # Convertir demandas a Hm³/mes para consistencia de unidades
        demanda_tucapel = TUCAPEL_MIN * first_factor * Conv  # Hm³/mes
        expr_tu = demanda_tucapel - Filtr[t] - A_nat_tu_t(t)
        m.addConstr(DefTu[t] >= expr_tu - M * (1 - dTu[t]), name=f"DTu_lb_{t}")
        m.addConstr(
            DefTu[t] <= expr_tu + M * (1 - dTu[t]), name=f"DTu_ub1_{t}"
            )
        m.addConstr(DefTu[t] <= M * dTu[t], name=f"DTu_ub2_{t}")

        # Abanico: DefAb_t = max{0, 47*factor1_t - Filtr_t - A_abanico_t}
        # Convertir demandas a Hm³/mes para consistencia de unidades
        demanda_abanico = ABANICO_MIN * first_factor * Conv  # Hm³/mes
        expr_ab = demanda_abanico - Filtr[t] - A_ab_t(t)
        m.addConstr(DefAb[t] >= expr_ab - M * (1 - dAb[t]), name=f"DAb_lb_{t}")
        m.addConstr(
            DefAb[t] <= expr_ab + M * (1 - dAb[t]), name=f"DAb_ub1_{t}"
            )
        m.addConstr(DefAb[t] <= M * dAb[t], name=f"DAb_ub2_{t}")

        # DÉFICIT CONSOLIDADO PRIMEROS REGANTES
        # Def1_t = min{DefTu_t, DefAb_t}
        # Osea, Def1_t debe ser menor o igual a ambos ( <= al min de los dos)
        m.addConstr(Def1[t] <= DefTu[t], name=f"D1_min_Tu_{t}")
        m.addConstr(Def1[t] <= DefAb[t], name=f"D1_min_Ab_{t}")

        # Linearización usando variable binaria dMin[t]:
        # Si dMin[t] = 1 -> DefTu <= DefAb -> Def1 = DefTu
        # Si dMin[t] = 0 -> DefAb < DefTu  -> Def1 = DefAb

        # Forzar que Def1 sea igual al menor
        m.addConstr(Def1[t] >= DefTu[t] - M * (1 - dMin[t]),
                    name=f"D1_eq_Tu_{t}")
        m.addConstr(Def1[t] >= DefAb[t] - M * dMin[t],
                    name=f"D1_eq_Ab_{t}")

        # Forzar la selección correcta de dMin (CRÍTICO para corrección)
        m.addConstr(DefTu[t] <= DefAb[t] + M * (1 - dMin[t]),
                    name=f"D1_sel_Tu_{t}")
        m.addConstr(DefAb[t] <= DefTu[t] + M * dMin[t],
                    name=f"D1_sel_Ab_{t}")

        # SEGUNDOS REGANTES (medido en Tucapel):
        # Paso 1: Calcular excedente de primeros regantes
        # Exc1_t = max{0, (Filtr_t + A_naturales_t) - 90*factor1_t}
        caudal_disponible_1os = Filtr[t] + A_nat_tu_t(t)
        expr_exc1 = caudal_disponible_1os - demanda_tucapel

        # Linearización del excedente con variable binaria dExc1[t]
        m.addConstr(Exc1[t] >= expr_exc1 - M * (1 - dExc1[t]),
                    name=f"Exc1_lb_{t}")
        m.addConstr(Exc1[t] <= expr_exc1 + M * (1 - dExc1[t]),
                    name=f"Exc1_ub1_{t}")
        m.addConstr(Exc1[t] <= M * dExc1[t], name=f"Exc1_ub2_{t}")

        # Paso 2: Calcular déficit de segundos regantes
        # Def2_t = max{0, 53*factor2_t - Exc1_t}
        # Convertir demandas a Hm³/mes para consistencia
        demanda_2dos = SECOND_REGANTES_BASE * second_factor * Conv  # Hm³/mes
        expr_2 = demanda_2dos - Exc1[t]

        # Linearización Big-M estándar para max{0, expr_2}
        # La formulación del informe (R6.3a-d) debe interpretarse como:
        # - Cuando d2=1: Def2 = expr_2 (si expr_2 > 0)
        # - Cuando d2=0: Def2 = 0 (si expr_2 <= 0)
        m.addConstr(Def2[t] >= expr_2 - M * (1 - d2[t]),
                    name=f"D2_lb_{t}")  # (R6.3a modificada)
        m.addConstr(Def2[t] <= expr_2 + M * (1 - d2[t]),
                    name=f"D2_ub1_{t}")  # (R6.3b)
        m.addConstr(Def2[t] <= M * d2[t], name=f"D2_ub2_{t}")  # (R6.3c)

        # Cobertura desde Embalse via El Toro
        # Q_extraccion_El_Toro >= Def1_t (déficit 1os) + Def2_t (déficit 2dos)
        m.addConstr(
            x["Embalse", "ElToro", t] >= Def1[t] + Def2[t],
            name=f"D_cover_by_ElToro_{t}"
        )

    # (R7) Presupuestos por colchón basados en volumen inicial
    # Variables auxiliares para linearización McCormick
    vinit_share = m.addVars(C_LABELS, lb=0.0, ub=V_max, name="vinit_share")

    for c in C_LABELS:
        # Linearización McCormick para vinit_share[c] = z[c] * Vinit
        m.addConstr(vinit_share[c] <= V_max * z[c],
                    name=f"R7a_McCormick1_{c}")
        m.addConstr(vinit_share[c] >= 0, name=f"R7b_McCormick2_{c}")
        m.addConstr(vinit_share[c] <= Vinit, name=f"R7c_McCormick3_{c}")
        m.addConstr(vinit_share[c] >= Vinit - V_max * (1 - z[c]),
                    name=f"R7d_McCormick4_{c}")

    # Cálculo de uso anual por categoría (Hm3) - CORREGIDO PARA USO DUAL

    # Calcular total de agua por El Toro (convertir a Hm³/año)
    sum_eltoro_total_Hm3 = gp.quicksum(
        x["Embalse", "ElToro", t] for t in T
    ) * Conv

    # RIEGO: Solo la cobertura de déficits desde El Toro
    # (uso exclusivo para riego = agua destinada a cubrir déficits)
    # Def1 = min{DefTu, DefAb} (déficit consolidado primeros regantes)
    # Def2 = déficit segundos regantes
    sum_riego_Hm3 = gp.quicksum(
        (Def1[t] + Def2[t]) for t in T
    )  # Ya está en Hm³/mes, suma anual

    # GENERACIÓN: Solo el excedente de El Toro que NO cubre déficits
    # (cualquier agua extra por El Toro será para generación)
    sum_gen_Hm3 = sum_eltoro_total_Hm3 - sum_riego_Hm3

    # Cálculo de presupuestos por colchón
    budget_terms = {"riego": [], "generacion": [], "lago": []}

    for c in C_LABELS:
        r_share, g_share, l_share = COLCHONES[c]["shares"]

        # Para cada categoría: valor fijo (>1.0) o porcentaje (<=1.0)
        categories = [("riego", r_share), ("generacion", g_share),
                      ("lago", l_share)]
        for category, share in categories:
            if share > 1.0:  # Valor fijo en Hm³
                budget_terms[category].append(share * z[c])
            else:  # Porcentaje del volumen inicial
                budget_terms[category].append(share * vinit_share[c])

    # Restricciones de presupuesto anual
    budget_riego = gp.quicksum(budget_terms["riego"])
    budget_gen = gp.quicksum(budget_terms["generacion"])
    budget_lago = gp.quicksum(budget_terms["lago"])

    # RESTRICCIÓN RIEGO
    m.addConstr(sum_riego_Hm3 <= budget_riego, name="R7e_presupuesto_riego")

    # RESTRICCIÓN GENERACIÓN
    # Generación con cap de 1200 Hm³ para Colchón Superior
    # Si Superior activo (z["Superior"]=1): budget_gen limitado a 1200 Hm³
    budget_gen_capped = m.addVar(lb=0.0, name="budget_gen_capped")
    m.addConstr(budget_gen_capped <= budget_gen,
                name="R7f_gen_base")
    m.addConstr(
        budget_gen_capped <= 1200.0 * z["Superior"] + M * (1 - z["Superior"]),
        name="R7f_gen_cap_superior"
    )
    # Para otros colchones, no hay límite adicional
    m.addConstr(budget_gen_capped >= budget_gen - M * z["Superior"],
                name="R7f_gen_otros")

    m.addConstr(sum_gen_Hm3 <= budget_gen_capped,
                name="R7f_presupuesto_generacion")

    # RESTRICCIÓN LAGO
    for t in T:
        m.addConstr(V[t] >= budget_lago, name=f"R7g_volumen_lago_{t}")

    # (R8) Mínimo ecológico en Saltos del Laja (con factor estacional)
    for t in T:
        # Aplicar factor estacional al caudal mínimo base
        saltos_factor = SALTOS_REGANTES_FACTOR.get(t, 1.0)
        saltos_min_t = SALTOS_MIN * saltos_factor

        m.addConstr(
            gp.quicksum(y[i, "SaltosLaja", t] for i in IN["SaltosLaja"])
            >= saltos_min_t,
            name=f"R8_saltos_min_{t}"
        )

    # 5) FO: Max energía total
    m.setObjective(gp.quicksum(G[t] for t in T), GRB.MAXIMIZE)

    # Adjuntar variables y metadatos al modelo para postprocesamiento
    m._y = y
    m._x = x
    m._V = V
    m._Filtr = Filtr
    m._G = G
    m._meta = {
        "eta": eta,
        "Conv": Conv,
        "A_generacion": A_generacion,
        "ARCS": ARCS
    }

    return m


# =============================
# INTERFAZ PRINCIPAL
# =============================
if __name__ == "__main__":
    """
    Interfaz para ejecutar el modelo determinístico.
    Uso: python src/run_model.py
    """
    from run_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Determinístico - Embalse del Laja",
        default_v0=V_0
    )
