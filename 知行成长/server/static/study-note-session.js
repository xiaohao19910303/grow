/* Private draft state. Saving here never changes a course's completion state. */
(() => {
  const same = (a, b) => !!b && a.notes === b.notes && a.version === b.version &&
    JSON.stringify(Object.entries(a.answers).sort()) === JSON.stringify(Object.entries(b.answers || {}).sort());
  class StudyDraftSession {
    constructor(options) {
      Object.assign(this, options);
      this.url = '/api/study-notes/' + this.kind + '/' + this.course.split('/').map(encodeURIComponent).join('/');
      this.storageKey = 'course-study-notes:' + this.userId + ':' + this.kind + ':' + this.course;
      this.notes = options.seedNotes || ''; this.answers = {}; this.revision = 0;
      this.dirty = false; this.localSaved = true; this.pending = null;
      this.loaded = false; this.conflict = false;
      try {
        const value = JSON.parse(this.storage?.getItem(this.storageKey) || 'null');
        if (value && typeof value.notes === 'string' && value.answers && typeof value.answers === 'object') {
          this.notes = value.notes; this.answers = value.answers; this.revision = value.revision || 0;
          this.dirty = !!value.dirty; this.pending = value.pending || null;
          this.changedVersion = value.version !== this.version;
        }
      } catch (_) { /* The server remains available when browser storage is blocked. */ }
    }
    snapshot() { return {notes: this.notes, answers: {...this.answers}, version: this.version}; }
    get safe() { return !this.dirty || this.localSaved; }
    status(message) { this.onStatus?.(message); }
    persist() {
      try {
        if (!this.storage) throw Error('storage unavailable');
        this.storage.setItem(this.storageKey, JSON.stringify({...this.snapshot(), revision: this.revision, dirty: this.dirty, pending: this.pending}));
        this.localSaved = true;
      } catch (_) { this.localSaved = false; }
    }
    changed() {
      this.dirty = true; this.persist();
      this.status(this.localSaved ? '已在本机暂存，正在等待同步；不会标记学完。' : '本机暂存不可用，请保存到云端后再离开。');
    }
    setNotes(value) { this.notes = value; this.changed(); }
    setAnswer(key, value) { this.answers = {...this.answers, [key]: value}; this.changed(); }
    load() {
      if (this.loading) return this.loading;
      this.loading = this.read().finally(() => { this.loading = null; });
      return this.loading;
    }
    async read() {
      try {
        const response = await this.fetch(this.url);
        if (!response.ok) throw Error('暂存读取失败');
        const cloud = await response.json();
        if (cloud && (typeof cloud.notes !== 'string' || !cloud.answers || typeof cloud.answers !== 'object' || !Number.isInteger(cloud.revision))) throw Error('暂存格式无效');
        this.remote = cloud; this.conflict = false; this.hasCloud = !!cloud;
        const revision = cloud?.revision || 0;
        if (this.dirty) {
          if (this.pending && revision === this.pending.revision + 1 && same(this.pending, cloud)) {
            // The previous save succeeded even though its response was lost.
            this.pending = null; this.revision = revision; this.dirty = !same(this.snapshot(), cloud);
          } else if (revision !== this.revision) {
            this.conflict = true;
          }
        } else if (cloud) {
          this.changedVersion ||= cloud.version !== this.version;
          this.notes = cloud.notes; this.answers = cloud.answers; this.revision = revision;
        }
        this.loaded = true; this.persist(); this.onChange?.(this.snapshot());
        this.status(this.conflict ? '云端已被其他页面更新，当前输入仍保留在本机。请核对后重新打开课程。' :
          this.changedVersion ? '课程内容已更新，原笔记与答案已恢复，请核对后暂存。' :
          this.dirty ? '已恢复本机暂存，尚未同步；不会标记学完。' : cloud ? '已恢复云端暂存；保存笔记不会改变完成状态。' : '笔记和练习可单独暂存，不必标记学完。');
        return true;
      } catch (_) {
        this.status(this.safe ? '暂时无法读取云端；可继续填写，输入会在本机暂存。' : '暂时无法读取云端，本机暂存也不可用，请勿关闭页面。');
        return false;
      }
    }
    save() {
      if (this.saving) return this.saving;
      this.saving = this.sync().finally(() => { this.saving = null; });
      return this.saving;
    }
    keepLocal() {
      this.revision = this.remote?.revision || 0; this.conflict = false; this.pending = null;
      this.dirty = true; this.persist();
    }
    useCloud() {
      this.notes = this.remote?.notes || ''; this.answers = this.remote?.answers || {};
      this.revision = this.remote?.revision || 0; this.conflict = false; this.pending = null;
      this.dirty = false; this.persist(); this.onChange?.(this.snapshot());
      this.status('已采用云端版本，完成状态未改变。');
    }
    async sync() {
      if (!this.loaded && !await this.load()) throw Error('云端暂不可用，当前输入仍在本机。');
      if (this.conflict) throw Error('另一页面已更新云端，请先核对；当前输入仍在本机。');
      if (!this.hasCloud) { this.dirty = true; this.persist(); }
      while (this.dirty) {
        this.pending ||= {...this.snapshot(), revision: this.revision, key: crypto.randomUUID()};
        this.persist(); this.status('正在同步笔记与练习答案…');
        try {
          const response = await this.fetch(this.url, {method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'}, body: JSON.stringify(this.pending)});
          const data = await response.json();
          if (!response.ok) {
            if (response.status === 409) {
              await this.load(); this.conflict = true;
            }
            throw Error(typeof data.detail === 'string' ? data.detail : '同步失败，请重试暂存。');
          }
          this.revision = data.revision; this.pending = null; this.hasCloud = true;
          this.dirty = !same(this.snapshot(), data); this.persist();
        } catch (error) {
          this.status((this.safe ? '输入已保留在本机。' : '请勿关闭页面。') + error.message);
          throw error;
        }
      }
      this.status('笔记与练习答案已暂存到云端；完成状态未改变。');
      return this.snapshot();
    }
  }
  window.StudyDraftSession = StudyDraftSession;
})();
