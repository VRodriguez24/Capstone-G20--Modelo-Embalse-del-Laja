# ================================
# SETUP BÁSICO DE LA RED
# ================================

# --- HORIZONTE MENSUAL (12 meses) ---
T = list(range(1, 12 + 1))

# --- NODOS ---
NODES = [
    # principales / generación
    "ElToro", "Abanico", "Antuco", "Rucue",
    "Quilleco", "Laja_I", "ElDiuto",

    # principales / conectividad (virtuales)
    "AltoPolc", "Embalse", "FiltracionesLaja",
    "Riegazaco", "Canrucue", "Canecol",
    "Clajrucue", "Tucapel", "CanalLaja",
    "SaltosLaja", "NodoMar",

    # controles
    "control_FiltracionesLaja", "control_Abanico",
    "control_Antuco", "control_Riegzaco", "control_Clajrucue",
    "control_Rucue", "control_Canecol", "control_Canrucue",
    "control_Quilleco", "control_Tucapel", "control_CanalLaja",
    "control_ElDiuto", "control_Laja_I",

    # afluentes (nodos fuente de inyección en arco)
    "afluente_Embalse", "afluente_Abanico", "afluente_Antuco",
    "afluente_Canecol", "afluente_Tucapel", "afluente_Laja_I",
]

# --- ARCOS ---

# Inyección (afluentes)
A_inyeccion = [
    ("afluente_Embalse", "Embalse"),
    ("afluente_Abanico",  "control_Abanico"),
    ("afluente_Antuco",   "control_Antuco"),
    ("afluente_Canecol",  "control_Canecol"),
    ("afluente_Tucapel",  "control_Tucapel"),
    ("afluente_Laja_I",   "control_Laja_I"),
]

# Arcos de generación (donde puede existir x[i,j,t])
A_generacion = [
    ("Embalse",           "ElToro"),
    ("control_Abanico",   "Abanico"),
    ("control_Antuco",    "Antuco"),
    ("control_Rucue",     "Rucue"),
    ("control_Quilleco",  "Quilleco"),
    ("control_CanalLaja", "CanalLaja"),
    ("control_ElDiuto",   "ElDiuto"),
    ("control_Laja_I",    "Laja_I"),
]

# Conectividad (virtuales)
A_conectividad = [
    ("AltoPolc",                 "Embalse"),
    ("Embalse",                  "control_FiltracionesLaja"),
    ("control_FiltracionesLaja", "FiltracionesLaja"),
    ("FiltracionesLaja",         "control_Abanico"),
    ("Abanico",                  "control_Antuco"),
    ("ElToro",                   "control_Antuco"),
    ("Antuco",                   "control_Riegzaco"),
    ("control_Riegzaco",         "Riegazaco"),
    ("Riegazaco",                "NodoMar"),
    ("control_Clajrucue",        "Clajrucue"),
    ("Clajrucue",                "control_Rucue"),
    ("control_Canrucue",         "Canrucue"),
    ("Canrucue",                 "control_Rucue"),
    ("Rucue",                    "control_Quilleco"),
    ("Quilleco",                 "control_Tucapel"),
    ("control_Canecol",          "Canecol"),
    ("Canecol",                  "control_Tucapel"),
    ("control_Tucapel",          "Tucapel"),
    ("Tucapel",                  "control_CanalLaja"),
    ("CanalLaja",                "control_ElDiuto"),
    ("ElDiuto",                  "NodoMar"),
    ("Laja_I",                   "SaltosLaja"),
]

# Vertimientos (entre controles y sumideros)
A_vertimiento = [
    ("control_Abanico",   "control_Antuco"),
    ("control_Antuco",    "control_Riegzaco"),
    ("control_Riegzaco",  "control_Clajrucue"),
    ("control_Clajrucue", "control_Tucapel"),
    ("control_Rucue",     "control_Quilleco"),
    ("control_Quilleco",  "control_Tucapel"),
    ("control_Tucapel",   "control_CanalLaja"),
    ("control_CanalLaja", "control_Laja_I"),
    ("control_Laja_I",    "SaltosLaja"),
    ("control_ElDiuto",   "NodoMar"),
]

# --- Consolidado de arcos + validaciones ---
ARCS = A_inyeccion + A_generacion + A_conectividad + A_vertimiento

# Dedupe manteniendo orden
_seen = set()
ARCS = [e for e in ARCS if not (e in _seen or _seen.add(e))]

# Validación: nodos existentes
bad_arcs = [(i, j) for (i, j) in ARCS if i not in NODES or j not in NODES]
assert not bad_arcs, f"Hay arcos con nodos inexistentes: {bad_arcs}"

# Vecindarios
IN = {n: [i for (i, j) in ARCS if j == n] for n in NODES}
OUT = {n: [j for (i, j) in ARCS if i == n] for n in NODES}
