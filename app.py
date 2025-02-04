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
    Đảm bảo rằng bạn đã cấu hình key "gcp_service_account" và "sheet" trong file secrets.
    """
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(credentials)
    sheet_url = st.secrets["sheet"]["url"]
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    df = get_as_dataframe(worksheet, evaluate_formulas=True, header=0)
    df = df.dropna(how="all")
    return df

# Load dữ liệu từ Google Sheet
data = load_data()
st.write("### Dữ liệu từ Google Sheet (5 dòng đầu tiên)", data.head())

##############################################
# PHẦN 2: BỘ LỌC DỮ LIỆU (Sidebar)
##############################################

st.sidebar.header("Bộ lọc dữ liệu")

# --- Bước 1: Lọc theo ngành hàng ---
# Lấy danh sách các ngành hàng từ cột "Category description"
categories = data["Category description"].dropna().unique().tolist()
# Mặc định chỉ chọn "Fish Sauces" (điều chỉnh nếu dữ liệu của bạn có tên khác)
selected_categories = st.sidebar.multiselect(
    "Chọn ngành hàng:",
    options=categories,
    default=["Fish Sauces"]
)

# --- Bước 2: Lọc theo sản phẩm ---
# Lấy dữ liệu chỉ chứa các dòng thuộc ngành hàng đã chọn
data_by_category = data[data["Category description"].isin(selected_categories)]
# Lấy danh sách các sản phẩm (Spec description) thuộc ngành hàng đã chọn
specs_in_category = data_by_category["Spec description"].dropna().unique().tolist()
# Mặc định chỉ chọn "Nước mắm Nam ngư" (điều chỉnh nếu dữ liệu của bạn có tên khác)
selected_specs = st.sidebar.multiselect(
    "Chọn sản phẩm:",
    options=specs_in_category,
    default=["Nước mắm Nam ngư"]
)

# Lọc dữ liệu cuối cùng dựa trên lựa chọn ngành hàng và sản phẩm
filtered_data = data[
    data["Category description"].isin(selected_categories) &
    data["Spec description"].isin(selected_specs)
].copy()

##############################################
# PHẦN 3: XỬ LÝ DỮ LIỆU CHO BIỂU ĐỒ
##############################################

# Hàm chuyển đổi Sample Name sang giá trị thời gian tính theo tháng.
def parse_sample_name(sample_name):
    """
    Chuyển đổi chuỗi Sample Name theo định dạng:
      - "01D-RO": số ngày, chuyển thành tháng = số ngày/30
      - "02W-RO": số tuần, chuyển thành tháng = số tuần/4.345
      - "01M-RO": số tháng, giữ nguyên số đó
    """
    try:
        part = sample_name.split('-')[0]  # Lấy phần trước dấu "-"
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

if "Sample Name" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Sample Name' trong dữ liệu.")
    st.stop()

# Tạo cột mới "Time_Months" làm trục x cho biểu đồ
filtered_data["Time_Months"] = filtered_data["Sample Name"].apply(parse_sample_name)

# (Tùy chọn) Tạo cột "Lot_ID" chỉ lấy 6 ký tự đầu của "Lot number" để nhận diện mẫu
if "Lot number" in filtered_data.columns:
    filtered_data["Lot_ID"] = filtered_data["Lot number"].astype(str).str[:6]
else:
    st.warning("Không tìm thấy cột 'Lot number' trong dữ liệu.")

# Kiểm tra cột "Test" để phân chia dữ liệu
if "Test" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Test' trong dữ liệu.")
    st.stop()

# Tách dữ liệu theo chỉ tiêu:
# - Dữ liệu cảm quan: các dòng có giá trị trong cột Test bắt đầu bằng "CQ"
# - Dữ liệu hóa lý: các dòng có giá trị trong cột Test bắt đầu bằng "HL"
sensory_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("CQ")].copy()
chemical_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("HL")].copy()

# Chuyển đổi cột "Actual result" sang kiểu số
for df in [sensory_data, chemical_data]:
    if "Actual result" in df.columns:
        df["Actual result"] = pd.to_numeric(df["Actual result"], errors="coerce")
    else:
        st.error("Không tìm thấy cột 'Actual result' trong dữ liệu.")
        st.stop()

# Nhóm dữ liệu theo "Test description" và "Time_Months", tính trung bình của "Actual result"
sensory_grouped = sensory_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})
chemical_grouped = chemical_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})

##############################################
# PHẦN 4: VẼ BIỂU ĐỒ VỚI PLOTLY
##############################################

st.write("## Biểu đồ xu hướng")

# Biểu đồ xu hướng cảm quan
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

# Biểu đồ xu hướng hóa lý
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
