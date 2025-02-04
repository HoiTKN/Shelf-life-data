import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import get_as_dataframe

# ---------------------------
# HÀM: ĐỌC DỮ LIỆU TỪ GOOGLE SHEET
# ---------------------------
@st.cache_data(show_spinner=False)
def load_data():
    # Lấy thông tin credentials từ st.secrets (secrets.toml)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(credentials)
    
    # Lấy URL của Google Sheet từ st.secrets
    sheet_url = st.secrets["sheet"]["url"]
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    
    # Đọc dữ liệu từ worksheet thành DataFrame
    df = get_as_dataframe(worksheet, evaluate_formulas=True, header=0)
    # Xóa các dòng hoàn toàn trống nếu có
    df = df.dropna(how="all")
    return df

# Đọc dữ liệu
data = load_data()
st.write("### Dữ liệu từ Google Sheet", data.head())

# ---------------------------
# XỬ LÝ DỮ LIỆU CHO BIỂU ĐỒ
# ---------------------------

# Tạo bộ lọc dựa trên các cột "Category description" và "Spec description"
if "Category description" in data.columns and "Spec description" in data.columns:
    categories = data["Category description"].dropna().unique().tolist()
    specs = data["Spec description"].dropna().unique().tolist()
else:
    st.error("Không tìm thấy cột 'Category description' hoặc 'Spec description' trong dữ liệu.")
    st.stop()

st.sidebar.header("Bộ lọc dữ liệu")
selected_categories = st.sidebar.multiselect("Chọn ngành hàng:", options=categories, default=categories)
selected_specs = st.sidebar.multiselect("Chọn sản phẩm:", options=specs, default=specs)

# Lọc dữ liệu theo lựa chọn
filtered_data = data[
    data["Category description"].isin(selected_categories) &
    data["Spec description"].isin(selected_specs)
]

# Hàm chuyển đổi Sample Name thành giá trị thời gian (đơn vị: tháng)
def parse_sample_name(sample_name):
    """
    Ví dụ format: "01D-RO", "02W-RO", "01M-RO"
    - Nếu có chữ D (Days): chuyển sang tháng = số ngày / 30
    - Nếu có chữ W (Weeks): chuyển sang tháng = số tuần / 4.345
    - Nếu có chữ M (Months): giữ nguyên số đó
    """
    try:
        # Lấy phần trước dấu "-" ví dụ "01D" từ "01D-RO"
        part = sample_name.split('-')[0]
        num_str = "".join(filter(str.isdigit, part))
        unit = "".join(filter(str.isalpha, part)).upper()
        num = float(num_str)
        if unit == "D":
            return num / 30.0
        elif unit == "W":
            return num / 4.345
        elif unit == "M":
            return num
        else:
            return None
    except Exception as e:
        return None

# Tạo cột mới "Time_Months" từ cột "Sample Name"
if "Sample Name" in filtered_data.columns:
    filtered_data["Time_Months"] = filtered_data["Sample Name"].apply(parse_sample_name)
else:
    st.error("Không tìm thấy cột 'Sample Name' trong dữ liệu.")
    st.stop()

# Tách dữ liệu cho biểu đồ cảm quan và hóa lý dựa trên cột "Test"
# Chỉ tiêu cảm quan: Test bắt đầu bằng "CQ"
# Chỉ tiêu hóa lý: Test bắt đầu bằng "HL"
if "Test" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Test' trong dữ liệu.")
    st.stop()

sensory_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("CQ")]
chemical_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("HL")]

# ---------------------------
# VẼ BIỂU ĐỒ DỰA TRÊN PLOTLY
# ---------------------------

# Biểu đồ cảm quan
if not sensory_data.empty:
    fig_sensory = px.line(
        sensory_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        title="Biểu đồ xu hướng CẢM QUAN",
        labels={"Time_Months": "Thời gian (tháng)", "Actual result": "Kết quả Actual"}
    )
    st.plotly_chart(fig_sensory, use_container_width=True)
else:
    st.info("Không có dữ liệu cảm quan để hiển thị biểu đồ.")

# Biểu đồ hóa lý
if not chemical_data.empty:
    fig_chemical = px.line(
        chemical_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        title="Biểu đồ xu hướng HÓA LÝ",
        labels={"Time_Months": "Thời gian (tháng)", "Actual result": "Kết quả Actual"}
    )
    st.plotly_chart(fig_chemical, use_container_width=True)
else:
    st.info("Không có dữ liệu hóa lý để hiển thị biểu đồ.")
