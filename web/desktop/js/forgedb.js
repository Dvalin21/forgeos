(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s)};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  function token(){try{return localStorage.getItem('forgeos_token')}catch(e){return null}}
  async function api(p,o){o=o||{};var h=Object.assign({},o.headers||{});var t=token();if(t)h.Authorization='Bearer '+t;
    if(o.body&&!h['Content-Type'])h['Content-Type']='application/json';
    try{var r=await fetch(p,Object.assign({},o,{headers:h}));var d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,data:null}}}
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
  function fmtBytes(b){b=Number(b)||0;if(b>=1e9)return (b/1e9).toFixed(1)+' GB';if(b>=1e6)return (b/1e6).toFixed(1)+' MB';if(b>=1e3)return (b/1e3).toFixed(0)+' KB';return b+' B'}
  function fmtIso(s){if(!s)return '—';var d=new Date(s);return isNaN(d)?s:d.toLocaleString()}
  function fmtTs(ts){if(!ts)return '—';var m=String(ts).match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/);if(!m)return ts;return m[1]+'-'+m[2]+'-'+m[3]+' '+m[4]+':'+m[5]+':'+m[6]}
  function toast(m,k){k=k||'info';var b=$('#toasts'),e=document.createElement('div');e.className='toast '+k;e.textContent=m;b.appendChild(e);setTimeout(function(){e.style.transition='opacity .2s';e.style.opacity=0;setTimeout(function(){e.remove()},220)},4000)}

  function modal(o){
    var back=document.createElement('div');back.className='modal-back';
    back.innerHTML='<div class="modal '+(o.size||'')+'"><h3>'+esc(o.title)+'</h3>'+(o.sub?'<p class="sub">'+esc(o.sub)+'</p>':'')+(o.warn?'<div class="warn-box">'+esc(o.warn)+'</div>':'')+(o.html||'')+
      '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">'+(o.cta===null?'<button class="btn-pri" data-x>Close</button>':'<button class="btn-ghost" data-x>Cancel</button><button class="'+(o.danger?'btn-pri':'btn-pri')+'" data-go>'+esc(o.cta||'OK')+'</button>')+'</div></div>';
    document.body.appendChild(back);var close=function(){back.remove()};
    back.addEventListener('click',function(e){if(e.target===back||e.target.hasAttribute('data-x'))close()});
    if(o.onSubmit){$('[data-go]',back).addEventListener('click',function(){Promise.resolve(o.onSubmit(back)).then(function(ok){if(ok!==false)close()})})}
    return {el:back,close:close};
  }

  var STATE={status:null,clients:[],dbDirs:[],locks:{},snapshots:[],settings:null};

  // ── network sharing panel ──
  async function loadNetwork(){
    var d=(await api('/api/filedb/network')).data;if(!d)return;
    $('#net-smb').textContent=d.smb_url_pattern||'—';
    $('#net-smb-ip').textContent=d.smb_url_ip||'—';
    $('#net-port').textContent=d.edb_port||'—';
    $('#net-mdns').textContent=(d.mdns_service_types||[]).join(' · ');
    $('#net-hint').textContent=d.discovery_hint||'';
    var p=$('#mdns-pill');
    if(d.mdns_published){p.className='pill ok';p.textContent='Broadcasting on LAN'}
    else{p.className='pill warn';p.textContent='mDNS not published'}
  }
  function wireCopyBtns(){
    $$('[data-copy]').forEach(function(b){b.onclick=function(){
      var t=$('#'+b.getAttribute('data-copy')).textContent;
      navigator.clipboard&&navigator.clipboard.writeText(t).then(function(){toast('Copied','ok')},function(){toast('Copy failed','err')});
    }});
  }

  // ══════════ NEW DATABASE FLOWS ══════════
  function dbDirOptions(){
    var dirs=STATE.dbDirs.map(function(d){return d.dir});
    var watch=(STATE.settings&&STATE.settings.watch_root)||'/srv/nas';
    if(dirs.indexOf(watch)<0)dirs.unshift(watch);
    return dirs.map(function(d){return '<option value="'+esc(d)+'">'+esc(d)+'</option>'}).join('');
  }

  function newSqlite(){
    modal({title:'Create SQLite database',sub:'Real SQLite file. Optional initial schema runs through sqlite3 before save.',size:'big',html:
      '<div class="field"><label>Where</label><select id="sq-dir">'+dbDirOptions()+'</select></div>'+
      '<div class="field"><label>Filename</label><input id="sq-name" placeholder="ledger.db"></div>'+
      '<div class="field"><label>Initial schema (optional)</label><textarea id="sq-schema" placeholder="CREATE TABLE customers (\n  id INTEGER PRIMARY KEY,\n  name TEXT NOT NULL,\n  email TEXT UNIQUE\n);"></textarea></div>',
      cta:'Create',onSubmit:async function(back){
        var dir=$('#sq-dir',back).value,fn=$('#sq-name',back).value.trim(),sc=$('#sq-schema',back).value;
        if(!dir||!fn){toast('Directory and filename required','warn');return false}
        var r=await api('/api/filedb/sqlite/create',{method:'POST',body:JSON.stringify({dir:dir,filename:fn,schema:sc})});
        toast(r.ok?'SQLite database created':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');
        if(r.ok)refresh();return r.ok}});
  }

  function newDbase(){
    var rowHtml=function(){return '<tr><td><input placeholder="NAME"></td><td><select><option value="C">C — char</option><option value="N">N — number</option><option value="D">D — date</option><option value="L">L — yes/no</option></select></td><td><input type="number" placeholder="30" min="1" max="254"></td><td><input type="number" placeholder="0" min="0" value="0"></td><td><button type="button" class="del">×</button></td></tr>'};
    modal({title:'Create dBase database (.dbf)',sub:'Real dBase III file. Define the columns now; rows can be added by your app.',size:'huge',html:
      '<div class="field"><label>Where</label><select id="db-dir">'+dbDirOptions()+'</select></div>'+
      '<div class="field"><label>Filename</label><input id="db-name" placeholder="contacts.dbf"></div>'+
      '<label style="font-size:12px;font-weight:800;color:var(--muted);margin-bottom:6px;display:block">Columns</label>'+
      '<table class="schema-table"><thead><tr><th>Name (max 10, A–Z 0–9 _)</th><th>Type</th><th>Length</th><th>Decimals (N only)</th><th></th></tr></thead><tbody id="db-cols">'+rowHtml()+rowHtml()+'</tbody></table>'+
      '<button type="button" class="add-pair" id="db-add">+ Add column</button>',
      cta:'Create',onSubmit:async function(back){
        var cols=[];
        $$('#db-cols tr',back).forEach(function(tr){var i=$$('input,select',tr),n=i[0].value.trim();if(!n)return;
          var c={name:n,type:i[1].value,length:parseInt(i[2].value,10)||0,decimal:parseInt(i[3].value,10)||0};cols.push(c)});
        if(!cols.length){toast('At least one column required','warn');return false}
        var fn=$('#db-name',back).value.trim();if(!fn){toast('Filename required','warn');return false}
        var r=await api('/api/filedb/dbase/create',{method:'POST',body:JSON.stringify({dir:$('#db-dir',back).value,filename:fn,columns:cols})});
        toast(r.ok?'dBase database created':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');
        if(r.ok)refresh();return r.ok}});
    // wire add/remove
    setTimeout(function(){
      $('#db-add').onclick=function(){var tr=document.createElement('tr');tr.innerHTML=rowHtml().replace(/^<tr>|<\/tr>$/g,'');$('#db-cols').appendChild(tr);wireDel()};
      wireDel();
      function wireDel(){$$('.schema-table .del').forEach(function(b){b.onclick=function(){if($$('.schema-table tbody tr').length<=1){toast('At least one column required','warn');return}b.closest('tr').remove()}})}
      // Auto-set length when type changes (D=8 readonly, L=1 readonly)
      $$('#db-cols tr select').forEach(wireType);
      function wireType(s){s.addEventListener('change',function(){var tr=s.closest('tr'),inp=$$('input',tr);var t=s.value;
        if(t==='D'){inp[1].value=8;inp[1].disabled=true;inp[2].value=0;inp[2].disabled=true}
        else if(t==='L'){inp[1].value=1;inp[1].disabled=true;inp[2].value=0;inp[2].disabled=true}
        else{inp[1].disabled=false;inp[2].disabled=(t!=='N')}})}
    },20);
  }

  function prepareDir(){
    modal({title:'Prepare directory for app',sub:'Creates an empty, properly-permissioned folder. Point Atrex, ElevateDB, Access, NexusDB at it — the app creates its own DB files on first run.',html:
      '<div class="field"><label>Parent directory (under the watch root)</label><select id="pd-parent">'+dbDirOptions()+'</select></div>'+
      '<div class="field"><label>New folder name</label><input id="pd-name" placeholder="accounting"></div>'+
      '<div class="field-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><div class="field"><label>Owner (optional)</label><input id="pd-owner" placeholder="admin"></div>'+
      '<div class="field"><label>Group (optional)</label><input id="pd-group" placeholder="users"></div></div>'+
      '<div class="field"><label>Mode (POSIX octal)</label><input id="pd-mode" value="770"></div>',
      cta:'Create directory',onSubmit:async function(back){
        var name=$('#pd-name',back).value.trim();if(!name){toast('Name required','warn');return false}
        var r=await api('/api/filedb/dir/prepare',{method:'POST',body:JSON.stringify({parent:$('#pd-parent',back).value,name:name,owner:$('#pd-owner',back).value.trim(),group:$('#pd-group',back).value.trim(),mode:$('#pd-mode',back).value.trim()})});
        toast(r.ok?'Directory ready at '+(r.data&&r.data.path):(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');
        if(r.ok)refresh();return r.ok}});
  }

  function importDb(){
    modal({title:'Import existing database files',sub:'Upload .db, .edb, .dbf, .mdb, etc. into a tracked directory. Up to 200 MB per file in the UI; larger files belong over SMB.',size:'big',html:
      '<div class="field"><label>Target directory</label><select id="im-dir">'+dbDirOptions()+'</select></div>'+
      '<div class="field"><label>Files</label><input id="im-files" type="file" multiple style="height:auto;padding:14px"></div>'+
      '<p style="font-size:12px;color:var(--muted);margin:6px 0 0">After upload, ForgeDB rescans automatically.</p>',
      cta:'Upload',onSubmit:async function(back){
        var dir=$('#im-dir',back).value,files=$('#im-files',back).files;
        if(!dir||!files||!files.length){toast('Pick a directory and at least one file','warn');return false}
        var fd=new FormData();fd.append('path',dir);for(var i=0;i<files.length;i++)fd.append('files',files[i]);
        var t=token();var headers=t?{Authorization:'Bearer '+t}:{};
        var res=await fetch('/api/files/upload',{method:'POST',body:fd,headers:headers}).catch(function(){return null});
        if(!res||!res.ok){toast('Upload failed','err');return false}
        // Tell daemon to pick up the new files
        await api('/api/filedb/rescan',{method:'POST'});
        toast(files.length+' file(s) imported','ok');refresh();return true}});
  }

  function registerDir(){
    modal({title:'Register existing directory',sub:'Tell ForgeDB to start tracking a directory that already contains database files. Must be under the watch root.',html:
      '<div class="field"><label>Full path</label><input id="rg-path" placeholder="/srv/nas/main/legacy-app-data"></div>',
      cta:'Register',onSubmit:async function(back){
        var p=$('#rg-path',back).value.trim();if(!p){toast('Path required','warn');return false}
        var r=await api('/api/filedb/register',{method:'POST',body:JSON.stringify({dir:p})});
        toast(r.ok?'Registered ('+(r.data&&r.data.method)+')':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');
        if(r.ok)refresh();return r.ok}});
  }

  // ══════════ NEW-DB DROPDOWN ══════════
  function wireNewDbMenu(){
    var btn=$('#new-db'),menu=$('#new-db-menu');
    btn.onclick=function(e){e.stopPropagation();menu.classList.toggle('hidden')};
    document.addEventListener('click',function(e){if(!menu.contains(e.target)&&e.target!==btn)menu.classList.add('hidden')});
    $$('#new-db-menu button').forEach(function(b){b.onclick=function(){menu.classList.add('hidden');
      var k=b.getAttribute('data-newkind');
      if(k==='sqlite')newSqlite();else if(k==='dbase')newDbase();else if(k==='prepare')prepareDir();else if(k==='import')importDb();else if(k==='register')registerDir();
    }});
  }

  // ── status / hero ──
  async function loadStatus(){
    var s=(await api('/api/filedb/status')).data;STATE.status=s;
    if(!s){$('#hero-title').textContent='Daemon unreachable';$('#hero-sub').textContent='Could not contact the ForgeDB daemon.';$('#status-shield').className='hero-shield off';return}
    var on=!!s.daemon_running;
    $('#status-shield').className='hero-shield '+(on?'ok':'off');
    $('#hero-title').textContent=on?'ForgeDB is protecting your databases':'Daemon stopped';
    $('#hero-sub').textContent=on?'Watching for changes and snapshotting on writes.':'Start the forgefiledb service to resume protection.';
    $('#hero-uptime').textContent=s.uptime||'—';$('#hero-version').textContent=s.version||'—';
    $('#st-clients').textContent=s.connected_clients!=null?s.connected_clients:'—';
    $('#st-dbs').textContent=s.open_databases!=null?s.open_databases:'—';
    $('#st-snaps').textContent=s.snapshots_today!=null?s.snapshots_today:'—';
    var conflicts=s.total_conflicts!=null?s.total_conflicts:0;$('#st-conflicts').textContent=conflicts;
    var cf=$('#st-conflicts');cf.style.color=conflicts>0?'var(--danger)':'';
  }

  // ── databases tab ──
  async function loadDatabases(){
    var d=(await api('/api/filedb/databases')).data;STATE.dbDirs=(d&&d.databases)||[];
    $('#b-db').textContent=STATE.dbDirs.length;
    var box=$('#db-list');
    if(!STATE.dbDirs.length){box.innerHTML='<div class="empty">No databases detected yet. The daemon scans for files matching its database patterns under the watch root.</div>';$('#hero-watch').textContent=(STATE.settings&&STATE.settings.watch_root)||'—';return}
    $('#hero-watch').textContent=(STATE.settings&&STATE.settings.watch_root)||'—';
    box.innerHTML=STATE.dbDirs.map(function(dir){
      return '<div class="db-dir-card"><div class="db-dir-head">'+
        '<div class="ico-box dbdir"><svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></div>'+
        '<div class="path">'+esc(dir.dir)+'</div>'+
        '<button class="row-act" data-snap="'+esc(dir.dir)+'"><svg viewBox="0 0 24 24"><path d="M12 5v8l4 2"/><circle cx="12" cy="12" r="9"/></svg>Snapshot now</button>'+
        '<button class="row-act" data-snaps="'+esc(dir.dir)+'"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h12"/></svg>History</button>'+
        '</div>'+
        '<div class="db-files">'+(dir.files||[]).map(function(f){
          return '<div class="db-file"><div class="ico-box dbfile"><svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg></div>'+
            '<div style="min-width:0"><h5>'+esc(f.name)+'</h5><p>'+fmtBytes(f.size)+' · '+fmtIso(f.modified)+'</p></div></div>'}).join('')+'</div></div>'}).join('');
    $$('[data-snap]').forEach(function(b){b.onclick=function(){doSnapshot(b.getAttribute('data-snap'))}});
    $$('[data-snaps]').forEach(function(b){b.onclick=function(){showHistory(b.getAttribute('data-snaps'))}});
  }

  // ── clients tab ──
  async function loadClients(){
    var d=(await api('/api/filedb/clients')).data;STATE.clients=(d&&d.clients)||[];
    $('#b-cl').textContent=STATE.clients.length;
    var rows=$('#client-rows');
    if(!STATE.clients.length){rows.innerHTML='<tr><td colspan="4" class="empty">No active clients.</td></tr>';return}
    rows.innerHTML=STATE.clients.map(function(c){
      return '<tr><td><div class="name-cell"><div class="ico-box client"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3"/><path d="M5 21c0-4 3-7 7-7s7 3 7 7"/></svg></div><span class="mono" style="font-size:13px;color:var(--text);font-weight:700">'+esc(c.ip)+'</span></div></td>'+
        '<td>'+esc(c.user||'—')+'</td><td>'+(c.files_open||0)+'</td><td>'+fmtIso(c.connected_since)+'</td></tr>'}).join('');
  }

  // ── locks tab ──
  async function loadLocks(){
    var d=(await api('/api/filedb/locks')).data;STATE.locks=(d&&d.lock_details&&d.lock_details.files)||{};
    var keys=Object.keys(STATE.locks);
    $('#b-lk').textContent=keys.length;
    var rows=$('#lock-rows');
    if(!keys.length){rows.innerHTML='<tr><td colspan="4" class="empty">No file locks held right now.</td></tr>';return}
    var flat=[];keys.forEach(function(f){(STATE.locks[f].holders||[]).forEach(function(h){flat.push({file:f,mode:h.mode,client:h.client,since:h.since})})});
    rows.innerHTML=flat.map(function(l){
      var mode=(l.mode||'').toUpperCase();var cls=mode==='EXCLUSIVE'?'err':mode==='SHARED'?'warn':'idle';
      return '<tr><td><div class="name-cell"><div class="ico-box lock"><svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M7 11V8a5 5 0 0 1 10 0v3"/></svg></div><span class="mono" style="font-size:12px;color:var(--text);font-weight:700">'+esc(l.file)+'</span></div></td>'+
        '<td><span class="pill '+cls+'">'+esc(mode)+'</span></td><td class="mono">'+esc(l.client)+'</td><td>'+fmtIso(l.since)+'</td></tr>'}).join('');
  }

  // ── snapshots tab ──
  async function loadSnapshots(dbDir){
    var url='/api/filedb/snapshots'+(dbDir?'?db_dir='+encodeURIComponent(dbDir):'');
    var d=(await api(url)).data;STATE.snapshots=(d&&d.snapshots)||[];
    $('#b-sn').textContent=STATE.snapshots.length;
    var rows=$('#snap-rows');
    if(!STATE.snapshots.length){rows.innerHTML='<tr><td colspan="5" class="empty">No snapshots yet.</td></tr>';return}
    rows.innerHTML=STATE.snapshots.map(function(s){
      return '<tr><td><div class="name-cell"><div class="ico-box snap"><svg viewBox="0 0 24 24"><path d="M12 5v8l4 2"/><circle cx="12" cy="12" r="9"/></svg></div><span class="mono" style="font-size:13px;color:var(--text);font-weight:700">'+fmtTs(s.ts)+'</span></div></td>'+
        '<td class="mono">'+esc(s.db_dir)+'</td><td>'+esc(s.method||'—')+'</td><td>'+esc(s.reason||'—')+'</td>'+
        '<td><button class="row-act" data-restore=\''+esc(JSON.stringify({ts:s.ts,dir:s.db_dir}))+'\'><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4"/></svg>Restore</button></td></tr>'}).join('');
    $$('[data-restore]').forEach(function(b){b.onclick=function(){doRestore(JSON.parse(b.getAttribute('data-restore')))}});
  }

  function showHistory(dir){switchTab('snapshots');loadSnapshots(dir);toast('Showing snapshots for '+dir,'info')}

  // ── log tab ──
  async function loadLog(){
    var n=$('#log-lines').value||'100';
    var d=(await api('/api/filedb/log?lines='+n)).data;
    var lines=(d&&d.lines)||[];var box=$('#log-body');
    if(!lines.length){box.textContent='(log is empty)';return}
    box.innerHTML=lines.map(function(l){
      var m=l.match(/^\[([^\]]+)\]\s+(\w+)\s+(.*)$/);
      if(!m)return esc(l);
      var lv=m[2].toLowerCase(),cls='lv-'+lv;
      return '<span class="ts">['+esc(m[1])+']</span> <span class="'+cls+'">'+esc(m[2].padEnd(6))+'</span> '+esc(m[3])}).join('\n');
    box.scrollTop=box.scrollHeight;
  }

  // ── settings tab ──
  async function loadSettings(){
    var d=(await api('/api/filedb/settings')).data;STATE.settings=d||{};
    $('#set-debounce').value=d&&d.snapshot_debounce_sec||10;
    $('#set-max').value=d&&d.max_snapshots||24;
    $('#set-thresh').value=d&&d.write_threshold||100;
    $('#set-root').value=d&&d.watch_root||'';
    $('#hero-watch').textContent=(d&&d.watch_root)||'—';
  }
  async function saveSettings(){
    var body={snapshot_debounce_sec:parseInt($('#set-debounce').value,10),max_snapshots:parseInt($('#set-max').value,10),write_threshold:parseInt($('#set-thresh').value,10),watch_root:$('#set-root').value.trim()};
    if(!body.watch_root){toast('Watch root required','warn');return}
    var r=await api('/api/filedb/settings',{method:'PUT',body:JSON.stringify(body)});
    toast(r.ok?'Settings saved':(r.data&&r.data.detail)||'Save failed',r.ok?'ok':'err');if(r.ok)loadSettings();
  }

  // ── actions ──
  function doSnapshot(prefillDir){
    var options=STATE.dbDirs.map(function(d){return '<option value="'+esc(d.dir)+'"'+(d.dir===prefillDir?' selected':'')+'>'+esc(d.dir)+'</option>'}).join('');
    modal({title:'Create snapshot',sub:'Force a recovery point now (in addition to automatic ones).',html:
      '<div class="field"><label>Database directory</label><select id="snap-dir">'+(options||'<option value="">— no directories detected —</option>')+'</select></div>'+
      '<div class="field"><label>Reason (audit note)</label><input id="snap-reason" placeholder="manual checkpoint" value="manual"></div>',cta:'Create',
      onSubmit:async function(back){var db=$('#snap-dir',back).value,re=$('#snap-reason',back).value.trim()||'manual';
        if(!db){toast('Pick a directory','warn');return false}
        var r=await api('/api/filedb/snapshots',{method:'POST',body:JSON.stringify({db_dir:db,reason:re})});
        toast(r.ok?'Snapshot created':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');if(r.ok){loadStatus();loadSnapshots()}return r.ok}});
  }

  function doRestore(s){
    modal({title:'Restore snapshot',sub:'Restore '+fmtTs(s.ts)+' for '+s.dir,
      warn:'Restoring in place will overwrite the current database files. Choose a different target directory to restore alongside the original.',
      html:'<div class="field"><label>Restore target</label><select id="rs-mode"><option value="">In place (overwrite)</option><option value="alt">Restore to a different directory</option></select></div>'+
        '<div class="field hidden" id="rs-alt-wrap"><label>Target directory</label><input id="rs-alt" placeholder="/srv/nas/main/restored"></div>',cta:'Restore',
      onSubmit:async function(back){var alt=$('#rs-mode',back).value==='alt'?$('#rs-alt',back).value.trim():null;
        if($('#rs-mode',back).value==='alt'&&!alt){toast('Target directory required','warn');return false}
        var body={snap_ts:s.ts,db_dir:s.dir};if(alt)body.target_dir=alt;
        var r=await api('/api/filedb/restore',{method:'POST',body:JSON.stringify(body)});
        toast(r.ok?'Restored':(r.data&&r.data.detail)||'Restore failed',r.ok?'ok':'err');return r.ok}});
    setTimeout(function(){var m=$('#rs-mode');if(m)m.onchange=function(){$('#rs-alt-wrap').classList.toggle('hidden',this.value!=='alt')}},30);
  }

  // ── tabs + orchestration ──
  function switchTab(t){
    $$('.tab').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-t')===t)});
    ['databases','clients','locks','snapshots','log','settings'].forEach(function(x){$('#tab-'+x).classList.toggle('hidden',x!==t)});
    if(t==='clients')loadClients();
    else if(t==='locks')loadLocks();
    else if(t==='snapshots')loadSnapshots();
    else if(t==='log')loadLog();
    else if(t==='settings')loadSettings();
  }
  async function refresh(){await loadStatus();await loadSettings();await loadDatabases();await loadNetwork();wireCopyBtns();loadClients();loadLocks();loadSnapshots()}

  document.addEventListener('DOMContentLoaded',function(){
    $$('.tab').forEach(function(b){b.onclick=function(){switchTab(b.getAttribute('data-t'))}});
    $('#refresh').onclick=function(){refresh();toast('Refreshed','info')};
    $('#new-snap').onclick=function(){doSnapshot()};
    $('#log-lines').onchange=loadLog;
    $('#save-settings').onclick=saveSettings;
    wireNewDbMenu();
    refresh();
    setInterval(function(){loadStatus();loadClients();loadLocks()},10000);
  });
  window.switchTab=switchTab;
})();
