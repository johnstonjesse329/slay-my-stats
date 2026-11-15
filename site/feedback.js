// Gamma-only feedback. No dependencies on the dashboard's render lifecycle.
(() => {
  if (location.hostname !== 'gamma.slay-my-stats.com' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') return;
  const host = document.createElement('div');
  host.id = 'gamma-feedback';
  document.body.append(host);
  const root = host.attachShadow({mode: 'open'});
  root.innerHTML = `<style>
    :host{font:14px system-ui;color:#f4f0e7;position:fixed;bottom:16px;right:16px;z-index:2147483646}
    *{box-sizing:border-box}button,textarea{font:inherit}button,a{touch-action:manipulation}
    button{background:#302d27;color:#fff;border:1px solid #82735b;border-radius:6px;padding:10px;cursor:pointer}
    button:hover{background:#514635}button:disabled{opacity:.5}a{color:#edc782}
    #launcher{display:flex;align-items:center;gap:8px;padding:12px 20px;border:1px solid #f6e3b0;border-radius:999px;background:linear-gradient(#f4dda6,#e0c468);color:#191c20;font-size:15px;font-weight:700;box-shadow:0 6px 20px #000a}
    #launcher:hover{background:linear-gradient(#f9e7ba,#e8cf7c)}
    #launcher:focus-visible{outline:3px solid #f6c66d;outline-offset:3px}
    #page-url{display:block;margin:2px 0 10px;color:#bcb8b0;font-size:12px;line-height:1.4;overflow-wrap:anywhere}
    article .note-url{display:block;color:#bcb8b0;font-size:12px;overflow-wrap:anywhere}
    #launcher-count{min-width:20px;padding:1px 6px;border-radius:999px;background:#191c20;color:#f4dda6;font-size:12px;font-weight:700;text-align:center}
    #prior{margin:0 0 12px;padding:10px 12px;border:1px solid #635948;border-radius:6px;background:#101316}
    #prior b{display:block;margin-bottom:6px}#prior ul{margin:0;padding-left:16px;max-height:150px;overflow:auto}
    #prior li{margin:4px 0;line-height:1.4}#prior .resolved{color:#8f8a80;text-decoration:line-through}
    .bucket > summary{cursor:pointer;padding:6px 0;font-weight:700;line-height:1.4}
    .bucket > summary small{display:block;font-weight:400;color:#bcb8b0}
    #panel{background:#191c20;border:1px solid #82735b;border-radius:10px;padding:16px;width:390px;max-width:calc(100vw - 32px);max-height:calc(100dvh - 32px);overflow:auto;box-shadow:0 8px 40px #0009}
    h2{font-size:19px;margin:0}p{line-height:1.45}nav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
    textarea{width:100%;min-height:100px;background:#101316;color:#fff;border:1px solid #82735b;padding:9px;border-radius:5px}
    article{border-top:1px solid #635948;padding:12px 0;overflow-wrap:anywhere}article p{white-space:pre-wrap}
    small{color:#bcb8b0}#status{white-space:pre-wrap}header{display:flex;justify-content:space-between;align-items:center;gap:12px}
    [hidden]{display:none!important}#hint{background:#191c20;padding:12px;max-width:310px;border:1px solid #edc782;border-radius:6px}
    @media(max-height:500px){:host{bottom:8px;right:8px}#panel{max-height:calc(100dvh - 16px);width:460px}textarea{min-height:65px}#launcher{padding:9px 16px;font-size:14px}}
  </style><button id="launcher" type="button"><span aria-hidden="true">✎</span> Feedback<span id="launcher-count" aria-hidden="true" hidden></span></button>
  <div id="hint" hidden>Choose an element on the page. For a region, drag across it. Press Escape to cancel. <button id="cancel">Cancel</button></div>
  <section id="panel" role="dialog" aria-label="Gamma feedback" hidden>
    <header><h2>Gamma feedback</h2><button id="close" aria-label="Close feedback">Close</button></header>
    <nav><button id="pick">Pin to element / region</button><button id="page">Whole page</button><button id="inbox">Inbox</button></nav>
    <div id="composer"><p id="target">Feedback for this page</p><small id="page-url"></small><div id="prior" hidden></div><label for="comment">What should change?</label>
    <textarea id="comment" maxlength="4000" placeholder="Describe the issue or suggestion…"></textarea>
    <nav><button id="save">Send feedback</button></nav><small>Shared with everyone who has access to gamma. Page link, selected text and viewport are included.</small></div>
    <div id="review" hidden><nav><button id="copy">Copy open notes</button><button id="refresh">Refresh</button></nav><div id="notes"></div></div>
    <p id="status" role="status"></p>
  </section>`;
  const $ = id => root.getElementById(id);
  let target = {kind: 'page',viewport:{width:innerWidth,height:innerHeight}}, notes = [], picking = false, start, previousFocus, oldTouchAction;
  const mark = document.createElement('div');
  Object.assign(mark.style, {position:'fixed',pointerEvents:'none',zIndex:'2147483645',border:'2px solid #f6c66d',background:'#f6c66d22',display:'none'});
  document.body.append(mark);
  function rect(box) { Object.assign(mark.style,{display:'block',left:box.x+'px',top:box.y+'px',width:box.width+'px',height:box.height+'px'}); }
  function panel(open) { $('panel').hidden=!open; $('launcher').hidden=open; if(open) { previousFocus=document.activeElement; $('page-url').textContent=pageUrl(); renderPrior(); $('close').focus(); } else previousFocus?.focus(); }
  function pageUrl() { const url=new URL(location.href); url.searchParams.delete('feedback'); return url.href; }
  function currentPath() { const url=new URL(pageUrl()); return url.pathname+url.search+url.hash; }
  function composer() { $('composer').hidden=false; $('review').hidden=true; $('status').textContent=''; $('page-url').textContent=pageUrl(); renderPrior(); }
  // Notes already recorded for the same page and the same pick, so a reviewer
  // sees the history where they are about to write instead of repeating it.
  function sameTarget(note) {
    if (target.kind==='page') return note.target?.kind==='page';
    return note.target?.kind!=='page' && note.target?.selector===target.selector;
  }
  function renderPrior() {
    const box=$('prior'), matches=notes.filter(note=>note.path===currentPath() && sameTarget(note));
    box.replaceChildren();
    if(!matches.length){box.hidden=true;return;}
    const open=matches.filter(note=>!note.resolved).length, title=document.createElement('b'), list=document.createElement('ul');
    title.textContent=`${matches.length} earlier note${matches.length===1?'':'s'} here`+(open?` · ${open} open`:' · all resolved');
    for(const note of matches.slice(0,8)) {
      const li=document.createElement('li');
      li.textContent=`${note.resolved?'[resolved] ':''}${note.comment.replace(/\s+/g,' ').slice(0,240)} · ${note.author}`;
      if(note.resolved) li.className='resolved';
      list.append(li);
    }
    box.append(title,list);box.hidden=false;
  }
  function stop() { picking=false; document.documentElement.style.touchAction=oldTouchAction; start=null; mark.style.display='none'; $('hint').hidden=true; panel(true); }
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
    stop();composer();$('target').textContent=`Pinned ${target.kind}: ${target.text.slice(0,100) || el.localName}`; $('comment').focus();
  },true);
  // Consume the synthetic click following selection, including links and buttons.
  let suppressClick=false;
  document.addEventListener('click',e=>{if(suppressClick && !e.composedPath().includes(host)){e.preventDefault();e.stopImmediatePropagation();suppressClick=false;}},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(picking)stop();else if(!$('panel').hidden)panel(false);}});
  async function api(body) {
    const response=await fetch('/auth/feedback',{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    if(!response.ok) throw new Error(response.status===401?'Sign in to gamma again.':`Could not ${body?'save':'load'} feedback. Please retry.`);
    return response.json();
  }
  const report = note => `Feedback ${note.id}\n${note.resolved?'Resolved':'Open'} · ${new Date(note.created*1000).toISOString()}\n${note.url || location.origin + note.path}\n${JSON.stringify(note.target,null,2)}\n\n${note.comment}`;
  function pageNotes() { const path=currentPath(); return notes.filter(note=>note.path===path); }
  function updateLauncher() {
    const open=pageNotes().filter(note=>!note.resolved).length;
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
  function noteArticle(note) {
    const article=document.createElement('article'),meta=document.createElement('small'),p=document.createElement('p'),link=document.createElement('a'),resolve=document.createElement('button');
    meta.textContent=`${note.resolved?'Resolved':'Open'} · ${new Date(note.created*1000).toLocaleString()} · ${note.author}`;
    p.textContent=note.comment;link.textContent='Open location';
    const url=new URL(note.path,location.origin);url.searchParams.set('feedback',note.id);link.href=url.href;
    resolve.textContent=note.resolved?'Reopen':'Resolve';
    resolve.onclick=async()=>{resolve.disabled=true;try{await api({action:'resolve',id:note.id,resolved:!note.resolved});await refreshNotes();renderInbox();renderPrior();}catch(e){$('status').textContent=e.message;resolve.disabled=false;}};
    const context=document.createElement('p');context.textContent=`${note.target.kind}: ${note.target.text?.slice(0,180) || note.path}`;
    const noteUrl=document.createElement('small');noteUrl.className='note-url';noteUrl.textContent=note.url || location.origin + note.path;
    article.append(meta,noteUrl,p,context,link,document.createTextNode(' '),resolve);
    return article;
  }
  const collapsed=new Set();
  function renderInbox() {
    const groups=buckets(notes);
    $('notes').replaceChildren();
    for(const bucket of groups) {
      const details=document.createElement('details'),summary=document.createElement('summary'),meta=document.createElement('small');
      details.className='bucket';details.open=!collapsed.has(bucket.key);
      summary.append(bucket.label,meta);
      meta.textContent=`${bucket.kind} · ${bucket.notes.length} note${bucket.notes.length===1?'':'s'} · ${bucket.open} open`;
      details.append(summary);
      for(const note of bucket.notes) details.append(noteArticle(note));
      details.addEventListener('toggle',()=>{if(details.open) collapsed.delete(bucket.key); else collapsed.add(bucket.key);});
      $('notes').append(details);
    }
    $('status').textContent=groups.length?`${notes.length} latest note${notes.length===1?'':'s'} · ${groups.length} ${groups.length===1?'place':'places'}`:'No feedback yet.';
  }
  async function refreshNotes() { notes=(await api()).notes; updateLauncher(); return notes; }
  async function load() {
    $('composer').hidden=true;$('review').hidden=false;$('status').textContent='Loading…';
    try { await refreshNotes(); renderInbox(); } catch(e){ $('status').textContent=e.message; }
  }
  $('launcher').onclick=()=>panel(true);$('close').onclick=()=>panel(false);$('cancel').onclick=stop;
  $('pick').onclick=()=>{picking=true;oldTouchAction=document.documentElement.style.touchAction;document.documentElement.style.touchAction='none';panel(false);$('launcher').hidden=true;$('hint').hidden=false;};
  $('page').onclick=()=>{target={kind:'page',viewport:{width:innerWidth,height:innerHeight}};composer();$('target').textContent='Feedback for this page';$('comment').focus();};
  $('inbox').onclick=load;$('refresh').onclick=load;
  $('save').onclick=async()=>{
    if(!$('comment').value.trim()){$('status').textContent='Add a comment first.';$('comment').focus();return;}
    $('save').disabled=true;
    try{const url=new URL(pageUrl());await api({comment:$('comment').value,path:url.pathname+url.search+url.hash,url:url.href,target});$('comment').value='';$('status').textContent='Feedback sent to the shared inbox.';await refreshNotes();renderPrior();}
    catch(e){$('status').textContent=e.message;}finally{$('save').disabled=false;}
  };
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText(notes.filter(n=>!n.resolved).map(report).join('\n\n---\n\n'));$('status').textContent='Open notes copied. Paste them into your conversation.';}catch{$('status').textContent='Clipboard unavailable. Select and copy the notes below.';const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=notes.filter(n=>!n.resolved).map(report).join('\n\n');$('notes').replaceChildren(pre);}};
  const requested=new URLSearchParams(location.search).get('feedback');
  if(requested) {
    panel(true);
    refreshNotes().then(()=>{
      const note=notes.find(n=>n.id===requested);if(!note){$('status').textContent='This note is outside the latest 200 notes.';return;}
      $('comment').value=note.comment;$('target').textContent=`Reviewing ${note.target.kind}: ${note.target.text || note.path}`;
      let attempts=0;
      const timer=setInterval(()=>{
        let el;try{el=note.target.selector && document.querySelector(note.target.selector);}catch{}
        if(el){clearInterval(timer);if(note.target.kind==='region' && note.target.scroll && note.target.rect){window.scrollTo(note.target.scroll.x,note.target.scroll.y);rect(note.target.rect);}else{el.scrollIntoView({block:'center'});rect(el.getBoundingClientRect());}setTimeout(()=>mark.style.display='none',6000);}
        else if(++attempts>=30){clearInterval(timer);$('status').textContent='Original element unavailable. Use the saved text and viewport in Copy open notes.';}
      },300);
    }).catch(e=>$('status').textContent=e.message);
  } else {
    // Show how much feedback is already waiting on this page, so it is found
    // before it is written again. A failure leaves the plain launcher.
    refreshNotes().catch(()=>{});
  }
})();
