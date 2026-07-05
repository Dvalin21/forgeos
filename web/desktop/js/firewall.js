(function(){
  "use strict";
  var $=function(s,r){return (r||document).querySelector(s)};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  function token(){try{return localStorage.getItem('forgeos_token')}catch(e){return null}}
  async function api(p,o){o=o||{};var h=Object.assign({},o.headers||{});var t=token();if(t)h.Authorization='Bearer '+t;
    if(o.body&&!h['Content-Type'])h['Content-Type']='application/json';
    try{var r=await fetch(p,Object.assign({},o,{headers:h}));var d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,data:null}}}
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
  function toast(m,k){k=k||'info';var b=$('#toasts'),e=document.createElement('div');e.className='toast '+k;e.textContent=m;b.appendChild(e);setTimeout(function(){e.style.transition='opacity .2s';e.style.opacity=0;setTimeout(function(){e.remove()},220)},4000)}

  var SERVICES=[];

  async function loadStatus(){
    var d=(await api('/api/firewall/status')).data;
    if(!d){toast('Could not read firewall status','err');return}
    var on=!!d.active;
    $('#shield').className='fw-shield '+(on?'on':'off');
    $('#toggle').className='big-toggle'+(on?' on':'');
    $('#fw-title').textContent='Firewall is '+(on?'on':'off');
    $('#fw-desc').textContent=on?'Protecting this NAS. '+(d.rules||[]).length+' active rule'+((d.rules||[]).length!==1?'s':'')+'.':'All connections are currently allowed. Turn it on to enforce rules.';
    // default policy segments
    var pol=d.defaults||{};
    setSeg('pol-in',pol.incoming);setSeg('pol-out',pol.outgoing);
    // rules
    var box=$('#rules');var rules=d.rules||[];
    $('#rule-chip').textContent=rules.length+' rule'+(rules.length!==1?'s':'');
    if(!rules.length){box.innerHTML='<p style="color:var(--muted)">No rules yet. Tap <b>Add Rule</b> to allow a service like file sharing or SSH.</p>';return}
    box.innerHTML=rules.map(function(r){
      var act=(r.action||'').toLowerCase().indexOf('allow')>=0?'allow':(r.action||'').toLowerCase().indexOf('reject')>=0?'reject':'deny';
      return '<div class="rule-row"><div class="rule-num">'+r.num+'</div>'+
        '<div><div class="rule-port">'+esc(r.to||'Anywhere')+'</div><div class="rule-from">from '+esc(r.from||'Anywhere')+'</div></div>'+
        '<span class="fam-tag">'+(r.family==='ipv6'?'IPv6':'IPv4')+'</span>'+
        '<span class="rule-act '+act+'">'+esc(r.action||act)+'</span>'+
        '<button class="rule-del" data-del="'+r.num+'" title="Delete rule"><svg class="ico" viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button></div>'}).join('');
    $$('[data-del]').forEach(function(b){b.onclick=function(){delRule(b.getAttribute('data-del'))}});
  }
  function setSeg(id,pol){$$('#'+id+' button').forEach(function(b){
    var sel=b.getAttribute('data-pol')===(pol||'').toLowerCase();
    b.className=sel?('sel '+b.getAttribute('data-pol')):'';})}

  async function loadServices(){var d=(await api('/api/firewall/services')).data;SERVICES=(d&&d.services)||[]}

  async function toggleFw(){
    var on=$('#toggle').classList.contains('on');
    var r=await api('/api/firewall/toggle',{method:'POST',body:JSON.stringify({enable:!on})});
    toast(r.ok?('Firewall '+(!on?'enabled':'disabled')):(r.data&&r.data.detail)||'Toggle failed',r.ok?'ok':'err');
    if(r.ok)loadStatus();
  }
  async function setPolicy(dir,pol){
    var b={};b[dir]=pol;var r=await api('/api/firewall/defaults',{method:'PUT',body:JSON.stringify(b)});
    toast(r.ok?('Default '+dir+' set to '+pol):(r.data&&r.data.detail)||'Policy failed',r.ok?'ok':'err');
    if(r.ok)loadStatus();
  }
  async function delRule(num){
    var r=await api('/api/firewall/rule/'+num,{method:'DELETE'});
    toast(r.ok?'Rule removed':(r.data&&r.data.detail)||'Delete failed',r.ok?'ok':'err');
    if(r.ok)loadStatus();
  }

  // ── caveman-simple rule builder ──
  function ruleWizard(){
    var sel={svc:null,action:'allow',from:'any',family:'both',port:''};
    var back=document.createElement('div');back.className='modal-back';
    back.innerHTML='<div class="modal"><h3>Add a firewall rule</h3><p class="sub">Three steps: pick what to allow, choose allow or block, say where from.</p>'+
      '<div class="wz-section"><div class="wz-label">1 · What service?</div><div class="svc-grid" id="svc"></div>'+
        '<input class="wz-input hidden" id="custom-port" placeholder="Custom port, e.g. 8096/tcp or 53" style="margin-top:10px"></div>'+
      '<div class="wz-section"><div class="wz-label">2 · Allow or block it?</div><div class="seg" id="act">'+
        '<button data-a="allow">Allow</button><button data-a="deny">Block</button></div></div>'+
      '<div class="wz-section"><div class="wz-label">3 · From where?</div><div class="wz-from">'+
        '<select class="wz-input" id="from-mode"><option value="any">Anywhere</option><option value="ip">Specific IP / range</option></select>'+
        '<input class="wz-input" id="from-ip" placeholder="192.168.1.0/24" disabled></div>'+
        '<div class="wz-label" style="margin-top:14px">IP version</div>'+
        '<div class="seg" id="fam"><button data-f="both">Both</button><button data-f="ipv4">IPv4 only</button><button data-f="ipv6">IPv6 only</button></div></div>'+
      '<div class="summary" id="summary">Pick a service to begin.</div>'+
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go disabled style="opacity:.5">Add rule</button></div></div>';
    document.body.appendChild(back);
    var go=$('[data-go]',back),sum=$('#summary',back);
    // services
    $('#svc',back).innerHTML=SERVICES.map(function(s){return '<div class="svc-opt" data-svc="'+esc(s.id)+'"><h5>'+esc(s.label)+'</h5><p>'+(s.port||'choose port')+'</p></div>'}).join('');
    $$('#svc .svc-opt',back).forEach(function(o){o.onclick=function(){
      $$('#svc .svc-opt',back).forEach(function(x){x.classList.remove('sel')});o.classList.add('sel');
      sel.svc=o.getAttribute('data-svc');
      var svc=SERVICES.filter(function(s){return s.id===sel.svc})[0];
      var cp=$('#custom-port',back);
      if(sel.svc==='custom'){cp.classList.remove('hidden');sel.port=cp.value;}
      else{cp.classList.add('hidden');sel.port=svc.port;}
      update();}});
    $('#custom-port',back).oninput=function(){sel.port=this.value;update()};
    // action
    $$('#act button',back).forEach(function(b){b.onclick=function(){sel.action=b.getAttribute('data-a');
      $$('#act button',back).forEach(function(x){x.className=''});b.className='sel '+(sel.action==='allow'?'allow':'deny');update()}});
    $$('#act button',back)[0].click();
    // from
    $('#from-mode',back).onchange=function(){var ip=$('#from-ip',back);if(this.value==='ip'){ip.disabled=false;ip.focus();sel.from=ip.value||'';}else{ip.disabled=true;sel.from='any';famLock(false);}update()};
    $('#from-ip',back).oninput=function(){sel.from=this.value;famAuto(this.value);update()};
    // family segment (default Both)
    function setFam(f){sel.family=f;$$('#fam button',back).forEach(function(x){x.className=x.getAttribute('data-f')===f?'sel allow':''})}
    $$('#fam button',back).forEach(function(b){b.onclick=function(){if(b.disabled)return;setFam(b.getAttribute('data-f'))}});
    setFam('both');
    function famLock(on){$$('#fam button',back).forEach(function(x){x.disabled=on;x.style.opacity=on?.45:1;x.style.cursor=on?'default':'pointer'})}
    function famAuto(addr){ // a specific address dictates its family
      if(!addr||addr.length<2){famLock(false);return}
      var f=addr.indexOf(':')>=0?'ipv6':'ipv4';setFam(f);famLock(true);
    }
    function update(){
      var ok=sel.svc&&sel.port&&/^\d{1,5}(:\d{1,5})?(\/(tcp|udp))?$/.test(sel.port)&&(sel.from==='any'||sel.from.length>2);
      go.disabled=!ok;go.style.opacity=ok?1:.5;
      if(!sel.svc){sum.innerHTML='Pick a service to begin.';return}
      var verb=sel.action==='allow'?'<b>Allow</b>':'<b>Block</b>';
      var src=sel.from==='any'?'any device':'<b>'+esc(sel.from)+'</b>';
      var fam=sel.family==='both'?'IPv4 &amp; IPv6':sel.family==='ipv6'?'IPv6 only':'IPv4 only';
      sum.innerHTML=verb+' connections to port <b>'+esc(sel.port||'?')+'</b> from '+src+' &middot; <b>'+fam+'</b>.';
    }
    var close=function(){back.remove()};
    back.addEventListener('click',function(e){if(e.target===back||e.target.hasAttribute('data-x'))close()});
    go.onclick=async function(){
      var r=await api('/api/firewall/rule',{method:'POST',body:JSON.stringify({action:sel.action,port:sel.port,from:sel.from,family:sel.family})});
      toast(r.ok?'Rule added':(r.data&&r.data.detail)||'Could not add rule',r.ok?'ok':'err');
      if(r.ok){close();loadStatus()}
    };
  }

  document.addEventListener('DOMContentLoaded',function(){
    $('#toggle').onclick=toggleFw;
    $('#add-rule').onclick=ruleWizard;
    $('#refresh').onclick=function(){loadStatus();toast('Refreshed','info')};
    $$('#pol-in button,#pol-out button').forEach(function(b){b.onclick=function(){setPolicy(b.getAttribute('data-dir'),b.getAttribute('data-pol'))}});
    loadServices().then(loadStatus);
  });
})();
