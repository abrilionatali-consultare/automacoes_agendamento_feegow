from core.map_generator import generate_weekly_maps, generate_daily_maps

def gerar_mapas_wrapper(tipo, unidade_id, week_start):
    if tipo == "semanal":
        return generate_weekly_maps(
            start_date=week_start,
            unidade_id=None if unidade_id == "Todas" else unidade_id
        )
    elif tipo == "diario":
        return generate_daily_maps(
            start_date=week_start,
            unidade_id=None if unidade_id == "Todas" else unidade_id
        )

