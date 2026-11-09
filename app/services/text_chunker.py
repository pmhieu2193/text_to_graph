from dataclasses import dataclass
from app.services.pdf_extractor import ExtractedPDF
@dataclass
class TextChunk:
    chunk_index:int; content:str; char_count:int; page_start:int|None; page_end:int|None
class TextChunker:
    def __init__(self,chunk_size=1000,chunk_overlap=150):
        if chunk_size<=0: raise ValueError('chunk_size phải lớn hơn 0.')
        if chunk_overlap<0 or chunk_overlap>=chunk_size: raise ValueError('chunk_overlap phải >= 0 và nhỏ hơn chunk_size.')
        self.chunk_size=chunk_size;self.chunk_overlap=chunk_overlap
    def split(self,extracted:ExtractedPDF)->list[TextChunk]:
        parts=[];ranges=[];cursor=0
        for page in extracted.pages:
            if not page.text: continue
            if parts: parts.append('\n\n');cursor+=2
            start=cursor;parts.append(page.text);cursor+=len(page.text);ranges.append((start,cursor,page.page_number))
        text=''.join(parts).strip();chunks=[];start=0
        while start<len(text):
            end=min(start+self.chunk_size,len(text))
            if end<len(text):
                floor=start+int(self.chunk_size*.65)
                boundary=max(text.rfind('\n\n',floor,end),text.rfind('\n',floor,end),text.rfind('. ',floor,end))
                if boundary>start: end=boundary+(2 if text[boundary:boundary+2]=='. ' else 1)
            content=text[start:end].strip()
            if content:
                pages=[n for a,b,n in ranges if a<end and b>start]
                chunks.append(TextChunk(len(chunks),content,len(content),min(pages) if pages else None,max(pages) if pages else None))
            if end>=len(text): break
            start=max(start+1,end-self.chunk_overlap)
        return chunks
