from typing import Tuple, Optional
import os
import gurobipy as gp
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import (
    NODES, ARCS, A_inyeccion, A_conectividad,
    IN, OUT
)
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
SEGUNDOS_MIN = 53.0    # m3/s

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

# Big-M y conversión
M = 6000                        # Big-M
EPS = 1e-3                      # epsilon para desambiguar límites
Conv = (86400 * 30) / 1e6       # m^3/s x mes -> Hm3

# Volúmenes embalse (Hm3) - Basado en ANEXO N°1
V_0 = 1400.0  # Volumen inicial por defecto
V_min = 0.0     # Volumen mínimo
V_max = 5582.0  # Volumen máximo

# --- Colchones según configuración definitiva operacional ---
# (ANEXO 1 Convenio) Riego puede ser valor fijo en Hm3 o porcentaje
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
    # permitir sobreescribir inyecciones (útil para Monte Carlo)
    if I_arc_override is None:
        I_arc = load_injections_for_year(INJ_CSV, target_year)
    else:
        I_arc = I_arc_override
    V0_eff = V_0 if V0 is None else V0

    # Helpers de balance (incluyen x para El Toro)
    def sum_in(n: str, t: int):
        base = gp.quicksum(y[i, n, t] for i in IN[n])
        # Agregar x si es El Toro
        if n == "ElToro":
            base += x["Embalse", "ElToro", t]
        return base

    def sum_out(n: str, t: int):
        base = gp.quicksum(y[n, j, t] for j in OUT[n])
        # Agregar x si es Embalse
        if n == "Embalse":
            base += x["Embalse", "ElToro", t]
        return base
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

    # 3) Variables principales
    # Flujos en arcos de conectividad
    y = m.addVars(ARCS, T, lb=0.0, name="y")

    # Flujo de extracción por El Toro
    # (similar a generación pero sin producir energía)
    x = m.addVars([("Embalse", "ElToro")], T, lb=0.0, name="x")

    # Agua específica para cobertura de déficit (subconjunto de x)
    x_deficit = m.addVars(T, lb=0.0, name="x_deficit")

    # Volumen del embalse
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")

    # Filtraciones
    Filtr = m.addVars(T, lb=0.0, name="Filtr")

    # Binarias de saturación para arcos de conectividad
    # gamma[i,j,t] = 1 si y solo si y[i,j,t] está al máximo de capacidad
    gamma = m.addVars(A_conectividad, T, vtype=GRB.BINARY, name="gamma")

    # Déficits y binarias (primeros regantes)
    DefAb = m.addVars(T, lb=0.0, name="DeficitAbanico")
    ExcAb = m.addVars(T, lb=0.0, name="ExcedenteAbanico")
    dAb = m.addVars(T, vtype=GRB.BINARY, name="deltaAb")

    DefTu = m.addVars(T, lb=0.0, name="DeficitTucapel")
    ExcTu = m.addVars(T, lb=0.0, name="ExcedenteTucapel")
    dTu = m.addVars(T, vtype=GRB.BINARY, name="deltaTu")

    # Déficit consolidado primeros regantes: min{DefTu, DefAb}
    Def1 = m.addVars(T, lb=0.0, name="Deficit1erosRegantes")
    dMin = m.addVars(T, vtype=GRB.BINARY, name="deltaMin")

    # Excedente de primeros regantes (medido en tucapel)
    Exc1 = m.addVars(T, lb=0.0, name="ExcedentePrimeros")

    # Déficit segundos regantes
    Def2 = m.addVars(T, lb=0.0, name="Deficit2dosRegantes")

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

    # (R3) Capacidad máxima en arcos de conectividad

    # R3a: El Toro usa exclusivamente arco x (y=0)
    for t in T:
        m.addConstr(
            y["Embalse", "ElToro", t] == 0.0,
            name=f"R3a_y0_ElToro_{t}"
        )

    # R3c: Capacidad en conectividad con binarias gamma para saturación
    cap_max_dict = load_caudalmax(CAUDALMAX_CSV)[1]
    for (i, j) in A_conectividad:
        cap = cap_max_dict.get((i, j))
        if cap is not None and cap < 9000:
            for t in T:
                # Capacidad normal (límite superior)
                m.addConstr(y[i, j, t] <= cap, name=f"R3c_cap_{i}{j}{t}")

                # Linearización Big-M para gamma=1 <=> y=cap
                # Similar a beta pero para arcos de conectividad
                m.addConstr(
                    y[i, j, t] >= cap - M * (1 - gamma[i, j, t]),
                    name=f"R3c_gamma_lb_{i}{j}{t}"
                )
                m.addConstr(
                    y[i, j, t] <= cap + M * (1 - gamma[i, j, t]),
                    name=f"R3c_gamma_ub_{i}{j}{t}"
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

    # ------------------------------------------------------------------
    # (R6) Déficits (MILP) linealizadas y cobertura por El Toro
    # ------------------------------------------------------------------
    # Se calculan dos tipos de déficits independientes:
    # 1) Déficit de primeros regantes (90 m³/s en Tucapel, 47 m³/s en Abanico)
    # 2) Déficit de segundos regantes (53 m³/s, basado en excedente de Tucapel)
    for t in T:
        # Factores estacionales
        first_factor = FIRST_REGANTES_FACTOR.get(t, 1.0)

        # Demandas estacionales (Hm3/mes)
        demanda_abanico = ABANICO_MIN * first_factor * Conv
        demanda_tucapel = TUCAPEL_MIN * first_factor * Conv

        # ------------------------------------------------------------------
        # (R6.1) PRIMEROS REGANTES: balances y modo déficit/excedente
        # ------------------------------------------------------------------
        # Balance Abanico: Filtr + A_ab + DefAb - ExcAb = D_Abanico
        m.addConstr(
            (Filtr[t] * Conv) + A_ab_t(t) + DefAb[t] - ExcAb[t] ==
            demanda_abanico, name=f"R6_1a_balance_Ab_{t}"
        )

        # Balance Tucapel: Filtr + A_nat + DefTu - ExcTu = D_Tucapel
        m.addConstr(
            (Filtr[t] * Conv) + A_nat_tu_t(t) + DefTu[t] - ExcTu[t] ==
            demanda_tucapel, name=f"R6_1b_balance_Tu_{t}"
        )

        # Modo déficit/excedente en Abanico
        m.addConstr(DefAb[t] <= dAb[t] * M, name=f"R6_1c_DefAb_ub_{t}")
        m.addConstr(ExcAb[t] <= (1 - dAb[t]) * M, name=f"R6_1c_ExcAb_ub_{t}")

        # Modo déficit/excedente en Tucapel
        m.addConstr(DefTu[t] <= dTu[t] * M, name=f"R6_1d_DefTu_ub_{t}")
        m.addConstr(ExcTu[t] <= (1 - dTu[t]) * M, name=f"R6_1d_ExcTu_ub_{t}")

        # ------------------------------------------------------------------
        # Déficit consolidado de primeros regantes (Def1 = min{DefAb, DefTu})
        # ------------------------------------------------------------------
        # Def1 debe ser menor o igual a ambos ( <= al min de los dos)
        m.addConstr(Def1[t] <= DefAb[t], name=f"R6_1e_Def1_le_Ab_{t}")
        m.addConstr(Def1[t] <= DefTu[t], name=f"R6_1f_Def1_le_Tu_{t}")

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

        # ------------------------------------------------------------------
        # (R6.4) COBERTURA DESDE EL TORO
        # ------------------------------------------------------------------
        # x_deficit cubre exactamente el déficit
        m.addConstr(
            x_deficit[t] * Conv == Def1[t],
            name=f"R6_4a_deficit_exacto_{t}"
        )

        # x total (extracción El Toro) >= x_deficit
        # Puede ser mayor si embalse necesita vaciarse
        # (vertimiento de emergencia)
        m.addConstr(
            x["Embalse", "ElToro", t] >= x_deficit[t],
            name=f"R6_4b_extraccion_total_{t}"
        )

    # 5) FO: Minimizar déficit + penalizar extracción excesiva
    # Prioridad 1: Minimizar déficit máximo (peso 1000x)
    # Prioridad 2: Minimizar extracción total para conservar agua en embalse
    MaxDef = m.addVar(lb=0.0, name="MaxDeficit")
    for t in T:
        m.addConstr(MaxDef >= Def1[t], name=f"MaxDef_ge_{t}")

    # Extracción total anual (Hm³)
    ExtraccionTotal = gp.quicksum(
        x["Embalse", "ElToro", t] * Conv for t in T
    )

    # Función objetivo: min(1000*MaxDef + ExtraccionTotal)
    # El factor 1000 asegura que minimizar déficit sea MUCHO más importante
    # que minimizar extracción, pero cuando déficit=0, prefiere conservar agua
    m.setObjective(1000 * MaxDef + ExtraccionTotal, GRB.MINIMIZE)

    # Adjuntar variables y metadatos al modelo para postprocesamiento
    m._y = y
    m._x = x
    m._x_deficit = x_deficit  # Agua exacta para cubrir déficit
    m._V = V
    m._Filtr = Filtr
    m._Def1 = Def1  # Déficit consolidado primeros regantes
    m._Def2 = Def2  # Déficit segundos regantes
    m._DefTu = DefTu  # Déficit Tucapel
    m._DefAb = DefAb  # Déficit Abanico
    m._Exc1 = Exc1  # Excedente primeros regantes
    m._meta = {
        "Conv": Conv,
        "ARCS": ARCS,
        # Agregar demandas mensuales para KPIs (extracción exacta)
        "demandas_mensuales": {
            "tucapel": {
                t: TUCAPEL_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            },
            "abanico": {
                t: ABANICO_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            },
            "segundos": {
                t: SEGUNDOS_MIN * SECOND_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            }
        }
    }

    return m


# =============================
# INTERFAZ PRINCIPAL
# =============================
if __name__ == "__main__":
    """
    Interfaz para ejecutar el modelo determinístico.
    Uso: python src/model.py
    """
    from ui_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Caso Base - Embalse del Laja",
        default_v0=V_0
    )
