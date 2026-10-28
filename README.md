# event-photos

Photo delivery for community events, built for AWS Community Day Brasil — Edição Norte (Belém, 2026).
The attendee-facing pages (gallery, upload page, review) are in Portuguese; code and docs are in English.

## How it works

1. **Photographers upload** from their phones through a private page, each with a personal code.
2. **One command** pulls the uploads and culls them (blur, closed eyes, bursts and retakes), develops them
   (phone rendering + a learned FiveK LUT) and frames them in the event's brand (4:5 feed, 9:16 story,
   face-aware crop).
3. **The operator reviews** the selection on a local page and approves it.
4. **A static gallery goes live** (S3 + CloudFront), grouped by the event's schedule, crediting each
   photographer; attendees save a photo or post it with the frame they pick.
5. **Attendees find themselves** by scrolling or, optionally, with a selfie (Amazon Rekognition).

Everything runs on the CPU (no GPU). Inputs: DNG (incl. Apple ProRAW), HEIC, JPEG; larger photos (48 MP
phones) are processed and delivered at 4032 px on the long side, which keeps each worker near 1 GB.

## Setup

Python 3.12+, [uv](https://docs.astral.sh/uv/) and `exiftool` (or only Docker, see
[Docker](#docker)). The models are not versioned; put them in `models/`:

```bash
mkdir -p models
curl -L -o models/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl -L -o models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

plus the two FiveK files (see [Auto-enhancement](#auto-enhancement-fivek-adaptive-3d-lut)).
`uv run pytest` runs the tests. Face handling in the pipeline is detection + landmarks only; identity
matching exists only in the optional face search.

## Running an event

```bash
uv run event-photos event <slug>             # pull uploads → process → review on 127.0.0.1 → gallery in out/
uv run event-photos event <slug> --publish   # same, then publish (and index faces when face search is on)
uv run event-photos event <slug> --publish --skip-review   # reuse the last approved review
```

`events/<slug>/event.json` describes the event: `name`, `date`, `place`, `accent`, `aws_stack`; optional
`heading` (the gallery's title, default `name`), `schedule` (gallery sections by moment), `photographer`, `instagram`, `frames` (folders in
`assets/frames/`, the first is the default), `aws_profile` (default `event-photos`), `timezone` (default
`America/Belem`), `clock_offsets` (e.g. `{"ana-souza": "-0:05"}` for a camera clock that was off),
`strength`, `face_search`, `removal_contact`, `pages_project`.

Values that must not be versioned — the removal contact, whether face search is on — go in
`events/<slug>/event.local.json` (gitignored), which overrides event.json key by key; `face-search
enable|disable` writes there. This repository runs three events this way: the official one and two
rehearsals (team training, speakers' dinner).

Re-runs only process new photos, and the review lists the photos that arrived since the last approval
first, marked "Nova", with the ones already reviewed folded below. Output in `out/events/<slug>/`: `uploads/`,
`run/` (report, review), `site/` (the gallery), `instagram/` (approved frames, ready to post).

A gallery left open sees the next publish: while it is on screen it checks `photos.json` (published beside the
page, never cached) every minute and offers "N fotos novas · Ver", which reloads the page at the first new photo,
with the new ones marked "Nova" for a few seconds.

## AWS

### Gallery and upload page

`infra/aws-gallery.yaml` (us-east-1), one stack per event named `event-photos-<slug>`: a private bucket
behind CloudFront (noindex, no framing), an upload inbox bucket whose uploads expire after 30 days, the
upload page (a Lambda URL that hands out one-file upload permissions), a logs bucket for the event report,
and a publisher policy that can only publish this gallery, collect this inbox and read these logs.

**Counts for the event report.** The gallery requests `e.gif?e=<action>` when a visitor opens the gallery or a
photo, picks a frame, saves, shares, copies the @ or ends a selfie search (only the size of the result, in
ranges). CloudFront's access log (standard logging v2, JSON, kept 90 days) records date, time, path, query,
status, bytes, edge, cache result and User-Agent; never the viewer's IP, port or cookies, and the page keeps no
identifier, so the counts are of actions, not people. The footer says so. Logging starts when the stack is
deployed, so update the stacks before the event.

Create the stacks from AWS CloudShell with `scripts/cloudshell_event_stacks.sh` (gallery and face search,
for several events at once; see its header). With `PUBLISHER_USER=<an existing publisher>`, new events
are granted to that IAM user (`PublisherUser` parameter of both templates), so one access key, stored
with `aws configure --profile event-photos`, runs every event. To take an event down, empty its three
buckets and delete its stacks. (`pages_project` publishes to Cloudflare Pages instead, without the upload page or
face search.)

### Photographers

```bash
uv run event-photos inbox <slug> deploy                        # once per event and after editing inbox_app.py
uv run event-photos photographers <slug> add "Ana Souza"       # prints the code and the page link
uv run event-photos photographers <slug> add-file team.txt     # one name per line; known names are skipped
uv run event-photos photographers <other> copy <slug>          # same codes on another event
uv run event-photos photographers <slug> list | remove "Ana Souza"   # remove revokes at once
```

Each upload page shows its event's name. A photographer keeps one code across events, but the page
decides where a photo lands, so send the link of the event at hand, one at a time. Photos are stored as
`<photographer slug>--<file>` (two phones' `IMG_1234` never collide) and credited in the gallery. Send the
RAW or the JPEG of a shot, not both. The machine running `event` is never reached from outside: it pulls
the inbox.

## Face search

Optional and off by default. An attendee takes a selfie in the gallery and sees only the photos they are
in. It processes biometric data, so it is gated on a written legal sign-off.

**Privacy by design**
- Collection, search function, rate-limit table and deletion schedule live in **sa-east-1**.
- The gallery asks for explicit consent, uses the live front camera only and sends a 640 px JPEG; the
  selfie is compared and discarded, never stored or logged (logs hold platform lines only, kept 7 days).
- Rate limits key on a salted hash of the caller's IP, never the IP itself, and expire on their own.
- Photos marked "Tem menor de idade (fora da busca)" in the review are never indexed.
- The collection is deleted on a schedule (event date + `retention_days`, default 30) and on demand.
- `face-search enable` refuses to run without `legal_ok` (date of the legal sign-off) and
  `removal_contact`, and asks to confirm the account's AI services opt-out policy.

**Setup:** the face search stack (`infra/aws-face-search.yaml`, sa-east-1, `event-photos-<slug>-faces`,
created by the CloudShell script) and `"face_search": {"stack": "event-photos-<slug>-faces",
"legal_ok": "<date>"}` in event.json. The review then shows faces per photo and the minors toggle.

```bash
uv run event-photos face-search <slug> enable --confirm-ai-opt-out   # deploys the search, creates the
                                                                      # collection, schedules its deletion
uv run event-photos event <slug> --publish                            # indexes faces, shows "Encontrar minhas fotos"
uv run event-photos face-search <slug> status | disable | purge       # purge deletes the collection now
```

**Limits:** 5 searches a minute and 30 an hour per caller (an IPv4 address, or an IPv6 /64) and
`GLOBAL_LIMIT` (2000) an hour in all. Matches need 95 % similarity: no wrong matches is the priority, so
faces in profile or very small in the frame are often missed, and the schedule sections stay the fallback.
Cost: about US$ 0.0013 per photo indexed and per face count in the review, US$ 0.0026 per search
(sa-east-1 list prices, 2026); set an AWS Budgets alert.

## Processing on AWS

The events run on one EC2 instance next to the galleries (`infra/aws-processing.yaml`, us-east-1, stack
`event-photos-processing`), reached only through SSM Session Manager: no inbound port, no ssh key, and the
instance works through a role, so no access key lives on it. The events' publisher key, on the operator's
notebook, may operate that instance and nothing else. A private work bucket holds what git does not: the
models, each `event.local.json` and each event's `out/` state, saved at the end of every round.

**Setup**, once, after the event stacks: upload `infra/aws-processing.yaml` to CloudShell and run
`PUBLISHER_USER=<the events' iam user> bash cloudshell_processing_stack.sh <slug>...` with every event
(again whenever an event is added). Then, on the notebook, with the AWS CLI, the
[Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
and the `event-photos` profile:

```bash
scripts/aws.sh setup                          # models and event.local.json to the bucket, Docker image
scripts/aws.sh size c7i.4xlarge c7a.4xlarge   # stop, resize, start (the next type if the first is not free)
scripts/aws.sh run <slug>                     # a round: open the review link it prints; --no-publish to only build
scripts/aws.sh attach                         # the connection dropped: back into the same round
scripts/aws.sh status | stop | shell
```

The instance runs the `stable` branch, which CI (`.github/workflows/ci.yml`: tests, `cfn-lint`, `shellcheck`,
the image) fast-forwards to `main` once `main` is green, so a failing commit never reaches an event.
The round runs in `tmux` on the instance, so a dropped connection does not stop it; `run` and `attach`
open the review tunnel themselves (local port 8766). `.env` on the instance follows its size (one worker per
physical core with about 1.2 GB each). An alarm stops the instance after two idle hours; `run` starts it
again. `event.local.json` is edited on the notebook (`face-search` runs there too) and sent on every `run`.

**Sizes:** c7i.large (2 vCPU, US$ 0.09/h, about 6.5 s per photo) for small events; c7i.4xlarge (16 vCPU,
US$ 0.71/h, 8 workers) when photos arrive by the thousand. Cost is hours on × size, so size it for the day.

**On this machine instead** (fallback): `scripts/aws.sh pull-state <slug>`, run `event` here, then
`scripts/aws.sh push-state <slug>`; the next round on the instance takes that state with `run <slug> --restore`.

### Docker

`Dockerfile` packs the CLI with exiftool, the AWS CLI and the models (base images pinned by digest);
`compose.yaml` runs it as a one-shot command limited to 1.5 GB and 1.5 CPU with one worker by default (peak
1.2 GB per worker). On a bigger machine, copy `.env.example` to `.env` next to `compose.yaml` and raise
`EVENT_PHOTOS_WORKERS`, `EVENT_PHOTOS_MEMORY` (workers × 1.2 GB or more) and `EVENT_PHOTOS_CPUS`;
`EVENT_PHOTOS_MAX_LONG_SIDE=0` keeps photos at their original size. `.env` is gitignored, so each machine
keeps its own. The review port is published on the host's 127.0.0.1 only; `~/.aws` is mounted read-only; the
host user needs uid 1000. `EVENT_PHOTOS_WORKERS` and `EVENT_PHOTOS_REVIEW_HOST` also work outside Docker.

## Security notes

- The review page lives under a random token and answers only to `127.0.0.1`/`localhost` with JSON
  posts, so no other site open in the browser can read it or approve a selection.
- Gallery, upload page and search refuse to be framed by other sites; the gallery is noindex.
- Neither Lambda function has reserved concurrency: on accounts with the default quota of 10, any
  reservation fails the stack. With a higher quota, adding `ReservedConcurrentExecutions` bounds a flood
  further.
- After the event, delete the publisher's access key (`aws iam delete-access-key`), or the stacks; the
  processing stack's work bucket must be emptied first (it keeps old versions for a week).

## Frames

Folders in `assets/frames/`, listed in event.json as `"frames": [...]`; attendees switch between them in
the gallery. Either strips (`header.png`, `footer.png`, optional `frame.json` with `background`,
`accent`) or layered (`frame.json` with `label` and, per format, the photo `box`, `radius`, `border`;
`<format>-bg.png` under the photo, optional `<format>-fg.png` over it, `swatch.png` for the chooser).
`scripts/make_frames_cd_norte.py` draws the three AWS Community Day Norte frames from the brand kit in
`assets/brand/cd-norte/`.

## Auto-enhancement (FiveK adaptive 3D LUT)

`models/fivek_lut_classifier.onnx` and `models/fivek_lut_basis.npy` are exported from
[Image-Adaptive-3DLUT](https://github.com/HuiZeng/Image-Adaptive-3DLUT):

    git clone --depth 1 https://github.com/HuiZeng/Image-Adaptive-3DLUT /tmp/ext/Image-Adaptive-3DLUT
    cd /tmp/ext/Image-Adaptive-3DLUT && uv run --no-project --with torch --with onnx \
      --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
      python <repo>/scripts/export_fivek_lut.py   # then copy /tmp/ext/lut_* to models/

The pipeline also runs on any folder: `uv run event-photos run <input> <output> --strength 0.7`.
Blind comparison of treatments: `uv run python scripts/blind_compare.py <photos> <run dir> <out dir>`.

## License and credits

MIT (see `LICENSE`). Models: YuNet face detector (OpenCV Zoo), MediaPipe Face Landmarker,
Image-Adaptive-3DLUT (Apache-2.0). Fonts in `assets/brand/cd-norte/fonts/`: IBM Plex Sans and
Permanent Marker (SIL Open Font License 1.1).
