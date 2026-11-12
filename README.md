# Tour 7622 promo — 愛爾蘭與英倫 11 天精華之遊 (盛世公主號)

A 70-second promotion video for XO Tours' Ireland & Britain cruise, rendered entirely on
GitHub Actions. Nothing here needs a workstation or a GPU:

| stage | tool | what it does |
|---|---|---|
| narration | [OmniVoice](https://github.com/k2-fsa/OmniVoice) (k2-fsa, Apache-2.0), CPU | every line in `script.json` is spoken in the presenter's cloned voice (zero-shot, from a 15 s reference clip) — or, without the key, in a designed voice |
| plate | ffmpeg | the AI port clips and brochure stills are cut to the narration length, Ken-Burns'd and cross-faded into one 1080p30 plate |
| overlays + mix | [HyperFrames](https://hyperframes.heygen.com) 0.5.1 | title card, anniversary burst, "全包" pills, port labels, the $4099 poster, bilingual-free Traditional-Chinese subtitles, voice + music mix |
| output | release | `out/tour_7622_promo.mp4` is attached to a release tagged `run-<number>` and uploaded as an artifact |

## Run it

* **Push to `main`** (any change to `script.json`, `build.py`, `tpl/`, `assets/`, `voice/`) renders at high quality.
* **Actions → render → Run workflow** lets you pick `quality` (draft / standard / high),
  `voice` (`auto` / `clone` / `design`) and `force_tts`.

First run: ~25 min (3.3 GB checkpoint download + CPU synthesis + render). Later runs reuse the
cached checkpoint and the cached narration (keyed on `script.json` + `voice/`), so a text or
layout change re-renders in ~8 min.

## The voice

`voice/ronnie_ref.wav.enc` is the presenter's reference recording, AES-256 encrypted
(`openssl enc -aes-256-cbc -pbkdf2`). The passphrase is the repository secret **`VOICE_KEY`**.
With the secret present the workflow clones that voice; without it, `build.py` falls back to
OmniVoice *voice design* using `voice.instruct_fallback` in `script.json`, so a fork still renders.

```
python voice_tool.py encrypt --key-file /path/to/key.txt   # re-encrypt a new reference clip (creates the key file if missing)
python voice_tool.py decrypt --key-file /path/to/key.txt   # local decrypt
```

The passphrase file is kept outside every repository (on the owner's PC:
`%USERPROFILE%\.config\amber-quay-4f9d\VOICE_KEY.txt`). Lose it and the `.enc` is unreadable;
re-run `encrypt` from the original recording with a new key and update the secret.

`assets/vo/*.wav` are the synthesized lines, committed so a layout-only change does not
re-synthesize (CPU OmniVoice runs at roughly a minute per second of speech on a 4-core runner).
The file name carries a hash of voice mode + text, so editing a `vo` line in `script.json`
regenerates just that line on the next run.

`voice/ref_text.txt` is the transcript of the reference clip; shipping it avoids a 1.5 GB
Whisper download on the runner.

## Edit the video

Everything is data in `script.json`:

* `shots[]` — order, `kind` (`clip` | `still`), `src`, the narration line `vo`, the on-screen
  `sub`, an optional port `label` ("中文 English"), `overlay` (`cover` | `anniv` | `includes` | `price`),
  `min` seconds, `lead`/`pad` around the narration, `ss` (clip in-point), `zoom` (`in` | `out`).
* `music[]` — beds with `from`/`to` shot ids, `volume`, `fadeIn`/`fadeOut`.
* `tour` — the texts the poster and cover print.

Shot length = cross-fades + lead + spoken length + pad, never below `min`, so the cut follows the
narration automatically.

## Run locally

```
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install omnivoice soundfile
python voice_tool.py decrypt --key-file key.txt   # optional
python build.py all        # tts -> plate -> index.html
npx hyperframes@0.5.1 lint
npx hyperframes@0.5.1 render -q high -w 2 -o out/tour_7622_promo.mp4
```

Needs ffmpeg and a CJK font (Noto Sans CJK TC on Linux, Microsoft JhengHei on Windows).

## Assets

* `assets/clips/` — AI-generated port and ship clips (Gemini / Veo) made for this tour
* `assets/photos/` — brochure photos
* `assets/music/` — jingles generated with Suno for this campaign (`intro_vocal` is the
  Auld-Lang-Syne-themed 32nd-anniversary song)
* `assets/presenter/` — presenter cut-out and the booking QR code
