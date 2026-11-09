from dataclasses import dataclass
from pathlib import Path
import pymupdf as fitz

@dataclass
class ExtractedPage:
    page_number:int
    text:str
@dataclass
class ExtractedPDF:
    pages:list[ExtractedPage]
    @property
    def full_text(self): return '\n\n'.join(p.text for p in self.pages if p.text.strip())
class PDFExtractor:
    def extract(self,file_path:str|Path)->ExtractedPDF:
        pages=[]
        try:
            with fitz.open(file_path) as pdf:
                if pdf.is_encrypted: raise ValueError('PDF được mã hóa, không thể trích xuất.')
                for i,page in enumerate(pdf): pages.append(ExtractedPage(i+1,page.get_text('text').strip()))
        except fitz.FileDataError as exc: raise ValueError('Tệp PDF bị lỗi hoặc không đọc được.') from exc
        if not any(p.text for p in pages): raise ValueError('Không trích xuất được văn bản. Có thể PDF là bản scan; cần bổ sung OCR.')
        return ExtractedPDF(pages)
