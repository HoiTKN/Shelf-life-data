import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import get_as_dataframe
import numpy as np
import statsmodels.api as sm

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

##############################################
# PHẦN 2: TẠO BỘ LỌC TRÊN SIDEBAR
##############################################

st.sidebar.header("Bộ lọc dữ liệu")

# Cấu hình phân tích
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

# Thêm tùy chọn chế độ hiển thị
# And replace with this simple constant:
display_mode = "Standard" 

# Load dữ liệu từ Google Sheet
data = load_data()
if data.empty:
    st.stop()

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

# Hàm dự báo thời điểm đạt ngưỡng giới hạn
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
        except Exception as e:
            projections[test] = "Lỗi khi tính toán"
    
    return projections

def generate_qa_summary(sensory_grouped, threshold_value):
    """Generate a QA summary dashboard with key metrics"""
    if sensory_grouped.empty:
        return None
    
    # Calculate projections for shelf life estimation
    projections = calculate_projections(
        sensory_grouped, 
        "Test description", 
        "Time_Months", 
        "Actual result", 
        threshold_value
    )
    
    # Extract shelf life values (numbers only)
    shelf_life_values = []
    for val in projections.values():
        try:
            if isinstance(val, (int, float)):
                shelf_life_values.append(val)
        except Exception:
            pass
    
    min_shelf_life = min(shelf_life_values) if shelf_life_values else "Không xác định"
    
    # Find attribute closest to threshold
    latest_values = {}
    for test in sensory_grouped['Test description'].unique():
        test_data = sensory_grouped[sensory_grouped['Test description'] == test]
        if not test_data.empty:
            latest = test_data.sort_values('Time_Months').iloc[-1]
            latest_values[test] = latest['Actual result']
    
    closest_attr = None
    min_distance = float('inf')
    for attr, value in latest_values.items():
        if value < threshold_value:  # Only consider values below threshold
            distance = threshold_value - value
            if distance < min_distance:
                min_distance = distance
                closest_attr = attr
    
    # Calculate rate of change for all attributes
    change_rates = {}
    for test, group in sensory_grouped.groupby("Test description"):
        if len(group) >= 3:
            group = group.sort_values("Time_Months")
            recent = group.tail(3)
            first_month = recent["Time_Months"].iloc[0]
            last_month = recent["Time_Months"].iloc[-1]
            first_value = recent["Actual result"].iloc[0]
            last_value = recent["Actual result"].iloc[-1]
            
            if last_month > first_month:
                rate = (last_value - first_value) / (last_month - first_month)
                change_rates[test] = rate
    
    fastest_attr = max(change_rates.items(), key=lambda x: x[1])[0] if change_rates else None
    
    # Create summary metrics
    return {
        'min_shelf_life': min_shelf_life,
        'closest_attr': closest_attr,
        'closest_attr_value': latest_values.get(closest_attr, None) if closest_attr else None,
        'fastest_attr': fastest_attr,
        'change_rates': change_rates,
        'projections': projections,
        'latest_values': latest_values
    }

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
# PHẦN 4: HIỂN THỊ QA DASHBOARD
##############################################
def create_improved_dashboard(sensory_grouped, threshold_value, qa_summary):
    
    st.markdown("## Báo cáo Shelf-Life MMB")
    
    if not sensory_grouped.empty:
        # Create status indicator based on shelf life projection
        if isinstance(qa_summary['min_shelf_life'], (int, float)):
            current_month = max(sensory_grouped["Time_Months"])
            remaining_months = qa_summary['min_shelf_life'] - current_month
            
            if remaining_months <= 1:
                status_emoji = "🔴"
                status_text = "Cảnh báo"
                status_color = "#ffebee"  # light red
                status_border = "#f44336"  # red
                status_detail = f"Sản phẩm dự kiến đạt ngưỡng trong {remaining_months:.1f} tháng"
            elif remaining_months <= 3:
                status_emoji = "🟠"
                status_text = "Cần chú ý"
                status_color = "#fff8e1"  # light amber
                status_border = "#ffa000"  # amber
                status_detail = f"Cần theo dõi sát trong {remaining_months:.1f} tháng tới"
            else:
                status_emoji = "🟢"
                status_text = "Ổn định"
                status_color = "#e8f5e9"  # light green
                status_border = "#4caf50"  # green
                status_detail = f"Chất lượng dự báo ổn định trong {remaining_months:.1f} tháng tới"
        else:
            status_emoji = "⚪"
            status_text = "Chưa xác định"
            status_color = "#f5f5f5"  # light grey
            status_border = "#9e9e9e"  # grey
            status_detail = "Không đủ dữ liệu để đánh giá"
        
        # Main status card
        st.markdown(f"""
        <div style="padding:15px; background-color:{status_color}; border-left:5px solid {status_border}; 
                    margin-bottom:20px; border-radius:4px;">
            <div style="display:flex; align-items:center;">
                <span style="font-size:2rem; margin-right:10px;">{status_emoji}</span>
                <div>
                    <div style="font-size:1.2rem; font-weight:bold; margin-bottom:5px;">
                        Trạng thái: {status_text}
                    </div>
                    <div>{status_detail}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Key metrics
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if isinstance(qa_summary['min_shelf_life'], (int, float)):
                value_display = f"{qa_summary['min_shelf_life']:.1f} tháng"
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Dự kiến hạn sử dụng</div>
                    <div style="font-size:1.8rem; font-weight:bold; margin:5px 0;">{value_display}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Dự kiến hạn sử dụng</div>
                    <div style="font-size:1.5rem; font-weight:bold; margin:5px 0;">Chưa xác định</div>
                </div>
                """, unsafe_allow_html=True)
        
        with col2:
            if qa_summary['closest_attr']:
                current_val = qa_summary['closest_attr_value']
                distance = threshold_value - current_val
                progress_pct = min(100, max(0, (current_val / threshold_value) * 100))
                
                display_name = qa_summary['closest_attr']
                # Trim if too long
                if len(display_name) > 20:
                    display_name = display_name[:18] + "..."
                
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Chỉ tiêu gần ngưỡng nhất</div>
                    <div style="font-size:1.5rem; font-weight:bold; margin:5px 0;">{display_name}</div>
                    <div style="margin:10px 0;">
                        <div style="background-color:#e0e0e0; height:5px; border-radius:5px; width:100%;">
                            <div style="background-color:{status_border}; height:5px; border-radius:5px; width:{progress_pct}%;"></div>
                        </div>
                    </div>
                    <div style="font-size:0.9rem;">Còn cách ngưỡng {distance:.2f} đơn vị</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Chỉ tiêu gần ngưỡng nhất</div>
                    <div style="font-size:1.5rem; font-weight:bold; margin:5px 0;">Chưa xác định</div>
                </div>
                """, unsafe_allow_html=True)
        
        with col3:
            if qa_summary['fastest_attr']:
                change_rate = qa_summary['change_rates'][qa_summary['fastest_attr']]
                display_name = qa_summary['fastest_attr']
                # Trim if too long
                if len(display_name) > 20:
                    display_name = display_name[:18] + "..."
                
                arrow = "↑" if change_rate > 0 else "↓"
                color = "#f44336" if change_rate > 0 else "#4caf50"  # Red for increasing (bad), green for decreasing (good)
                
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Chỉ tiêu biến đổi nhanh nhất</div>
                    <div style="font-size:1.5rem; font-weight:bold; margin:5px 0;">{display_name}</div>
                    <div style="color:{color}; font-size:1.2rem;">{arrow} {abs(change_rate):.2f}/tháng</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0; border-radius:5px; padding:10px; text-align:center;">
                    <div style="color:#666; font-size:0.9rem;">Chỉ tiêu biến đổi nhanh nhất</div>
                    <div style="font-size:1.5rem; font-weight:bold; margin:5px 0;">Chưa xác định</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Key recommendations
        st.markdown("### Khuyến nghị hành động")
        
        if isinstance(qa_summary['min_shelf_life'], (int, float)):
            # Determine recommendations based on status
            recs = []
            if remaining_months <= 1:
                recs.append(f"• Đề xuất giảm hạn sử dụng xuống **{int(qa_summary['min_shelf_life'])} tháng**")
                recs.append("• Đánh giá khẩn cấp chất lượng sản phẩm hiện tại")
                recs.append(f"• Tập trung cải thiện chỉ tiêu **{qa_summary['closest_attr']}**")
            elif remaining_months <= 3:
                recs.append(f"• Cân nhắc hạn sử dụng **{int(qa_summary['min_shelf_life'])} tháng**")
                recs.append("• Tăng tần suất giám sát chất lượng")
                
                if qa_summary['fastest_attr']:
                    fastest_rate = qa_summary['change_rates'][qa_summary['fastest_attr']]
                    if fastest_rate > 0:  # Only if it's getting worse
                        recs.append(f"• Khảo sát nguyên nhân biến đổi nhanh của **{qa_summary['fastest_attr']}**")
            else:
                recs.append("• Duy trì quy trình hiện tại")
                recs.append(f"• Tiếp tục theo dõi định kỳ các chỉ tiêu")
            
            rec_html = "<div style='background-color:#f5f5f5; padding:15px; border-radius:5px;'>"
            for rec in recs:
                rec_html += f"<div style='margin-bottom:8px;'>{rec}</div>"
            rec_html += "</div>"
            
            st.markdown(rec_html, unsafe_allow_html=True)
        else:
            st.info("Chưa đủ dữ liệu để đưa ra khuyến nghị. Cần bổ sung thêm dữ liệu theo thời gian.")
    else:
        st.info("Không có dữ liệu cảm quan để hiển thị dashboard.")

# Then use it in your main code like this, replacing the current QA dashboard section:
if not sensory_grouped.empty:
    qa_summary = generate_qa_summary(sensory_grouped, threshold_value)
    create_improved_dashboard(sensory_grouped, threshold_value, qa_summary)
else:
    st.info("Không có dữ liệu cảm quan để hiển thị dashboard.")

### 3. Simplify the main trend chart section
# Replace the current chart section with a cleaner version:

def create_cleaner_trend_chart(sensory_grouped, threshold_value, projections):
    """Create a cleaner and more informative trend chart"""
    
    # Create the trend chart with annotations
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template="plotly_white"
    )
    
    # Add threshold line
    if not sensory_grouped["Time_Months"].empty:
        x_min = sensory_grouped["Time_Months"].min()
        x_max = sensory_grouped["Time_Months"].max()
        x_range = max(1, x_max - x_min)  # Avoid division by zero
        
        fig_sensory.add_shape(
            type="line",
            x0=x_min,
            x1=x_max + (x_range * 0.2),
            y0=threshold_value,
            y1=threshold_value,
            line=dict(color="red", width=2, dash="dash"),
        )
        
        # Add threshold label
        fig_sensory.add_annotation(
            x=x_max + (x_range * 0.1),
            y=threshold_value,
            text=f"Ngưỡng giới hạn: {threshold_value}",
            showarrow=False,
            font=dict(color="red", size=12),
        )
    
    # Add projection lines
    for test, proj_month in projections.items():
        if isinstance(proj_month, (int, float)):
            # Get the last point for this attribute
            test_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months")
            if len(test_data) > 0:
                last_point = test_data.iloc[-1]
                last_month = last_point["Time_Months"]
                last_value = last_point["Actual result"]
                
                # Add projection line
                color_index = list(sensory_grouped["Test description"].unique()).index(test) % len(px.colors.qualitative.Plotly)
                line_color = px.colors.qualitative.Plotly[color_index]
                
                fig_sensory.add_shape(
                    type="line",
                    x0=last_month,
                    x1=proj_month,
                    y0=last_value,
                    y1=threshold_value,
                    line=dict(color=line_color, width=1, dash="dot"),
                )
                
                # Add projection point
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
                        name=f"{test} (tháng {proj_month})",
                        showlegend=True
                    )
                )
                
                # Add more descriptive annotation for important points
                if proj_month < last_month + 4:  # Only for attributes close to threshold
                    fig_sensory.add_annotation(
                        x=proj_month,
                        y=threshold_value + 0.2,
                        text=f"{test}: dự báo tháng {proj_month}",
                        showarrow=True,
                        arrowhead=2,
                        arrowcolor=line_color,
                        font=dict(color=line_color, size=10),
                    )
    
    # Clean up the layout
    fig_sensory.update_layout(
        title="Xu hướng cảm quan theo thời gian lưu",
        xaxis_title="Thời gian (tháng)",
        yaxis_title="Giá trị cảm quan",
        legend_title="Chỉ tiêu",
        hovermode="x unified",
        margin=dict(l=30, r=30, t=50, b=30),
    )
    
    return fig_sensory

# Use it in your main code:
st.markdown("## Biểu đồ xu hướng cảm quan")

if not sensory_grouped.empty:
    # Create and display the trend chart
    fig_sensory = create_cleaner_trend_chart(sensory_grouped, threshold_value, qa_summary['projections'])
    st.plotly_chart(fig_sensory, use_container_width=True)
    
    # Create a more useful table with key trends and projections
    st.markdown("### Dự báo thời hạn sử dụng")
    
    # Group by priority (closest to threshold first)
    projection_data = []
    for test, value in qa_summary['projections'].items():
        latest_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months").iloc[-1]
        current_value = latest_data['Actual result']
        distance = threshold_value - current_value if current_value < threshold_value else 0
        
        # Get change rate
        change_rate = qa_summary['change_rates'].get(test, "N/A")
        if isinstance(change_rate, (int, float)):
            change_text = f"{change_rate:.2f}/tháng"
            months_to_threshold = distance / change_rate if change_rate > 0 else float('inf')
        else:
            change_text = "N/A"
            months_to_threshold = float('inf')
            
        # Calculate a priority score (lower = higher priority)
        if isinstance(value, (int, float)):
            priority = value
        else:
            priority = float('inf')
            
        projection_data.append({
            "Chỉ tiêu": test,
            "Giá trị hiện tại": current_value,
            "Khoảng cách": distance,
            "Tốc độ thay đổi": change_text,
            "Ước tính đạt ngưỡng": value,
            "priority": priority
        })
    
    if projection_data:
        # Sort by priority
        projection_data.sort(key=lambda x: x["priority"])
        
        # Create DataFrame without the priority column
        df_display = pd.DataFrame(projection_data)
        if 'priority' in df_display.columns:
            df_display = df_display.drop('priority', axis=1)
            
        # Format the numeric columns
        for col in ["Giá trị hiện tại", "Khoảng cách"]:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x)
                
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("Không đủ dữ liệu để dự báo thời hạn sử dụng.")
else:
    st.info("Không có dữ liệu cảm quan để hiển thị biểu đồ.")

### 4. Simplify the analysis tabs - Combine into one clear section
# Replace the current tabs with a more focused analysis:

st.markdown("## Đánh giá của QA Manager")

if not sensory_grouped.empty and len(qa_summary['change_rates']) > 0:
    # Create one clear column layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Create rate of change chart
        change_df = pd.DataFrame([
            {"Chỉ tiêu": test, "Tốc độ thay đổi": rate}
            for test, rate in qa_summary['change_rates'].items()
        ])
        
        if not change_df.empty:
            # Sort by change rate (fastest first)
            change_df = change_df.sort_values("Tốc độ thay đổi", ascending=False)
            
            # Create horizontal bar chart
            fig_change = px.bar(
                change_df,
                y="Chỉ tiêu",
                x="Tốc độ thay đổi",
                orientation="h",
                title="Tốc độ thay đổi của các chỉ tiêu (đơn vị/tháng)",
                template="plotly_white",
                text_auto='.2f'
            )
            
            # Add a vertical reference line at 0
            fig_change.add_vline(
                x=0, 
                line_width=1, 
                line_dash="dash", 
                line_color="gray",
            )
            
            # Color bars based on value (positive = red, negative = green)
            fig_change.update_traces(
                marker_color=[
                    'red' if x > 0 else 'green' for x in change_df["Tốc độ thay đổi"]
                ],
                opacity=0.7
            )
            
            fig_change.update_layout(
                xaxis_title="Tốc độ thay đổi (đơn vị/tháng)",
                yaxis_title="",
                height=350
            )
            
            # Display chart
            st.plotly_chart(fig_change, use_container_width=True)
    
    with col2:
        # Determine which attributes are changing significantly
        significant_change = 0.1  # Threshold for significant change
        improving = [attr for attr, rate in qa_summary['change_rates'].items() if rate < -significant_change]
        worsening = [attr for attr, rate in qa_summary['change_rates'].items() if rate > significant_change]
        stable = [attr for attr, rate in qa_summary['change_rates'].items() 
                 if abs(rate) <= significant_change]
        
        # Create insights
        st.markdown("### Đánh giá xu hướng")
        
        # Add icons
        if worsening:
            st.markdown("""
            <div style="background-color:#ffebee; padding:10px; border-radius:5px; margin-bottom:10px;">
                <div style="font-weight:bold; color:#d32f2f;">⚠️ Chỉ tiêu đang xấu đi:</div>
            """, unsafe_allow_html=True)
            
            for attr in worsening:
                rate = qa_summary['change_rates'][attr]
                st.markdown(f"• **{attr}**: +{rate:.2f}/tháng")
                
            st.markdown("</div>", unsafe_allow_html=True)
        
        if improving:
            st.markdown("""
            <div style="background-color:#e8f5e9; padding:10px; border-radius:5px; margin-bottom:10px;">
                <div style="font-weight:bold; color:#388e3c;">✅ Chỉ tiêu đang cải thiện:</div>
            """, unsafe_allow_html=True)
            
            for attr in improving:
                rate = qa_summary['change_rates'][attr]
                st.markdown(f"• **{attr}**: {rate:.2f}/tháng")
                
            st.markdown("</div>", unsafe_allow_html=True)
        
        if stable:
            st.markdown("""
            <div style="background-color:#e3f2fd; padding:10px; border-radius:5px; margin-bottom:10px;">
                <div style="font-weight:bold; color:#1976d2;">ℹ️ Chỉ tiêu ổn định:</div>
            """, unsafe_allow_html=True)
            
            for attr in stable:
                st.markdown(f"• **{attr}**")
                
            st.markdown("</div>", unsafe_allow_html=True)

### 5. Add a concise regression analysis section
# Keep only the most useful analysis from statsmodels

st.markdown("## Phân tích hồi quy")

if not insight_data.empty and "Time_Months" in insight_data.columns:
    # Create a more focused and informative regression analysis
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Scatter plot with trendline - just for most critical attributes
        critical_attrs = []
        if qa_summary['closest_attr']:
            critical_attrs.append(qa_summary['closest_attr'])
        if qa_summary['fastest_attr'] and qa_summary['fastest_attr'] not in critical_attrs:
            critical_attrs.append(qa_summary['fastest_attr'])
            
        # If we have no critical attributes, use all
        if not critical_attrs and 'Test description' in insight_data.columns:
            critical_attrs = insight_data['Test description'].unique().tolist()
            
        # If we have too many, limit to top 3
        if len(critical_attrs) > 3:
            critical_attrs = critical_attrs[:3]
            
        # Filter data for critical attributes
        if critical_attrs and 'Test description' in insight_data.columns:
            critical_data = insight_data[insight_data['Test description'].isin(critical_attrs)]
        else:
            critical_data = insight_data
            
        # Create scatter plot with trendline
        fig_scatter = px.scatter(
            critical_data,
            x="Time_Months",
            y="Actual result",
            color="Test description",
            template="plotly_white",
            trendline="ols",
            title="Phân tích hồi quy cho chỉ tiêu chính"
        )
        
        # Add threshold line
        fig_scatter.add_shape(
            type="line",
            x0=critical_data["Time_Months"].min(),
            x1=critical_data["Time_Months"].max() * 1.2,
            y0=threshold_value,
            y1=threshold_value,
            line=dict(color="red", width=2, dash="dash"),
        )
        
        fig_scatter.update_layout(
            xaxis_title="Thời gian (tháng)", 
            yaxis_title="Kết quả Actual",
            height=400
        )
        
        st.plotly_chart(fig_scatter, use_container_width=True)
    
    with col2:
        # Add a more concise equation interpretation
        st.markdown("### Phương trình dự báo")
        
        import statsmodels.api as sm
        
        equations = []
        
        for test in critical_attrs:
            test_data = insight_data[insight_data["Test description"] == test].dropna(subset=["Time_Months", "Actual result"])
            
            if len(test_data) >= 3:  # Need at least 3 points for meaningful regression
                X = sm.add_constant(test_data["Time_Months"])
                y = test_data["Actual result"]
                
                try:
                    model = sm.OLS(y, X).fit()
                    intercept = model.params[0]
                    slope = model.params[1]
                    r_squared = model.rsquared
                    
                    # Calculate projected month to reach threshold
                    if slope > 0:
                        projected_month = (threshold_value - intercept) / slope
                        projection_text = f"{projected_month:.1f} tháng"
                        
                        equations.append({
                            "test": test,
                            "intercept": intercept,
                            "slope": slope,
                            "r_squared": r_squared,
                            "projected_month": projected_month
                        })
                    else:
                        equations.append({
                            "test": test,
                            "intercept": intercept,
                            "slope": slope,
                            "r_squared": r_squared,
                            "projected_month": None
                        })
                except:
                    pass
        
        # Display equations in a nice format
        for eq in equations:
            slope_sign = "+" if eq["slope"] > 0 else ""
            
            quality = ""
            if eq["r_squared"] >= 0.9:
                quality = "🔵 Dự báo đáng tin cậy cao"
            elif eq["r_squared"] >= 0.7:
                quality = "🟢 Dự báo đáng tin cậy"
            elif eq["r_squared"] >= 0.5:
                quality = "🟠 Dự báo tin cậy trung bình"
            else:
                quality = "🔴 Dự báo độ tin cậy thấp"
                
            st.markdown(f"""
            **{eq['test']}**:
            - y = {eq['intercept']:.2f} {slope_sign}{eq['slope']:.2f}x
            - R² = {eq['r_squared']:.2f} ({quality})
            """)
            
            if eq["projected_month"] is not None:
                st.markdown(f"- Dự báo đạt ngưỡng: **{eq['projected_month']:.1f} tháng**")
            else:
                st.markdown("- Không thể dự báo (xu hướng đi ngang hoặc giảm)")
                
            st.markdown("---")
else:
    st.info("Không đủ dữ liệu để phân tích hồi quy.")
