import axios from 'axios';
export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1', timeout: 120000 });
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type DocumentItem = { id: string; original_filename: string; status: string; uploaded_at: string; updated_at?: string; file_size: number; page_count?: number | null; chunk_count: number; error_message?: string | null };
export type Candidate = { pair_id: string; entity_a: string; entity_b: string; evidence_a: string[]; evidence_b: string[]; fuzzy_score?: number | null; embedding_score?: number | null; final_score?: number | null; match_method: string; classification: string; decision?: string | null; review_status: string };
export const messageOf = (error: unknown) => { if (axios.isAxiosError(error)) return String(error.response?.data?.detail || error.message); return error instanceof Error ? error.message : 'Unexpected error'; };
