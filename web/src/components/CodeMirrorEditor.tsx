/**
 * CodeMirrorEditor — minimal CodeMirror 6 binding for markdown editing.
 *
 * Used by ResourceEditorView and NovelView. Wraps
 * @codemirror/state + @codemirror/view + @codemirror/lang-markdown into
 * a controlled component: value/onChange/readOnly. Each data type has
 * an independent editor; the variables type is read-only.
 */

import { useEffect, useRef } from "react";
import { EditorState, type Extension } from "@codemirror/state";
import {
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  placeholder as placeholderExt,
} from "@codemirror/view";
import { markdown } from "@codemirror/lang-markdown";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";

interface CodeMirrorEditorProps {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
}

export default function CodeMirrorEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
}: CodeMirrorEditorProps): React.ReactNode {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!hostRef.current) return;
    const updateListener = EditorView.updateListener.of((u) => {
      if (u.docChanged && onChangeRef.current) {
        onChangeRef.current(u.state.doc.toString());
      }
    });
    const extensions: Extension[] = [
      lineNumbers(),
      history(),
      highlightActiveLine(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      markdown(),
      EditorView.lineWrapping,
      EditorState.readOnly.of(readOnly),
      EditorView.contentAttributes.of({ "aria-label": "代码编辑器" }),
      updateListener,
    ];
    if (placeholder) {
      extensions.push(placeholderExt(placeholder));
    }
    const state = EditorState.create({
      doc: value,
      extensions,
    });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, placeholder]);

  // Sync external value changes (load/select) into the editor without
  // resetting the extensions.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return <div className="cm-host" ref={hostRef} />;
}
