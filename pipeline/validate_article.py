#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_article.py — strukturální kontrola nového blogového článku
===================================================================

Bezpečnostní brána content agenta: článek se publikuje jen, když projde.
Kontroluje strukturu a zapojení do webu; věcnou správnost čísel hlídá
check_blog_consistency.py (spouští se hned po tomto skriptu).

    python3 pipeline/validate_article.py blog-<slug>.html   # exit != 0 při chybě
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fail(msgs):
    print("VALIDACE SELHALA:")
    for m in msgs:
        print("  ✗", m)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print("použití: validate_article.py <blog-soubor.html>")
        sys.exit(2)
    fname = os.path.basename(sys.argv[1])
    path = os.path.join(ROOT, fname)
    errors = []

    if not re.fullmatch(r"blog-[a-z0-9-]+\.html", fname):
        fail([f"název souboru musí být blog-<slug>.html, je: {fname}"])
    if not os.path.exists(path):
        fail([f"soubor {fname} neexistuje"])

    html = open(path, encoding="utf-8").read()
    size = len(html.encode("utf-8"))

    # velikost v pásmu ostatních článků
    if not (6_000 <= size <= 30_000):
        errors.append(f"velikost {size} B mimo pásmo 6–30 kB")

    # základní struktura
    checks = [
        ('<html lang="cs">', "chybí lang=cs"),
        ("<title>", "chybí <title>"),
        ('name="description"', "chybí meta description"),
        ('rel="canonical"', "chybí canonical"),
        ("application/ld+json", "chybí JSON-LD"),
        ('class="art"', "chybí <article class=art>"),
        ("index.html#analyzer", "chybí odkaz na kalkulačku"),
        ("nav-burger", "chybí mobilní menu (hamburger)"),
        ("assets/consent.js", "chybí consent.js"),
        ('class="note"', "chybí závěrečná poznámka se zdroji"),
        ("</footer>", "chybí footer"),
    ]
    for needle, msg in checks:
        if needle not in html:
            errors.append(msg)

    # počet h1 přesně 1
    h1s = len(re.findall(r"<h1[ >]", html))
    if h1s != 1:
        errors.append(f"počet <h1> = {h1s}, má být 1")

    # meta description 50–160 znaků
    m = re.search(r'name="description" content="([^"]*)"', html)
    if m and not (50 <= len(m.group(1)) <= 160):
        errors.append(f"meta description má {len(m.group(1))} znaků (má být 50–160)")

    # JSON-LD musí být parsovatelné
    for ld in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            json.loads(ld)
        except json.JSONDecodeError as e:
            errors.append(f"JSON-LD neparsovatelné: {e}")

    # žádné zbylé placeholdery
    for bad in ("TODO", "[doplň", "XXX", "lorem"):
        if bad.lower() in html.lower():
            errors.append(f"zbylý placeholder: {bad}")

    # zapojení: blog.html + sitemap.xml musí odkazovat
    blog = open(os.path.join(ROOT, "blog.html"), encoding="utf-8").read()
    if fname not in blog:
        errors.append(f"blog.html neodkazuje na {fname} (chybí karta článku)")
    sitemap = open(os.path.join(ROOT, "sitemap.xml"), encoding="utf-8").read()
    if fname not in sitemap:
        errors.append(f"sitemap.xml neobsahuje {fname}")

    # topics.csv: přesně jedno téma nově done… (kontrola, že agent odškrtl)
    topics = open(os.path.join(ROOT, "pipeline", "topics.csv"), encoding="utf-8").read()
    slug = fname[len("blog-"):-len(".html")]
    row = next((l for l in topics.splitlines() if f",{slug}," in l), None)
    if row is None:
        errors.append(f"slug {slug} není v pipeline/topics.csv")
    elif not row.startswith("done,"):
        errors.append(f"téma {slug} v topics.csv nemá status done")

    if errors:
        fail(errors)
    print(f"OK — {fname} prošel strukturální validací ({size} B, 1×h1, "
          "JSON-LD ✓, blog.html ✓, sitemap ✓, topics ✓).")


if __name__ == "__main__":
    main()
