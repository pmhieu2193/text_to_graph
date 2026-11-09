from pathlib import Path
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    database_url:str='sqlite:///./data/app.db'
    storage_dir:Path='./storage/documents'
    extracted_text_dir:str='./storage/extracted'
    max_upload_size_mb:int=30
    chunk_size:int=1000
    chunk_overlap:int=150
    model_config=SettingsConfigDict(env_file='.env',env_file_encoding='utf-8',extra='ignore')
    
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024
    
settings=Settings()
Path(settings.storage_dir).mkdir(parents=True,exist_ok=True)
Path(settings.extracted_text_dir).mkdir(parents=True,exist_ok=True)
