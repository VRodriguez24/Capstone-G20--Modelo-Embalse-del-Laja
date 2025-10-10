# __init__.py
"""
Paquete del modelo de optimización del Embalse del Laja.
"""

# Configurar el path para imports
import sys
import os

# Agregar el directorio src al path cuando se importa el paquete
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
