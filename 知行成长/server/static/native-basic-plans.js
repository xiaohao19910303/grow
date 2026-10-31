"use strict";
(async () => {
  const $ = (id) => document.getElementById(id),
    clone = (x) => JSON.parse(JSON.stringify(x)),
    today = () => new Date().toLocaleDateString("en-CA");
  let owner,
    scope,
    state,
    plans = [],
    goals = [],
    busy = false,
    latest = null,
    alive = true;
  const message = (text) => {
    $("message").textContent = text;
  };
  function fresh() {
    return {
      form: {
        title: "",
        completion_criteria: "",
        period_start: today(),
        period_end: today(),
        tasks: [action()],
      },
      snapshot: null,
      baseVersion: null,
      pending: null,
    };
  }
  function action() {
    return {
      id: crypto.randomUUID(),
      title: "",
      scheduled_for: null,
      estimated_minutes: null,
      completion_criteria: "",
      guidance: "",
    };
  }
  function persist() {
    localStorage.setItem(scope, JSON.stringify(state));
  }
  async function api(path, method = "GET", body, key) {
    const r = await fetch("/api/native-plans/" + path, {
      method,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Copilot-Request": "1",
        "X-Account-Id": owner,
        "Idempotency-Key": key || "",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const v = await r.json();
    if (!alive) throw Error("账户已变化，原输入已保留。");
    if (!r.ok) {
      const explanation =
        r.status === 409
          ? "目标或计划已变化，输入已保留。请读取最新状态并重新审阅。"
          : r.status === 401
            ? "网页登录已失效，原输入和请求已保留；重新登录原账户后再核对。"
            : r.status === 422
              ? "请检查标题、日期、投入和当前可用时间后再保存。"
              : r.status >= 500
                ? "操作结果尚未确认，原输入和请求已保留，请核对上次原请求。"
                : "请求未完成，输入已保留。";
      const e = Error(explanation);
      e.status = r.status;
      throw e;
    }
    return v.data;
  }
  const edited = () =>
    state.snapshot
      ? JSON.stringify(state.form) !== JSON.stringify(state.snapshot.draft)
      : Boolean(state.form.title || state.form.tasks.some((x) => x.title));
  function text(parent, value) {
    const p = document.createElement("p");
    p.textContent = value;
    parent.append(p);
  }
  function updateButtons() {
    const unavailable = busy || !alive;
    const proposed = !state.snapshot || state.snapshot.status === "proposed";
    $("fields").disabled = unavailable || !!state.pending || !proposed;
    $("save").disabled = unavailable || !!state.pending || !proposed;
    $("confirm").disabled =
      unavailable ||
      !!state.pending ||
      state.snapshot?.status !== "proposed" ||
      edited() ||
      state.baseVersion !== state.snapshot.version ||
      Boolean(latest && latest.version !== state.baseVersion);
    $("retry").hidden = !state.pending;
    $("retry").disabled = unavailable;
    $("rebase").hidden = !latest || state.baseVersion === latest.version;
    $("refresh").disabled = unavailable;
    $("new").disabled = unavailable || !!state.pending;
    $("rebase").disabled = unavailable || !!state.pending;
  }
  function changed() {
    try {
      persist();
      updateButtons();
    } catch (e) {
      message("输入尚未保存到浏览器，请保留页面并重试。");
      $("save").disabled = $("confirm").disabled = true;
    }
  }
  function render() {
    for (const [id, key] of [
      ["title", "title"],
      ["criteria", "completion_criteria"],
      ["start", "period_start"],
      ["end", "period_end"],
    ]) {
      $(id).value = state.form[key];
      $(id).oninput = () => {
        state.form[key] = $(id).value;
        changed();
      };
    }
    $("goal").replaceChildren(new Option("新目标", ""));
    for (const g of goals.filter((g) => ["draft", "active"].includes(g.status)))
      $("goal").add(new Option(g.title, g.id));
    $("goal").options[0].text = state.snapshot
      ? "本草稿目标：" + state.snapshot.draft.title
      : "新目标";
    $("goal").disabled = Boolean(state.snapshot);
    $("goal").value = state.form.goal_id || "";
    $("goal").onchange = () => {
      if ($("goal").value) state.form.goal_id = $("goal").value;
      else delete state.form.goal_id;
      changed();
    };
    $("actions").replaceChildren();
    state.form.tasks.forEach((a, index) => {
      const row = document.createElement("div");
      row.className = "action";
      text(row, "行动 " + (index + 1));
      for (const [key, label, type] of [
        ["title", "一件可执行的小事", "text"],
        ["scheduled_for", "日期，留空待安排", "date"],
        ["estimated_minutes", "预计分钟，留空为未知", "number"],
        ["completion_criteria", "完成标准", "text"],
        ["guidance", "说明或步骤", "text"],
      ]) {
        const l = document.createElement("label");
        l.textContent = label;
        const input = document.createElement("input");
        input.type = type;
        input.value = a[key] ?? "";
        input.dataset.field = key;
        if (type === "number") {
          input.min = 1;
          input.max = 1440;
        }
        input.oninput = () => {
          a[key] =
            key === "estimated_minutes"
              ? input.value === ""
                ? null
                : Number(input.value)
              : key === "scheduled_for"
                ? input.value || null
                : input.value;
          changed();
        };
        l.append(input);
        row.append(l);
      }
      if (state.form.tasks.length > 1) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "移除此草稿行动";
        remove.onclick = () => {
          state.form.tasks.splice(index, 1);
          changed();
          render();
        };
        row.append(remove);
      }
      $("actions").append(row);
    });
    $("plans").replaceChildren();
    for (const p of plans) {
      const b = document.createElement("button");
      b.textContent =
        p.draft.title +
        " · " +
        ({ proposed: "草稿", active: "已生效", superseded: "历史" }[p.status] ||
          "历史") +
        " · 第" +
        p.version +
        "版";
      b.dataset.planId = p.id;
      b.disabled = busy || !alive || !!state.pending;
      b.onclick = () => {
        if (edited()) {
          message("当前输入已保留，请先保存草稿再切换计划。");
          return;
        }
        state = {
          form: clone(p.draft),
          snapshot: p,
          baseVersion: p.version,
          pending: null,
        };
        latest = p;
        changed();
        render();
      };
      $("plans").append(b);
    }
    $("review").replaceChildren();
    const p = state.snapshot;
    if (p) {
      text(
        $("review"),
        "当前草稿第" +
          state.baseVersion +
          "版；服务器第" +
          (latest?.version || p.version) +
          "版。",
      );
      text(
        $("review"),
        p.status === "proposed"
          ? "确认后新增 " +
              p.draft.tasks.length +
              " 项行动，已有安排保留 " +
              p.preserved_tasks.length +
              " 项。"
          : "已确认或历史计划为只读；事实继续保留。",
      );
      for (const t of p.preserved_tasks) text($("review"), "保留：" + t.title);
      for (const l of p.daily_limits || [])
        text(
          $("review"),
          l.date +
            "：可用 " +
            (l.minutes ?? "未确认") +
            " 分钟；已知安排 " +
            l.known_minutes +
            " 分钟，另有 " +
            l.unknown_count +
            " 项投入未知",
        );
      if (p.source_reflection)
        text($("review"), "复盘来源：" + p.source_reflection.content);
      if (latest && latest.version !== state.baseVersion) {
        text($("review"), "服务器最新草稿（请与输入逐项比较）：");
        for (const t of latest.draft.tasks)
          text(
            $("review"),
            t.title +
              " · " +
              (t.scheduled_for || "日期未定") +
              " · " +
              (t.estimated_minutes ?? "投入未定") +
              " · " +
              t.completion_criteria,
          );
      }
    }
    updateButtons();
  }
  async function refresh() {
    if (busy || !alive) return;
    busy = true;
    updateButtons();
    try {
      const [ps, gs] = await Promise.all([api("manual-plans"), api("goals")]);
      plans = ps.items;
      goals = gs.items;
      if (state.snapshot) {
        latest = plans.find((p) => p.id === state.snapshot.id) || null;
        if (latest && !edited()) {
          state.snapshot = latest;
          state.form = clone(latest.draft);
          state.baseVersion = latest.version;
        }
      }
      persist();
      message("已读取最新账户状态。");
    } catch (e) {
      message("暂未刷新，原输入与已保存结果保留。" + e.message);
    } finally {
      busy = false;
      render();
    }
  }
  async function command(op) {
    if (busy || !alive) return;
    busy = true;
    updateButtons();
    try {
      state.pending = op;
      persist();
      const accepted = await api(op.path, op.method, op.body, op.key);
      const previous = clone(state);
      state.snapshot = accepted;
      state.baseVersion = accepted.version;
      state.form = clone(accepted.draft);
      state.pending = null;
      try {
        persist();
      } catch (e) {
        state = previous;
        throw Error("服务器可能已保存，请核对原请求。");
      }
      latest = accepted;
      plans = [accepted, ...plans.filter((p) => p.id !== accepted.id)];
      message(
        accepted.status === "active"
          ? "已确认保存，可在App读取同一份安排。"
          : "已保存草稿，尚未创建执行任务。",
      );
    } catch (e) {
      if (
        e.status >= 400 &&
        e.status < 500 &&
        ![401, 408, 429].includes(e.status)
      ) {
        const pending = state.pending;
        state.pending = null;
        try {
          persist();
        } catch {
          state.pending = pending;
        }
      }
      message(e.message);
    } finally {
      busy = false;
      render();
    }
  }
  try {
    const r = await fetch("/api/auth/me", { cache: "no-store" });
    if (!r.ok) throw Error("请先登录。");
    const identity = await r.json();
    owner = identity.user.id;
    const c = await (
      await fetch("/api/native-plans/config", { cache: "no-store" })
    ).json();
    if (
      !c.unified ||
      typeof c.scope !== "string" ||
      !/^[a-f0-9]{64}$/.test(c.scope)
    )
      throw Error(
        "请在设置关联自己的LightTick账号，再使用统一账号登录。App基础使用不需要此网页关联。",
      );
    scope =
      "native-basic-plans.v2." + location.origin + "." + owner + "." + c.scope;
    const saved = localStorage.getItem(scope);
    state = saved ? JSON.parse(saved) : fresh();
    if (!state.form || !Array.isArray(state.form.tasks))
      throw Error("草稿暂无法读取，请保留浏览器数据。");
  } catch (e) {
    message(e.message);
    $("fields").disabled = $("save").disabled = $("confirm").disabled = true;
    return;
  }
  window.addEventListener("storage", (e) => {
    if (e.key === "grow-account-session") {
      alive = false;
      $("fields").disabled = $("save").disabled = $("confirm").disabled = true;
      message("账户已变化，请重新打开本页；原输入保留在原账户。");
    }
  });
  $("editor").onsubmit = (e) => {
    e.preventDefault();
    if (busy || state.pending) return;
    const body = clone(state.form);
    if (state.snapshot) body.base_version = state.baseVersion;
    command({
      path: "manual-plans" + (state.snapshot ? "/" + state.snapshot.id : ""),
      method: state.snapshot ? "PATCH" : "POST",
      body,
      key: crypto.randomUUID(),
    });
  };
  $("confirm").onclick = () =>
    command({
      path: "manual-plans/" + state.snapshot.id + "/confirm",
      method: "POST",
      body: {
        base_version: state.baseVersion,
        goal_base_version: state.snapshot.goal_version,
      },
      key: crypto.randomUUID(),
    });
  $("retry").onclick = () => command(state.pending);
  $("refresh").onclick = refresh;
  $("rebase").onclick = () => {
    if (!latest || busy || state.pending) return;
    state.baseVersion = latest.version;
    state.snapshot = latest;
    changed();
    render();
    message("输入已保留，请对照最新安排审阅，再保存草稿。");
  };
  $("add").onclick = () => {
    if (state.form.tasks.length < 50) {
      state.form.tasks.push(action());
      changed();
      render();
    }
  };
  $("new").onclick = () => {
    if (busy || state.pending || edited()) {
      message("请先保存当前输入并核对上次请求。");
      return;
    }
    state = fresh();
    latest = null;
    changed();
    render();
  };
  render();
  await refresh();
})();
