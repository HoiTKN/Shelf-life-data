import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import get_as_dataframe
import numpy as np

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

# Thêm cấu hình phân tích
st.sidebar.markdown("---")
st.sidebar.header("Cấu hình phân tích")

# Thêm thanh trượt cho ngưỡng giới hạn cảm quan
threshold_value = st.sidebar.slider(
    "Ngưỡng giới hạn cảm quan:",
    min_value=4.0,
    max_value=9.0,
    value=6.5,
    step=0.1,
    help="Giá trị cảm quan vượt qua ngưỡng này được coi là không đạt"
)

# Thêm tùy chọn hiển thị dự báo
show_projection = st.sidebar.checkbox("Hiển thị dự báo thời hạn sử dụng", value=True)

# Thêm tùy chọn chế độ hiển thị
display_mode = st.sidebar.radio(
    "Chế độ hiển thị:",
    options=["Standard", "Professional", "Compact"],
    index=0
)

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

# Thêm hàm dự báo thời điểm đạt ngưỡng giới hạn
def calculate_projections(df, test_col, time_col, value_col, threshold=6.5):
    """
    Dự báo thời điểm đạt ngưỡng giới hạn cho từng chỉ tiêu
    
    Args:
        df: DataFrame với dữ liệu
        test_col: Tên cột chứa tên chỉ tiêu 
        time_col: Tên cột chứa thời gian (tháng)
        value_col: Tên cột chứa giá trị cảm quan
        threshold: Ngưỡng giới hạn
        
    Returns:
        dict: Dự báo cho mỗi chỉ tiêu
    """
    projections = {}
    
    # Nhóm dữ liệu theo chỉ tiêu
    for test, group in df.groupby(test_col):
        if len(group) < 2:
            projections[test] = "Không đủ dữ liệu"
            continue
            
        # Sắp xếp theo thời gian và lấy 3 điểm gần nhất
        group = group.sort_values(time_col)
        recent_points = group.tail(3)
        
        if len(recent_points) < 2:
            projections[test] = "Không đủ dữ liệu"
            continue
            
        # Tính tốc độ thay đổi
        x_values = recent_points[time_col].values
        y_values = recent_points[value_col].values
        
        # Tính hệ số góc của đường thẳng (tốc độ thay đổi)
        if len(set(x_values)) < 2:
            projections[test] = "Không đủ dữ liệu"
            continue
            
        try:
            # Sử dụng numpy polyfit để tìm đường thẳng tốt nhất
            slope, intercept = np.polyfit(x_values, y_values, 1)
            
            # Điểm cuối cùng
            last_x = x_values[-1]
            last_y = y_values[-1]
            
            # Nếu đường thẳng đi xuống hoặc ngang
            if slope <= 0:
                projections[test] = "Không xác định (xu hướng đi ngang hoặc giảm)"
            else:
                # Tính thời điểm đạt ngưỡng (x = (threshold - intercept) / slope)
                projected_month = (threshold - intercept) / slope
                
                # Nếu đã vượt ngưỡng
                if last_y >= threshold:
                    projections[test] = "Đã vượt ngưỡng"
                else:
                    projections[test] = round(projected_month, 1)
        except:
            projections[test] = "Lỗi khi tính toán"
    
    return projections

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

# Biểu đồ xu hướng cảm quan (Line Chart) với ngưỡng giới hạn
if not sensory_grouped.empty:
    st.markdown("### Xu hướng cảm quan theo thời gian lưu")
    
    # Tính dự báo nếu được yêu cầu
    if show_projection:
        projections = calculate_projections(
            sensory_grouped, 
            "Test description", 
            "Time_Months", 
            "Actual result", 
            threshold_value
        )
        
        # Hiển thị bảng dự báo
        projection_data = []
        for test, value in projections.items():
            latest_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months").iloc[-1]
            projection_data.append({
                "Chỉ tiêu": test,
                "Giá trị hiện tại": f"{latest_data['Actual result']:.2f}",
                "Dự báo tháng đạt ngưỡng": value
            })
        
        projection_df = pd.DataFrame(projection_data)
        
        # Tính thời hạn sử dụng dự kiến
        shelf_life_values = []
        for val in projections.values():
            try:
                if isinstance(val, (int, float)):
                    shelf_life_values.append(val)
            except:
                pass
        
        min_shelf_life = min(shelf_life_values) if shelf_life_values else "Không xác định"
        
        # Hiển thị thông tin thời hạn sử dụng
        col1, col2 = st.columns(2)
        with col1:
            if isinstance(min_shelf_life, (int, float)):
                st.info(f"💡 Dự kiến thời hạn sử dụng: **{min_shelf_life:.1f} tháng**")
            else:
                st.info(f"💡 Dự kiến thời hạn sử dụng: **{min_shelf_life}**")
        
        with col2:
            st.info(f"⚠️ Ngưỡng giới hạn cảm quan: **{threshold_value}**")
    
    # Tạo biểu đồ xu hướng
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template="plotly_white",
        title="Xu hướng CẢM QUAN theo thời gian lưu"
    )
    
    # Thêm đường ngưỡng giới hạn
    if not sensory_grouped["Time_Months"].empty:
        x_min = sensory_grouped["Time_Months"].min()
        x_max = sensory_grouped["Time_Months"].max()
        x_range = max(1, x_max - x_min)  # Avoid division by zero
        
        fig_sensory.add_shape(
            type="line",
            x0=x_min,
            x1=x_max + (x_range * 0.2),  # Kéo dài sang phải thêm 20%
            y0=threshold_value,
            y1=threshold_value,
            line=dict(color="red", width=2, dash="dash"),
        )
        
        # Thêm nhãn cho đường ngưỡng
        fig_sensory.add_annotation(
            x=x_max + (x_range * 0.1),
            y=threshold_value,
            text=f"Ngưỡng giới hạn: {threshold_value}",
            showarrow=False,
            font=dict(color="red", size=12),
        )
    
    # Thêm dự báo vào biểu đồ nếu được yêu cầu
    if show_projection and not sensory_grouped.empty:
        # Cho mỗi chỉ tiêu, thêm đường dự báo
        for test, proj_month in projections.items():
            if isinstance(proj_month, (int, float)):
                # Lấy điểm cuối cùng của chỉ tiêu
                test_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months")
                if len(test_data) > 0:
                    last_point = test_data.iloc[-1]
                    last_month = last_point["Time_Months"]
                    last_value = last_point["Actual result"]
                    
                    # Thêm đường dự báo
                    color_index = list(sensory_grouped["Test description"].unique()).index(test) % len(px.colors.qualitative.Plotly)
                    line_color = px.colors.qualitative.Plotly[color_index]
                    
                    fig_sensory.add_shape(
                        type="line",
                        x0=last_month,
                        x1=proj_month,
                        y0=last_value,
                        y1=threshold_value,
                        line=dict(
                            color=line_color, 
                            width=1, 
                            dash="dot"
                        ),
                    )
                    
                    # Thêm điểm dự báo
                    fig_sensory.add_trace(
                        go.Scatter(
                            x=[proj_month],
                            y=[threshold_value],
                            mode="markers",
                            marker=dict(
                                symbol="star",
                                size=10,
                                color=line_color,
                            ),
                            name=f"{test} (dự báo tháng {proj_month})",
                            showlegend=True
                        )
                    )
    
    # Cấu hình layout dựa trên chế độ hiển thị
    if display_mode == "Professional":
        fig_sensory.update_layout(
            xaxis_title="Thời gian (tháng)",
            yaxis_title="Giá trị cảm quan",
            legend_title="Chỉ tiêu cảm quan",
            hovermode="x unified",
            font=dict(family="Arial", size=12),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=40, r=40, t=80, b=40),
            plot_bgcolor="white",
            title=dict(font=dict(size=20, color="#333333"), x=0.5, xanchor="center")
        )
    elif display_mode == "Compact":
        fig_sensory.update_layout(
            xaxis_title="Tháng",
            yaxis_title="Giá trị",
            showlegend=False,
            hovermode="closest",
            margin=dict(l=20, r=20, t=40, b=20),
            height=300
        )
    else:  # Standard
        fig_sensory.update_layout(
            xaxis_title="Thời gian (tháng)",
            yaxis_title="Kết quả Actual",
            legend_title="Chỉ tiêu",
            hovermode="x unified"
        )
    
    # Hiển thị biểu đồ
    st.plotly_chart(fig_sensory, use_container_width=True)
    
    # Hiển thị bảng dự báo nếu được yêu cầu
    if show_projection:
        st.markdown("#### Dự báo thời điểm đạt ngưỡng giới hạn")
        st.dataframe(projection_df, use_container_width=True, hide_index=True)
        
        # Hiển thị nhận xét phân tích
        st.markdown("#### Nhận xét phân tích")
        
        # Tìm chỉ tiêu quyết định đến hạn sử dụng
        critical_attr = None
        critical_month = None
        
        for test, value in projections.items():
            if isinstance(value, (int, float)):
                if critical_month is None or value < critical_month:
                    critical_month = value
                    critical_attr = test
        
        if critical_attr:
            st.info(f"""
            💡 **Đánh giá chung:**
            
            - Chỉ tiêu quyết định đến hạn sử dụng: **{critical_attr}** (dự kiến đạt ngưỡng vào tháng {critical_month:.1f})
            - Các chỉ tiêu còn lại có thời hạn dài hơn, cho thấy **{critical_attr}** là chỉ tiêu hạn chế chất lượng sản phẩm
            - Khuyến nghị: Tập trung cải thiện độ ổn định của chỉ tiêu **{critical_attr}**
            """)
else:
    st.info("Không có dữ liệu cảm quan để hiển thị biểu đồ.")

# Biểu đồ xu hướng hóa lý (Line Chart)
if not chemical_grouped.empty:
    st.markdown("### Xu hướng hóa lý theo thời gian lưu")
    
    fig_chemical = px.line(
        chemical_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template="plotly_white",
        title="Xu hướng HÓA LÝ theo thời gian lưu"
    )
    
    # Cấu hình layout dựa trên chế độ hiển thị
    if display_mode == "Professional":
        fig_chemical.update_layout(
            xaxis_title="Thời gian (tháng)",
            yaxis_title="Giá trị hóa lý",
            legend_title="Chỉ tiêu hóa lý",
            hovermode="x unified",
            font=dict(family="Arial", size=12),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=40, r=40, t=80, b=40),
            plot_bgcolor="white",
            title=dict(font=dict(size=20, color="#333333"), x=0.5, xanchor="center")
        )
    elif display_mode == "Compact":
        fig_chemical.update_layout(
            xaxis_title="Tháng",
            yaxis_title="Giá trị",
            showlegend=False,
            hovermode="closest",
            margin=dict(l=20, r=20, t=40, b=20),
            height=300
        )
    else:  # Standard
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
        template="plotly_white",
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
        template="plotly_white",
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
        template="plotly_white",
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
        template="plotly_white",
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
        template="plotly_white",
        title="Xu hướng trung bình kết quả kiểm theo tháng lưu"
    )
    st.plotly_chart(fig_line, use_container_width=True)
else:
    st.info("Không đủ dữ liệu để vẽ biểu đồ xu hướng trung bình.")

##############################################
# PHẦN 5: THÊM PHÂN TÍCH TỐC ĐỘ BIẾN ĐỔI
##############################################

# Phân tích tốc độ biến đổi cho chỉ tiêu cảm quan
if not sensory_grouped.empty and show_projection:
    st.markdown("## Phân tích tốc độ biến đổi cảm quan")
    
    # Tính tốc độ thay đổi cho mỗi chỉ tiêu
    change_rates = []
    
    for test, group in sensory_grouped.groupby("Test description"):
        if len(group) >= 3:
            # Sắp xếp theo thời gian
            group = group.sort_values("Time_Months")
            
            # Lấy 3 điểm gần nhất
            recent = group.tail(3)
            
            # Tính tốc độ thay đổi
            first_month = recent["Time_Months"].iloc[0]
            last_month = recent["Time_Months"].iloc[-1]
            first_value = recent["Actual result"].iloc[0]
            last_value = recent["Actual result"].iloc[-1]
            
            if last_month > first_month:
                rate = (last_value - first_value) / (last_month - first_month)
                
                change_rates.append({
                    "Chỉ tiêu": test,
                    "Tốc độ thay đổi": rate
                })
    
    if change_rates:
        # Tạo DataFrame
        change_df = pd.DataFrame(change_rates)
        
        # Sắp xếp theo tốc độ thay đổi (giảm dần)
        change_df = change_df.sort_values("Tốc độ thay đổi", ascending=False)
        
        # Vẽ biểu đồ thanh ngang
        fig_change = px.bar(
            change_df,
            y="Chỉ tiêu",
            x="Tốc độ thay đổi",
            orientation="h",
            title="Tốc độ thay đổi của các chỉ tiêu cảm quan (đơn vị/tháng)",
            template="plotly_white",
            text_auto='.2f'
        )
        
        fig_change.update_layout(
            xaxis_title="Tốc độ thay đổi (đơn vị/tháng)",
            yaxis_title="",
            height=400
        )
        
        # Hiển thị biểu đồ
        st.plotly_chart(fig_change, use_container_width=True)
        
        # Hiển thị nhận xét về tốc độ thay đổi
        if len(change_df) > 0:
            fastest = change_df.iloc[0]
            slowest = change_df.iloc[-1]
            
            st.info(f"""
            💡 **Phân tích tốc độ biến đổi cảm quan:**
            
            - Chỉ tiêu **{fastest["Chỉ tiêu"]}** có tốc độ thay đổi nhanh nhất: {fastest["Tốc độ thay đổi"]:.2f} đơn vị/tháng
            - Chỉ tiêu **{slowest["Chỉ tiêu"]}** có tốc độ thay đổi chậm nhất: {slowest["Tốc độ thay đổi"]:.2f} đơn vị/tháng
            - Tất cả các chỉ tiêu đều có xu hướng thay đổi theo thời gian, với tốc độ khác nhau
            """)
