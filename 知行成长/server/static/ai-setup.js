/* Guide the existing browser-owned fields; never test or generate automatically. */
(() => {
  'use strict';
  const form=document.getElementById('apiSettingsForm');if(!form)return;
  const get=id=>document.getElementById(id);
  const groups=['apiBaseUrl','apiKey','modelName'].map(id=>get(id).closest('.field-row'));
  let step=null;
  function render(focus=false){
    const guided=step!==null;
    get('aiSetupHeader').hidden=!guided;get('aiSetupNavigation').hidden=!guided;
    groups.forEach((el,i)=>{el.hidden=guided&&(step===2||(step===0?i!==0:i===0));});
    get('aiCredentialsHelp').hidden=guided&&step!==1;
    get('aiSetupReview').hidden=!guided||step!==2;
    get('aiSaveActions').hidden=guided&&step!==2;get('aiTestHelp').hidden=guided&&step!==2;
    get('aiLocalActions').hidden=guided&&step!==2;
    if(!guided)return;
    get('aiSetupBack').hidden=step===0;get('aiSetupNext').hidden=step===2;
    get('aiSetupStep').textContent=`配置引导 ${step+1}/3 · ${['服务地址','密钥与模型','核对并保存'][step]}`;
    get('aiSetupHint').textContent=[
      '先准备服务商提供的 API 地址。已有内容无需配置即可阅读。',
      '填写自己的 API Key 和可用模型 ID。密钥不会显示在下一步核对摘要中。',
      '核对后可直接保存。也可以先手动测试连接；每次测试只验证当前填写的配置，不会自动保存或生成课程。'
    ][step];
    if(step===2){
      const value=window.AIConfig.validate(window.apiSettingsValue()),review=get('aiSetupReview');
      review.replaceChildren();
      for(const text of ['API 地址：'+value.api_base_url,'模型：'+value.model_name,'API Key：已填写（此处不显示）','保存范围：当前账号、当前浏览器。换浏览器或清除站点数据后需重新填写。']){
        const line=document.createElement('p');line.textContent=text;review.append(line);
      }
    }
    if(focus)get('aiSetupStep').focus();
  }
  function open(){
    if(get('view-settings')?.style.display==='none'&&window.goTab('settings')===false)return false;
    step=0;window.cancelApiTest();get('apiStatus').textContent='引导填写不会调用模型；配置会在点击保存后写入本浏览器。';render(true);
    form.scrollIntoView({block:'start'});return true;
  }
  function next(){
    try{
      if(step===0)window.AIConfig.address(get('apiBaseUrl').value);
      else window.AIConfig.validate(window.apiSettingsValue());
      step=Math.min(2,step+1);get('apiStatus').textContent='';render(true);
    }catch(error){get('apiStatus').textContent=error.message;(step===0?get('apiBaseUrl'):get('apiKey')).focus();}
  }
  function back(){step=Math.max(0,step-1);render(true);}
  function close(focus=true){step=null;render();if(focus)get('apiBaseUrl').focus();}
  function changed(){
    if(step===2){
      try{render();}catch{step=0;render();}
    }
  }
  function entry(parent){
    const button=document.createElement('button');button.type='button';button.className='btn';button.textContent='配置个人模型';button.onclick=open;
    if(parent.tagName==='UL'){const item=document.createElement('li');item.append(button);parent.append(item);}else parent.append(button);
    return button;
  }
  window.AISetup={open,next,back,close,changed,entry,saved:()=>close(false)};
})();
