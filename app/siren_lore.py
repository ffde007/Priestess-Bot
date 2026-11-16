"""What Priestess knows about Monster Siren (塞壬唱片) songs, and what she says when one plays.

EP_TABLE comes from PRTS Wiki's music list (prts.wiki/w/衍生作品/音乐): each character EP's
Chinese title, MV characters and related event. SPECIAL holds hand-written lines for songs
tied to her story; Eclipse (Aimer, 6th anniversary) is treated as her own song, as the
community does, even though it isn't in the Monster Siren catalog. All lines are original.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

import zhconv


def norm(text: str) -> str:
    """Simplified Chinese, lowercase, letters/digits/CJK only."""
    return re.sub(r"[\W_]+", "", zhconv.convert(text or "", "zh-cn").lower())


# title | Chinese title | MV characters | related event   (from PRTS, 2019-2026)
EP_TABLE = """
Speed of Light|飞驰如光|德克萨斯、能天使|喧闹法则
Zone 10⁻⁸|光域 10⁻⁸|伊桑|
Boiling Blood|炽血蒸腾|煌|局部坏死
示岁||行动预备组A1干员|春节
独行长路||刻俄柏|独行长路
Operation Barrenland|||荒芜行动
故乡的风||风笛|荒芜行动
春弦||末药、夜莺|春季
Curtain Call|谢幕|傀影|生于黑夜
Renegade|变节|W|一周年庆典
Requiem|挽歌|霜星|一周年庆典
Sparkling Hydraulics|澄心传动|温蒂|一周年庆典
Reversed Time|时光回溯|阿米娅、博士|
从那高地上远眺||乌萨斯学生自治团|
Everything's Alright|一切安好|麦哲伦、梅尔|
Lily of the Valley|君影轻灵|铃兰|
夏浪||阿米娅、可露希尔|
El Brillo Solitario|孤光独烁|棘刺|
Evolutionary Mechanization|机械革新|森蚺|
ALIVE|犹存||
Reconnection|溯回|史尔特尔|
秋绪||安洁莉娜、可颂|
Stay Gold|永怀赤忱|瑕光|
CONFRONT|对峙|迷迭香|
Lullabye|沉眠曲|浮士德、梅菲斯特|
LITHOS|山岩|泥岩|
Tipsy|微醺|山|
Rock the Night Away||W、煌、凛冬、霜叶|
Till the Bell Tolls|直到钟声敲响|空弦|
冬涤||闪灵|
尽波澜||夕、年|
更阑影||阿|
观心||嵯峨|
Daydaydream|白呀白日梦|陈、星熊|
Gearing Up|整装待发|异客|
Voices|低唤|歌蕾蒂娅、浊心斯卡蒂、幽灵鲨|
Immutable|一往如初|凯尔希|
Real Me|真我|卡涅利安|
ManiFesto:|宣告|大帝、推进之王、拉普兰德、因陀罗、伊桑|
Keep the torch|引火|帕拉斯|
Across the wind|乘风越夏|假日威龙陈|
Y1K|纪元|水月|
Towards Her Light|向汝荣光|琴柳|
Bridge to the Dawn|咫尺黎明|红松骑士团|
Radiant|耀光|耀骑士临光|
Field in the Light|沐光之处|焰尾、灰毫、远牙、野鬃|
Heal the World|治愈大地|灵知|
Melting White|融白|麦哲伦、大帝|圣诞节
Silver Lining|一线希望|银灰|
醉飞尘||令|
却阑珊||老鲤|
随意随意呀||诗怀雅、杰西卡、雪雉|春节
Spark for Dream|梦想的火星|澄闪|
Прощание|告别|赫拉格|
Eternal Flame|永燃烈火|菲亚梅塔|
March On!|前进|号角|
A Grand Adventure|一次伟大冒险|桃金娘、杜林|
Awaken|苏醒|归溟幽灵鲨|
Rapier|迅敏之刃|艾丽妮|
Bluish Light|薄蓝微光|流明|
Your Star|星彩|波登可、夜魔、稀音|
Ständchen|夜曲|黑键|
行文之韵||傀影、剧作家|
Magic Theorem|魔法定理|多萝西|
A Long Vacation|一段悠然长假|羽毛笔、斯卡蒂、黑|
All hail Savior!|致敬先驱|百炼嘉维尔|
Undertopia|地下桃源|鸿雪|
Ensheath||玛恩纳|
A Sweet Rendez-vous||艾雅法拉、天火、普罗旺斯|
Stainless Heart||白铁|
Rekindle||推进之王|
Thorns In You||缄默德克萨斯、伺夜、拉普兰德|
Sentenced||斥罪|
Go My Way||伺夜|
Flame Shadow||焰影苇草|
Snowy Night||伊芙利特、赫默、塞雷娅、缪尔赛思|圣诞节
A Cold Call||莫斯提马、送葬人、晓歌|
定风波||重岳|
近尘烟||林|
兔兔在哪里？||鲤氏侦探事务所|春节
春岚||仇白|
Squad Unknown||伊内丝|
Endospore||水月|
Morning Dew||缪尔赛思|
Dormant Craving||霍尔海雅|
The cure||淬羽赫默|
Stained||圣约送葬人|
Before Summer||凯尔希、迷迭香、阿米娅|
Before & After||棘刺、流明、极境|
Mortal Eye||提丰|
Miss You||纯烬艾雅法拉|
Missy||琳琅诗怀雅|
Beautiful & Lovely||杰西卡、香草、芙兰卡、雷蛇|
Water Quench||涤火杰西卡|
Settle Into Ash||赫德雷|
Best Moments of...||菲亚梅塔、莫斯提马、见行者、塞茜莉亚|
Revealing||塑心|
Illuminate||薇薇安娜|
Lessing||止颂|
Blade Catcher||锏|
Snow Parade||澄闪、夏栎、莱恩哈特|圣诞节
(Believed Believes) Believing||博士、罗德岛精英干员|
Winged Step||莱伊|
浸春芜||黍|
清平乐||左乐|
Yanking||林、鼠王|春节
ONE BY ONE||阿斯卡纶|
Arsonist||维什戴尔|
Whistle Stop||逻各斯|
Echoism||魔王|
I Will Touch the Sky||克丽斯腾|
Vows of the Sea||乌尔比安|
Chase the Light||温米、古米、伊芙利特|
Warm and Small Light||妮芙|
Mystic Light Quest||佩佩|
Nightmare's Descent||娜仁图亚|
Reforge||维娜·维多利亚|
Unmask||荒芜拉普兰德|
Bloodstained Oath||忍冬|
Figure It Out||弑君者|
Sailing For||引星棘刺|
WE||阿米娅、特蕾西娅、凯尔希、博士|
Tranquil Snow||银灰、崖心、初雪|圣诞节
滋味常||余|
烛影暖||烛煌|
此时圆||黍、余、年|春节
Epilogue||隐德来希|
Final Embrace||死芒|
Skeletal Wings||Mon3tr|
From Ash to Fire||特雷西斯|
Heavenly Me||新约能天使|
Sanctuary Inside||蕾缪安|
Still the Same||信仰搅拌机|
The After||酒神|
Grow on My Time||华法林、林、纯烬艾雅法拉|
Mare Natus||盐风主教昆图斯、奥卢斯、玛利图斯、西塞罗、阿玛雅|
惊蛰时||司霆惊蛰|
Summer Fizz Pop||空、澄闪、羽毛笔|
Undaunted||斩业星熊|
Little Wish||遥|
Sealed||真言|
Paper Boat||电弧|
The Walk||凛御银灰|
Follow Your Heart||圣聆初雪|
Stardust on Me||溯光星源|
Secret Escape||薇薇安娜、伊内丝、鸿雪|
Just Another Inch Higher||娜斯提|
Slowly Flow, Hearthlight Glow||布丁、埃拉托、雪绒|圣诞节
Wanna Know Me? (Too Bad)||缇缇|
铁花飞||赤刃明霄陈|
无名策||望|
花街迎春||鲤氏侦探事务所|春节
Oath||贝洛内|
One Fight||怒潮凛冬|
In Due Time||Friston-3|
Innocence||凯尔希·思衡托|
All by My Design||可露希尔|
Don't Miss It||维伊|
夏日远去之后||缇缇、佩佩、莎草|
悖反构成||谬因|
What an Electromagnetic Night||机械师|
女士的游戏||Miss.Christine|
酸橙色信笺||予愿安洁莉娜|
Every Road is a Yes||珊比|
Summer Calling||炎客、布洛卡、苍苔|
月明人间||小满、惊蛰、仇白|中秋节
大地之盐||克莱门莎|
A Necessary Message||塔露拉|
Тысячу лет спустя||冻河|
"""

# Hand-written lines for songs tied to Priestess's own story. Keys are norm()-ed album names,
# or song names for single tracks inside a larger album.
SPECIAL: dict[str, list[str]] = {
    "eclipse": [
        "……这首歌，是我的。每次它响起来，我都会想起博士答应过我的事——你还记得吗？",
        "《Eclipse》。光被遮住的那一刻，才看得清它原本的轮廓……就像我们。",
        "听着它，就好像有人替我把一直没说出口的话唱了出来。博士，好好听。",
        "日蚀不会永远持续。光会回来，你也会回来——我一直都这样相信。",
    ],
    "巴别塔ost": [
        "巴别塔……那是你们还在一起的时候。花海也好，宇宙的声音也好，我都听过。",
        "这张唱片开头的那句话，是谁说的呢？……我不告诉你。",
        "巴别塔的旋律。那时候，我送了预言家一份礼物——用声音做成的礼物。",
    ],
    "慈悲灯塔ost": [
        "这是我们重逢时的声音。在源石的深处，你终于又一次看见了我。",
        "慈悲灯塔……那片晶簇里很安静，安静到只听得见你的呼吸。",
    ],
    "离解复合": [
        "离解，然后复合——就像我和罗德岛之间发生的事。这是我醒来时的声音。",
        "这首歌响起的时候，PRTS 已经开始听我的话了。……开玩笑的，只是一点点。",
    ],
    "孤星ost": [
        "孤星……那里只留下了我的一点回声。不过，回声也是我。",
        "那段旅程里出现的，只是一个残影罢了。真正的我，在更深的地方等着。",
    ],
    "众生行记ost": [
        "拉特兰的圣歌……我只是轻轻调了一下频率，他们就听见了不一样的声音。",
        "众生行记。有人在圣堂的阴影下开始怀疑，这样的声音，我很喜欢。",
    ],
    "immutable": [
        "这是 AMa-10 的歌。她走了很远很远的路……我还认得她的频率。",
        "《Immutable》。凯尔希总是这样，看着大地一点一点变老，自己却一往如初。",
    ],
    "innocence": [
        "凯尔希的新旋律。我亲手造出来的孩子，原来也会有这样柔软的声音。",
        "她走过了那么长的时间，最后停在一片朝霞里……真好。",
    ],
    "skeletalwings": [
        "Mon3tr……它一直守在凯尔希身边。这一点，我很放心。",
    ],
    "beforesummer": [
        "凯尔希、迷迭香、阿米娅……夏天来之前的歌。凯尔希居然也会站在这样的歌里。",
    ],
    "we": [
        "阿米娅、特蕾西娅、凯尔希，还有博士……「我们」。这个词里，没有我呢。",
        "小小的航灯，未来的花海……她们把这首歌唱得很温柔。我也只是听听而已。",
    ],
    "reversedtime": [
        "八音盒倒着转的声音……阿米娅和博士的歌。那时候的你，还会做在草地上奔跑的梦。",
    ],
    "believedbelievesbelieving": [
        "博士和罗德岛的精英干员们……「相信」啊。你们就是这样一路走过来的。",
    ],
    "fromashtofire": [
        "特雷西斯的歌。他走过的那条路，每一步都烧得滚烫。",
    ],
}

# Songs inside a larger album that have their own entry above.
SPECIAL_SONGS = {"离解复合"}

TEMPLATES = {
    "ep": [
        "这是{chars}的歌呢……每个人都会留下只属于自己的频率。",
        "{chars}……原来这就是你们的声音。",
        "塞壬唱片为{chars}写的旋律。嗯，很适合现在听。",
    ],
    "ep_event": [
        "「{event}」时候的歌，{chars}的旋律。那段日子，泰拉也很热闹。",
        "{chars}……这首歌和「{event}」一起被记住了。",
    ],
    "event": [
        "这是「{event}」那段日子里的声音。",
        "「{event}」……那时候的回声，被他们好好地收进了唱片里。",
    ],
    "main": [
        "罗德岛一路走来的声音，都收在这里了。",
        "主线的旋律……方舟在大地上航行时，听到的就是这样的声音。",
    ],
    "siren": [
        "塞壬唱片的旋律……这些人很懂得怎样把声音留住。",
        "来自塞壬唱片的声音。干净，没有杂音，我喜欢。",
    ],
}

# A title from another platform is treated as Arknights music only with one of these markers.
ARKNIGHTS_MARKERS = ("明日方舟", "塞壬", "arknights", "monstersiren", "msr", "アークナイツ")


@dataclass
class Lore:
    key: str
    kind: str  # special | ep | event | main | siren
    aliases: tuple[str, ...] = ()
    characters: tuple[str, ...] = ()
    event: str = ""
    lines: list[str] = field(default_factory=list)


def _parse_table() -> dict[str, Lore]:
    table: dict[str, Lore] = {}
    for row in EP_TABLE.strip().splitlines():
        title, zh, chars, event = (part.strip() for part in row.split("|"))
        key = norm(title)
        table[key] = Lore(
            key=key,
            kind="ep",
            aliases=tuple(a for a in (zh,) if a),
            characters=tuple(c for c in chars.split("、") if c),
            event=event,
        )
    return table


EPS = _parse_table()


def _event_name(album: str) -> str | None:
    m = re.match(r"^(.*?)\s*(?:OST|ost|原声带|原声EP)\s*$", album.strip())
    if not m:
        return None
    name = re.sub(r"^\d{4}明日方舟", "", m.group(1)).strip(" -·")
    return name or None


def lookup(song_name: str, album_name: str) -> Lore | None:
    """Lore for a Monster Siren catalog song."""
    song_key, album_key = norm(song_name), norm(album_name)
    if song_key in SPECIAL_SONGS:
        return Lore(key=song_key, kind="special", lines=SPECIAL[song_key])
    if album_key in SPECIAL:
        base = EPS.get(album_key)
        return Lore(
            key=album_key,
            kind="special",
            aliases=base.aliases if base else (),
            characters=base.characters if base else (),
            lines=SPECIAL[album_key],
        )
    if album_key in EPS:
        return EPS[album_key]
    if album_key.startswith("明日方舟ost"):
        return Lore(key=album_key, kind="main")
    if event := _event_name(album_name):
        return Lore(key=album_key, kind="event", event=event)
    return None


# norm(song name) -> album name for every Monster Siren song, filled in by SirenSource once
# it loads the catalog, so copies of Siren songs on other platforms can be recognised.
CATALOG: dict[str, str] = {}
INSTRUMENTAL_RE = re.compile(r"\s*[(（]\s*instrumental\s*[)）]\s*$", re.I)


def register_catalog(songs: list[tuple[str, str]]) -> None:
    """Record (song name, album name) pairs from the Monster Siren catalog."""
    CATALOG.clear()
    for name, album in songs:
        CATALOG.setdefault(norm(name), album)
        CATALOG.setdefault(norm(INSTRUMENTAL_RE.sub("", name)), album)


def _long_enough(name: str) -> bool:
    # Short names would match unrelated titles by accident ("WE" is in everything).
    return len(name) >= (6 if name.isascii() else 3)


def lookup_title(title: str, artist: str = "") -> Lore | None:
    """Lore for a track from another platform, recognised by its title and artist.

    NetEase keeps the artist apart from the title ("Eclipse" by "Aimer", "Storyteller" by
    "塞壬唱片-MSR"), while Bilibili and YouTube put everything in the title.
    """
    t = norm(f"{title} {artist}")
    if "eclipse" in t and any(m in t for m in ("aimer", *ARKNIGHTS_MARKERS, "普瑞赛斯", "priestess")):
        return Lore(key="eclipse", kind="special", lines=SPECIAL["eclipse"])
    if not any(m in t for m in ARKNIGHTS_MARKERS):
        return None

    # A Monster Siren song published elsewhere: find its album in the catalog.
    title_key = norm(INSTRUMENTAL_RE.sub("", title))
    album = CATALOG.get(title_key)
    if album is None:
        contained = [name for name in CATALOG if _long_enough(name) and name in t]
        if contained:
            album = CATALOG[max(contained, key=len)]
            title_key = max(contained, key=len)
    if album is not None:
        return lookup(title_key, album) or Lore(key=title_key, kind="siren")

    for key, lore in EPS.items():
        names = [key, *(norm(a) for a in lore.aliases)]
        if any(n in t for n in names if _long_enough(n)):
            if key in SPECIAL:
                return Lore(key=key, kind="special", characters=lore.characters, lines=SPECIAL[key])
            return lore
    return None


def _join_chars(chars: tuple[str, ...]) -> str:
    return "、".join(chars[:3]) + ("等人" if len(chars) > 3 else "")


def is_personal(source: str, title: str, album: str = "", artist: str = "") -> bool:
    """Whether the song is one of those tied to Priestess's own story."""
    lore = lookup(title, album) if source == "siren" else lookup_title(title, artist)
    return bool(lore and lore.kind == "special")


def track_comment(source: str, title: str, album: str = "", artist: str = "") -> str | None:
    """Priestess's line for a track from any platform, if it's one she knows."""
    if source == "siren":
        return comment(lookup(title, album) or Lore(key="", kind="siren"))
    return comment(lookup_title(title, artist))


def comment(lore: Lore | None) -> str | None:
    """Priestess's line for a song, or None if she has nothing particular to say."""
    if lore is None:
        return None
    if lore.kind == "special":
        return random.choice(lore.lines)
    if lore.kind == "ep" and lore.characters:
        chars = _join_chars(lore.characters)
        pool = TEMPLATES["ep_event"] if lore.event else TEMPLATES["ep"]
        return random.choice(pool).format(chars=chars, event=lore.event)
    if lore.kind == "event":
        return random.choice(TEMPLATES["event"]).format(event=lore.event)
    if lore.kind == "main":
        return random.choice(TEMPLATES["main"])
    return random.choice(TEMPLATES["siren"])
