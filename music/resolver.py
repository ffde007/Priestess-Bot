from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import zhconv

import config
import moderation
from music.sources import BilibiliSource, NeteaseSource, SirenSource, YouTubeSource
from music.track import SOURCE_LABELS, SourceError, Stream, Track
from persona import line

log = logging.getLogger(__name__)

FALLBACK_SEARCH_LIMIT = 6
# Choice lists for typed queries: results from the default platform, then a second one
# (which also fills the list when the first platform's search fails), CHOICES_SHOWN at most.
CHOICES_MAIN = 5
CHOICES_EXTRA = 5
CHOICES_SHOWN = 8
CHOICES_ONE_PLATFORM = 8
CHOICES_SIREN = 2  # at most this many Monster Siren results in a mixed list
SIREN_EXACT_SCORE = 95  # SirenSource score for an exact song or album title match
CHOICE_MIN_SECONDS = 30
CHOICE_MAX_SECONDS = 20 * 60
# NetEase "pop" score (0-100) below which an original-looking search result isn't trusted.
MIN_NETEASE_POPULARITY = 50
# Versions that usually aren't what someone asking for the original wants, unless the
# original title says so too. Matched after converting to simplified Chinese.
VARIANT_WORDS = (
    "翻唱", "cover", "covered", "伴奏", "instrumental", "karaoke", "カラオケ", "ニコカラ", "ktv", "off vocal",
    "钢琴", "piano", "吉他", "guitar", "鼓谱", "架子鼓", "drum", "演奏", "光遇", "sky studio", "民乐", "口琴",
    "live", "现场", "演唱会", "concert", "remix", "dj", "纯音乐", "教学", "教程", "reaction", "8d", "倍速", "加速",
    "降调", "片段", "鬼畜", "混剪", "跳舞机", "脚谱", "e舞", "和声", "女声版", "男声版", "nightcore", "slowed",
    "鼓组", "只剩", "纯享", "弹唱", "翻弹", "改编", "治愈版", "抖音", "慢速",
)
# Signs of the original recording.
QUALITY_WORDS = ("official", "官方", "hi-res", "hires", "无损", "lyrics", "歌词", "原版", "topic", "audio")
BRACKETS_RE = re.compile(r"[(（\[【].*?[)）\]】]")


# Platforms that only take links: YouTube search results can be anything, so it's never searched.
LINK_ONLY = {"youtube"}


def _blocked(track: Track) -> bool:
    """A title or uploader on the blocked-words list (see moderation.py)."""
    return moderation.check(f"{track.title} {track.artist or ''}") is not None


def _simplify(text: str) -> str:
    return zhconv.convert(text, "zh-cn").lower()


def _has_word(text: str, word: str) -> bool:
    # Whole words for English ("live" must not match "alive"), substrings for CJK.
    if word.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None
    return word in text


def _variant_words(text: str) -> set[str]:
    text = _simplify(text)
    return {w for w in VARIANT_WORDS if _has_word(text, w)}


def _norm(text: str) -> str:
    """Simplified Chinese, lowercase, only letters, digits and CJK characters."""
    return re.sub(r"[\W_]+", "", _simplify(text))


@dataclass
class _Wanted:
    """What a fallback candidate is matched against (all text already normalized)."""

    terms: list[str]  # all must appear in the candidate's title
    artist: str = ""
    duration: int | None = None
    # Also look for terms in the uploader name (a typed query may name the artist).
    check_uploader: bool = False
    allowed_variants: set[str] = field(default_factory=set)


def _query_wanted(query: str) -> _Wanted:
    """Match what the user typed: every word must appear in the title or uploader name."""
    return _Wanted(
        terms=[t for t in map(_norm, query.split()) if t],
        check_uploader=True,
        allowed_variants=_variant_words(query),
    )


class Resolver:
    """Routes queries and URLs to the right platform."""

    def __init__(self) -> None:
        self.siren = SirenSource()
        self.sources = {s.name: s for s in (YouTubeSource(), BilibiliSource(), NeteaseSource(), self.siren)}
        if config.DEFAULT_SOURCE not in self.sources:
            raise ValueError(f"DEFAULT_SOURCE must be one of {', '.join(self.sources)}")
        if config.DEFAULT_SOURCE in LINK_ONLY:
            raise ValueError("DEFAULT_SOURCE can't be youtube: YouTube only takes links")
        unknown = [s for s in config.NETEASE_FALLBACK if s not in self.sources or s == "netease"]
        if unknown:
            raise ValueError(f"NETEASE_FALLBACK has unknown platforms: {', '.join(unknown)}")
        # The fallback searches by title, so a link-only platform can't take part.
        self.fallback = [s for s in config.NETEASE_FALLBACK if s not in LINK_ONLY]

    def source_for_url(self, text: str):
        text = text.strip()
        for source in self.sources.values():
            if source.matches_url(text):
                return source
        return None

    async def search(self, query: str, source: str | None = None, limit: int = 5) -> list[Track]:
        source = source or config.DEFAULT_SOURCE
        if source in LINK_ONLY:
            raise SourceError(line("link_only", label=SOURCE_LABELS[source]))
        return await self.sources[source].search(query, limit)

    def is_link(self, text: str) -> bool:
        text = text.strip()
        return text.startswith(("http://", "https://")) or self.source_for_url(text) is not None

    async def search_choices(self, query: str, source: str | None = None) -> list[Track]:
        """Candidates for a typed query for the user to pick from.

        Without a chosen platform, mixes the default platform's top results with a few from a
        second one, so a song missing or mislabeled on one platform still shows up.
        """
        if source:
            plan = [(source, CHOICES_ONE_PLATFORM)]
        else:
            other = "netease" if config.DEFAULT_SOURCE != "netease" else "bilibili"
            plan = [(config.DEFAULT_SOURCE, CHOICES_MAIN), (other, CHOICES_EXTRA)]
        # Monster Siren is searched locally alongside, unless a platform was chosen.
        siren_search = self.siren.search_scored(query, CHOICES_SIREN) if not source else asyncio.sleep(0, [])
        results = await asyncio.gather(
            siren_search, *(self.search(query, name, limit) for name, limit in plan), return_exceptions=True
        )
        siren_results, results = results[0], results[1:]
        if isinstance(siren_results, BaseException):
            log.info("Monster Siren search failed: %s", siren_results)
            siren_results = []
        tracks: list[Track] = []
        errors: list[BaseException] = []
        for (name, _), result in zip(plan, results):
            if isinstance(result, BaseException):
                log.info("Choice search on %s failed: %s", name, result)
                errors.append(result)
            else:
                tracks.extend(result)
        if not tracks and errors and not siren_results:
            raise errors[0] if isinstance(errors[0], SourceError) else SourceError("搜索失败了，请稍后再试")

        # Drop clips and hour-long videos (films, compilations, loops), then list covers,
        # karaoke, tutorials and the like after the rest unless the query asked for them.
        tracks = [
            t for t in tracks
            if (not t.duration or CHOICE_MIN_SECONDS <= t.duration <= CHOICE_MAX_SECONDS) and not _blocked(t)
        ]
        wanted_variants = _variant_words(query)
        tracks.sort(key=lambda t: bool(_variant_words(t.title) - wanted_variants))  # stable: keeps search order

        # Official Monster Siren audio goes first when the title matched exactly ("Speed of
        # Light", "飞驰如光"), and at the end for looser matches (a character's name).
        siren_results = [(score, t) for score, t in siren_results if not _blocked(t)]
        exact = [t for score, t in siren_results if score >= SIREN_EXACT_SCORE][:CHOICES_SIREN]
        exact_albums = {t.extra.get("album") for t in exact}
        loose = [
            t for score, t in siren_results
            if score < SIREN_EXACT_SCORE and t.extra.get("album") not in exact_albums  # e.g. its instrumental
        ][: CHOICES_SIREN - len(exact)]
        tracks = exact + tracks[: CHOICES_SHOWN - len(exact) - len(loose)] + loose
        for t in tracks:
            t.extra["query"] = query  # lets a NetEase playback fallback search for what was typed
        return tracks

    async def find(self, query: str, source: str | None = None) -> list[Track]:
        """A URL yields every track it points to; plain text yields the top search result."""
        query = query.strip()
        if url_source := self.source_for_url(query):
            tracks = await url_source.from_url(query)
            allowed = [t for t in tracks if not _blocked(t)]
            if not allowed:
                raise SourceError(line("song_blocked"))
            return allowed
        if query.startswith(("http://", "https://")):
            raise SourceError("不支持这个链接，目前支持 YouTube、Bilibili 和网易云音乐")
        source = source or config.DEFAULT_SOURCE
        if source == "netease":
            return [await self._find_netease(query)]
        results = await self.search(query, source, limit=1)
        if not results:
            raise SourceError(f"在 {SOURCE_LABELS[source]} 上没有找到「{query}」")
        return results[:1]

    async def _find_netease(self, query: str) -> Track:
        """Best NetEase result for a typed query: an original recording whose title matches.

        Overseas, NetEase hides region-locked originals from search, so the top results are
        often covers ("晴天 (原唱 周杰伦)", "夜曲 - Xai小爱") or other songs ("晴天四季").
        """
        results = await self.search(query, "netease", limit=10)
        for t in results:
            t.extra["query"] = query  # lets a playback fallback search for what was typed
        wanted = _query_wanted(query)
        typed = _norm(query)
        obscure: Track | None = None
        for t in results:
            if not t.extra.get("original") or _variant_words(t.title) - wanted.allowed_variants:
                continue
            # The title (minus "(Live)"-style suffixes) must be part of what was typed, and every
            # typed word must be in the title or artist: "句号 邓紫棋" matches 句号 by G.E.M.邓紫棋.
            core = _norm(BRACKETS_RE.sub("", t.title))
            if core and core in typed and all(term in _norm(f"{t.title} {t.artist or ''}") for term in wanted.terms):
                if t.extra.get("popularity", 0) >= MIN_NETEASE_POPULARITY:
                    return t
                # Little-known "originals" with a famous song's name are usually not it.
                obscure = obscure or t

        if self.fallback:
            ranked = await self._ranked_alternatives(query, wanted)
            if ranked:
                alt = ranked[0]
                alt.extra["note"] = f"网易云上没有找到原唱版本，已改用 {alt.label}"
                return alt
        if obscure or results:
            return obscure or results[0]
        raise SourceError(f"在 {SOURCE_LABELS['netease']} 上没有找到「{query}」")

    async def resolve(self, track: Track) -> Stream:
        return await self.sources[track.source].resolve(track)

    async def find_alternative(self, track: Track) -> tuple[Track, Stream] | None:
        """Find and resolve the same song on the NETEASE_FALLBACK platforms."""
        if user_query := track.extra.get("query"):
            # The NetEase result may not be the original; search for what the user typed instead.
            query = user_query
            wanted = _query_wanted(user_query)
        else:
            title = BRACKETS_RE.sub("", track.title).strip() or track.title
            artist = (track.artist or "").split(" / ")[0].strip()
            query = f"{title} {artist}".strip()
            wanted = _Wanted(
                terms=[_norm(title)] if _norm(title) else [],
                artist=_norm(artist),
                duration=track.duration,
                allowed_variants=_variant_words(track.title),
            )

        for candidate in await self._ranked_alternatives(query, wanted):
            try:
                stream = await self.resolve(candidate)
            except SourceError as e:
                log.info("Fallback candidate %s failed: %s", candidate.page_url, e)
                continue
            candidate.requester_id = track.requester_id
            return candidate, stream
        return None

    async def _ranked_alternatives(self, query: str, wanted: _Wanted) -> list[Track]:
        # Search every fallback platform at once and rank all results together.
        results = await asyncio.gather(
            *(self.sources[name].search(query, FALLBACK_SEARCH_LIMIT) for name in self.fallback),
            return_exceptions=True,
        )
        candidates: list[tuple[int, int, Track]] = []  # (platform order, search rank, track)
        for p, (name, result) in enumerate(zip(self.fallback, results)):
            if isinstance(result, BaseException):
                log.info("Fallback search on %s failed: %s", name, result)
                continue
            candidates.extend((p, rank, t) for rank, t in enumerate(result) if not _blocked(t))
        return self._rank_alternatives(wanted, candidates)

    @staticmethod
    def _rank_alternatives(wanted: _Wanted, candidates: list[tuple[int, int, Track]]) -> list[Track]:
        scored: list[tuple[float, Track]] = []

        for platform_order, rank, c in candidates:
            if _variant_words(c.title) - wanted.allowed_variants:
                continue
            text = _norm(f"{c.title} {c.artist or ''}" if wanted.check_uploader else c.title)
            title_match = bool(wanted.terms) and all(t in text for t in wanted.terms)
            artist_in_title = bool(wanted.artist) and wanted.artist in _norm(c.title)
            # Uploaded by the artist's own channel (or a "Artist - Topic" channel).
            artist_uploaded = bool(wanted.artist) and wanted.artist in _norm(c.artist or "")
            quality = any(_has_word(_simplify(c.title), w) for w in QUALITY_WORDS)

            if wanted.duration and c.duration:
                diff = abs(wanted.duration - c.duration)
                # Allow small differences (intros, MV endings) but not a different cut of the song.
                if diff > max(20, wanted.duration * 0.15):
                    continue
            elif wanted.duration is None and wanted.check_uploader:
                # Matching a typed query: no reference length, so only rule out clips and
                # hour-long loops/compilations.
                if c.duration and not 60 <= c.duration <= 900:
                    continue
                diff = 0
            else:
                diff = 30  # unknown length: rely on the title
            if not title_match and (wanted.check_uploader or diff > 5):
                continue

            # Lower is better. Duration difference in seconds is the baseline.
            score = (
                diff
                - (30 if title_match else 0)
                - (10 if artist_in_title else 0)
                - (15 if artist_uploaded else 0)
                - (6 if quality else 0)
                + 3 * platform_order
                + 0.5 * rank
            )
            scored.append((score, c))

        scored.sort(key=lambda s: s[0])
        return [c for _, c in scored]

    async def close(self) -> None:
        for source in self.sources.values():
            await source.close()
