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

# Improvements for the trend chart visualization
def create_enhanced_trend_chart(sensory_grouped, threshold_value, projections):
    """Create an enhanced version of the trend chart with more visual information"""
    import plotly.express as px
    import plotly.graph_objects as go
    import numpy as np
    
    # Create the trend chart with annotations
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template="plotly_white"
    )
    
    # Add threshold line with shaded area
    if not sensory_grouped["Time_Months"].empty:
        x_min = sensory_grouped["Time_Months"].min()
        x_max = sensory_grouped["Time_Months"].max()
        x_range = max(1, x_max - x_min)  # Avoid division by zero
        extended_x_max = x_max + (x_range * 0.3)  # Extend a bit more
        
        # Add threshold line
        fig_sensory.add_shape(
            type="line",
            x0=x_min,
            x1=extended_x_max,
            y0=threshold_value,
            y1=threshold_value,
            line=dict(color="red", width=2, dash="dash"),
        )
        
        # Add shaded area above threshold (danger zone)
        fig_sensory.add_shape(
            type="rect",
            x0=x_min,
            x1=extended_x_max,
            y0=threshold_value,
            y1=threshold_value * 1.2,  # Extend upward
            fillcolor="rgba(255, 0, 0, 0.1)",
            line=dict(width=0),
        )
        
        # Add threshold label
        fig_sensory.add_annotation(
            x=x_max + (x_range * 0.1),
            y=threshold_value,
            text=f"Ngưỡng giới hạn: {threshold_value}",
            showarrow=False,
            font=dict(color="red", size=12),
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor="red",
            borderwidth=1,
            borderpad=4,
        )
    
    # Add projection lines with confidence intervals
    for test, proj_month in projections.items():
        if isinstance(proj_month, (int, float)):
            # Get the last point for this attribute
            test_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months")
            if len(test_data) > 1:  # Need at least 2 points
                last_point = test_data.iloc[-1]
                last_month = last_point["Time_Months"]
                last_value = last_point["Actual result"]
                
                # Calculate projection line
                color_index = list(sensory_grouped["Test description"].unique()).index(test) % len(px.colors.qualitative.Plotly)
                line_color = px.colors.qualitative.Plotly[color_index]
                
                # Calculate slope and confidence
                if len(test_data) >= 3:
                    x = test_data["Time_Months"].values
                    y = test_data["Actual result"].values
                    
                    # Get slope variance for confidence interval
                    coeffs = np.polyfit(x, y, 1, cov=True)
                    slope, intercept = coeffs[0]
                    slope_variance = coeffs[1][0, 0]
                    
                    # Calculate confidence interval boundaries (using 90% confidence)
                    slope_error = 1.645 * np.sqrt(slope_variance)  # 90% confidence
                    
                    # Calculate upper and lower projection points
                    time_to_threshold = (threshold_value - last_value) / slope
                    upper_time = (threshold_value - last_value) / (slope + slope_error) if (slope + slope_error) > 0 else None
                    lower_time = (threshold_value - last_value) / (slope - slope_error) if (slope - slope_error) > 0 else None
                    
                    # Add projection line
                    fig_sensory.add_shape(
                        type="line",
                        x0=last_month,
                        x1=proj_month,
                        y0=last_value,
                        y1=threshold_value,
                        line=dict(color=line_color, width=2, dash="dot"),
                    )
                    
                    # Add confidence interval if we have valid bounds
                    if upper_time is not None and lower_time is not None:
                        proj_points_x = [upper_time + last_month, proj_month, lower_time + last_month]
                        proj_points_y = [threshold_value, threshold_value, threshold_value]
                        
                        fig_sensory.add_trace(go.Scatter(
                            x=proj_points_x,
                            y=proj_points_y,
                            mode='markers',
                            marker=dict(color=line_color, size=8, symbol=['triangle-left', 'circle', 'triangle-right']),
                            name=f"{test} CI (90%)",
                            showlegend=False
                        ))
                        
                        # Add semi-transparent confidence band
                        x_vals = np.linspace(last_month, max(proj_points_x), 50)
                        lower_y = intercept + (slope - slope_error) * (x_vals - last_month) + last_value
                        upper_y = intercept + (slope + slope_error) * (x_vals - last_month) + last_value
                        
                        fig_sensory.add_trace(go.Scatter(
                            x=np.concatenate([x_vals, x_vals[::-1]]),
                            y=np.concatenate([upper_y, lower_y[::-1]]),
                            fill='toself',
                            fillcolor=f'rgba{tuple(list(int(line_color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + [0.2])}',
                            line=dict(color='rgba(255,255,255,0)'),
                            hoverinfo="skip",
                            showlegend=False
                        ))
                else:
                    # Add simple projection line for cases with limited data
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
                            size=12,
                            color=line_color,
                            line=dict(color='black', width=1)
                        ),
                        name=f"{test} (tháng {proj_month:.1f})",
                        showlegend=False
                    )
                )
                
                # Add custom hover text for projection point
                fig_sensory.add_trace(
                    go.Scatter(
                        x=[proj_month],
                        y=[threshold_value],
                        mode="markers",
                        marker=dict(opacity=0, size=15),
                        hoverinfo="text",
                        hovertext=f"{test}<br>Dự báo đạt ngưỡng: {proj_month:.1f} tháng<br>Từ giá trị hiện tại: {last_value:.2f}",
                        showlegend=False
                    )
                )
                
                # Add more descriptive annotation for important points
                if proj_month < last_month + 4:  # Only for attributes close to threshold
                    fig_sensory.add_annotation(
                        x=proj_month,
                        y=threshold_value + 0.2,
                        text=f"{test}: {proj_month:.1f} tháng",
                        showarrow=True,
                        arrowhead=2,
                        arrowcolor=line_color,
                        font=dict(color=line_color, size=10, family="Arial Black"),
                        bgcolor="rgba(255, 255, 255, 0.8)",
                        bordercolor=line_color,
                        borderwidth=1,
                        borderpad=4,
                    )
    
    # Add vertical line for current time
    if not sensory_grouped["Time_Months"].empty:
        current_month = sensory_grouped["Time_Months"].max()
        fig_sensory.add_shape(
            type="line",
            x0=current_month,
            x1=current_month,
            y0=sensory_grouped["Actual result"].min() * 0.9,
            y1=max(threshold_value * 1.1, sensory_grouped["Actual result"].max() * 1.1),
            line=dict(color="black", width=1, dash="dot"),
        )
        
        fig_sensory.add_annotation(
            x=current_month,
            y=sensory_grouped["Actual result"].min() * 0.95,
            text="Hiện tại",
            showarrow=False,
            font=dict(color="black", size=10),
            bgcolor="white",
            bordercolor="black",
            borderwidth=1,
            borderpad=2,
        )
    
    # Improve hover template to show more details
    fig_sensory.update_traces(
        hovertemplate='<b>%{fullData.name}</b><br>Tháng: %{x:.1f}<br>Giá trị: %{y:.2f}<extra></extra>'
    )
    
    # Clean up the layout with improved styling
    fig_sensory.update_layout(
        title={
            'text': "Xu hướng cảm quan và dự báo thời gian sử dụng",
            'y':0.95,
            'x':0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': dict(size=18, family="Arial", color="#333")
        },
        xaxis={
            'title': "Thời gian (tháng)",
            'gridcolor': 'rgba(230, 230, 230, 0.8)',
            'tickvals': list(range(0, int(extended_x_max) + 2)) if 'extended_x_max' in locals() else None,
        },
        yaxis={
            'title': "Giá trị cảm quan",
            'gridcolor': 'rgba(230, 230, 230, 0.8)',
        },
        legend={
            'title': "Chỉ tiêu",
            'bgcolor': 'rgba(255, 255, 255, 0.8)',
            'bordercolor': 'rgba(0, 0, 0, 0.3)',
            'borderwidth': 1
        },
        hovermode="closest",
        margin=dict(l=30, r=30, t=80, b=30),
        plot_bgcolor='rgba(255, 255, 255, 1)',
        paper_bgcolor='rgba(255, 255, 255, 1)',
        font=dict(family="Arial", size=12),
    )
    
    # Add a disclaimer about projection reliability
    fig_sensory.add_annotation(
        x=0.5,
        y=0,
        xref="paper",
        yref="paper",
        text="Lưu ý: Dự báo dựa trên dữ liệu hiện có và có thể thay đổi khi có thêm dữ liệu mới",
        showarrow=False,
        font=dict(size=10, color="gray"),
    )
    
    return fig_sensory

# Add a waterfall chart to show change in quality attributes over time
def create_waterfall_chart(sensory_grouped, selected_test=None):
    """Create a waterfall chart to visualize changes in quality over time periods"""
    import plotly.graph_objects as go
    
    if selected_test is None and not sensory_grouped.empty:
        # If no test selected, use the one with most data points
        test_counts = sensory_grouped['Test description'].value_counts()
        if not test_counts.empty:
            selected_test = test_counts.index[0]
    
    # Filter for selected test
    test_data = sensory_grouped[sensory_grouped['Test description'] == selected_test].sort_values('Time_Months')
    
    if len(test_data) < 2:
        return None
    
    # Calculate changes between time periods
    changes = []
    periods = []
    measures = []
    
    first_value = test_data.iloc[0]['Actual result']
    last_value = first_value
    
    # Add initial value
    changes.append(first_value)
    periods.append(f"Tháng {test_data.iloc[0]['Time_Months']:.1f}")
    measures.append('absolute')
    
    # Add changes between periods
    for i in range(1, len(test_data)):
        current = test_data.iloc[i]['Actual result']
        change = current - last_value
        changes.append(change)
        periods.append(f"→ Tháng {test_data.iloc[i]['Time_Months']:.1f}")
        measures.append('relative')
        last_value = current
    
    # Add final value
    changes.append(test_data.iloc[-1]['Actual result'])
    periods.append(f"Hiện tại (Tháng {test_data.iloc[-1]['Time_Months']:.1f})")
    measures.append('total')
    
    # Create waterfall chart
    fig = go.Figure(go.Waterfall(
        name=selected_test,
        orientation="v",
        measure=measures,
        x=periods,
        y=changes,
        text=[f"{y:.2f}" for y in changes],
        textposition="outside",
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        decreasing={"marker": {"color": "#7CFC00"}},  # Green for improvements (decreasing is better for sensory)
        increasing={"marker": {"color": "#FF4500"}},  # Red for degradation
        totals={"marker": {"color": "#0047AB"}}      # Blue for totals
    ))
    
    fig.update_layout(
        title={
            'text': f"Biến đổi chất lượng {selected_test} theo thời gian",
            'x': 0.5,
            'xanchor': 'center',
            'font': dict(size=16)
        },
        showlegend=False,
        yaxis={
            'title': "Giá trị cảm quan",
            'gridcolor': 'rgba(230, 230, 230, 0.8)'
        },
        margin=dict(l=30, r=30, t=80, b=30),
        plot_bgcolor='rgba(255, 255, 255, 1)',
        paper_bgcolor='rgba(255, 255, 255, 1)',
    )
    
    return fig

# Create a radar chart to compare sensory attributes at different time points
def create_radar_chart(sensory_grouped):
    """Create a radar chart to compare different time points for all sensory attributes"""
    import plotly.graph_objects as go
    import pandas as pd
    
    if sensory_grouped.empty:
        return None
    
    # Group by test description
    all_tests = sensory_grouped['Test description'].unique()
    
    # Determine time points to compare (initial, middle, latest)
    all_months = sorted(sensory_grouped['Time_Months'].unique())
    
    if len(all_months) < 2:
        return None
    
    # Always include first and last month
    compare_months = [all_months[0], all_months[-1]]
    
    # Add a middle month if available
    if len(all_months) >= 3:
        middle_idx = len(all_months) // 2
        compare_months.insert(1, all_months[middle_idx])
    
    # Create nice labels for the time points
    month_labels = [f"Tháng {m:.1f}" for m in compare_months]
    
    # Prepare data for radar chart
    radar_data = []
    
    for month, label in zip(compare_months, month_labels):
        # Get data for this month
        month_values = {}
        
        for test in all_tests:
            test_at_month = sensory_grouped[
                (sensory_grouped['Test description'] == test) & 
                (sensory_grouped['Time_Months'] == month)
            ]
            
            if not test_at_month.empty:
                month_values[test] = test_at_month['Actual result'].values[0]
            else:
                # If no exact match, get closest month
                test_data = sensory_grouped[sensory_grouped['Test description'] == test]
                if not test_data.empty:
                    closest_idx = (test_data['Time_Months'] - month).abs().idxmin()
                    month_values[test] = test_data.loc[closest_idx, 'Actual result']
                else:
                    month_values[test] = None
        
        # Filter out None values
        valid_tests = [test for test in all_tests if month_values.get(test) is not None]
        
        if valid_tests:
            radar_data.append(
                go.Scatterpolar(
                    r=[month_values[test] for test in valid_tests],
                    theta=valid_tests,
                    fill='toself',
                    name=label
                )
            )
    
    # Create the radar chart
    fig = go.Figure(radar_data)
    
    # Update layout
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max([
                    max([trace['r'][i] for i in range(len(trace['r']))], default=0) 
                    for trace in radar_data
                ], default=10) * 1.1]
            )
        ),
        title={
            'text': "So sánh chỉ tiêu cảm quan theo thời gian",
            'x': 0.5,
            'xanchor': 'center',
            'font': dict(size=16)
        },
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.2,
            xanchor="center",
            x=0.5
        ),
        margin=dict(l=30, r=30, t=80, b=30),
    )
    
    return fig

# Create a heatmap of correlations between quality attributes
def create_correlation_heatmap(sensory_data):
    """Create a heatmap showing correlations between quality attributes over time"""
    import plotly.express as px
    import pandas as pd
    import numpy as np
    
    if sensory_data.empty:
        return None
    
    # Pivot data to get attributes as columns and time as index
    pivot_df = sensory_data.pivot_table(
        index='Time_Months', 
        columns='Test description', 
        values='Actual result', 
        aggfunc='mean'
    )
    
    # Fill NAs with forward fill (or other appropriate method)
    pivot_df = pivot_df.ffill().bfill()
    
    # Only include attributes with sufficient data points
    min_required = 3  # Require at least 3 data points
    valid_columns = [col for col in pivot_df.columns if pivot_df[col].count() >= min_required]
    
    if len(valid_columns) < 2:
        return None
    
    # Calculate correlation matrix
    corr_matrix = pivot_df[valid_columns].corr()
    
    # Convert to long format for heatmap
    corr_df = corr_matrix.stack().reset_index()
    corr_df.columns = ['Attribute 1', 'Attribute 2', 'Correlation']
    
    # Create heatmap
    fig = px.imshow(
        corr_matrix,
        color_continuous_scale='RdBu_r',  # Red-Blue scale, reversed (Blue = positive, Red = negative)
        zmin=-1,
        zmax=1,
        text_auto='.2f',
        aspect="auto",
        title="Tương quan giữa các chỉ tiêu chất lượng",
    )
    
    # Update layout
    fig.update_layout(
        xaxis_title="",
        yaxis_title="",
        xaxis={'side': 'bottom'},
        margin=dict(l=30, r=30, t=80, b=30),
        coloraxis_colorbar=dict(
            title="Hệ số<br>tương quan",
            titleside="right",
            thickness=15,
            len=0.6,
            outlinewidth=0
        ),
    )
    
    # Improve text and font sizes
    fig.update_traces(
        textfont=dict(size=10),
    )
    
    # Make clearer diagonal
    diagonal_values = np.eye(len(corr_matrix)) * 2 - 1  # Creates 1s on diagonal and 0s elsewhere
    diagonal_text = np.full_like(diagonal_values, "", dtype=object)
    
    # Add diagonal highlight
    fig.add_trace(
        px.imshow(
            diagonal_values, 
            text_auto=diagonal_text
        ).data[0]
    )
    
    return fig

# Create a composite quality index visualization
def create_composite_quality_index(sensory_grouped, threshold_value):
    """Create a time series visualization of a composite quality index"""
    import plotly.graph_objects as go
    import pandas as pd
    import numpy as np
    
    if sensory_grouped.empty:
        return None
    
    # Get all unique time points
    all_times = sorted(sensory_grouped['Time_Months'].unique())
    
    if len(all_times) < 2:
        return None
    
    # Prepare to calculate composite index across time
    composite_data = []
    upper_ci = []
    lower_ci = []
    
    # For each time point, calculate:
    # 1. Mean distance from threshold (as percentage)
    # 2. Standard deviation of distances
    for time_point in all_times:
        time_data = sensory_grouped[sensory_grouped['Time_Months'] == time_point]
        
        if len(time_data) > 0:
            # Calculate distance from threshold for each attribute
            distances = []
            for _, row in time_data.iterrows():
                # Distance as percentage (how close to threshold)
                # 0% = at threshold, 100% = max distance (usually initial quality)
                distance = (threshold_value - row['Actual result']) / threshold_value * 100
                distances.append(max(0, distance))  # Only consider positive distances
            
            # Calculate average quality index (higher is better)
            if distances:
                mean_distance = np.mean(distances)
                std_distance = np.std(distances) if len(distances) > 1 else 0
                quality_index = 100 - mean_distance  # Invert so higher is better
                
                composite_data.append({
                    'Time_Months': time_point,
                    'Quality_Index': quality_index,
                    'StdDev': std_distance,
                    'Count': len(distances)
                })
                
                # Calculate confidence interval
                ci_factor = 1.96 / np.sqrt(len(distances))  # 95% confidence
                upper_ci.append(quality_index + std_distance * ci_factor)
                lower_ci.append(max(0, quality_index - std_distance * ci_factor))
    
    if not composite_data:
        return None
    
    # Convert to DataFrame for plotting
    df = pd.DataFrame(composite_data)
    
    # Create gauge-like visualization
    fig = go.Figure()
    
    # Add confidence interval as shaded area
    fig.add_trace(go.Scatter(
        x=df['Time_Months'],
        y=upper_ci,
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip'
    ))
    
    fig.add_trace(go.Scatter(
        x=df['Time_Months'],
        y=lower_ci,
        mode='lines',
        line=dict(width=0),
        fill='tonexty',
        fillcolor='rgba(0, 100, 80, 0.2)',
        showlegend=False,
        hoverinfo='skip'
    ))
    
    # Add main line
    fig.add_trace(go.Scatter(
        x=df['Time_Months'],
        y=df['Quality_Index'],
        mode='lines+markers',
        line=dict(color='rgb(0, 100, 80)', width=3),
        marker=dict(size=8, color='rgb(0, 100, 80)'),
        name='Chỉ số chất lượng tổng hợp',
        hovertemplate='Tháng %{x:.1f}<br>Chỉ số chất lượng: %{y:.1f}%<br>Số chỉ tiêu: %{text}<extra></extra>',
        text=df['Count']
    ))
    
    # Add horizontal guide lines for quality ranges
    fig.add_shape(
        type="line",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=20,
        y1=20,
        line=dict(color="red", width=1, dash="dash"),
    )
    
    fig.add_shape(
        type="line",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=50,
        y1=50,
        line=dict(color="orange", width=1, dash="dash"),
    )
    
    fig.add_shape(
        type="line",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=80,
        y1=80,
        line=dict(color="green", width=1, dash="dash"),
    )
    
    # Add annotations for quality ranges
    fig.add_annotation(
        x=max(df['Time_Months']),
        y=10,
        text="Cảnh báo",
        showarrow=False,
        font=dict(color="red", size=10),
        xanchor="left",
        xshift=10
    )
    
    fig.add_annotation(
        x=max(df['Time_Months']),
        y=35,
        text="Cảnh giác",
        showarrow=False,
        font=dict(color="orange", size=10),
        xanchor="left",
        xshift=10
    )
    
    fig.add_annotation(
        x=max(df['Time_Months']),
        y=65,
        text="Chấp nhận",
        showarrow=False,
        font=dict(color="#9ACD32", size=10),  # Yellowgreen
        xanchor="left",
        xshift=10
    )
    
    fig.add_annotation(
        x=max(df['Time_Months']),
        y=90,
        text="Tốt",
        showarrow=False,
        font=dict(color="green", size=10),
        xanchor="left",
        xshift=10
    )
    
    # Update layout
    fig.update_layout(
        title={
            'text': "Chỉ số chất lượng sản phẩm theo thời gian",
            'x': 0.5,
            'xanchor': 'center',
            'font': dict(size=16)
        },
        xaxis_title="Thời gian (tháng)",
        yaxis=dict(
            title="Chỉ số chất lượng (%)",
            range=[0, 105],
            gridcolor='rgba(230, 230, 230, 0.8)'
        ),
        margin=dict(l=30, r=30, t=80, b=30),
        showlegend=False,
        plot_bgcolor='rgba(255, 255, 255, 1)',
    )
    
    # Add colored background zones
    fig.add_shape(
        type="rect",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=0,
        y1=20,
        fillcolor="rgba(255, 0, 0, 0.1)",
        line=dict(width=0),
        layer="below"
    )
    
    fig.add_shape(
        type="rect",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=20,
        y1=50,
        fillcolor="rgba(255, 165, 0, 0.1)",
        line=dict(width=0),
        layer="below"
    )
    
    fig.add_shape(
        type="rect",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=50,
        y1=80,
        fillcolor="rgba(154, 205, 50, 0.1)",
        line=dict(width=0),
        layer="below"
    )
    
    fig.add_shape(
        type="rect",
        x0=min(df['Time_Months']),
        x1=max(df['Time_Months']),
        y0=80,
        y1=105,
        fillcolor="rgba(0, 128, 0, 0.1)",
        line=dict(width=0),
        layer="below"
    )
    
    return fig

# Helper function to implement these visualizations in the app
def implement_enhanced_visualizations(sensory_grouped, threshold_value, qa_summary):
    """
    Call this function in the app to implement the enhanced visualizations
    
    Args:
        sensory_grouped: The grouped sensory data DataFrame
        threshold_value: The quality threshold value
        qa_summary: The quality summary dictionary
        
    Returns:
        None (displays visualizations in Streamlit)
    """
    import streamlit as st
    
    # 1. Enhanced trend chart (main visualization)
    st.markdown("## Biểu đồ xu hướng cảm quan nâng cao")
    fig_trend = create_enhanced_trend_chart(sensory_grouped, threshold_value, qa_summary['projections'])
    st.plotly_chart(fig_trend, use_container_width=True)
    
    # 2. Composite quality index
    st.markdown("## Chỉ số chất lượng tổng hợp")
    fig_composite = create_composite_quality_index(sensory_grouped, threshold_value)
    if fig_composite:
        st.plotly_chart(fig_composite, use_container_width=True)
    else:
        st.info("Không đủ dữ liệu để tạo chỉ số chất lượng tổng hợp.")
    
    # 3. Detailed analysis with multiple charts
    st.markdown("## Phân tích chi tiết")
    
    # 3.1. Correlation heatmap
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Tương quan giữa các chỉ tiêu")
        fig_corr = create_correlation_heatmap(sensory_grouped)
        if fig_corr:
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.info("Không đủ dữ liệu để tạo bản đồ tương quan.")
    
    with col2:
        st.markdown("### So sánh theo thời gian")
        fig_radar = create_radar_chart(sensory_grouped)
        if fig_radar:
            st.plotly_chart(fig_radar, use_container_width=True)
        else:
            st.info("Không đủ dữ liệu để tạo biểu đồ radar.")
    
    # 3.2. Waterfall chart
    st.markdown("### Phân tích biến đổi chất lượng")
    
    # Dropdown to select attribute for waterfall chart
    if not sensory_grouped.empty:
        available_tests = sensory_grouped['Test description'].unique().tolist()
        selected_test = st.selectbox(
            "Chọn chỉ tiêu để phân tích chi tiết:", 
            available_tests,
            index=0 if available_tests else None
        )
        
        if selected_test:
            fig_waterfall = create_waterfall_chart(sensory_grouped, selected_test)
            if fig_waterfall:
                st.plotly_chart(fig_waterfall, use_container_width=True)
            else:
                st.info(f"Không đủ dữ liệu để tạo biểu đồ waterfall cho {selected_test}.")
    else:
        st.info("Không có dữ liệu cảm quan để phân tích.")
