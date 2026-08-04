"""Generate a static Classroom-like website from the backups/ directory."""
from __future__ import annotations

import html
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUPS = BASE_DIR / "site" / "backups"
SITE = BASE_DIR / "site"

COURSE_BANNER_COLORS = [
    "#0f9d58", "#4285f4", "#f4b400", "#db4437", "#9c27b0",
    "#00bcd4", "#ff7043", "#5c6bc0", "#66bb6a", "#ec407a",
    "#26a69a", "#ab47bc",
]


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_courses() -> list[dict]:
    courses = []
    if not BACKUPS.exists():
        return courses
    for d in sorted(BACKUPS.iterdir()):
        if not d.is_dir():
            continue
        course = _load(d / "course.json")
        if not course:
            continue
        slug = d.name
        topics = _load(d / "topics.json") or []
        announcements = _load(d / "announcements.json") or []
        coursework = _load(d / "coursework.json") or []
        cw_materials = _load(d / "coursework_materials.json") or []
        mats_index = _load(d / "materials_index.json") or []
        errors = _load(d / "errors.json") or []
        links = _load(d / "links.json") or []
        forms = _load(d / "forms.json") or []

        # id -> saved file info map (for attachment linking)
        file_map: dict[str, dict] = {}
        materials = []
        for m in mats_index:
            fname = m.get("filename") or Path(m.get("path", "")).name
            rel = f"backups/{slug}/materials/{fname}"
            info = {
                "id": m.get("id"),
                "name": m.get("name") or m.get("originalFilename") or fname,
                "url": rel,
                "mimeType": m.get("mimeType", ""),
                "size": m.get("size"),
                "exported": m.get("exportedAs"),
                "modified": m.get("modifiedTime", ""),
                "via": m.get("downloadedVia", ""),
                "transcripts": [],
            }
            for tr in (m.get("transcripts") or []):
                vtt_name = tr.get("vtt") or Path(tr.get("vtt", "")).name
                if vtt_name:
                    info["transcripts"].append({
                        "lang": tr.get("lang", ""),
                        "url": f"backups/{slug}/materials/{vtt_name}",
                    })
            materials.append(info)
            if info["id"]:
                file_map[info["id"]] = info

        courses.append({
            "id": course.get("id", slug),
            "slug": slug,
            "name": course.get("name", slug),
            "section": course.get("section", ""),
            "description": course.get("descriptionHeading", "") or course.get("description", ""),
            "state": course.get("courseState", ""),
            "bannerColor": COURSE_BANNER_COLORS[hash(course.get("id", slug)) % len(COURSE_BANNER_COLORS)],
            "topics": topics,
            "announcements": announcements,
            "coursework": coursework,
            "courseworkMaterials": cw_materials,
            "materials": materials,
            "fileMap": file_map,
            "links": links,
            "forms": forms,
            "errors": errors,
        })
    return courses


def build_site() -> Path:
    courses = collect_courses()
    data = json.dumps(courses, ensure_ascii=False, default=str)
    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "index.html"
    out.write_text(_render(data), encoding="utf-8")
    return out


def _render(data: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Classroom Backup</title>
<style>
:root {{
  --bg:#fafafa; --surface:#fff; --border:#e0e0e0; --text:#1f1f1f; --muted:#5f6368;
  --accent:#1a73e8; --accent2:#0f9d58; --hover:#f1f3f4; --shadow:0 1px 3px rgba(0,0,0,.12);
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:'Google Sans',Roboto,system-ui,Arial,sans-serif; background:var(--bg); color:var(--text); }}
header.topbar {{ position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:16px;
  height:64px; padding:0 24px; background:var(--surface); border-bottom:1px solid var(--border); box-shadow:var(--shadow); }}
.topbar .logo {{ display:flex; align-items:center; gap:10px; font-size:22px; font-weight:500; }}
.topbar .logo .badge {{ width:32px; height:32px; border-radius:8px; background:var(--accent2);
  display:flex; align-items:center; justify-content:center; color:#fff; font-size:18px; }}
.layout {{ display:flex; min-height:calc(100vh - 64px); }}
aside.sidebar {{ width:280px; flex:0 0 280px; background:var(--surface); border-right:1px solid var(--border);
  padding:16px 0; overflow-y:auto; }}
.sidebar h3 {{ padding:0 20px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin:16px 0 8px; }}
.course-item {{ display:flex; align-items:center; gap:12px; padding:10px 20px; cursor:pointer; transition:background .15s; }}
.course-item:hover {{ background:var(--hover); }}
.course-item.active {{ background:#e8f0fe; border-left:4px solid var(--accent); padding-left:16px; }}
.course-item .swatch {{ width:36px; height:36px; border-radius:8px; flex:0 0 36px; display:flex; align-items:center; justify-content:center; color:#fff; font-size:15px; font-weight:600; }}
.course-item .meta {{ overflow:hidden; }}
.course-item .meta .nm {{ font-size:14px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.course-item .meta .st {{ font-size:12px; color:var(--muted); }}
main.content {{ flex:1; padding:0; overflow-y:auto; }}
.empty {{ padding:80px 40px; text-align:center; color:var(--muted); }}
.empty .big {{ font-size:48px; margin-bottom:16px; }}
.banner {{ height:160px; display:flex; align-items:flex-end; padding:24px 32px; color:#fff; }}
.banner h1 {{ margin:0; font-size:28px; font-weight:500; text-shadow:0 1px 3px rgba(0,0,0,.3); }}
.banner .sub {{ font-size:14px; opacity:.9; margin-top:4px; }}
.tabs {{ display:flex; gap:0; border-bottom:1px solid var(--border); background:var(--surface); position:sticky; top:0; z-index:10; }}
.tab {{ padding:16px 28px; cursor:pointer; font-size:14px; font-weight:500; color:var(--muted); border-bottom:3px solid transparent; }}
.tab:hover {{ background:var(--hover); }}
.tab.active {{ color:var(--accent); border-bottom-color:var(--accent); }}
.panel {{ padding:24px 32px; max-width:1100px; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; margin-bottom:16px; box-shadow:var(--shadow); overflow:hidden; }}
.card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; padding:20px 24px; cursor:pointer; }}
.card-head:hover {{ background:var(--hover); }}
.card .title {{ font-size:16px; font-weight:500; }}
.card .date {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.card .desc {{ font-size:14px; line-height:1.6; color:#3c4043; white-space:pre-wrap; word-break:break-word; margin-top:4px; }}
.card .due {{ margin-top:8px; font-size:13px; color:var(--accent); }}
.card-body {{ padding:0 24px 20px; }}
.card-body .desc {{ margin-bottom:12px; }}
.badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.badge-chip {{ display:inline-flex; align-items:center; gap:4px; padding:3px 10px; border-radius:12px; font-size:12px; background:#e8f0fe; color:var(--accent); }}
.badge-chip.video {{ background:#fce8e6; color:#d93025; }}
.badge-chip.pdf {{ background:#e6f4ea; color:var(--accent2); }}
.badge-chip.link {{ background:#fef7e0; color:#f9ab00; }}
.badge-chip.form {{ background:#f3e8fd; color:#9c27b0; }}
.expand-arrow {{ font-size:14px; color:var(--muted); transition:transform .2s; flex-shrink:0; }}
.card.expanded .expand-arrow {{ transform:rotate(90deg); }}
.materials-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:14px; }}
.file {{ display:flex; flex-direction:column; gap:8px; padding:14px; background:var(--surface); border:1px solid var(--border); border-radius:10px; text-decoration:none; color:var(--text); transition:box-shadow .15s,transform .15s; }}
.file:hover {{ box-shadow:0 4px 12px rgba(0,0,0,.15); transform:translateY(-2px); }}
.file .icon {{ font-size:30px; }}
.file .nm {{ font-size:13px; font-weight:500; word-break:break-word; line-height:1.3; }}
.file .mt {{ font-size:11px; color:var(--muted); }}
.topic-pill {{ display:inline-block; padding:4px 12px; margin:4px 6px 4px 0; background:#e6f4ea; color:var(--accent2); border-radius:16px; font-size:13px; }}
.err {{ background:#fce8e6; border-color:#f28b82; }}
.err .title {{ color:#d93025; }}
a {{ color:var(--accent); }}
video {{ max-width:100%; border-radius:8px; margin-top:10px; background:#000; }}
.pdf-frame {{ width:100%; height:600px; border:1px solid var(--border); border-radius:8px; margin-top:10px; }}
.att {{ margin:6px 0; }}
.att a {{ text-decoration:none; }}
.vid-card {{ margin-top:12px; }}
.pdf-btn {{ display:inline-block; padding:8px 16px; background:var(--accent); color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:13px; margin-top:8px; }}
.pdf-btn:hover {{ background:#1557b0; }}
@media(max-width:760px) {{ aside.sidebar{{display:none;}} .layout{{flex-direction:column;}} }}
</style>
</head>
<body>
<header class="topbar"><div class="logo"><div class="badge">C</div> Classroom Backup</div></header>
<div class="layout">
  <aside class="sidebar">
    <h3>Courses</h3>
    <div id="courseList"></div>
  </aside>
  <main class="content" id="content">
    <div class="empty"><div class="big">&#128218;</div>Select a course to view its content.</div>
  </main>
</div>
<script>
const DATA = {data};
const $ = (s)=>document.querySelector(s);
const $$ = (s)=>document.querySelectorAll(s);
const esc = (s)=>String(s||'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[c]));
function fmtDate(s){{ if(!s) return ''; return s.replace('T',' ').split('.')[0].slice(0,16); }}
function fileIcon(mime,name){{
  let n=(name||'').toLowerCase(), m=(mime||'').toLowerCase();
  if(m.startsWith('video')) return '&#127909;';
  if(m.includes('pdf')||n.endsWith('.pdf')) return '&#128214;';
  if(m.includes('image')||/\\.(png|jpg|jpeg|gif|svg)$/.test(n)) return '&#128247;';
  if(m.includes('spreadsheet')||n.endsWith('.xlsx')||n.endsWith('.csv')) return '&#128202;';
  if(m.includes('document')||n.endsWith('.docx')) return '&#128196;';
  if(n.endsWith('.ipynb')) return '&#128187;';
  if(n.endsWith('.sql')) return '&#128458;';
  return '&#128206;';
}}
function fmtSize(b){{ if(!b) return ''; b=+b; if(b<1024) return b+' B'; if(b<1048576) return (b/1024).toFixed(1)+' KB'; return (b/1048576).toFixed(1)+' MB'; }}

const TABS=['stream','classwork','materials','topics','files'];
let currentCourse=null, currentTab='stream', expandedIdx=null;

/* ---- hash router ---- */
function parseHash(){{
  let h = location.hash.slice(2);
  let parts = h.split('/').filter(Boolean);
  if(parts[0]==='course' && parts[1]){{
    let cid=parts[1], tab=parts[2]||'stream', idx=parts[3]!=null?+parts[3]:null;
    return {{cid, tab, idx}};
  }}
  return null;
}}
function setHash(cid, tab, idx){{
  let h = '#/course/'+cid+'/'+tab;
  if(idx!=null) h += '/'+idx;
  if(location.hash !== h) history.pushState(null,'',h);
}}
window.addEventListener('popstate', route);

function route(){{
  let r = parseHash();
  if(!r) return;
  let c = DATA.find(c=>c.id===r.cid);
  if(!c) return;
  if(currentCourse?.id !== r.cid){{
    selectCourse(r.cid, false);
  }}
  if(currentTab !== r.tab){{
    setTab(r.tab, false);
  }}
  if(r.idx!=null && expandedIdx !== r.idx){{
    toggleCard(r.idx, false);
  }} else if(r.idx==null && expandedIdx!=null){{
    let prev = document.getElementById('card-'+expandedIdx);
    if(prev) collapseCard(prev);
    expandedIdx = null;
  }}
}}

/* ---- course list ---- */
function renderCourseList(){{
  $('#courseList').innerHTML = DATA.map(c=>`
    <div class="course-item" data-id="${{c.id}}" onclick="selectCourse('${{c.id}}')">
      <div class="swatch" style="background:${{c.bannerColor}}">${{esc(c.name.charAt(0).toUpperCase())}}</div>
      <div class="meta"><div class="nm">${{esc(c.name)}}</div><div class="st">${{esc(c.state)}}</div></div>
    </div>`).join('');
}}

function selectCourse(id, push=true){{
  currentCourse = DATA.find(c=>c.id===id);
  currentTab='stream'; expandedIdx=null;
  $$('.course-item').forEach(i=>i.classList.toggle('active', i.dataset.id===id));
  renderContent();
  if(push) setHash(id, 'stream', null);
}}

/* ---- content shell ---- */
function renderContent(){{
  const c=currentCourse; if(!c) return;
  $('#content').innerHTML = `
    <div class="banner" style="background:linear-gradient(135deg,${{c.bannerColor}},${{c.bannerColor}}cc)">
      <div><h1>${{esc(c.name)}}</h1>
      <div class="sub">${{esc(c.section||'')}} ${{c.state? '&middot; '+esc(c.state):''}}</div>
      ${{c.description? `<div class="sub">${{esc(c.description)}}</div>`:''}}
      </div>
    </div>
    <div class="tabs">
      ${{TABS.map(t=>`<div class="tab" onclick="setTab('${{t}}')">${{t.charAt(0).toUpperCase()+t.slice(1)}}</div>`).join('')}}
    </div>
    <div class="panel" id="panel"></div>`;
  setTab(currentTab, false);
}}

/* ---- tab rendering ---- */
function setTab(t, push=true){{
  currentTab=t; expandedIdx=null;
  $$('.tab').forEach((el,i)=>el.classList.toggle('active',TABS[i]===t));
  if(push && currentCourse) setHash(currentCourse.id, t, null);
  const c=currentCourse, p=$('#panel'); if(!p) return;

  if(t==='topics'){{
    if(!c.topics.length){{ p.innerHTML='<div class="empty">No topics.</div>'; return; }}
    p.innerHTML='<div>'+c.topics.map(tp=>`<span class="topic-pill">${{esc(tp.name||'')}}</span>`).join('')+'</div>';
    return;
  }}
  if(t==='files'){{
    renderFilesTab(c, p); return;
  }}
  let items, labelFn;
  if(t==='stream'){{ items=c.announcements||[]; labelFn=()=>'Announcement'; }}
  else if(t==='classwork'){{ items=c.coursework||[]; labelFn=w=>w.title||'Untitled'; }}
  else if(t==='materials'){{ items=c.courseworkMaterials||[]; labelFn=w=>w.title||'Untitled'; }}
  else return;

  if(!items.length){{ p.innerHTML=`<div class="empty">No ${{t}}.</div>`; return; }}
  items = items.slice().sort((a,b)=>(b.updateTime||'').localeCompare(a.updateTime||''));

  p.innerHTML = items.map((item,i)=>renderCardCollapsed(item, i, labelFn(item))).join('');
}}

/* ---- collapsed card ---- */
function renderCardCollapsed(item, idx, label){{
  let mats = item.materials||[];
  let badges = mats.map(m=>attachmentBadge(m)).filter(Boolean).join('');
  let dueStr = '';
  if(item.dueDate){{
    dueStr = `<div class="due">Due: ${{item.dueDate.year}}-${{String(item.dueDate.month).padStart(2,'0')}}-${{String(item.dueDate.day).padStart(2,'0')}}${{item.dueTime? ' '+String(item.dueTime.hours).padStart(2,'0')+':'+String(item.dueTime.minutes||0).padStart(2,'0'):''}}</div>`;
  }}
  return `<div class="card" data-idx="${{idx}}" id="card-${{idx}}">
    <div class="card-head" onclick="toggleCard(${{idx}})">
      <div style="flex:1;min-width:0">
        <div class="title">${{esc(label)}}</div>
        <div class="date">${{fmtDate(item.updateTime||item.creationTime)}}</div>
        ${{dueStr}}
        ${{badges? `<div class="badges">${{badges}}</div>`:''}}
      </div>
      <div class="expand-arrow">&#9654;</div>
    </div>
  </div>`;
}}

function attachmentBadge(m){{
  if(m.driveFile){{
    const df=m.driveFile.driveFile||m.driveFile;
    const fi=currentCourse.fileMap[df.id];
    if(fi && (fi.mimeType||'').startsWith('video')) return `<span class="badge-chip video">&#127909; video</span>`;
    if(fi && (fi.mimeType||'').includes('pdf')) return `<span class="badge-chip pdf">&#128214; PDF</span>`;
    if(fi) return `<span class="badge-chip">${{fileIcon(fi.mimeType,df.title)}} file</span>`;
    return `<span class="badge-chip">&#128206; unavailable</span>`;
  }}
  if(m.link) return `<span class="badge-chip link">&#128279; link</span>`;
  if(m.form) return `<span class="badge-chip form">&#128221; form</span>`;
  if(m.youtubeVideo) return `<span class="badge-chip video">&#127909; YouTube</span>`;
  return '';
}}

/* ---- expand/collapse card ---- */
function toggleCard(idx, push=true){{
  let card = document.getElementById('card-'+idx);
  if(!card) return;

  if(expandedIdx === idx){{
    collapseCard(card);
    expandedIdx = null;
    if(push && currentCourse) setHash(currentCourse.id, currentTab, null);
    return;
  }}
  if(expandedIdx != null){{
    let prev = document.getElementById('card-'+expandedIdx);
    if(prev) collapseCard(prev);
  }}
  expandCard(card, idx);
  expandedIdx = idx;
  if(push && currentCourse) setHash(currentCourse.id, currentTab, idx);
}}

function collapseCard(card){{
  card.classList.remove('expanded');
  let body = card.querySelector('.card-body');
  if(body){{
    body.querySelectorAll('video').forEach(v=>{{ v.pause(); v.removeAttribute('src'); v.load(); }});
    body.querySelectorAll('iframe').forEach(f=>{{ f.src='about:blank'; }});
    body.remove();
  }}
}}

function expandCard(card, idx){{
  card.classList.add('expanded');
  let items, labelFn;
  if(currentTab==='stream') items=(currentCourse.announcements||[]).slice().sort((a,b)=>(b.updateTime||'').localeCompare(a.updateTime||''));
  else if(currentTab==='classwork') items=(currentCourse.coursework||[]).slice().sort((a,b)=>(b.updateTime||'').localeCompare(a.updateTime||''));
  else if(currentTab==='materials') items=(currentCourse.courseworkMaterials||[]).slice().sort((a,b)=>(b.updateTime||'').localeCompare(a.updateTime||''));
  else return;

  let item = items[idx]; if(!item) return;
  let body = document.createElement('div');
  body.className = 'card-body';
  let html = '';
  if(item.text) html += `<div class="desc">${{esc(item.text)}}</div>`;
  if(item.description) html += `<div class="desc">${{esc(item.description)}}</div>`;
  if(item.dueDate) html += `<div class="due">Due: ${{item.dueDate.year}}-${{String(item.dueDate.month).padStart(2,'0')}}-${{String(item.dueDate.day).padStart(2,'0')}}${{item.dueTime? ' '+String(item.dueTime.hours).padStart(2,'0')+':'+String(item.dueTime.minutes||0).padStart(2,'0'):''}}</div>`;
  if(item.materials && item.materials.length) html += renderAttachments(item.materials);
  body.innerHTML = html;
  card.appendChild(body);
}}

/* ---- attachment rendering (lazy) ---- */
function renderAttachments(mats){{
  return '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px">'+mats.map(m=>{{
    if(m.driveFile){{
      const df=m.driveFile.driveFile||m.driveFile;
      const fid=df.id;
      const fi=currentCourse.fileMap[fid];
      if(fi && (fi.mimeType||'').startsWith('video')){{
        let tracks='';
        (fi.transcripts||[]).forEach((t,i)=>{{ tracks+=`<track kind="subtitles" src="${{t.url}}" srclang="${{t.lang}}" label="${{t.lang}}" ${{i===0?'default':''}}>`; }});
        return `<div class="vid-card"><video controls preload="none" src="${{fi.url}}">${{tracks}}Your browser does not support video.</video><div class="mt">${{esc(df.title||'')}} ${{(fi.transcripts||[]).length?'&middot; subtitles:'+fi.transcripts.map(t=>t.lang).join(','):''}}</div></div>`;
      }}
      if(fi && (fi.mimeType||'').includes('pdf')){{
        return `<div class="vid-card"><div class="att"><a href="${{fi.url}}" target="_blank">${{fileIcon('pdf',df.title)}} ${{esc(df.title||'file')}}</a></div><button class="pdf-btn" onclick="loadPdf(this,'${{fi.url}}')">&#128214; View PDF</button></div>`;
      }}
      if(fi) return `<div class="att"><a href="${{fi.url}}" target="_blank">${{fileIcon(fi.mimeType,df.title)}} ${{esc(df.title||'file')}}</a></div>`;
      return `<div class="att"><a href="${{esc(df.alternateLink||'')}}" target="_blank">${{fileIcon('',df.title)}} ${{esc(df.title||'file')}}</a> <span class="mt">(not downloaded)</span></div>`;
    }}
    if(m.link) return `<div class="att"><a href="${{esc(m.link.url)}}" target="_blank">&#128279; ${{esc(m.link.title||m.link.url)}}</a></div>`;
    if(m.form) return `<div class="att"><a href="${{esc(m.form.formUrl)}}" target="_blank">&#128221; ${{esc(m.form.title||'Form')}}</a></div>`;
    if(m.youtubeVideo) return `<div class="att"><a href="https://youtu.be/${{esc(m.youtubeVideo.id)}}" target="_blank">&#127909; ${{esc(m.youtubeVideo.title||'Video')}}</a></div>`;
    return '';
  }}).join('')+'</div>';
}}

function loadPdf(btn, url){{
  if(btn.nextElementSibling && btn.nextElementSibling.tagName==='IFRAME') return;
  let frame = document.createElement('iframe');
  frame.className = 'pdf-frame';
  frame.src = url;
  btn.after(frame);
  btn.textContent = '&#128214; Hide PDF';
  btn.onclick = () => {{
    if(frame.style.display==='none'){{ frame.style.display=''; btn.textContent='&#128214; Hide PDF'; }}
    else {{ frame.style.display='none'; btn.textContent='&#128214; Show PDF'; }}
  }};
}}

/* ---- files tab ---- */
function renderFilesTab(c, p){{
  const errs=c.errors||[];
  if(!c.materials.length && !errs.length && !c.links.length && !c.forms.length){{ p.innerHTML='<div class="empty">No files.</div>'; return; }}
  let h='<div class="materials-grid">'+c.materials.map(m=>{{
    let extra=[];
    if(m.via==='stream') extra.push('streamed');
    if(m.exported) extra.push('exported PDF');
    if(m.transcripts&&m.transcripts.length) extra.push('subtitles:'+m.transcripts.map(t=>t.lang).join(','));
    return `<a class="file" href="${{m.url}}" target="_blank">
      <div class="icon">${{fileIcon(m.mimeType,m.name)}}</div>
      <div class="nm">${{esc(m.name)}}</div>
      <div class="mt">${{fmtSize(m.size)}}${{extra.length? ' &middot; '+extra.join(','):''}}</div>
    </a>`;
  }}).join('')+'</div>';
  if(c.links&&c.links.length) h+=`<h3 style="margin-top:24px">Links</h3>`+c.links.map(l=>`<div class="att"><a href="${{esc(l.url)}}" target="_blank">&#128279; ${{esc(l.title||l.url)}}</a></div>`).join('');
  if(c.forms&&c.forms.length) h+=`<h3 style="margin-top:24px">Forms</h3>`+c.forms.map(f=>`<div class="att"><a href="${{esc(f.formUrl)}}" target="_blank">&#128221; ${{esc(f.title||'Form')}}</a></div>`).join('');
  if(errs.length) h+=`<div class="card err" style="margin-top:18px;padding:20px 24px"><div class="title">${{errs.length}} file(s) could not be downloaded</div>
    <div class="desc">${{errs.map(e=>esc(e.id+' ('+e.phase+')')).join('\\n')}}</div></div>`;
  p.innerHTML=h;
}}

/* ---- init ---- */
renderCourseList();
let r = parseHash();
if(r) route();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    out = build_site()
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
