"""Parametric question generators: numbers vary, answer keys are computed, so every
generated item is correct by construction. Used for quant, physics and accounting drills."""

import random


def _fmt(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else f"{x:,}"


def _mcq(stem, correct, distractors, explanation, steps, difficulty, rng, unit=""):
    vals = [correct] + [d for d in distractors if d != correct][:3]
    opts = list(dict.fromkeys(vals))[:4]
    bump = 1
    while len(opts) < 4:
        candidate = round(correct * rng.choice([1.1, 0.9, 1.25, 0.8]) + bump, 2)
        bump += 1
        if candidate not in opts and candidate > 0:
            opts.append(candidate)
    rng.shuffle(opts)
    ids = ["a", "b", "c", "d"]
    return {
        "qtype": "mcq",
        "stem": stem,
        "payload": {"options": [{"id": i, "text": f"{_fmt(v)}{unit}"} for i, v in zip(ids, opts, strict=True)], "answer": ids[opts.index(correct)]},
        "explanation": explanation,
        "difficulty": difficulty,
        "steps": steps,
    }


def _num(stem, answer, explanation, steps, difficulty, tolerance=0.01, unit=""):
    return {"qtype": "numerical", "stem": stem, "payload": {"answer": answer, "tolerance": tolerance, "unit": unit}, "explanation": explanation, "difficulty": difficulty, "steps": steps}


def percentage_basics(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        p = rng.choice([5, 12, 15, 20, 25, 35, 40, 62.5, 75, 120])
        x = rng.choice([80, 160, 240, 360, 480, 640, 720, 960])
        ans = round(p * x / 100, 2)
        steps = {
            "hint": "'Per cent' means 'out of 100'. Turn the percentage into a fraction first.",
            "concept": "p% of x = (p/100) × x.",
            "approach": f"Write {p}% as {p}/100 and multiply by {x}.",
            "solution": f"{p}/100 × {x} = {_fmt(ans)}.",
            "shortcut": "Use fraction equivalents: 25% = 1/4, 12.5% = 1/8, 62.5% = 5/8, 20% = 1/5.",
            "mistakes": "Dividing by p instead of 100, or moving the decimal the wrong way.",
        }
        if i % 2 == 0:
            out.append(_mcq(f"What is {p}% of {x}?", ans, [round(ans * 10, 2), round(x / p, 2), round(ans / 2, 2), round(ans + p, 2)], f"{p}% of {x} = {p}/100 × {x} = {_fmt(ans)}.", steps, "easy", rng))
        else:
            out.append(_num(f"Find {p}% of {x}.", ans, f"{p}/100 × {x} = {_fmt(ans)}.", steps, "easy"))
    return out


def percentage_change(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        old = rng.choice([200, 250, 400, 500, 800, 1200, 1600])
        pct = rng.choice([10, 15, 20, 25, 30, 40])
        up = i % 2 == 0
        new = old * (1 + pct / 100) if up else old * (1 - pct / 100)
        new = round(new)
        word = "increases" if up else "decreases"
        steps = {
            "hint": "Percentage change is always measured against the ORIGINAL value.",
            "concept": "% change = (new − old) / old × 100.",
            "approach": f"Find the change {new} − {old}, then divide by the original {old}.",
            "solution": f"({new} − {old}) / {old} × 100 = {'+' if up else '−'}{pct}%.",
            "shortcut": "If the change divided by the original is a known fraction (1/4, 1/5), read the % directly.",
            "mistakes": "Dividing by the new value instead of the old one.",
        }
        out.append(_mcq(f"The price of an item {word} from ₹{old} to ₹{new}. What is the percentage {'increase' if up else 'decrease'}?", pct, [round(abs(new - old) / new * 100, 2), pct + 5, abs(new - old)], f"Change = {abs(new - old)}; {abs(new - old)}/{old} × 100 = {pct}%.", steps, "easy", rng, "%"))
    return out


def successive_percentage(rng: random.Random, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        a, b = rng.choice([(10, 20), (20, 10), (25, 20), (10, 10), (20, 20), (30, 10)])
        net = round(a + b + a * b / 100, 2)
        steps = {
            "hint": "Two successive increases do not simply add: the second acts on an already increased value.",
            "concept": "Net effect of successive changes a% and b% = a + b + ab/100 (use negative signs for decreases).",
            "approach": f"Apply the formula with a = {a}, b = {b}.",
            "solution": f"{a} + {b} + ({a}×{b})/100 = {_fmt(net)}%.",
            "shortcut": "Multiply factors: (1 + a/100)(1 + b/100) − 1.",
            "mistakes": f"Answering {a + b}% by adding the two rates.",
        }
        out.append(_mcq(f"A salary is increased by {a}% and then by {b}%. What is the overall percentage increase?", net, [a + b, round(net - 1, 2), round(a * b / 10, 2)], f"Net = {a} + {b} + {a}×{b}/100 = {_fmt(net)}%.", steps, "medium", rng, "%"))
    return out


def profit_loss(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        cp = rng.choice([400, 500, 640, 800, 1200, 1500])
        pct = rng.choice([10, 12.5, 20, 25, 30])
        gain = i % 3 != 2
        sp = round(cp * (1 + pct / 100) if gain else cp * (1 - pct / 100), 2)
        steps = {
            "hint": "Profit and loss percentages are calculated on the cost price.",
            "concept": "Profit % = (SP − CP)/CP × 100; Loss % = (CP − SP)/CP × 100.",
            "approach": f"Find SP − CP and divide by CP = {cp}.",
            "solution": f"|{_fmt(sp)} − {cp}| / {cp} × 100 = {pct}% {'profit' if gain else 'loss'}.",
            "shortcut": "SP = CP × (100 ± %)/100; reverse it to find the %.",
            "mistakes": "Using SP as the base instead of CP.",
        }
        if i % 2 == 0:
            out.append(_mcq(f"An article bought for ₹{cp} is sold for ₹{_fmt(sp)}. Find the {'profit' if gain else 'loss'} percentage.", pct, [round(abs(sp - cp) / sp * 100, 2), pct + 5, round(abs(sp - cp), 2)], f"{'Profit' if gain else 'Loss'} = {_fmt(abs(sp - cp))}; ÷ {cp} × 100 = {pct}%.", steps, "easy", rng, "%"))
        else:
            out.append(_num(f"A trader buys goods for ₹{cp} and wants a {'profit' if gain else 'loss'} of {pct}%. At what price (in ₹) must he sell?", sp, f"SP = {cp} × {(100 + pct) if gain else (100 - pct)}/100 = {_fmt(sp)}.", {**steps, "approach": f"SP = CP × (100 {'+' if gain else '−'} {pct})/100."}, "easy", unit="₹"))
    return out


def discount(rng: random.Random, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        mp = rng.choice([800, 1000, 1200, 1500, 2000, 2400])
        d = rng.choice([10, 15, 20, 25])
        sp = round(mp * (1 - d / 100), 2)
        steps = {
            "hint": "Discount is always on the marked price (list price).",
            "concept": "SP = MP × (100 − discount%)/100.",
            "approach": f"Multiply {mp} by (100 − {d})/100.",
            "solution": f"{mp} × {100 - d}/100 = ₹{_fmt(sp)}.",
            "shortcut": f"Find {d}% of {mp} and subtract it.",
            "mistakes": "Applying the discount to the cost price.",
        }
        out.append(_mcq(f"An item marked at ₹{mp} is sold at a discount of {d}%. What is the selling price?", sp, [mp - d, round(mp * d / 100, 2), round(mp * (1 + d / 100), 2)], f"SP = {mp} × {100 - d}/100 = ₹{_fmt(sp)}.", steps, "easy", rng))
    return out


def simple_interest(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        p = rng.choice([2000, 5000, 8000, 10000, 12000, 15000])
        r = rng.choice([4, 5, 6, 8, 10, 12])
        t = rng.choice([2, 3, 4, 5])
        si = round(p * r * t / 100, 2)
        steps = {
            "hint": "Simple interest grows by the same amount every year.",
            "concept": "SI = P × R × T / 100.",
            "approach": f"P = {p}, R = {r}, T = {t}.",
            "solution": f"{p} × {r} × {t} / 100 = ₹{_fmt(si)}.",
            "shortcut": f"One year's interest is {r}% of {p} = {_fmt(p * r / 100)}; multiply by {t}.",
            "mistakes": "Forgetting to divide by 100, or giving the amount (P + SI) when SI is asked.",
        }
        if i % 2 == 0:
            out.append(_mcq(f"Find the simple interest on ₹{p} at {r}% per annum for {t} years.", si, [round(si + p, 2), round(p * r / 100, 2), round(si * 2, 2)], f"SI = {p}×{r}×{t}/100 = ₹{_fmt(si)}.", steps, "easy", rng))
        else:
            amount = round(p + si, 2)
            out.append(_num(f"₹{p} is lent at {r}% simple interest per annum. What is the amount (in ₹) after {t} years?", amount, f"SI = ₹{_fmt(si)}; amount = {p} + {_fmt(si)} = ₹{_fmt(amount)}.", {**steps, "solution": f"SI = {_fmt(si)}; Amount = P + SI = {_fmt(amount)}."}, "medium", unit="₹"))
    return out


def compound_interest(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        p = rng.choice([1000, 2000, 5000, 8000, 10000])
        r = rng.choice([5, 10, 20])
        t = 2 if i % 2 == 0 else 3
        amount = round(p * (1 + r / 100) ** t, 2)
        ci = round(amount - p, 2)
        si = p * r * t / 100
        steps = {
            "hint": "In compound interest, each year's interest is added to the principal before the next year.",
            "concept": "A = P(1 + R/100)^T, CI = A − P.",
            "approach": f"Compute {p} × (1 + {r}/100)^{t}, then subtract {p}.",
            "solution": f"A = {p} × {1 + r / 100:g}^{t} = {_fmt(amount)}; CI = {_fmt(ci)}.",
            "shortcut": f"For 2 years, CI − SI = P(R/100)^2 = {_fmt(p * (r / 100) ** 2)}." if t == 2 else "Use successive %: each year multiply by (1 + R/100).",
            "mistakes": "Using the simple-interest formula, or reporting the amount instead of the interest.",
        }
        out.append(_mcq(f"Find the compound interest on ₹{p} at {r}% per annum for {t} years, compounded annually.", ci, [round(si, 2), round(amount, 2), round(ci - p * r / 200, 2)], f"A = {_fmt(amount)}, CI = {_fmt(ci)}.", steps, "medium" if t == 2 else "hard", rng))
    return out


def ohms_law(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        r = rng.choice([2, 4, 5, 10, 12, 20])
        current = rng.choice([0.5, 1, 1.5, 2, 3])
        v = round(r * current, 2)
        steps = {
            "hint": "Voltage, current and resistance are linked by one law.",
            "concept": "Ohm's law: V = I × R (at constant temperature).",
            "approach": "Rearrange for the unknown: I = V/R, R = V/I.",
            "solution": f"I = {v}/{r} = {current} A." if i % 2 == 0 else f"V = {current} × {r} = {v} V.",
            "shortcut": "Cover the unknown in the V-over-I×R triangle.",
            "mistakes": "Multiplying when you should divide; mixing mA and A.",
        }
        if i % 2 == 0:
            out.append(_num(f"A potential difference of {v} V is applied across a {r} Ω resistor. What current (in A) flows?", current, f"I = V/R = {v}/{r} = {current} A.", steps, "easy", unit="A"))
        else:
            out.append(_mcq(f"A current of {current} A flows through a {r} Ω resistor. What is the potential difference across it?", v, [round(r / current, 2), round(current / r, 2), round(v * 2, 2)], f"V = IR = {current} × {r} = {v} V.", steps, "easy", rng, " V"))
    return out


def resistance_combo(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        a, b = rng.choice([(2, 3), (4, 4), (3, 6), (6, 12), (10, 15), (5, 20)])
        series = i % 2 == 0
        ans = a + b if series else round(a * b / (a + b), 2)
        steps = {
            "hint": "Decide first: is the same current through both (series) or the same voltage across both (parallel)?",
            "concept": "Series: R = R1 + R2. Parallel: 1/R = 1/R1 + 1/R2, so R = R1R2/(R1 + R2).",
            "approach": f"Use the {'series' if series else 'parallel'} formula with {a} Ω and {b} Ω.",
            "solution": f"R = {a} + {b} = {ans} Ω." if series else f"R = ({a}×{b})/({a}+{b}) = {ans} Ω.",
            "shortcut": "Parallel resistance is always smaller than the smallest resistor.",
            "mistakes": "Adding parallel resistances directly.",
        }
        out.append(_mcq(f"Two resistors of {a} Ω and {b} Ω are connected in {'series' if series else 'parallel'}. What is the equivalent resistance?", ans, [round(a * b / (a + b), 2) if series else a + b, abs(b - a) or 1, round((a + b) / 2, 2)], steps["solution"], "easy" if series else "medium", rng, " Ω"))
    return out


def electric_power(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        v = rng.choice([220, 230, 110, 12])
        current = rng.choice([0.5, 1, 2, 4, 5])
        p = round(v * current, 2)
        hours = rng.choice([2, 4, 5, 10])
        steps = {
            "hint": "Power is the rate of using energy.",
            "concept": "P = V × I; energy (kWh) = P (kW) × time (h).",
            "approach": f"P = {v} × {current}.",
            "solution": f"P = {p} W.",
            "shortcut": "1 kWh = 1 'unit' on your electricity bill.",
            "mistakes": "Forgetting to convert W to kW before multiplying by hours.",
        }
        if i % 2 == 0:
            out.append(_mcq(f"An appliance draws {current} A from a {v} V supply. What is its power?", p, [round(v / current, 2), round(p / 1000, 3), round(p * 2, 2)], f"P = VI = {v} × {current} = {p} W.", steps, "easy", rng, " W"))
        else:
            kwh = round(p / 1000 * hours, 3)
            out.append(_num(f"An appliance of {p} W runs for {hours} hours. How many kWh (units) of energy does it use?", kwh, f"{p} W = {p / 1000} kW; × {hours} h = {kwh} kWh.", {**steps, "solution": f"{p / 1000} kW × {hours} h = {kwh} kWh."}, "medium", tolerance=0.001, unit="kWh"))
    return out


def depreciation_slm(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        cost = rng.choice([100000, 120000, 250000, 500000])
        salvage = rng.choice([0, 10000, 20000, 50000])
        life = rng.choice([4, 5, 8, 10])
        dep = round((cost - salvage) / life, 2)
        steps = {
            "hint": "Straight line means the same depreciation charge every year.",
            "concept": "SLM annual depreciation = (Cost − Residual value) / Useful life.",
            "approach": f"({cost} − {salvage}) / {life}.",
            "solution": f"= ₹{_fmt(dep)} per year.",
            "shortcut": "As a rate: (annual dep / cost) × 100.",
            "mistakes": "Ignoring the residual (scrap) value, or applying the rate on the reducing balance.",
        }
        if i % 2 == 0:
            out.append(_num(f"A machine costs ₹{cost:,} with a residual value of ₹{salvage:,} and a useful life of {life} years. Find the annual depreciation (₹) under the straight line method.", dep, f"({cost} − {salvage}) / {life} = ₹{_fmt(dep)}.", steps, "easy", unit="₹"))
        else:
            out.append(_mcq(f"Cost ₹{cost:,}, residual value ₹{salvage:,}, life {life} years. Annual depreciation by SLM is:", dep, [round(cost / life, 2), round((cost + salvage) / life, 2), round(dep * 2, 2)], steps["solution"], "easy", rng))
    return out


def depreciation_wdv(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        cost = rng.choice([100000, 200000, 500000, 800000])
        rate = rng.choice([10, 15, 20, 25])
        year = 2 if i % 2 == 0 else 3
        book = cost
        for _ in range(year - 1):
            book *= 1 - rate / 100
        dep = round(book * rate / 100, 2)
        steps = {
            "hint": "WDV charges depreciation on the reduced (written down) value each year.",
            "concept": "Dep for a year = Opening WDV × rate; closing WDV = opening − dep.",
            "approach": f"Reduce ₹{cost:,} by {rate}% for {year - 1} year(s) to get the opening WDV of year {year}.",
            "solution": f"Opening WDV year {year} = ₹{_fmt(round(book, 2))}; depreciation = {rate}% = ₹{_fmt(dep)}.",
            "shortcut": f"Opening WDV of year n = Cost × (1 − r)^(n−1) = {cost} × {1 - rate / 100:g}^{year - 1}.",
            "mistakes": "Applying the rate on the original cost every year (that is SLM).",
        }
        out.append(_mcq(f"An asset costing ₹{cost:,} is depreciated at {rate}% p.a. on the written down value method. What is the depreciation for year {year}?", dep, [round(cost * rate / 100, 2), round(dep * (1 - rate / 100), 2), round(book, 2)], steps["solution"], "medium", rng))
    return out
