#!/usr/bin/env python3
"""Choose the sentences the Docket Clock shows.

Reads the harvested candidates, scores each one for how well it reads as a
line on a clock, and writes data/HH.json (up to three sentences per minute)
plus data/index.json (how often each minute turned up at all).

usage: curate.py <candidates.jsonl> <stats.json> <out_data_dir> [removed.txt] [--show H0 H1]

The rules here do the coarse work: they prefer a sentence that opens with its
time, reads cleanly and is about an alarm, a train or a jury, and they refuse
anything about violence, illness, sex or children. They are not enough on
their own. With --show the script prints its pick for each minute so that a
person can read them; ids of sentences to take out go in removed.txt, and the
script is run again. That loop was repeated until a pass turned up nothing
new. The long word lists below are the residue of that reading.
"""
import sys, os, re, json, collections, hashlib

TIME_FIRST = re.compile(r'^["“]?(?:At|Around|About|By|Until|Before|After|Shortly (?:before|after)|Just (?:before|after)|Sometime (?:before|after|around)|At (?:about|around|approximately|or about|or around)|Approximately|On [A-Z][a-z]+ \d{1,2}, \d{4},? at(?: about| approximately)?|That (?:night|morning|evening|afternoon),? at(?: about| approximately)?)\s*$')
CHARM = re.compile(r"\b(tele(?:phone|gram|graph)\w*|phoned?|call(?:ed|s)?|train|locomotive|engine(?:er)?|conductor|whistle|depot|station|streetcar|trolley|bus|taxi|cab|truck|wagon|horses?|mule|ferry|steamer|ship|boat|pilot|airport|flight|plane|elevator|door(?:bell)?|knock\w*|lights?|lamp|window|porch|kitchen|coffee|restaurant|diner|tavern|saloon|store|shop|bank|motel|hotel|parking lot|street|avenue|highway|bridge|rain\w*|snow\w*|fog\w*|dark\w*|jury|jurors?|verdict|deliberat\w*|foreman|courtroom|radio\w*|dispatch\w*|alarm|clock|watch|dog|fax\w*|e-?mail\w*|text message|voicemail|letter|newspaper|television|movie|theat(?:er|re)|church|school|office|factory|mill|mine|farm|barn|river|lake|beach|sunrise|sunset|moon\w*|storm|wind|shift|bed|asleep|awake|woke|sleep\w*|dinner|lunch|breakfast|supper|midnight|noon|dawn|dusk)\b", re.I)
LEGALESE = re.compile(r"\b(pursuant|aforesaid|hereinafter|hereinbefore|thereof|therein|thereto|appellant|appellee|petitioner|respondent|movant|claimant|decedent|said (?:train|car|defendant|plaintiff|day)|the instant|supra|infra)\b", re.I)
ANON = re.compile(r"\b[A-Z]\.[A-Z]\.(?:[A-Z]\.)?|\bJohn Doe|\bJane Doe|\b[A-Z][a-z]+ [A-Z]\.(?=\s+[a-z])|\b[A-Z]\. ?[A-Z] (?=received|was|said|told)|\b[A-Z]\.[’']s\b")
# Cases where more than one sentence kept surfacing and none of them belongs on a clock:
# notorious killings, deaths in custody, cases about children. (name fragment, year or None)
CASE_BLOCK = [("People v. Salcido", None), ("State v. McNeill", None), ("McCarthy v. City of Waltha", None), ("Gosciminski", None), ("Perry v. State", "2002"),
    ("United States v. Quarterma", None), ("State v. Hull", "2010"), ("Miskovich", None), ("Duval County School Board", None), ("Roach v. Springfield", None),
    ("State v. King", "2017"), ("King v. State", "2017"), ("People v. Knoller", None), ("Jahr v. District", None), ("Texasgulf", None), ("People v. Coffman", None),
    ("People v. Daveggio", None), ("Commonwealth v. Frein", None), ("State v. Fukusaku", None), ("Norwood v. State", None), ("People v. Sims", "1993"),
    ("Espinosa v. City", None), ("Calloway v. Kinkelaar", None), ("People v. Steidl", None), ("Swearingen v. Carle", None), ("Rasnick v. Krishna", None),
    ("Bristol ex rel", None), ("State v. Declerck", None), ("State v. Mumma", None), ("State v. Johnson", "2000"), ("Weaver v. Stewart", None),
    ("Rhodes v. Illinois Central", None), ("People v. Edwards", "1991"), ("Edwards v. United States D", None), ("People v. Butler", "1975"), ("State v. Mingo", None),
    ("State v. Achelles", None), ("State v. Bowers", "1999"), ("Glasscock", None), ("Simmons v. Garces", None), ("Cherry v. Macon", None), ("Limonja", None),
    ("Ray v. Civil Service", None), ("Wallace v. State", "2014"), ("State v. Hart", "2015"), ("People v. D.C.", None), ("Tiedeman", None), ("Heggs v. Grant", None),
    ("People v. Edwards", None), ("King v. State", "2012"), ("Tucker v. Pearce", None), ("Levenson v. Lake-To-Lake", None), ("Deckman v. Deckman", None),
    ("Grenier v. Stratton", None), ("State v. Hughes", "2010"), ("Syed v. State", None), ("State v. Peterson", "2006"), ("Valore v. Islamic", None), ("State v. Beasley", None),
    ("State v. Andersen", "2010"), ("Nisbett", None), ("Danese v. Asman", None), ("State v. Cox", "2017"), ("Bhakta v. Director", None),
    ("People v. Davis", "2009"), ("State v. Avery", None), ("People v. Hochstraser", None), ("Commonwealth v. Cosby", None), ("Commonwealth v. Hernandez", None),
    ("People v. Ramirez", None), ("State v. Skakel", None), ("People v. Gacy", None), ("Bundy v. State", None), ("People v. Kraft", None), ("People v. Ng", None),
    ("United States v. McVeigh", None), ("United States v. Tsarnaev", None), ("Anthony v. State", None), ("Zimmerman v. State", None), ("People v. Peterson", None)]
def case_blocked(c):
    return any(frag in c.get("c", "") and (yr is None or c.get("y") == yr) for frag, yr in CASE_BLOCK)
KEEP = 1
JURY = re.compile(r"\b(jur(?:y|ors?)|verdict\w*|deliberat\w*|foreman|foreperson|forelady)\b", re.I)
# A second, stricter read of the same sentence. The harvester already drops the
# worst subjects; this keeps the clock from leaning on violence at all.
GRIM = re.compile(r"\b(shot|shoot\w*|gun\w*|stab\w*|kill\w*|dead|death|died|dying|bod(?:y|ies)|murder\w*|blood\w*|weapon\w*|robb\w*|assault\w*|victim\w*|overdos\w*|heroin|cocaine|fatal\w*|wound\w*|beat(?:en|ing)?|bullet\w*|knife|knives|firearm\w*|rifle|pistol|revolver|unconscious|bleeding|deceased|homicide|manslaughter|kidnap\w*|hostage\w*|arson|drown\w*|morgue|coroner|funeral|pronounced|cardiac|seizure|surgery|ventilator|life support|resuscitat\w*|stillb\w*|labor|deliver(?:y|ed) (?:of|the)|contraction\w*|patient\w*|nurse\w*|hospital\w*|emergency room|ambulance|paramedic\w*|EMT\w*|injur\w*|crash\w*|collision|collided|wreck\w*|struck by|hit by|hang(?:ing|ed)|hung|noose|shots?|gunshot\w*|GSR|EMS|emergency medical|indecent\w*|lewd\w*|obscen\w*|peep\w*|exposure|exposed|mental\w*|psychiatr\w*|schizophren\w*|bipolar|disturbed|committed to|retard\w*|handicap\w*|disabled|a minor|minors|cancer|tumor|stroke|heart attack|dementia|alzheimer\w*|diabet\w*|epilep\w*|HIV|AIDS|addict\w*|alcoholi\w*|homeless|vagrant|welfare|deport\w*|illegal alien|immigra\w*|race|racial|black (?:male|man|men|female|woman)|white (?:male|man|men|female|woman)|hispanic|mexican|oriental|indian|gay|lesbian|homosexual\w*|transgender|transvest\w*|affair|adulter\w*|mistress|lover|divorce\w*|pregnant|asystole|pulse|CPR|expired|lifeless|unresponsive|assailant\w*|attack\w*|molot\w*|bomb\w*|explo\w*|rampage|massacre|terror\w*|riot\w*|klan|nazi\w*|slap\w*|punch\w*|kick\w*|chok\w*|bruis\w*|crying|cried|sobbing|hysterical|frantic\w*|scared|afraid|terrified|begg\w*|plead(?:ed|ing) (?:for|with)|missing|runaway|abduct\w*|lure\w*|stalk\w*|harass\w*|restraining order|protective order|trespass\w*|vandal\w*|prowl\w*|loiter\w*|panhandl\w*|shoplift\w*|larceny|felony|misdemeanor|probation|parole\w*|sentenced|incarcerat\w*|penitentiary|reformatory|workhouse|asylum|sanitarium|insane|lunatic|idiot|imbecile|cripple\w*|deaf|dumb|blind|pussy|fuck\w*|cunt|bitch\w*|whore\w*|slut\w*|shit\w*|asshole|blow ?job|horny|sext\w*|suck\w*|rectal|cervi\w*|dilat\w*|uter\w*|fetal|epidural|anesthe\w*|incision|catheter|intubat\w*|hemorrhag\w*|vomit\w*|urin\w*|feces|diarrhea|nause\w*|decedent\w*|struck|altercation\w*|cutting|calls? for help|on the floor|forcibl\w*|pushed|shov\w*|negotiat\w*|heart stopped|standoff|barricad\w*|Mirandiz\w*|disturbing|distraught|upset|bang(?:ed|ing)|pound(?:ed|ing) on|break(?:ing)? in(?:to)?|broke in(?:to)?|broken into|intruder\w*|masked|ski mask|gunpoint|hold-?up|stick-?up|getaway|complainant\w*|passed away|blown up|copulat\w*|African[- ]American\w*|black (?:males|youths?|women|couple)|white (?:males|youths?|women|couple)|complexion|ransom|laser|womb|umbilical|heart rate|beats per minute|medics?|medical (?:emergency|examiner|advice)|operating room|airway|endotracheal|pronouncement|pain\w*|excruciat\w*|respiratory|scream\w*|yelling|prosecutrix|fractur\w*|person down|lying (?:face|on|behind|partially)|face down|still breathing|tactical|SWAT|Last Will|pedestrian\w*|telemetry|EKG|ICU|surgeon\w*|chemical test\w*|Intoxilyzer|Breathalyzer|DataMaster|excited utterance|implor\w*|saliva|carjack\w*|perimeter|youth officer|apolog\w*|wrapped in a blanket|execut\w*|slipped in|sleeping mat|x-ray\w*|radiolog\w*|feeding tube|lungs?|C-section|caesarean|cesarean|membranes|biophysical|insulin|dextrose|intraven\w*|physician\w*|trauma\w*|helicopter|evacuat\w*|disappear\w*|last (?:incoming |outgoing )?call|never answered|no answer|did not answer|posing as|how old|cannabinoid\w*|specimen|blood sample|incoherent\w*|slurred|swaying|finger-to-nose|walk and turn|battery|the crime|wrongful|barracks|takeoff|hit something|sister|her home|his home|residence of|sleeping quietly|blood test\w*|breath test\w*|blood alcohol|electrocardiogram|lidocaine|injection\w*|observation status|domestic violence|night auditor|crime scene|blood was drawn|ambulance|rescue truck|cell block|handcuff\w*|\bear\b)\b", re.I)
# Milder, but a clock made mostly of arrests would be a bleak clock.
LOW = re.compile(r"\b(arrest\w*|charged|convicted|intoxicat\w*|drunk\w*|DUI|DWI|OWI|OUI|breath\w*|sobriety|handcuff\w*|custody|jail\w*|inmate\w*|prison\w*|booked|booking|Miranda|confess\w*|interrogat\w*|suspect\w*|warrant\w*|narcotic\w*|drugs?|marijuana|methamphetamine|contraband|stolen|theft|fled|fleeing|pursuit|chase[ds]?|domestic|disturbance|fight\w*|argu(?:ed|ing|ment)|threat\w*|yell\w*|scream\w*)\b", re.I)
FAMILY = re.compile(r"\b(husband|wife|ex-wife|ex-husband|girlfriend|boyfriend|fianc[eé]e?|mother|father|son|daughter|sister|brother|step\w+|grand(?:mother|father|son|daughter|parents?)|uncle|aunt|nephew|niece|rights|waiver)\b", re.I)
WHO = re.compile(r"^[\s,]*(?:on [A-Z][a-z]+ \d{1,2}, \d{4},?\s*)?(?:the |a |an )?(?:Officers?|Deputy|Trooper|Sergeant|Detective|Patrolman|Corporal|Lieutenant|dispatch\w*|alarm|burglar alarm|silent alarm|call|telephone|train|jury|court|clerk|judge|operator|engineer|conductor|watchman|guard|nurse|pilot|driver|bartender|waitress|neighbor)\b", re.I)
BAD_CASE = re.compile(r"Health & H|Human Serv|Children|Child\b|Family Serv|Social Serv|\bDCFS\b|\bCPS\b|\bex rel\. \w+ v\.|\bDoe\b|\bRoe\b|^In re\b|^In the (?:Matter|Interest)\b|^Matter of|^Interest of|Adoption|Guardianship|Custody|Juvenile|Commitment|\b[A-Z][a-z]+ [A-Z]\.(?: v\.|,|$)|^[A-Z]\.[A-Z]\.")
OCR = re.compile(r"[a-z]- [a-z]|\s-[a-z]|[a-z]'(?!clock)[a-z]{4,}|\b[a-z]+[A-Z][a-z]+|\d,\d{4}\b|\s[.,;]\s|\b(?:tbe|tiie|bis|tlie|wbo|aud|tbat|witb|bave)\b")

def score(c):
    q, (i, j) = c["q"], c["s"]
    sc = 0.0
    sc += 3 if c["n"] == 1 else (0 if c["n"] == 2 else -4)
    grim = len(GRIM.findall(q)) + (2 if BAD_CASE.search(c.get("c", "")) or case_blocked(c) else 0) + (1 if ANON.search(q) else 0)
    sc -= 2.5 * min(grim, 3)
    sc -= 1.5 * min(len(LOW.findall(q)), 2)
    if WHO.match(q[j:j + 60]): sc += 1
    sc -= 1.2 * min(len(FAMILY.findall(q)), 2)
    broken = bool(OCR.search(q)) or q.count("“") != q.count("”") or q.count('"') % 2 == 1 or bool(re.search(r"\bExs?\.|\bpp\. ?\d|\(Pis|^Email from|\bT\. \d+\.|\b[A-Z]{5,}\b|\w'\s|\s'\w|[a-z]\.[a-z]{2,}|,,|\band\.$", q))    # OCR damage, or a quotation cut in half
    if broken: sc -= 4; grim += 1
    if TIME_FIRST.match(q[:i]): sc += 2.5
    elif i < 40: sc += 1
    L = len(q)
    sc += 2 if 70 <= L <= 170 else (1 if 55 <= L <= 230 else 0)
    sc += min(len(set(m.lower() for m in CHARM.findall(q))), 3) * 1.0
    sc -= min(len(LEGALESE.findall(q)), 3) * 1.0
    if ANON.search(q): sc -= 3
    y = int(c["y"]) if c["y"].isdigit() else 2000
    sc += 1.5 if y < 1950 else (0.5 if y < 1990 else 0)
    others = len(re.findall(r"\d+", q[:i] + q[j:]))
    if others > 2: sc -= 1 + 0.5 * (others - 3)
    if re.search(r"\b(?:approximately|about|around)\b", q[:i][-20:], re.I): sc -= 0.3
    if q.count(",") > 5: sc -= 1
    if re.match(r'^["“]?(?:And|But|Or|Thus|Therefore|Accordingly|Moreover|Furthermore|However|Further|Additionally|In addition|Specifically|Indeed|Rather|Instead|Nevertheless)\b', q): sc -= 1.5
    if c.get("op") in ("dissent", "concurrence"): sc -= 0.3
    if not c.get("c") or not c.get("cite") or not c.get("y"): sc -= 5
    c["grim"] = grim; c["low"] = len(LOW.findall(q))
    return sc

def court_label(c):
    return (c.get("ct") or "").strip()

def main():
    cand_path, stats_path, out_dir = sys.argv[1:4]
    rest = sys.argv[4:]
    show = None
    if "--show" in rest:
        k = rest.index("--show"); show = (int(rest[k + 1]), int(rest[k + 2])); rest = rest[:k]
    block = set()
    if rest and os.path.exists(rest[0]):
        block = {w for l in open(rest[0]) if not l.startswith("#") for w in l.split()}
    by = collections.defaultdict(list); seen = set(); total = 0
    for line in open(cand_path):
        c = json.loads(line); total += 1
        key = re.sub(r"\W+", "", c["q"].lower())[:160]
        if key in seen: continue
        seen.add(key)
        c["id"] = hashlib.sha1(c["q"].encode()).hexdigest()[:8]
        if c["id"] in block: continue
        c["score"] = score(c); by[c["k"]].append(c)
    stats = json.load(open(stats_path))
    keys = ["%02d:%02d" % (h, m) for h in range(24) for m in range(60)]
    picked = {}; recent = []
    for k in keys:
        pool = sorted(by.get(k, []), key=lambda c: -c["score"])
        chosen, cases = [], set()
        for c in pool:
            if chosen and (c["score"] < 6.0 or c["grim"] or c["low"]): continue   # alternates: clean or not at all
            if c["grim"] > 0: continue
            ck = (c["c"], c["y"])
            if ck in cases: continue
            cases.add(ck); chosen.append(c)
            if len(chosen) == KEEP: break
        if chosen and JURY.search(chosen[0]["q"]) and sum(1 for p in recent[-3:] if p) >= 2:
            alt = next((c for c in pool if not JURY.search(c["q"]) and not c["grim"] and not c["low"] and c["score"] >= chosen[0]["score"] - 3.0), None)
            if alt: chosen = [alt]
        recent.append(bool(chosen and JURY.search(chosen[0]["q"])))
        picked[k] = chosen
    if show:
        for k in keys:
            h = int(k[:2])
            if not (show[0] <= h < show[1]): continue
            if not picked[k]: print("%s  --" % k); continue
            c = picked[k][0]; i, j = c["s"]
            print("%s %s| %s[%s]%s (%s %s)" % (k[3:] if k[3:] != "00" else k, c["id"], c["q"][:i], c["q"][i:j], c["q"][j:][:230 - min(i, 200)], c["c"][:26], c["y"]))
        return
    os.makedirs(out_dir, exist_ok=True)
    for h in range(24):
        day = {}
        for m in range(60):
            k = "%02d:%02d" % (h, m)
            if picked[k]:
                day[k] = [{"q": c["q"], "s": c["s"], "c": c["c"], "ct": court_label(c), "y": c["y"], "cite": c["cite"],
                           "u": "https://static.case.law/%s/%s/html/%s.html" % (c["r"], c["v"], c["f"])} for c in picked[k]]
        json.dump(day, open(os.path.join(out_dir, "%02d.json" % h), "w"), ensure_ascii=False, separators=(",", ":"))
    counts = [min(int(stats["any"].get(k, 0)), 999) for k in keys]
    json.dump({"counts": counts, "volumes": stats["vols"], "found": int(sum(stats["any"].values())), "shown": sum(len(v) for v in picked.values()),
               "silent": [k for k in keys if not picked[k]]}, open(os.path.join(out_dir, "index.json"), "w"), separators=(",", ":"))
    n1 = sum(1 for k in keys if picked[k]); n3 = sum(1 for k in keys if len(picked[k]) == 3)
    grim = sum(1 for k in keys for c in picked[k] if c["grim"])
    print("candidates read:", total, "| distinct:", len(seen), "| minutes filled:", n1, "| with three:", n3, "| sentences shipped:", sum(len(v) for v in picked.values()), "| any grim word:", grim)
    print("silent minutes:", [k for k in keys if not picked[k]])
    eras = collections.Counter((int(c["y"]) // 25) * 25 for k in keys for c in picked[k][:1] if c["y"].isdigit())
    print("opening sentence by era:", sorted(eras.items()))

if __name__ == "__main__":
    main()
