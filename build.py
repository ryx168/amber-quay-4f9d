#!/usr/bin/env python
"""Tour 7622 promotion video: narration (OmniVoice) -> plate (ffmpeg) -> composition (HyperFrames).

  python build.py tts        synthesize every narration line into assets/vo/ (cached by text hash)
  python build.py plate      cut the clips/stills into one 1080p30 plate with cross-fades
  python build.py compose    write index.html (timings, subtitles, overlays, audio tags)
  python build.py all        the three above
  python build.py render     npx hyperframes render -> out/tour_7622_promo.mp4

Flags: --force (ignore the TTS cache), --voice clone|design|auto (default auto: clone when
voice/ronnie_ref.wav exists, else design), --quality draft|standard|high (render).

Everything is driven by script.json. Shot timing comes from the narration: a shot lasts
lead + narration + pad (+ the two 0.5 s cross-fades), never shorter than its `min`.
"""
import hashlib, json, os, shutil, subprocess, sys, wave

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
VO = os.path.join(ASSETS, "vo")
BUILD = os.path.join(ASSETS, "build")
OUT = os.path.join(HERE, "out")
for d in (VO, BUILD, OUT):
    os.makedirs(d, exist_ok=True)

SR = 24000
FADE = 0.5            # cross-fade between shots (s)
FPS = 30
W, H = 1920, 1080

SCRIPT = json.load(open(os.path.join(HERE, "script.json"), encoding="utf-8"))
SHOTS = SCRIPT["shots"]
VOICE = SCRIPT["voice"]
REF_WAV = os.path.join(HERE, "voice", "ronnie_ref.wav")
REF_TXT = os.path.join(HERE, "voice", "ref_text.txt")


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


# ---------------------------------------------------------------- narration
def voice_mode():
    m = arg("--voice", "auto")
    if m == "auto":
        m = "clone" if os.path.exists(REF_WAV) else "design"
    if m == "clone" and not os.path.exists(REF_WAV):
        sys.exit("--voice clone but voice/ronnie_ref.wav is missing (run voice_tool.py decrypt)")
    return m


def tts(force=False):
    mode = voice_mode()
    speed = float(VOICE.get("speed", 1.0))
    lang = VOICE.get("language", "zh")
    todo = []
    for s in SHOTS:
        if not s.get("vo"):
            continue
        key = hashlib.sha1(f"{mode}|{lang}|{speed}|{s['vo']}".encode("utf-8")).hexdigest()[:14]
        s["_wav"] = os.path.join(VO, f"{s['id']}_{key}.wav")
        if force or not os.path.exists(s["_wav"]):
            todo.append(s)
    print(f"voice={mode} speed={speed} lang={lang}: {len(todo)} line(s) to synthesize, "
          f"{sum(1 for s in SHOTS if s.get('vo')) - len(todo)} cached")
    if not todo:
        return
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    print("loading k2-fsa/OmniVoice on", device, dtype)
    model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)
    kw = {}
    if mode == "clone":
        ref_text = open(REF_TXT, encoding="utf-8").read().strip() if os.path.exists(REF_TXT) else None
        if ref_text is None:
            model.load_asr_model()      # whisper auto-transcription (large download on CI; ship ref_text.txt instead)
        kw["voice_clone_prompt"] = model.create_voice_clone_prompt(REF_WAV, ref_text=ref_text)
    else:
        kw["instruct"] = VOICE["instruct_fallback"]
    for s in todo:
        audio = model.generate(text=s["vo"], language=lang, speed=speed, **kw)
        sf.write(s["_wav"], audio[0], SR)
        print(f"  {s['id']:10s} {len(audio[0]) / SR:5.2f}s  {s['vo']}")


def trim_silence(path, thresh=500, keep=0.15):
    """Return (start, end) in seconds of the voiced part so timing ignores leading/trailing silence."""
    import array
    with wave.open(path, "rb") as w:
        sr = w.getframerate(); n = w.getnframes(); ch = w.getnchannels()
        a = array.array("h"); a.frombytes(w.readframes(n))
    if ch > 1:
        a = a[::ch]
    n = len(a); i, j = 0, n
    while i < n and abs(a[i]) < thresh: i += 1
    while j > i and abs(a[j - 1]) < thresh: j -= 1
    pad = int(keep * sr)
    return max(0, i - pad) / sr, min(n, j + pad) / sr


# ---------------------------------------------------------------- timing
def timeline():
    """Attach _start/_dur/_vo_start/_vo_dur to every shot. Needs tts() cache to exist."""
    mode = voice_mode()
    speed = float(VOICE.get("speed", 1.0)); lang = VOICE.get("language", "zh")
    t = 0.0
    for k, s in enumerate(SHOTS):
        first, last = k == 0, k == len(SHOTS) - 1
        vo_dur = 0.0
        if s.get("vo"):
            key = hashlib.sha1(f"{mode}|{lang}|{speed}|{s['vo']}".encode("utf-8")).hexdigest()[:14]
            s["_wav"] = os.path.join(VO, f"{s['id']}_{key}.wav")
            if not os.path.exists(s["_wav"]):
                sys.exit(f"missing narration for {s['id']}: run `python build.py tts` first")
            a, b = trim_silence(s["_wav"])
            s["_trim"] = (round(a, 3), round(b, 3)); vo_dur = b - a
        fade_in = 0.0 if first else FADE
        fade_out = 0.0 if last else FADE
        dur = fade_in + s["lead"] + vo_dur + s["pad"] + fade_out
        dur = max(dur, s["min"])
        s["_offset"] = round(t, 3)                 # plate time of this shot's first frame
        s["_dur"] = round(dur, 3)                  # length of this shot's segment in the plate
        s["_vis"] = round(t + fade_in, 3)          # fully visible from here
        s["_vis_end"] = round(t + dur - fade_out, 3)
        s["_vo_start"] = round(t + fade_in + s["lead"], 3) if s.get("vo") else None
        s["_vo_dur"] = round(vo_dur, 3)
        t += dur - fade_out
    total = round(t, 3)
    return total


# ---------------------------------------------------------------- plate
def plate(total):
    inputs, chains = [], []
    for k, s in enumerate(SHOTS):
        src = os.path.join(ASSETS, s["src"])
        d = s["_dur"]; frames = int(round(d * FPS))
        if s["kind"] == "clip":
            ss = s.get("ss", 0.0)
            avail = probe_duration(src) - ss
            if avail < d:                       # too short: slow it down slightly rather than loop
                inputs += ["-ss", str(ss), "-i", src]
                chains.append(f"[{k}:v]setpts=PTS*{d / avail:.4f},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
                              f"crop={W}:{H},setsar=1,trim=duration={d},setpts=PTS-STARTPTS[v{k}]")
            else:
                inputs += ["-ss", str(ss), "-t", str(d + 0.2), "-i", src]
                chains.append(f"[{k}:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                              f"setsar=1,trim=duration={d},setpts=PTS-STARTPTS[v{k}]")
        else:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(d + 0.2), "-i", src]
            zoom = s.get("zoom", "in")
            if zoom == "in":
                z = f"min(1+0.0009*on,1.14)"
            else:
                z = f"max(1.14-0.0009*on,1.0)"
            chains.append(f"[{k}:v]scale=-2:2160,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
                          f"setsar=1,trim=duration={d},setpts=PTS-STARTPTS[v{k}]")
    # cross-fade chain
    prev = "v0"
    for k in range(1, len(SHOTS)):
        off = SHOTS[k]["_offset"]
        out = f"x{k}" if k < len(SHOTS) - 1 else "vout"
        chains.append(f"[{prev}][v{k}]xfade=transition=fade:duration={FADE}:offset={off}[{out}]")
        prev = out
    dst = os.path.join(BUILD, "plate.mp4")
    ffmpeg(*inputs, "-filter_complex", ";".join(chains), "-map", "[vout]", "-an",
           "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-t", str(total), "-movflags", "+faststart", dst)
    print("plate", dst, f"{probe_duration(dst):.2f}s (timeline {total}s)")


# ---------------------------------------------------------------- audio beds
def music(total):
    by_id = {s["id"]: s for s in SHOTS}
    tags = []
    for i, m in enumerate(SCRIPT.get("music", [])):
        a = by_id[m["from"]]["_offset"]; b = by_id[m["to"]]["_vis_end"] + (FADE if m["to"] != SHOTS[-1]["id"] else 0)
        b = min(b, total); dur = round(b - a, 3)
        src = os.path.join(ASSETS, m["src"]); src_dur = probe_duration(src)
        dst = os.path.join(BUILD, f"music_{i}.wav")
        fi, fo = m.get("fadeIn", 0.0), m.get("fadeOut", 1.0)
        filters = []
        if src_dur < dur:                                  # loop the bed to cover the span
            inputs = ["-stream_loop", "-1", "-i", src]
        else:
            inputs = ["-i", src]
        if fi: filters.append(f"afade=t=in:st=0:d={fi}")
        filters.append(f"afade=t=out:st={max(0, dur - fo):.3f}:d={fo}")
        ffmpeg(*inputs, "-t", str(dur), "-af", ",".join(filters), "-ac", "2", "-ar", "48000", dst)
        tags.append(f'<audio id="music-{i}" src="assets/build/music_{i}.wav" data-start="{a}" '
                    f'data-duration="{dur}" data-track-index="{40 + i}" data-volume="{m["volume"]}"></audio>')
    return tags


# ---------------------------------------------------------------- compose
def compose():
    total = timeline()
    if not os.path.exists(os.path.join(BUILD, "plate.mp4")):
        plate(total)
    audio = music(total)
    for s in SHOTS:
        if s.get("vo"):
            a, b = s["_trim"]
            rel = os.path.relpath(s["_wav"], HERE).replace("\\", "/")
            audio.append(f'<audio id="vo-{s["id"]}" src="{rel}" data-start="{s["_vo_start"]}" '
                         f'data-duration="{s["_vo_dur"]}" data-media-start="{a}" data-track-index="30" data-volume="1"></audio>')
    data = dict(total=total, tour=SCRIPT["tour"], fade=FADE,
                shots=[{k: v for k, v in s.items() if k != "_wav"} for s in SHOTS])
    with open(os.path.join(HERE, "timing.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tpl = open(os.path.join(HERE, "tpl", "index.tpl.html"), encoding="utf-8").read()
    html = (tpl.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
               .replace("<!--__AUDIO__-->", "\n    ".join(audio))
               .replace("__TOTAL__", str(total)))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    for s in SHOTS:
        vo = f"vo {s['_vo_start']:6.2f}+{s['_vo_dur']:.2f}" if s.get("vo") else "vo      -   "
        print(f"{s['id']:10s} plate {s['_offset']:6.2f}  vis {s['_vis']:6.2f}-{s['_vis_end']:6.2f}  {vo}")
    print(f"TOTAL {total:.2f}s  -> index.html")


def render():
    q = arg("--quality", "high")
    dst = os.path.join(OUT, "tour_7622_promo.mp4")
    cmd = ["npx", "--yes", "hyperframes@0.5.1", "render", "-q", q, "-w", "2", "-o", dst]
    subprocess.run(cmd, cwd=HERE, check=True, shell=(os.name == "nt"))
    print("rendered", dst, f"{probe_duration(dst):.2f}s")


if __name__ == "__main__":
    steps = [a for a in sys.argv[1:] if not a.startswith("--") and a not in ("clone", "design", "auto", "draft", "standard", "high")]
    if not steps:
        print(__doc__); sys.exit(0)
    if "all" in steps:
        steps = ["tts", "plate", "compose"]
    for st in steps:
        if st == "tts":
            tts(force="--force" in sys.argv)
        elif st == "plate":
            plate(timeline())
        elif st == "compose":
            compose()
        elif st == "render":
            render()
        else:
            sys.exit(f"unknown step {st}")
