import streamlit as st

st.title("Text Length Counter with Buttons")

text = st.text_area("Enter text", height=200)

if st.button("Count"):
  st.write(f"Character Count: {len(text)}")
