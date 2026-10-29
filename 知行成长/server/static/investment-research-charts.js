/* Display-only charts: calculation decisions and exact money remain on the server. */
(() => {
  'use strict';
  const ns='http://www.w3.org/2000/svg';
  const el=(tag,attributes={},text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attributes))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
  const color={up:'var(--error-text,#cf4a4a)',down:'var(--success-text,#21805c)',line:'var(--primary,#4f6ef7)',muted:'var(--muted,#777)',grid:'var(--border,#ddd)'};
  const label=(svg,x,y,text)=>svg.append(el('text',{x,y,fill:color.muted,'font-size':12},text));
  function svgFor(root,title,height=320){const svg=el('svg',{viewBox:`0 0 1000 ${height}`,role:'img','aria-label':title,preserveAspectRatio:'none'});root.replaceChildren(svg);return svg;}
  function path(svg,values,x,y,stroke){const points=values.map((v,i)=>v==null?'':`${x(i)},${y(v)}`).filter(Boolean);if(points.length)svg.append(el('polyline',{points:points.join(' '),fill:'none',stroke,'stroke-width':2,'vector-effect':'non-scaling-stroke'}));}
  function averages(values,n){let sum=0;return values.map((v,i)=>{sum+=v;if(i>=n)sum-=values[i-n];return i+1>=n?sum/n:null;});}
  function ema(values,n){let prior;const a=2/(n+1);return values.map(v=>prior=prior===undefined?v:a*v+(1-a)*prior);}
  function candles(root,bars,cursor,count,options,detail){
    const end=Math.max(1,Math.min(cursor,bars.length)),start=Math.max(0,end-count),visible=bars.slice(start,end);
    const svg=svgFor(root,'历史OHLC、成交量与技术指标回放',340);
    if(!visible.length){label(svg,20,30,'尚未载入行情');return;}
    const lo=Math.min(...visible.map(b=>Number(b.low))),hi=Math.max(...visible.map(b=>Number(b.high))),span=hi-lo||1;
    const x=i=>55+(i+.5)*920/visible.length,y=v=>22+(hi-v)/span*170;
    for(let i=0;i<4;i++){const at=22+i*170/3;svg.append(el('line',{x1:50,y1:at,x2:980,y2:at,stroke:color.grid}));label(svg,4,at+4,(hi-i*span/3).toFixed(2));}
    const width=Math.max(1,Math.min(12,650/visible.length)),maxVol=Math.max(1,...visible.map(b=>Number(b.volume_shares)));
    visible.forEach((b,i)=>{
      const open=Number(b.open),close=Number(b.close),stroke=close>=open?color.up:color.down,at=x(i);
      svg.append(el('line',{x1:at,y1:y(Number(b.high)),x2:at,y2:y(Number(b.low)),stroke}));
      svg.append(el('rect',{x:at-width/2,y:Math.min(y(open),y(close)),width,height:Math.max(1,Math.abs(y(close)-y(open))),fill:stroke}));
      if(options.volume)svg.append(el('rect',{x:at-width/2,y:245-Number(b.volume_shares)/maxVol*40,width,height:Number(b.volume_shares)/maxVol*40,fill:stroke,opacity:.55}));
    });
    for(const trade of options.trades||[]){
      const at=Date.parse(trade.time),i=visible.findIndex(b=>at>=Date.parse(b.open_at||b.time)&&at<=Date.parse(b.time));
      if(i<0)continue;
      const buy=trade.side==='buy',py=y(Number(trade.price));
      const group=el('g',{'data-trade-marker':trade.side,role:'img','aria-label':`${buy?'买入':'卖出'} ${trade.time} ${trade.price}`});
      group.append(el('circle',{cx:x(i),cy:py,r:5,fill:buy?color.up:color.down,stroke:'white'}));
      group.append(el('text',{x:x(i)+7,y:py+(buy?-9:15),fill:buy?color.up:color.down,'font-size':14},buy?'买':'卖'));
      group.append(el('title',{},`${trade.time} · ${buy?'买入':'卖出'} ${trade.quantity} · 价格 ${trade.price}`));svg.append(group);
    }
    const closes=bars.slice(0,end).map(b=>Number(b.close));
    if(options.ma)for(const [n,stroke] of [[5,'#c57824'],[10,'#397e99'],[20,'#8f69a1']])path(svg,averages(closes,n).slice(start),x,y,stroke);
    if(options.macd){
      const a=ema(closes,12),b=ema(closes,26),diff=a.map((v,i)=>v-b[i]),signal=ema(diff,9),hist=diff.map((v,i)=>2*(v-signal[i]));
      const scale=Math.max(.000001,...diff.slice(start).map(Math.abs),...signal.slice(start).map(Math.abs),...hist.slice(start).map(Math.abs)),my=v=>293-v/scale*32;
      svg.append(el('line',{x1:50,y1:293,x2:980,y2:293,stroke:color.grid}));
      hist.slice(start).forEach((v,i)=>svg.append(el('rect',{x:x(i)-width/2,y:Math.min(293,my(v)),width,height:Math.max(1,Math.abs(my(v)-293)),fill:v>=0?color.up:color.down,opacity:.5})));
      path(svg,diff.slice(start),x,my,'#c57824');path(svg,signal.slice(start),x,my,'#397e99');
    }
    label(svg,55,337,visible[0].time.replace('T',' ').slice(0,16));label(svg,760,337,visible.at(-1).time.replace('T',' ').slice(0,16));
    const vertical=el('line',{x1:0,y1:12,x2:0,y2:325,stroke:color.muted,'stroke-dasharray':'3 3',visibility:'hidden'});svg.append(vertical);
    svg.onpointermove=event=>{
      const box=svg.getBoundingClientRect(),position=(event.clientX-box.left)/box.width*1000;
      const i=Math.max(0,Math.min(visible.length-1,Math.floor((position-55)/920*visible.length)));
      vertical.setAttribute('x1',x(i));vertical.setAttribute('x2',x(i));vertical.setAttribute('visibility','visible');detail(visible[i]);
    };
    detail(visible.at(-1));return svg;
  }
  function curve(root,points,field,title,negative=false){
    const svg=svgFor(root,title,210);const values=points.map(p=>Number(p[field]));
    if(!values.length){label(svg,20,40,'没有可展示的曲线');return;}
    const low=Math.min(...values),high=Math.max(...values),span=high-low||1,x=i=>55+i*920/Math.max(1,values.length-1),y=v=>20+(high-v)/span*155;
    for(let n=0;n<3;n++){const v=high-n*span/2;svg.append(el('line',{x1:50,y1:y(v),x2:980,y2:y(v),stroke:color.grid}));label(svg,2,y(v)+4,v.toFixed(2));}
    path(svg,values,x,y,negative?color.down:color.line);label(svg,55,203,points[0].time.slice(0,10));label(svg,830,203,points.at(-1).time.slice(0,10));
    return svg;
  }
  window.InvestmentResearchCharts={candles,curve,averages,ema};
})();
