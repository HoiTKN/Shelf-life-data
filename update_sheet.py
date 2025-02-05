# update_sheet.py
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import set_with_dataframe

def load_source_data():
    """
    Ví dụ: Đọc dữ liệu từ một nguồn khác (có thể từ file CSV, database, v.v.)
    Ở đây mình tạo dữ liệu mẫu.
    """
    # Đây chỉ là ví dụ; bạn thay đổi theo logic cập nhật dữ liệu của bạn.
    df = pd.DataFrame({
        "Time": pd.date_range(start="2025-01-01", periods=10, freq="D"),
        "Value": range(10)
    })
    return df

def update_google_sheet(data: pd.DataFrame):
    # Các scope cần thiết cho Google Sheet API
    scope = [
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ]
    # Đọc credentials từ file JSON hoặc từ st.secrets nếu chạy trong Streamlit
    # Ở đây, bạn có thể dùng file JSON cục bộ nếu cần, hoặc tích hợp theo cách bạn đã làm trong app.py.
    # Giả sử bạn sử dụng file JSON cục bộ (nếu dùng GitHub Actions, bạn có thể lưu thông tin này dưới dạng Secrets).
    import os, json
    # Ví dụ: Lấy thông tin từ biến môi trường GCP_SERVICE_ACCOUNT
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise ValueError("Không tìm thấy biến môi trường GCP_SERVICE_ACCOUNT_JSON")
    creds_dict = json.loads(creds_json)
    
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    
    # URL của Google Sheet cũng được cung cấp qua biến môi trường (hoặc secrets)
    sheet_url = os.environ.get("GOOGLE_SHEET_URL")
    if not sheet_url:
        raise ValueError("Không tìm thấy biến môi trường GOOGLE_SHEET_URL")
    
    spreadsheet = client.open_by_url(sheet_url)
    # Chọn worksheet đầu tiên
    worksheet = spreadsheet.get_worksheet(0)
    
    # Ghi dữ liệu mới lên Google Sheet (bạn có thể sử dụng set_with_dataframe)
    set_with_dataframe(worksheet, data)

def main():
    data = load_source_data()
    update_google_sheet(data)
    print("Cập nhật dữ liệu lên Google Sheet thành công.")

if __name__ == "__main__":
    main()
