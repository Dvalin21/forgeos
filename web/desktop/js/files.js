(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s)};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  function token(){try{return localStorage.getItem('forgeos_token')}catch(e){return null}}
  async function api(p,o){o=o||{};var h=Object.assign({},o.headers||{});var t=token();if(t)h.Authorization='Bearer '+t;
    if(o.body&&!h['Content-Type']&&!(o.body instanceof FormData))h['Content-Type']='application/json';
    try{var r=await fetch(p,Object.assign({},o,{headers:h}));var d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,data:null}}}
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
  function fmtBytes(b){if(b==null)return '—';b=Number(b)||0;if(b===0)return '—';if(b>=1e12)return (b/1e12).toFixed(1)+' TB';if(b>=1e9)return (b/1e9).toFixed(1)+' GB';if(b>=1e6)return (b/1e6).toFixed(1)+' MB';if(b>=1e3)return (b/1e3).toFixed(0)+' KB';return b+' B'}
  function fmtTime(t){if(!t)return '—';var d=new Date(t*1000);return d.toLocaleString()}
  function toast(m,k){k=k||'info';var b=$('#toasts'),e=document.createElement('div');e.className='toast '+k;e.textContent=m;b.appendChild(e);setTimeout(function(){e.style.transition='opacity .2s';e.style.opacity=0;setTimeout(function(){e.remove()},220)},4000)}

  // ── modal (with optional html body) ──
  function modal(o){
    var back=document.createElement('div');back.className='modal-back';
    var f=(o.fields||[]).map(function(x){
      if(x.type==='select'){var op=x.options.map(function(q){return '<option value="'+esc(q.value)+'">'+esc(q.label)+'</option>'}).join('');
        return '<div class="field"><label>'+esc(x.label)+'</label><select id="mf-'+x.id+'">'+op+'</select></div>'}
      return '<div class="field"><label>'+esc(x.label)+'</label><input id="mf-'+x.id+'" type="'+(x.type||'text')+'" placeholder="'+esc(x.ph||'')+'" value="'+esc(x.val||'')+'"></div>'}).join('');
    back.innerHTML='<div class="modal'+(o.big?' big':'')+'"><h3>'+esc(o.title)+'</h3>'+(o.sub?'<p class="sub">'+esc(o.sub)+'</p>':'')+(o.warn?'<div class="warn-box">'+esc(o.warn)+'</div>':'')+(o.html||'')+f+
      '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">'+(o.cta===null?'':'<button class="btn-ghost" data-x>Cancel</button><button class="'+(o.danger?'btn-pri btn-danger':'btn-pri')+'" data-go>'+esc(o.cta||'Confirm')+'</button>')+(o.cta===null?'<button class="btn-pri" data-x>Close</button>':'')+'</div></div>';
    document.body.appendChild(back);var close=function(){back.remove()};
    back.addEventListener('click',function(e){if(e.target===back||e.target.hasAttribute('data-x'))close()});
    var go=$('[data-go]',back);if(go)go.addEventListener('click',function(){var v={};(o.fields||[]).forEach(function(x){v[x.id]=($('#mf-'+x.id,back)||{}).value});
      Promise.resolve(o.onSubmit(v,back)).then(function(ok){if(ok!==false)close()})});
    var fi=back.querySelector('input,select');if(fi&&!o.big)fi.focus();
    return {close:close,el:back};
  }

  // ── state ──
  var CWD=null,ENTRIES=[],SELECTED=new Set(),CLIPBOARD=null,ROOTS=[];

  function iconFor(e){
    if(e.type==='dir')return {cls:'dir',svg:'<svg viewBox=\"0 0 24 24\"><path d=\"M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/></svg>'};
    var n=(e.name||'').toLowerCase(),ext=n.split('.').pop();
    if(/^(jpg|jpeg|png|gif|webp|svg|bmp|heic)$/.test(ext))return {cls:'image',svg:'<svg viewBox=\"0 0 24 24\"><rect x=\"3\" y=\"5\" width=\"18\" height=\"14\" rx=\"2\"/><circle cx=\"9\" cy=\"10\" r=\"1.5\"/><path d=\"M21 17l-5-5-9 9\"/></svg>'};
    if(/^(mp4|mkv|mov|webm|avi|m4v)$/.test(ext))return {cls:'video',svg:'<svg viewBox=\"0 0 24 24\"><rect x=\"3\" y=\"5\" width=\"18\" height=\"14\" rx=\"2\"/><path d=\"M10 9l5 3-5 3z\"/></svg>'};
    if(/^(mp3|wav|flac|ogg|m4a|aac)$/.test(ext))return {cls:'audio',svg:'<svg viewBox=\"0 0 24 24\"><path d=\"M9 18V6l10-2v12\"/><circle cx=\"6\" cy=\"18\" r=\"3\"/><circle cx=\"16\" cy=\"16\" r=\"3\"/></svg>'};
    if(/^(zip|tar|gz|7z|rar|xz|bz2)$/.test(ext))return {cls:'archive',svg:'<svg viewBox=\"0 0 24 24\"><path d=\"M5 4h14v16H5z\"/><path d=\"M10 4v3M10 9v3M10 14v3M10 19v1\"/></svg>'};
    if(/^(py|js|jsx|ts|tsx|sh|c|cpp|rs|go|java|html|css|json|yaml|yml|toml|conf|ini)$/.test(ext))return {cls:'code',svg:'<svg viewBox=\"0 0 24 24\"><path d=\"M8 9l-4 3 4 3M16 9l4 3-4 3M14 6l-4 12\"/></svg>'};
    return {cls:'file',svg:'<svg viewBox=\"0 0 24 24\"><path d=\"M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z\"/><path d=\"M14 3v5h5\"/></svg>'};
  }
  function previewKind(e){
    var n=(e.name||'').toLowerCase(),ext=n.indexOf('.')>=0?n.split('.').pop():'';
    if(/^(jpg|jpeg|png|gif|webp|svg|bmp)$/.test(ext))return 'image';
    if(/^(mp4|mkv|mov|webm|m4v)$/.test(ext))return 'video';
    if(/^(mp3|wav|flac|ogg|m4a|aac)$/.test(ext))return 'audio';
    if(!ext||/^(txt|md|log|conf|ini|json|yaml|yml|toml|sh|py|js|jsx|ts|tsx|c|cpp|h|rs|go|java|html|css|sql|csv|xml)$/.test(ext))return 'text';
    return null;
  }

  // ── tree ──
  async function loadRoots(){
    var d=(await api('/api/files/roots')).data;ROOTS=(d&&d.roots)||['/srv/nas'];
    var tb=$('#tree-body');tb.innerHTML=ROOTS.map(function(r){
      return '<div class="tree-node" data-go="'+esc(r)+'"><svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>'+esc(r.split('/').pop()||r)+'</div>'+
        '<div class="tree-children" data-children="'+esc(r)+'"></div>'}).join('');
    $$('#tree-body .tree-node').forEach(function(n){n.onclick=function(){go(n.getAttribute('data-go'))}});
    if(!CWD)go(ROOTS[0]);
  }
  async function expandTree(path){
    var holder=$('[data-children="'+CSS.escape(path)+'"]');if(!holder)return;
    var d=(await api('/api/files/list?path='+encodeURIComponent(path))).data;
    if(!d)return;var dirs=(d.entries||[]).filter(function(e){return e.type==='dir'});
    holder.innerHTML=dirs.map(function(e){return '<div class="tree-node" data-go="'+esc(e.path)+'"><svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>'+esc(e.name)+'</div>'}).join('');
    $$('[data-children="'+CSS.escape(path)+'"] .tree-node').forEach(function(n){n.onclick=function(ev){ev.stopPropagation();go(n.getAttribute('data-go'))}});
  }

  // ── list ──
  async function go(path){
    var d=(await api('/api/files/list?path='+encodeURIComponent(path))).data;
    if(!d){toast('Could not open '+path,'err');return}
    CWD=d.path;ENTRIES=d.entries||[];SELECTED.clear();
    // crumbs
    $('#crumbs').innerHTML=(d.crumbs||[]).map(function(c,i,a){return '<a class="'+(i===a.length-1?'cur':'')+'" data-go="'+esc(c.path)+'">'+esc(c.name||'/')+'</a>'+(i<a.length-1?'<span>›</span>':'')}).join('');
    $$('#crumbs a').forEach(function(a){a.onclick=function(){go(a.getAttribute('data-go'))}});
    // tree highlight + expand
    $$('#tree .tree-node').forEach(function(n){n.classList.toggle('sel',n.getAttribute('data-go')===CWD)});
    var matchRoot=ROOTS.find(function(r){return CWD===r||CWD.indexOf(r+'/')===0});if(matchRoot)expandTree(matchRoot);
    // rows
    var tb=$('#rows');
    if(!ENTRIES.length){tb.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:40px">This folder is empty.</td></tr>';refreshToolbar();return}
    tb.innerHTML=ENTRIES.map(function(e,i){
      var ic=iconFor(e),cut=CLIPBOARD&&CLIPBOARD.op==='cut'&&CLIPBOARD.items.indexOf(e.path)>=0;
      return '<tr data-i="'+i+'"'+(cut?' class="cut"':'')+'>'+
        '<td><input type="checkbox" class="ck" data-i="'+i+'"></td>'+
        '<td><div class="name-cell"><div class="ftype '+ic.cls+'">'+ic.svg+'</div><span>'+esc(e.name)+'</span></div></td>'+
        '<td>'+(e.type==='dir'?'—':fmtBytes(e.size))+'</td>'+
        '<td style="color:var(--muted);font-size:12px">'+fmtTime(e.mtime)+'</td>'+
        '<td><span class="mode">'+esc(e.mode_str||'')+'</span></td>'+
        '<td><span class="owner">'+esc(e.owner||'?')+':'+esc(e.group||'?')+'</span></td></tr>'}).join('');
    $$('#rows tr').forEach(function(tr){
      var i=+tr.getAttribute('data-i'),e=ENTRIES[i];
      tr.ondblclick=function(){e.type==='dir'?go(e.path):openPreview(e)};
      tr.onclick=function(ev){if(ev.target.classList.contains('ck'))return;
        if(!ev.shiftKey&&!ev.ctrlKey&&!ev.metaKey)SELECTED.clear();
        SELECTED.has(e.path)?SELECTED.delete(e.path):SELECTED.add(e.path);refreshSel()};
      tr.oncontextmenu=function(ev){
        ev.preventDefault();
        // right-click acts on the clicked row: if it isn't part of the current
        // selection, make it the selection (standard file-manager behavior).
        if(!SELECTED.has(e.path)){SELECTED.clear();SELECTED.add(e.path);refreshSel()}
        showContextMenu(ev.clientX,ev.clientY,false);
      };
    });
    $$('#rows .ck').forEach(function(c){c.onchange=function(){var i=+c.getAttribute('data-i'),e=ENTRIES[i];c.checked?SELECTED.add(e.path):SELECTED.delete(e.path);refreshSel()}});
    refreshSel();refreshToolbar();
  }
  function refreshSel(){$$('#rows tr').forEach(function(tr){var i=+tr.getAttribute('data-i'),e=ENTRIES[i];var s=SELECTED.has(e.path);tr.classList.toggle('sel',s);var c=$('.ck',tr);if(c)c.checked=s});refreshToolbar()}
  function refreshToolbar(){
    var n=SELECTED.size,one=n===1;
    $('#btn-cut').disabled=$('#btn-copy').disabled=$('#btn-delete').disabled=n===0;
    $('#btn-rename').disabled=$('#btn-perms').disabled=$('#btn-download').disabled=!one;
    $('#btn-paste').disabled=!CLIPBOARD||!CLIPBOARD.items.length;
    if(one){var e=selEntries()[0];if(e&&e.type==='dir')$('#btn-download').disabled=true}
  }
  // ── context menu (a second trigger for the toolbar's own handlers) ──
  function closeContextMenu(){var m=$('#ctx-menu');if(m)m.remove();}
  function showContextMenu(x,y,emptyArea){
    closeContextMenu();
    var n=SELECTED.size,one=n===1;
    var e=one?selEntries()[0]:null;
    var canDownload=one&&e&&e.type!=='dir';
    var canPaste=!!(CLIPBOARD&&CLIPBOARD.items&&CLIPBOARD.items.length);
    // [label, handler, enabled, danger?]  — null = separator
    var items=emptyArea?[
      ['New folder',newFolder,true],
      ['Paste',doPaste,canPaste]
    ]:[
      ['Open',function(){e.type==='dir'?go(e.path):openPreview(e)},one],
      ['Download',download,canDownload],
      null,
      ['Cut',doCut,n>=1],
      ['Copy',doCopy,n>=1],
      ['Paste',doPaste,canPaste],
      null,
      ['Rename',rename,one],
      ['Permissions',editPerms,one],
      null,
      ['Delete',delSel,n>=1,true]
    ];
    var m=document.createElement('div');m.id='ctx-menu';m.className='ctx-menu';
    m.innerHTML=items.map(function(it){
      if(!it)return '<div class="ctx-sep"></div>';
      return '<button class="ctx-item'+(it[3]?' danger':'')+'"'+(it[2]?'':' disabled')+'>'+esc(it[0])+'</button>';
    }).join('');
    document.body.appendChild(m);
    // clamp to viewport so it never opens off-screen
    var r=m.getBoundingClientRect();
    var px=Math.min(x,window.innerWidth-r.width-6);
    var py=Math.min(y,window.innerHeight-r.height-6);
    m.style.left=Math.max(6,px)+'px';m.style.top=Math.max(6,py)+'px';
    var btns=m.querySelectorAll('.ctx-item');var bi=0;
    items.forEach(function(it){
      if(!it)return;var btn=btns[bi++];
      if(it[2])btn.onclick=function(){closeContextMenu();it[1]();};
    });
  }
  // dismiss on any outside click / escape / scroll
  document.addEventListener('click',function(e){if(!e.target.closest('#ctx-menu'))closeContextMenu();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeContextMenu();});
  window.addEventListener('resize',closeContextMenu);


  async function newFolder(){
    modal({title:'New folder',sub:'Create a folder in '+CWD,fields:[{id:'name',label:'Folder name',ph:'documents'}],cta:'Create',
      onSubmit:async function(v){if(!v.name){toast('Name required','warn');return false}
        var r=await api('/api/files/mkdir',{method:'POST',body:JSON.stringify({path:CWD,name:v.name})});
        toast(r.ok?'Folder created':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');if(r.ok)go(CWD);return r.ok}});
  }
  async function rename(){
    var e=selEntries()[0];if(!e)return;
    modal({title:'Rename',sub:'Rename "'+e.name+'"',fields:[{id:'name',label:'New name',val:e.name}],cta:'Rename',
      onSubmit:async function(v){if(!v.name){toast('Name required','warn');return false}
        var r=await api('/api/files/rename',{method:'POST',body:JSON.stringify({src:e.path,name:v.name})});
        toast(r.ok?'Renamed':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');if(r.ok)go(CWD);return r.ok}});
  }
  function doCut(){CLIPBOARD={op:'cut',items:[...SELECTED]};toast(CLIPBOARD.items.length+' item(s) cut','info');go(CWD)}
  function doCopy(){CLIPBOARD={op:'copy',items:[...SELECTED]};toast(CLIPBOARD.items.length+' item(s) copied','info');refreshToolbar()}
  async function doPaste(){
    if(!CLIPBOARD||!CLIPBOARD.items.length)return;
    var ep=CLIPBOARD.op==='cut'?'/api/files/move':'/api/files/copy';
    var r=await api(ep,{method:'POST',body:JSON.stringify({items:CLIPBOARD.items,target:CWD})});
    toast(r.ok?(CLIPBOARD.op==='cut'?'Moved':'Copied')+' '+(r.data&&r.data.count||CLIPBOARD.items.length)+' item(s)':(r.data&&r.data.detail)||'Paste failed',r.ok?'ok':'err');
    if(r.ok){CLIPBOARD=null;go(CWD)}
  }
  function delSel(){
    var n=SELECTED.size;if(!n)return;
    modal({title:'Delete '+n+' item'+(n>1?'s':''),sub:'This permanently removes the selected files and folders.',
      warn:'Deleted data cannot be recovered through this interface.',danger:true,cta:'Delete permanently',
      onSubmit:async function(){var items=[...SELECTED];var ok=0,fail=0;
        for(var i=0;i<items.length;i++){var r=await api('/api/files/delete',{method:'POST',body:JSON.stringify({path:items[i]})});r.ok?ok++:fail++}
        toast((fail?fail+' failed, ':'')+ok+' deleted',fail?'warn':'ok');go(CWD);return true}});
  }
  async function download(){
    var e=selEntries()[0];if(!e||e.type==='dir')return;
    var url='/api/files/download?path='+encodeURIComponent(e.path);var t=token();
    // Anchor-based download with auth header isn't trivial; fetch as blob then trigger.
    var r=await fetch(url,{headers:t?{Authorization:'Bearer '+t}:{}});if(!r.ok){toast('Download failed','err');return}
    var blob=await r.blob();var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=e.name;a.click();setTimeout(function(){URL.revokeObjectURL(a.href)},1000);
  }

  // ── permissions editor ──
  async function editPerms(){
    var e=selEntries()[0];if(!e)return;
    var idents=(await api('/api/files/idents')).data||{users:[],groups:[]};
    var mode=e.mode||0o644;
    var bits=[(mode>>6)&7,(mode>>3)&7,mode&7];
    function row(label,key){var n=key===0?'o':key===1?'g':'a';return '<div class="who">'+label+'</div>'+['r','w','x'].map(function(p,j){var mask=p==='r'?4:p==='w'?2:1;return '<label class="perm-cell"><input type="checkbox" data-k="'+key+'" data-m="'+mask+'" '+(bits[key]&mask?'checked':'')+'>'+p.toUpperCase()+'</label>'}).join('')}
    var html='<div class="perm-grid">'+row('Owner',0)+row('Group',1)+row('Others',2)+'</div>'+
      '<div style="display:flex;align-items:center;gap:14px;margin-bottom:14px"><span class="octal-display" id="oct">'+bits.join('')+'</span><label style="display:flex;align-items:center;gap:6px;font-size:13px;font-weight:600"><input type="checkbox" id="recur"> Apply to all contents</label></div>'+
      '<div class="field"><label>Owner</label><select id="mf-owner">'+(idents.users||[]).map(function(u){return '<option '+(u===e.owner?'selected':'')+'>'+esc(u)+'</option>'}).join('')+'</select></div>'+
      '<div class="field"><label>Group</label><select id="mf-group">'+(idents.groups||[]).map(function(g){return '<option '+(g===e.group?'selected':'')+'>'+esc(g)+'</option>'}).join('')+'</select></div>';
    var m=modal({title:'Permissions · '+e.name,sub:'POSIX chmod and chown for '+e.path,html:html,cta:'Apply',
      onSubmit:async function(v,back){
        var bs=[0,0,0];$$('.perm-grid input',back).forEach(function(c){if(c.checked)bs[+c.getAttribute('data-k')]|=+c.getAttribute('data-m')});
        var oct=bs.join('');var rec=$('#recur',back).checked;
        var r1=await api('/api/files/chmod',{method:'POST',body:JSON.stringify({path:e.path,mode:oct,recursive:rec})});
        var owner=$('#mf-owner',back).value,group=$('#mf-group',back).value;
        var r2={ok:true};if(owner!==e.owner||group!==e.group){r2=await api('/api/files/chown',{method:'POST',body:JSON.stringify({path:e.path,owner:owner,group:group,recursive:rec})})}
        toast(r1.ok&&r2.ok?'Permissions updated':(r1.data&&r1.data.detail)||(r2.data&&r2.data.detail)||'Failed',r1.ok&&r2.ok?'ok':'err');
        if(r1.ok&&r2.ok)go(CWD);return r1.ok&&r2.ok}});
    // live octal preview
    $$('.perm-grid input',m.el).forEach(function(c){c.onchange=function(){var bs=[0,0,0];$$('.perm-grid input',m.el).forEach(function(x){if(x.checked)bs[+x.getAttribute('data-k')]|=+x.getAttribute('data-m')});$('#oct',m.el).textContent=bs.join('')}});
  }

  // ── preview ──
  function openPreview(e){
    var kind=previewKind(e);var t=token();var url='/api/files/raw?path='+encodeURIComponent(e.path)+(t?'&_t='+encodeURIComponent(t):'');
    var stage='';
    if(kind==='image')stage='<img src="'+esc(url)+'" alt="'+esc(e.name)+'">';
    else if(kind==='video')stage='<video src="'+esc(url)+'" controls></video>';
    else if(kind==='audio')stage='<audio src="'+esc(url)+'" controls></audio>';
    else if(kind==='text')stage='<pre id="pv-text">Loading…</pre>';
    else stage='<div class="none">No preview available. Use Download to retrieve this file.</div>';
    var meta='<div class="pv-meta"><span><b>Size</b> '+fmtBytes(e.size)+'</span><span><b>Modified</b> '+fmtTime(e.mtime)+'</span><span><b>Permissions</b> <code class="mode">'+esc(e.mode_str)+'</code></span><span><b>Owner</b> '+esc(e.owner)+':'+esc(e.group)+'</span></div>';
    var m=modal({title:e.name,big:true,html:meta+'<div class="pv-stage">'+stage+'</div>',cta:null});
    if(kind==='text'){fetch(url,{headers:t?{Authorization:'Bearer '+t}:{}}).then(function(r){return r.text()}).then(function(txt){
      var pre=$('#pv-text',m.el);if(pre)pre.textContent=txt.length>200000?txt.slice(0,200000)+'\n\n… (truncated)':txt})}
  }

  // ── upload (drag-drop + button) ──
  async function uploadFiles(files){
    if(!files||!files.length)return;
    var fd=new FormData();fd.append('path',CWD);
    for(var i=0;i<files.length;i++)fd.append('files',files[i]);
    var r=await api('/api/files/upload',{method:'POST',body:fd});
    toast(r.ok?'Uploaded '+(r.data&&r.data.saved&&r.data.saved.length||files.length)+' file(s)':(r.data&&r.data.detail)||'Upload failed',r.ok?'ok':'err');
    if(r.ok)go(CWD);
  }

  function wireDragDrop(){
    var dz=$('#dz'),main=$('.fs-main'),depth=0;
    ['dragenter','dragover'].forEach(function(ev){main.addEventListener(ev,function(e){e.preventDefault();e.dataTransfer.dropEffect='copy'})});
    main.addEventListener('dragenter',function(e){if(e.dataTransfer&&[...e.dataTransfer.types].indexOf('Files')>=0){depth++;dz.classList.add('show')}});
    main.addEventListener('dragleave',function(){depth--;if(depth<=0){depth=0;dz.classList.remove('show')}});
    main.addEventListener('drop',function(e){e.preventDefault();depth=0;dz.classList.remove('show');uploadFiles(e.dataTransfer.files)});
  }

  // ── wire ──
  document.addEventListener('DOMContentLoaded',function(){
    $('#refresh').onclick=function(){go(CWD);toast('Refreshed','info')};
    $('#btn-new').onclick=newFolder; $('#btn-rename').onclick=rename;
    $('#btn-cut').onclick=doCut; $('#btn-copy').onclick=doCopy; $('#btn-paste').onclick=doPaste;
    $('#btn-delete').onclick=delSel; $('#btn-perms').onclick=editPerms; $('#btn-download').onclick=download;
    $('#btn-upload').onclick=function(){$('#upload-input').click()};
    $('#upload-input').onchange=function(){uploadFiles(this.files);this.value=''};
    $('#ck-all').onchange=function(){if(this.checked){ENTRIES.forEach(function(e){SELECTED.add(e.path)})}else{SELECTED.clear()}refreshSel()};
    document.addEventListener('keydown',function(e){
      if(e.target&&e.target.matches&&e.target.matches('input,select,textarea'))return;
      if(e.key==='Delete'&&SELECTED.size)delSel();
      if((e.ctrlKey||e.metaKey)&&e.key==='x'){e.preventDefault();if(SELECTED.size)doCut()}
      if((e.ctrlKey||e.metaKey)&&e.key==='c'){e.preventDefault();if(SELECTED.size)doCopy()}
      if((e.ctrlKey||e.metaKey)&&e.key==='v'){e.preventDefault();doPaste()}
      if(e.key==='F2'&&SELECTED.size===1){e.preventDefault();rename()}
    });
    var tbl=document.querySelector('.files');
    if(tbl)tbl.addEventListener('contextmenu',function(ev){
      // only when the click is NOT on a row (rows handle their own menu)
      if(ev.target.closest('#rows tr'))return;
      ev.preventDefault();showContextMenu(ev.clientX,ev.clientY,true);
    });
    wireDragDrop();
    loadRoots();
  });
})();
