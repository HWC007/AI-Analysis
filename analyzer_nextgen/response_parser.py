import json
import re


def parse_response(content: str) -> dict:
    data = json.loads(content)
    explanation = data.get("explanation") or data.get("overall_explanation") or data.get("final_reasoning")
    if not isinstance(explanation, str) or not explanation.strip():
        aliases = {
            1: ("priority_1_company_analysis", "priority_1_company", "p1_company_analysis"),
            2: ("priority_2_current_position_analysis", "priority_2_current_role", "p2_current_role"),
            3: ("priority_3_previous_position_and_background", "priority_3_background", "p3_background"),
            4: ("priority_4_competitor_alternative_software", "priority_4_software", "p4_software"),
            5: ("priority_5_moldex3d_false_positive_avoidance", "priority_5_moldex", "p5_moldex"),
        }
        sections = {}
        for number, names in aliases.items():
            section = next((data.get(name) for name in names if isinstance(data.get(name), dict)), None)
            if section is None:
                prefix = f"p{number}"
                section = next(
                    (value for name, value in data.items()
                     if re.sub(r"[^a-z0-9]", "", str(name).lower()).startswith(prefix)
                     and isinstance(value, dict)),
                    None,
                )
            if not section:
                raise RuntimeError(f"AI response is missing Priority {number}")
            evidence = section.get("explanation") or section.get("evidence") or section.get("reasoning") or section.get("details")
            if not isinstance(evidence, str) or not evidence.strip():
                raise RuntimeError(f"AI response is missing Priority {number} evidence")
            sections[number] = evidence.strip()
        labels = {
            1: "Priority 1 – Company analysis", 2: "Priority 2 – Current position analysis",
            3: "Priority 3 – Previous experience and background", 4: "Priority 4 – Competitor/alternative software",
            5: "Priority 5 – Moldex3D/Moldex analysis",
        }
        explanation = "\n\n".join(f"{labels[n]}:\n{text}" for n, text in sections.items())
    # Parse terminal conclusions inside their numbered sections. Counting
    # conclusions globally can silently shift P1-P5 when one section is
    # missing a conclusion and another contains an extra one.
    headers = list(re.finditer(r"(?im)^\s*(?:priority\s*|p)([1-5])\b[^\n]*", explanation))
    numbers = [int(match.group(1)) for match in headers]
    if numbers != [1, 2, 3, 4, 5]:
        raise RuntimeError(f"AI explanation must contain Priority sections 1 through 5 in order; found {numbers}")
    for position, number in enumerate(numbers):
        start = headers[position].end()
        end = headers[position + 1].start() if position + 1 < len(headers) else len(explanation)
        section_text = explanation[start:end]
        conclusions = re.findall(r"(?im)^\s*Conclusion\s*:\s*(True|False)\s*\.?\s*$", section_text)
        if len(conclusions) != 1:
            raise RuntimeError(
                f"Priority {number} section must contain exactly one terminal conclusion; found {len(conclusions)}"
            )
        data[f"priority_{number}_satisfied"] = conclusions[0].casefold() == "true"
    data["explanation"] = explanation.strip()
    data["judgement"] = "Yes" if any(data[f"priority_{n}_satisfied"] for n in (1, 2, 3, 5)) else "No"
    return data
