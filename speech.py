"""Her voice: GPT-SoVITS with the Priestess model, started on demand and stopped when idle.

The voice settings come from the JSON file VOICE_CONFIG points at (model weights, the
reference clip, the pauses between sentences; voices/example.json shows the fields). The
sentence splitting and the redo of stalled takes follow an audiobook script. GPT-SoVITS's
api_v2.py is started hidden with its own runtime Python, output in logs/sovits.log. If it's
already running (started elsewhere), it's used but never stopped from here.
"""

from __future__ import annotations

import asyncio
import atexit
import io
import json
import logging
import re
import subprocess
import time
import wave
from pathlib import Path

import aiohttp

import config

log = logging.getLogger(__name__)

LOG_FILE = Path(__file__).parent / "logs" / "sovits.log"
STARTUP_TIMEOUT = 240  # seconds for the models to load
SPOKEN_CHARS = 220  # read at most about this much of a reply; the rest stays in the text
WARMUP_TEXT = "嗯。"
MIN_CHARS = 4  # shorter sentences ("咔。") are merged into the next one
DROP = "【】“”「」『』\"'"  # brackets and quotes aren't spoken
# Spoken characters per second; a take outside this (a stall, or a garbled rush) is redone with
# another seed. The audio isn't trimmed here, so the floor is lower than narrate.py's 1.5.
OK_RATE = (1.0, 9.0)
RETRIES = 2


class SpeechError(Exception):
    """A user-facing reason she can't speak."""


def load_voice_config() -> dict | None:
    try:
        cfg = json.loads(Path(config.VOICE_CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ref = Path(cfg["reference"]["audio"])
    if not ref.is_absolute():
        ref = Path(config.VOICE_CONFIG).parent / ref
    cfg["reference"]["audio"] = str(ref)
    if config.VOICE_PROMPT == "clip" and cfg["reference"].get("text_of_clip"):
        cfg["reference"]["text"] = cfg["reference"]["text_of_clip"]
    elif config.VOICE_PROMPT == "none":
        cfg["reference"]["text"] = ""
    return cfg


# ---- text for speaking -----------------------------------------------------------

_URL_RE = re.compile(r"<?https?://\S+>?")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>|<@[!&]?\d+>|<#\d+>|\[表情[:：][^\]]*\]")
_MARKDOWN_RE = re.compile(r"[*_`~>#|]+")
_DOLLARS_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


def speakable(text: str) -> str:
    """Her reply as something to read aloud: no links, emoji, markdown; about SPOKEN_CHARS long."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("-#")]
    text = "\n".join(lines)
    text = _URL_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _DOLLARS_RE.sub(lambda m: m.group(1).replace(",", "") + "美元", text)
    text = re.sub(r"\s*\n+\s*", "。", text.strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"。{2,}", "。", text)
    if len(text) <= SPOKEN_CHARS:
        return text
    cut = max(text.rfind(p, 0, SPOKEN_CHARS) for p in "。！？…")
    return text[: cut + 1] if cut > 40 else text[:SPOKEN_CHARS] + "……"


def spoken_len(text: str) -> int:
    return len(re.sub(r"[，。！？、；：…,\s]", "", text))


def _pause(sentence: str, kind: str, pauses: dict) -> float:
    if kind in ("ellipsis", "dash"):
        return float(pauses.get(kind, 2.0 if kind == "ellipsis" else 0.8))
    rule = pauses.get("question" if kind == "question" else "period") or {}
    lo, hi = float(rule.get("min", 1.0)), float(rule.get("max", 1.5))
    return lo + (hi - lo) * min(1.0, spoken_len(sentence) / float(rule.get("full_at_chars", 24)))


def sentences(text: str, pauses: dict) -> list[tuple[str, float]]:
    """(sentence, pause after it in seconds), split like the audiobook's narrate.py: whole
    sentences keep their commas (the model phrases them in one breath), a dash —— is a short
    beat between two halves, very short lines are merged into the next one."""
    text = "".join(ch for ch in text if ch not in DROP).strip()
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(……)?([^。！？!?…]+)([。！？!?]|……)?", text):
        lead, body, end = m.group(1), m.group(2).strip(" ，,"), m.group(3) or "。"
        if not re.search(r"[\w\u4e00-\u9fff]", body):
            continue
        if lead and out:
            out[-1] = (out[-1][0], "ellipsis")
        kind = "ellipsis" if end == "……" else "question" if end in "！？!?" else "period"
        out.append((body + ("。" if end == "……" else end), kind))
    beats: list[tuple[str, str]] = []
    for sentence, kind in out:
        pieces = [p.strip("，、 ") for p in re.split(r"—{1,2}|－{1,2}", sentence)]
        if len(pieces) == 1:
            beats.append((sentence, kind))
            continue
        if not pieces[0] and beats:  # dash at the very start: a pause before
            beats[-1] = (beats[-1][0], "dash" if beats[-1][1] == "period" else beats[-1][1])
        for i, piece in enumerate(pieces):
            if not piece or set(piece) <= set("。！？!?"):
                continue
            final = i == len(pieces) - 1 or not any(q.strip("。！？!?") for q in pieces[i + 1:])
            if final and piece[-1] in "。！？!?":
                beats.append((piece, kind))
            else:  # the left side ends in "，" so the model keeps a continuing intonation
                beats.append((piece + "，", "dash"))
    merged: list[tuple[str, str]] = []
    for sentence, kind in beats:
        if merged and merged[-1][1] != "dash" and spoken_len(merged[-1][0]) < MIN_CHARS:
            merged[-1] = (merged[-1][0] + sentence, kind)
        else:
            merged.append((sentence, kind))
    return [(sentence, _pause(sentence, kind, pauses)) for sentence, kind in merged]


def wav_seconds(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0.0


# ---- the GPT-SoVITS server -------------------------------------------------------


class SpeechEngine:
    """Starts, stops and talks to GPT-SoVITS's api_v2.py."""

    def __init__(self) -> None:
        self.cfg = load_voice_config()
        self.process: subprocess.Popen | None = None
        self.state = "off"  # off | starting | on
        self.owned = False  # started by us (so we may stop it)
        self.last_used = time.monotonic()
        self.lock = asyncio.Lock()
        self.synth_lock = asyncio.Lock()  # one synthesis at a time on the GPU
        self._session: aiohttp.ClientSession | None = None
        atexit.register(self._kill)

    @property
    def available(self) -> bool:
        return self.cfg is not None and Path(self.cfg["gsv_root"], "api_v2.py").is_file()

    @property
    def post_filter(self) -> str:
        """FFmpeg audio filter the voice's settings ask for (e.g. a loudness chain), or ""."""
        return str(((self.cfg or {}).get("synthesis") or {}).get("post_filter") or "")

    @property
    def api(self) -> str:
        return (self.cfg or {}).get("api", "http://127.0.0.1:9880").rstrip("/")

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return self._session

    async def alive(self) -> bool:
        try:
            async with (await self._http()).get(f"{self.api}/control", timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status in (200, 400)  # 400 = up, just no command given
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def start(self) -> str:
        """Start (or adopt) the server and load the Priestess model. Returns "started"/"running"."""
        if not self.available:
            raise SpeechError("没有找到语音设置或 GPT-SoVITS（VOICE_CONFIG）")
        async with self.lock:
            if self.state == "on" and await self.alive():
                return "running"
            self.state = "starting"
            try:
                result = "running"
                if not await self.alive():
                    self._spawn()
                    await self._wait_until_up()
                    result = "started"
                await self._load_weights()
                await self.synthesize(WARMUP_TEXT)  # the first synthesis is slow (CUDA graphs)
            except BaseException:
                self.state = "off"
                if self.owned:
                    self._kill()
                raise
            self.state = "on"
            self.last_used = time.monotonic()
            return result

    def _spawn(self) -> None:
        root = Path(self.cfg["gsv_root"])  # type: ignore[index]
        port = self.api.rsplit(":", 1)[-1]
        LOG_FILE.parent.mkdir(exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 5_000_000:  # one old copy
            LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))
        out = LOG_FILE.open("ab")
        self.process = subprocess.Popen(
            [str(root / "runtime" / "python.exe"), "api_v2.py", "-a", "127.0.0.1", "-p", port,
             "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self.owned = True
        log.info("Started GPT-SoVITS (pid %s)", self.process.pid)

    async def _wait_until_up(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise SpeechError("GPT-SoVITS 启动失败了（见 logs/sovits.log）")
            if await self.alive():
                return
            await asyncio.sleep(1.5)
        raise SpeechError("GPT-SoVITS 启动太久了，没有响应")

    async def _load_weights(self) -> None:
        model = self.cfg["model"]  # type: ignore[index]
        for path, key in (("set_gpt_weights", "gpt_weights"), ("set_sovits_weights", "sovits_weights")):
            async with (await self._http()).get(f"{self.api}/{path}", params={"weights_path": model[key]}) as r:
                if r.status != 200:
                    raise SpeechError(f"加载声音模型失败（{path}: {r.status}）")

    async def stop(self) -> bool:
        """Stop the server if we started it. False when it belongs to someone else (left running)."""
        async with self.lock:
            self.state = "off"
            if not self.owned:
                return False
            self._kill()
            return True

    def _kill(self) -> None:
        if self.process and self.process.poll() is None:
            # api_v2 may start helper processes: end the whole tree.
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log.info("Stopped GPT-SoVITS (pid %s)", self.process.pid)
        self.process = None
        self.owned = False

    async def synthesize(self, sentence: str) -> bytes:
        """WAV bytes for one sentence; a stalled or rushed take is redone with another seed."""
        seed = int(((self.cfg or {}).get("synthesis") or {}).get("seed", 1234))
        for attempt in range(RETRIES + 1):
            data = await self._synthesize_once(sentence, seed + attempt * 101)
            rate = spoken_len(sentence) / max(wav_seconds(data), 1e-3)
            if OK_RATE[0] <= rate <= OK_RATE[1] or spoken_len(sentence) < MIN_CHARS:
                break
            log.info("Redoing a take (%.1f chars/s): %s", rate, sentence)
        return data

    async def _synthesize_once(self, sentence: str, seed: int) -> bytes:
        cfg = self.cfg or {}
        ref, synth = cfg.get("reference", {}), cfg.get("synthesis", {})
        body = {
            "text": sentence,
            "text_lang": "zh",
            "ref_audio_path": ref.get("audio"),
            "prompt_text": ref.get("text", ""),
            "prompt_lang": ref.get("lang", "zh"),
            "text_split_method": synth.get("text_split_method", "cut0"),
            "fragment_interval": synth.get("fragment_interval", 0.0),
            "seed": seed,
            "batch_size": 1,
            "media_type": "wav",
            "streaming_mode": False,
        }
        async with self.synth_lock:
            try:
                async with (await self._http()).post(f"{self.api}/tts", json=body) as r:
                    data = await r.read()
                    if r.status != 200:
                        raise SpeechError(f"合成失败（{r.status}）：{data[:200]!r}")
            except (aiohttp.ClientError, TimeoutError) as e:
                raise SpeechError(f"连不上 GPT-SoVITS（{e.__class__.__name__}）") from e
        self.last_used = time.monotonic()
        return data

    async def close(self) -> None:
        await self.stop()
        if self._session and not self._session.closed:
            await self._session.close()
