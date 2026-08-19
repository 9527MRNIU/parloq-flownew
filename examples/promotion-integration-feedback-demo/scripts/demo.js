(function () {
  const status = document.querySelector("#runtime-status");
  const integration = document.querySelector("#integration-value");
  const channel = document.querySelector("#channel-value");
  const source = document.querySelector("#source-value");
  const log = document.querySelector("#event-log");
  const buttons = Array.from(document.querySelectorAll("[data-event]"));

  function append(message, tone) {
    const item = document.createElement("li");
    item.textContent = `${new Date().toLocaleTimeString()} · ${message}`;
    item.dataset.tone = tone || "neutral";
    log.prepend(item);
  }

  function setDisabled(disabled) {
    buttons.forEach((button) => {
      button.disabled = disabled;
    });
  }

  async function report(eventType) {
    setDisabled(true);
    append(`正在上报 ${eventType}`);
    try {
      const response = await window.PromotionIntegrationBridge.report(eventType, {
        demo: true,
        trigger: "button",
        result: eventType === "completed" ? "ok" : "simulated_failure"
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      append(
        `${eventType} 已持久化${payload.data && payload.data.eventId ? `，事件 ${payload.data.eventId}` : ""}`,
        "success"
      );
    } catch (error) {
      append(`${eventType} 上报失败：${error.message}`, "error");
    } finally {
      setDisabled(false);
    }
  }

  setDisabled(true);
  if (!window.PromotionIntegrationBridge) {
    status.textContent = "未获得运行会话";
    append("请从已绑定渠道生成的 iframe 地址打开此页面", "error");
    return;
  }

  window.PromotionIntegrationBridge.ready()
    .then(async (runtime) => {
      status.textContent = "已连接";
      integration.textContent = `${runtime.integration.key} · v${runtime.integration.version}`;
      channel.textContent = `${runtime.channel.slug} · ${runtime.channel.countryCode}`;
      source.textContent = runtime.channel.trafficSource === "fission" ? "裂变" : "直接";
      setDisabled(false);
      append("运行上下文获取成功", "success");
      const response = await window.PromotionIntegrationBridge.report("ready", {
        demo: true,
        trigger: "runtime_ready"
      });
      append(response.ok ? "ready 已持久化" : `ready 上报失败：HTTP ${response.status}`, response.ok ? "success" : "error");
    })
    .catch((error) => {
      status.textContent = "连接失败";
      append(`运行上下文获取失败：${error.message}`, "error");
    });

  buttons.forEach((button) => {
    button.addEventListener("click", () => report(button.dataset.event));
  });
})();
