# anylink — Design System

The reference is a two-surface mobile app: a **dark home screen** (greeting, week strip,
timeline, task cards) and a **light messages screen** (search, story avatars, conversation
list, amber compose button). Whisper Line adopts the same split. Everything in
`newgen/secret/static/secret/app.css` and every template must follow this file.

---

## 1. Principles

1. **Conversations are home.** The first screen a person sees is their chat list, in the
   light "Messages" layout. Informational pages reuse that same list language with simple
   widget rows. Light is the default everywhere; dark is an opt-in theme chosen with the
   header toggle and remembered per device (`localStorage` → `.theme-dark` on `<html>`).
2. **Quiet, not clinical.** Generous whitespace, soft rounded rectangles, no hard borders
   on content, no gradients inside cards.
3. **One accent per job.** Blue means "today / progress / active". Amber means "create /
   compose". Mint means "read / online". Red means "urgent / danger". Nothing else.
4. **Content first.** No decorative illustration, no drop shadows on text, no emoji in
   the interface (the icon set is stroke-based SVG via `{% icon %}`).
5. **Anonymous by design.** Never imply identity collection. Privacy copy is part of the
   visual language (shield icons, muted reassurance lines), not a separate page.

---

## 2. Colour tokens

Defined once in `:root` and overridden in `.theme-dark`.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#FFFFFF` | `#101014` | App surface |
| `--surface` | `#FFFFFF` | `#1B1B20` | Cards on dark |
| `--surface-2` | `#F5F5F7` | `#26262C` | Chips, inputs, bubbles, timeline cards |
| `--line` | `#ECECF1` | `#2F2F36` | 1px dividers only |
| `--ink` | `#101014` | `#FFFFFF` | Primary text / filled buttons |
| `--ink-2` | `#4B4B55` | `#D5D5DD` | Secondary text |
| `--muted` | `#8B8B96` | `#8F8F9B` | Timestamps, captions |
| `--accent` | `#5D7BF7` | `#5D7BF7` | Active day, progress, selection |
| `--amber` | `#F0A93B` | `#F0A93B` | Compose button only |
| `--mint` | `#2FBF71` | `#2FBF71` | Read ticks, presence |
| `--danger` | `#E5484D` | `#E5484D` | Urgent, destructive |

Backdrop behind the phone frame (desktop only): `linear-gradient(160deg, #D6DEFE, #A7B7F4)`.
Never put this gradient inside `.app`.

Avatar tones are six flat colours keyed by a hash of the name, all with white text:
amber, blue, mint, violet `#A78BFA`, rose `#F472B6`, sky `#38BDF8`.

---

## 3. Typography

**Poppins** (400/500/600/700) with `system-ui` fallback. No second family.

| Role | Size / weight / tracking |
| --- | --- |
| Screen title (`Messages`) | 28px / 600 / `-0.03em` |
| Greeting (`Hey, Kelly!`) | 24px / 600 / `-0.03em` |
| Section heading | 16px / 600 / `-0.01em` |
| Card title | 14px / 600 |
| Body | 14px / 400, line-height 1.5 |
| List name | 14px / 600 |
| List preview | 12.5px / 400, muted, single line, ellipsis |
| Caption / timestamp | 11px / 500, muted |
| Nav label | 10px / 500 |

Numbers in the day strip are 15px/600; the weekday letter is 11px/500 muted.

---

## 4. Shape, spacing, elevation

- Radii: inputs/chips `14px`, cards `18–20px`, sheets `26px`, avatars & buttons `50%`.
- Spacing scale: `4, 8, 12, 16, 20, 24, 32` — screens pad `20px` horizontally, sections
  are separated by `22–26px`.
- Elevation exists only on the phone frame and the compose button. Cards are flat.
- Dividers are 1px `--line` and only appear between list rows.
- Touch targets are at least `44×44px`.

---

## 5. Frame

`.app-page` is a periwinkle backdrop with a centered 430px column. On phones the column is
the whole viewport (`height: 100dvh`); from 600px up it becomes a 900px-max rounded device
with a black bezel ring and a large soft shadow, exactly like the mockups. Chat uses the
same frame (`.chat-shell`).

Content scrolls inside the frame (`.screen`, `.messages`), never the page, so the bottom
navigation and the composer stay put.

---

## 6. Components

### Theme toggle
- **Placement**: 40px `icon-btn` in each app header (room entry, directory, inbox, chat) and
  fixed top-right on the auth screens. Sun in light mode, moon in dark.
- **Behaviour**: flips `.theme-dark` on `<html>`, saves the choice under `anylink-theme`,
  and updates `aria-pressed` plus the label. Applied before paint by
  `partials/theme_boot.html` so there is no flash.
- **Scope**: app surfaces only. The marketing landing and privacy pages stay light.

### Light messages
- **Visitor dock**: one shared `partials/anon_nav.html` — Chats, Directory, How it works —
  same order and one active item on every anonymous screen. Directory appears once the
  device has an active room.
- **Header**: 28px title, small muted subtitle, actions right. Search is a plain 40px
  circle; compose is a 46px **amber** circle with a pencil — the only amber in the product.
- **Search**: 14px rounded `--surface-2` field with a leading icon; no border, no shadow.
- **Story row**: 54px circular avatars in a horizontal scroll, 10.5px name under each.
  No rings, no plus button on the anonymous side.
- **Thread row**: 44px avatar, name + time on one line, single-line preview beneath,
  optional badges below. 1px divider between rows, none after the last.
- **Segmented filter**: pill row on `--surface-2`, active pill `--ink` (white in dark).
- **Metrics**: three flat bordered tiles, value 20px/600, label 10.5px muted.

### Chat
- Incoming bubble `--surface-2` with a 6px bottom-left corner; outgoing bubble `--ink`
  (black on light) with a 6px bottom-right corner. Both 18px radius, 14px text.
- Date separators are centered muted pills. System notes are centered muted italic text.
- Composer: pill textarea (`--surface-2`) + 44px filled send circle; private-note toggle
  is a small outlined pill. Quick replies are outlined chips.
- Sheets slide from the bottom in a 430px-wide panel; scrim is `rgba(12,12,16,.45)`.

### Forms and feedback
- Fields are label + 14px `--surface-2` input, no border, focus ring in `--accent`.
- Primary button = `--ink` fill; on dark it inverts to white fill with ink text.
- Notices: `--surface-2` panel, coloured icon, no border. Errors use a red-tinted panel.

### Bottom navigation
Four items maximum, icon over a 10px label, muted; active item is `--ink`. A 1px top
divider and safe-area padding. Badges are 16px mint/red dots.

---

## 7. Screen map

| Template | Surface | Pattern |
| --- | --- | --- |
| `landing.html` (`/`) | Light, wide | Public landing: ghost mascot, invite note, three steps, leader panel |
| `stranger_inbox.html` (`/inbox/`) | Light | **Chats**: chat list, search, stories, compose FAB, nav |
| `contact.html` (`/welcome/`) | Light | How it works: three widget rows (steps), privacy note, helpline card |
| `room_entry.html` (`/chatroom/<uuid>/`) | Light | OTP entry: white ghost tile, 4–6 digit boxes, shake on error, success takeover |
| `leader_inbox.html` | Light | Messages: search, stories, metrics, filters, threads, FAB, nav |
| `room_people.html` (`/chatroom/<uuid>/directory/`) | Light | Leader directory: search, skeleton rows, lazily fetched cards with role, bio, Chat |
| `chat.html` | Light | Conversation: header, bubbles, quick replies, composer, sheets |
| `sign_in.html` | Light card | Auth: brand, fields, one primary action |
| `chat_blocked.html` | Light card | Terminal state with helplines |
| `privacy.html` (`/privacy/`) | Light, wide | Privacy policy: short version, sticky contents, lazily painted sections |

`/` is the public landing page. Chats live at `/inbox/` (URL name still `directory`, so
existing links keep working). `/privacy/` is the policy. `/welcome/` is the short
How-it-works page. Codes are only ever typed on a room's own `/chatroom/<uuid>/` page:
the landing page has no code field, because the invitation link already identifies the room.

### Rooms, links and codes

A room is owned by one institution and addressed by its **UUID**:
`/chatroom/<room-uuid>/` is the invitation the organisation shares,
`/chatroom/<room-uuid>/directory/` is the leader directory, and
`/chatroom/<room-uuid>/chat/<leader-uuid>/` starts a conversation. The code itself is
never in the link.

Codes are **4 or 6 digits**, generated by `Room.save()` and editable in Django admin
(blank means “generate one”). `Room.regenerate_code()` and the admin actions issue a new
one. Old `/r/<slug>/...` links 301 to the UUID address. After a correct code the session
can open that room for 12 hours; revisiting the entry URL inside that window goes straight
to the directory.

Entry is a real OTP field: one box per digit, auto-advance, paste support, backspace to the
previous box, shake on failure, mint check plus a success takeover on success. It posts to
the same view and asks for JSON with `X-Requested-With: fetch` so the success animation can
run before navigation. Without JavaScript the boxes are ordinary inputs that post.

### Loading

Skeletons are only used where something actually loads. The directory renders five
`skeleton-row`s, then `directory.js` fetches `.../directory/leaders/` when the list nears
the viewport and swaps in the server-rendered partial (`partials/people_list.html`). A
`<noscript>` copy keeps the directory usable without JavaScript. The OTP form shows a
spinner while the code is being checked. Below-the-fold privacy sections
use `content-visibility: auto` rather than fake placeholders, and leader photos use
`loading="lazy"`.

Brand: **anylink**, lowercase wordmark in Poppins 600 at `-0.055em`, preceded by the ghost
speech-bubble mascot. The ghost is `{% ghost_mark size %}` (filled silhouette, eyes punched
through to `--bg`, two spark strokes at the top right). On light surfaces the ghost is ink;
on dark surfaces it is white. Never put the ghost on an amber tile — the amber belongs to
the compose action.

Copy rules: sentence case everywhere except the tiny kicker; second person; no exclamation
marks except the greeting; never promise confidentiality beyond what the backend does.

---

## 8. Motion & accessibility

- Transitions are 150–200ms `ease-out` and only on colour, background, transform.
- Respect `prefers-reduced-motion`: no scrolling animation, no transforms.
- Never remove focus outlines; `:focus-visible` is a 2px `--accent` ring with 2px offset.
- Body text contrast must stay ≥ 4.5:1; muted text is only used at ≥ 11px for metadata.
- Sheets and banners are announced with `role="status"` / `aria-live="polite"`.
- All icon-only controls need `aria-label`.

---

## 9. Implementation rules

- One stylesheet: `secret/static/secret/app.css`. No utility frameworks, no inline styles
  for colour or spacing (one-off widths inside `style` are tolerated only for dynamic
  progress values).
- Class names follow `block__element--modifier`. Dynamic state classes used by JavaScript
  (`msg-row--mine`, `ticks--read`, `thread--urgent`, `is-active`, `avatar--soft`) are part
  of the contract — do not rename them in templates without updating `chat.js` / `inbox.js`.
- Shared behaviour lives in `secret/static/secret/ui.js`: search filtering, sheet toggles,
  clipboard copy, password reveal, toast. Templates never inline scripts except config
  objects (`window.INBOX_CONFIG`, `chat-config`).
- Icons come from `{% icon "name" size %}`; add new glyphs to `chat_extras.py` rather than
  using emoji or icon fonts.
