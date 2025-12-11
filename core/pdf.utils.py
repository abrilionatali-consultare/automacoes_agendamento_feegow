import base64
import streamlit as st
from io import BytesIO

def pdf_bytes_to_download_button(pdf_bytes: bytes, label="Download PDF", filename="mapa.pdf"):
    b64 = base64.b64encode(pdf_bytes).decode()
    href = f'<a href="data:application/pdf;base64,{b64}" download="{filename}">{label}</a>'
    st.markdown(href, unsafe_allow_html=True)

def show_pdf(pdf_bytes: bytes):
    b64 = base64.b64encode(pdf_bytes).decode()
    pdf_display = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600px" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)