import streamlit as st

st.title("Text Length Counter")

text = st.text_area("Enter text", height=200)

if text:
  st.wirte(f"Character Count: {len(text)}")
