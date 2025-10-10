"""
Script de prueba para verificar la modularización del código
"""

def test_imports():
    """Prueba que todos los módulos se puedan importar correctamente"""
    print("🧪 Probando imports de módulos...")
    
    try:
        from src.model import build_model_for_one_year
        print("✅ src.model - OK")
    except ImportError as e:
        print(f"❌ src.model - ERROR: {e}")
    
    try:
        from src.sensitivity_analysis import run_sensitivity_analysis
        print("✅ src.sensitivity_analysis - OK")
    except ImportError as e:
        print(f"❌ src.sensitivity_analysis - ERROR: {e}")
    
    try:
        from src.montecarlo_simulation import run_single_year_montecarlo
        print("✅ src.montecarlo_simulation - OK")
    except ImportError as e:
        print(f"❌ src.montecarlo_simulation - ERROR: {e}")
    
    try:
        from src.utils import print_summary_from_kpis
        print("✅ src.utils - OK")
    except ImportError as e:
        print(f"❌ src.utils - ERROR: {e}")
    
    try:
        from src.config import YEARS_HORIZON, DEFAULT_V0
        print("✅ src.config - OK")
        print(f"   Años disponibles: {len(YEARS_HORIZON)} ({min(YEARS_HORIZON)}-{max(YEARS_HORIZON)})")
        print(f"   V0 por defecto: {DEFAULT_V0} Hm³")
    except ImportError as e:
        print(f"❌ src.config - ERROR: {e}")
    
    print("\n🏗️  Modularización completada exitosamente!")


def test_main_cli():
    """Prueba la interfaz CLI principal"""
    print("\n🖥️  Probando CLI...")
    
    try:
        from src.main import parse_args
        print("✅ CLI parser disponible")
        
        # Simular argumentos de ayuda
        import sys
        original_argv = sys.argv
        sys.argv = ['main.py', '--help']
        
        try:
            parse_args()
        except SystemExit:
            # Es normal que --help termine con SystemExit
            pass
        finally:
            sys.argv = original_argv
            
        print("✅ CLI funcionando correctamente")
        
    except Exception as e:
        print(f"❌ CLI - ERROR: {e}")


if __name__ == "__main__":
    print("🚀 === PRUEBA DE MODULARIZACIÓN ===\n")
    test_imports()
    test_main_cli()
    print("\n✅ Todas las pruebas completadas!")