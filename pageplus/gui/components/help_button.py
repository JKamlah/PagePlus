import streamlit as st

def help_button(help_text):
    st.markdown(
        f'<div style="text-align: right;"><a href="#" title="{help_text}">ℹ️ Help</a></div>',
        unsafe_allow_html=True
    )
