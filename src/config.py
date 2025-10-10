"""
Configuración y constantes del modelo de optimización del Embalse del Laja
"""

# Rango de años disponibles para optimización
YEARS_HORIZON = list(range(1960, 2024))

# Configuración por defecto
DEFAULT_V0 = 1200.0  # Volumen inicial por defecto en Hm³
DEFAULT_TIME_LIMIT = None  # Sin límite por defecto
DEFAULT_N_SIMS = 100  # Número de simulaciones Monte Carlo por defecto
DEFAULT_SEED = 42  # Semilla por defecto para reproducibilidad

# Parámetros de análisis de sensibilidad
SENSITIVITY_PARAMS = {
    'V0': {'min': 800, 'max': 1400, 'step': 50},
    'factor_segundos': {'min': 0.5, 'max': 1.5, 'step': 0.1},
    'factor_primeros': {'min': 0.8, 'max': 1.2, 'step': 0.05}
}