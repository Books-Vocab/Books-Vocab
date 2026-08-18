(function(root){
  "use strict";

  const LIMITS={
    reloadDelayMs:25,
    reloadMaxWaitMs:250,
    eventBudgetMs:900,
    loadDeadlineMs:650,
    fallbackBaseDelayMs:200,
    fallbackMaxDelayMs:700,
    fallbackJitterMs:50,
    fallbackRequestBudgetMs:200,
  };

  function createLiveRefreshController(options){
    const load=options.load;
    const onError=options.onError||(()=>{});
    const now=options.now||(()=>performance.now());
    const setTimer=options.setTimeout||((callback,delay)=>setTimeout(callback,delay));
    const clearTimer=options.clearTimeout||((timer)=>clearTimeout(timer));
    const random=options.random||(()=>Math.random());
    const enqueue=options.enqueue||((callback)=>queueMicrotask(callback));
    const locks=options.locks===undefined?root.navigator?.locks:options.locks;
    let active=null;
    let pendingDeadlineAt=null;
    let reloadTimer=null;
    let reloadMaxTimer=null;
    let reloadDeadlineAt=null;
    let fallbackTimer=null;
    let fallbackAttempts=0;
    let streamConnected=false;

    function report(promise){
      promise.catch(onError);
      return promise;
    }

    function startLoad(deadlineAt){
      const state={controller:new AbortController(),superseded:false,timer:null,promise:null};
      active=state;
      const budget=deadlineAt===null?LIMITS.loadDeadlineMs:Math.max(1,deadlineAt-now());
      state.timer=setTimer(()=>state.controller.abort(),budget);
      state.promise=Promise.resolve().then(()=>load({
        signal:state.controller.signal,
        deadlineAt,
        budget,
      })).catch(error=>{
        if(state.superseded&&error?.name==="AbortError")return;
        throw error;
      }).finally(()=>{
        clearTimer(state.timer);
        if(active!==state)return;
        active=null;
        const nextDeadlineAt=pendingDeadlineAt;
        pendingDeadlineAt=null;
        if(nextDeadlineAt!==null)enqueue(()=>report(requestLoad(nextDeadlineAt)));
      });
      return state.promise;
    }

    function requestLoad(deadlineAt=null){
      if(active){
        if(deadlineAt!==null){
          pendingDeadlineAt=deadlineAt;
          active.superseded=true;
          active.controller.abort();
        }
        return active.promise;
      }
      return startLoad(deadlineAt);
    }

    function flushLiveReload(){
      if(reloadTimer!==null){clearTimer(reloadTimer);reloadTimer=null}
      if(reloadMaxTimer!==null){clearTimer(reloadMaxTimer);reloadMaxTimer=null}
      const deadlineAt=reloadDeadlineAt;
      reloadDeadlineAt=null;
      return report(requestLoad(deadlineAt));
    }

    function scheduleLiveReload(){
      if(reloadTimer!==null)clearTimer(reloadTimer);
      reloadDeadlineAt=now()+LIMITS.eventBudgetMs;
      if(reloadMaxTimer===null)reloadMaxTimer=setTimer(flushLiveReload,LIMITS.reloadMaxWaitMs);
      reloadTimer=setTimer(flushLiveReload,LIMITS.reloadDelayMs);
    }

    async function runLiveFallbackLoad(){
      const request=async()=>{
        try{await requestLoad(now()+LIMITS.fallbackRequestBudgetMs)}catch(error){onError(error)}
      };
      if(locks?.request){
        await locks.request("kg-board-live-fallback",{ifAvailable:true},async lock=>{
          if(lock)await request();
        });
      }else await request();
      fallbackAttempts=Math.min(fallbackAttempts+1,2);
    }

    function scheduleLiveFallback(){
      if(fallbackTimer!==null)return;
      const exponential=Math.min(
        LIMITS.fallbackMaxDelayMs,
        LIMITS.fallbackBaseDelayMs*(2**Math.min(fallbackAttempts,2)),
      );
      const delay=exponential+Math.floor(random()*LIMITS.fallbackJitterMs);
      fallbackTimer=setTimer(async()=>{
        fallbackTimer=null;
        if(streamConnected)return;
        await runLiveFallbackLoad();
        scheduleLiveFallback();
      },delay);
    }

    function clearLiveFallback(){
      if(fallbackTimer===null)return;
      clearTimer(fallbackTimer);fallbackTimer=null;
    }

    function streamOpened(){
      streamConnected=true;
      fallbackAttempts=0;
      clearLiveFallback();
    }

    function streamErrored(){
      streamConnected=false;
      scheduleLiveFallback();
    }

    return {
      limits:{...LIMITS},
      loadInitial:()=>requestLoad(),
      scheduleLiveReload,
      flushLiveReload,
      scheduleLiveFallback,
      streamOpened,
      streamErrored,
      clearLiveFallback,
    };
  }

  root.KgBoardLiveRefresh={createLiveRefreshController,limits:{...LIMITS}};
  if(typeof module==="object"&&module.exports)module.exports=root.KgBoardLiveRefresh;
})(typeof window==="undefined"?globalThis:window);
