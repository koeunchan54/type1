import streamlit as st

st.title("Paragraph Splitter")

text = st.text_area("Paste text", height=200)

if st.button("Split"):
  paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
  st.write(f"Number of Paragraphs: {len(paragraphs)}")

  for i, p in enumerate(paragraphs, start=1):
    st.markdown(f"**Paragraph {i}**")
    st.write(p)
