# Images

Attach images to messages so the agent can see them.

## Attaching

Three ways an image gets attached:

1. **Drag & drop** — drop a file into the terminal; most terminals paste a quoted path. The TUI extracts the path (single-quoted, double-quoted, or bare with backslash-escaped spaces) and stages it for the next message.
2. **Paste a path** — paste any `/path/to/file.png`-style absolute path; same detection rules apply.
3. **Type-and-send** — paths matching an image extension inside a typed message also get extracted and attached.

When at least one path is recognized, it disappears from the message text and shows up as a dim `+ filename` line above the chat bar.

Supported extensions:

```
.png .jpg .jpeg .gif .bmp .webp .svg .tiff .ico
```

Only **existing** files with one of those extensions are attached — typos and non-image paths are left in the message as literal text.

## Multiple attachments

Each attachment is appended to the pending list; the preview shows all of them. Stacking is not deduplicated by content, just by path string.

`Esc` clears any pending attachments before submission. After the message is sent, the pending list resets.

## How attachments are sent

Each attachment is read from disk, base64-encoded, and sent as an `image_url` block alongside a `text` block. The resulting multimodal content list is:

```json
[
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
  {"type": "text", "text": "What's in these screenshots?"}
]
```

If the message text is empty after path extraction, the placeholder `Please analyze this image.` is used so there's always a text block.

## Inline rendering (output)

The TUI can render images inline in terminals that support it (iTerm2 protocol or Kitty graphics protocol). Detected from `TERM_PROGRAM`, `LC_TERMINAL`, and `TERM`:

- iTerm2, WezTerm → iTerm2 OSC 1337 protocol
- Kitty → Kitty graphics protocol
- Anything else → no inline preview

Inline rendering is only used by helper utilities — the main message flow does not currently render images inline back to the user. Pasted attachments show as filename chips.

## Implementation pointers

- `src/deepagent_tui/utils/images.py` — detection, encoding, terminal protocols
- `tui/app.py:ChatTextArea._on_paste` — paste handler that extracts paths
- `tui/app.py:on_chat_text_area_submitted` — attach merging at submission time
