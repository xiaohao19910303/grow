/* Course status is a projection; only source completion facts count as learned. */
(() => {
  'use strict';
  function key(module) { return module.kind === 'plan' ? 'plan:' + module.id : module.id; }
  function describe(module, activity) {
    const planned = module.curriculum?.lessons;
    const finite = module.kind === 'plan' && Array.isArray(planned) && planned.length > 0;
    const numbers = finite ? new Set(planned.map(l => l.number)) : null;
    const lessons = [...module.lessons].filter(l => !numbers || numbers.has(l.lesson_no)).sort((a,b) => a.lesson_no-b.lesson_no);
    const completed = lessons.filter(l => l.learning_state === 'completed');
    const total = finite ? planned.length : lessons.length;
    const finished = finite && completed.length === total;
    const inactive = ['paused','archived'].includes(module.status);
    const status = inactive ? module.status : finished ? 'completed' : completed.length || activity ? 'learning' : 'pending';
    const resume = lessons.find(l => l.lesson_no === activity?.lesson_no && l.learning_state !== 'completed');
    const next = resume || lessons.find(l => l.learning_state !== 'completed');
    const upcoming = finite ? planned.find(l => !completed.some(done => done.lesson_no === l.number)) : null;
    const stage = finite ? module.curriculum.stages[(planned.find(l => l.number === (next?.lesson_no || upcoming?.number))?.stage || 1)-1] : null;
    const last = lessons.find(l => l.lesson_no === activity?.lesson_no);
    return {module, key:key(module), lessons, finite, total, completed:completed.length, status, next, upcoming, last,
      percent:total ? Math.round(completed.length*100/total) : 0,
      caughtUp:!finished && lessons.length>0 && completed.length===lessons.length,
      stage:finished ? '全部阶段已完成' : stage?.title || (finite ? '待安排阶段' : '持续学习'),
      completedAt:completed.map(l => l.completed_at).filter(Boolean).sort().at(-1),
      goal:module.goal || module.brief?.goal || '',
      activity};
  }
  globalThis.CourseCatalog = {key, describe};
})();
