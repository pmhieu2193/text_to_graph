from app.services.pdf_extractor import ExtractedPDF,ExtractedPage
from app.services.text_chunker import TextChunker
def test_chunker_splits_text():
    result=TextChunker(500,100).split(ExtractedPDF([ExtractedPage(1,'A'*1800)]))
    assert len(result)>=4
    assert all(c.char_count<=500 for c in result)
def test_chunker_tracks_pages():
    pdf=ExtractedPDF([ExtractedPage(1,'Trang mot. '*50),ExtractedPage(2,'Trang hai. '*50)])
    chunks=TextChunker(400,50).split(pdf)
    assert chunks and any(c.page_start==1 and c.page_end==2 for c in chunks)
