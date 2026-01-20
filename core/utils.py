from datetime import datetime, timedelta, date, time
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
import pandas as pd
import re

# ---------------- tratamento de dados ----------------
def format_cell(raw):
    if not raw or not isinstance(raw, str):
        return ""

    items = raw.split("||ITEM||")
    out_lines = []

    for item in items:
        parts = item.split("||SEP||")
        # Agora esperamos 4 partes: Especialidade, Nome, Horário, Taxa
        if len(parts) < 3:
            continue

        esp = parts[0].strip().upper()
        nome = parts[1].strip()
        horario = parts[2].strip()
        taxa = parts[3].strip() if len(parts) > 3 else ""

        # Montagem do bloco interno
        bloco = f"<b>{esp}</b><br/>{nome}<br/><b>{horario}</b>"
        if taxa:
            bloco += f"<br/><span style='font-size: 0.9em; opacity: 0.9;'>Ocupação: {taxa}%</span>"
        
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
    """Retorna 'Manhã' se horário <= 12:00:00, caso contrário 'Tarde'"""
    if t is None:
        return None
    
    # Compara o horário completo com 12:00:00
    return "Manhã" if t <= time(12, 0, 0) else "Tarde"

def fmt_time(t):
    if t is None:
        return ""
    return t.strftime("%H:%M")

# ---------------- agregação e montagem de matrizes ----------------
def get_natural_key(text):
    """
    Gera uma chave de ordenação natural (Ex: Sala 2 antes de Sala 10).
    Retorna TUPLA (hashable) para ser compatível com Pandas e sort().
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Retorna tupla para evitar erro 'unhashable type: list' no Pandas
    return tuple([
        int(c) if c.isdigit() else c.lower()
        for c in re.split("([0-9]+)", text)
    ])

def sort_natural(values):
    """Ordenação natural de uma lista de valores."""
    return sorted(values, key=get_natural_key)

def build_matrices(df, include_taxa=True):
    df = df.copy()
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["time"] = df["horario"].apply(to_time)
    df["periodo"] = df["time"].apply(periodo_from_time)

    day_names = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado"]
    df["dia_pt"] = df["data"].apply(lambda d: day_names[d.weekday()] if d.weekday() < 6 else "")
    
    def montar_matriz(subdf, salas):
        if not salas: return None
        mat = pd.DataFrame("", index=salas, columns=day_names)
        group_cols = ["sala", "dia_pt", "especialidade", "nome_profissional"]
        
        subdf_grouped = (
            subdf.groupby(group_cols)
                 .agg(
                     start=("time", "min"), 
                     end=("time", "max"),
                     real_appts=("agendamento_id", lambda x: (x > 0).sum()),
                     total_slots=("horario", "count")
                 )
                 .reset_index()
        )

        for _, r in subdf_grouped.iterrows():
            # Define o horário formatado
            horario_str = f"{fmt_time(r['start'])}-{fmt_time(r['end'])}"
            
            if include_taxa:
                # Lógica para o Mapa Diário (com taxa e flag de cor)
                taxa_val = (r["real_appts"] / r["total_slots"] * 100) if r["total_slots"] > 0 else 0
                taxa_str = f"{taxa_val:.0f}"
                low_flag = "||LOW||" if taxa_val < 50 else ""
                item = f"{r['especialidade']}||SEP||{r['nome_profissional']}||SEP||{horario_str}||SEP||{taxa_str}{low_flag}"
            else:
                # Lógica para o Mapa Semanal (limpo, sem taxa)
                item = f"{r['especialidade']}||SEP||{r['nome_profissional']}||SEP||{horario_str}"

            prev = mat.at[r["sala"], r["dia_pt"]]
            mat.at[r["sala"], r["dia_pt"]] = (prev + "||ITEM||" + item) if prev else item
        return mat

    # Separação Manhã/Tarde
    matrices = {
        "Manhã": montar_matriz(df[df["periodo"] == "Manhã"], sort_natural(df[df["periodo"] == "Manhã"]["sala"].unique())),
        "Tarde": montar_matriz(df[df["periodo"] == "Tarde"], sort_natural(df[df["periodo"] == "Tarde"]["sala"].unique()))
    }

    occupancy = {"Manhã": [], "Tarde": []}
    for periodo, m in matrices.items():
        if m is None:
            occupancy[periodo] = [0]*6
            continue
        for dia in day_names:
            filled = m[dia].apply(lambda v: isinstance(v, str) and v.strip() != "").sum()
            occupancy[periodo].append(int(round((filled / len(m.index)) * 100)) if len(m.index) else 0)

    return matrices, occupancy, day_names


# ---------------- render / salvar PDF ----------------
def render_pdf_from_template(
    unidade,
    matrices,
    occupancy,
    day_names,
    week_start_date,
    week_end_date,
    template_path,
    out_pdf_path=None,
    cell_font_size_px=10,
    return_bytes=False
):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from weasyprint import HTML
    from datetime import datetime

    env = Environment(
        loader=FileSystemLoader('.'),
        autoescape=select_autoescape(['html','xml'])
    )

    # registra format_cell tanto como filtro quanto como global
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

    # ➖➖➖➖➖➖➖
    # Se quiser PDF em bytes (para o Streamlit)
    # ➖➖➖➖➖➖➖
    if return_bytes:
        pdf_bytes = HTML(string=html).write_pdf()
        return pdf_bytes

    # ➖➖➖➖➖➖➖
    # Se quiser salvar o PDF em arquivo
    # ➖➖➖➖➖➖➖
    if out_pdf_path is None:
        raise ValueError("out_pdf_path é obrigatório quando return_bytes=False")

    HTML(string=html).write_pdf(out_pdf_path)
    print(f"PDF salvo em: {out_pdf_path}")
    return out_pdf_path


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


