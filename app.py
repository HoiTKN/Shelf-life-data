# Modifications for app.py to create a more focused QA dashboard

## 1. Modify the sidebar configuration section 
# Replace the current configuration section with this (remove the checkbox option)
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
display_mode = st.sidebar.radio(
    "Chế độ hiển thị:",
    options=["Standard", "Professional", "Compact"],
    index=0
)

## 2. Add a QA summary dashboard at the top of the visualizations
# Add this right after processing the data, before the chart sections
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
        except:
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

# Display QA Dashboard
st.markdown("## QA Dashboard - Phân tích hạn sử dụng")

# Create QA Summary
if not sensory_grouped.empty:
    qa_summary = generate_qa_summary(sensory_grouped, threshold_value)
    
    # Create metrics in three columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if isinstance(qa_summary['min_shelf_life'], (int, float)):
            st.metric(
                "Dự kiến hạn sử dụng", 
                f"{qa_summary['min_shelf_life']:.1f} tháng",
                help="Thời gian dự kiến khi chỉ tiêu đầu tiên đạt ngưỡng giới hạn"
            )
        else:
            st.metric("Dự kiến hạn sử dụng", qa_summary['min_shelf_life'])
    
    with col2:
        if qa_summary['closest_attr']:
            current_val = qa_summary['closest_attr_value']
            distance = threshold_value - current_val
            st.metric(
                "Chỉ tiêu gần ngưỡng nhất", 
                qa_summary['closest_attr'],
                f"Còn cách {distance:.2f} đơn vị",
                help="Chỉ tiêu đang gần đạt ngưỡng giới hạn nhất"
            )
        else:
            st.metric("Chỉ tiêu gần ngưỡng nhất", "Không xác định")
    
    with col3:
        if qa_summary['fastest_attr']:
            change_rate = qa_summary['change_rates'][qa_summary['fastest_attr']]
            st.metric(
                "Chỉ tiêu biến đổi nhanh nhất", 
                qa_summary['fastest_attr'],
                f"{change_rate:.2f}/tháng",
                help="Chỉ tiêu có tốc độ thay đổi nhanh nhất theo thời gian"
            )
        else:
            st.metric("Chỉ tiêu biến đổi nhanh nhất", "Không xác định")
    
    # Create a visual status indicator
    st.markdown("### Trạng thái sản phẩm")
    
    # Determine status based on proximity to threshold
    if isinstance(qa_summary['min_shelf_life'], (int, float)):
        remaining_months = qa_summary['min_shelf_life'] - max(sensory_grouped["Time_Months"])
        
        if remaining_months <= 1:
            status_color = "red"
            status_text = "⚠️ Cảnh báo: Sản phẩm gần đạt ngưỡng giới hạn"
            recommendation = "Đề xuất đánh giá chất lượng khẩn cấp và xem xét giảm hạn sử dụng."
        elif remaining_months <= 3:
            status_color = "orange"
            status_text = "⚠️ Chú ý: Cần theo dõi chặt chẽ"
            recommendation = "Đề xuất tăng tần suất giám sát và cải thiện quy trình sản xuất."
        else:
            status_color = "green"
            status_text = "✅ Ổn định: Chất lượng sản phẩm trong giới hạn cho phép"
            recommendation = "Duy trì tần suất giám sát hiện tại."
            
        st.markdown(f"<div style='padding:10px; background-color:{status_color}20; border-left:5px solid {status_color}; margin-bottom:10px;'><strong style='color:{status_color};'>{status_text}</strong><br>{recommendation}</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='padding:10px; background-color:#80808020; border-left:5px solid gray; margin-bottom:10px;'><strong>⚙️ Chưa đủ dữ liệu để đánh giá</strong><br>Cần thêm dữ liệu để dự báo hạn sử dụng chính xác.</div>", unsafe_allow_html=True)

## 3. Modify the sensory trend chart section
# Update the sensory visualization with automatic projection (no checkbox needed)
st.markdown("## Biểu đồ xu hướng cảm quan")

# Biểu đồ xu hướng cảm quan (Line Chart) với ngưỡng giới hạn
if not sensory_grouped.empty:
    # Use projections from QA summary
    projections = qa_summary['projections']
    
    # Create the sensory trend chart
    fig_sensory = px.line(
        sensory_grouped,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        markers=True,
        template="plotly_white",
        title="Xu hướng CẢM QUAN theo thời gian lưu"
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
    
    # Add projection lines automatically
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
                        name=f"{test} (dự báo tháng {proj_month})",
                        showlegend=True
                    )
                )
    
    # Apply selected display mode
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
    
    # Display chart
    st.plotly_chart(fig_sensory, use_container_width=True)
    
    # Display projection table with enhanced QA insights
    st.markdown("### Dự báo và phân tích chỉ tiêu")
    
    # Create a table with more detailed QA metrics
    projection_data = []
    for test, value in projections.items():
        latest_data = sensory_grouped[sensory_grouped["Test description"] == test].sort_values("Time_Months").iloc[-1]
        current_value = latest_data['Actual result']
        change_rate = qa_summary['change_rates'].get(test, "N/A")
        if isinstance(change_rate, (int, float)):
            change_rate = f"{change_rate:.2f}/tháng"
            
        projection_data.append({
            "Chỉ tiêu": test,
            "Giá trị hiện tại": f"{current_value:.2f}",
            "Còn cách ngưỡng": f"{threshold_value - current_value:.2f}" if current_value < threshold_value else "Đã vượt",
            "Tốc độ thay đổi": change_rate,
            "Dự báo tháng đạt ngưỡng": value
        })
    
    projection_df = pd.DataFrame(projection_data)
    st.dataframe(projection_df, use_container_width=True, hide_index=True)

## 4. Improve the chemical section with threshold comparison (if applicable)
# This is optional if chemical parameters have thresholds too

## 5. Replace histogram with a more valuable rate of change analysis
# Add this instead of the histogram
st.markdown("## Phân tích chuyên sâu")

# Add tabs for different analyses
tab1, tab2 = st.tabs(["📈 Tốc độ biến đổi", "📊 Box Plot"])

with tab1:
    # Rate of change analysis
    if not sensory_grouped.empty and len(qa_summary['change_rates']) > 0:
        # Create DataFrame from change rates
        change_df = pd.DataFrame([
            {"Chỉ tiêu": test, "Tốc độ thay đổi": rate}
            for test, rate in qa_summary['change_rates'].items()
        ])
        
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
            annotation_text="Không thay đổi",
            annotation_position="top"
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
            height=400
        )
        
        # Display chart
        st.plotly_chart(fig_change, use_container_width=True)
        
        # Add QA analysis
        st.markdown("### Phân tích dành cho QA Manager")
        
        # Determine which attributes are changing significantly
        significant_change = 0.1  # Threshold for significant change
        improving = [attr for attr, rate in qa_summary['change_rates'].items() if rate < -significant_change]
        worsening = [attr for attr, rate in qa_summary['change_rates'].items() if rate > significant_change]
        stable = [attr for attr, rate in qa_summary['change_rates'].items() 
                 if abs(rate) <= significant_change]
        
        # Create insights
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### Đánh giá tốc độ biến đổi")
            if worsening:
                st.markdown(f"⚠️ **Chỉ tiêu đang xấu đi:**")
                for attr in worsening:
                    rate = qa_summary['change_rates'][attr]
                    st.markdown(f"- {attr}: +{rate:.2f}/tháng")
            
            if improving:
                st.markdown(f"✅ **Chỉ tiêu đang cải thiện:**")
                for attr in improving:
                    rate = qa_summary['change_rates'][attr]
                    st.markdown(f"- {attr}: {rate:.2f}/tháng")
            
            if stable:
                st.markdown(f"ℹ️ **Chỉ tiêu ổn định:**")
                for attr in stable:
                    st.markdown(f"- {attr}")
        
        with col2:
            st.markdown("#### Khuyến nghị hành động")
            
            if worsening:
                worst_attr = max([(attr, rate) for attr, rate in qa_summary['change_rates'].items() 
                                 if attr in worsening], key=lambda x: x[1])
                
                st.markdown(f"""
                - Ưu tiên cải thiện: **{worst_attr[0]}** (biến đổi nhanh nhất)
                - Tăng tần suất giám sát cho các chỉ tiêu đang xấu đi
                - Xem xét điều chỉnh quy trình sản xuất/bảo quản
                """)
            else:
                st.markdown("- Duy trì quy trình hiện tại, các chỉ tiêu đang ổn định hoặc cải thiện")
            
            # Add projection-based recommendation
            if isinstance(qa_summary['min_shelf_life'], (int, float)):
                current_max_month = max(sensory_grouped["Time_Months"])
                remaining = qa_summary['min_shelf_life'] - current_max_month
                
                if remaining < 2:
                    st.markdown(f"- Xem xét giảm hạn sử dụng xuống **{int(qa_summary['min_shelf_life'])} tháng**")
                elif remaining < 4:
                    st.markdown(f"- Cân nhắc thời hạn sử dụng **{int(qa_summary['min_shelf_life'])} tháng**")
    else:
        st.info("Cần ít nhất 3 điểm dữ liệu cho mỗi chỉ tiêu để phân tích tốc độ biến đổi.")

with tab2:
    # Box Plot (kept from original)
    if not insight_data.empty:
        fig_box = px.box(
            insight_data,
            x="Time_Months",
            y="Actual result",
            color="Test description",
            template="plotly_white",
            title="Phân bố kết quả kiểm theo tháng lưu"
        )
        fig_box.update_layout(xaxis_title="Thời gian (tháng)", yaxis_title="Kết quả Actual")
        st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("Không đủ dữ liệu để vẽ Box Plot.")

## 6. Remove or simplify the remaining plots
# Keep only the most useful visualizations from the remaining plots
# For example, you might want to keep only the scatter plot with trendline
if not insight_data.empty and "Time_Months" in insight_data.columns:
    st.markdown("### Mối quan hệ giữa thời gian lưu và kết quả kiểm")
    # Use scatter with trendline - one of the most valuable charts for shelf-life analysis
    fig_scatter = px.scatter(
        insight_data,
        x="Time_Months",
        y="Actual result",
        color="Test description",
        template="plotly_white",
        trendline="ols"
    )
    
    # Add threshold line
    fig_scatter.add_shape(
        type="line",
        x0=insight_data["Time_Months"].min(),
        x1=insight_data["Time_Months"].max() * 1.2,
        y0=threshold_value,
        y1=threshold_value,
        line=dict(color="red", width=2, dash="dash"),
    )
    
    fig_scatter.update_layout(
        xaxis_title="Thời gian (tháng)", 
        yaxis_title="Kết quả Actual",
        height=500
    )
    
    st.plotly_chart(fig_scatter, use_container_width=True)
    
    # Add trendline equation interpretation
    if "Test description" in insight_data.columns:
        st.markdown("#### Phương trình hồi quy tuyến tính")
        
        import statsmodels.api as sm
        
        for test in insight_data["Test description"].unique():
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
                    else:
                        projection_text = "Không xác định (xu hướng đi ngang hoặc giảm)"
                    
                    st.markdown(f"""
                    **{test}**: 
                    - Phương trình: y = {intercept:.2f} + {slope:.2f}x
                    - R² = {r_squared:.2f}
                    - Dự báo đạt ngưỡng: {projection_text}
                    """)
                except:
                    st.markdown(f"**{test}**: Không đủ dữ liệu để phân tích hồi quy")
