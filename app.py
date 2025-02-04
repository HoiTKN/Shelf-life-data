import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import get_as_dataframe

# Hàm lấy dữ liệu từ Google Sheet
@st.cache_data(show_spinner=False)
def load_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(credentials)
    sheet_url = st.secrets["sheet"]["url"]
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    df = get_as_dataframe(worksheet, evaluate_formulas=True, header=0)
    df = df.dropna(how="all")
    return df

# Đọc dữ liệu
data = load_data()
st.write("### Dữ liệu từ Google Sheet", data.head())

# Ví dụ: Hiển thị một biểu đồ đơn giản
if "Actual result" in data.columns and "Sample Name" in data.columns:
    st.write("Biểu đồ mẫu (chưa xử lý thời gian):")
    fig = px.line(data, x="Sample Name", y="Actual result", title="Biểu đồ mẫu")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Dữ liệu không có cột 'Sample Name' hoặc 'Actual result'.")
