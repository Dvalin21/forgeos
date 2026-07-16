(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s)};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  function token(){try{return localStorage.getItem('forgeos_token')}catch(e){return null}}
  async function api(p,o){o=o||{};var h=Object.assign({},o.headers||{});var t=token();if(t)h.Authorization='Bearer '+t;
    if(o.body&&!h['Content-Type'])h['Content-Type']='application/json';
    try{var r=await fetch(p,Object.assign({},o,{headers:h}));var d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,data:null}}}
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
  function toast(m,k){k=k||'info';var b=$('#toasts'),e=document.createElement('div');e.className='toast '+k;e.textContent=m;b.appendChild(e);setTimeout(function(){e.style.transition='opacity .2s';e.style.opacity=0;setTimeout(function(){e.remove()},220)},4200)}

  // ── modal helper ──
  function modal(o){
    var back=document.createElement('div');back.className='modal-back';
    back.innerHTML='<div class="modal '+(o.size||'')+'"><h3>'+esc(o.title)+'</h3>'+(o.sub?'<p class="sub">'+esc(o.sub)+'</p>':'')+(o.warn?'<div class="warn-box">'+esc(o.warn)+'</div>':'')+(o.html||'')+
      '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">'+(o.cta===null?'<button class="btn-pri" data-x>Close</button>':'<button class="btn-ghost" data-x>Cancel</button><button class="'+(o.danger?'btn-pri btn-danger':'btn-pri')+'" data-go>'+esc(o.cta||'Save')+'</button>')+'</div></div>';
    document.body.appendChild(back);var close=function(){back.remove()};
    back.addEventListener('click',function(e){if(e.target===back||e.target.hasAttribute('data-x'))close()});
    if(o.onSubmit){$('[data-go]',back).addEventListener('click',function(){Promise.resolve(o.onSubmit(back)).then(function(ok){if(ok!==false)close()})})}
    return {el:back,close:close};
  }

  // ── helpers for repeating key/value pair lists ──
  function pairList(containerEl,initial,phK,phV){
    function add(k,v){
      var row=document.createElement('div');row.className='pair-row';
      row.innerHTML='<input placeholder="'+esc(phK)+'" value="'+esc(k||'')+'"><input placeholder="'+esc(phV)+'" value="'+esc(v||'')+'"><button type="button">×</button>';
      $('button',row).onclick=function(){row.remove()};
      containerEl.appendChild(row);
    }
    (initial||[]).forEach(function(p){add(p[0],p[1])});
    return {add:add,values:function(){return $$('.pair-row',containerEl).map(function(r){var i=$$('input',r);return [i[0].value.trim(),i[1].value.trim()]}).filter(function(p){return p[0]||p[1]})}};
  }
  function singleList(containerEl,initial,ph){
    function add(v){
      var row=document.createElement('div');row.className='pair-row';row.style.gridTemplateColumns='1fr auto';
      row.innerHTML='<input placeholder="'+esc(ph)+'" value="'+esc(v||'')+'"><button type="button">×</button>';
      $('button',row).onclick=function(){row.remove()};
      containerEl.appendChild(row);
    }
    (initial||[]).forEach(add);
    return {add:add,values:function(){return $$('.pair-row input',containerEl).map(function(i){return i.value.trim()}).filter(Boolean)}};
  }

  // ── catalog ──
  // vols are functions of the app-data root so "Default app folder" applies.
  // 30 curated, single-container apps. Image refs verified; per-app data
  // under the configurable app folder ({r}); icons vendored from
  // homarr-labs/dashboard-icons at /img/apps/{id}.png (emoji = fallback).
  var CATALOG=[
    // ── Media ──
    {id:'jellyfin',name:'Jellyfin',cat:'Media',icon:'🎬',desc:'Free media server for movies, TV, music.',image:'jellyfin/jellyfin:latest',ports:['8096:8096'],vols:function(r){return [r+'/jellyfin/config:/config',r+'/jellyfin/cache:/cache','/srv/nas:/media:ro']}},
    {id:'plex',name:'Plex',cat:'Media',icon:'▶',desc:'Personal media library with mobile/TV apps.',image:'plexinc/pms-docker:latest',ports:['32400:32400'],vols:function(r){return [r+'/plex:/config','/srv/nas:/media:ro']}},
    {id:'navidrome',name:'Navidrome',cat:'Media',icon:'🎵',desc:'Modern music server & streamer (Subsonic-compatible).',image:'deluan/navidrome:latest',ports:['4533:4533'],vols:function(r){return [r+'/navidrome:/data','/srv/nas/music:/music:ro']}},
    {id:'audiobookshelf',name:'Audiobookshelf',cat:'Media',icon:'🎧',desc:'Audiobook & podcast server with apps.',image:'ghcr.io/advplyr/audiobookshelf:latest',ports:['13378:80'],vols:function(r){return [r+'/audiobookshelf/config:/config',r+'/audiobookshelf/metadata:/metadata','/srv/nas/audiobooks:/audiobooks']}},
    {id:'photoprism',name:'PhotoPrism',cat:'Media',icon:'📷',desc:'AI-powered photo library. Set the admin password before first run.',image:'photoprism/photoprism:latest',ports:['2342:2342'],env:['PHOTOPRISM_ADMIN_PASSWORD=change-me-now'],vols:function(r){return [r+'/photoprism:/photoprism/storage','/srv/nas/photos:/photoprism/originals']}},
    // ── *arr / downloads ──
    {id:'sonarr',name:'Sonarr',cat:'Downloads',icon:'📺',desc:'TV series management and automation.',image:'lscr.io/linuxserver/sonarr:latest',ports:['8989:8989'],vols:function(r){return [r+'/sonarr:/config','/srv/nas:/data']}},
    {id:'radarr',name:'Radarr',cat:'Downloads',icon:'🎥',desc:'Movie collection management and automation.',image:'lscr.io/linuxserver/radarr:latest',ports:['7878:7878'],vols:function(r){return [r+'/radarr:/config','/srv/nas:/data']}},
    {id:'prowlarr',name:'Prowlarr',cat:'Downloads',icon:'🔎',desc:'Indexer manager for the *arr stack.',image:'lscr.io/linuxserver/prowlarr:latest',ports:['9696:9696'],vols:function(r){return [r+'/prowlarr:/config']}},
    {id:'qbittorrent',name:'qBittorrent',cat:'Downloads',icon:'⬇',desc:'BitTorrent client with web UI.',image:'lscr.io/linuxserver/qbittorrent:latest',ports:['8090:8080'],vols:function(r){return [r+'/qbittorrent:/config','/srv/nas/downloads:/downloads']}},
    {id:'jellyseerr',name:'Jellyseerr',cat:'Downloads',icon:'🍿',desc:'Media requests for Jellyfin/Plex users.',image:'fallenbagel/jellyseerr:latest',ports:['5055:5055'],vols:function(r){return [r+'/jellyseerr:/app/config']}},
    // ── Productivity ──
    {id:'nextcloud',name:'Nextcloud',cat:'Productivity',icon:'☁',desc:'Files, calendar, contacts, collaboration.',image:'nextcloud:latest',ports:['8080:80'],vols:function(r){return [r+'/nextcloud:/var/www/html']}},
    {id:'gitea',name:'Gitea',cat:'Productivity',icon:'🍵',desc:'Lightweight self-hosted Git service.',image:'gitea/gitea:latest',ports:['3003:3000'],vols:function(r){return [r+'/gitea:/data']}},
    {id:'n8n',name:'n8n',cat:'Productivity',icon:'🔗',desc:'Workflow automation (self-hosted Zapier).',image:'n8nio/n8n:latest',ports:['5678:5678'],vols:function(r){return [r+'/n8n:/home/node/.n8n']}},
    {id:'freshrss',name:'FreshRSS',cat:'Productivity',icon:'📰',desc:'Self-hosted RSS reader.',image:'freshrss/freshrss:latest',ports:['8083:80'],vols:function(r){return [r+'/freshrss:/var/www/FreshRSS/data']}},
    {id:'mealie',name:'Mealie',cat:'Productivity',icon:'🍲',desc:'Recipe manager and meal planner.',image:'ghcr.io/mealie-recipes/mealie:latest',ports:['9925:9000'],vols:function(r){return [r+'/mealie:/app/data']}},
    {id:'stirling-pdf',name:'Stirling PDF',cat:'Productivity',icon:'📄',desc:'Web-based PDF toolbox: merge, split, convert.',image:'stirlingtools/stirling-pdf:latest',ports:['8084:8080'],vols:function(r){return [r+'/stirling-pdf/configs:/configs',r+'/stirling-pdf/data:/usr/share/tessdata']}},
    {id:'code-server',name:'Code Server',cat:'Productivity',icon:'💻',desc:'VS Code in the browser on your NAS.',image:'codercom/code-server:latest',ports:['8443:8080'],vols:function(r){return [r+'/code-server:/home/coder']}},
    // ── Security & network ──
    {id:'vaultwarden',name:'Vaultwarden',cat:'Security',icon:'🔐',desc:'Bitwarden-compatible password manager.',image:'vaultwarden/server:latest',ports:['8200:80'],vols:function(r){return [r+'/vaultwarden:/data']}},
    {id:'adguardhome',name:'AdGuard Home',cat:'Network',icon:'🛡',desc:'Network-wide ad blocking. Add 53:53 in the wizard only if THIS box should serve DNS.',image:'adguard/adguardhome:latest',ports:['3000:3000'],vols:function(r){return [r+'/adguard/work:/opt/adguardhome/work',r+'/adguard/conf:/opt/adguardhome/conf']}},
    {id:'pihole',name:'Pi-hole',cat:'Network',icon:'🕳',desc:'DNS ad blocking. Add 53:53 in the wizard only if THIS box should serve DNS.',image:'pihole/pihole:latest',ports:['8181:80'],vols:function(r){return [r+'/pihole/etc:/etc/pihole']}},
    // ── Home & dashboards ──
    {id:'homeassistant',name:'Home Assistant',cat:'Automation',icon:'🏠',desc:'Open-source home automation.',image:'ghcr.io/home-assistant/home-assistant:stable',ports:['8123:8123'],vols:function(r){return [r+'/homeassistant:/config']}},
    {id:'homepage',name:'Homepage',cat:'Dashboards',icon:'🗂',desc:'Fast, static-feeling services dashboard.',image:'ghcr.io/gethomepage/homepage:latest',ports:['3004:3000'],vols:function(r){return [r+'/homepage:/app/config']}},
    {id:'homarr',name:'Homarr',cat:'Dashboards',icon:'🧭',desc:'Drag-and-drop dashboard for your services.',image:'ghcr.io/homarr-labs/homarr:latest',ports:['7575:7575'],vols:function(r){return [r+'/homarr:/appdata']}},
    // ── Files, sync, backup ──
    {id:'syncthing',name:'Syncthing',cat:'Sync',icon:'🔄',desc:'Continuous folder sync between devices.',image:'syncthing/syncthing:latest',ports:['8384:8384','22000:22000'],vols:function(r){return [r+'/syncthing:/var/syncthing']}},
    {id:'filebrowser',name:'File Browser',cat:'Files',icon:'📁',desc:'Web file manager over your NAS shares.',image:'filebrowser/filebrowser:latest',ports:['8082:80'],vols:function(r){return [r+'/filebrowser:/database','/srv/nas:/srv']}},
    {id:'duplicati',name:'Duplicati',cat:'Backup',icon:'💾',desc:'Encrypted backups to cloud or local targets.',image:'lscr.io/linuxserver/duplicati:latest',ports:['8201:8200'],vols:function(r){return [r+'/duplicati:/config','/srv/nas:/source:ro']}},
    // ── Monitoring & tools ──
    {id:'uptime-kuma',name:'Uptime Kuma',cat:'Monitoring',icon:'📈',desc:'Self-hosted uptime monitoring with alerts.',image:'louislam/uptime-kuma:1',ports:['3001:3001'],vols:function(r){return [r+'/uptime-kuma:/app/data']}},
    {id:'grafana',name:'Grafana',cat:'Monitoring',icon:'📊',desc:'Dashboards and metrics visualization.',image:'grafana/grafana:latest',ports:['3002:3000'],vols:function(r){return [r+'/grafana:/var/lib/grafana']}},
    {id:'dozzle',name:'Dozzle',cat:'Monitoring',icon:'🪵',desc:'Live container log viewer.',image:'amir20/dozzle:latest',ports:['8085:8080'],vols:function(r){return ['/var/run/docker.sock:/var/run/docker.sock:ro']}},
    {id:'portainer',name:'Portainer',cat:'Tools',icon:'⚓',desc:'Advanced container management UI.',image:'portainer/portainer-ce:latest',ports:['9443:9443'],vols:function(r){return [r+'/portainer:/data','/var/run/docker.sock:/var/run/docker.sock']}}
  ];



  var NATIVE_SERVICES=[
    {key:'nginx',name:'nginx',unit:'nginx',desc:'Web server and reverse proxy.',icon:'svc',configure:'nginx'},
    {key:'samba',name:'Samba (SMB shares)',unit:'smbd',desc:'Windows-compatible file sharing.',icon:'svc',configure:'samba'},
    {key:'forge-object-storage',name:'Forge Object Storage',unit:'forge-object-storage',desc:'S3-compatible object storage for buckets.',icon:'store',configure:'object-storage'},
    {key:'docker',name:'Docker engine',unit:'docker',desc:'Container runtime.',icon:'svc'},
    {key:'incus',name:'Container hypervisor',unit:'incus',desc:'System containers and lightweight VMs.',icon:'svc'},
    {key:'ssh',name:'SSH',unit:'ssh',desc:'Remote shell access. Configure in Security Center.',icon:'svc'},
    {key:'fail2ban',name:'Fail2ban',unit:'fail2ban',desc:'Bans IPs after failed logins.',icon:'svc'},
    {key:'smartd',name:'SMART monitoring',unit:'smartd',desc:'Drive SMART monitoring.',icon:'svc'}
  ];

  var STATE={containers:[],services:[],updateMap:{},appsRoot:'/srv/apps'};
  function recalc(){
    var svcUp=STATE.services.filter(function(s){return s.status==='running'}).length;
    var ctrUp=STATE.containers.filter(function(c){return c.running}).length;
    var upd=Object.values(STATE.updateMap).filter(function(x){return x===true}).length;
    $('#ov-svc').innerHTML=svcUp+' <small>/ '+STATE.services.length+'</small>';
    $('#ov-ctr').innerHTML=ctrUp+' <small>/ '+STATE.containers.length+'</small>';
    $('#ov-up').innerHTML=upd?upd+' <small>ready</small>':'<span style="color:var(--muted)">none</span>';
    $('#b-ctr').textContent=STATE.containers.length;$('#b-svc').textContent=STATE.services.length;
  }

  // ══════════ CATALOG ══════════
  function appIcon(id, fallback){
    // vendored logos at /img/apps/{id}.png (homarr-labs/dashboard-icons,
    // see img/apps/LICENSE.md); emoji fallback if a file is ever missing.
    return '<img src="/img/apps/'+esc(id)+'.png" alt="" loading="lazy" '+
      'style="width:30px;height:30px;object-fit:contain" '+
      'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'\'">'+
      '<span style="display:none">'+(fallback||'📦')+'</span>';
  }
  function renderCatalog(){
    var installed={};STATE.containers.forEach(function(c){if(c.fromCatalog)installed[c.fromCatalog]=c.name});
    $('#catalog-grid').innerHTML=CATALOG.map(function(a){
      var is=installed[a.id];
      return '<div class="card"><div class="card-head"><div class="card-icon" style="background:var(--surface-2);border:1px solid var(--line)">'+appIcon(a.id,a.icon)+'</div>'+
        '<div style="min-width:0"><h4>'+esc(a.name)+'</h4><p class="meta">'+esc(a.cat)+(a.compose?' · Compose':'')+'</p></div></div>'+
        '<p class="desc">'+esc(a.desc)+'</p>'+
        '<div class="badge-row"><span class="pill '+(is?'ok':'idle')+'">'+(is?'Installed':'Available')+'</span></div>'+
        '<div class="card-actions">'+
          (is?'<button class="danger" data-uninstall="'+esc(is)+'"><svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13"/></svg>Uninstall</button>':'<button data-install="'+esc(a.id)+'"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>Install</button>')+
        '</div></div>'}).join('');
    $$('[data-install]').forEach(function(b){b.onclick=function(){installApp(b.getAttribute('data-install'))}});
    $$('[data-uninstall]').forEach(function(b){b.onclick=function(){wipeContainer(b.getAttribute('data-uninstall'))}});
  }
  async function installApp(id){
    var a=CATALOG.filter(function(x){return x.id===id})[0];if(!a)return;
    // Ask the server for conflict-free host ports so defaults never collide
    // with ForgeOS services (80/443/445/5432…) or other containers.
    var ports=(a.ports||[]).slice();
    var want=ports.map(function(p){return p.split(':')[0]}).join(',');
    if(want){
      var f=await api('/api/docker/ports/free?ports='+encodeURIComponent(want));
      if(f.ok&&f.data&&f.data.ports){
        var moved=[];
        ports=ports.map(function(p){var seg=p.split(':'),got=f.data.ports[seg[0]];
          if(got&&String(got)!==seg[0]){moved.push(seg[0]+'→'+got);seg[0]=String(got)}return seg.join(':')});
        if(moved.length)toast('Port in use — moved '+moved.join(', '),'warn');
      }
    }
    var vols=typeof a.vols==='function'?a.vols(STATE.appsRoot):(a.vols||[]);
    containerWizard({name:a.id,image:a.image,restart:'unless-stopped',ports:ports,volumes:vols,env:a.env||[],labels:[['forgeos.catalog',id]]});
  }

  // ══════════ CONTAINER CREATE WIZARD ══════════
  function containerWizard(prefill){
    prefill=prefill||{};
    var html=
      '<div class="field"><label>Name</label><input id="cw-name" placeholder="my-container" value="'+esc(prefill.name||'')+'"></div>'+
      '<div class="field"><label>Image</label><input id="cw-image" placeholder="nginx:latest" value="'+esc(prefill.image||'')+'"></div>'+
      '<div class="field-row"><div class="field"><label>Restart policy</label><select id="cw-restart"><option value="unless-stopped">unless-stopped</option><option value="always">always</option><option value="on-failure">on-failure</option><option value="no">no</option></select></div>'+
      '<div class="field"><label>Working directory (optional)</label><input id="cw-workdir" placeholder="/app"></div></div>'+
      '<div class="field"><label>Ports (host:container, optional /udp)</label><div id="cw-ports" class="pair-list"></div><button class="add-pair" id="cw-add-port">+ Add port mapping</button></div>'+
      '<div class="field"><label>Volumes (host_path:container_path[:ro])</label><div id="cw-vols" class="pair-list"></div><button class="add-pair" id="cw-add-vol">+ Add volume</button></div>'+
      '<details class="adv"><summary><svg class="ico" viewBox="0 0 24 24" style="width:14px;height:14px"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/></svg>Advanced settings</summary><div class="body">'+
        '<div class="field"><label>Environment variables</label><div id="cw-env" class="pair-list"></div><button class="add-pair" id="cw-add-env">+ Add variable</button></div>'+
        '<div class="field"><label>Networks (one per row)</label><div id="cw-nets" class="pair-list"></div><button class="add-pair" id="cw-add-net">+ Add network</button></div>'+
        '<div class="field"><label>Labels</label><div id="cw-labels" class="pair-list"></div><button class="add-pair" id="cw-add-label">+ Add label</button></div>'+
        '<div class="field-row"><div class="field"><label>CPU limit (e.g. 1.5)</label><input id="cw-cpu" placeholder="2"></div>'+
        '<div class="field"><label>Memory limit (e.g. 512m, 2g)</label><input id="cw-mem" placeholder="1g"></div></div>'+
        '<div class="field"><label>Command override (space-separated)</label><input id="cw-cmd" placeholder="--config /etc/app.conf"></div>'+
        '<div class="field"><label>Entrypoint override</label><input id="cw-ep" placeholder="/usr/local/bin/start.sh"></div>'+
        '<div class="field"><label>Healthcheck command (optional)</label><input id="cw-hc" placeholder="curl -f http://localhost/health"></div>'+
        '<div class="field-row"><div class="field"><label>Health interval</label><input id="cw-hci" placeholder="30s"></div>'+
        '<div class="field"><label>Health retries</label><input id="cw-hcr" placeholder="3"></div></div>'+
      '</div></details>';
    var m=modal({title:'Create container',sub:'Basic fields up top, advanced settings collapsed below.',size:'big',html:html,cta:'Create',
      onSubmit:async function(back){
        var b={name:$('#cw-name',back).value.trim(),image:$('#cw-image',back).value.trim(),restart:$('#cw-restart',back).value,workdir:$('#cw-workdir',back).value.trim()||undefined,
          ports:plPorts.values().map(function(p){return p[0]+':'+p[1]+(p[2]?'/'+p[2]:'')}).filter(function(s){return s.length>1}),
          volumes:plVols.values().map(function(p){return p[0]+':'+p[1]+(p[2]?':'+p[2]:'')}).filter(function(s){return s.length>1}),
          env:plEnv.values().map(function(p){return p[0]+'='+p[1]}).filter(function(s){return s.length>1}),
          networks:plNets.values(),labels:{},
          cpu_limit:$('#cw-cpu',back).value.trim()||undefined,mem_limit:$('#cw-mem',back).value.trim()||undefined,
          command:$('#cw-cmd',back).value.trim()||undefined,entrypoint:$('#cw-ep',back).value.trim()||undefined};
        plLabels.values().forEach(function(p){b.labels[p[0]]=p[1]});
        var hcCmd=$('#cw-hc',back).value.trim();if(hcCmd)b.healthcheck={test:hcCmd,interval:$('#cw-hci',back).value.trim()||'30s',retries:parseInt($('#cw-hcr',back).value||'3',10)};
        if(!b.name||!b.image){toast('Name and image required','warn');return false}
        toast('Creating…','info');
        async function attempt(n){
          var r=await api('/api/docker/run',{method:'POST',body:JSON.stringify(b)});
          if(r.status===202&&n<240){if(!n)toast('Pulling image…','info');
            return new Promise(function(res){setTimeout(function(){res(attempt(n+1))},5000)})}
          toast(r.ok?b.name+' created':(r.data&&r.data.detail)||'Create failed',r.ok?'ok':'err');
          if(r.ok)refresh();return r.ok}
        return attempt(0)}});
    // Wire repeating lists. Ports use 3-field rows for host:container[/proto].
    function portList(el,initial){
      function add(host,ctr,proto){var row=document.createElement('div');row.className='pair-row';row.style.gridTemplateColumns='1fr 1fr 80px auto';
        row.innerHTML='<input placeholder="host port" value="'+esc(host||'')+'"><input placeholder="container port" value="'+esc(ctr||'')+'"><select><option value="">tcp</option><option value="udp" '+(proto==='udp'?'selected':'')+'>udp</option></select><button type="button">×</button>';
        $('button',row).onclick=function(){row.remove()};el.appendChild(row)}
      (initial||[]).forEach(function(s){var m=String(s).match(/^(\d+):(\d+)(?:\/(tcp|udp))?$/);if(m)add(m[1],m[2],m[3])});
      return {add:function(){add('','','')},values:function(){return $$('.pair-row',el).map(function(r){var i=$$('input',r),s=$('select',r);return [i[0].value.trim(),i[1].value.trim(),s.value]}).filter(function(p){return p[0]&&p[1]})}};
    }
    function volList(el,initial){
      function add(h,c,ro){var row=document.createElement('div');row.className='pair-row';row.style.gridTemplateColumns='1.2fr 1.2fr auto auto';
        row.innerHTML='<input placeholder="/host/path" value="'+esc(h||'')+'"><input placeholder="/container/path" value="'+esc(c||'')+'"><label class="checkbox-field" style="padding:0 10px;height:38px"><input type="checkbox" '+(ro?'checked':'')+'>RO</label><button type="button">×</button>';
        $('button[type=button]',row).onclick=function(){row.remove()};el.appendChild(row)}
      (initial||[]).forEach(function(s){var p=String(s).split(':');add(p[0],p[1],p[2]==='ro')});
      return {add:function(){add('','',false)},values:function(){return $$('.pair-row',el).map(function(r){var i=$$('input[placeholder]',r),c=$('input[type=checkbox]',r);return [i[0].value.trim(),i[1].value.trim(),c.checked?'ro':'']}).filter(function(p){return p[0]&&p[1]})}};
    }
    var plPorts=portList($('#cw-ports',m.el),prefill.ports);
    var plVols=volList($('#cw-vols',m.el),prefill.volumes);
    var plEnv=pairList($('#cw-env',m.el),(prefill.env||[]).map(function(e){var i=e.indexOf('=');return [e.slice(0,i),e.slice(i+1)]}),'KEY','value');
    var plNets=singleList($('#cw-nets',m.el),prefill.networks||[],'bridge / my-net');
    var plLabels=pairList($('#cw-labels',m.el),prefill.labels||[],'label','value');
    $('#cw-add-port',m.el).onclick=function(){plPorts.add()};
    $('#cw-add-vol',m.el).onclick=function(){plVols.add()};
    $('#cw-add-env',m.el).onclick=function(){plEnv.add('','')};
    $('#cw-add-net',m.el).onclick=function(){plNets.add('')};
    $('#cw-add-label',m.el).onclick=function(){plLabels.add('','')};
  }

  // ══════════ CONTAINERS LIST ══════════
  function renderContainers(){
    var box=$('#containers-grid');if(!STATE.containers.length){box.innerHTML='<div class="empty">No containers. Use <b>+ New container</b> or install from the Catalog.</div>';return}
    box.innerHTML=STATE.containers.map(function(c){
      var st=c.running?'ok':c.status==='exited'?'err':'idle',stText=c.running?'Running':(c.status||'Stopped');
      var upd=STATE.updateMap[c.name]===true;
      return '<div class="card" data-card-ctr="'+esc(c.name)+'">'+
        (upd?'<span class="pill update" data-update="'+esc(c.name)+'" title="Update available"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7-7 7 7"/></svg>Update</span>':'')+
        '<div class="card-head"><div class="card-icon" style="background:var(--surface-2);border:1px solid var(--line)">'+(c.fromCatalog?appIcon(c.fromCatalog,''):'<svg viewBox="0 0 24 24" style="width:22px;height:22px;stroke:var(--muted);fill:none;stroke-width:1.9"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h2M11 10h2M15 10h2"/></svg>')+'</div>'+
        '<div style="min-width:0"><h4>'+esc(c.name)+'</h4><p class="meta">'+esc(c.image||c.runtime||'container')+'</p></div></div>'+
        '<div class="badge-row"><span class="pill '+st+'">'+stText+'</span>'+(c.runtime?'<span class="pill idle">'+esc(c.runtime)+'</span>':'')+(c.composeProject?'<span class="pill idle">compose: '+esc(c.composeProject)+'</span>':'')+'</div>'+
        '<div class="card-actions">'+
          (c.running?'<button data-stop="'+esc(c.name)+'"><svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12"/></svg>Stop</button><button data-restart="'+esc(c.name)+'"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4"/></svg>Restart</button>':'<button data-start="'+esc(c.name)+'"><svg viewBox="0 0 24 24"><path d="M7 5l12 7-12 7z"/></svg>Start</button>')+
          '<button data-logs="'+esc(c.name)+'"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h12"/></svg>Logs</button>'+
          '<button data-update-one="'+esc(c.name)+'"'+(c.composeProject?' disabled title="Use compose to update"':'')+'><svg viewBox="0 0 24 24"><path d="M12 4v8M9 9l3-3 3 3M5 16a8 8 0 0 0 14 0"/></svg>Update</button>'+
          '<button data-term="'+esc(c.name)+'" title="Run a command inside the container"><svg viewBox="0 0 24 24"><path d="M4 17l6-5-6-5M12 19h8"/></svg>Terminal</button>'+
          '<button data-remove="'+esc(c.name)+'" title="Remove container only — image and volumes are kept"><svg viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>Remove</button>'+
          '<button class="danger" data-wipe="'+esc(c.name)+'" title="Remove container + image + anonymous volumes"><svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13"/></svg>Wipe</button>'+
        '</div></div>'}).join('');
    $$('[data-start]').forEach(function(b){b.onclick=function(){ctrAction(b.getAttribute('data-start'),'start')}});
    $$('[data-stop]').forEach(function(b){b.onclick=function(){ctrAction(b.getAttribute('data-stop'),'stop')}});
    $$('[data-restart]').forEach(function(b){b.onclick=function(){ctrAction(b.getAttribute('data-restart'),'restart')}});
    $$('[data-logs]').forEach(function(b){b.onclick=function(){showLogs(b.getAttribute('data-logs'))}});
    $$('[data-update-one]').forEach(function(b){b.onclick=function(){updateContainer(b.getAttribute('data-update-one'))}});
    $$('[data-update]').forEach(function(b){b.onclick=function(){updateContainer(b.getAttribute('data-update'))}});
    $$('[data-wipe]').forEach(function(b){b.onclick=function(){wipeContainer(b.getAttribute('data-wipe'))}});
    $$('[data-term]').forEach(function(b){b.onclick=function(){execModal(b.getAttribute('data-term'))}});
    $$('[data-remove]').forEach(function(b){b.onclick=function(){removeContainer(b.getAttribute('data-remove'))}});
  }
  async function ctrAction(name,act){var r=await api('/api/docker/containers/'+name+'/'+act,{method:'POST'});toast(r.ok?name+' '+act+'ed':(r.data&&r.data.detail)||(act+' failed'),r.ok?'ok':'err');if(r.ok)refresh()}
  async function showLogs(name){
    var d=(await api('/api/docker/containers/'+name+'/logs?tail=200')).data;
    var html='<pre style="background:var(--surface-3);padding:14px;border-radius:12px;font:500 11px JetBrains Mono,monospace;max-height:60vh;overflow:auto;white-space:pre-wrap;margin:0">'+esc((d&&d.logs||'(no logs)').slice(-15000))+'</pre>';
    modal({title:'Logs · '+name,sub:'Last 200 lines',size:'big',html:html,cta:null});
  }
  async function updateContainer(name,attempt){
    attempt=attempt||0;
    if(!attempt)toast('Updating '+name+'…','info');
    var r=await api('/api/docker/containers/'+encodeURIComponent(name)+'/update',{method:'POST'});
    if(r.status===202&&attempt<240){ // image pulling in background — poll
      if(!attempt)toast('Pulling image…','info');
      setTimeout(function(){updateContainer(name,attempt+1)},5000);return}
    if(r.data&&r.data.compose_managed){toast('Compose-managed: '+r.data.hint,'warn');return}
    toast(r.ok?((r.data&&r.data.updated===false)?name+' already up to date':name+' updated'):(r.data&&r.data.detail)||'Update failed',r.ok?'ok':'err');
    if(r.ok){delete STATE.updateMap[name];refresh()}
  }
  function wipeContainer(name){
    modal({title:'Wipe '+name,sub:'Removes the container, its image, and anonymous volumes.',
      warn:'Cannot be undone. Named volumes shared with other containers are preserved.',
      danger:true,cta:'Wipe permanently',
      onSubmit:async function(){var r=await api('/api/docker/wipe',{method:'POST',body:JSON.stringify({name:name})});
        toast(r.ok?name+' wiped':(r.data&&r.data.detail)||'Wipe failed',r.ok?'ok':'err');if(r.ok)refresh();return r.ok}});
  }
  function removeContainer(name){
    modal({title:'Remove '+name,sub:'Removes the container only.',
      warn:'The image and all volumes are kept — reinstalling or recreating brings it back with its data.',
      danger:true,cta:'Remove container',
      onSubmit:async function(){var r=await api('/api/docker/containers/'+encodeURIComponent(name)+'?force=true',{method:'DELETE'});
        toast(r.ok?name+' removed':(r.data&&r.data.detail)||'Remove failed',r.ok?'ok':'err');if(r.ok)refresh();return r.ok}});
  }
  function execModal(name){
    var html='<div class="fld"><label>Command (runs via sh -c inside '+esc(name)+')</label><input id="ex-cmd" class="wz-input" placeholder="ls -la /" autocomplete="off"></div>'+
      '<pre id="ex-out" style="background:var(--surface-3);padding:14px;border-radius:12px;font:500 11px JetBrains Mono,monospace;max-height:45vh;overflow:auto;white-space:pre-wrap;margin:10px 0 0;min-height:60px">(output)</pre>';
    var m=modal({title:'Terminal · '+name,sub:'One command at a time; output appears below.',html:html,cta:'Run',
      onSubmit:async function(back){
        var cmd=$('#ex-cmd',back).value.trim();if(!cmd){toast('Command required','warn');return false}
        var r=await api('/api/docker/containers/'+encodeURIComponent(name)+'/exec',{method:'POST',body:JSON.stringify({command:cmd})});
        var out=(r.data&&((r.data.stdout||'')+(r.data.stderr?'\n'+r.data.stderr:'')))||((r.data&&r.data.detail)||'exec failed');
        $('#ex-out',back).textContent=out||'(no output)';return false}}); // stay open for more commands
    $('#ex-cmd',m.el).focus();
  }
  var PRUNES={containers:{t:'Prune stopped containers',w:'Removes ALL stopped containers. Their images and volumes are kept.'},
    images:{t:'Prune unused images',w:'Removes images not used by any container.'},
    volumes:{t:'Prune unused volumes',w:'Removes volumes not attached to any container. This DELETES their data.'},
    networks:{t:'Prune unused networks',w:'Removes networks not used by any container.'},
    system:{t:'Prune system',w:'Stopped containers, unused images, networks and build cache — the big cleanup.'}};
  function pruneModal(kind){
    var p=PRUNES[kind];if(!p)return;
    modal({title:p.t,warn:p.w+' This cannot be undone.',danger:true,cta:'Prune',
      onSubmit:async function(){var r=await api('/api/docker/prune/'+kind,{method:'POST'});
        toast(r.ok?'Pruned':(r.data&&r.data.detail)||'Prune failed',r.ok?'ok':'err');if(r.ok)refresh();return r.ok}});
  }
  function appFolderModal(){
    var html='<div class="fld"><label>Default app data folder</label><input id="af-root" class="wz-input" value="'+esc(STATE.appsRoot)+'"></div>'+
      '<p class="sub" style="margin-top:8px">New catalog installs store their data under this folder ({folder}/{app}). Existing containers are not moved.</p>';
    modal({title:'Default app folder',html:html,cta:'Save',
      onSubmit:async function(back){
        var r=await api('/api/docker/settings',{method:'PUT',body:JSON.stringify({apps_root:$('#af-root',back).value.trim()})});
        toast(r.ok?'App folder updated':(r.data&&r.data.detail)||'Save failed',r.ok?'ok':'err');
        if(r.ok){STATE.appsRoot=r.data.apps_root;}return r.ok}});
  }
  async function checkAllUpdates(){
    toast('Checking for updates…','info');
    var d=(await api('/api/docker/update-check')).data;
    if(!d||!d.containers){toast('Update check failed','err');return}
    STATE.updateMap={};d.containers.forEach(function(c){STATE.updateMap[c.name]=c.update_available});
    var n=Object.values(STATE.updateMap).filter(function(x){return x===true}).length;
    toast(n?n+' update(s) available':'Everything up to date',n?'warn':'ok');recalc();renderContainers();
  }

  // ══════════ SERVICES TAB ══════════
  function renderServices(){
    var byKey={};STATE.services.forEach(function(s){byKey[s.name]=s});
    $('#services-grid').innerHTML=NATIVE_SERVICES.map(function(svc){
      var live=byKey[svc.unit]||byKey[svc.key]||{},on=live.status==='running';
      var ic=svc.icon==='store'?'ic-store':'ic-svc';
      return '<div class="card"><div class="card-head"><div class="card-icon '+ic+'"><svg viewBox="0 0 24 24"><path d="M5 5h14v14H5z"/><path d="M9 9h6v6H9z"/></svg></div>'+
        '<div style="min-width:0"><h4>'+esc(svc.name)+'</h4><p class="meta">'+esc(svc.unit)+'</p></div></div>'+
        '<p class="desc">'+esc(svc.desc)+'</p>'+
        '<div class="badge-row"><span class="pill '+(on?'ok':'idle')+'">'+(on?'Running':'Stopped')+'</span></div>'+
        '<div class="card-actions">'+
          (on?'<button data-svc-stop="'+esc(svc.unit)+'"><svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12"/></svg>Stop</button><button data-svc-restart="'+esc(svc.unit)+'"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4"/></svg>Restart</button>':'<button data-svc-start="'+esc(svc.unit)+'"><svg viewBox="0 0 24 24"><path d="M7 5l12 7-12 7z"/></svg>Start</button>')+
          (svc.configure?'<button data-svc-cfg="'+esc(svc.configure)+'"><svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/></svg>Configure</button>':'')+
        '</div></div>'}).join('');
    $$('[data-svc-start]').forEach(function(b){b.onclick=function(){svcAction(b.getAttribute('data-svc-start'),'start')}});
    $$('[data-svc-stop]').forEach(function(b){b.onclick=function(){svcAction(b.getAttribute('data-svc-stop'),'stop')}});
    $$('[data-svc-restart]').forEach(function(b){b.onclick=function(){svcAction(b.getAttribute('data-svc-restart'),'restart')}});
    $$('[data-svc-cfg]').forEach(function(b){b.onclick=function(){configureService(b.getAttribute('data-svc-cfg'))}});
  }
  async function svcAction(name,act){var r=await api('/api/service/'+act,{method:'POST',body:JSON.stringify({name:name})});toast(r.ok?name+' '+act+'ed':(r.data&&r.data.detail)||(act+' failed'),r.ok?'ok':'err');if(r.ok)refresh()}

  // ══════════ CONFIGURE — TIERED FORMS ══════════
  function configureService(kind){
    if(kind==='samba')return sambaWizard();
    if(kind==='nginx')return nginxOpen();
    if(kind==='object-storage')return forgeStoreOpen();
  }

  // — Samba (single tier — already minimal) —
  function sambaWizard(){
    modal({title:'Add Samba share',sub:'Path must exist on a pool.',html:
      '<div class="field"><label>Share name</label><input id="sb-name" placeholder="family-photos"></div>'+
      '<div class="field"><label>Folder on the NAS</label><input id="sb-path" placeholder="/srv/nas/main/Photos"></div>'+
      '<div class="field"><label>Template</label><select id="sb-type"><option value="standard">Standard (read/write)</option><option value="timemachine">Time Machine</option><option value="media">Media (read-only)</option><option value="private">Private (specific users)</option></select></div>'+
      '<label class="checkbox-field"><input type="checkbox" id="sb-w" checked>Allow writes from network</label>',cta:'Create',
      onSubmit:async function(back){var b={name:$('#sb-name',back).value.trim(),path:$('#sb-path',back).value.trim(),type:$('#sb-type',back).value,writable:$('#sb-w',back).checked};
        if(!b.name||!b.path){toast('Name and path required','warn');return false}
        var r=await api('/api/samba/share',{method:'POST',body:JSON.stringify(b)});toast(r.ok?'Share created':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');return r.ok}});
  }

  // — nginx tiered —
  async function nginxOpen(){
    var d=(await api('/api/nginx/sites')).data;var sites=(d&&d.sites)||[];
    var listHtml=sites.length?'<div style="display:grid;gap:6px;margin-bottom:14px">'+sites.map(function(s){return '<div style="display:flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--line);border-radius:11px;background:var(--surface-2)"><span style="flex:1;font-weight:700">'+esc(s.name)+'<span style="color:var(--muted);font-weight:600;font-size:11px;margin-left:8px">'+(s.server_names||[]).join(' ')+'</span></span><span class="pill '+(s.enabled?'ok':'idle')+'">'+(s.enabled?'Enabled':'Disabled')+'</span><button class="btn-ghost" data-edit="'+esc(s.name)+'" style="height:32px;padding:0 12px;font-size:12px">Edit</button><button class="btn-ghost" data-del="'+esc(s.name)+'" style="height:32px;padding:0 12px;font-size:12px;color:var(--danger);border-color:rgba(207,61,70,.3)">×</button></div>'}).join('')+'</div>':'<p style="color:var(--muted);font-size:13px;margin-bottom:14px">No sites configured.</p>';
    var m=modal({title:'nginx sites',sub:'Reverse proxies and virtual hosts. nginx -t runs before save.',size:'big',html:listHtml,cta:'New site',
      onSubmit:function(){m.close();nginxWizard();return false}});
    $$('[data-edit]',m.el).forEach(function(b){b.onclick=function(){m.close();nginxEdit(b.getAttribute('data-edit'))}});
    $$('[data-del]',m.el).forEach(function(b){b.onclick=function(){if(!confirm('Delete '+b.getAttribute('data-del')+'?'))return;api('/api/nginx/site/'+b.getAttribute('data-del'),{method:'DELETE'}).then(function(r){toast(r.ok?'Deleted':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');if(r.ok){m.close();nginxOpen()}})}});
  }
  function nginxWizard(initContent){
    var tier='simple';
    var html='<div class="wz-tier" id="nx-tier"><button class="active" data-tier="simple">Simple</button><button data-tier="standard">Standard</button><button data-tier="advanced" class="advanced">Advanced</button></div>'+
      '<div id="nx-simple">'+
        '<div class="field"><label>Site name (filename)</label><input id="nx-name" placeholder="photos"></div>'+
        '<div class="field"><label>Domain (what users type)</label><input id="nx-host" placeholder="photos.example.com"></div>'+
        '<div class="field"><label>Where to send the traffic</label><input id="nx-upstream" placeholder="http://127.0.0.1:2283"></div>'+
        '<label class="checkbox-field"><input type="checkbox" id="nx-ssl">Listen on HTTPS port 443 (add a cert later)</label>'+
      '</div>'+
      '<div id="nx-standard" class="hidden">'+
        '<div class="field-row"><div class="field"><label>Basic auth user</label><input id="nx-ba-user" placeholder="(leave empty for none)"></div><div class="field"><label>Basic auth password</label><input id="nx-ba-pass" type="password"></div></div>'+
        '<label class="checkbox-field" style="margin-bottom:10px"><input type="checkbox" id="nx-gzip" checked>Enable gzip compression</label>'+
        '<label class="checkbox-field" style="margin-bottom:10px"><input type="checkbox" id="nx-hsts">Add HSTS header (HTTPS only)</label>'+
        '<label class="checkbox-field"><input type="checkbox" id="nx-clientmax">Increase upload size to 500M</label>'+
      '</div>'+
      '<div id="nx-advanced" class="hidden">'+
        '<div class="warn-box">Advanced mode replaces the generated config with whatever you type here. nginx -t still runs before save.</div>'+
        '<div class="field"><label>Raw nginx configuration</label><textarea id="nx-raw" style="min-height:280px">'+esc(initContent||'server {\n  listen 80;\n  server_name example.com;\n  location / {\n    proxy_pass http://127.0.0.1:8080;\n    proxy_set_header Host $host;\n  }\n}\n')+'</textarea></div>'+
      '</div>'+
      '<label class="checkbox-field" style="margin-top:14px"><input type="checkbox" id="nx-enabled" checked>Enable this site immediately</label>';
    var m=modal({title:initContent?'Edit nginx site':'New nginx site',sub:'Pick a complexity level. Each tier builds on the one before it.',size:'big',html:html,cta:'Save',
      onSubmit:async function(back){
        var name=($('#nx-name',back)||{}).value||'';name=name.trim();
        var enabled=$('#nx-enabled',back).checked;
        var content;
        if(tier==='advanced'){content=$('#nx-raw',back).value;name=name||'site-'+Date.now()}
        else{
          var host=$('#nx-host',back).value.trim(),up=$('#nx-upstream',back).value.trim(),ssl=$('#nx-ssl',back).checked;
          if(!name||!host||!up){toast('Name, domain, and upstream required','warn');return false}
          var headers='    proxy_set_header Host $host;\n    proxy_set_header X-Real-IP $remote_addr;\n    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n    proxy_set_header X-Forwarded-Proto $scheme;\n';
          var extra='';
          if(tier==='standard'){
            var bu=$('#nx-ba-user',back).value.trim();var bp=$('#nx-ba-pass',back).value;
            if(bu&&bp){extra+='    auth_basic "Restricted";\n    auth_basic_user_file /etc/nginx/.htpasswd-'+name+';\n';
              toast('Note: also create the .htpasswd file manually with htpasswd -c','info')}
            if($('#nx-gzip',back).checked){extra+='    gzip on;\n    gzip_types text/plain application/json application/javascript text/css;\n'}
            if($('#nx-clientmax',back).checked){extra='    client_max_body_size 500M;\n'+extra}
            if($('#nx-hsts',back).checked&&ssl){extra+='    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n'}
          }
          content='server {\n  listen '+(ssl?'443 ssl':'80')+';\n  server_name '+host+';\n\n  location / {\n    proxy_pass '+up+';\n'+headers+extra+'  }\n}\n';
        }
        var r=await api('/api/nginx/site',{method:'POST',body:JSON.stringify({name:name,content:content,enabled:enabled})});
        toast(r.ok?name+' saved':(r.data&&r.data.detail)||'Save failed',r.ok?'ok':'err');return r.ok}});
    $$('#nx-tier button',m.el).forEach(function(b){b.onclick=function(){
      $$('#nx-tier button',m.el).forEach(function(x){x.classList.remove('active');if(b.classList.contains('advanced'))x.classList.remove('active')});
      b.classList.add('active');tier=b.getAttribute('data-tier');
      ['simple','standard','advanced'].forEach(function(t){$('#nx-'+t,m.el).classList.toggle('hidden',t!==tier)});
    }});
    if(initContent){tier='advanced';$$('#nx-tier button',m.el)[2].click()}
  }
  async function nginxEdit(name){var d=(await api('/api/nginx/site/'+name)).data;if(!d)return;nginxWizard(d.content)}

  // — Forge Object Storage tiered —
  function forgeStoreOpen(){
    var tier='simple';
    var html='<div class="wz-tier" id="fs-tier"><button class="active" data-tier="simple">Simple</button><button data-tier="standard">Standard</button><button data-tier="advanced" class="advanced">Advanced</button></div>'+
      '<div id="fs-simple">'+
        '<div class="field"><label>Data directory (where buckets live)</label><input id="fs-data" placeholder="/srv/nas/main/object-storage" value="/srv/nas/main/object-storage"></div>'+
        '<div class="field"><label>Admin access key</label><input id="fs-ak" placeholder="forgeadmin"></div>'+
        '<div class="field"><label>Admin secret key (16+ chars)</label><input id="fs-sk" type="password" placeholder="••••••••••••••••"></div>'+
      '</div>'+
      '<div id="fs-standard" class="hidden">'+
        '<div class="field-row"><div class="field"><label>S3 API port</label><input id="fs-port" value="9000"></div><div class="field"><label>Console port</label><input id="fs-console" value="9001"></div></div>'+
        '<div class="field"><label>Region (S3 region identifier)</label><input id="fs-region" value="us-east-1"></div>'+
        '<label class="checkbox-field" style="margin-bottom:10px"><input type="checkbox" id="fs-tls">Enable TLS (you must provide certs in /etc/forgeos/object-storage/certs)</label>'+
        '<label class="checkbox-field"><input type="checkbox" id="fs-versioning">Default versioning for new buckets</label>'+
      '</div>'+
      '<div id="fs-advanced" class="hidden">'+
        '<div class="warn-box">Direct config edit. Restart of the service is required after save.</div>'+
        '<div class="field"><label>config.yaml</label><textarea id="fs-raw" style="min-height:280px"># Forge Object Storage configuration\nendpoint: 0.0.0.0:9000\nconsole: 0.0.0.0:9001\ndata: /srv/nas/main/object-storage\nregion: us-east-1\ntls:\n  enabled: false\n</textarea></div>'+
      '</div>';
    var m=modal({title:'Forge Object Storage',sub:'S3-compatible buckets backed by ForgeRAID.',size:'big',html:html,cta:'Save & restart',
      onSubmit:async function(back){
        var body={};
        if(tier==='advanced')body={raw_config:$('#fs-raw',back).value};
        else{
          body={data:$('#fs-data',back).value.trim(),access_key:$('#fs-ak',back).value.trim(),secret_key:$('#fs-sk',back).value};
          if(!body.data||!body.access_key||!body.secret_key){toast('Data dir + admin keys required','warn');return false}
          if(body.secret_key.length<16){toast('Secret key must be 16+ chars','warn');return false}
          if(tier==='standard'){body.api_port=$('#fs-port',back).value||'9000';body.console_port=$('#fs-console',back).value||'9001';body.region=$('#fs-region',back).value||'us-east-1';body.tls=$('#fs-tls',back).checked;body.default_versioning=$('#fs-versioning',back).checked}
        }
        var r=await api('/api/service/forge-object-storage/config',{method:'POST',body:JSON.stringify(body)});
        toast(r.ok?'Saved; restarting…':(r.data&&r.data.detail)||'Failed',r.ok?'ok':'err');return r.ok}});
    $$('#fs-tier button',m.el).forEach(function(b){b.onclick=function(){$$('#fs-tier button',m.el).forEach(function(x){x.classList.remove('active')});b.classList.add('active');tier=b.getAttribute('data-tier');['simple','standard','advanced'].forEach(function(t){$('#fs-'+t,m.el).classList.toggle('hidden',t!==tier)})}});
  }

  // ══════════ TABS + REFRESH ══════════
  function switchTab(t){$$('.tab').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-t')===t)});['catalog','containers','services'].forEach(function(x){$('#tab-'+x).classList.toggle('hidden',x!==t)})}
  function switchSub(st){$$('.subtab').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-st')===st)});$('#sub-ctrs').classList.toggle('hidden',st!=='ctrs')}
  function parseLabels(raw){ // docker ps --format json emits Labels as "k=v,k=v"
    if(!raw)return{};if(typeof raw==='object')return raw;
    var o={};String(raw).split(',').forEach(function(kv){var i=kv.indexOf('=');if(i>0)o[kv.slice(0,i)]=kv.slice(i+1)});return o}
  async function refresh(){
    var [svc,docker,lxc,st]=await Promise.all([api('/api/services'),api('/api/docker/containers?all=true'),api('/api/lxc/containers'),api('/api/docker/settings')]);
    STATE.services=(svc.data&&svc.data.services)||[];
    STATE.appsRoot=(st.data&&st.data.apps_root)||'/srv/apps';
    var docks=((docker.data&&docker.data.containers)||[]).map(function(c){var labels=parseLabels(c.Labels||c.labels);return {name:(c.Names&&c.Names.replace(/^\//,''))||c.name,image:c.Image||c.image,running:(c.State||c.state||'').toLowerCase()==='running',status:c.Status||c.state,runtime:'docker',composeProject:labels['com.docker.compose.project'],fromCatalog:labels['forgeos.catalog']}});
    var incs=((lxc.data&&lxc.data.containers)||[]).map(function(c){return {name:c.name,image:c.image||c.type||'container',running:c.status==='Running',status:c.status,runtime:'container'}});
    STATE.containers=docks.concat(incs);
    recalc();renderCatalog();renderContainers();renderServices();
  }

  document.addEventListener('DOMContentLoaded',function(){
    $$('.tab').forEach(function(b){b.onclick=function(){switchTab(b.getAttribute('data-t'))}});
    $$('.subtab').forEach(function(b){b.onclick=function(){switchSub(b.getAttribute('data-st'))}});
    $('#refresh').onclick=function(){refresh();toast('Refreshed','info')};
    $('#check-updates').onclick=checkAllUpdates;
    $('#new-ctr').onclick=function(){containerWizard()};
    var af=$('#app-folder');if(af)af.onclick=appFolderModal;
    $$('[data-prune]').forEach(function(b){b.onclick=function(){pruneModal(b.getAttribute('data-prune'))}});
    refresh();
  });
})();
