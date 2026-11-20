"""Pronunciation check for synthesized narration.

OmniVoice samples randomly: the same line can come out clean on one take and slurred on the
next (measured 2026-11-20: three takes of one line ranged from 2 to 4 wrong syllables out of 17).
So build.py synthesizes up to N takes per line, transcribes each with Whisper, and keeps the take
whose *pinyin* is closest to the script.

Pinyin, not characters: Whisper writes homophones freely (貝/背, 爾/耳) and mixes simplified and
traditional script, neither of which is a pronunciation error. Numerals are dropped from both
sides because Whisper writes 三十二 as 32.
"""
NUMERALS = set("零〇一二兩两三四五六七八九十百千萬万")


def _syllables(text):
    from pypinyin import lazy_pinyin
    han = "".join(c for c in text if "一" <= c <= "鿿" and c not in NUMERALS)
    return lazy_pinyin(han)


def _distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def score(target, heard):
    """Syllable error rate of `heard` against `target` (0 = every syllable right)."""
    a, b = _syllables(target), _syllables(heard)
    return _distance(a, b) / max(1, len(a))


class Checker:
    """Lazily loads Whisper once; transcribe(wav_path) -> text."""

    def __init__(self, model="openai/whisper-large-v3-turbo", language="zh"):
        self.model, self.language, self._pipe = model, language, None

    def transcribe(self, path):
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("automatic-speech-recognition", model=self.model, device=-1)
        import librosa
        audio, _ = librosa.load(path, sr=16000, mono=True)
        out = self._pipe(audio, generate_kwargs={"task": "transcribe", "language": self.language})
        return out["text"].strip()


if __name__ == "__main__":
    # python tts_qa.py "<target text>" a.wav b.wav ...   -> score each take
    import sys
    target, paths = sys.argv[1], sys.argv[2:]
    c = Checker()
    for p in paths:
        heard = c.transcribe(p)
        print(f"{score(target, heard):.3f}  {p}  {heard}")
