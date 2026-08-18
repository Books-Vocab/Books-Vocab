(function(root){
  "use strict";

  const LIMITS={
    reloadDelayMs:25,
    reloadMaxWaitMs:250,
    // The board payloads are intentionally rich: on the live felix instance
    // the three parallel snapshots take several seconds and can be multiple
    // megabytes. Keep the timeout as a hung-request guard, not a sub-second
    // latency target.
    eventBudgetMs:15000,
    loadDeadlineMs:15000,
    fallbackBaseDelayMs:1000,
    fallbackMaxDelayMs:5000,
    fallbackJitterMs:250,
    fallbackRequestBudgetMs:15000,
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
    let pendingRequest=false;
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
      const state={controller:new AbortController(),timer:null,promise:null};
      active=state;
      const budget=deadlineAt===null?LIMITS.loadDeadlineMs:Math.max(1,deadlineAt-now());
      state.timer=setTimer(()=>state.controller.abort(),budget);
      state.promise=Promise.resolve().then(()=>load({
        signal:state.controller.signal,
        deadlineAt,
        budget,
      })).finally(()=>{
        clearTimer(state.timer);
        if(active!==state)return;
        active=null;
        const shouldReload=pendingRequest;
        pendingRequest=false;
        if(shouldReload)enqueue(()=>report(requestLoad()));
      });
      return state.promise;
    }

    function requestLoad(deadlineAt=null){
      if(active){
        if(deadlineAt!==null)pendingRequest=true;
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
