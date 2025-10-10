"""
Utilidades y funciones auxiliares para el modelo de optimización
"""
from typing import Dict, Any

def print_summary_from_kpis(kpis: Dict[str, Any]):
    """Imprime resumen de resultados basado en KPIs calculados."""
    print("\n" + "="*60)
    print("📊 RESUMEN DE OPTIMIZACIÓN")
    print("="*60)
    
    print(f"✅ Años óptimos: {kpis.get('optimal_years', 0)}/{kpis.get('total_years', 0)}")
    print(f"📈 Tasa factibilidad: {kpis.get('feasibility_rate', 0)*100:.1f}%")
    
    if kpis.get('total_energy_MWh', 0) > 0:
        print(f"⚡ Generación total: {kpis['total_energy_MWh']:.1f} MWh")
        print(f"📊 Promedio anual: {kpis['avg_energy_MWh']:.1f} MWh")
        print(f"🎯 Mejor año: {kpis.get('best_year', 'N/A')} "
              f"({kpis.get('max_energy_MWh', 0):.1f} MWh)")
    
    print("="*60)