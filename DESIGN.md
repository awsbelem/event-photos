---
name: Event Photos — AWS Community Day Norte
description: The event's own agenda, carried on as a living timeline where the photos of each moment hang from its time.
colors:
  navy: "#091b33"
  deep: "#06111f"
  raised: "#11274a"
  raised-hover: "#1a3460"
  rule: "#313453"
  ink: "#ffffff"
  muted: "#c4d0e6"
  orange: "#fb8617"
  orange-hover: "#ff9a3d"
  violet: "#5446e1"
  lavender: "#8365c7"
  good: "#4cc38a"
  bad: "#ff6b6b"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "clamp(42px, 11.5vw, 84px)"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.04em"
  time:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "34px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  time-wide:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "44px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  headline:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  headline-wide:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "24px"
    fontWeight: 800
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  lead:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 600
  label:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.04em"
    fontFeature: "tnum"
  code-entry:
    fontFamily: "ui-monospace, SFMono-Regular, monospace"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.1em"
rounded:
  pill: "7px"
  tile: "8px"
  row: "10px"
  control: "12px"
  panel: "14px"
  dialog: "16px"
spacing:
  tile-gap: "6px"
  tile-gap-wide: "8px"
  inline: "12px"
  gutter: "20px"
  moment: "40px"
  moment-wide: "56px"
  container: "1200px"
components:
  button-primary:
    backgroundColor: "{colors.orange}"
    textColor: "{colors.navy}"
    typography: "{typography.lead}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "52px"
  button-primary-hover:
    backgroundColor: "{colors.orange-hover}"
    textColor: "{colors.navy}"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "52px"
  button-secondary-hover:
    backgroundColor: "{colors.raised-hover}"
    textColor: "{colors.ink}"
  icon-button:
    backgroundColor: "#ffffff14"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    size: "48px"
  pill-count:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  banner:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.row}"
    padding: "7px 14px"
  photo-tile:
    backgroundColor: "{colors.raised}"
    rounded: "{rounded.tile}"
  schedule-row:
    textColor: "{colors.ink}"
    rounded: "{rounded.row}"
    padding: "0 8px"
    height: "52px"
  schedule-row-current:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
  frame-option:
    textColor: "{colors.muted}"
    rounded: "{rounded.row}"
    height: "44px"
  frame-option-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.navy}"
  input-code:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    typography: "{typography.code-entry}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
    height: "56px"
  dialog:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.dialog}"
    padding: "22px"
  toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.navy}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
---

# Design System: Event Photos — AWS Community Day Norte

## Overview

**Creative North Star: "A Programação Viva"**

The gallery is the official "Momentos do dia" agenda slide of AWS Community Day Brasil — Edição Norte, carried on past the slide. Every time on the schedule is a node on one vertical timeline, and the photos of that moment hang from it. The visitor recognizes the event's own artwork first (navy ground, the official logo lockup, isometric hexagon cubes in the top corners, orange times beside hexagon nodes), then sees the day fill in with photos. The page closes on the Belém skyline with the orange sun, as the artwork does. With every photo removed the page still reads as this event: navy, an orange-time timeline, hexagon nodes.

Every visual decision traces to the official artwork (`assets/frames/aws-community-day-belem/source-agenda.jpg`, `header.png`, `footer.png`). Colors were sampled from the agenda slide. The hexagon corners and skyline are cut from the official header and footer, never redrawn. The typeface is Inter, a stand-in for the artwork's unconfirmed face. The system is built for this one event and is not a white-label. The photos are the content, and the artwork frames the page around them without competing with them.

The density is calm and vertical. There is one column and one timeline. Photo grids are square-cropped and edge-to-edge within the column. On wide screens the column gains a 200px time rail to the left. Motion is limited to the timeline: nodes and the rule light orange as the day is scrolled.

The page and the upload page are each a single self-contained file. The gallery inlines every asset (font, logo, hexagons, skyline) as a data URI. The upload page gets the same assets baked into its Lambda source at deploy. Neither page loads anything from a third party.

**Key Characteristics:**
- Navy ground (#091b33) edge to edge, sampled from the official agenda slide.
- One vertical timeline of pointy-top hexagon nodes, with a monumental orange time per moment.
- Orange calls (times, the primary action, lit nodes, links, focus), and white is for reading.
- A violet pill marks photo counts and the demo or notice banner, and nothing else.
- Official artwork (logo, hexagon cubes, Belém skyline) is used as supplied, inlined.
- The whole schedule stays visible, including moments with no photos.
- Photo frames keep the cd-norte plum brand kit, and the page around them does not.

## Colors

A deep-navy night with two hot accents taken from the event's own agenda: AWS orange that calls and a violet that tags.

### Primary
- **Agenda Orange** (`orange`): the calling color. Used for moment times, the primary button ("Encontrar minhas fotos", "Baixar foto", "Escolher fotos"), lit timeline nodes and the lit rule, link underlines, the copy-handle button, the focus ring, the spinner arc, the upload progress fill, text selection and `accent-color`. On the primary button its text is navy, never white. **Orange Glow** (`orange-hover`) is its hover state only.

### Secondary
- **Pill Violet** (`violet`): the tag color. It fills two things only: the photo-count pill beside a moment title ("4 FOTOS") and the banner that labels a demo or notice ("Demonstração: fotos de outros eventos (Wikimedia Commons), não do CD Norte"). Text on it is white.

### Tertiary
- **Keynote Lavender** (`lavender`): fills and strokes the hexagon node of keynote moments (titles starting "Keynote"), on the timeline and in the schedule list, as on the official agenda. A lit keynote keeps its lavender fill and gains an orange stroke.

### Neutral
- **Agenda Navy** (`navy`): the page ground, `theme-color`, the schedule dropdown, the inside of outline nodes, and text on orange and white surfaces.
- **Viewer Deep** (`deep`): the full-screen photo viewer's ground, one step darker than the page so the photo sits in the darkest field. It is also the base of the dialog scrim (`#06111fd9`) and the viewer arrow plates (`#06111fb3`).
- **Raised Navy** (`raised`): controls and containers above the ground. Used for secondary buttons, the frame chooser track, dialogs, the to-top button, the current or hovered schedule row, the code input, and the placeholder behind a loading photo tile. **Raised Hover** (`raised-hover`) is its hover state only.
- **Timeline Rule** (`rule`): the unlit timeline line, the hairlines under the now bar and above the footer, list dividers, input and consent borders, and the empty progress track.
- **Reading White** (`ink`): headings, moment titles and body text. It is also the selected frame option's fill and the toast fill, both with navy text.
- **Support Blue-Gray** (`muted`): dates and venue, photo counts in the schedule, viewer position ("5 de 42"), footer prose, unselected frame options, upload tips.

### Status (upload page only)
- **Sent Green** (`good`) and **Failed Red** (`bad`): the per-file upload status ("enviada", "O envio falhou.") and the login error. In-flight files are orange and queued files muted.

### Named Rules
**The Call-and-Read Rule.** Orange calls and white is for reading. This rule comes from the official brand kit and is binding. Orange marks what to act on or where you are: times, the primary action, lit nodes, links and focus. All reading text is white or support blue-gray, never orange.

**The Violet Tag Rule.** Violet appears only as a filled tag: the count pill and the notice banner. It never fills a button or a heading, and it never sits above a heading as a kicker.

**The Plum Stays Framed Rule.** The cd-norte plum kit (`assets/brand/cd-norte/brand.json`: plum #42314B, lavender cards, sunset gradients, IBM Plex Sans, Permanent Marker) lives only inside the photo frames, by the user's decision. The page around the frames uses the agenda palette above and never borrows a plum token.

## Typography

**Display Font:** Inter, variable 400–800, Latin subset, inlined (with system-ui, -apple-system, Segoe UI, Roboto, sans-serif)
**Body Font:** Inter (same stack)
**Label/Mono Font:** ui-monospace, SFMono-Regular, monospace, only for the photographer's invite-code field

**Character:** One family at heavy weights with tight tracking, matching the agenda slide's bold grotesque. Inter stands in for the official artwork's face until the organizers confirm it. Every number that counts or tells time uses tabular figures, so times and counts line up down the timeline.

### Hierarchy
- **Display** (800, `clamp(42px, 11.5vw, 84px)`, 0.98, -0.04em, balanced): the page heading only, "Momentos do dia". The upload page's "Enviar fotos" uses the same voice at `clamp(40px, 11vw, 60px)`, line-height 1.
- **Time** (800, 34px narrow / 44px from 860px, line-height 1, -0.03em, tabular, orange): the monumental time of each moment. The now bar repeats it at 19px and the schedule list at body size, both orange and 800.
- **Headline** (700, 22px narrow / 26px from 860px, 1.25, -0.015em): the moment title on the timeline, for example "Intervalo para almoço".
- **Title** (800, 22–24px, -0.02em): dialog headings ("Encontrar minhas fotos"), the selfie-result bar ("Encontramos 6 fotos com você"), and the upload greeting ("Olá, Ana Souza!").
- **Body** (400, 16px, 1.5): gallery text. The lead line under the display heading and the whole upload page run at 17px. Footer prose is capped at 68ch.
- **Meta** (600, 14px, muted): "Programação", schedule counts, the viewer's "N de M", and the tag line under the viewer controls.
- **Label** (700, 12px, 0.04em, uppercase, tabular, white on violet): the count pill only.

### Named Rules
**The Monumental Time Rule.** Each moment's time is the largest type in its row: orange, weight 800, tabular figures. Moment titles stay white and smaller.

**The One Family Rule.** Inter carries every role. The monospace face appears only where a typed code must be read character by character.

## Layout

One centered column, 1200px max, with a 20px gutter. The masthead is centered: the official logo lockup at `clamp(230px, 62vw, 340px)`, then the heading, the date and venue line, the photo-count line, the optional banner, and the selfie button (full width up to 360px). Each fact in the date line is kept whole (`white-space: nowrap`), and only the separators wrap.

**The timeline.** Below 860px each moment is a two-column grid: a 28px node column and the content, 12px apart. The time sits beside the node, and the title and photos sit under the time. From 860px the moment becomes three columns: a 132px time, a 32px node and the content, 18px apart. The photos start 200px in, so the times form a rail to the left of every grid. A 2px rule runs from node to node, centered on the node column, and stops at the last moment. Moments are 40px apart (56px from 860px). Moments without photos stay as bare rows with a dimmed time and 30px spacing.

**Photo grids.** Square tiles in an auto-fill grid: at least 140px wide with 6px gaps, and from 700px at least 210px wide with 8px gaps. Tiles are built in batches of 60 as the page scrolls, and the space they will fill is reserved so jumps land correctly.

**Sticky now bar.** A 60px bar under the masthead stays at the top of the screen. It shows a node, the current moment's time and title, and "Programação" with a chevron that opens the full schedule as a dropdown list. Anchor jumps leave 72px of scroll padding for it.

**Footer.** A hairline rule, then credits, the removal contact, an optional notice and collapsible photo credits. The skyline closes the page. It bleeds to the screen edges on narrow screens and is capped at 1080px. From 1120px it is centered with its sides faded out by a mask. That fade covers for the 1080px raster: a skyline at least 2160px wide is still pending.

**Upload page.** A single 560px column with the same masthead artwork, 56px tall full-width controls, a tips list under a hairline, and the skyline at the foot (600px max, centered from 640px).

**Breakpoints:** 640px (upload skyline), 700px (grid density), 860px (timeline rail and type step-up), 1120px (skyline fade), and `hover: none` (the viewer's arrow buttons are hidden on touch devices, where swiping replaces them).

### Named Rules
**The Whole Day Rule.** The timeline shows the complete schedule. A moment with no photos keeps its time, node and title as a bare row, so the day reads in order. Only the selfie search hides moments, and only those without the visitor.

## Elevation & Depth

Depth comes from tonal layers of the same navy. The viewer is darkest (`deep`), the page sits on `navy`, and controls rise to `raised`. Shadows appear only on things that float over the page: the schedule dropdown, the selfie dialog, the to-top button and the toast. The now bar uses translucency and a 14px backdrop blur over 90% navy, not a shadow. Resting surfaces such as tiles, buttons and pills cast no shadow.

### Shadow Vocabulary
- **Dropdown** (`box-shadow: 0 24px 48px #0008`): the schedule list hanging from the now bar.
- **Dialog** (`box-shadow: 0 24px 64px #0009`): the selfie-search dialog box over its `#06111fd9` scrim.
- **Floating control** (`box-shadow: 0 8px 24px #0009`): the to-top button. The toast uses the same geometry at `#000a`.

### Named Rules
**The Overlay-Only Shadow Rule.** A shadow means "this floats over the page." Nothing at rest gets one, and none are hard or offset.

## Shapes

The hexagon is the system's one geometric form, and it is pointy-top, as on the agenda's timeline (`M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z` on a 24 grid). An outline hexagon (navy fill, 2.4 orange stroke) is a moment not yet reached. A filled hexagon is a lit moment or a keynote. The same shape, as a CSS mask, marks upload status (outline while waiting or sending, filled when sent or failed) and bullets the upload tips. The isometric hexagon cubes in the top corners are raster artwork cut from the official header. They sit flush against the top edge at `clamp(28px, 7.8vw, 84px)` on the left and `clamp(60px, 16.7vw, 180px)` on the right.

Rectangles are softly rounded and get rounder as they get bigger or more interactive: 7px for the count pill, 8px for photo tiles, 10px for the banner, schedule rows and frame options, 12px for buttons, inputs, the consent card and the camera preview, 14px for icon buttons, the frame chooser track and the to-top button, and 16px for the dialog. Photos are always cropped square in the grid and shown whole (`object-fit: contain`) in the viewer.

### Named Rules
**The Hexagon Marker Rule.** Every marker, whether a node, status or bullet, is the pointy-top hexagon. Dots, discs and checkmarks are not used.

## Components

### Buttons
Solid and tactile: full-height blocks that press in slightly.
- **Shape:** gently rounded (12px). Height 52px in the gallery and 56px on the upload page. Text is weight 700.
- **Primary:** orange fill with navy text. There is one per view: "Encontrar minhas fotos", "Salvar ou postar" (or "Baixar foto" where files cannot be shared), "Abrir câmera", "Continuar", "Escolher fotos".
- **Hover / Focus:** the fill shifts (orange to `orange-hover`, raised to `raised-hover`) over 0.2s. Pressing scales to 0.98. Focus shows a 2px orange outline 3px out (3px wide on the upload page). Disabled buttons drop to 55% opacity.
- **Secondary:** raised navy fill with white text ("Baixar arquivo", "Cancelar", "Ver todas as fotos"). On the upload page, "Tentar de novo" adds a 1px rule border that turns orange on hover.
- **Quiet:** a text button with an orange underline ("Trocar código"; "@awscommunitydaynorte" in orange for copying the handle).
- **Icon button:** 48px with a 14px radius, on a translucent white plate (`#ffffff14`, `#ffffff26` on hover). It holds an authored 2px-stroke SVG (close, previous, next, up). The to-top button is a 52px raised plate with an orange arrow.

### Chips
- **Count pill:** violet with white uppercase 12px tabular text ("2 FOTOS"), 7px radius, inline after the moment title. It is hidden when the moment has no photos.
- **Banner:** violet, white 14px bold sentence case, 10px radius, sized to its content. It is used for the demo label or an event notice under the masthead.

### Cards / Containers
- **Photo tile:** square, 8px radius, raised-navy placeholder while loading. On hover the image scales to 1.04 inside the clip over 0.35s.
- **Dialog:** raised navy, 16px radius, 22px padding, 460px max, over a deep-navy scrim. The consent option inside is a navy card with a 1px rule border that turns orange when checked.
- **Toast:** white with navy 15px/600 text, 12px radius. It rises 8px into place and is used for confirmations ("@awscommunitydaynorte copiado. Cole na legenda ao postar.").

### Inputs / Fields
- **Code input (upload page):** 56px, raised navy, 1px rule border, 12px radius. Monospace 22px/600, uppercase, 0.1em tracking, orange caret, placeholder "XXXX-XXXX" in `#8a9bbb`.
- **Focus:** the border turns orange.
- **Error:** a red 600-weight line under the action ("Código não reconhecido. Confira com quem te convidou.").

### Navigation
- **Now bar:** sticky, translucent navy with blur and a bottom rule. Before the first moment it reads "Ir para um momento" in muted 600. Once a moment is reached it shows that moment's node, orange 19px time and white 700 title, with an ellipsis if the title is too long. "Programação" with a chevron that rotates 180° when open sits on the right.
- **Schedule list:** opens below the bar (72vh / 600px max, scrolls). Each 52px row has a time (orange, 800, tabular), a 20px hexagon node (lavender for keynotes), the title and the muted photo count. The current row and the hovered row get a raised fill. Choosing a row jumps to the moment and closes the list.

### Timeline Moment (signature)
The repeated unit of the page: time, hexagon node, title with count pill, then the photo grid. As the visitor scrolls, a moment whose top passes 60% of the screen lights up. Its node fills orange (0.45s), the rule below it turns orange (0.6s), and the node pops to 1.18× for 380ms. Scrolling back up unlights it. Keynote nodes are lavender, filled at rest and orange-stroked when lit. A moment without photos keeps its row with the time dimmed (orange mixed 70% into navy). All of this uses `cubic-bezier(.16,1,.3,1)`, and reduced motion turns it off.

### Photo Viewer
Full screen on viewer deep. The top line shows the moment's time in orange, its title and "N de M · Foto: [nome]" in muted text. The photo is centered and contained, and a spinner (orange arc on a faint white ring) appears after 0.15s of loading. Below is a 560px control stack. The frame chooser is a segmented control on a raised track: each option shows its frame swatch with the current photo drawn into the frame's window, then "Sem moldura" last. The selected option is white with navy text. Below that are the actions row and "Ao postar, marque @handle". The frames themselves are the plum cd-norte designs.

### Upload Status List (upload page)
Rows split by rule hairlines: file name on the left (truncated) and a hexagon status marker with its word on the right. Statuses are muted "na fila", orange "enviando…", green "enviada" and red failure text. An 8px progress bar (rule track, orange fill) and the summary "2 de 5 enviadas · 1 com falha" sit above the rows.

## Do's and Don'ts

### Do:
- **Do** sample new colors from the official agenda artwork and add them as tokens. The page palette is navy, orange, violet, lavender, white and support blue-gray.
- **Do** keep orange for calling and white for reading (The Call-and-Read Rule): times, the primary action, lit nodes, links and focus are orange, and all reading text is white or `muted`.
- **Do** set every time and count in Inter 800 or 700 with tabular figures.
- **Do** use the pointy-top hexagon for every node, status and bullet, with an outline for pending and a fill for reached or done.
- **Do** keep the whole schedule on the timeline, with photo-less moments as bare rows.
- **Do** inline every asset as a data URI so each page stays one self-contained file, and record each raster's provenance in `assets/web/README.md` and its `.json` sidecar.
- **Do** use the official artwork (logo lockup, hexagon cubes, skyline) as supplied, cut from the source files, never redrawn.
- **Do** keep touch targets at 44px or more, keep a visible orange focus ring, and turn motion off under `prefers-reduced-motion`.
- **Do** label demonstration content with the violet banner.

### Don't:
- **Don't** put an eyebrow or kicker pill above a heading. The violet pill marks photo counts and the demo or notice banner only.
- **Don't** set body text, moment titles or headings in orange.
- **Don't** bring the plum brand-kit colors, gradients or fonts onto the page. They stay inside the photo frames.
- **Don't** use violet for buttons, headings or anything that isn't a tag.
- **Don't** hide moments without photos outside the selfie-search result.
- **Don't** add shadows to resting surfaces, and don't use hard or offset shadows anywhere.
- **Don't** use glyph or emoji icons. Icons are authored 2px-stroke SVGs and markers are hexagons.
- **Don't** load fonts, images or scripts from third-party hosts.
- **Don't** apply this system to the internal tools (`review.py`, `report.py`). They are outside it.
