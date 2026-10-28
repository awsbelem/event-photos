import datetime as dt
import gzip
import json
import re
from zoneinfo import ZoneInfo

from event_photos import stats

TZ = ZoneInfo("America/Belem")
PHONE = "Mozilla/5.0%20(iPhone;%20CPU%20iPhone%20OS%2027_0_1%20like%20Mac%20OS%20X)%20AppleWebKit/605.1.15"
DESK = "Mozilla/5.0%20(X11;%20Linux%20x86_64)%20AppleWebKit/537.36%20Chrome/151.0.0.0%20Safari/537.36"


def line(time, path, query="-", ua=PHONE, status="200", size="43", date="2026-10-31"):
    return json.dumps({"date": date, "time": time, "cs-uri-stem": path, "cs-uri-query": query, "sc-status": status,
                       "sc-bytes": size, "x-edge-location": "FOR50-P6", "x-edge-result-type": "Hit",
                       "cs(User-Agent)": ua})


LINES = [
    line("13:05:00", "/e.gif", "e=open&r=a1"),
    line("13:06:00", "/e.gif", "e=open&r=a2", ua=DESK),
    line("14:10:00", "/e.gif", "e=open&r=a3"),
    line("14:11:00", "/e.gif", "e=open&r=a4", ua="Mozilla/5.0%20HeadlessChrome/151"),  # a test browser
    line("14:12:00", "/e.gif", "e=photo&id=a--1&r=b1"),
    line("14:12:30", "/e.gif", "e=photo&id=a--1&r=b2"),
    line("14:13:00", "/e.gif", "e=photo&id=kid&r=b3"),
    line("14:14:00", "/e.gif", "e=save&id=a--1&f=hex&m=feed&r=c1"),
    line("14:15:00", "/e.gif", "e=share&id=a--1&f=fun&m=story&r=c2"),
    line("14:15:30", "/e.gif", "e=frame&id=a--1&f=fun&m=story&r=c3"),
    line("14:16:00", "/e.gif", "e=find&n=1-5&r=d1"),
    line("14:17:00", "/e.gif", "e=find&n=0&s=file&r=d2"),
    line("14:18:00", "/e.gif", "e=wall&r=w1"),
    line("14:33:00", "/e.gif", "e=wall&r=w2"),
    line("14:19:00", "/e.gif", "-"),  # no query
    line("14:20:00", "/e.gif", "e=open&r=x", status="404"),
    line("14:21:00", "/og/a--1.jpg", ua="WhatsApp/2.23.20.0", size="90000"),
    line("14:21:01", "/p/a--1.html", ua="WhatsApp/2.23.20.0"),
    line("14:22:00", "/p/a--1.html"),
    line("14:23:00", "/og.jpg", ua="LinkedInBot/1.0"),
    "not json",
]
LISTING = {"moments": [{"t": "10:00", "n": "Abertura"}, {"t": "", "n": "Outros momentos"}],
           "photos": [{"id": "a--1", "m": 0, "t": "10:30", "c": "Ana"}, {"id": "kid", "m": 0, "t": "10:40", "c": "Ana"},
                      {"id": "b--2", "m": 1, "t": "", "c": "Bia"}]}


def hits(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    with gzip.open(folder / "E1.2026-10-31-13.abc.gz", "wt") as f:
        f.write("\n".join(LINES) + "\n")
    return stats.read_logs(folder, TZ)


def numbers(tmp_path, rounds=()):
    taken = {"a--1": dt.datetime(2026, 10, 31, 9, 50, tzinfo=TZ), "kid": dt.datetime(2026, 10, 31, 9, 40, tzinfo=TZ)}
    return stats.compute(hits(tmp_path), LISTING, list(rounds), taken, {"hex": "Hexágonos"}, {"kid"})


def test_log_lines_are_read_in_the_event_time_zone(tmp_path):
    found = hits(tmp_path)
    assert len(found) == len(LINES) - 1  # the broken line is skipped
    assert found[0].when == dt.datetime(2026, 10, 31, 10, 5, tzinfo=TZ) and found[0].query == {"e": "open", "r": "a1"}
    assert {h.agent for h in found if "WhatsApp" in h.path or h.path.startswith("/og")} == {"preview"}


def test_counts_people_actions_and_leave_robots_out(tmp_path):
    n = numbers(tmp_path)
    assert n["reach"]["opens"] == 3 and n["reach"]["phone"] == 2 and n["reach"]["computer"] == 1
    assert n["reach"]["per_hour"] == {"2026-10-31 10:00": 2, "2026-10-31 11:00": 1}
    assert n["reach"]["peak"] == {"hour": "2026-10-31 10:00", "opens": 2}
    assert n["reach"]["photo_views"] == 3 and n["reach"]["link_visits"] == 1
    assert n["brand"]["by_format"] == {"feed": 1, "story": 1}
    assert n["brand"]["by_frame"] == {"Hexágonos": 1, "Divertida": 1} and n["brand"]["fun_picks"] == 1
    assert n["brand"]["links_pasted"] == 2  # the WhatsApp card and the LinkedIn one; not the page fetch
    assert n["find"] == {"searches": 2, "by_result": {"0": 1, "1-5": 1, "6+": 0, "erro": 0}, "camera": 1, "photo": 1}
    assert n["venue"]["wall_hours"] == 0.5
    assert n["day"]["photographers"] == {"Ana": 2, "Bia": 1}


def test_minors_stay_out_of_the_highlights(tmp_path):
    opened = numbers(tmp_path)["highlights"]["opened"]
    assert [(p["id"], p["n"], p["moment"]) for p in opened] == [("a--1", 2, "Abertura")]


def test_rounds_give_the_time_from_photo_to_gallery(tmp_path):
    rounds = [{"published": "2026-10-31T10:10:00-03:00", "uploads": 4, "new": ["a--1", "kid"], "total": 2}]
    day = numbers(tmp_path, rounds)["day"]
    assert day["received"] == 4 and day["rounds"][0]["median_minutes"] == 25 and day["rounds"][0]["new"] == 2


def test_the_report_has_its_seven_sections_and_nothing_external(tmp_path):
    html = stats.render({"name": "Evento"}, numbers(tmp_path), {"a--1": b"RIFF....WEBP"})
    headings = re.findall(r"<h2>(.*?)</h2>", html)
    assert headings == ["O dia em números", "Alcance", "Marca em circulação", "Encontrar-se", "No local",
                        "Destaques", "Custo e limites"]
    assert not re.search(r"""(src|href)=["']?https?:""", html) and "data:image/webp;base64," in html
    assert "1 aberturas" not in html and "2 aberturas<" in html and "<svg" in html


def test_an_empty_log_still_gives_a_report(tmp_path):
    (tmp_path / "logs").mkdir()
    n = stats.compute(stats.read_logs(tmp_path / "logs", TZ), {"photos": [], "moments": []}, [], {}, {}, set())
    assert n["reach"]["opens"] == 0 and n["reach"]["peak"] is None
    assert "Sem registros." in stats.render({"name": "E"}, n, {})
