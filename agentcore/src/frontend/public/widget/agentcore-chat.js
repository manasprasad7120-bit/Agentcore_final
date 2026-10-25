(function () {
  const REMOTE_BUNDLE_PATH = "/widget/agentcore-chat-runtime.js";
  const RUN_PATH_RE = /\/api\/v1\/run\//;
  const DEFAULT_RUN_CONTEXT = { env: "dev", version: "v1" };

  let bundleLoadPromise;

  function getRunContext() {
    const ctx = window.__agentcoreWidgetRunContext || {};
    return {
      env: String(ctx.env || DEFAULT_RUN_CONTEXT.env),
      version: String(ctx.version || DEFAULT_RUN_CONTEXT.version),
    };
  }

  function rewriteRunUrl(urlLike) {
    if (!urlLike) return urlLike;
    const { env, version } = getRunContext();
    try {
      const absolute = new URL(String(urlLike), window.location.origin);
      if (RUN_PATH_RE.test(absolute.pathname)) {
        absolute.pathname = absolute.pathname.replace("/api/v1/run/", "/api/run/");
        if (!absolute.searchParams.get("env")) {
          absolute.searchParams.set("env", env);
        }
        if (!absolute.searchParams.get("version")) {
          absolute.searchParams.set("version", version);
        }
        return absolute.toString();
      }
      return urlLike;
    } catch (_err) {
      const asString = String(urlLike);
      if (RUN_PATH_RE.test(asString)) {
        const normalized = asString.replace("/api/v1/run/", "/api/run/");
        try {
          const absoluteNormalized = new URL(normalized, window.location.origin);
          if (!absoluteNormalized.searchParams.get("env")) {
            absoluteNormalized.searchParams.set("env", env);
          }
          if (!absoluteNormalized.searchParams.get("version")) {
            absoluteNormalized.searchParams.set("version", version);
          }
          return absoluteNormalized.toString();
        } catch (_innerErr) {
          return normalized;
        }
      }
      return urlLike;
    }
  }

  function patchNetworkForRunPath() {
    if (!window.__agentcoreWidgetRunPathPatched) {
      window.__agentcoreWidgetRunPathPatched = true;

      const originalFetch = window.fetch;
      window.fetch = function (input, init) {
        if (typeof input === "string" || input instanceof URL) {
          const rewritten = rewriteRunUrl(input);
          return originalFetch.call(this, rewritten, init);
        }
        if (input && typeof input === "object" && "url" in input) {
          const rewritten = rewriteRunUrl(input.url);
          if (rewritten !== input.url) {
            const patchedRequest = new Request(rewritten, input);
            return originalFetch.call(this, patchedRequest, init);
          }
        }
        return originalFetch.call(this, input, init);
      };

      const originalOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function (method, url, async, user, password) {
        const rewritten = rewriteRunUrl(url);
        return originalOpen.call(this, method, rewritten, async, user, password);
      };
    }
  }

  function getRuntimeBundleUrl() {
    const ctx = window.__agentcoreWidgetRunContext || {};
    const baseHost = String(ctx.host_url || window.location.origin);
    return new URL(REMOTE_BUNDLE_PATH, `${baseHost}/`).toString();
  }

  function loadRemoteBundle() {
    if (bundleLoadPromise) return bundleLoadPromise;

    bundleLoadPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector(
        `script[data-agentcore-widget="remote-bundle"]`,
      );

      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener(
          "error",
          () => reject(new Error("Failed to load remote widget bundle.")),
          { once: true },
        );
        return;
      }

      const script = document.createElement("script");
      script.src = getRuntimeBundleUrl();
      script.async = true;
      script.defer = true;
      script.setAttribute("data-agentcore-widget", "remote-bundle");
      script.addEventListener("load", () => resolve(), { once: true });
      script.addEventListener(
        "error",
        () => reject(new Error("Failed to load remote widget bundle.")),
        { once: true },
      );
      document.head.appendChild(script);
    });

    return bundleLoadPromise;
  }

  class AgentcoreChatElement extends HTMLElement {
    static get observedAttributes() {
      return [
        "window_title",
        "agent_id",
        "agentId",
        "flow_id",
        "flowId",
        "host_url",
        "hostUrl",
        "env",
        "version",
        "api_key",
        "apiKey",
      ];
    }

    connectedCallback() {
      this.mount();
    }

    attributeChangedCallback(name, _oldValue, newValue) {
      if (!this._innerWidget) return;
      if (newValue === null) {
        this._innerWidget.removeAttribute(name);
      } else {
        this._innerWidget.setAttribute(name, newValue);
      }

      // Keep agent/flow aliases in sync for runtimes that read one or the other.
      if (name === "agent_id" || name === "agentId") {
        const val = newValue || "";
        if (val) {
          this._innerWidget.setAttribute("flow_id", val);
          this._innerWidget.setAttribute("flowId", val);
        }
      }
      if (name === "flow_id" || name === "flowId") {
        const val = newValue || "";
        if (val) {
          this._innerWidget.setAttribute("agent_id", val);
          this._innerWidget.setAttribute("agentId", val);
        }
      }

      if (name === "env" || name === "version") {
        window.__agentcoreWidgetRunContext = {
          ...(window.__agentcoreWidgetRunContext || DEFAULT_RUN_CONTEXT),
          host_url: this.getAttribute("host_url") || window.location.origin,
          env: this.getAttribute("env") || DEFAULT_RUN_CONTEXT.env,
          version: this.getAttribute("version") || DEFAULT_RUN_CONTEXT.version,
        };
      }
    }

    async mount() {
      patchNetworkForRunPath();
      window.__agentcoreWidgetRunContext = {
        ...(window.__agentcoreWidgetRunContext || DEFAULT_RUN_CONTEXT),
        host_url: this.getAttribute("host_url") || window.location.origin,
        env: this.getAttribute("env") || DEFAULT_RUN_CONTEXT.env,
        version: this.getAttribute("version") || DEFAULT_RUN_CONTEXT.version,
      };

      try {
        await loadRemoteBundle();
      } catch (error) {
        console.error("[agentcore-widget]", error);
      }

      if (this._innerWidget) return;

      const inner = document.createElement("agentcore-chat-internal");
      for (const attr of this.attributes) {
        inner.setAttribute(attr.name, attr.value);
      }

      const idFromAttrs =
        this.getAttribute("flow_id") ||
        this.getAttribute("flowId") ||
        this.getAttribute("agent_id") ||
        this.getAttribute("agentId");

      if (idFromAttrs) {
        inner.setAttribute("flow_id", idFromAttrs);
        inner.setAttribute("flowId", idFromAttrs);
        inner.setAttribute("agent_id", idFromAttrs);
        inner.setAttribute("agentId", idFromAttrs);
      }

      this._innerWidget = inner;
      this.appendChild(inner);
    }
  }

  if (!customElements.get("agentcore-chat")) {
    customElements.define("agentcore-chat", AgentcoreChatElement);
  }
})();
