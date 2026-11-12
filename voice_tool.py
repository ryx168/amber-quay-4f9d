#!/usr/bin/env python
"""Encrypt / decrypt the voice-clone reference clip.

The reference recording is a real person's voice, so it is NOT committed in clear.
`voice/ronnie_ref.wav.enc` is AES-256-CBC (openssl enc -pbkdf2); the passphrase lives
in the repository secret VOICE_KEY (CI) or a local key file (never committed).

  python voice_tool.py encrypt --key-file C:/path/to/key.txt   (local, once)
  python voice_tool.py decrypt                                  (CI: VOICE_KEY in env)
  python voice_tool.py decrypt --key-file C:/path/to/key.txt   (local)

Without a key the pipeline falls back to OmniVoice voice *design* (see script.json
voice.instruct_fallback), so the repo still renders for anyone who clones it.
"""
import argparse, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLAIN = os.path.join(HERE, "voice", "ronnie_ref.wav")
ENC = PLAIN + ".enc"


def openssl():
    for cand in ("openssl", r"C:\Program Files\Git\mingw64\bin\openssl.exe",
                 r"C:\Program Files\Git\usr\bin\openssl.exe"):
        if shutil.which(cand) or os.path.exists(cand):
            return cand
    sys.exit("openssl not found")


def run(mode, src, dst, key_file):
    cmd = [openssl(), "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", src, "-out", dst]
    if mode == "decrypt":
        cmd.insert(2, "-d")
    if key_file:
        cmd += ["-pass", "file:" + key_file]
    elif os.environ.get("VOICE_KEY"):
        cmd += ["-pass", "env:VOICE_KEY"]
    else:
        return False
    subprocess.run(cmd, check=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["encrypt", "decrypt"])
    ap.add_argument("--key-file")
    a = ap.parse_args()
    if a.mode == "encrypt":
        if a.key_file and not os.path.exists(a.key_file):
            import secrets
            with open(a.key_file, "w") as f:
                f.write(secrets.token_hex(32))
            print("generated new key file", a.key_file)
        if not run("encrypt", PLAIN, ENC, a.key_file):
            sys.exit("no key: pass --key-file or set VOICE_KEY")
        print("wrote", ENC, os.path.getsize(ENC), "bytes")
    else:
        if not os.path.exists(ENC):
            print("no voice/ronnie_ref.wav.enc in the repo: voice design fallback will be used")
            return
        if not run("decrypt", ENC, PLAIN, a.key_file):
            print("VOICE_KEY not set: voice design fallback will be used")
            return
        print("decrypted", PLAIN, os.path.getsize(PLAIN), "bytes")


if __name__ == "__main__":
    main()
