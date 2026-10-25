/* A saved learning fact must be reflected by its dependent views immediately. */
(() => {
  let sourceWarning = '';
  async function refresh(result = {}) {
    sourceWarning = result.arrangement_sync_error || '';
    const outcomes = await Promise.allSettled([
      Promise.resolve().then(() => window.ActionPlans?.refresh()),
      Promise.resolve().then(() => window.refreshAutoCheckins?.())
    ]);
    const warning = sourceWarning || (outcomes.some(item => item.status === 'rejected' || item.value === false)
      ? '完成记录已保存，安排或学习足迹暂未刷新，请重试刷新状态。' : '');
    const status = document.getElementById('learningSyncStatus');
    if (status) {
      status.hidden = !warning;
      document.getElementById('learningSyncMessage').textContent = warning;
    }
    try{Promise.resolve(window.CoachFacts?.refresh(true)).catch(()=>{});}catch{}
    try{await window.DailyRhythm?.sourceSaved(result);}catch{}
    return warning;
  }
  window.refreshLearningCompletion = refresh;
  window.retryLearningCompletion = () => refresh({arrangement_sync_error: sourceWarning});
})();
