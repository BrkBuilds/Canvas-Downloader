import streamlit as st
st.html("""<style>
div[data-testid="stExpander"] details > summary::after {
    content: "Floating Tooltip";
    position: fixed;
    margin-top: -30px;
    margin-left: 20px;
    background: #f00;
    color: #fff;
    padding: 5px;
    z-index: 99999;
}
</style>""")
with st.container(border=True):
    with st.expander("Hello world"):
        st.write("Content")
