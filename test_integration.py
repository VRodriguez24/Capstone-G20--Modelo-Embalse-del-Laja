#!/usr/bin/env python3
"""
Test final de la solución de infactibilidad integrada en main.py
"""

import sys
sys.path.append('src')

from main import run_deterministic

def test_integration():
    """Probar la solución integrada con casos conocidos."""
    print("🧪 PRUEBA DE INTEGRACIÓN - SOLUCIÓN DE INFACTIBILIDAD")
    print("=" * 70)
    
    # Caso 1: Años problemáticos con V0 bajo (conocido problemático)
    print("\n📊 CASO 1: Modo estándar con volumen bajo")
    print("(Debería tener infactibilidades)")
    print("-" * 50)
    
    problematic_years = [1960, 1961, 1962]
    low_V0 = 1220.0
    
    run_deterministic(years=problematic_years, V0=low_V0, robust=False)
    
    print("\n" + "=" * 70)
    print("📊 CASO 2: Modo robusto con el mismo escenario")
    print("(Debería resolver las infactibilidades)")
    print("-" * 50)
    
    run_deterministic(years=problematic_years, V0=low_V0, robust=True)
    
    print("\n" + "=" * 70)
    print("✅ PRUEBA COMPLETADA")
    print("=" * 70)

if __name__ == "__main__":
    test_integration()