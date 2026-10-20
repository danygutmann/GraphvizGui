import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { StreamLanguage, indentOnInput, bracketMatching, syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";

const dotLanguage = StreamLanguage.define({
  startState: () => ({ inBlockComment: false }),
  token(stream, state) {
    if (stream.eatSpace()) return null;
    if (state.inBlockComment) {
      if (stream.match("*/")) state.inBlockComment = false;
      else stream.next();
      return "comment";
    }
    if (stream.match("//") || stream.peek() === "#") {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match("/*")) {
      state.inBlockComment = true;
      return "comment";
    }
    if (stream.match(/^"(?:[^"\\]|\\.)*"?/)) return "string";
    if (stream.match(/^(?:digraph|graph|strict|subgraph|node|edge|rankdir|rank|label|shape|style|color|fillcolor|fontname|fontsize|splines|overlap)\b/i)) return "keyword";
    if (stream.match(/^(?:->|--|[{}\[\];=,])/)) return "operator";
    if (stream.match(/^[A-Za-z_][\w.-]*/)) return "variableName";
    stream.next();
    return null;
  },
  languageData: { commentTokens: { line: "//", block: { open: "/*", close: "*/" } } },
});

const highlight = syntaxHighlighting(defaultHighlightStyle, { fallback: true });
const editor = new EditorView({
  state: EditorState.create({
    doc: `digraph Example {\n  rankdir=LR;\n  Start -> Design -> Build -> Deploy;\n}\n`,
    extensions: [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      dotLanguage,
      indentOnInput(),
      bracketMatching(),
      highlight,
      EditorView.lineWrapping,
      EditorView.theme({
        "&": { height: "100%", fontSize: "14px" },
        ".cm-scroller": { overflow: "auto", fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace" },
        ".cm-gutters": { backgroundColor: "#f5f7fa", border: "0" },
        ".cm-activeLine": { backgroundColor: "#f0f5fb" },
      }),
    ],
  }),
  parent: document.querySelector("#editor"),
});

const byId = (id) => document.getElementById(id);
const authToken = () => byId("api-token").value.trim();
const headers = (json = false) => ({
  ...(json ? { "Content-Type": "application/json" } : {}),
  ...(authToken() ? { Authorization: "Bearer " + authToken() } : {}),
});
const source = () => editor.state.doc.toString();
const status = (message, kind = "") => {
  const element = byId("status");
  element.textContent = message;
  element.className = `status ${kind}`;
};
const apiJson = async (path, options = {}) => {
  const response = await fetch(`/api/v1${path}`, { ...options, headers: { ...headers(Boolean(options.body)), ...options.headers } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.diagnostics || payload.error?.message || `Request failed (${response.status}).`);
  return payload;
};

async function populateLibraries() {
  try {
    const [examples, templates, macros, engines, formats] = await Promise.all([
      apiJson("/examples"), apiJson("/templates"), apiJson("/macros"), apiJson("/engines"), apiJson("/formats"),
    ]);
    for (const item of [...examples.items, ...templates.items]) {
      const option = document.createElement("option");
      option.value = `${examples.items.includes(item) ? "examples" : "templates"}/${encodeURIComponent(item.name)}`;
      option.textContent = `${examples.items.includes(item) ? "Example" : "Template"}: ${item.name}`;
      byId("library").append(option);
    }
    byId("engine").replaceChildren(...engines.engines.map((engine) => new Option(engine, engine)));
    byId("format").replaceChildren(...formats.formats.map((format) => new Option(format.toUpperCase(), format)));
    renderMacros(macros.macros);
  } catch (error) {
    status(error.message, "error");
  }
}

function renderMacros(macros) {
  const container = byId("macros");
  const categories = new Map();
  for (const macro of macros) {
    if (!categories.has(macro.category)) categories.set(macro.category, []);
    categories.get(macro.category).push(macro);
  }
  for (const [category, items] of categories) {
    const heading = document.createElement("h3");
    heading.textContent = category;
    container.append(heading);
    for (const macro of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "macro";
      button.textContent = macro.name;
      button.title = macro.description;
      button.addEventListener("click", () => {
        const values = {};
        for (const parameter of macro.parameters) {
          const value = window.prompt(`${parameter.description}\n${parameter.name}`, parameter.default ?? "");
          if (value === null) return;
          values[parameter.name] = value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
        }
        const fragment = macro.dot.replace(/\{([^}]+)\}/g, (_, name) => values[name] ?? `{${name}}`);
        if (!window.confirm("Insert this fragment at the editor cursor? Place the cursor inside the graph body. Existing text will not be overwritten.")) return;
        const selection = editor.state.selection.main;
        editor.dispatch({ changes: { from: selection.from, to: selection.to, insert: `${fragment}\n` } });
        editor.focus();
      });
      container.append(button);
    }
  }
}

byId("render").addEventListener("click", async () => {
  status("Validating DOT…");
  try {
    const validation = await fetch("/api/v1/validate", {
      method: "POST", headers: headers(true), body: JSON.stringify({ dot: source(), engine: byId("engine").value }),
    });
    const result = await validation.json();
    if (!validation.ok) {
      status(result.error?.diagnostics || result.diagnostics || result.error?.message || "DOT validation failed.", "error");
      return;
    }
    if (!result.valid) {
      status(result.diagnostics || "Graphviz rejected this DOT document.", "error");
      return;
    }
    status("Rendering…");
    const response = await fetch("/api/v1/render", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ dot: source(), engine: byId("engine").value, format: byId("format").value }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error?.diagnostics || payload.error?.message || `Render failed (${response.status}).`);
    }
    const blob = await response.blob();
    const oldUrl = byId("download").dataset.url;
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    const url = URL.createObjectURL(blob);
    byId("download").dataset.url = url;
    byId("download").href = url;
    byId("download").download = `diagram.${byId("format").value}`;
    byId("download").hidden = false;
    if (byId("format").value === "svg" || byId("format").value === "png") {
      byId("preview").src = url;
      byId("preview").hidden = false;
      byId("preview-placeholder").hidden = true;
    } else {
      byId("preview").hidden = true;
      byId("preview-placeholder").hidden = false;
      byId("preview-placeholder").textContent = "PDF rendered. Use Download to view it.";
    }
    status(result.diagnostics || "Rendered successfully.", "success");
  } catch (error) {
    status(error.message, "error");
  }
});

byId("library").addEventListener("change", async (event) => {
  if (!event.target.value) return;
  try {
    const [kind, name] = event.target.value.split("/");
    const document = await apiJson(`/${kind}/${name}`);
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: document.dot } });
  } catch (error) {
    status(error.message, "error");
  }
  event.target.value = "";
});

byId("save").addEventListener("click", async () => {
  const name = window.prompt("Project name (without .dot):", "my-diagram");
  if (!name) return;
  try {
    let response = await fetch("/api/v1/projects", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ name, dot: source() }),
    });
    let payload = await response.json().catch(() => ({}));
    if (response.status === 409) {
      if (!window.confirm(`Project ${name} already exists. Replace it?`)) {
        status("Save cancelled.");
        return;
      }
      response = await fetch(`/api/v1/projects/${encodeURIComponent(name)}`, {
        method: "PUT", headers: headers(true), body: JSON.stringify({ dot: source() }),
      });
      payload = await response.json().catch(() => ({}));
    }
    if (!response.ok) throw new Error(payload.error?.message || `Save failed (${response.status}).`);
    status(`Saved ${payload.name}.`, "success");
  } catch (error) {
    status(error.message, "error");
  }
});

byId("load").addEventListener("click", async () => {
  try {
    const { projects } = await apiJson("/projects");
    const name = window.prompt(`Project filename to load:\n${projects.join("\n")}`);
    if (!name) return;
    const project = await apiJson(`/projects/${encodeURIComponent(name)}`);
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: project.dot } });
    status(`Loaded ${name}.`, "success");
  } catch (error) {
    status(error.message, "error");
  }
});

byId("export-dot").addEventListener("click", () => {
  const blob = new Blob([source()], { type: "text/vnd.graphviz;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "diagram.dot";
  link.click();
  URL.revokeObjectURL(url);
});

byId("zoom").addEventListener("input", (event) => {
  byId("preview").style.width = `${event.target.value}%`;
  byId("preview").style.maxWidth = "none";
});

populateLibraries();
