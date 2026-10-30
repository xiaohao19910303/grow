/* Credentials live only in this form; canonical tokens stay in the server-side session. */
(() => {
  const box=document.getElementById('zookWebSettings');if(!box)return;
  function node(tag,text){const e=document.createElement(tag);if(text)e.textContent=text;return e;}
  window.Account.ready.then(async user=>{
    const response=await fetch('/api/auth/zook/status',{cache:'no-store'});if(!response.ok)return;
    const state=await response.json();if(!state.enabled)return;box.hidden=false;
    box.replaceChildren(node('h2','统一账号登录'));
    box.append(node('p',state.auth_mode==='zook'?'当前已使用LightTick账号登录，课程与记录仍按原授权范围接续。':state.linked?'身份已关联，可在登录页选择LightTick账号。':'先验证你自己的LightTick账号，再明确关联当前Grow空间。关联不会自动接管历史数据。'));
    if(state.linked)return;
    const form=node('form');form.className='github-fields';
    const account=node('input');account.required=true;account.maxLength=254;account.autocomplete='username';account.setAttribute('aria-label','LightTick账号');
    const password=node('input');password.type='password';password.required=true;password.maxLength=256;password.autocomplete='current-password';password.setAttribute('aria-label','LightTick密码');
    const accountLabel=node('label','LightTick账号（邮箱或手机号）');accountLabel.append(account);
    const passwordLabel=node('label','LightTick密码');passwordLabel.append(password);
    const consent=node('input');consent.type='checkbox';consent.required=true;
    const label=node('label');label.append(consent,document.createTextNode('我确认关联当前Grow账号 '+user.username+' 与上方LightTick账号，不自动迁移历史。'));
    const message=node('p');message.setAttribute('role','status');
    const save=node('button','验证并关联');save.className='btn primary';save.type='submit';form.append(accountLabel,passwordLabel,label,save,message);box.append(form);
    form.onsubmit=async event=>{
      event.preventDefault();if(save.disabled)return;save.disabled=true;account.disabled=password.disabled=consent.disabled=true;message.textContent='正在验证两个身份…';
      try{
        const result=await fetch('/api/auth/zook/link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:account.value.trim(),password:password.value,consent:consent.checked})});
        const data=await result.json();if(!result.ok)throw Error(data.message||'暂未关联，请核对账号。');
        password.value='';localStorage.setItem('grow-account-session',Date.now()+':'+Math.random());location.reload();
      }catch(error){message.textContent=error.message;save.disabled=false;account.disabled=password.disabled=consent.disabled=false;}
    };
  }).catch(()=>{});
})();
