(() => {
  const config = window.LOCAL_LLM || {};
  const chat = document.getElementById("chat");
  const welcome = document.getElementById("welcome");
  const composer = document.getElementById("composer");
  const prompt = document.getElementById("prompt");
  const send = document.getElementById("send");
  const fileInput = document.getElementById("file-input");
  const attachment = document.getElementById("attachment");
  const composerShell = document.querySelector(".composer-shell");
  const status = document.getElementById("status");
  let messages = [];
  let selectedFile = null;
  let busy = false;
  let activeController = null;
  let chatGeneration = 0;

  function escapeHtml(value) {
    return value.replace(/[&<>'"]/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[character]));
  }

  function renderInline(value) {
    let html = escapeHtml(value);
    const codeSpans = [];
    html = html.replace(/`([^`\n]+)`/g, (_, code) => {
      codeSpans.push(`<code>${code}</code>`);
      return `@@CODE${codeSpans.length - 1}@@`;
    });
    html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    html = html.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
    html = html.replace(/@@CODE(\d+)@@/g, (_, index) => codeSpans[Number(index)]);
    return html.replace(/\n/g, "<br>");
  }

  function tableCells(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
  }

  function isTableSeparator(line) {
    return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  }

  function renderTable(lines) {
    const headers = tableCells(lines[0]);
    const rows = lines.slice(2).map(tableCells);
    const headerHtml = headers.map((cell) => `<th>${renderInline(cell)}</th>`).join("");
    const rowHtml = rows.map((row) => {
      const cells = headers.map((_, index) => `<td>${renderInline(row[index] || "")}</td>`).join("");
      return `<tr>${cells}</tr>`;
    }).join("");
    return `<div class="table-scroll"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowHtml}</tbody></table></div>`;
  }

  function renderMarkdown(value) {
    const lines = value.replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }

      if (line.trim().startsWith("```")) {
        const code = [];
        index += 1;
        while (index < lines.length && !lines[index].trim().startsWith("```")) {
          code.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        continue;
      }

      if (index + 1 < lines.length && line.includes("|") && isTableSeparator(lines[index + 1])) {
        const table = [line, lines[index + 1]];
        index += 2;
        while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
          table.push(lines[index]);
          index += 1;
        }
        blocks.push(renderTable(table));
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        const level = heading[1].length;
        blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
          items.push(`<li>${renderInline(lines[index].replace(/^\s*[-*+]\s+/, ""))}</li>`);
          index += 1;
        }
        blocks.push(`<ul>${items.join("")}</ul>`);
        continue;
      }

      if (/^\s*\d+\.\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
          items.push(`<li>${renderInline(lines[index].replace(/^\s*\d+\.\s+/, ""))}</li>`);
          index += 1;
        }
        blocks.push(`<ol>${items.join("")}</ol>`);
        continue;
      }

      const paragraph = [line];
      index += 1;
      while (index < lines.length && lines[index].trim()) {
        if (/^#{1,6}\s+/.test(lines[index]) || /^\s*[-*+]\s+/.test(lines[index]) || /^\s*\d+\.\s+/.test(lines[index])) break;
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
    }
    return blocks.join("");
  }

  function addMessage(role, content, attachmentInfo = null) {
    welcome?.classList.add("hidden");
    const row = document.createElement("div");
    row.className = `message-row ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (attachmentInfo) {
      const fileBadge = document.createElement("div");
      fileBadge.className = "message-attachment";
      fileBadge.textContent = `📎 ${attachmentInfo.name}`;
      bubble.appendChild(fileBadge);
    }
    const contentElement = document.createElement("div");
    contentElement.className = "message-content";
    contentElement.innerHTML = renderMarkdown(content || "");
    bubble.appendChild(contentElement);
    row.appendChild(bubble);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return contentElement;
  }

  function addDownload(card) {
    const row = document.createElement("div");
    row.className = "message-row assistant";
    row.innerHTML = `<div class="bubble"><div class="download-card"><a href="${encodeURI(card.download_url)}">Download ${escapeHtml(card.name)}</a><small>This temporary file expires automatically.</small></div></div>`;
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
  }

  function setBusy(value) {
    busy = value;
    send.disabled = false;
    prompt.disabled = value;
    fileInput.disabled = value;
    send.classList.toggle("stop", value);
    send.setAttribute("aria-label", value ? "Stop generation" : "Send message");
    send.innerHTML = value ? "Stop <span>■</span>" : "Send <span>↵</span>";
  }

  function stopGeneration() {
    if (activeController) activeController.abort();
  }

  function handleDroppedFile(file) {
    if (!file || busy) return;
    upload(file).catch((error) => { status.textContent = error.message; });
  }

  function parseSseBuffer(buffer, handler) {
    const frames = buffer.split("\n\n");
    const remainder = frames.pop();
    for (const frame of frames) {
      const eventLine = frame.split("\n").find((line) => line.startsWith("event: "));
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      let data;
      try { data = JSON.parse(dataLine.slice(6)); } catch (_) { continue; }
      handler(eventLine ? eventLine.slice(7) : "message", data);
    }
    return remainder;
  }

  async function upload(file) {
    const form = new FormData();
    form.append("upload", file);
    status.textContent = "Uploading…";
    const response = await fetch("/api/uploads", { method: "POST", headers: { "X-CSRF-Token": config.csrf_token }, body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Upload failed");
    selectedFile = data;
    attachment.classList.remove("hidden");
    attachment.innerHTML = `${escapeHtml(data.name)} <button type="button" id="remove-file" aria-label="Remove attachment">×</button>`;
    document.getElementById("remove-file").addEventListener("click", removeFile);
    status.textContent = "Attached";
  }

  async function clearAttachment(deleteRemote) {
    if (selectedFile && deleteRemote) {
      await fetch(`/api/files/${encodeURIComponent(selectedFile.file_id)}`, { method: "DELETE", headers: { "X-CSRF-Token": config.csrf_token } });
    }
    selectedFile = null;
    fileInput.value = "";
    attachment.classList.add("hidden");
    attachment.textContent = "";
    status.textContent = "";
  }

  async function removeFile() { await clearAttachment(true); }

  async function startNewChat() {
    chatGeneration += 1;
    stopGeneration();
    if (selectedFile) await clearAttachment(true);
    messages = [];
    chat.innerHTML = "";
    chat.appendChild(welcome);
    welcome.classList.remove("hidden");
    prompt.value = "";
    status.textContent = "";
    setBusy(false);
    prompt.focus();
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (busy) {
      stopGeneration();
      return;
    }
    if (!prompt.value.trim()) return;
    const requestGeneration = chatGeneration;
    const text = prompt.value.trim();
    prompt.value = "";
    const attachedFile = selectedFile;
    const attachedFileId = attachedFile?.file_id || null;
    addMessage("user", text, attachedFile);
    messages.push({ role: "user", content: text });
    setBusy(true);
    clearAttachment(false);
    status.textContent = "Thinking…";
    const controller = new AbortController();
    activeController = controller;
    let assistantText = "";
    let assistantBubble = null;
    let assistantStatusBubble = null;

    function setAssistantStatus(message) {
      if (!assistantBubble) {
        if (!assistantStatusBubble) {
          assistantStatusBubble = addMessage("assistant", "");
          assistantStatusBubble.classList.add("status-bubble");
        }
        assistantStatusBubble.textContent = message;
      }
    }

    function setAssistantError(message) {
      const target = assistantBubble || assistantStatusBubble || addMessage("assistant", "");
      target.classList.remove("status-bubble");
      target.innerHTML = renderMarkdown(`Error: ${message}`);
    }

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": config.csrf_token },
        body: JSON.stringify({ messages, file_id: attachedFileId }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error("Chat request failed");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        buffer = parseSseBuffer(buffer, (eventName, data) => {
          if (requestGeneration !== chatGeneration) return;
          if (eventName === "start") {
            status.textContent = "Generating…";
            setAssistantStatus("Generating…");
          }
          if (eventName === "status") {
            status.textContent = data.message || "Working…";
            setAssistantStatus(data.message || "Working…");
          }
          if (eventName === "token") {
            if (!assistantBubble) {
              assistantBubble = assistantStatusBubble || addMessage("assistant", "");
              assistantBubble.classList.remove("status-bubble");
            }
            assistantText += data.content || "";
            assistantBubble.innerHTML = renderMarkdown(assistantText);
            chat.scrollTop = chat.scrollHeight;
          }
          if (eventName === "message") {
            assistantText = data.content || "";
            assistantBubble = assistantStatusBubble || addMessage("assistant", "");
            assistantBubble.classList.remove("status-bubble");
            assistantBubble.innerHTML = renderMarkdown(assistantText);
          }
          if (eventName === "file") addDownload(data);
          if (eventName === "error") throw new Error(data.message || "Request failed");
        });
      }
      if (requestGeneration === chatGeneration) {
        if (assistantText) messages.push({ role: "assistant", content: assistantText });
        status.textContent = "";
      }
    } catch (error) {
      if (requestGeneration !== chatGeneration) return;
      if (error.name === "AbortError") {
        if (assistantText) {
          messages.push({ role: "assistant", content: assistantText });
          status.textContent = "Stopped";
        } else {
          setAssistantStatus("Stopped.");
          status.textContent = "Stopped";
        }
      } else {
        setAssistantError(error.message);
        status.textContent = "";
      }
    } finally {
      if (activeController === controller) activeController = null;
      if (requestGeneration === chatGeneration) {
        setBusy(false);
        prompt.focus();
      }
    }
  }

  document.getElementById("new-chat")?.addEventListener("click", startNewChat);
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) upload(fileInput.files[0]).catch((error) => { status.textContent = error.message; }); });
  ["dragenter", "dragover"].forEach((eventName) => {
    composerShell.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (!busy) composerShell.classList.add("drag-active");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    composerShell.addEventListener(eventName, (event) => {
      event.preventDefault();
      composerShell.classList.remove("drag-active");
    });
  });
  composerShell.addEventListener("drop", (event) => {
    handleDroppedFile(event.dataTransfer.files[0]);
  });
  composer.addEventListener("submit", sendMessage);
  prompt.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); } });
  window.setInterval(() => {
    if (!document.hidden) {
      fetch("/api/heartbeat", { method: "POST", headers: { "X-CSRF-Token": config.csrf_token } }).catch(() => {});
    }
  }, 60_000);
})();
