import os
import sys
import google.generativeai as genai

# Điền API Key của bạn vào đây (hoặc để biến môi trường GEMINI_API_KEY)
API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCXBY5oz-R0HQBC6pQqGVLdzbKnVD6hYQI")

if API_KEY == "YOUR_GEMINI_API_KEY" or not API_KEY:
    print("❌ Lỗi: Bạn chưa nhập API Key!")
    print("Vui lòng thay 'YOUR_GEMINI_API_KEY' bằng key thật của bạn.")
    sys.exit(1)

def test_gemini_connection():
    try:
        # Cấu hình SDK
        genai.configure(api_key=API_KEY)

        # Sử dụng model gemini-1.5-flash
        model = genai.GenerativeModel("gemini-2.5-flash")

        print("🔄 Đang kiểm tra kết nối tới Gemini API...")
        
        # Gửi request test
        response = model.generate_content("Trả lời đúng 1 câu: Hệ thống của bạn hoạt động ổn định chứ?")
        
        print("\n==========================================")
        print("✅ KẾT NỐI THÀNH CÔNG! API Key hợp lệ.")
        print("==========================================")
        print(f"🤖 Phản hồi từ Gemini: {response.text.strip()}")

    except Exception as e:
        print("\n==========================================")
        print("❌ KẾT NỐI THẤT BẠI!")
        print("==========================================")
        print(f"Chi tiết lỗi: {e}")

if __name__ == "__main__":
    test_gemini_connection()