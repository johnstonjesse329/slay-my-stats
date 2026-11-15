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
    #panel{background:#191c20;border:1px solid #82735b;border-radius:10px;padding:16px;width:390px;max-width:calc(100vw - 32px);max-height:calc(100dvh - 32px);overflow:auto;box-shadow:0 8px 40px #0009}
    h2{font-size:19px;margin:0}p{line-height:1.45}nav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
    textarea{width:100%;min-height:100px;background:#101316;color:#fff;border:1px solid #82735b;padding:9px;border-radius:5px}
    article{border-top:1px solid #635948;padding:12px 0;overflow-wrap:anywhere}article p{white-space:pre-wrap}
    small{color:#bcb8b0}#status{white-space:pre-wrap}header{display:flex;justify-content:space-between;align-items:center;gap:12px}
    [hidden]{display:none!important}#hint{background:#191c20;padding:12px;max-width:310px;border:1px solid #edc782;border-radius:6px}
    @media(max-height:500px){:host{bottom:8px;right:8px}#panel{max-height:calc(100dvh - 16px);width:460px}textarea{min-height:65px}}
  </style><button id="launcher">Feedback</button>
  <div id="hint" hidden>Choose an element on the page. For a region, drag across it. Press Escape to cancel. <button id="cancel">Cancel</button></div>
  <section id="panel" role="dialog" aria-label="Gamma feedback" hidden>
    <header><h2>Gamma feedback</h2><button id="close" aria-label="Close feedback">Close</button></header>
    <nav><button id="pick">Pin to element / region</button><button id="page">Whole page</button><button id="inbox">Inbox</button></nav>
    <div id="composer"><p id="target">Feedback for this page</p><label for="comment">What should change?</label>
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
  function panel(open) { $('panel').hidden=!open; $('launcher').hidden=open; if(open) { previousFocus=document.activeElement; $('close').focus(); } else previousFocus?.focus(); }
  function composer() { $('composer').hidden=false; $('review').hidden=true; $('status').textContent=''; }
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
  const report = note => `Feedback ${note.id}\n${note.resolved?'Resolved':'Open'} · ${new Date(note.created*1000).toISOString()}\n${location.origin}${note.path}\n${JSON.stringify(note.target,null,2)}\n\n${note.comment}`;
  async function load() {
    $('composer').hidden=true;$('review').hidden=false;$('status').textContent='Loading…';
    try {
      notes=(await api()).notes;$('notes').replaceChildren();
      for(const note of notes) {
        const article=document.createElement('article'),meta=document.createElement('small'),p=document.createElement('p'),link=document.createElement('a'),resolve=document.createElement('button');
        meta.textContent=`${note.resolved?'Resolved':'Open'} · ${new Date(note.created*1000).toLocaleString()} · ${note.author}`;
        p.textContent=note.comment;link.textContent='Open location';
        const url=new URL(note.path,location.origin);url.searchParams.set('feedback',note.id);link.href=url.href;
        resolve.textContent=note.resolved?'Reopen':'Resolve';resolve.onclick=async()=>{resolve.disabled=true;try{await api({action:'resolve',id:note.id,resolved:!note.resolved});await load();}catch(e){$('status').textContent=e.message;resolve.disabled=false;}};
        const context=document.createElement('p');context.textContent=`${note.target.kind}: ${note.target.text?.slice(0,180) || note.path}`;
        article.append(meta,p,context,link,document.createTextNode(' '),resolve);$('notes').append(article);
      }
      $('status').textContent=notes.length?`${notes.length} latest notes`:'No feedback yet.';
    }catch(e){$('status').textContent=e.message;}
  }
  $('launcher').onclick=()=>panel(true);$('close').onclick=()=>panel(false);$('cancel').onclick=stop;
  $('pick').onclick=()=>{picking=true;oldTouchAction=document.documentElement.style.touchAction;document.documentElement.style.touchAction='none';panel(false);$('launcher').hidden=true;$('hint').hidden=false;};
  $('page').onclick=()=>{target={kind:'page',viewport:{width:innerWidth,height:innerHeight}};composer();$('target').textContent='Feedback for this page';$('comment').focus();};
  $('inbox').onclick=load;$('refresh').onclick=load;
  $('save').onclick=async()=>{
    if(!$('comment').value.trim()){$('status').textContent='Add a comment first.';$('comment').focus();return;}
    $('save').disabled=true;
    try{const url=new URL(location.href);url.searchParams.delete('feedback');await api({comment:$('comment').value,path:url.pathname+url.search+url.hash,target});$('comment').value='';$('status').textContent='Feedback sent to the shared inbox.';}
    catch(e){$('status').textContent=e.message;}finally{$('save').disabled=false;}
  };
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText(notes.filter(n=>!n.resolved).map(report).join('\n\n---\n\n'));$('status').textContent='Open notes copied. Paste them into your conversation.';}catch{$('status').textContent='Clipboard unavailable. Select and copy the notes below.';const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=notes.filter(n=>!n.resolved).map(report).join('\n\n');$('notes').replaceChildren(pre);}};
  const requested=new URLSearchParams(location.search).get('feedback');
  if(requested) {
    panel(true);
    api().then(data=>{
      const note=data.notes.find(n=>n.id===requested);if(!note){$('status').textContent='This note is outside the latest 200 notes.';return;}
      $('comment').value=note.comment;$('target').textContent=`Reviewing ${note.target.kind}: ${note.target.text || note.path}`;
      let attempts=0;
      const timer=setInterval(()=>{
        let el;try{el=note.target.selector && document.querySelector(note.target.selector);}catch{}
        if(el){clearInterval(timer);if(note.target.kind==='region' && note.target.scroll && note.target.rect){window.scrollTo(note.target.scroll.x,note.target.scroll.y);rect(note.target.rect);}else{el.scrollIntoView({block:'center'});rect(el.getBoundingClientRect());}setTimeout(()=>mark.style.display='none',6000);}
        else if(++attempts>=30){clearInterval(timer);$('status').textContent='Original element unavailable. Use the saved text and viewport in Copy open notes.';}
      },300);
    }).catch(e=>$('status').textContent=e.message);
  }
})();
