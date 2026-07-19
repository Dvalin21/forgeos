(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s)};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  function token(){try{return localStorage.getItem('forgeos_token')}catch(e){return null}}
  async function api(p,o){o=o||{};var h=Object.assign({},o.headers||{});var t=token();if(t)h.Authorization='Bearer '+t;
    if(o.body&&!h['Content-Type'])h['Content-Type']='application/json';
    try{var r=await fetch(p,Object.assign({},o,{headers:h}));var d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,data:null}}}
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
  function fmtBytes(b){b=Number(b)||0;if(b>=1e12)return (b/1e12).toFixed(1)+' TB';if(b>=1e9)return (b/1e9).toFixed(1)+' GB';if(b>=1e6)return (b/1e6).toFixed(0)+' MB';return b+' B'}
  function toast(m,k){k=k||'info';var b=$('#toasts'),e=document.createElement('div');e.className='toast '+k;e.textContent=m;b.appendChild(e);setTimeout(function(){e.style.transition='opacity .2s';e.style.opacity=0;setTimeout(function(){e.remove()},220)},4000)}

  function modal(o){
    var back=document.createElement('div');back.className='modal-back';
    var f=(o.fields||[]).map(function(x){
      if(x.type==='select'){var op=x.options.map(function(q){return '<option value="'+esc(q.value)+'">'+esc(q.label)+'</option>'}).join('');
        return '<div class="field"><label>'+esc(x.label)+'</label><select id="mf-'+x.id+'">'+op+'</select></div>'}
      return '<div class="field"><label>'+esc(x.label)+'</label><input id="mf-'+x.id+'" type="'+(x.type||'text')+'" placeholder="'+esc(x.ph||'')+'" value="'+esc(x.val||'')+'"></div>'}).join('');
    back.innerHTML='<div class="modal"><h3>'+esc(o.title)+'</h3><p class="sub">'+esc(o.sub||'')+'</p>'+(o.warn?'<div class="warn-box">'+esc(o.warn)+'</div>':'')+f+
      '<div class="row"><button class="btn-ghost" data-x>Cancel</button><button class="'+(o.danger?'btn-pri btn-danger':'btn-pri')+'" data-go>'+esc(o.cta||'Confirm')+'</button></div></div>';
    document.body.appendChild(back);var close=function(){back.remove()};
    back.addEventListener('click',function(e){if(e.target===back||e.target.hasAttribute('data-x'))close()});
    $('[data-go]',back).addEventListener('click',function(){var v={};(o.fields||[]).forEach(function(x){v[x.id]=($('#mf-'+x.id,back)||{}).value});
      Promise.resolve(o.onSubmit(v)).then(function(ok){if(ok!==false)close()})});
    var fi=back.querySelector('input,select');if(fi)fi.focus();
  }

  var POOLS=[];
  async function loadPools(){
    var p=(await api('/api/storage/pools')).data; var box=$('#pool-list');POOLS=(p&&p.pools)||[];
    if(POOLS.length){
      var worst='ok',ord={ok:0,predict:1,warn:2,rebuilding:2,err:3};
      POOLS.forEach(function(x){if((ord[x.health]||0)>(ord[worst]||0))worst=x.health});
      $('#array-chip').textContent=POOLS.length+' array'+(POOLS.length>1?'s':'')+' · '+(worst==='ok'?'Healthy':worst);
      box.innerHTML=POOLS.map(function(x){
        var lvl=(x.raid_level||'').toUpperCase().replace('RAID','RAID ');
        var rb=x.rebuild_pct!=null?'<div class="rebuild-bar"><i style="width:'+x.rebuild_pct+'%"></i></div><p style="margin:6px 0 0;color:var(--muted);font-size:12px">Rebuilding · '+x.rebuild_pct+'%</p>':'';
        var hc=x.health==='ok'?'ok':x.health==='err'?'err':'warn';
        var state=x.mounted?'mounted':'not mounted';
        return '<div class="volume"><div class="volume-head"><div><h4>'+esc(x.name)+' <span class="chip" style="font-size:10px">'+lvl+'</span></h4>'+
          '<p>'+(x.devices||[]).length+' drives · '+esc(state)+'</p></div>'+
          '<strong class="status '+hc+'">'+(x.health==='ok'?'Online':esc(x.health))+'</strong></div>'+rb+
          '<div class="pill-row"><button class="btn-ghost" data-rebuild="'+esc(x.name)+'" style="height:36px">Run consistency check</button>'+
          '<button class="btn-ghost" data-addd="'+esc(x.name)+'" style="height:36px">Add drive</button></div></div>'}).join('');
      $$('[data-rebuild]').forEach(function(b){b.onclick=function(){doRebuild(b.getAttribute('data-rebuild'))}});
      $$('[data-addd]').forEach(function(b){b.onclick=function(){doAddDrive(b.getAttribute('data-addd'))}});
    } else { $('#array-chip').textContent='No array'; box.innerHTML='<p style="color:var(--muted)">No storage pools yet. Use Create Pool to build a btrfs RAID pool.</p>'; }
  }

  async function loadCapacity(){
    var df=(await api('/api/storage/df')).data;var vl=$('#vols');var tot=0,used=0;
    if(Array.isArray(df)&&df.length){
      vl.innerHTML=df.map(function(v){tot+=v.total||0;used+=v.used||0;var pc=v.total?Math.round(v.used/v.total*100):0;
        var c=pc>=90?'danger':pc>=75?'warn':'good';
        return '<div class="volume"><div class="volume-head"><div><h4>'+esc(v.mount)+'</h4><p>btrfs · '+esc(v.source)+'</p></div><strong>'+fmtBytes(v.used)+' / '+fmtBytes(v.total)+'</strong></div><div class="bar '+c+'"><i style="width:'+pc+'%"></i></div></div>'}).join('');
    } else vl.innerHTML='<p style="color:var(--muted);font-size:13px">No btrfs volumes mounted.</p>';
    var pct=tot?Math.round(used/tot*100):0;$('#pct').textContent=pct+'%';$('#donut').style.setProperty('--pct',pct+'%');
  }

  // Three distinct, full drive icons — no cylinder, no emoji.
  function driveIcon(media){
    if(media==='nvme')  // M.2 stick: long board, connector notch, pin fingers
      return '<svg viewBox="0 0 24 24"><rect x="2.5" y="8.5" width="16" height="7" rx="1.2"/><rect x="18.5" y="9.8" width="3" height="4.4" rx="0.6"/><path d="M2.5 11h2M2.5 13h2"/><rect x="6" y="10.4" width="3.4" height="3.2" rx="0.5"/><rect x="10.2" y="10.4" width="3.4" height="3.2" rx="0.5"/></svg>';
    if(media==='ssd')   // flash chip: package body + pin rows + die grid
      return '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="1.6"/><path d="M8 3v2M12 3v2M16 3v2M8 19v2M12 19v2M16 19v2M3 8h2M3 12h2M3 16h2M19 8h2M19 12h2M19 16h2"/><rect x="9" y="9" width="6" height="6" rx="0.8"/></svg>';
    // HDD: platter + spindle hub + read/write head arm — a spinning disk
    return '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="11" cy="12" r="5.2"/><circle cx="11" cy="12" r="1.1" fill="currentColor" stroke="none"/><path d="M17.5 6.5l-4 5.2"/><circle cx="17.5" cy="6.5" r="0.9" fill="currentColor" stroke="none"/></svg>';
  }
  function mediaLabel(m){return m==='nvme'?'NVMe':m==='ssd'?'SSD':'HDD';}

  function driveCard(dr){
    var lvl=dr.health>=90?'ok':dr.health>=60?'warn':'err';
    var name=esc(dr.name.replace('/dev/',''));
    var temp=dr.temp?dr.temp+' °C':'—';var tcls=dr.temp>=55?'err':dr.temp>=45?'warn':'ok';
    var media=dr.media||'hdd';
    var roleBadge = dr.role==='os'
      ? '<span class="role-badge os">'+esc(dr.os_label||'Forge')+'</span>'
      : dr.role==='pool'
        ? '<span class="role-badge pool">'+esc(dr.pool)+'</span>'
        : '<span class="role-badge spare">Spare</span>';
    return '<div class="drive-card'+(lvl==='err'?' failed':'')+(dr.role==='os'?' is-os':'')+'">'+
      '<span class="dot '+lvl+'"></span>'+
      '<div class="drive-icon media-'+media+'">'+driveIcon(media)+'</div>'+
      '<div class="drive-top"><h4>'+name+'</h4>'+roleBadge+'</div>'+
      '<p class="model">'+esc(dr.model||'Unknown')+'</p>'+
      '<div class="drive-meta"><div class="cell"><span>Capacity</span><strong>'+esc(dr.size||'—')+'</strong></div>'+
      '<div class="cell"><span>Media</span><strong>'+mediaLabel(media)+'</strong></div>'+
      '<div class="cell"><span>Temp</span><strong class="lvl '+tcls+'" style="color:var(--'+(tcls==='ok'?'success':tcls==='warn'?'warn':'danger')+')">'+temp+'</strong></div>'+
      '<div class="cell"><span>Health</span><strong>'+dr.health+'%</strong></div></div>'+
      '<div class="drive-health"><div class="health-row"><span>SMART status</span><span class="lvl '+lvl+'">'+(lvl==='ok'?'Passed':lvl==='warn'?'Warning':'Failing')+'</span></div>'+
      '<div class="bar '+(lvl==='ok'?'good':lvl==='warn'?'warn':'danger')+'"><i style="width:'+dr.health+'%"></i></div></div>'+
      '<div class="drive-actions">'+
      '<button data-spin="'+esc(dr.name)+'" title="Spin down"><svg viewBox="0 0 24 24"><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="9"/></svg>Spin</button>'+
      '<button data-replace="'+esc(dr.name)+'" title="Replace"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4"/></svg>Replace</button>'+
      '<button class="danger" data-smart="'+esc(dr.name)+'" title="SMART detail"><svg viewBox="0 0 24 24"><path d="M12 9v4M12 17h0"/><circle cx="12" cy="12" r="9"/></svg>Info</button>'+
      '</div></div>';
  }

  async function loadDrives(){
    var d=(await api('/api/storage/drives')).data;var box=$('#drives');var drives=(d&&d.drives)||[];
    $('#drive-chip').textContent=drives.length+' drive'+(drives.length!==1?'s':'');
    if(!drives.length){box.innerHTML='<p style="color:var(--muted)">No drives detected.</p>';return}
    // Order: OS first, then pool members grouped by pool name, then spares.
    var rank={os:0,pool:1,spare:2};
    drives.sort(function(a,b){
      var ra=rank[a.role]||2,rb=rank[b.role]||2;
      if(ra!==rb)return ra-rb;
      if(a.role==='pool'&&b.role==='pool'&&a.pool!==b.pool)return a.pool.localeCompare(b.pool);
      return a.name.localeCompare(b.name);
    });
    // Render in labeled groups so the OS disk and each pool are visually distinct.
    var groups=[];var cur=null;
    drives.forEach(function(dr){
      var key=dr.role==='os'?'__os':dr.role==='pool'?('pool:'+dr.pool):'__spare';
      if(!cur||cur.key!==key){cur={key:key,role:dr.role,pool:dr.pool,items:[]};groups.push(cur)}
      cur.items.push(dr);
    });
    box.innerHTML=groups.map(function(g){
      var title=g.role==='os'?'Operating system':g.role==='pool'?('Pool · '+esc(g.pool)):'Unassigned';
      var sub=g.role==='os'?'Forge':g.role==='spare'?'not in a pool':'';
      var n=g.items.length;
      return '<div class="drive-group'+(g.role==='os'?' os-box':'')+'">'+
        '<div class="drive-group-head">'+title+
        (sub?' <span class="gcount">· '+sub+'</span>':'')+
        ' <span class="gcount">· '+n+' drive'+(n!==1?'s':'')+'</span></div>'+
        '<div class="drive-grid">'+g.items.map(driveCard).join('')+'</div></div>';
    }).join('');
    $$('[data-spin]').forEach(function(b){b.onclick=function(){doSpin(b.getAttribute('data-spin'))}});
    $$('[data-replace]').forEach(function(b){b.onclick=function(){doReplace(b.getAttribute('data-replace'))}});
    $$('[data-smart]').forEach(function(b){b.onclick=function(){doSmart(b.getAttribute('data-smart'))}});
  }

  // Storage activity terminal — reads the audit log filtered to storage.*
  var LOGVERB={'storage.pool.create':'created pool','storage.drive.add':'added drive',
    'storage.drive.replace':'replaced drive','storage.pool.rebuild':'started scrub',
    'storage.pool.scrub_done':'scrub finished',
    'storage.drive.spindown':'spun down drive','storage.drive.fail':'fail requested'};
  async function loadLog(){
    var r=(await api('/api/audit?prefix=storage.&limit=60')).data;var box=$('#storage-log');
    var entries=(r&&r.entries)||[];
    if(!entries.length){box.innerHTML='<div class="term-line muted">No storage activity recorded yet.</div>';return}
    box.innerHTML=entries.map(function(e){
      var t=e.timestamp?new Date((String(e.timestamp).length>12?e.timestamp:e.timestamp*1000)):null;
      var ts=t?t.toLocaleString([], {month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
      var verb=LOGVERB[e.action]||(e.action||'').replace('storage.','').replace(/[._]/g,' ');
      var ok=(e.status==='success');
      return '<div class="term-line"><span class="term-ts">'+esc(ts)+'</span>'+
        '<span class="term-st '+(ok?'ok':'err')+'">'+(ok?'OK':'ERR')+'</span>'+
        '<span class="term-who">'+esc(e.who||'system')+'</span>'+
        '<span class="term-msg">'+esc(verb)+(e.detail?' — '+esc(e.detail):'')+'</span></div>';
    }).join('');
  }

  // ── actions ──
  function poolOpts(){return POOLS.map(function(p){return{value:p.name,label:p.name+' ('+(p.level||'').toUpperCase()+')'}})}
  async function doSpin(dev){
    var r=await api('/api/storage/drive/spindown',{method:'POST',body:JSON.stringify({device:dev.replace('/dev/','')})});
    toast(r.ok?dev+' sent to standby':(r.data&&r.data.detail)||'Spin-down failed',r.ok?'ok':'err');
  }
  function doReplace(dev){
    modal({title:'Replace drive',sub:'Swap '+dev+' for a new disk. btrfs copies the data online — no downtime.',
      warn:'btrfs rebuilds redundancy onto the new drive while the pool stays online. If the old drive is already gone, enter its btrfs devid instead of a name.',
      danger:true,cta:'Start replacement',
      fields:[{id:'pool',label:'Array',type:'select',options:poolOpts()},
        {id:'new',label:'New drive (e.g. sdg)',ph:'sdg'}],
      onSubmit:async function(v){if(!v.new){toast('New drive required','warn');return false}
        var r=await api('/api/storage/drive/replace',{method:'POST',body:JSON.stringify({pool:v.pool,old:dev.replace('/dev/',''),new:v.new})});
        toast(r.ok?'Replacement started; rebuilding':(r.data&&r.data.detail)||'Replace failed',r.ok?'ok':'err');if(r.ok){loadPools();loadDrives()}return r.ok}});
  }
  async function doSmart(dev){
    var d=(await api('/api/storage/smart/'+dev.replace('/dev/',''))).data;
    modal({title:'SMART · '+dev,sub:'Raw smartctl output',fields:[],cta:'Close',onSubmit:function(){return true}});
    setTimeout(function(){var m=$('.modal');if(m&&d)m.insertAdjacentHTML('beforeend','<pre style="max-height:300px;overflow:auto;background:var(--surface-2);padding:12px;border-radius:12px;font:500 11px JetBrains Mono,monospace;white-space:pre-wrap">'+esc((d.output||'').slice(0,4000))+'</pre>')},30);
  }
  function doRebuild(pool){
    modal({title:'Consistency check',sub:'Run a btrfs scrub on '+pool+'. Reads every block and verifies checksums, repairing from the good copy. Safe online; uses disk I/O.',cta:'Start check',
      fields:[],onSubmit:async function(){var r=await api('/api/storage/pool/rebuild',{method:'POST',body:JSON.stringify({pool:pool})});
        toast(r.ok?'Scrub started — results will appear in the activity log':(r.data&&r.data.detail)||'Could not start',r.ok?'ok':'err');
        if(r.ok)pollScrub(pool);return r.ok}});
  }
  // poll scrub status until finished; each poll records completion to the log
  function pollScrub(pool,tries){
    tries=tries||0;
    if(tries>120)return;                     // ~10 min ceiling
    setTimeout(async function(){
      var r=(await api('/api/storage/scrub-status/'+encodeURIComponent(pool))).data;
      if(r&&r.status==='finished'){
        var ok=(r.errors||'').toLowerCase().indexOf('no errors')>=0;
        toast('Scrub of '+pool+' finished — '+(r.errors||'done'),ok?'ok':'warn');
        loadLog();                           // surface the recorded result
      } else { pollScrub(pool,tries+1); loadLog(); }
    },5000);
  }
  function doAddDrive(pool){
    modal({title:'Add drive to '+pool,sub:'Add a disk to grow this btrfs pool. Added online.',cta:'Add drive',
      fields:[{id:'device',label:'Drive (e.g. sdg)',ph:'sdg'}],
      onSubmit:async function(v){if(!v.device){toast('Drive required','warn');return false}
        var r=await api('/api/storage/drive',{method:'POST',body:JSON.stringify({pool:pool,device:v.device})});
        toast(r.ok?'Drive added':(r.data&&r.data.detail)||'Add failed',r.ok?'ok':'err');if(r.ok){loadPools();loadDrives()}return r.ok}});
  }
  function doNewPool(){
    modal({title:'Create storage pool',sub:'Build a new btrfs RAID pool from available drives.',cta:'Create pool',
      warn:'All data on the selected drives will be erased.',danger:true,
      fields:[{id:'name',label:'Pool name',ph:'main'},
        {id:'level',label:'RAID level',type:'select',options:[{value:'1',label:'RAID 1 — mirror (2 drives)'},{value:'5',label:'RAID 5 — single parity (3+)'},{value:'6',label:'RAID 6 — double parity (4+)'},{value:'10',label:'RAID 10 — striped mirror (4+)'},{value:'0',label:'RAID 0 — stripe, no redundancy'}]},
        {id:'drives',label:'Drives (comma-separated, e.g. sdb,sdc,sdd)',ph:'sdb,sdc,sdd'}],
      onSubmit:async function(v){var ds=(v.drives||'').split(',').map(function(s){return s.trim()}).filter(Boolean);
        if(!v.name||ds.length<2){toast('Name and 2+ drives required','warn');return false}
        var r=await api('/api/storage/pool',{method:'POST',body:JSON.stringify({name:v.name,level:parseInt(v.level,10),drives:ds})});
        toast(r.ok?'Pool created':(r.data&&r.data.detail)||'Create failed',r.ok?'ok':'err');if(r.ok){loadPools();loadDrives();loadCapacity()}return r.ok}});
  }

  function refresh(){loadPools();loadCapacity();loadDrives();loadLog()}
  document.addEventListener('DOMContentLoaded',function(){
    $('#refresh').onclick=function(){refresh();toast('Refreshed','info')};
    $('#new-pool').onclick=doNewPool;
    var lr=$('#log-refresh');if(lr)lr.onclick=function(){loadLog()};
    refresh();
  });
})();
