(() => {
  window.Account?.ready
    .then(async () => {
      const r = await fetch("/api/native-plans/config", { cache: "no-store" });
      if (!r.ok) return;
      const c = await r.json();
      if (!c.enabled) return;
      const link = document.createElement("a");
      link.href = "/native-plans";
      link.textContent = "基础目标与计划";
      link.className = "btn";
      (
        document.querySelector("nav") ||
        document.querySelector("header") ||
        document.body
      ).append(link);
    })
    .catch(() => {});
})();
