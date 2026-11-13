// Only fixed data routes are public. Credentials never enter assets or responses.
import { createDataService } from './server/service.js';
import { createDemoService } from './server/demo.js';
import { createReadOnlyService, UPDATE_POLICY } from './server/read-only.js';
export function createGateway({ assets = typeof ASSETS === "undefined" ? {} : ASSETS, seed = typeof SEED === "undefined" ? undefined : SEED, service } = {}) {
  const data = service || (seed.demo ? createDemoService(seed) : createReadOnlyService(seed));
  const json = (value, status=200) => new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff','x-data-provider':value.provider||'FTShare'}});
  return {async fetch(request,env={},ctx={}){
    const url=new URL(request.url),path=url.pathname;
    if(request.method!=='GET'&&request.method!=='HEAD')return new Response('Method not allowed',{status:405});
    if(url.search.length>256)return new Response('Query too long',{status:414});
    try{
      if(path==='/api/board'){
        const response=json(data.seed());if(!seed.demo)response.headers.set('cache-control','public, max-age=60, s-maxage=60');return response;
      }
      if(path==='/api/live'){
        const edge=!seed.demo&&env.FTSHARE_CACHE?globalThis.caches?.default:null;
        const key=new Request(url.origin+'/__published-live/'+seed.built_at);
        if(edge){try{const hit=await edge.match(key);if(hit)return hit;}catch{}}
        const response=json(await data.live(env));
        if(!seed.demo)response.headers.set('cache-control','public, max-age=15, s-maxage=15');
        if(edge){const save=edge.put(key,response.clone()).catch(()=>{});if(ctx.waitUntil)ctx.waitUntil(save);else await save;}
        return response;
      }
      if(path==='/api/history')return json(await data.marketHistory(env));
      if(path==='/api/daily'){
        if(!seed.demo)return json({error:'日度数据由后台定时更新',code:'visitor_collection_disabled'},410);
        const b=url.searchParams.get('batch');if(!/^\d{1,2}$/.test(b||''))return json({error:'请选择有效的数据批次'},400);
        return json(await data.dailyBatch(Number(b),env));
      }
      if(path==='/api/cumulative')return json(await data.cumulativeDate(url.searchParams.get('date')||'',env));
      if(path==='/api/health')return json({provider:seed.provider,mode:seed.demo?'demo':'live',sources:seed.sources,configured:!seed.demo&&Boolean(env.FTSHARE_CACHE||seed.live_snapshot),history_built_at:seed.built_at,formula:seed.formula,flow_policy:seed.flow_policy,funds:seed.universe.length,cloud_update:seed.cloud_update||null,update_policy:UPDATE_POLICY});
      if(path==='/favicon.ico')return new Response(null,{status:204});
      const a=assets[path==='/'?'/index.html':path];if(!a)return new Response('Not found',{status:404});
      return new Response(request.method==='HEAD'?null:a.body,{headers:{'content-type':a.type,'cache-control':'no-cache','x-content-type-options':'nosniff','referrer-policy':'same-origin'}});
    }catch(error){
      if(error.message==='Invalid date'||error.message==='Invalid batch')return json({error:'查询参数无效'},400);
      if(error.code==='not_archived')return json({error:'该日期尚未归档',code:'not_archived'},404);
      if(error.code==='cache_not_ready')return json({error:'后台行情尚未就绪；历史图表可继续查看',code:'cache_not_ready'},503);
      return json({error:error.code==='not_configured'?'数据服务尚未配置':error.code==='quota_exceeded'?'FtShare调用额度暂不可用，稍后重试':error.code==='truncated'?'本次数据不完整，稍后重试':'FtShare数据暂不可用，请稍后刷新',code:error.code||'upstream_error'},503);
    }
  }};
}
export default typeof SEED === "undefined" ? null : createGateway();
