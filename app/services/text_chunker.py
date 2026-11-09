import re
import unicodedata
from dataclasses import dataclass
from app.services.pdf_extractor import ExtractedPDF

# Các từ viết tắt phổ biến trong tiếng Việt để tránh bị cắt nhầm thành kết thúc câu
VIETNAMESE_ABBREVIATIONS = (
    r'\b(TP|ThS|TS|BS|PGS|GS|NXB|QĐ|NĐ|TT|TW|HĐND|UBND|đ/c|v\.v)\.$'
)

@dataclass
class TextChunk:
    chunk_index: int
    content: str
    char_count: int
    page_start: int | None
    page_end: int | None

class TextChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        if chunk_size <= 0:
            raise ValueError('chunk_size phải lớn hơn 0.')
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError('chunk_overlap phải >= 0 và nhỏ hơn chunk_size.')
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _clean_text(self, text: str) -> str:
        """Làm sạch ký tự rác, lọc số trang và nối các dòng bị ngắt dở dang."""
        if not text:
            return ""

        # 1. Chuẩn hóa Unicode NFC (đảm bảo không bị tách dấu tiếng Việt)
        text = unicodedata.normalize("NFC", text)

        # 2. Loại bỏ các ký tự điều khiển ẩn (Control characters)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufeff]', '', text)

        # 3. Loại bỏ dòng số trang độc lập (Header / Footer / Page number)
        lines = text.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if re.match(r'^(?:trang\s+\d+(?:\/\d+)?|\d+|-\s*\d+\s*-)$', stripped, re.IGNORECASE):
                continue
            cleaned_lines.append(line)
            
        text = "\n".join(cleaned_lines)

        # 4. Chuẩn hóa khoảng trắng quanh dấu xuống dòng trước khi unwrap
        text = re.sub(r'[ \t]+\n', '\n', text)  # Xóa space thừa cuối dòng
        text = re.sub(r'\n[ \t]+', '\n', text)  # Xóa space thừa đầu dòng

        # 5. SỬA LỖI CHÍNH: Nối các dòng bị ngắt giữa câu (Unwrap lines)
        # Các định dạng BẮT ĐẦU DÒNG MỚI HỢP LỆ (Bắt buộc phải có khoảng trắng \s+ theo sau):
        # - Gạch đầu dòng: - , * , • , + 
        # - Số thứ tự: 1. , 2) 
        # - Chữ cái: a) , A. 
        # - Điều/Khoản luật: Điều 1, Khoản 2, Chương III
        LIST_ITEM_START = r'(?:[-*•+]\s+|\d+[\.\)]\s+|[a-zA-Z][\.\)]\s+|(?:Điều|Khoản|Chương|Mục|Phần)\s+)'

        # Nối dòng nếu dòng trước không kết thúc bằng .?!:; 
        # và dòng sau KHÔNG PHẢI là đầu mục danh sách/đoạn mới (\n\n)
        text = re.sub(
            r'([^\n.?!:;])\n(?!\n|\s*' + LIST_ITEM_START + r')',
            r'\1 ',
            text
        )

        # 6. Sửa lỗi dính chữ với số (ví dụ: "dưới1.4m" -> "dưới 1.4m")
        text = re.sub(
            r'([a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ])(\d)',
            r'\1 \2',
            text
        )

        # 7. Chuẩn hóa lại khoảng trắng thừa và dòng trống
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)

        return text.strip()

    def _find_smart_boundary(self, text: str, start: int, end: int) -> int:
        """Tìm vị trí cắt tối ưu dựa trên cấu trúc câu và đoạn văn tiếng Việt."""
        floor = start + int(self.chunk_size * 0.65)
        search_zone = text[floor:end]

        # Ưu tiên 1: Cắt theo đoạn văn (\n\n)
        p_idx = search_zone.rfind('\n\n')
        if p_idx != -1:
            return floor + p_idx + 2

        # Ưu tiên 2: Cắt theo kết thúc câu (. ? !) - kiểm tra loại trừ từ viết tắt tiếng Việt
        matches = list(re.finditer(r'[.?!]\s+', search_zone))
        for m in reversed(matches):
            boundary = floor + m.end()
            prefix = text[start:boundary].split()[-1] if text[start:boundary].split() else ""
            if not re.search(VIETNAMESE_ABBREVIATIONS, prefix, re.IGNORECASE):
                return boundary

        # Ưu tiên 3: Cắt theo dấu xuống dòng đơn (\n)
        n_idx = search_zone.rfind('\n')
        if n_idx != -1:
            return floor + n_idx + 1

        # Ưu tiên 4: Cắt theo dấu phẩy, chấm phẩy hoặc hai chấm (, ; :)
        c_idx = max(search_zone.rfind(', '), search_zone.rfind('; '), search_zone.rfind(': '))
        if c_idx != -1:
            return floor + c_idx + 2

        # Ưu tiên 5: Cắt theo khoảng trắng (cuối từ)
        s_idx = search_zone.rfind(' ')
        if s_idx != -1:
            return floor + s_idx + 1

        return end

    def split(self, extracted: ExtractedPDF) -> list[TextChunk]:
        parts = []
        ranges = []
        cursor = 0

        for page in extracted.pages:
            if not page.text:
                continue

            cleaned_page_text = self._clean_text(page.text)
            if not cleaned_page_text:
                continue

            if parts:
                parts.append('\n\n')
                cursor += 2

            start = cursor
            parts.append(cleaned_page_text)
            cursor += len(cleaned_page_text)
            ranges.append((start, cursor, page.page_number))

        text = ''.join(parts).strip()
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))

            if end < len(text):
                end = self._find_smart_boundary(text, start, end)

            content = text[start:end].strip()
            if content:
                pages = [n for a, b, n in ranges if a < end and b > start]
                chunks.append(
                    TextChunk(
                        chunk_index=len(chunks),
                        content=content,
                        char_count=len(content),
                        page_start=min(pages) if pages else None,
                        page_end=max(pages) if pages else None,
                    )
                )

            if end >= len(text):
                break

            next_start = max(start + 1, end - self.chunk_overlap)
            if next_start < len(text) and text[next_start] == ' ':
                next_start += 1
            start = next_start

        return chunks