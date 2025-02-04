import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import get_as_dataframe

##############################################
# PHẦN 1: LOAD DỮ LIỆU TỪ GOOGLE SHEET
##############################################

@st.cache_data(show_spinner=False)
def load_data():
    """
    Hàm load dữ liệu từ Google Sheet sử dụng thông tin trong st.secrets.
    Cấu hình credentials đã được lưu trong file secrets.toml.
    """
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(credentials)
    
    # Lấy URL của Google Sheet từ phần secrets
    sheet_url = st.secrets["sheet"]["url"]
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    
    # Đọc dữ liệu thành DataFrame, evaluate_formulas=True nếu có công thức
    df = get_as_dataframe(worksheet, evaluate_formulas=True, header=0)
    df = df.dropna(how="all")
    return df

# Load dữ liệu
data = load_data()
st.write("### Dữ liệu từ Google Sheet (5 dòng đầu tiên)", data.head())

##############################################
# PHẦN 2: BỘ LỌC DỮ LIỆU (Sidebar)
##############################################

# Kiểm tra sự tồn tại của cột Category description và Spec description
if "Category description" not in data.columns or "Spec description" not in data.columns:
    st.error("Dữ liệu không có cột 'Category description' hoặc 'Spec description'.")
    st.stop()

# Lấy danh sách các giá trị duy nhất cho bộ lọc
categories = data["Category description"].dropna().unique().tolist()
specs = data["Spec description"].dropna().unique().tolist()

st.sidebar.header("Bộ lọc dữ liệu")
selected_categories = st.sidebar.multiselect("Chọn ngành hàng:", options=categories, default=categories)
selected_specs = st.sidebar.multiselect("Chọn sản phẩm:", options=specs, default=specs)

# Lọc dữ liệu theo lựa chọn của người dùng
filtered_data = data[
    data["Category description"].isin(selected_categories) &
    data["Spec description"].isin(selected_specs)
].copy()

##############################################
# PHẦN 3: XỬ LÝ DỮ LIỆU CHO BIỂU ĐỒ
##############################################

# Hàm chuyển đổi "Sample Name" sang giá trị thời gian tính bằng tháng.
def parse_sample_name(sample_name):
    """
    Chuyển đổi Sample Name theo format:
    - "01D-RO": 01 ngày => chuyển thành 1/30 tháng
    - "02W-RO": 02 tuần => chuyển thành 2/4.345 tháng (4.345 ≈ số tuần trung bình trong 1 tháng)
    - "01M-RO": 01 tháng => giữ nguyên số tháng
    """
    try:
        # Lấy phần trước dấu '-' (ví dụ: "01D")
        part = sample_name.split('-')[0]
        # Tách số và đơn vị
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

# Kiểm tra cột "Sample Name"
if "Sample Name" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Sample Name' trong dữ liệu.")
    st.stop()

# Tạo cột mới "Time_Months" từ "Sample Name"
filtered_data["Time_Months"] = filtered_data["Sample Name"].apply(parse_sample_name)

# (Tùy chọn) Tạo cột "Lot_ID" từ 6 ký tự đầu của cột "Lot number" để nhận diện mẫu sản xuất
if "Lot number" in filtered_data.columns:
    filtered_data["Lot_ID"] = filtered_data["Lot number"].astype(str).str[:6]
else:
    st.warning("Không tìm thấy cột 'Lot number' trong dữ liệu.")

# Lọc dữ liệu cho hai nhóm chỉ tiêu:
# - Nhóm cảm quan: Test bắt đầu bằng "CQ"
# - Nhóm hóa lý: Test bắt đầu bằng "HL"
if "Test" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Test' trong dữ liệu.")
    st.stop()

# Ép kiểu thành chuỗi và lọc
sensory_data = filtered_data[ filtered_data["Test"].astype(str).str.startswith("CQ") ].copy()
chemical_data = filtered_data[ filtered_data["Test"].astype(str).str.startswith("HL") ].copy()

# Nhóm dữ liệu theo "Test description" và "Time_Months", lấy trung bình "Actual result"
# Lưu ý: Đảm bảo cột "Actual result" tồn tại và có kiểu số
for df in [sensory_data, chemical_data]:
    if "Actual result" in df.columns:
        df["Actual result"] = pd.to_numeric(df["Actual result"], errors="coerce")
    else:
        st.error("Không tìm thấy cột 'Actual result' trong dữ liệu.")
        st.stop()

sensory_grouped = sensory_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})
chemical_grouped = chemical_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})

##############################################
# PHẦN 4: VẼ BIỂU ĐỒ VỚI PLOTLY
##############################################

st.write("## Biểu đồ xu hướng")

# Biểu đồ xu hướng CẢM QUAN
if not sensory_grouped.empty:
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        title="Biểu đồ xu hướng CẢM QUAN",
        labels={"Time_Months": "Thời gian (tháng)", "Actual result": "Kết quả Actual"}
    )
    st.plotly_chart(fig_sensory, use_container_width=True)
else:
    st.info("Không có dữ liệu cảm quan để hiển thị biểu đồ.")

# Biểu đồ xu hướng HÓA LÝ
if not chemical_grouped.empty:
    fig_chemical = px.line(
        chemical_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        title="Biểu đồ xu hướng HÓA LÝ",
        labels={"Time_Months": "Thời gian (tháng)", "Actual result": "Kết quả Actual"}
    )
    st.plotly_chart(fig_chemical, use_container_width=True)
else:
    st.info("Không có dữ liệu hóa lý để hiển thị biểu đồ.")
