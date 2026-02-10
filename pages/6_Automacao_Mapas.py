import os
from datetime import date

import streamlit as st

from automation.daily_maps import (
    DEFAULT_OUTPUT_DIR,
    generate_daily_maps_for_units,
    get_available_units,
    get_configured_units_from_env,
    resolve_units,
)
from automation.drive_uploader import GoogleDriveUploader, is_drive_upload_configured
from automation.timezone_utils import DEFAULT_TIMEZONE, resolve_target_date


if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")
    st.stop()

st.set_page_config(page_title="Automacao de Mapas", page_icon="🗓️", layout="wide")

st.title("🗓️ Automacao de Mapas Diarios")
st.write(
    "Dispare manualmente a geracao dos mapas diarios das unidades e, se configurado, "
    "publique os PDFs no Google Drive."
)


def _default_unit_selection(available_units: list[str]) -> list[str]:
    configured = get_configured_units_from_env()
    if configured:
        try:
            return resolve_units(configured)
        except Exception:
            pass
    return available_units[:3]


available_units = get_available_units()
if not available_units:
    st.error("Nenhuma unidade disponivel encontrada na API.")
    st.stop()

default_units = _default_unit_selection(available_units)
default_timezone = os.getenv("MAP_AUTOMATION_TIMEZONE", DEFAULT_TIMEZONE)
default_output_dir = os.getenv("MAP_AUTOMATION_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)

col1, col2, col3 = st.columns(3)
with col1:
    mode_label = st.radio(
        "Data alvo",
        options=["Hoje (BRT)", "Amanha (BRT)", "Data especifica"],
        horizontal=False,
    )
with col2:
    custom_date = st.date_input(
        "Data especifica",
        value=date.today(),
        format="DD/MM/YYYY",
        disabled=mode_label != "Data especifica",
    )
with col3:
    timezone_name = st.text_input("Timezone", value=default_timezone)

selected_units = st.multiselect(
    "Unidades para gerar",
    options=available_units,
    default=default_units,
)

col_opts_1, col_opts_2, col_opts_3 = st.columns(3)
with col_opts_1:
    save_local = st.checkbox("Salvar localmente", value=True)
with col_opts_2:
    upload_drive = st.checkbox(
        "Enviar para Google Drive",
        value=is_drive_upload_configured("diario"),
    )
with col_opts_3:
    output_dir = st.text_input("Diretorio local", value=default_output_dir)

if upload_drive and not is_drive_upload_configured("diario"):
    st.warning(
        "Google Drive nao esta totalmente configurado. "
        "Verifique credentials.json, token.json e pasta raiz do mapa diario."
    )

if not selected_units:
    st.info("Selecione ao menos uma unidade.")
    st.stop()

if st.button("Gerar mapas diarios agora", type="primary"):
    mode_map = {
        "Hoje (BRT)": "today",
        "Amanha (BRT)": "tomorrow",
        "Data especifica": "date",
    }
    mode = mode_map[mode_label]

    with st.spinner("Gerando mapas diarios..."):
        try:
            resolved = resolve_target_date(
                mode,
                timezone_name=timezone_name,
                explicit_date=custom_date if mode == "date" else None,
            )
            units = resolve_units(selected_units)
            results = generate_daily_maps_for_units(
                target_date=resolved.target_date,
                units=units,
                save_local=save_local,
                output_dir=output_dir,
            )

            if upload_drive and is_drive_upload_configured("diario"):
                uploader = GoogleDriveUploader()
                for result in results:
                    if not result.success or not result.pdf_bytes or not result.filename:
                        continue
                    try:
                        uploaded = uploader.upload_map_pdf(
                            map_type="diario",
                            target_date=result.target_date,
                            filename=result.filename,
                            file_bytes=result.pdf_bytes,
                        )
                        result.drive_file_id = uploaded.file_id
                        result.drive_web_view_link = uploaded.web_view_link
                    except Exception as exc:
                        result.success = False
                        result.error = f"Falha no upload para Drive: {exc}"

            success_count = sum(1 for r in results if r.success)
            warning_count = sum(1 for r in results if r.warning)
            error_count = sum(1 for r in results if not r.success and not r.warning)

            st.success(
                f"Processamento finalizado: {success_count} sucesso(s), "
                f"{warning_count} aviso(s), {error_count} erro(s)."
            )
            st.caption(
                f"Data alvo: {resolved.target_date.strftime('%d/%m/%Y')} | "
                f"Timezone: {resolved.timezone} | "
                f"Hora local de referencia: {resolved.now_local.strftime('%d/%m/%Y %H:%M:%S')}"
            )

            for idx, item in enumerate(results):
                if item.success and item.pdf_bytes and item.filename:
                    st.subheader(item.unidade)
                    c1, c2, c3 = st.columns([2, 2, 3])
                    with c1:
                        st.download_button(
                            label=f"Baixar PDF - {item.unidade}",
                            data=item.pdf_bytes,
                            file_name=item.filename,
                            mime="application/pdf",
                            key=f"dl_{idx}",
                        )
                    with c2:
                        st.write(item.local_path or "Nao salvo localmente")
                    with c3:
                        if item.drive_web_view_link:
                            st.link_button("Abrir no Drive", item.drive_web_view_link)
                        elif item.drive_file_id:
                            st.write(f"Drive file_id: {item.drive_file_id}")
                        else:
                            st.write("Sem upload no Drive")
                elif item.warning:
                    st.warning(f"{item.unidade}: {item.warning}")
                else:
                    st.error(f"{item.unidade}: {item.error}")
        except Exception as exc:
            st.error(f"Erro durante a automacao: {exc}")
