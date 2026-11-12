import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, NavLink, Route, Routes, useNavigate, useParams, useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Activity, ArrowLeft, ArrowRight, Check, ChevronRight, CircleHelp, Clock3, FilePlus2,
  FileText, Files, Gauge, GitMerge, LayoutDashboard, Loader2, Network, RefreshCw,
  Search, Settings as SettingsIcon, ShieldCheck, UploadCloud, Workflow, X, Languages,
  Download, Database, AlertCircle, CircleCheck, CircleX, Sparkles, Eye
} from 'lucide-react';
import { api, messageOf } from './api';
import type { Candidate, DocumentItem } from './api';

type Toast = { kind: 'success' | 'error' | 'info'; message: string };
const fmt = (value?: string | null) => value ? new Date(value).toLocaleString() : '—';
const bytes = (value: number) => value < 1024 * 1024 ? (value / 1024).toFixed(0) + ' KB' : (value / 1024 / 1024).toFixed(1) + ' MB';
const statusTone = (s: string) => ['FINALIZED','NEO4J_SYNCED','CHUNKED','EXTRACTED'].includes(s) ? 'success' : ['FAILED','SYNC_FAILED'].includes(s) ? 'danger' : ['HUMAN_REVIEW','ENTITY_RESOLUTION','PROCESSING'].includes(s) ? 'warning' : 'neutral';
const statusLabel = (s: string) => (s || 'UPLOADED').replaceAll('_',' ').toLowerCase().replace(/\b\w/g, x => x.toUpperCase());
const steps = [
  { key: 'processing', label: 'Processing', hint: 'Extract text and split into chunks', icon: Files },
  { key: 'extraction', label: 'Extraction', hint: 'Extract entities and relations with an LLM', icon: Sparkles },
  { key: 'entity-resolution', label: 'Entity Resolution', hint: 'Generate candidate entity pairs', icon: GitMerge },
  { key: 'human-review', label: 'Human Review', hint: 'Review and resolve candidate pairs', icon: ShieldCheck },
  { key: 'finalize', label: 'Finalize', hint: 'Build canonical entities and relations', icon: Check },
  { key: 'neo4j-sync', label: 'Neo4j Sync', hint: 'Synchronize the canonical graph', icon: Database },
];
const statusRank: Record<string, number> = { UPLOADED: 0, PENDING: 0, PROCESSING: 0, CHUNKED: 1, COMPLETED: 1, EXTRACTED: 2, ENTITY_RESOLUTION: 3, HUMAN_REVIEW: 3, FINALIZED: 5, NEO4J_SYNCED: 6, FAILED: 0 };

function App() {
  const { t, i18n } = useTranslation();
  const [toast, setToast] = useState<Toast | null>(null);
  const notify = (kind: Toast['kind'], message: string) => { setToast({ kind, message }); window.setTimeout(() => setToast(null), 4500); };
  const [langOpen, setLangOpen] = useState(false);
  const changeLanguage = (lang: string) => { i18n.changeLanguage(lang); localStorage.setItem('kg-language', lang); setLangOpen(false); };
  const location = useLocation();
  useEffect(() => { setLangOpen(false); }, [location.pathname]);
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-mark"><Network size={21}/></div>
      <div className="brand-name">KG Studio<span>DOCUMENT INTELLIGENCE</span></div>
      <div className="side-caption">WORKSPACE</div>
      <nav className="side-nav">
        <NavLink to="/" end><LayoutDashboard size={18}/>{t('dashboard')}</NavLink>
        <NavLink to="/documents"><Files size={18}/>{t('documents')}</NavLink>
      </nav>
      <div className="side-caption secondary-caption">PREFERENCES</div>
      <nav className="side-nav">
        <NavLink to="/settings"><SettingsIcon size={18}/>{t('settings')}</NavLink>
        <NavLink to="/guide"><CircleHelp size={18}/>{t('howToUse')}</NavLink>
      </nav>
      <div className="sidebar-bottom"><span className="online-dot"/> API workspace <span className="version">v1</span></div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <div className="topbar-title">Convert Vietnamese PDF to Knowledge Graph <span>· Neo4j</span></div>
        <div className="topbar-actions">
          <button className="icon-button" title="Language" onClick={() => setLangOpen(!langOpen)}><Languages size={17}/><span>{i18n.language.toUpperCase()}</span></button>
          {langOpen && <div className="language-menu"><button onClick={() => changeLanguage('en')}>English</button><button onClick={() => changeLanguage('vi')}>Tiếng Việt</button></div>}
        </div>
      </header>
      <div className="page-wrap">
        <Routes>
          <Route path="/" element={<Dashboard notify={notify}/>}/>
          <Route path="/documents" element={<Documents notify={notify}/>}/>
          <Route path="/documents/:id/:step" element={<Workspace notify={notify}/>}/>
          <Route path="/settings" element={<Settings notify={notify}/>}/>
          <Route path="/guide" element={<Guide/>}/>
          <Route path="*" element={<NotFound/>}/>
        </Routes>
      </div>
    </main>
    {toast && <div className={'toast '+toast.kind}><span>{toast.kind === 'success' ? <CircleCheck/> : toast.kind === 'error' ? <CircleX/> : <AlertCircle/>}</span>{toast.message}<button onClick={() => setToast(null)}><X size={15}/></button></div>}
  </div>;
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>;
}
function StatCard({ label, value, icon: Icon, note }: { label: string; value: number | string; icon: any; note?: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className="stat-icon"><Icon size={18}/></span></div><div className="stat-value">{Number(value).toLocaleString()}</div>{note && <div className="stat-note">{note}</div>}</div>;
}
function StatusPill({ status }: { status: string }) { return <span className={'status-pill '+statusTone(status)}><i/>{statusLabel(status)}</span>; }
function Empty({ title = 'Nothing here yet', detail = 'Data will appear after this step has been completed.' }: { title?: string; detail?: string }) { return <div className="empty-state"><div className="empty-icon"><Files size={23}/></div><strong>{title}</strong><span>{detail}</span></div>; }
function Loading() { return <div className="loading-state"><Loader2 className="spin" size={20}/> Loading data…</div>; }

function Dashboard({ notify }: { notify: (kind: Toast['kind'], message: string) => void }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['dashboard'], queryFn: async () => (await api.get('/dashboard')).data });
  if (q.isLoading) return <Loading/>;
  if (q.isError) return <ErrorPanel error={q.error} retry={() => q.refetch()}/>;
  const d = q.data;
  return <>
    <PageHeading eyebrow="OVERVIEW" title={t('dashboard')} description="A clear view of your document processing workspace." action={<button className="button secondary" onClick={() => q.refetch()}><RefreshCw size={16}/> {t('refresh')}</button>}/>
    <div className="stats-grid">
      <StatCard label="PDF documents" value={d.total_documents} icon={Files} note="All uploaded files"/>
      <StatCard label="Finalized documents" value={d.finalized_documents} icon={ShieldCheck} note="Canonical graph ready"/>
      <StatCard label="Raw entities extracted" value={d.raw_entity_count} icon={Activity} note="Across extracted documents"/>
      <StatCard label="Raw relations extracted" value={d.raw_relation_count} icon={Workflow} note="Across extracted documents"/>
      <StatCard label="Pairs awaiting review" value={d.pending_review_count} icon={GitMerge} note="Human review required"/>
    </div>
    <section className="panel">
      <div className="panel-heading"><div><h2>Recently uploaded</h2><p>Your latest documents and their current workflow status.</p></div><Link className="text-link" to="/documents">View all <ArrowRight size={15}/></Link></div>
      <DocumentTable documents={d.recent_documents.map((x: any) => ({id:x.document_id,original_filename:x.filename,status:x.status,uploaded_at:x.uploaded_at,updated_at:x.updated_at,file_size:0,chunk_count:0}))}/>
    </section>
  </>;
}

function Documents({ notify }: { notify: (kind: Toast['kind'], message: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const q = useQuery({ queryKey: ['documents', page, search, status], queryFn: async () => (await api.get('/documents', { params:{ page, page_size:10, search:search || undefined, status:status || undefined } })).data });
  const upload = useMutation({ mutationFn: async () => { if (!file) throw new Error('Choose a PDF file first.'); const form = new FormData(); form.append('file', file); return (await api.post('/documents/upload', form, { headers:{'Content-Type':'multipart/form-data'} })).data as DocumentItem; }, onSuccess: async (doc) => { notify('success','PDF uploaded successfully.'); setFile(null); await qc.invalidateQueries({queryKey:['documents']}); await qc.invalidateQueries({queryKey:['dashboard']}); window.location.href = '/documents/'+doc.id+'/processing'; }, onError: e => notify('error',messageOf(e)) });
  const docs: DocumentItem[] = q.data?.items || [];
  return <>
    <PageHeading eyebrow="WORKSPACE" title={t('documents')} description="Upload, monitor and process your Vietnamese PDF documents."/>
    <section className="upload-panel">
      <div className="upload-copy"><div className="upload-icon"><UploadCloud size={22}/></div><div><strong>Upload a PDF document</strong><p>PDF only · Maximum file size is configured by the API.</p></div></div>
      <div className="upload-actions"><label className="file-picker"><input type="file" accept="application/pdf,.pdf" onChange={e => setFile(e.target.files?.[0] || null)}/><FilePlus2 size={16}/>{file ? file.name : 'Choose PDF'}</label><button className="button primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? <Loader2 className="spin" size={16}/> : <UploadCloud size={16}/>} {t('upload')}</button></div>
    </section>
    <section className="panel">
      <div className="table-toolbar"><div><h2>All documents</h2><p>{q.data?.total ?? 0} documents in your workspace</p></div><div className="filters"><div className="search-field"><Search size={16}/><input value={search} onChange={e => {setSearch(e.target.value);setPage(1);}} placeholder={t('search')}/></div><select value={status} onChange={e => {setStatus(e.target.value);setPage(1);}}><option value="">All statuses</option>{['UPLOADED','CHUNKED','EXTRACTED','ENTITY_RESOLUTION','HUMAN_REVIEW','FINALIZED','NEO4J_SYNCED','FAILED'].map(s=><option key={s} value={s}>{statusLabel(s)}</option>)}</select></div></div>
      {q.isLoading ? <Loading/> : q.isError ? <ErrorPanel error={q.error} retry={() => q.refetch()}/> : <DocumentTable documents={docs}/>}
      <Pagination page={page} pageSize={10} total={q.data?.total || 0} onPage={setPage}/>
    </section>
  </>;
}

function DocumentTable({ documents }: { documents: DocumentItem[] }) {
  return <div className="table-scroll"><table><thead><tr><th>Document</th><th>Status</th><th>Last updated</th><th>Size</th><th></th></tr></thead><tbody>
    {documents.length === 0 ? <tr><td colSpan={5}><Empty title="No documents found" detail="Upload a PDF to start building your knowledge graph."/></td></tr> : documents.map(doc => <tr key={doc.id}><td><div className="file-cell"><span className="pdf-icon"><FileText size={17}/></span><div><strong>{doc.original_filename}</strong><small>PDF document</small></div></div></td><td><StatusPill status={doc.status}/></td><td>{fmt(doc.updated_at || doc.uploaded_at)}</td><td>{doc.file_size ? bytes(doc.file_size) : '—'}</td><td><Link className="row-action" to={'/documents/'+doc.id+'/processing'}>Open <ChevronRight size={15}/></Link></td></tr>)}
  </tbody></table></div>;
}
function Pagination({ page, pageSize, total, onPage }: { page:number; pageSize:number; total:number; onPage:(n:number)=>void }) {
  const pages = Math.max(1,Math.ceil(total/pageSize));
  return <div className="pagination"><span>Showing {total ? (page-1)*pageSize+1 : 0}–{Math.min(page*pageSize,total)} of {total}</span><div><button disabled={page<=1} onClick={()=>onPage(page-1)}>Previous</button><span>{page} / {pages}</span><button disabled={page>=pages} onClick={()=>onPage(page+1)}>Next</button></div></div>;
}
function ErrorPanel({ error, retry }: { error: unknown; retry:()=>void }) { return <div className="error-panel"><AlertCircle size={18}/><div><strong>Unable to load data</strong><span>{messageOf(error)}</span></div><button className="button secondary small" onClick={retry}>Retry</button></div>; }

function Workspace({ notify }: { notify:(kind:Toast['kind'],message:string)=>void }) {
  const { id = '', step = 'processing' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const qc = useQueryClient();
  const docQ = useQuery({ queryKey:['document',id], queryFn:async()=> (await api.get('/documents/'+id)).data as DocumentItem });
  const workflowQ = useQuery({ queryKey:['workflow',id], queryFn:async()=> (await api.get('/documents/'+id+'/workflow')).data, enabled:!!id });
  const doc = docQ.data;
  const rank = statusRank[doc?.status || 'UPLOADED'] ?? 0;
  const activeIndex = steps.findIndex(s=>s.key===step);
  const currentIndex = Math.max(0,Math.min(5,rank));
  const erCompleted = Boolean(workflowQ.data?.entity_resolution?.completed);
  const pendingReview = workflowQ.data?.entity_resolution?.pending_count;
  const reviewCompleted = erCompleted && pendingReview === 0;
  const completedThrough = doc?.status === 'NEO4J_SYNCED' ? 5
    : currentIndex === 0 ? -1
    : currentIndex === 3 ? (reviewCompleted ? 3 : 2)
    : currentIndex - 1;
  const canVisit = (index:number) => index <= completedThrough || index === currentIndex
    || (index === 3 && erCompleted) || (index === 4 && erCompleted) || (index === 5 && rank >= 5);
  const refresh = async () => { await Promise.all([qc.invalidateQueries({queryKey:['document',id]}),qc.invalidateQueries({queryKey:['workflow',id]}),qc.invalidateQueries({queryKey:['dashboard']}),qc.invalidateQueries({queryKey:['documents']})]); };
  if (docQ.isLoading) return <Loading/>;
  if (docQ.isError || !doc) return <ErrorPanel error={docQ.error} retry={()=>docQ.refetch()}/>;
  if (activeIndex < 0) return <NotFound/>;
  const goNext = () => {
    const next = steps[activeIndex+1];
    if (next) navigate('/documents/'+id+'/'+next.key);
  };
  return <div className="workspace">
    <div className="workspace-head"><div><Link to="/documents" className="back-link"><ArrowLeft size={15}/> All documents</Link><div className="doc-title-row"><div className="pdf-icon large"><FileText size={20}/></div><div><h1>{doc.original_filename}</h1><span>{doc.page_count ? doc.page_count+' pages' : 'PDF document'} · {bytes(doc.file_size)}</span></div><StatusPill status={doc.status}/></div></div></div>
    <div className="workflow-bar"><div className="workflow-label">DOCUMENT WORKFLOW</div><div className="workflow-steps">{steps.map((s,i)=>{const Icon=s.icon;const done=i<=completedThrough;const active=i===currentIndex;const disabled=!canVisit(i);return <button key={s.key} className={'workflow-step '+(done?'done ':'')+(active?'active ':'')+(disabled?'disabled':'')} disabled={disabled} onClick={()=>navigate('/documents/'+id+'/'+s.key)} title={disabled?'Complete previous steps first':s.label}><span className="workflow-icon">{done?<Check size={15}/>:<Icon size={15}/>}</span><span>{s.label}</span>{active&&<em>You are here</em>}</button>;})}</div></div>
    {!canVisit(activeIndex) && <div className="notice warning"><AlertCircle size={17}/> This step is not available yet. Complete the previous step first.</div>}
    {canVisit(activeIndex) && <div className="step-content">
      <StepPage step={step} id={id} doc={doc} workflow={workflowQ.data} notify={notify} refresh={refresh} onNext={goNext} onGoStep={(s)=>navigate('/documents/'+id+'/'+s)}/>
    </div>}
  </div>;
}

function StepPage({step,id,doc,workflow,notify,refresh,onNext,onGoStep}:{step:string;id:string;doc:DocumentItem;workflow:any;notify:(k:Toast['kind'],m:string)=>void;refresh:()=>Promise<void>;onNext:()=>void;onGoStep:(s:string)=>void}) {
  const {t}=useTranslation();
  const qc=useQueryClient();
  const [page,setPage]=useState(1);
  const [search,setSearch]=useState('');
  const [selected,setSelected]=useState<Candidate|null>(null);
  const [entityTab,setEntityTab]=useState<'entities'|'relations'>('entities');
  const [neoHealth,setNeoHealth]=useState<any>(null);
  const [autoMergeBeforeFinalize,setAutoMergeBeforeFinalize]=useState(true);
  const processQ=useQuery({queryKey:['chunks',id,page],queryFn:async()=> (await api.get('/documents/'+id+'/chunks',{params:{page,page_size:10}})).data,enabled:step==='processing'&&doc.status!=='UPLOADED'});
  const rawE=useQuery({queryKey:['raw-entities',id,page,search],queryFn:async()=> (await api.get('/documents/'+id+'/raw-entities',{params:{page,page_size:10,search:search||undefined}})).data,enabled:step==='extraction'&&doc.status!=='CHUNKED'});
  const rawR=useQuery({queryKey:['raw-relations',id,page,search],queryFn:async()=> (await api.get('/documents/'+id+'/raw-relations',{params:{page,page_size:10,search:search||undefined}})).data,enabled:step==='extraction'&&doc.status!=='CHUNKED'});
  const candidatesQ=useQuery({queryKey:['candidates',id,page],queryFn:async()=> (await api.get('/documents/'+id+'/entity-resolution/candidates',{params:{page,page_size:10}})).data,enabled:['entity-resolution','human-review'].includes(step)});
  const summaryQ=useQuery({queryKey:['er-summary',id],queryFn:async()=> (await api.get('/documents/'+id+'/entity-resolution/summary')).data,enabled:['entity-resolution','human-review','finalize'].includes(step)&&doc.status!=='EXTRACTED'});
  const canonE=useQuery({queryKey:['canonical-entities',id],queryFn:async()=> (await api.get('/documents/'+id+'/entity-resolution/canonical-entities')).data,enabled:step==='finalize'&&['FINALIZED','NEO4J_SYNCED'].includes(doc.status)});
  const canonR=useQuery({queryKey:['canonical-relations',id],queryFn:async()=> (await api.get('/documents/'+id+'/entity-resolution/canonical-relations')).data,enabled:step==='finalize'&&['FINALIZED','NEO4J_SYNCED'].includes(doc.status)});
  const run=useMutation({mutationFn:async()=>{if(step==='processing')return (await api.post('/documents/'+id+'/process')).data;if(step==='extraction')return (await api.post('/documents/'+id+'/extract')).data;if(step==='entity-resolution')return (await api.post('/documents/'+id+'/entity-resolution/preview')).data;if(step==='finalize')return (await api.post('/documents/'+id+'/entity-resolution/finalize')).data;if(step==='neo4j-sync')return (await api.post('/documents/'+id+'/entity-resolution/sync-neo4j')).data;},onSuccess:async()=>{notify('success',step==='neo4j-sync'?'Knowledge graph synchronized to Neo4j.':step==='finalize'?'Entity Resolution finalized successfully.':step==='entity-resolution'?'Candidate generation completed.':'Step completed successfully.');await refresh();await Promise.all([qc.invalidateQueries({queryKey:['chunks',id]}),qc.invalidateQueries({queryKey:['raw-entities',id]}),qc.invalidateQueries({queryKey:['raw-relations',id]}),qc.invalidateQueries({queryKey:['candidates',id]}),qc.invalidateQueries({queryKey:['er-summary',id]}),qc.invalidateQueries({queryKey:['canonical-entities',id]}),qc.invalidateQueries({queryKey:['canonical-relations',id]})]);},onError:e=>notify('error',messageOf(e))});
  const decision=useMutation({mutationFn:async({pair,choice}:{pair:string;choice:string})=>choice==='KEEP_SEPARATE'?api.post('/documents/'+id+'/entity-resolution/candidates/'+pair+'/keep-separate'):api.post('/documents/'+id+'/entity-resolution/candidates/'+pair+'/decision',{decision:choice}),onSuccess:async()=>{notify('success','Candidate decision saved.');setSelected(null);await Promise.all([qc.invalidateQueries({queryKey:['candidates',id]}),qc.invalidateQueries({queryKey:['er-summary',id]}),refresh()]);},onError:e=>notify('error',messageOf(e))});
  const autoMerge=useMutation({mutationFn:()=>api.post('/documents/'+id+'/entity-resolution/auto-merge'),onSuccess:async(r)=>{notify('success',r.data.merged_or_already_same_cluster+' candidates merged; '+r.data.blocked_by_keep_separate+' blocked by separation rules.');await Promise.all([qc.invalidateQueries({queryKey:['candidates',id]}),qc.invalidateQueries({queryKey:['er-summary',id]}),refresh()]);},onError:e=>notify('error',messageOf(e))});
  const continueToFinalize=useMutation({mutationFn:async()=>{let autoMergeResult=null;if(autoMergeBeforeFinalize){autoMergeResult=(await api.post('/documents/'+id+'/entity-resolution/auto-merge')).data;}const finalized=(await api.post('/documents/'+id+'/entity-resolution/finalize')).data;return {autoMergeResult,finalized};},onSuccess:async(result)=>{const merged=result.autoMergeResult?.merged_or_already_same_cluster??0;const blocked=result.autoMergeResult?.blocked_by_keep_separate??0;notify('success',`Finalized successfully. ${merged} candidate(s) merged; ${blocked} blocked by KEEP_SEPARATE. Remaining pending candidates were skipped.`);setSelected(null);await refresh();await Promise.all([qc.invalidateQueries({queryKey:['candidates',id]}),qc.invalidateQueries({queryKey:['er-summary',id]}),qc.invalidateQueries({queryKey:['canonical-entities',id]}),qc.invalidateQueries({queryKey:['canonical-relations',id]})]);onGoStep('finalize');},onError:e=>notify('error',messageOf(e))});
  const exportReport=async(type:string)=>{try{const r=await api.get('/documents/'+id+'/reports/'+type+'/download',{responseType:'blob'});const url=URL.createObjectURL(r.data);const a=document.createElement('a');a.href=url;a.download=(r.headers['content-disposition']?.match(/filename="?([^"]+)"?/)||[])[1]||('report.'+(type==='cypher'?'txt':'xlsx'));a.click();URL.revokeObjectURL(url);notify('success','Report downloaded.');}catch(e){notify('error',messageOf(e));}};
  const checkNeo=async()=>{try{const r=await api.get('/neo4j/health');setNeoHealth(r.data);notify(r.data.connected?'success':'error',r.data.message);}catch(e){notify('error',messageOf(e));}};
  const hasCandidates=!!candidatesQ.data;
  const pending=summaryQ.data?.pending_count ?? workflow?.entity_resolution?.pending_count;
  const done = step==='processing'?doc.status!=='UPLOADED'&&doc.status!=='FAILED'
    :step==='extraction'?['EXTRACTED','ENTITY_RESOLUTION','HUMAN_REVIEW','FINALIZED','NEO4J_SYNCED'].includes(doc.status)
    :step==='entity-resolution'?Boolean(workflow?.entity_resolution?.completed)
    :step==='human-review'?Boolean(workflow?.entity_resolution?.completed)
    :step==='finalize'?doc.status==='FINALIZED'||doc.status==='NEO4J_SYNCED'
    :step==='neo4j-sync'?doc.status==='NEO4J_SYNCED':false;
  const canNext = step==='human-review'?Boolean(workflow?.entity_resolution?.completed):done;
  const heading = steps.find(x=>x.key===step)?.label || 'Workflow';
  const description = steps.find(x=>x.key===step)?.hint || '';
  const titleAction = <div className="step-actions">{step==='entity-resolution'&&done&&!['FINALIZED','NEO4J_SYNCED'].includes(doc.status)&&<button className="button secondary" onClick={()=>exportReport('preview')}><Download size={16}/> Preview report</button>}{step==='finalize'&&done&&<button className="button secondary" onClick={()=>exportReport('final')}><Download size={16}/> Final report</button>}{step==='neo4j-sync'&&<button className="button secondary" onClick={()=>exportReport('cypher')}><Download size={16}/> Export Cypher</button>}</div>;
  return <div className="step-page">
    <div className="step-page-head"><div><div className="eyebrow">STEP {steps.findIndex(x=>x.key===step)+1} OF 6</div><h2>{step==='entity-resolution'&&done?'View Candidates':heading}</h2><p>{description}</p></div>{titleAction}</div>
    {step==='processing'&&<><div className="explain-card"><div className="explain-icon"><Files/></div><div><strong>Prepare your PDF</strong><p>The API extracts text, detects pages and splits the content into overlapping chunks. You can inspect the resulting chunks below.</p></div></div>{!done&&<StartCard title="Start PDF processing" description="This step runs locally and may take a short time depending on the PDF size." button={t('start')} loading={run.isPending} onStart={()=>run.mutate()}/>}{done&&<><div className="mini-stats"><MiniStat label="Pages" value={doc.page_count||0}/><MiniStat label="Chunks" value={doc.chunk_count}/></div><DataTable loading={processQ.isLoading} rows={processQ.data?.items||[]} columns={[['chunk_index','Chunk'],['char_count','Characters'],['page_start','Start page'],['page_end','End page']]} render={(x:any)=><td className="truncate-cell" title={x.content}>{x.content.slice(0,150)}{x.content.length>150?'…':''}</td>}/><Pagination page={page} pageSize={10} total={processQ.data?.total||0} onPage={setPage}/></>}</>}
    {step==='extraction'&&<><div className="explain-card"><div className="explain-icon purple"><Sparkles/></div><div><strong>LLM-powered information extraction</strong><p>This step sends each text chunk to your configured LLM provider. It may take several minutes depending on document size, internet speed, provider latency and rate limits. Keep this browser tab open while the request is running. If it fails, you can retry safely; completed chunks are skipped unless force retry is requested.</p></div></div>{!done&&<StartCard title="Start entity and relation extraction" description="The API processes pending chunks and stores raw entities, aliases, relations and evidence." button={t('start')} loading={run.isPending} onStart={()=>run.mutate()}/>}{done&&<><div className="mini-stats"><MiniStat label="Raw entities" value={workflow?.extraction?.raw_entity_count||0}/><MiniStat label="Raw relations" value={workflow?.extraction?.raw_relation_count||0}/></div><div className="tabs"><button className={entityTab==='entities'?'active':''} onClick={()=>{setEntityTab('entities');setPage(1)}}>Entities ({workflow?.extraction?.raw_entity_count||0})</button><button className={entityTab==='relations'?'active':''} onClick={()=>{setEntityTab('relations');setPage(1)}}>Relations ({workflow?.extraction?.raw_relation_count||0})</button></div><div className="table-toolbar compact"><div className="search-field"><Search size={15}/><input value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}} placeholder="Search names or relation endpoints"/></div></div>{entityTab==='entities'?<DataTable loading={rawE.isLoading} rows={rawE.data?.items||[]} columns={[['name','Name'],['entity_type','Type'],['confidence','Confidence']]} render={(x:any)=><td><span className="secondary-text">{(x.aliases||[]).slice(0,3).join(', ')||'No aliases'}</span><button className="inline-detail" onClick={()=>notify('info',(x.description||'No description')+' · Evidence: '+(x.evidence||[]).join(' | '))}>Details</button></td>}/>:<DataTable loading={rawR.isLoading} rows={rawR.data?.items||[]} columns={[['subject','Subject'],['relation_type','Relation'],['object','Object']]} render={(x:any)=><td><button className="inline-detail" onClick={()=>notify('info',(x.description||'No description')+' · '+(x.evidence||''))}>Evidence</button></td>}/>}<Pagination page={page} pageSize={10} total={entityTab==='entities'?(rawE.data?.total||0):(rawR.data?.total||0)} onPage={setPage}/></>}</>}
    {step==='entity-resolution'&&<><div className="explain-card"><div className="explain-icon amber"><GitMerge/></div><div><strong>Generate possible duplicate pairs</strong><p>Exact matching, fuzzy matching and semantic similarity are used to identify candidate pairs. This step does not merge entities; review decisions happen in the next stage.</p></div></div>{!done?<StartCard title="Generate ER candidates" description="The embedding model may need to load on the first run. Candidate generation can take a few minutes." button={t('start')} loading={run.isPending} onStart={()=>run.mutate()}/>:<><SummaryCards data={summaryQ.data}/><CandidateTable candidates={candidatesQ.data?.items||[]} onSelect={setSelected} readOnly/><Pagination page={page} pageSize={10} total={candidatesQ.data?.total||0} onPage={setPage}/></>}</>}
    {step==='human-review'&&<><div className="explain-card"><div className="explain-icon green"><ShieldCheck/></div><div><strong>Review candidate pairs</strong><p>Inspect names, aliases, scores and source evidence. Merge only when both records refer to the same real-world entity. Keep different entities separate. Skip uncertain pairs. You can also finish without reviewing every candidate.</p></div><button className="button secondary" disabled={autoMerge.isPending||!summaryQ.data?.auto_merge_count} onClick={()=>autoMerge.mutate()}><GitMerge size={16}/> {t('autoMerge')}</button></div><SummaryCards data={summaryQ.data}/><div className="review-toolbar"><div className="search-field"><Search size={15}/><input placeholder="Filter loaded candidates" value={search} onChange={e=>setSearch(e.target.value)}/></div><span>{pending} pending decisions</span></div><CandidateTable candidates={(candidatesQ.data?.items||[]).filter((x:Candidate)=>!search||x.entity_a.toLowerCase().includes(search.toLowerCase())||x.entity_b.toLowerCase().includes(search.toLowerCase()))} onSelect={setSelected}/><Pagination page={page} pageSize={10} total={candidatesQ.data?.total||0} onPage={setPage}/>{pending>0&&<div className="notice info"><AlertCircle size={17}/>{pending} candidate(s) remain pending. Next will finalize the document; unresolved candidates will be recorded as SKIP.</div>}</>}
    {step==='finalize'&&<>{!done?<><div className="explain-card"><div className="explain-icon green"><Check/></div><div><strong>Finalize canonical data</strong><p>Finalize applies pending AUTO_MERGE candidates, marks remaining undecided candidates as SKIP, refreshes canonical aliases and projects raw relations onto canonical entities.</p></div></div><SummaryCards data={summaryQ.data}/><StartCard title="Finalize Entity Resolution" description="This operation closes the current ER run. Review decisions cannot be changed afterward. Export the report separately when needed." button="Finalize document" loading={run.isPending} onStart={()=>run.mutate()}/></>:<><div className="success-banner"><CircleCheck/><div><strong>Entity Resolution finalized</strong><span>Canonical records are ready for Neo4j synchronization.</span></div></div><SummaryCards data={summaryQ.data}/><div className="tabs"><button className={entityTab==='entities'?'active':''} onClick={()=>setEntityTab('entities')}>Canonical entities ({canonE.data?.items?.length||0})</button><button className={entityTab==='relations'?'active':''} onClick={()=>setEntityTab('relations')}>Canonical relations ({canonR.data?.items?.length||0})</button></div>{entityTab==='entities'?<DataTable rows={canonE.data?.items||[]} columns={[['name','Canonical entity'],['entity_type','Type']]} render={(x:any)=><td>{(x.aliases||[]).join(', ')||'—'}<small className="block-muted">{x.raw_entity_ids?.length||0} raw members</small></td>}/>:<DataTable rows={canonR.data?.items||[]} columns={[['canonical_subject_name','Subject'],['relation_type','Relation'],['canonical_object_name','Object']]} render={(x:any)=><td>{x.raw_relation_count} source relation(s)<small className="block-muted">{(x.evidence||[]).slice(0,1).join(' ')}</small></td>}/>}</>}</>}
    {step==='neo4j-sync'&&<><div className="explain-card"><div className="explain-icon blue"><Database/></div><div><strong>Synchronize canonical graph</strong><p>Check Neo4j connectivity before writing. The sync replaces only this document's graph. You can also export a Cypher script without connecting to Neo4j.</p></div></div><div className="connection-card"><div><span className="eyebrow">NEO4J CONNECTION</span><strong>{neoHealth?.connected?'Connection verified':neoHealth?'Connection unavailable':'Not checked yet'}</strong><p>{neoHealth?.message||'Check your configured Neo4j connection before starting synchronization.'}</p></div><button className="button secondary" onClick={checkNeo}><Activity size={16}/> Test connection</button></div>{doc.status==='NEO4J_SYNCED'?<div className="success-banner"><CircleCheck/><div><strong>Graph synchronized</strong><span>The current document graph is available in Neo4j.</span></div></div>:<StartCard title="Sync to Neo4j" description="This action requires valid Neo4j credentials and a finalized ER run." button="Start synchronization" loading={run.isPending} disabled={!neoHealth?.connected} onStart={()=>run.mutate()}/>}<div className="export-card"><div><strong>Export Cypher script</strong><p>Generate a repeatable Cypher file from the finalized canonical graph. This does not require a live Neo4j connection.</p></div><button className="button secondary" onClick={()=>exportReport('cypher')}><Download size={16}/> Export Cypher</button></div></>}
    {selected&&<CandidateDrawer candidate={selected} id={id} readOnly={step==='entity-resolution'} onClose={()=>setSelected(null)} onDecision={(choice)=>decision.mutate({pair:selected.pair_id,choice})} loading={decision.isPending}/> }
    {step==='human-review'&&<label className="auto-merge-option"><input type="checkbox" checked={autoMergeBeforeFinalize} onChange={e=>setAutoMergeBeforeFinalize(e.target.checked)}/><span><strong>Auto-merge before Finalize</strong><small>Recommended and enabled by default. Applies only to candidates classified AUTO_MERGE; remaining pending candidates become SKIP.</small></span></label>}
    <div className="step-footer"><span>{step==='human-review'?'You can continue now. Unreviewed candidates will be skipped during Finalize.':done?'This step is complete. You can revisit it at any time.':'Complete this step to unlock the next stage.'}</span><button className="button primary" disabled={!canNext||continueToFinalize.isPending} onClick={()=>step==='human-review'?continueToFinalize.mutate():onNext()}>{step==='human-review'?(continueToFinalize.isPending?<><Loader2 className="spin" size={16}/> Finalizing…</>:'Next: Finalize'):t('next')} <ArrowRight size={16}/></button></div>
  </div>;
}

function StartCard({title,description,button,loading,onStart,disabled=false}:{title:string;description:string;button:string;loading:boolean;onStart:()=>void;disabled?:boolean}) {
 return <div className="start-card"><div className="start-card-icon"><Activity size={20}/></div><div className="start-card-copy"><strong>{title}</strong><p>{description}</p></div><button className="button primary" disabled={disabled||loading} onClick={onStart}>{loading?<><Loader2 className="spin" size={16}/> Working…</>:<>{button}<ArrowRight size={16}/></>}</button></div>;
}
function MiniStat({label,value}:{label:string;value:number|string}) {return <div className="mini-stat"><span>{label}</span><strong>{Number(value).toLocaleString()}</strong></div>;}
function SummaryCards({data}:{data:any}) {
 if(!data)return null;
 return <div className="mini-stats four"><MiniStat label="Candidates" value={data.candidate_count||0}/><MiniStat label="Pending" value={data.pending_count||0}/><MiniStat label="Merged" value={data.merged_count||0}/><MiniStat label="Kept separate" value={data.kept_separate_count||0}/></div>;
}
function DataTable({rows,columns,render,loading=false}:{rows:any[];columns:[string,string][];render?:(row:any)=>ReactNode;loading?:boolean}) {
 return <div className="table-scroll"><table><thead><tr>{columns.map(c=><th key={c[0]}>{c[1]}</th>)}{render&&<th>Details</th>}</tr></thead><tbody>{loading?<tr><td colSpan={columns.length+(render?1:0)}><Loading/></td></tr>:rows.length===0?<tr><td colSpan={columns.length+(render?1:0)}><Empty/></td></tr>:rows.map((row,i)=><tr key={row.id||row.pair_id||i}>{columns.map(c=><td key={c[0]}>{typeof row[c[0]]==='number'&&c[0].includes('score')?(row[c[0]]*100).toFixed(1)+'%':String(row[c[0]]??'—')}</td>)}{render&&render(row)}</tr>)}</tbody></table></div>;
}
function CandidateTable({candidates,onSelect,readOnly=false}:{candidates:Candidate[];onSelect:(c:Candidate)=>void;readOnly?:boolean}) {
 return <div className="table-scroll"><table><thead><tr><th>Entity A</th><th></th><th>Entity B</th><th>Score</th><th>Method</th><th>Classification</th><th>Status</th></tr></thead><tbody>{candidates.length===0?<tr><td colSpan={7}><Empty title="No candidate pairs" detail="Candidate pairs will appear after Entity Resolution preview."/></td></tr>:candidates.map(c=><tr key={c.pair_id} className={'clickable-row '+(readOnly?'read-only-row':'')} title={readOnly?'View candidate details (read-only)':'Review candidate'} onClick={()=>onSelect(c)}><td><strong>{c.entity_a}</strong><small className="block-muted">{c.evidence_a?.[0]||'No evidence snapshot'}</small></td><td className="versus">↔</td><td><strong>{c.entity_b}</strong><small className="block-muted">{c.evidence_b?.[0]||'No evidence snapshot'}</small></td><td>{c.final_score==null?'—':(c.final_score*100).toFixed(1)+'%'}</td><td>{c.match_method.replaceAll('_',' ')}</td><td><span className="tag">{c.classification}</span></td><td><StatusPill status={c.review_status}/></td></tr>)}</tbody></table></div>;
}
function CandidateDrawer({candidate,id,readOnly=false,onClose,onDecision,loading}:{candidate:Candidate;id:string;readOnly?:boolean;onClose:()=>void;onDecision:(choice:string)=>void;loading:boolean}) {
 const q=useQuery({queryKey:['candidate-detail',id,candidate.pair_id],queryFn:async()=> (await api.get('/documents/'+id+'/entity-resolution/candidates/'+candidate.pair_id)).data});
 const d=q.data;
 return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className="candidate-drawer"><div className="drawer-head"><div><span className="eyebrow">CANDIDATE REVIEW</span><h2>Compare entities</h2></div><button className="icon-button" onClick={onClose}><X size={18}/></button></div>{q.isLoading?<Loading/>:q.isError?<ErrorPanel error={q.error} retry={()=>q.refetch()}/>:<><div className="compare-grid"><EntityDetail title="Entity A" entity={d.entity_a} evidence={d.evidence_a}/><div className="compare-divider">VS</div><EntityDetail title="Entity B" entity={d.entity_b} evidence={d.evidence_b}/></div><div className="score-grid"><MiniStat label="Fuzzy" value={d.fuzzy_score==null?'—':(d.fuzzy_score*100).toFixed(1)+'%'}/><MiniStat label="Embedding" value={d.embedding_score==null?'—':(d.embedding_score*100).toFixed(1)+'%'}/><MiniStat label="Final score" value={d.final_score==null?'—':(d.final_score*100).toFixed(1)+'%'}/></div><div className="match-info"><span>Method <strong>{d.match_method}</strong></span><span>Classification <strong>{d.classification}</strong></span><span>Status <strong>{d.review_status}</strong></span></div>{readOnly?<div className="notice info"><Eye size={16}/> Preview mode: decisions are available in Human Review.</div>:d.review_status==='PENDING'?<div className="decision-actions"><button className="button success-button" disabled={loading} onClick={()=>onDecision('MERGE')}><GitMerge size={16}/> Merge entities</button><button className="button danger-outline" disabled={loading} onClick={()=>onDecision('KEEP_SEPARATE')}><ShieldCheck size={16}/> Keep separate</button><button className="button secondary" disabled={loading} onClick={()=>onDecision('SKIP')}>Skip</button></div>:<div className="notice success"><Check size={16}/> Decision recorded: {d.decision||d.review_status}</div>}</>}</div></div>;
}
function EntityDetail({title,entity,evidence}:{title:string;entity:any;evidence:string[]}) {
 if(!entity)return <div className="entity-detail"><strong>{title}</strong><Empty/></div>;
 return <div className="entity-detail"><span className="eyebrow">{title}</span><h3>{entity.name}</h3><span className="tag">{entity.entity_type}</span><div className="detail-label">Aliases</div><div className="alias-list">{(entity.aliases||[]).length?(entity.aliases||[]).map((x:string)=><span key={x}>{x}</span>):<small>None</small>}</div><div className="detail-label">Description</div><p>{entity.description||'No description provided.'}</p><div className="detail-label">Evidence</div><div className="evidence-list">{(evidence||entity.evidence||[]).map((x:string,i)=><blockquote key={i}>{x}</blockquote>)}</div><small className="block-muted">Confidence: {entity.confidence==null?'—':(entity.confidence*100).toFixed(0)+'%'}</small></div>;
}

function Settings({notify}:{notify:(k:Toast['kind'],m:string)=>void}) {
 const [health,setHealth]=useState<any>(null);
 const [busy,setBusy]=useState(false);
 const check=async()=>{setBusy(true);try{const r=await api.get('/neo4j/health');setHealth(r.data);notify(r.data.connected?'success':'error',r.data.message);}catch(e){notify('error',messageOf(e));}finally{setBusy(false);}};
 return <><PageHeading eyebrow="PREFERENCES" title="Settings" description="Connection and application configuration."/><section className="panel settings-panel"><div className="settings-row"><div className="settings-icon"><Database/></div><div className="settings-copy"><strong>Neo4j database</strong><p>Verify that the backend can connect to the configured Neo4j instance. Credentials remain on the server.</p>{health&&<StatusPill status={health.connected?'CONNECTED':'FAILED'}/>}</div><button className="button secondary" disabled={busy} onClick={check}>{busy?<Loader2 className="spin" size={16}/>:<RefreshCw size={16}/>} Test connection</button></div><div className="settings-row"><div className="settings-icon"><Languages/></div><div className="settings-copy"><strong>Interface language</strong><p>Choose English or Vietnamese for interface labels.</p></div><div className="language-switch"><button onClick={()=>{localStorage.setItem('kg-language','en');window.location.reload()}}>English</button><button onClick={()=>{localStorage.setItem('kg-language','vi');window.location.reload()}}>Tiếng Việt</button></div></div><div className="settings-row"><div className="settings-icon"><Activity/></div><div className="settings-copy"><strong>Backend API</strong><p>{import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000/api/v1'}</p></div><StatusPill status="CONFIGURED"/></div></section></>;
}
function Guide() {
 return <><PageHeading eyebrow="DOCUMENTATION" title="How to use" description="Follow the workflow in order. Completed stages can be revisited; future stages stay locked."/><div className="guide-grid">{[
 ['01','Upload PDF','Add a PDF from the Documents page. Each upload creates an independent document workspace.'],
 ['02','Processing','Extract text from the PDF and split it into chunks. Inspect chunk count and page ranges.'],
 ['03','Extraction','Send chunks to the configured LLM. Raw entities, aliases, relations and evidence are saved.'],
 ['04','Entity Resolution','Generate duplicate candidates using string and semantic similarity. No merge is performed at this stage.'],
 ['05','Human Review','Inspect candidate evidence. Merge same entities, keep different entities separate, or skip uncertain pairs. Auto merge applies only to AUTO_MERGE candidates.'],
 ['06','Finalize','Close the ER run and build canonical entities and deduplicated canonical relations. Pending candidates are treated as SKIP.'],
 ['07','Neo4j Sync','Test the database connection, then synchronize the finalized graph. You can export a Cypher script separately.']
 ].map(x=><div className="guide-card" key={x[0]}><span>{x[0]}</span><div><strong>{x[1]}</strong><p>{x[2]}</p></div></div>)}</div><div className="notice warning"><AlertCircle size={17}/> Finalize is irreversible for the current ER run. To run Entity Resolution again, follow the backend reset procedure first.</div></>;
}
function NotFound() { return <div className="empty-state large-empty"><div className="empty-icon"><Search/></div><strong>Page not found</strong><span>The page may have moved or the document does not exist.</span><Link className="button secondary" to="/documents">Back to documents</Link></div>; }

export default App;
