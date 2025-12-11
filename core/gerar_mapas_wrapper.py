from datetime import datetime, timedelta
from pathlib import Path
from core.api_client import fetch_agendamentos_completos
from core.map_generator import build_matrices, generate_weekly_maps
from core.utils import render_pdf_from_template
import re

def gerar_mapas_wrapper(tipo, unidade_id, week_start):
    if tipo == "semanal":
        return generate_weekly_maps(
            start_date=week_start,
            unidade_id=None if unidade_id == "Todas" else unidade_id
        )
