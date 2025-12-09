from datetime import datetime, timedelta, date, time
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
import pandas as pd
import re

# ---------------- tratamento de dados ----------------
def format_cell(raw):
    """
    Recebe a string já consolidada pelo build_matrices().
    Formato esperado:
        ESPECIALIDADE||SEP||NOME||SEP||HH:MM-HH:MM
        (várias entradas separadas por ||ITEM||)
    Retorna HTML formatado:
        <b>ESPECIALIDADE</b><br/>
        Nome<br/>
        <b>Horário</b><br/><br/>
    """
    if not raw or not isinstance(raw, str):
        return ""

    # Cada bloco de atendimento
    items = raw.split("||ITEM||")
    out_lines = []

    for item in items:
        parts = item.split("||SEP||")
        if len(parts) != 3:
            continue

        esp, nome, horario = parts
        esp = esp.strip().upper()
        nome = nome.strip()
        horario = horario.strip()

        bloco = f"<b>{esp}</b><br/>{nome}<br/><b>{horario}</b>"
        out_lines.append(bloco)

    return "<br/><br/>".join(out_lines)

# ---------------- utilitários de tempo ----------------
def normalize_time_to_minute(t):
    """Recebe datetime.time ou None e retorna time com segundos=0 (arredonda/trunca)."""
    if t is None:
        return None
    # se for datetime.time com segundos, zerar segundos
    return time(hour=t.hour, minute=t.minute, second=0, microsecond=0)

def to_time(h):
    """Converte '08:00' ou datetime/time em objeto datetime.time"""
    if pd.isna(h):
        return None
    if isinstance(h, time):
        return h
    if isinstance(h, datetime):
        return h.time()
    s = str(h).strip()
    # tenta HH:MM[:SS]
    try:
        return datetime.strptime(s, "%H:%M:%S").time()
    except:
        try:
            return datetime.strptime(s, "%H:%M").time()
        except:
            raise ValueError(f"Formato de horário inválido: {h}")

def periodo_from_time(t: time):
    """Define 'Manhã' se t.hour < 12, caso contrário 'Tarde'"""
    if t is None:
        return None
    return "Manhã" if t.hour < 12 else "Tarde"

def fmt_time(t):
    if t is None:
        return ""
    return t.strftime("%H:%M")

# ---------------- agregação e montagem de matrizes ----------------
def sort_natural(values):
    """Ordenação natural: CONSULTÓRIO 2 < CONSULTÓRIO 10."""
    def alphanum_key(key):
        return [
            int(text) if text.isdigit() else text.lower()
            for text in re.split("([0-9]+)", str(key))
        ]
    return sorted(values, key=alphanum_key)

def build_matrices(df):
    """
    Recebe df já filtrado pela data.
    Retorna:
        matrices: {"Manhã": DataFrame, "Tarde": DataFrame}
        occupancy: {"Manhã": [..], "Tarde":[..]}
        day_names: lista fixa de dias (Seg -> Sáb)
    """

    df = df.copy()

    # -------------------------------------------------------------------------
    # 1. Ajustar tipos
    # -------------------------------------------------------------------------
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["time"] = df["horario"].apply(to_time)
    df["periodo"] = df["time"].apply(periodo_from_time)

    # -------------------------------------------------------------------------
    # 2. Dias fixos
    # -------------------------------------------------------------------------
    day_names = [
        "Segunda-feira", "Terça-feira", "Quarta-feira",
        "Quinta-feira", "Sexta-feira", "Sábado"
    ]

    # Criar coluna dia_pt
    df["dia_pt"] = df["data"].apply(lambda d: day_names[d.weekday()] if d.weekday() < 6 else "")
    df = df[df["dia_pt"].isin(day_names)]

    # -------------------------------------------------------------------------
    # 3. Separar manha / tarde
    # -------------------------------------------------------------------------
    manha_df = df[df["periodo"] == "Manhã"].copy()
    tarde_df = df[df["periodo"] == "Tarde"].copy()

    # -------------------------------------------------------------------------
    # 4. Ordenar salas
    # -------------------------------------------------------------------------
    salas_manha = sort_natural(manha_df["sala"].unique()) if not manha_df.empty else []
    salas_tarde = sort_natural(tarde_df["sala"].unique()) if not tarde_df.empty else []

    # -------------------------------------------------------------------------
    # 5. Função interna para montar matriz consolidada
    # -------------------------------------------------------------------------
    def montar_matriz(subdf, salas):
        if not salas:
            return None

        # DataFrame final
        mat = pd.DataFrame("", index=salas, columns=day_names)

        # Agrupamento para encontrar 1º e último horário por profissional
        # CHAVE: (sala, dia, especialidade, profissional)
        group_cols = ["sala", "dia_pt", "especialidade", "nome_profissional"]

        subdf_grouped = (
            subdf.groupby(group_cols)
                 .agg(start=("time", "min"), end=("time", "max"))
                 .reset_index()
        )

        # Preencher a matriz
        for _, r in subdf_grouped.iterrows():
            sala = r["sala"]
            dia = r["dia_pt"]
            esp = r["especialidade"]
            prof = r["nome_profissional"]

            # Montar intervalo
            start_t = fmt_time(r["start"])
            end_t = fmt_time(r["end"])
            horario = f"{start_t}-{end_t}"

            # Formar item bruto (será formatado no template)
            item = f"{esp}||SEP||{prof}||SEP||{horario}"

            prev = mat.at[sala, dia]
            if prev:
                mat.at[sala, dia] = prev + "||ITEM||" + item
            else:
                mat.at[sala, dia] = item

        return mat

    # -------------------------------------------------------------------------
    # 6. Gerar matrizes
    # -------------------------------------------------------------------------
    mat_manha = montar_matriz(manha_df, salas_manha)
    mat_tarde = montar_matriz(tarde_df, salas_tarde)

    matrices = {
        "Manhã": mat_manha if (mat_manha is not None and not mat_manha.empty) else None,
        "Tarde": mat_tarde if (mat_tarde is not None and not mat_tarde.empty) else None,
    }

    # -------------------------------------------------------------------------
    # 7. Ocupação por período
    # -------------------------------------------------------------------------
    occupancy = {"Manhã": [], "Tarde": []}

    for periodo, mat in matrices.items():
        if mat is None:
            occupancy[periodo] = []
            continue

        total_salas = len(mat.index)

        for dia in day_names:
            filled = mat[dia].apply(lambda v: isinstance(v, str) and v.strip() != "").sum()
            perc = int(round((filled / total_salas) * 100)) if total_salas else 0
            occupancy[periodo].append(perc)

    return matrices, occupancy, day_names


# ---------------- render / salvar PDF ----------------
def render_pdf_from_template(
    unidade,
    matrices,
    occupancy,
    day_names,
    week_start_date,
    week_end_date,
    template_path="map_template.html",
    out_pdf_path="mapa_semana.pdf",
    cell_font_size_px=10
):
    env = Environment(
        loader=FileSystemLoader('.'),
        autoescape=select_autoescape(['html','xml'])
    )

    # registra format_cell tanto como filtro quanto como global (evita UndefinedError)
    env.filters["format_cell"] = format_cell
    env.globals["format_cell"] = format_cell

    tpl = env.get_template(template_path)

    # datas
    if isinstance(week_start_date, str):
        start = datetime.strptime(week_start_date, "%d-%m-%Y").date()
    else:
        start = week_start_date

    if isinstance(week_end_date, str):
        end = datetime.strptime(week_end_date, "%d-%m-%Y").date()
    else:
        end = week_end_date

    week_label = f"{start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}"

    # render com passagem explícita de format_cell no contexto (redundante, mas seguro)
    html = tpl.render(
        unidade=unidade,
        matrices=matrices,
        occupancy=occupancy,
        week_label=week_label,
        generated=datetime.now().strftime("%d/%m/%Y %H:%M"),
        day_names=day_names,
        cell_font_size_px=cell_font_size_px,
        format_cell=format_cell
    )

    HTML(string=html).write_pdf(out_pdf_path)
    print(f"PDF salvo em: {out_pdf_path}")



# ---------------- helper para input do usuário ----------------
def ask_week_start():
    """Pede ao usuário a data de início no formato DD-MM-AAAA, valida e retorna date."""
    while True:
        s = input("Insira a data de início (DD-MM-AAAA): ").strip()
        try:
            dt = datetime.strptime(s, "%d-%m-%Y").date()
            return dt
        except Exception as e:
            print("Formato inválido. Use DD-MM-AAAA (ex.: 01-12-2025). Tente novamente.")