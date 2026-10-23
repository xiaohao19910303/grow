/* Participation and questionnaires are explicit and optional. */
(() => {
  async function open(client,drafts={}){const ui=window.DailyRhythm,{node,button,field,modal}=ui,data=await client.read('/trial'),d=modal('两周节奏试用');
    if(!ui.state()?.preferences.enabled){d.append(node('p','日常节奏已关闭，已有试用数据仍可导出。开启后可以继续填写问卷。'));button(d,'关闭',()=>d.close());return;}
    if(!data.enrollment){d.append(node('p','自愿观察两周行动节奏。关闭功能或不回访仍保留入组记录；问卷可以跳过。个人数据可自行导出，不会自动上传分析平台。'));
      button(d,'加入两周试用',async()=>{await client.write('enrollment','/enrollment',{experiment_key:'daily-rhythm-v1'});d.close();await open(client);},true);
    }else{const report=data.trial_report;d.append(node('p',`观察区间：${report.window_start} 至 ${report.window_end}`),node('p',report.mature?'14天观察窗已结束。':'观察中，尚未满14天。','desc'),node('p',`已行动 ${report.stats.action_days} 天，完整闭环 ${report.stats.loop_days} 天；总结 ${report.stats.recap_units} / ${report.stats.action_units} 个行动单位。`));
      const begin=new Date(data.enrollment.enrolled_at),zone=data.enrollment.timezone_snapshot,localDay=window.ActionPlanClient.day(new Date(),zone),first=window.ActionPlanClient.day(begin,zone),elapsed=Math.floor((new Date(localDay+'T12:00:00Z')-new Date(first+'T12:00:00Z'))/86400000)+1;
      for(const day of [7,14]){const existing=data.enrollment['day'+day+'_survey'];if(elapsed<day){d.append(node('p',`第${day}天问卷尚未到期。`,'desc'));continue;}
        const form=node('form');form.append(node('h3',`第${day}天：两道可选问题`));const clarity=field(form,'下一步是否更清楚（1至5分）',drafts[day]?.clarity_score??existing?.clarity_score??4,'number'),progress=field(form,'是否更有进展感（1至5分）',drafts[day]?.progress_score??existing?.progress_score??4,'number');for(const input of [clarity,progress]){input.min=1;input.max=5;input.required=true;}
        const error=node('p','','action-error');error.setAttribute('role','alert');form.append(error);const save=node('button',existing?'更新这次问卷':'保存这次问卷','btn');save.type='submit';form.append(save);d.append(form);
        form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await client.write('survey:'+day,'/survey',{experiment_key:'daily-rhythm-v1',day,clarity_score:Number(clarity.value),progress_score:Number(progress.value)});d.close();await open(client);}catch(e){error.textContent=e.message;ui.recoverPending(error,'survey:'+day,'/survey',async()=>{const draft={clarity_score:Number(clarity.value),progress_score:Number(progress.value)};d.close();await open(client,{[day]:draft});});}finally{save.disabled=false;}};}}
    button(d,'关闭',()=>d.close());}
  window.RhythmTrial={open};
})();
