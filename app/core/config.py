from pathlib import Path
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    database_url:str='sqlite:///./data/app.db'
    storage_dir:str='./storage/documents'
    extracted_text_dir:str='./storage/extracted'
    max_upload_size_mb:int=30
    chunk_size:int=1000
    chunk_overlap:int=150
    model_config=SettingsConfigDict(env_file='.env',env_file_encoding='utf-8',extra='ignore')
settings=Settings()
Path(settings.storage_dir).mkdir(parents=True,exist_ok=True)
Path(settings.extracted_text_dir).mkdir(parents=True,exist_ok=True)
