#!/usr/bin/env python3
"""Harvest sentences that name an exact minute from the Caselaw Access Project.

Reads volumes straight from https://static.case.law (public-domain opinions,
published for bulk download), keeps nothing but the candidate sentences, and
steers itself toward the reporters that turn out to mention odd minutes most.

usage: docket_harvest.py <reporters.json> <out_dir> <minutes_budget> <gb_budget>
"""
import sys, os, re, json, io, zipfile, time, random, urllib.request, collections
from concurrent.futures import ProcessPoolExecutor, as_completed

BASE = "https://static.case.law"
UA = {"User-Agent": "docket-clock/0.1 (personal project; bulk static download)"}

# ---- times -----------------------------------------------------------------
NB = r"(?<![\d:.,$#/-])"
AP = r"(?P<ap>[ap])\.?\s?m\b\.?"
P_CLOCK = re.compile(NB + r"(?P<h>1[0-2]|0?[1-9])[:.](?P<m>[0-5]\d)\s?(?:o['’]clock\s)?" + AP, re.I)
P_HOUR = re.compile(NB + r"(?P<h>1[0-2]|[1-9])\s?(?:o['’]clock\s)?(?P<ap>[ap])\.\s?m\.", re.I)
P_MIL = re.compile(NB + r"(?P<h>[01]\d|2[0-3]):?(?P<m>[0-5]\d) hours\b")
P_PART = re.compile(NB + r"(?P<h>1[0-2]|0?[1-9]):(?P<m>[0-5]\d)\s(?:o['’]clock\s)?(?P<part>in the morning|in the afternoon|in the evening|at night|that night|that morning|that evening|that afternoon)", re.I)
P_WORD = re.compile(r"\b(?:at|around|about|until|before|after|approximately|by)\s(?:12(?::00)?\s(?:o['’]clock\s)?)?(?P<w>noon|midnight)\b", re.I)

def find_times(text):
    """Yield (start, end, 'HH:MM') for every time mention, longest pattern first."""
    taken = []
    def free(a, b): return all(b <= x or a >= y for x, y in taken)
    out = []
    for m in P_PART.finditer(text):
        h, mi, part = int(m.group("h")), int(m.group("m")), m.group("part").lower()
        if "morning" in part: h = h % 12
        elif "afternoon" in part or "evening" in part: h = h % 12 + 12
        else: h = (h % 12) if h in (12, 1, 2, 3, 4, 5) else h % 12 + 12
        out.append((m.start(), m.start() + len(m.group(0)) - len(m.group("part")) - 1, "%02d:%02d" % (h, mi))); taken.append((m.start(), m.end()))
    for m in P_CLOCK.finditer(text):
        if not free(m.start(), m.end()): continue
        h = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "p" else 0)
        out.append((m.start(), m.end(), "%02d:%02d" % (h, int(m.group("m"))))); taken.append((m.start(), m.end()))
    for m in P_HOUR.finditer(text):
        if not free(m.start(), m.end()): continue
        h = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "p" else 0)
        out.append((m.start(), m.end(), "%02d:00" % h)); taken.append((m.start(), m.end()))
    for m in P_MIL.finditer(text):
        if not free(m.start(), m.end()): continue
        out.append((m.start(), m.end(), "%02d:%02d" % (int(m.group("h")), int(m.group("m"))))); taken.append((m.start(), m.end()))
    for m in P_WORD.finditer(text):
        a = m.start("w") if not re.match(r".*12", m.group(0)) else m.start() + m.group(0).index("12")
        if not free(a, m.end()): continue
        out.append((a, m.end(), "12:00" if m.group("w").lower() == "noon" else "00:00")); taken.append((a, m.end()))
    return sorted(out)

# ---- sentences -------------------------------------------------------------
ABBR = set("Mr Mrs Ms Dr Jr Sr St No Nos Co Corp Inc Ltd v vs Id id Cf cf Sgt Lt Det Capt Ofc Cpl Dep Gen Gov Hon Rev Prof Ave Blvd Rd Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec Tr Ex Exh App Supp Cir Ct Rptr Stat Ann Sec Art Ch cl para pp op cit ed al Bros Mfg Ry Tel Ins Assn Dept Dist Div Univ Pet Resp Def Pl Mt Ft Messrs Esq Atty Supt Insp Cmdr Col Maj Pvt Spec approx est etc viz Ill Cal Mass Pa Tex Fla Mich Minn Wis Ind Ala Ga Ky Tenn Mo Kan Neb Okla Ark Miss La Va Md Del Conn Vt Me Ore Wash Colo Ariz Nev Mont Wyo Ida Dak".split())
STARTERS = set("The He She It They We A An At In On When After Before Upon There This That These Those His Her Their As While Later Then Shortly Approximately Around About Between During By From Once Although Because If Neither Both According However Thereafter Meanwhile Subsequently Also Thus But And Within Until Since No Not Some Several Two Three Four Five One Each All Another Other Such What Where Who Why How Having Being Finally Earlier Sometime Nothing Nobody Everyone Either Instead Here Now Next Minutes Moments Hours".split())
BOUND = re.compile(r'([.?!])(["”’\')]*)\s+(?=["“‘(]?[A-Z])')

def sentence_spans(par):
    spans, start = [], 0
    for m in BOUND.finditer(par):
        if m.group(1) == ".":
            before = par[:m.start()]
            nxt = re.match(r'["“‘(]?([A-Za-z]+)', par[m.end():])
            nw = nxt.group(1) if nxt else ""
            if re.search(r"\b[ap]\.?\s?m$", before, re.I):
                if nw not in STARTERS: continue
            else:
                w = re.search(r"([A-Za-z]+)$", before)
                w = w.group(1) if w else ""
                if w in ABBR or len(w) == 1: continue
        spans.append((start, m.end(2))); start = m.end()
    spans.append((start, len(par)))
    return spans

# ---- filters ---------------------------------------------------------------
HARD = re.compile(r"\b(rap(?:e|ed|es|ing|ist)|sexual\w*|sex|molest\w*|sodom\w*|incest\w*|porn\w*|genital\w*|penis|vagina\w*|anal|oral sex|fondl\w*|intercourse|naked|nude|suicid\w*|infant|bab(?:y|ies)|toddler|fetus|unborn|decapitat\w*|dismember\w*|strangl\w*|autops\w*|corpse|semen|prostitut\w*|abus\w*|lynch\w*|nigger\w*|negro\w*|colored|mulatto|child|children|juvenile\w*|teen\w*|girl|boy|schoolgirl|schoolboy|pregnan\w*|miscarr\w*|abort\w*|whipp\w*|slave\w*|mutilat\w*|tortur\w*|execution|executed|electrocut\w*|gas chamber|lethal injection|hanged)\b", re.I)
SOFT = re.compile(r"\b(shot|shoot\w*|gun\w*|stab\w*|kill\w*|dead|death|died|dying|body|bodies|murder\w*|blood\w*|weapon\w*|robb\w*|assault\w*|victim\w*|overdos\w*|heroin|cocaine|crack|meth\w*|fatal\w*|wound\w*|beat|beaten|beating|bullet\w*|knife|knives|firearm\w*|rifle|pistol|revolver|unconscious|bleeding|deceased|decedent|homicide|manslaughter|kidnap\w*|hostage\w*|arson|burn\w*|drown\w*|injur\w*|hospital\w*|ambulance|emergency room|pronounced|morgue|coroner|funeral|drunk\w*|intoxicat\w*|marijuana|drug\w*|narcotic\w*)\b", re.I)
GUNK = re.compile(r"(\bId\.|\bsupra\b|\binfra\b|[§¶\[\]{}|^*_•■□▪~<>=+]|\bat \d+[,;.)]|\b\d+ (?:F\.|U\.S\.|S\. ?Ct|P\.|N\.E\.|N\.W\.|S\.W\.|S\.E\.|So\.|A\.|Cal\.|N\.Y\.)|\bR\. ?at\b|\bTr\. |\bRT\b|\bCT\b|\bExh?\.|\bEx\. |\bNo\. \d|\bDoc\. |\bECF\b|\bDkt\b|\bStat\.|\bU\.S\.C|\bC\.F\.R|\b(?:see|See|citing|quoting) |\bet seq|\bibid|\bop\. cit)")
YOUNG = re.compile(r"\b(\d{1,2})[- ](?:year|yr)s?[- ]old")

def clean(q):
    return re.sub(r"\s+", " ", q).strip()

def harvest_opinion(text):
    out = []
    for par in text.split("\n"):
        if len(par) < 50 or len(par) > 6000: continue
        times = find_times(par)
        if not times: continue
        spans = sentence_spans(par)
        for (a, b, key) in times:
            hit = [(s, e) for (s, e) in spans if s <= a < e]
            if not hit: continue
            s, e = hit[0]
            if b > e: continue
            raw = par[s:e]
            lead = len(raw) - len(raw.lstrip())
            q = raw.strip()
            if not (45 <= len(q) <= 320): continue
            if not re.match(r'["“‘]?[A-Z][a-z]', q) and not re.match(r'["“‘]?(?:A|I) ', q): continue
            if not re.search(r'[.!?]["”’\']?$', q): continue
            if GUNK.search(q) or HARD.search(q): continue
            y = YOUNG.search(q)
            if y and int(y.group(1)) < 18: continue
            if sum(c.isupper() for c in q) > 0.18 * len(q): continue
            if re.search(r"\d{5,}|\.{3,}|\s[,;:]|[a-z][A-Z]{2,}|\b[b-df-hj-np-tv-z]{6,}\b", q): continue
            i, j = a - s - lead, b - s - lead
            if i < 0 or re.sub(r"\s+", " ", q) != q: continue
            n = sum(1 for (x, yy, _) in times if s <= x < e)
            out.append({"k": key, "q": q, "s": [i, j], "n": n, "soft": len(SOFT.findall(q))})
    return out

def work(job):
    """Download one volume, return (job, megabytes, n_cases, candidates)."""
    rep, vol = job
    try:
        req = urllib.request.Request("%s/%s/%s.zip" % (BASE, rep, vol), headers=UA)
        blob = urllib.request.urlopen(req, timeout=180).read()
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as ex:
        return (job, 0.0, 0, [], repr(ex)[:80])
    cands, n_cases = [], 0
    for name in z.namelist():
        if not (name.startswith("json/") and name.endswith(".json")): continue
        try: c = json.loads(z.read(name))
        except Exception: continue
        n_cases += 1
        cite = next((x["cite"] for x in c.get("citations", []) if x.get("type") == "official"), "")
        meta = {"c": c.get("name_abbreviation", ""), "ct": (c.get("court") or {}).get("name_abbreviation", ""), "ctn": (c.get("court") or {}).get("name", ""),
                "y": (c.get("decision_date") or "")[:4], "cite": cite, "r": rep, "v": vol, "f": c.get("file_name", "")}
        seen = set()
        for o in (c.get("casebody") or {}).get("opinions", []):
            for cand in harvest_opinion(o.get("text") or ""):
                if cand["q"] in seen: continue
                seen.add(cand["q"]); cand.update(meta); cand["op"] = o.get("type", ""); cands.append(cand)
    return (job, len(blob) / 1e6, n_cases, cands, "")

def volumes_of(rep):
    try:
        req = urllib.request.Request("%s/%s/VolumesMetadata.json" % (BASE, rep), headers=UA)
        return rep, [v["volume_folder"] for v in json.loads(urllib.request.urlopen(req, timeout=60).read())]
    except Exception:
        return rep, []

def main():
    reporters, out_dir, minutes, gb = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    t0 = time.time()
    prior_path = os.path.join(out_dir, "stats.json")
    prior = json.load(open(prior_path)) if os.path.exists(prior_path) else None
    rng = random.Random(1440 if not prior else int(t0))      # a later pass draws different volumes
    reps = [r["slug"] for r in json.load(open(reporters))]
    log = open(os.path.join(out_dir, "progress.log"), "a"); out = open(os.path.join(out_dir, "candidates.jsonl"), "a")
    def say(*a):
        line = "[%5.1f min] " % ((time.time() - t0) / 60) + " ".join(str(x) for x in a)
        log.write(line + "\n"); log.flush()
    workers = min(10, (os.cpu_count() or 4))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        vols = dict(pool.map(volumes_of, reps, chunksize=8))
        vols = {r: v for r, v in vols.items() if v}
        for v in vols.values(): rng.shuffle(v)
        say("reporters with volumes:", len(vols), "| volumes total:", sum(map(len, vols.values())), "| workers:", workers)
        clean_n = collections.Counter(); any_n = collections.Counter()
        stat = collections.defaultdict(lambda: [0.0, 0, 0, 0])   # mb, volumes, needed-hits, all-hits
        done_mb = 0.0; done_vols = 0; rnd = 0
        if prior:
            # A second pass starts from what the first one learned: which minutes are
            # still thin, and which reporters have been worth the download.
            any_n.update(prior["any"]); clean_n.update(prior["clean"])
            for r, v in prior["stat"].items(): stat[r] = list(v)
            done = collections.defaultdict(set)
            for line in open(os.path.join(out_dir, "candidates.jsonl")):
                c = json.loads(line); done[c["r"]].add(c["v"])
            for r in vols: vols[r] = [v for v in vols[r] if v not in done[r]]
            rnd = 1
        def need(k): return clean_n[k] < 3
        while True:
            rnd += 1
            if rnd == 1:
                jobs = [(r, v.pop()) for r, v in vols.items() if v]
            else:
                # Spend the next batch where odd, still-missing minutes have been turning up.
                live = [r for r in vols if vols[r]]
                if not live: break
                w = [((stat[r][2] + 0.3) / (stat[r][0] + 1.5)) ** 1.5 for r in live]
                picks = collections.Counter(rng.choices(live, weights=w, k=160))
                jobs = [(r, vols[r].pop()) for r, n in picks.items() for _ in range(min(n, len(vols[r])))]
            for fut in as_completed([pool.submit(work, j) for j in jobs]):
                (rep, vol), mb, n_cases, cands, err = fut.result()
                done_mb += mb; done_vols += 1; s = stat[rep]; s[0] += mb; s[1] += 1
                for c in cands:
                    k = c["k"]; any_n[k] += 1; s[3] += 1
                    is_clean = c["n"] == 1 and c["soft"] == 0
                    if is_clean and need(k): s[2] += 1
                    if is_clean: clean_n[k] += 1
                    if any_n[k] <= 600 or is_clean and clean_n[k] <= 400: out.write(json.dumps(c, ensure_ascii=False) + "\n")
            out.flush()
            c1 = sum(1 for h in range(24) for m in range(60) if any_n["%02d:%02d" % (h, m)] >= 1)
            k1 = sum(1 for h in range(24) for m in range(60) if clean_n["%02d:%02d" % (h, m)] >= 1)
            k3 = sum(1 for h in range(24) for m in range(60) if clean_n["%02d:%02d" % (h, m)] >= 3)
            top = sorted(stat.items(), key=lambda kv: -kv[1][2])[:8]
            say("round", rnd, "| volumes", done_vols, "| %.0f MB" % done_mb, "| candidates", sum(any_n.values()), "| minutes any>=1:", c1, "clean>=1:", k1, "clean>=3:", k3,
                "| best:", " ".join("%s:%d/%.0fMB" % (r, s[2], s[0]) for r, s in top))
            json.dump({"any": any_n, "clean": clean_n, "stat": stat, "mb": done_mb, "vols": done_vols}, open(os.path.join(out_dir, "stats.json"), "w"))
            if (time.time() - t0) / 60 > minutes or done_mb / 1000 > gb or (k1 >= 1436 and k3 >= 1380): break
        say("DONE", "volumes", done_vols, "%.0f MB" % done_mb)

if __name__ == "__main__":
    main()
