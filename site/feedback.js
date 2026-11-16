// Gamma-only feedback. One panel with two views: write a note, or review the
// inbox. The launcher carries how many notes are open on the page you are on.
(() => {
  if (location.hostname !== 'gamma.slay-my-stats.com' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') return;
  const host = document.createElement('div');
  host.id = 'gamma-feedback';
  document.body.append(host);
  const root = host.attachShadow({mode: 'open'});
  root.innerHTML = `<style>
    :host{font:14px/1.45 system-ui;color:#f4f0e7;position:fixed;bottom:16px;right:16px;z-index:2147483646;display:flex;flex-direction:column;align-items:flex-end;gap:10px}
    *{box-sizing:border-box}button,textarea,a{font:inherit;touch-action:manipulation}
    button{background:#302d27;color:#fff;border:1px solid #82735b;border-radius:6px;padding:9px 12px;cursor:pointer}
    button:hover{background:#514635}button:disabled{opacity:.5}a{color:#edc782}
    #launcher{display:flex;align-items:center;gap:8px;padding:12px 20px;border:1px solid #f6e3b0;border-radius:999px;background:linear-gradient(#f4dda6,#e0c468);color:#191c20;font-size:15px;font-weight:700;box-shadow:0 6px 20px #000a;order:2}
    #launcher:hover{background:linear-gradient(#f9e7ba,#e8cf7c)}
    #launcher.sent{background:linear-gradient(#cfe8b5,#9fcb7a);border-color:#cfe8b5}
    #launcher-count{min-width:20px;padding:1px 6px;border-radius:999px;background:#191c20;color:#f4dda6;font-size:12px;font-weight:700;text-align:center}
    #launcher:focus-visible,button:focus-visible{outline:3px solid #f6c66d;outline-offset:2px}
    #panel{order:1;background:#191c20;border:1px solid #82735b;border-radius:12px;padding:16px;width:420px;max-width:calc(100vw - 16px);max-height:calc(100dvh - 100px);min-width:300px;min-height:180px;overflow:auto;resize:both;box-shadow:0 8px 40px #0009}
    #panel.placed{position:fixed;max-height:calc(100dvh - 16px)}
    header{cursor:grab;touch-action:none;user-select:none}header.dragging{cursor:grabbing}header button{cursor:pointer}
    h2{display:flex;align-items:center;gap:10px}
    h2::before{content:'';width:10px;height:16px;flex:none;opacity:.7;background:radial-gradient(circle,#edc782 1.3px,transparent 1.6px) 0 0/5px 5.5px}
    header:hover h2::before{opacity:1}
    #panel::-webkit-resizer{background:linear-gradient(135deg,transparent 52%,#edc782 52% 60%,transparent 60% 72%,#edc782 72% 80%,transparent 80%);border-bottom-right-radius:10px}
    h2{font-size:18px;margin:0;letter-spacing:.01em}
    header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
    #close{display:flex;align-items:center;justify-content:center;width:30px;height:30px;padding:0;border-radius:50%;font-size:18px;line-height:1;color:#e0d0f8}
    #close:hover{background:#514635;border-color:#edc782}
    #tabs{display:inline-flex;border:1px solid #82735b;border-radius:999px;overflow:hidden;margin:0 0 12px}
    #tabs button{border:0;border-radius:0;padding:6px 14px;background:#101316;color:#bcb8b0;font-size:13px}
    #tabs button + button{border-left:1px solid #82735b}
    #tabs button[aria-selected="true"]{background:#e0c468;color:#191c20;font-weight:700}
    #page-url{display:block;margin:0 0 10px;padding:6px 8px;border-radius:5px;background:#101316;color:#a9a4b8;font-size:12px;overflow-wrap:anywhere}
    #modes{display:flex;gap:6px;margin:0 0 12px}
    #pick{flex:1;background:#514635;border-color:#edc782;font-weight:600}
    #page{background:none;border:0;color:#bcb8b0;text-decoration:underline;padding:4px 2px}
    #page:hover{background:none;color:#f4f0e7}
    #target-row{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:0 0 8px}
    #target{margin:0;font-weight:700;font-size:15px;min-width:0;overflow-wrap:anywhere}
    #clear{flex:none;padding:3px 10px;font-size:12px;border-radius:999px}
    #prior{margin:0 0 12px;padding:10px 12px;border:1px solid #635948;border-radius:8px;background:#101316}
    #prior b{display:block;margin-bottom:6px}#prior ul{margin:0;padding-left:16px;max-height:140px;overflow:auto}
    #prior li{margin:4px 0}#prior .resolved{color:#8f8a80;text-decoration:line-through}
    label{display:block;font-size:12px;color:#bcb8b0;margin-bottom:4px}
    textarea{width:100%;min-height:96px;background:#101316;color:#fff;border:1px solid #82735b;padding:9px;border-radius:6px;resize:vertical}
    #save{width:100%;margin-top:8px;background:#514635;border-color:#edc782;font-weight:700}
    #status,#inbox-status{margin:10px 0 0;font-size:12px;color:#bcb8b0;white-space:pre-wrap}
    #status:empty,#inbox-status:empty{display:none}
    #summary{margin:0 0 10px;font-size:12px;color:#bcb8b0}
    #summary b{color:#f4f0e7;font-size:14px}
    #scope{display:inline-flex;border:1px solid #82735b;border-radius:999px;overflow:hidden;margin:0 0 12px}
    #scope button{border:0;border-radius:0;padding:6px 12px;background:#101316;color:#bcb8b0;font-size:13px}
    #scope button + button{border-left:1px solid #82735b}
    #scope button[aria-pressed="true"]{background:#e0c468;color:#191c20;font-weight:700}
    .bucket{border:1px solid #3a3460;border-left:3px solid #e0c468;border-radius:8px;background:#101316;margin:0 0 10px;overflow:hidden}
    .bucket.resolved{border-left-color:#4a4a5e}
    .bucket > summary{display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:9px 11px;cursor:pointer;list-style:none}
    .bucket > summary::-webkit-details-marker{display:none}
    .bucket[open] > summary{border-bottom:1px solid #2a2740}
    .bucket-label{font-weight:700;line-height:1.3}
    .bucket-meta{color:#bcb8b0;font-size:11px;white-space:nowrap}
    .bucket-body{padding:2px 11px 10px}
    article{padding:10px 0;border-top:1px solid #2a2740}article:first-child{border-top:0}
    #kinds{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
    #kinds button{padding:4px 10px;border-radius:999px;border:1px solid #4a4666;background:transparent;color:inherit;font:inherit;font-size:12px;cursor:pointer}
    #kinds button[aria-checked="true"]{background:#d4af37;border-color:#d4af37;color:#16141f;font-weight:700}
    .pill.kind{background:#2a2740;color:#e8e4f4}
    .note-comment{margin:0 0 6px;white-space:pre-wrap;overflow-wrap:anywhere}
    .note-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin:0 0 4px;font-size:12px;color:#bcb8b0}
    .note-who{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#f4f0e7;font-weight:600}
    .note-who.bare{color:#8f8a80;font-weight:400}
    .note-head time{flex:none;white-space:nowrap}
    .note-meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:0;font-size:11px;color:#bcb8b0}
    .note-meta a{margin-left:auto}
    .pill{padding:1px 7px;border-radius:999px;font-weight:700;font-size:10px;letter-spacing:.03em;text-transform:uppercase}
    .pill.open{background:#e0c468;color:#191c20}.pill.resolved{background:#3a3460;color:#c9c4d8}
    .note-url{display:block;margin:6px 0 8px;color:#8f8a80;font-size:11px;overflow-wrap:anywhere}
    .note-actions{display:flex;gap:10px;align-items:center}
    .note-actions button{background:none;border:0;padding:0;color:#edc782;text-decoration:underline;font-size:12px}
    .note-actions button:hover{background:none;color:#f4f0e7}
    .note-resolution,.note-history{margin:4px 0 0;font-size:12px;color:#bcb8b0;overflow-wrap:anywhere}.note-history{color:#8f8a80}
    .close-form{display:grid;gap:6px;margin:8px 0 0}.close-form textarea{min-height:56px}
    .close-form input{background:#101316;color:#fff;border:1px solid #82735b;padding:7px 9px;border-radius:6px;font:inherit}
    .close-form div{display:flex;gap:8px}
    .close-form select{background:#101316;color:#fff;border:1px solid #82735b;padding:7px 9px;border-radius:6px;font:inherit}
    #filters{display:flex;gap:8px;margin:0 0 8px}
    #filters select{flex:1;background:#101316;color:#fff;border:1px solid #82735b;padding:6px 8px;border-radius:6px;font:inherit}
    #load-more{width:100%;margin:4px 0 0;background:#101316}
    #inbox-foot{display:flex;justify-content:space-between;gap:10px;margin-top:12px;padding-top:10px;border-top:1px solid #2a2740}
    #inbox-foot button{background:none;border:0;padding:0;color:#edc782;text-decoration:underline;font-size:12px}
    #inbox-foot button:hover{background:none;color:#f4f0e7}
    [hidden]{display:none!important}
    #hint{background:#191c20;padding:12px;max-width:320px;border:1px solid #edc782;border-radius:8px;order:0}
    @media(max-height:520px){:host{bottom:8px;right:8px}#panel{max-height:calc(100dvh - 78px);width:460px}textarea{min-height:64px}#launcher{padding:9px 14px;font-size:14px}}
  </style>
  <div id="hint" hidden>Click near what you mean, or drag across it. Press Escape to cancel. <button id="cancel" type="button">Cancel</button></div>
  <section id="panel" role="dialog" aria-label="Feedback" hidden>
    <header><h2>Feedback</h2><button id="close" type="button" aria-label="Close feedback" title="Close">✕</button></header>
    <div id="tabs" role="tablist"><button id="tab-inbox" type="button" role="tab" aria-selected="true" aria-controls="view-inbox">Inbox</button><button id="tab-compose" type="button" role="tab" aria-selected="false" aria-controls="view-compose">New note</button></div>
    <div id="view-compose" role="tabpanel" hidden>
      <small id="page-url"></small>
      <div id="modes"><button id="pick" type="button">Pick on page</button><button id="page" type="button">Whole page</button></div>
      <div id="target-row"><p id="target">Whole page</p><button id="clear" type="button" hidden>Clear</button></div>
      <div id="prior" hidden></div>
      <div id="kinds" role="radiogroup" aria-label="Type"><button type="button" role="radio" aria-checked="false" data-kind="bug">Bug</button><button type="button" role="radio" aria-checked="false" data-kind="feature">Feature request</button><button type="button" role="radio" aria-checked="false" data-kind="improvement">Improvement idea</button></div>
      <label for="comment">What should change?</label>
      <textarea id="comment" maxlength="4000" placeholder="Describe the issue or suggestion…"></textarea>
      <button id="save" type="button">Send</button>
      <p id="status" role="status"></p>
    </div>
    <div id="view-inbox" role="tabpanel">
      <p id="summary"></p>
      <div id="scope" role="group" aria-label="Inbox scope"><button id="scope-page" type="button" aria-pressed="false">This page</button><button id="scope-site" type="button" aria-pressed="false">Whole site</button></div>
      <div id="filters"><select id="filter-status" aria-label="Status"><option value="open">Open</option><option value="resolved">Resolved</option><option value="all">All</option></select><select id="filter-kind" aria-label="Type"><option value="">Any type</option><option value="bug">Bug</option><option value="feature">Feature request</option><option value="improvement">Improvement idea</option></select></div>
      <div id="notes"></div>
      <button id="load-more" type="button" hidden>Load the next 25</button>
      <p id="inbox-status" role="status"></p>
      <div id="inbox-foot"><button id="copy" type="button">Copy all notes</button><button id="refresh" type="button">Refresh</button></div>
    </div>
  </section>
  <button id="launcher" type="button"><span aria-hidden="true">✎</span> <span id="launcher-label">Feedback</span><span id="launcher-count" aria-hidden="true" hidden></span></button>`;
  const $ = id => root.getElementById(id);
  const ORIGIN = location.origin;
  let target = {kind: 'page',viewport:{width:innerWidth,height:innerHeight}}, notes = [], pageCache = [], scope = 'page', status = 'open', filterKind = '', nextCursor = null, view = 'inbox', picking = false, start, previousFocus, oldTouchAction;
  const mark = document.createElement('div');
  Object.assign(mark.style, {position:'fixed',pointerEvents:'none',zIndex:'2147483645',border:'2px solid #f6c66d',background:'#f6c66d22',display:'none'});
  document.body.append(mark);
  function rect(box) { Object.assign(mark.style,{display:'block',left:box.x+'px',top:box.y+'px',width:box.width+'px',height:box.height+'px'}); }
  const say = (text, which) => $(which === 'inbox' ? 'inbox-status' : 'status').textContent = text;
  function showView(which) {
    view = which;
    $('view-compose').hidden = which !== 'compose';
    $('view-inbox').hidden = which !== 'inbox';
    $('tab-compose').setAttribute('aria-selected', String(which === 'compose'));
    $('tab-inbox').setAttribute('aria-selected', String(which === 'inbox'));
    if (which === 'compose') { $('page-url').textContent = pageUrl(); renderPrior(); }
    else load(true);
    keepOnScreen();
  }
  function openPanel() {
    if ($('panel').hidden) previousFocus = document.activeElement;
    $('panel').hidden = false;
    placePanel();
    showView(view);
    $('close').focus();
  }
  // The panel starts bottom-right above the launcher, then is pinned to the viewport so it can be
  // dragged by its header and resized from its corner; it keeps its place between openings.
  function placePanel() {
    const panel = $('panel');
    if (!panel.classList.contains('placed')) {
      const r = panel.getBoundingClientRect();
      Object.assign(panel.style, {left: r.left + 'px', top: r.top + 'px', width: r.width + 'px'});
      panel.classList.add('placed');
    }
    keepOnScreen();
  }
  function keepOnScreen() {
    const panel = $('panel');
    if (panel.hidden || !panel.classList.contains('placed')) return;
    const r = panel.getBoundingClientRect();
    panel.style.left = Math.max(8, Math.min(r.left, innerWidth - r.width - 8)) + 'px';
    panel.style.top = Math.max(8, Math.min(r.top, innerHeight - r.height - 8)) + 'px';
  }
  addEventListener('resize', keepOnScreen);
  // A view that fills in later (the inbox loads its notes) makes the panel taller; keep its bottom in view.
  new ResizeObserver(keepOnScreen).observe($('panel'));
  $('panel').querySelector('header').addEventListener('pointerdown', e => {
    if (e.button || e.target.closest('button')) return;
    const head = e.currentTarget, panel = $('panel'), r = panel.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    const move = ev => {
      panel.style.left = Math.max(8 - r.width + 80, Math.min(ev.clientX - dx, innerWidth - 80)) + 'px';
      panel.style.top = Math.max(0, Math.min(ev.clientY - dy, innerHeight - 40)) + 'px';
    };
    head.classList.add('dragging');
    const done = () => { head.classList.remove('dragging'); removeEventListener('pointermove', move); removeEventListener('pointerup', done); removeEventListener('pointercancel', done); };
    addEventListener('pointermove', move); addEventListener('pointerup', done); addEventListener('pointercancel', done);
    e.preventDefault();
  });
  function closePanel() { $('panel').hidden = true; previousFocus?.focus(); }
  function pageUrl() { const url=new URL(location.href); url.searchParams.delete('feedback'); return url.href; }
  function currentPath() { const url=new URL(pageUrl()); return url.pathname+url.search+url.hash; }
  function composer() { say(''); showView('compose'); }
  // Clear shows whenever there is something to take back: a pinned element or region, or text typed.
  function syncClear() { $('clear').hidden = target.kind === 'page' && !$('comment').value; }
  const KINDS = {bug: 'Bug', feature: 'Feature request', improvement: 'Improvement idea'};
  let kind = '';
  function setKind(value) {
    kind = value;
    for (const b of $('kinds').children) b.setAttribute('aria-checked', String(b.dataset.kind === value));
  }
  function resetNote() {
    setKind('');
    target = {kind: 'page', viewport: {width: innerWidth, height: innerHeight}};
    $('target').textContent = 'Whole page'; $('comment').value = ''; say(''); syncClear(); $('comment').focus();
  }
  // Notes already recorded for the same page and the same pick, so a reviewer
  // sees the history where they are about to write instead of repeating it.
  function sameTarget(note) {
    if (target.kind==='page') return note.target?.kind==='page';
    return note.target?.kind!=='page' && note.target?.selector===target.selector;
  }
  function renderPrior() {
    const box=$('prior'), matches=pageCache.filter(sameTarget);
    box.replaceChildren();
    if(!matches.length){box.hidden=true;return;}
    const open=matches.filter(note=>!note.resolved).length, title=document.createElement('b'), list=document.createElement('ul');
    title.textContent=`${matches.length} earlier note${matches.length===1?'':'s'} here`+(open?` · ${open} open`:' · all resolved');
    for(const note of matches.slice(0,8)) {
      const li=document.createElement('li');
      li.textContent=`${note.resolved?'[resolved] ':''}${note.category?`[${KINDS[note.category]||note.category}] `:''}${note.comment.replace(/\s+/g,' ').slice(0,240)}`;
      if(note.resolved) li.className='resolved';
      list.append(li);
    }
    box.append(title,list);box.hidden=false;
  }
  function stop() { picking=false; document.documentElement.style.touchAction=oldTouchAction; start=null; mark.style.display='none'; $('hint').hidden=true; $('launcher').hidden=false; openPanel(); }
  function selector(el) {
    const parts=[];
    for(let node=el;node && node!==document.body;node=node.parentElement) {
      if(node.id) {parts.unshift('#'+CSS.escape(node.id)); break;}
      parts.unshift(node.localName+`:nth-of-type(${Array.from(node.parentElement.children).filter(n=>n.localName===node.localName).indexOf(node)+1})`);
    }
    return parts.join(' > ');
  }
  function point(event) {return {x:event.clientX,y:event.clientY};}
  function box(a,b) {return {x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)};}
  document.addEventListener('pointerdown', e => {
    suppressClick=picking;
    if(!picking || e.composedPath().includes(host)) return;
    e.preventDefault();e.stopImmediatePropagation();start=point(e);
  },true);
  document.addEventListener('pointermove',e=>{
    if(!picking || e.composedPath().includes(host)) return;
    e.preventDefault();
    if(start) rect(box(start,point(e)));
    else if(e.target instanceof Element) rect(e.target.getBoundingClientRect());
  },{capture:true,passive:false});
  document.addEventListener('pointerup',e=>{
    if(!picking || !start || e.composedPath().includes(host)) return;
    e.preventDefault();e.stopImmediatePropagation();
    const area=box(start,point(e)), el=document.elementFromPoint(start.x,start.y);
    if(!el) return;
    target={kind:area.width>12 || area.height>12?'region':'element',selector:selector(el),text:(el.innerText || el.getAttribute('aria-label') || '').slice(0,1000),
      viewport:{width:innerWidth,height:innerHeight,scale:devicePixelRatio},scroll:{x:scrollX,y:scrollY},
      rect:area.width>12 || area.height>12?area:Object.fromEntries(['x','y','width','height'].map(k=>[k,el.getBoundingClientRect()[k]]))};
    stop();composer();$('target').textContent=`Pinned: ${target.text.slice(0,100) || el.localName}`; syncClear(); $('comment').focus();
  },true);
  // Consume the synthetic click following selection, including links and buttons.
  let suppressClick=false;
  document.addEventListener('click',e=>{if(suppressClick && !e.composedPath().includes(host)){e.preventDefault();e.stopImmediatePropagation();suppressClick=false;}},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(picking)stop();else if(!$('panel').hidden)closePanel();}});
  async function api(body, params) {
    const query=body?'':'?'+new URLSearchParams(params||{}).toString();
    const response=await fetch('/auth/feedback'+query,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    if(!response.ok) throw new Error(response.status===401?'Sign in to gamma again.':`Could not ${body?'save':'load'} feedback. Please retry.`);
    return response.json();
  }
  const report = note => `Feedback ${note.id}\n${note.category?(KINDS[note.category]||note.category)+' · ':''}${note.resolved?'Resolved':'Open'} · ${new Date(note.created*1000).toISOString()}\n${note.url || ORIGIN + note.path}\n${JSON.stringify(note.target,null,2)}\n\n${note.comment}`;
  function updateCount() {
    const open=pageCache.filter(note=>!note.resolved).length;
    $('launcher-count').textContent=open?String(open):'';
    $('launcher-count').hidden=!open;
    $('launcher').title=open?`${open} open note${open===1?'':'s'} on this page`:'Send feedback on this page';
  }
  // One bucket per whole-page note set and per pinned element or region, so the
  // inbox reads as categories instead of a single stream.
  function bucketOf(note) {
    const page=note.target?.kind==='page', selector=note.target?.selector||'';
    return {key:(page?'page:':'element:')+note.path+(page?'':':'+selector),
            kind:page?'whole page':note.target?.kind==='region'?'region':'element',
            label:page?'Whole page':(note.target?.text||'').replace(/\s+/g,' ').trim().slice(0,110)||selector||'Unknown element'};
  }
  function buckets(list) {
    const map=new Map();
    for(const note of list) {
      const bucket=bucketOf(note);
      if(!map.has(bucket.key)) map.set(bucket.key,{...bucket,notes:[]});
      map.get(bucket.key).notes.push(note);
    }
    const out=[...map.values()];
    for(const bucket of out) {
      bucket.notes.sort((a,b)=>b.created-a.created);
      bucket.open=bucket.notes.filter(note=>!note.resolved).length;
    }
    return out.sort((a,b)=>b.notes[0].created-a.notes[0].created);
  }
  const when = ts => new Date(ts*1000).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
  const matchesFilter = note => (status==='all'||!!note.resolved===(status==='resolved'))&&(!filterKind||note.category===filterKind);
  // A name the lookup gave once stays for the session, so a later response where Steam could not be
  // asked does not turn the same person back into an ID fragment.
  const names = new Map();
  const nameOf = (note, field = 'author') => {
    const id = String(note[field]), name = note[field + '_name'];
    if (name) names.set(id, name);
    return names.get(id) || '';
  };
  const author = (note, field = 'author') => nameOf(note, field) || 'Steam …' + String(note[field]).slice(-4);
  const OUTCOMES = {done:'Done',declined:'Declined',duplicate:'Duplicate'};
  function noteArticle(note) {
    const article=document.createElement('article'),comment=document.createElement('p'),meta=document.createElement('p'),
      pill=document.createElement('span'),time=document.createElement('time'),who=document.createElement('span'),head=document.createElement('p'),
      place=document.createElement('a'),actions=document.createElement('div'),resolve=document.createElement('button'),
      url=document.createElement('small');
    comment.className='note-comment';comment.textContent=note.comment;
    pill.className='pill '+(note.resolved?'resolved':'open');pill.textContent=note.resolved?(OUTCOMES[note.outcome]||'Resolved'):'Open';
    time.textContent=when(note.created);
    who.textContent=author(note);who.className='note-who'+(nameOf(note)?'':' bare');who.title=String(note.author);
    head.className='note-head';head.append(who,time);
    const openUrl=new URL(note.path,ORIGIN);openUrl.searchParams.set('feedback',note.id);
    place.href=openUrl.href;place.textContent='Open location';
    meta.className='note-meta';
    meta.append(pill);
    if(note.category){const tag=document.createElement('span');tag.className='pill kind';tag.textContent=KINDS[note.category]||note.category;meta.append(tag);}
    meta.append(place);
    url.className='note-url';url.textContent=note.url || ORIGIN + note.path;
    resolve.textContent=note.resolved?'Reopen':'Resolve';
    const send=async(fields,button)=>{
      button.disabled=true;
      try {
        const {note:updated}=await api({action:'resolve',id:note.id,...fields});
        const swap=list=>list.map(item=>item.id===updated.id?updated:item);
        notes=swap(notes).filter(matchesFilter);pageCache=swap(pageCache);
        renderInbox();renderPrior();updateCount();
      } catch(e){ say(e.message,'inbox'); button.disabled=false; }
    };
    // Resolving asks for an optional close note and commit; reopening is one click, and the
    // resolution it undoes stays in the note's history.
    resolve.onclick=()=>{
      if(note.resolved) return send({resolved:false},resolve);
      const form=document.createElement('div'),outcome=document.createElement('select'),text=document.createElement('textarea'),
        commit=document.createElement('input'),twin=document.createElement('input'),
        row=document.createElement('div'),done=document.createElement('button'),cancel=document.createElement('button');
      form.className='close-form';
      for(const [value,label] of Object.entries(OUTCOMES)){const o=document.createElement('option');o.value=value;o.textContent=label;outcome.append(o);}
      outcome.setAttribute('aria-label','Outcome');
      text.maxLength=2000;text.setAttribute('aria-label','Close note');
      commit.maxLength=40;commit.placeholder='Commit';commit.setAttribute('aria-label','Commit');
      twin.maxLength=60;twin.placeholder='Duplicate of (note id)';twin.setAttribute('aria-label','Duplicate of');
      const fit=()=>{
        text.placeholder=outcome.value==='declined'?'Why not (required)':outcome.value==='done'?'What changed (required)':'Close note (optional)';
        commit.hidden=outcome.value!=='done';twin.hidden=outcome.value!=='duplicate';
      };
      outcome.onchange=fit;fit();
      done.type=cancel.type='button';done.textContent='Mark resolved';cancel.textContent='Cancel';
      done.onclick=()=>send({resolved:true,outcome:outcome.value,close_note:text.value,resolved_in:commit.value,duplicate_of:twin.value.trim()},done);
      cancel.onclick=()=>{form.remove();resolve.hidden=false;};
      row.append(done,cancel);form.append(outcome,text,commit,twin,row);
      resolve.hidden=true;actions.after(form);text.focus();
    };
    const copyOne=document.createElement('button');copyOne.type='button';copyOne.textContent='Copy details';
    copyOne.title='Copy just this note';
    copyOne.onclick=()=>copyText(report(note),'Copied this note.');
    actions.className='note-actions';actions.append(resolve,copyOne);
    article.append(head,comment,meta,url);
    if(note.resolved){
      const line=document.createElement('p');line.className='note-resolution';
      line.textContent=[(OUTCOMES[note.outcome]||'Resolved')+(note.resolved_by?' by '+author(note,'resolved_by'):'')+(note.resolved_at?' · '+when(note.resolved_at):''),
        note.close_note,note.resolved_in&&'commit '+note.resolved_in,note.duplicate_of&&'duplicate of '+note.duplicate_of].filter(Boolean).join(' · ');
      article.append(line);
    }
    for(const old of note.history||[]){
      const line=document.createElement('p');line.className='note-history';
      line.textContent='Earlier: resolved'+(old.resolved_at?' '+when(old.resolved_at):'')+(old.close_note?' ("'+old.close_note+'")':'')+
        (old.reopened_at?', reopened '+when(old.reopened_at):'');
      article.append(line);
    }
    article.append(actions);
    return article;
  }
  const collapsed=new Set();
  function renderInbox() {
    const groups=buckets(notes);
    $('notes').replaceChildren();
    for(const bucket of groups) {
      const details=document.createElement('details'),summary=document.createElement('summary'),
        label=document.createElement('span'),meta=document.createElement('span'),body=document.createElement('div');
      details.className='bucket'+(bucket.open?'':' resolved');
      details.open=!collapsed.has(bucket.key);
      label.className='bucket-label';label.textContent=bucket.label;
      meta.className='bucket-meta';meta.textContent=`${bucket.kind} · ${bucket.notes.length} note${bucket.notes.length===1?'':'s'} · ${bucket.open} open`;
      summary.append(label,meta);
      body.className='bucket-body';
      for(const note of bucket.notes) body.append(noteArticle(note));
      details.append(summary,body);
      details.addEventListener('toggle',()=>{if(details.open) collapsed.delete(bucket.key); else collapsed.add(bucket.key);});
      $('notes').append(details);
    }
    const open=notes.filter(note=>!note.resolved).length;
    $('filter-status').value=status;$('filter-kind').value=filterKind;
    $('summary').innerHTML=`<b>${notes.length}</b> note${notes.length===1?'':'s'}${nextCursor?'+':''} · ${open} open · ${groups.length} ${groups.length===1?'place':'places'}`;
    $('scope-page').setAttribute('aria-pressed',String(scope==='page'));
    $('scope-site').setAttribute('aria-pressed',String(scope==='site'));
    $('load-more').hidden=!nextCursor;
    $('copy').textContent=notes.length?`Copy all notes (${notes.length}${nextCursor?' loaded':''})`:'Copy all notes';
    $('copy').disabled=!notes.length;
    say(groups.length?'':(status==='all'&&!filterKind?(scope==='page'?'No notes on this page yet.':'No notes yet.'):'No notes match.'),'inbox');
  }
  // pageCache feeds the launcher badge and the composer's earlier notes; the
  // inbox owns its own paged list in `notes`.
  async function refreshPageNotes() {
    const path=currentPath(), found=(await api(null,{scope:'page',path})).notes;
    if(path!==currentPath()) return pageCache;  // navigated on while this was in flight
    pageCache=found; updateCount(); return pageCache;
  }
  // The site moves between tabs and runs by changing the hash, which is part of a note's path:
  // the badge has to follow, or it keeps counting the page you left.
  addEventListener('hashchange',()=>{ refreshPageNotes().then(()=>{ if(view==='compose') renderPrior(); }).catch(()=>{}); });
  // Only the newest request may fill the list: two quick loads (tab then filter) must not both append.
  let loadId=0;
  async function load(reset=true) {
    const mine=++loadId;
    if(reset){notes=[];nextCursor=null;$('summary').textContent='Loading…';say('','inbox');}
    try {
      const params={scope,status};
      if(filterKind) params.category=filterKind;
      if(scope==='page') params.path=currentPath();
      if(nextCursor) params.cursor=nextCursor;
      const data=await api(null,params);
      if(mine!==loadId) return;
      notes=notes.concat(data.notes);nextCursor=data.next||null;renderInbox();
    } catch(e){ if(mine!==loadId) return; $('summary').textContent='';say(e.message,'inbox'); }
  }
  $('launcher').onclick=openPanel;
  $('close').onclick=closePanel;$('cancel').onclick=stop;
  $('tab-compose').onclick=()=>showView('compose');
  $('tab-inbox').onclick=()=>showView('inbox');
  $('pick').onclick=()=>{picking=true;oldTouchAction=document.documentElement.style.touchAction;document.documentElement.style.touchAction='none';$('panel').hidden=true;$('launcher').hidden=true;$('hint').hidden=false;};
  $('page').onclick=()=>{target={kind:'page',viewport:{width:innerWidth,height:innerHeight}};composer();$('target').textContent='Whole page';syncClear();$('comment').focus();};
  $('clear').onclick=resetNote;
  $('comment').addEventListener('input',syncClear);
  $('refresh').onclick=()=>load(true);
  $('load-more').onclick=()=>load(false);
  $('scope-page').onclick=()=>{if(scope!=='page'){scope='page';load(true);}};
  $('scope-site').onclick=()=>{if(scope!=='site'){scope='site';load(true);}};
  $('filter-status').onchange=e=>{status=e.target.value;load(true);};
  $('filter-kind').onchange=e=>{filterKind=e.target.value;load(true);};
  $('kinds').onclick=e=>{const b=e.target.closest('button');if(b)setKind(b.dataset.kind);};
  $('save').onclick=async()=>{
    if(!kind){say('Pick a type first: bug, feature request or improvement idea.');return;}
    if(!$('comment').value.trim()){say('Add a comment first.');$('comment').focus();return;}
    $('save').disabled=true;
    try{const url=new URL(pageUrl());await api({category:kind,comment:$('comment').value,path:url.pathname+url.search+url.hash,url:url.href,target});$('comment').value='';setKind('');syncClear();say('');view='inbox';closePanel();sentFlash();refreshPageNotes().then(renderPrior).catch(()=>{});}
    catch(e){say(e.message);}finally{$('save').disabled=false;}
  };
  // The panel closes on a successful send; the launcher says so for a moment.
  let flashTimer;
  function sentFlash() {
    const button=$('launcher'), label=$('launcher-label');
    label.textContent='Sent';button.classList.add('sent');
    clearTimeout(flashTimer);
    flashTimer=setTimeout(()=>{label.textContent='Feedback';button.classList.remove('sent');},2500);
  }
  // Clipboard with a visible fallback: the text is shown in the list to select by hand.
  async function copyText(text,done) {
    try{await navigator.clipboard.writeText(text);say(done,'inbox');}
    catch{say('Clipboard unavailable. Select and copy below.','inbox');const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=text;$('notes').replaceChildren(pre);}
  }
  // Every note in the list, resolved or not, in a collapsed group or not.
  $('copy').onclick=()=>copyText(notes.map(report).join('\n\n---\n\n'),`Copied all ${notes.length} note${notes.length===1?'':'s'}${nextCursor?' loaded so far (Load more for the rest)':''}.`);
  const requested=new URLSearchParams(location.search).get('feedback');
  if(requested) {
    openPanel();
    // Opening a note to review it is a compose errand, whatever the panel opens on.
    showView('compose');
    api(null,{scope:'site'}).then(data=>{
      const note=data.notes.find(n=>n.id===requested);if(!note){say('This note is outside the latest notes.');return;}
      // The note already exists: show where it points, and leave the entry empty so it can't be sent twice.
      $('target').textContent=`Reviewing: ${note.target.text || note.path}`;syncClear();
      let attempts=0;
      const timer=setInterval(()=>{
        let el;try{el=note.target.selector && document.querySelector(note.target.selector);}catch{}
        if(el){clearInterval(timer);if(note.target.kind==='region' && note.target.scroll && note.target.rect){window.scrollTo(note.target.scroll.x,note.target.scroll.y);rect(note.target.rect);}else{el.scrollIntoView({block:'center'});rect(el.getBoundingClientRect());}setTimeout(()=>mark.style.display='none',6000);}
        else if(++attempts>=30){clearInterval(timer);say('Original element unavailable. Use the saved text and viewport in Copy.');}
      },300);
    }).catch(e=>say(e.message));
  } else {
    // Show how much feedback is already waiting on this page, so it is found
    // before it is written again. A failure leaves the plain launcher.
    refreshPageNotes().catch(()=>{});
  }
})();