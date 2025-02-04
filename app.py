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
    Yêu cầu có key [gcp_service_account] và [sheet] trong secrets.
    """
    scope = [
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except KeyError:
        st.error(
            "Thiếu key 'gcp_service_account' trong st.secrets. "
            "Vui lòng thêm nó vào file .streamlit/secrets.toml hoặc trong cài đặt app trên Streamlit Cloud."
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

# Load dữ liệu từ Google Sheet
data = load_data()
if data.empty:
    st.stop()

##############################################
# PHẦN 2: TẠO BỘ LỌC TRÊN SIDEBAR
##############################################

st.sidebar.header("Bộ lọc dữ liệu")

# 1. Lọc theo ngành hàng (Category description)
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

# 2. Lọc theo sản phẩm (Spec description) dựa trên ngành hàng đã chọn
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

# 3. Lọc theo chỉ tiêu (Test description) dựa trên sản phẩm đã lọc
data_filtered = data_by_category[data_by_category["Spec description"].isin(selected_specs_filter)]
test_descriptions = data_filtered["Test description"].dropna().unique().tolist()
selected_tests = st.sidebar.multiselect(
    "Chọn chỉ tiêu (Test description) cho thống kê:",
    options=test_descriptions,
    default=[]
)
if not selected_tests:
    selected_tests_filter = test_descriptions
else:
    selected_tests_filter = selected_tests

##############################################
# PHẦN 3: XỬ LÝ DỮ LIỆU CHO BIỂU ĐỒ
##############################################

# Tính cột Time_Months dựa trên cột Sample Name (ví dụ: "01D-RO", "02W-RO", "01M-RO")
def parse_sample_name(sample_name):
    """
    Chuyển đổi chuỗi Sample Name:
      - Nếu kết thúc bằng D: tháng = số ngày / 30
      - Nếu kết thúc bằng W: tháng = số tuần / 4.345
      - Nếu kết thúc bằng M: giữ nguyên số tháng
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

if "Sample Name" not in data_filtered.columns:
    st.error("Không tìm thấy cột 'Sample Name' trong dữ liệu.")
    st.stop()

data_filtered["Time_Months"] = data_filtered["Sample Name"].apply(parse_sample_name)

# Lọc dữ liệu theo chỉ tiêu đã chọn (cho các biểu đồ Insight)
insight_data = data_filtered[data_filtered["Test description"].isin(selected_tests_filter)].copy()
if "Actual result" in insight_data.columns:
    insight_data["Actual result"] = pd.to_numeric(insight_data["Actual result"], errors="coerce")
else:
    st.error("Không tìm thấy cột 'Actual result' trong dữ liệu.")
    st.stop()

# Tách dữ liệu cho biểu đồ xu hướng dựa trên Test (Cảm quan: CQ..., Hóa lý: HL...)
sensory_data = data_filtered[data_filtered["Test"].astype(str).str.startswith("CQ")].copy()
chemical_data = data_filtered[data_filtered["Test"].astype(str).str.startswith("HL")].copy()

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
        title="Xu hướng CẢM QUAN theo thời gian lưu"
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
        title="Xu hướng HÓA LÝ theo thời gian lưu"
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

st.markdown("## Phân tích thống kê thêm (Insight)")

# 1. Box Plot: Phân bố kết quả kiểm theo tháng lưu theo từng chỉ tiêu
if not insight_data.empty:
    fig_box = px.box(
        insight_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        template=chart_template,
        title="Box Plot: Phân bố kết quả kiểm theo tháng lưu"
    )
    fig_box.update_layout(xaxis_title="Thời gian (tháng)", yaxis_title="Kết quả Actual")
    st.plotly_chart(fig_box, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Box Plot.")

# 2. Histogram: Phân bố kết quả kiểm theo tháng lưu, hiển thị theo từng chỉ tiêu
if not insight_data.empty:
    fig_hist = px.histogram(
        insight_data,
        x="Time_Months",
        color="Test description",
        facet_col="Test description",
        template=chart_template,
        title="Histogram: Phân bố kết quả kiểm theo tháng lưu (theo chỉ tiêu)"
    )
    fig_hist.update_layout(xaxis_title="Thời gian (tháng)", yaxis_title="Số lượng mẫu")
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Histogram.")

# 3. Scatter Plot với trendline: Mối quan hệ giữa thời gian lưu và kết quả kiểm
if not insight_data.empty and "Time_Months" in insight_data.columns:
    # Nếu bạn không cần trendline, có thể bỏ trendline="ols" để tránh yêu cầu statsmodels
    fig_scatter = px.scatter(
        insight_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        template=chart_template,
        title="Scatter Plot: Mối quan hệ giữa thời gian lưu và kết quả kiểm",
        trendline="ols"
    )
    fig_scatter.update_layout(xaxis_title="Thời gian (tháng)", yaxis_title="Kết quả Actual")
    st.plotly_chart(fig_scatter, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Scatter Plot.")

# 4. (Đề xuất thêm) Violin Plot: Phân bố kết quả kiểm theo tháng lưu
if not insight_data.empty:
    fig_violin = px.violin(
        insight_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        box=True,
        points="all",
        template=chart_template,
        title="Violin Plot: Phân bố kết quả kiểm theo tháng lưu"
    )
    st.plotly_chart(fig_violin, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ Violin Plot.")

# 5. (Đề xuất thêm) Line Chart trung bình kết quả kiểm theo tháng lưu cho từng chỉ tiêu
if not insight_data.empty:
    trend_data = insight_data.groupby(["Test description", "Time_Months"], as_index=False).agg({"Actual result": "mean"})
    fig_line = px.line(
        trend_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template=chart_template,
        title="Xu hướng trung bình kết quả kiểm theo tháng lưu"
    )
    st.plotly_chart(fig_line, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ biểu đồ xu hướng trung bình.")
