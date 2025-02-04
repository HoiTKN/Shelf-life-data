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
    Load dữ liệu từ Google Sheet sử dụng thông tin trong st.secrets.
    Đảm bảo rằng bạn đã cấu hình key "gcp_service_account" và "sheet" trong file secrets.
    """
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Nếu thiếu key, hiển thị thông báo lỗi rõ ràng
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except KeyError:
        st.error(
            "Thiếu key 'gcp_service_account' trong st.secrets. "
            "Vui lòng thêm nó vào file .streamlit/secrets.toml hoặc trong cài đặt app trên Streamlit Cloud.\n\n"
            "Xem thêm: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management"
        )
        return pd.DataFrame()
    
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    
    try:
        sheet_url = st.secrets["sheet"]["url"]
    except KeyError:
        st.error("Thiếu key 'sheet' trong st.secrets. Vui lòng thêm nó.")
        return pd.DataFrame()
    
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    df = get_as_dataframe(worksheet, evaluate_formulas=True, header=0)
    df = df.dropna(how="all")
    return df

# Load dữ liệu (không hiển thị bảng dữ liệu gốc)
data = load_data()
if data.empty:
    st.stop()

##############################################
# PHẦN 2: BỘ LỌC DỮ LIỆU (Sidebar)
##############################################

st.sidebar.header("Bộ lọc dữ liệu")

# --- Lọc theo ngành hàng ---
categories = data["Category description"].dropna().unique().tolist()
selected_categories = st.sidebar.multiselect(
    "Chọn ngành hàng:",
    options=categories,
    default=[]
)
if not selected_categories:
    selected_categories_filter = categories
else:
    selected_categories_filter = selected_categories

# --- Lọc theo sản phẩm ---
data_by_category = data[data["Category description"].isin(selected_categories_filter)]
specs_in_category = data_by_category["Spec description"].dropna().unique().tolist()
selected_specs = st.sidebar.multiselect(
    "Chọn sản phẩm:",
    options=specs_in_category,
    default=[]
)
if not selected_specs:
    selected_specs_filter = specs_in_category
else:
    selected_specs_filter = selected_specs

# --- Bộ lọc thêm cho Test description (cho biểu đồ thống kê) ---
test_descriptions = data["Test description"].dropna().unique().tolist()
selected_tests = st.sidebar.multiselect(
    "Chọn chỉ tiêu (Test description) cho thống kê:",
    options=test_descriptions,
    default=[]
)
if not selected_tests:
    selected_tests_filter = test_descriptions
else:
    selected_tests_filter = selected_tests

# Lọc dữ liệu cuối cùng theo ngành hàng và sản phẩm
filtered_data = data[
    data["Category description"].isin(selected_categories_filter) &
    data["Spec description"].isin(selected_specs_filter)
].copy()

##############################################
# PHẦN 3: XỬ LÝ DỮ LIỆU CHO BIỂU ĐỒ
##############################################

def parse_sample_name(sample_name):
    """
    Chuyển đổi chuỗi Sample Name:
      - "01D-RO": số ngày -> tháng = số ngày / 30
      - "02W-RO": số tuần -> tháng = số tuần / 4.345
      - "01M-RO": số tháng, giữ nguyên
    """
    try:
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
    except Exception:
        return None

if "Sample Name" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Sample Name' trong dữ liệu.")
    st.stop()

filtered_data["Time_Months"] = filtered_data["Sample Name"].apply(parse_sample_name)

if "Lot number" in filtered_data.columns:
    filtered_data["Lot_ID"] = filtered_data["Lot number"].astype(str).str[:6]
else:
    st.warning("Không tìm thấy cột 'Lot number' trong dữ liệu.")

if "Test" not in filtered_data.columns:
    st.error("Không tìm thấy cột 'Test' trong dữ liệu.")
    st.stop()

# Tách dữ liệu theo chỉ tiêu cho line chart
sensory_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("CQ")].copy()
chemical_data = filtered_data[filtered_data["Test"].astype(str).str.startswith("HL")].copy()

for df in [sensory_data, chemical_data]:
    if "Actual result" in df.columns:
        df["Actual result"] = pd.to_numeric(df["Actual result"], errors="coerce")
    else:
        st.error("Không tìm thấy cột 'Actual result' trong dữ liệu.")
        st.stop()

sensory_grouped = sensory_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})
chemical_grouped = chemical_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})

# Dữ liệu cho biểu đồ thống kê (Insight): lọc theo Test description đã chọn
insight_data = filtered_data[filtered_data["Test description"].isin(selected_tests_filter)].copy()
if "Actual result" in insight_data.columns:
    insight_data["Actual result"] = pd.to_numeric(insight_data["Actual result"], errors="coerce")
else:
    st.error("Không tìm thấy cột 'Actual result' trong dữ liệu.")
    st.stop()

##############################################
# PHẦN 4: VẼ BIỂU ĐỒ VỚI PLOTLY
##############################################

st.markdown("## Biểu đồ xu hướng")
chart_template = "plotly_white"

# Biểu đồ xu hướng cảm quan (Line Chart)
if not sensory_grouped.empty:
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template=chart_template,
        title="Biểu đồ xu hướng CẢM QUAN"
    )
    fig_sensory.update_layout(
        xaxis_title="Thời gian (tháng)",
        yaxis_title="Kết quả Actual",
        legend_title="Chỉ tiêu",
        hovermode="x unified"
    )
    st.plotly_chart(fig_sensory, use_container_width=True)
else:
    st.info("Không có dữ liệu cảm quan để hiển thị biểu đồ.")

# Biểu đồ xu hướng hóa lý (Line Chart)
if not chemical_grouped.empty:
    fig_chemical = px.line(
        chemical_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template=chart_template,
        title="Biểu đồ xu hướng HÓA LÝ"
    )
    fig_chemical.update_layout(
        xaxis_title="Thời gian (tháng)",
        yaxis_title="Kết quả Actual",
        legend_title="Chỉ tiêu",
        hovermode="x unified"
    )
    st.plotly_chart(fig_chemical, use_container_width=True)
else:
    st.info("Không có dữ liệu hóa lý để hiển thị biểu đồ.")

##############################################
# PHẦN 5: BIỂU ĐỒ THỐNG KÊ BỔ SUNG (Insight)
##############################################

st.markdown("## Phân tích thống kê thêm")

# 1. Box Plot: Phân bố kết quả kiểm theo Test description (Insight)
if not insight_data.empty and "Test description" in insight_data.columns:
    fig_box = px.box(
        insight_data,
        x="Test description",
        y="Actual result",
        color="Test description",
        template=chart_template,
        title="Phân bố kết quả kiểm theo chỉ tiêu"
    )
    fig_box.update_layout(xaxis_title="Chỉ tiêu", yaxis_title="Kết quả Actual")
    st.plotly_chart(fig_box, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Box Plot.")

# 2. Histogram: Phân bố tổng thể kết quả kiểm theo Test description
if not insight_data.empty:
    fig_hist = px.histogram(
        insight_data,
        x="Actual result",
        color="Test description",
        barmode="overlay",
        template=chart_template,
        title="Phân bố tổng thể kết quả kiểm theo chỉ tiêu"
    )
    fig_hist.update_layout(xaxis_title="Kết quả Actual", yaxis_title="Số lượng mẫu")
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Histogram.")

# 3. Scatter Plot với trendline: Mối quan hệ giữa thời gian lưu và kết quả kiểm
if not insight_data.empty and "Time_Months" in insight_data.columns:
    fig_scatter = px.scatter(
        insight_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        template=chart_template,
        title="Mối quan hệ giữa thời gian lưu và kết quả kiểm (Scatter Plot)",
        trendline="ols"
    )
    fig_scatter.update_layout(xaxis_title="Thời gian (tháng)", yaxis_title="Kết quả Actual")
    st.plotly_chart(fig_scatter, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Scatter Plot.")
