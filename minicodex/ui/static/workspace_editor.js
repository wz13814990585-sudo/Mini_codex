// CodeMirror-backed multi-file editor; the compiled bundle is shipped with the wheel.

import { basicSetup } from 'codemirror';
import { Compartment, EditorState } from '@codemirror/state';
import { EditorView, keymap } from '@codemirror/view';
import { openSearchPanel } from '@codemirror/search';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';

const editorTheme = EditorView.theme({
  '&': { backgroundColor: '#0e1113', color: '#e6ede8' },
  '.cm-content': { caretColor: '#9fffc9', fontFamily: 'var(--mono)' },
  '.cm-gutters': { backgroundColor: '#0e1113', color: '#596661', borderRight: '1px solid #202827' },
  '.cm-activeLine': { backgroundColor: '#18211d' },
  '.cm-activeLineGutter': { backgroundColor: '#18211d' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': { backgroundColor: '#315542' },
  '.cm-panels': { backgroundColor: '#151c1a', color: '#e6ede8' },
  '.cm-tooltip': { backgroundColor: '#1b2420', color: '#e6ede8', border: '1px solid #34463a' },
  '.cm-searchMatch': { backgroundColor: '#4c4a23' },
}, { dark: true });

function languageExtension(language) {
  switch (language) {
    case 'python': return python();
    case 'javascript': return javascript();
    case 'typescript': return javascript({ typescript: true });
    case 'tsx': return javascript({ typescript: true, jsx: true });
    case 'html': return html();
    case 'css': return css();
    case 'json': return json();
    case 'markdown': return markdown();
    default: return [];
  }
}

export class WorkspaceEditor {
  constructor(parent, { onChange, onSave, styleNonce }) {
    this.tabs = new Map();
    this.activePath = '';
    this.canEdit = true;
    this.onChange = onChange;
    this.onSave = onSave;
    this.styleNonce = styleNonce;
    this.readOnly = new Compartment();
    this.editable = new Compartment();
    this.view = new EditorView({
      state: EditorState.create({ doc: '', extensions: [basicSetup, editorTheme, EditorView.cspNonce.of(styleNonce)] }),
      parent,
    });
  }

  _state(content, language) {
    return EditorState.create({
      doc: content,
      extensions: [
        basicSetup,
        editorTheme,
        EditorView.cspNonce.of(this.styleNonce),
        languageExtension(language),
        this.readOnly.of(EditorState.readOnly.of(!this.canEdit)),
        this.editable.of(EditorView.editable.of(this.canEdit)),
        keymap.of([{ key: 'Mod-s', run: () => { this.onSave(); return true; } }]),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged || !this.activePath) return;
          const tab = this.tabs.get(this.activePath);
          if (!tab) return;
          tab.state = update.state;
          this.onChange(tab);
        }),
      ],
    });
  }

  open(path, payload) {
    let tab = this.tabs.get(path);
    if (!tab) {
      tab = {
        path, revision: payload.revision, savedContent: payload.content,
        editable: Boolean(payload.editable), language: payload.language,
        state: this._state(payload.content, payload.language),
      };
      this.tabs.set(path, tab);
    } else if (!this.dirty(path) && tab.revision !== payload.revision) {
      if (this.activePath === path) this.activePath = '';
      tab.revision = payload.revision;
      tab.savedContent = payload.content;
      tab.editable = Boolean(payload.editable);
      tab.language = payload.language;
      tab.state = this._state(payload.content, payload.language);
    }
    this.activate(path);
    return tab;
  }

  activate(path) {
    const tab = this.tabs.get(path);
    if (!tab) return null;
    if (this.activePath && this.tabs.has(this.activePath)) {
      this.tabs.get(this.activePath).state = this.view.state;
    }
    this.activePath = path;
    this.view.setState(tab.state);
    this.setCanEdit(this.canEdit, true);
    this.view.requestMeasure();
    return tab;
  }

  setCanEdit(value, force = false) {
    const normalized = Boolean(value);
    if (!force && normalized === this.canEdit) return;
    this.canEdit = normalized;
    const tab = this.tabs.get(this.activePath);
    if (!tab) return;
    const editable = this.canEdit && tab.editable;
    this.view.dispatch({ effects: [
      this.readOnly.reconfigure(EditorState.readOnly.of(!editable)),
      this.editable.reconfigure(EditorView.editable.of(editable)),
    ] });
    tab.state = this.view.state;
  }

  dirty(path) {
    const tab = this.tabs.get(path);
    if (!tab) return false;
    const state = path === this.activePath ? this.view.state : tab.state;
    return state.doc.toString() !== tab.savedContent;
  }

  current() {
    const tab = this.tabs.get(this.activePath);
    if (!tab) return null;
    return { ...tab, content: this.view.state.doc.toString(), dirty: this.dirty(tab.path) };
  }

  markSaved(path, payload) {
    const tab = this.tabs.get(path);
    if (!tab) return;
    tab.savedContent = payload.content;
    tab.revision = payload.revision;
    tab.editable = Boolean(payload.editable);
    if (path === this.activePath) tab.state = this.view.state;
    this.onChange(tab);
  }

  rename(oldPath, newPath) {
    const entries = [...this.tabs.entries()].map(([path, tab]) => {
      if (path !== oldPath) return [path, tab];
      tab.path = newPath;
      return [newPath, tab];
    });
    this.tabs = new Map(entries);
    if (this.activePath === oldPath) this.activePath = newPath;
  }

  close(path) {
    if (!this.tabs.has(path)) return;
    const wasActive = this.activePath === path;
    this.tabs.delete(path);
    if (wasActive) {
      this.activePath = '';
      const next = [...this.tabs.keys()].at(-1);
      if (next) this.activate(next);
      else this.view.setState(EditorState.create({ doc: '', extensions: [basicSetup, editorTheme, EditorView.cspNonce.of(this.styleNonce)] }));
    }
  }

  find() {
    if (!this.activePath) return;
    this.view.focus();
    openSearchPanel(this.view);
  }

  focus() { this.view.focus(); }
  requestMeasure() { this.view.requestMeasure(); }
}
