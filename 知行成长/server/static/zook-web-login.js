(() => {
  const button=document.getElementById('zookLoginTab');
  fetch('/api/auth/zook/config',{cache:'no-store'}).then(r=>r.json()).then(value=>{
    if(!value.enabled||!button)return;
    button.hidden=false;button.onclick=()=>window.GrowLogin.choose('zook');
  }).catch(()=>{});
})();
