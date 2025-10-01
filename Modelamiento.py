import gurobipy as gp
from gurobipy import GRB

# =============================
# Conjuntos y parámetros básicos
# =============================
T = range(1, 13)             # Meses
K = range(1, 5)              # Tramos de filtración

# Centrales de generación
Cgen = ["ELTORO", "ABANICO", "ANTUCO", "RUCUE",
        "QUILLECO", "LAJA_I", "EL_DIUTO"]

# Nodos
N = [

]

# Arcos (origen, destino, nombre)
''' Incluye: turbinas, derivaciones controladas, Saltos, “naturales” '''
A = [

]

# Colchones operacionales
C = {"Superior": 1,
     "Intermedio": 2,
     "Transicion": 3,
     "Inferior": 4}

# Porcentajes de reparto de agua (riego, generacion, lago)
C_1 = []
C_2 = []
C_3 = []
C_4 = []

# Parámetros
M = 1e6                                # Constante Big-M grande
V_0 = 0                                # volumen inicial del lago
V_E = 0                                # volumen del fondo de emergenica

In = {}                                # afluentes

# caudales máximos
qmax_c = {"ELTORO": 91.1, "ABANICO": 77.5, "ANTUCO": 200.0, "RUCUE": 139.4,
          "QUILLECO": 127.3, "LAJA_I": 250.4, "EL_DIUTO": 20.0}
# rendimientos energéticos
r_c = {"ELTORO": 4.8, "ABANICO": 1.2, "ANTUCO": 1.6, "RUCUE": 1.28,
       "QUILLECO": 0.55, "LAJA_I": 0.137, "EL_DIUTO": 0.1625}


# PWL filtraciones El Toro (K=4)
# Coeficientes (a_k + b_k * S)
a_k = {
    1: -477.789,
    2: -483.720,
    3: -707.724,
    4: -1159.45,
}
b_k = {
    1: 0.378375,
    2: 0.382877,
    3: 0.550670,
    4: 0.884665,
}
S_Lk = {1: 1300.0, 2: 1317.5, 3: 1335.0, 4: 1352.5}
S_Uk = {1: 1317.5, 2: 1335.0, 3: 1352.5, 4: 1370.0}


# =============================
# Modelo
# =============================
m = gp.Model("Lago_Laja")

# Variables
S = m.addVars(T, name="S")                        # almacenamiento
Filtr = m.addVars(T, name="Filtr")                # filtraciones
y = m.addVars(K, T, vtype=GRB.BINARY, name="y")   # binarios tramos
x = m.addVars(T, name="x")                        # ejemplo caudales

# =============================
# Restricciones
# =============================

# R1 - X

# R2 - Cotas de almacenamiento
Smin, Smax = 500, 5500
for t in T:
    m.addConstr(S[t] >= Smin)
    m.addConstr(S[t] <= Smax)


# R14 - Filtraciones PWL (4 tramos)
for t in T:
    # 1) Exactamente un tramo activo
    m.addConstr(gp.quicksum(y[k, t] for k in K) == 1,
                name=f"R14a_exact_t{t}")

    Sprev = V_0 if t == 1 else S[t-1]

    for k in K:
        # 2) Activación de dominio (solo válido si el tramo está activo)
        m.addConstr(Sprev >= S_Lk[k] - M*(1-y[k, t]),
                    name=f"R14b_low_t{t}_k{k}")
        m.addConstr(Sprev <= S_Uk[k] + M*(1-y[k, t]),
                    name=f"R14b_up_t{t}_k{k}")

        # 3) Restricción inferior
        m.addConstr(Filtr[t] >= a_k[k] + b_k[k]*Sprev - M*(1-y[k, t]),
                    name=f"R14c_lb_t{t}_k{k}")
        # 4) Restricción superior
        m.addConstr(Filtr[t] <= a_k[k] + b_k[k]*Sprev + M*(1-y[k, t]),
                    name=f"R14d_ub_t{t}_k{k}")


# =============================
# Función objetivo
# =============================
# Maximizar la generación de Energía

m.optimize()
