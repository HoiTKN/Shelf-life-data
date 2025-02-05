import os
import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import set_with_dataframe

def load_source_data():
    """
    Hàm này mô phỏng việc load dữ liệu từ nguồn nào đó.
    Bạn có thể thay thế bằng logic thực tế (ví dụ: đọc file CSV, truy vấn CSDL, v.v.)
    """
    # Ví dụ: tạo dữ liệu mẫu
    df = pd.DataFrame({
        "Time": pd.date_range(start="2025-01-01", periods=10, freq="D"),
        "Value": list(range(10))
    })
    return df

def update_google_sheet(data: pd.DataFrame):
    # Các scope cần cho Google Sheets API
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Lấy thông tin credentials từ biến môi trường GCP_SERVICE_ACCOUNT
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT")
    if not creds_json:
        raise ValueError("Không tìm thấy biến môi trường GCP_SERVICE_ACCOUNT")
    
    # Chuyển chuỗi JSON thành dict
    creds_dict = json.loads(creds_json)
    
    # Xây dựng credentials và ủy quyền
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    
    # Lấy URL của Google Sheet từ biến môi trường
    sheet_url = os.environ.get("GOOGLE_SHEET_URL")
    if not sheet_url:
        raise ValueError("Không tìm thấy biến môi trường GOOGLE_SHEET_URL")
    
    # Mở Google Sheet và chọn worksheet đầu tiên
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.get_worksheet(0)
    
    # Cập nhật dữ liệu lên Google Sheet
    set_with_dataframe(worksheet, data)
    print("Cập nhật dữ liệu lên Google Sheet thành công.")

def main():
    # Load dữ liệu từ nguồn (thay đổi hàm load_source_data theo nhu cầu thực tế của bạn)
    data = load_source_data()
    # Cập nhật dữ liệu lên Google Sheet
    update_google_sheet(data)

if __name__ == "__main__":
    main()
