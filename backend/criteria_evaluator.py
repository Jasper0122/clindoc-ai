# backend/criteria_evaluator.py
from typing import List, Any, Dict
import logging
import re

from alignment_types import ExtractedCriterion, ClinicalData, EvaluatedCriterion  # type: ignore

logger = logging.getLogger("clindocai.criteria_evaluator")
logger.setLevel(logging.INFO)


def _get_attr(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _match_keywords(keywords: List[str], text: str) -> List[str]:
    if not keywords or not text:
        return []
    matches = []
    t = text.lower()
    for kw in keywords:
        if not kw:
            continue
        k = kw.lower().strip()
        if not k:
            continue
        # full substring match
        if k in t:
            matches.append(kw)
            continue
        # token match (words)
        tokens = re.findall(r"\b\w+\b", t)
        if any(k in tok for tok in tokens):
            matches.append(kw)
            continue
        # partial fallback (first 4-7 chars)
        short = k[:6]
        if len(short) >= 3 and short in t:
            matches.append(kw)
    return matches


def _build_search_text(clinical_data: Any, doctor_notes_fallback: str = "") -> str:
    parts = []
    raw = _get_attr(clinical_data, "raw_text", None) or doctor_notes_fallback
    if raw:
        parts.append(str(raw))
    for k in ("symptoms", "imagingFindings", "labs", "vitals", "comorbidities",
              "spo2_values", "oxygen_methods", "outpatient_medications"):
        val = _get_attr(clinical_data, k, None)
        if isinstance(val, (list, tuple)):
            parts.append(" ".join(map(str, val)))
        elif isinstance(val, dict):
            parts.append(" ".join([f"{kk} {vv}" for kk, vv in val.items() if vv is not None]))
        elif val:
            parts.append(str(val))
    # also include explicit important flags if present
    for flag in ("hypoxemia", "oxygenRequirement", "tachypnea", "bilateral_pneumonia",
                 "iv_antibiotics", "dnr_dni", "assisted_living", "crackles", "distress"):
        fv = _get_attr(clinical_data, flag, None)
        if fv:
            parts.append(str(flag))
    return "\n".join([p for p in parts if p]).lower()


def _parse_bp_systolic(bp_str: str) -> Any:
    if not bp_str:
        return None
    try:
        m = re.match(r"(\d{2,3})\s*/\s*(\d{2,3})", str(bp_str))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def evaluate_criteria(criteria_list: List[ExtractedCriterion], clinical_data: ClinicalData) -> List[EvaluatedCriterion]:
    evaluated: List[EvaluatedCriterion] = []

    search_text = _build_search_text(clinical_data, doctor_notes_fallback="")

    labs = _get_attr(clinical_data, "labs", {}) or {}
    vitals = _get_attr(clinical_data, "vitals", {}) or {}
    lowest_spo2 = _get_attr(clinical_data, "lowest_spo2", None) or _get_attr(clinical_data, "spo2_values", [None])[0]
    oxygen_flow = _get_attr(clinical_data, "oxygen_flow_lpm", None)
    oxygen_req = bool(_get_attr(clinical_data, "oxygenRequirement", False))
    hypox = bool(_get_attr(clinical_data, "hypoxemia", False))
    imaging = _get_attr(clinical_data, "imagingFindings", []) or []
    outpatient_fail = bool(_get_attr(clinical_data, "outpatientFailure", False))
    comorbs = _get_attr(clinical_data, "comorbidities", []) or []

    # new extractor flags
    tachypnea = bool(_get_attr(clinical_data, "tachypnea", False))
    bilateral_pna = bool(_get_attr(clinical_data, "bilateral_pneumonia", False))
    iv_abx = bool(_get_attr(clinical_data, "iv_antibiotics", False))
    dnr_dni = bool(_get_attr(clinical_data, "dnr_dni", False))
    assisted_living = bool(_get_attr(clinical_data, "assisted_living", False))
    crackles = bool(_get_attr(clinical_data, "crackles", False))
    distress = bool(_get_attr(clinical_data, "distress", False))

    # numeric lab shortcuts
    try:
        wbc_val = float(labs.get("wbc")) if labs.get("wbc") is not None else None
    except Exception:
        wbc_val = None
    try:
        bun_val = float(labs.get("bun")) if labs.get("bun") is not None else None
    except Exception:
        bun_val = None
    try:
        cr_val = float(labs.get("creatinine")) if labs.get("creatinine") is not None else None
    except Exception:
        cr_val = None
    try:
        gfr_val = float(labs.get("gfr")) if labs.get("gfr") is not None else None
    except Exception:
        gfr_val = None
    try:
        inr_val = float(labs.get("inr")) if labs.get("inr") is not None else None
    except Exception:
        inr_val = None

    systolic_bp = _parse_bp_systolic(vitals.get("bp")) if isinstance(vitals.get("bp"), str) else None
    try:
        hr_val = int(vitals.get("hr")) if vitals.get("hr") is not None else None
    except Exception:
        hr_val = None

    for crit in criteria_list or []:
        try:
            # robustly extract criterion fields
            if isinstance(crit, dict):
                cid = crit.get("id") or crit.get("criterionId") or None
                ctext = crit.get("text") or crit.get("criterionText") or ""
                ccat = crit.get("category") or crit.get("cat") or ""
                keywords = crit.get("keywords") or crit.get("kw") or []
            else:
                cid = _get_attr(crit, "id", _get_attr(crit, "criterionId", None))
                ctext = _get_attr(crit, "text", _get_attr(crit, "criterionText", "")) or ""
                ccat = _get_attr(crit, "category", "") or ""
                keywords = _get_attr(crit, "keywords", []) or []

            ctext_norm = str(ctext or "").strip()
            cat_norm = str(ccat or "").strip().lower()
            keywords = list(keywords) if keywords else []

            status = "Missing"
            evidence_fragments: List[str] = []

            # 1) keyword-driven detection (high confidence)
            if keywords:
                matched = _match_keywords(keywords, search_text)
                if matched:
                    evidence_fragments.extend(matched)
                    if len(set([m.lower() for m in matched])) >= 2:
                        status = "Met"
                    else:
                        status = "Partial"
                else:
                    status = "Missing"

            else:
                # 2) Category / text driven deterministic rules
                text_lower = (ctext_norm or "").lower()

                # Pulmonary / Respiratory rules
                pulmonary_indicators = ("oxygen", "o2 sat", "hypox", "desat", "saturation", "respiratory", "tachypnea", "crackles", "pneumonia", "infiltrate", "consolidation", "bilateral")
                if cat_norm in ("respiratory", "pulmonary") or any(k in text_lower for k in pulmonary_indicators):
                    if hypox or (isinstance(lowest_spo2, (int, float)) and lowest_spo2 < 90):
                        status = "Met"
                        evidence_fragments.append(f"Lowest SpO2={lowest_spo2}")
                    elif oxygen_req or tachypnea or crackles or bilateral_pna or (isinstance(lowest_spo2, (int, float)) and 90 <= lowest_spo2 < 94):
                        status = "Partial"
                        if oxygen_req:
                            evidence_fragments.append("Supplemental oxygen documented")
                        if tachypnea:
                            evidence_fragments.append("Tachypnea documented")
                        if crackles:
                            evidence_fragments.append("Exam: crackles")
                        if bilateral_pna:
                            evidence_fragments.append("Bilateral pulmonary involvement")
                    else:
                        status = "Missing"

                # Imaging
                elif cat_norm in ("imaging",) or any(k in text_lower for k in ("pneumonia", "x-ray", "cxr", "ct", "consolidation", "infiltrate")):
                    if imaging:
                        status = "Met"
                        evidence_fragments.append("Radiographic evidence documented")
                    else:
                        status = "Missing"

                # Laboratory domain (WBC, lactate, BUN, creatinine, INR)
                elif cat_norm in ("laboratory", "labs", "renal") or any(k in text_lower for k in ("wbc", "white blood", "leukocyt", "lactate", "bun", "creatinine", "gfr", "inr")):
                    # renal specific
                    if "bun" in text_lower or "creatinine" in text_lower or "gfr" in text_lower or cat_norm == "renal":
                        if bun_val is not None and bun_val > 40:
                            status = "Met"
                            evidence_fragments.append(f"BUN={bun_val}")
                        elif cr_val is not None and cr_val > 1.5:
                            status = "Met"
                            evidence_fragments.append(f"Creatinine={cr_val}")
                        elif gfr_val is not None and gfr_val < 60:
                            status = "Partial"
                            evidence_fragments.append(f"GFR={gfr_val}")
                        else:
                            status = "Missing"
                    else:
                        # general infection labs
                        if wbc_val is not None:
                            if wbc_val >= 12:
                                status = "Met"
                                evidence_fragments.append(f"WBC={wbc_val}")
                            elif 10 <= wbc_val < 12:
                                status = "Partial"
                                evidence_fragments.append(f"WBC={wbc_val}")
                            else:
                                status = "Missing"
                        else:
                            status = "Missing"

                    # INR handling
                    if inr_val is not None and inr_val > 2:
                        # elevate to Met for coagulation concern
                        status = "Met"
                        evidence_fragments.append(f"INR={inr_val}")

                # Outpatient failure
                elif cat_norm in ("outpatient",) or "outpatient" in text_lower or "failed" in text_lower:
                    if outpatient_fail:
                        status = "Met"
                        evidence_fragments.append("Outpatient therapy failure documented")
                    else:
                        status = "Missing"

                # Escalation (IV antibiotics / IV therapy / ICU transfer requests)
                elif cat_norm in ("escalation", "treatment") or any(k in text_lower for k in ("iv", "intravenous", "vancomycin", "cefepime", "piperacillin", "zosyn", "broad-spectrum")):
                    if iv_abx:
                        status = "Met"
                        evidence_fragments.append("IV broad-spectrum antibiotics initiated")
                    else:
                        status = "Missing"

                # Hemodynamic instability
                elif cat_norm in ("hemodynamic", "cardiac") or any(k in text_lower for k in ("blood pressure", "sbp", "hypotension", "tachycardia", "arrhythmia")):
                    if systolic_bp is not None and systolic_bp < 90:
                        status = "Met"
                        evidence_fragments.append(f"SBP={systolic_bp}")
                    elif hr_val is not None and hr_val > 120:
                        status = "Partial"
                        evidence_fragments.append(f"HR={hr_val}")
                    else:
                        status = "Missing"

                # Functional / disposition risk
                elif cat_norm in ("functional", "disposition", "social") or any(k in text_lower for k in ("assisted living", "dnr", "dni", "homebound", "nursing")):
                    if assisted_living or dnr_dni or distress:
                        status = "Partial"
                        if assisted_living:
                            evidence_fragments.append("Assisted living residency")
                        if dnr_dni:
                            evidence_fragments.append("DNR/DNI documented")
                        if distress:
                            evidence_fragments.append("Clinically distressed / frail appearing")
                    else:
                        status = "Missing"

                # Comorbidity category
                elif cat_norm in ("comorbidity",) or any(k in text_lower for k in ("comorbid", "htn", "afib", "diabetes", "ckd", "dvt")):
                    if comorbs:
                        status = "Partial"
                        evidence_fragments.append("Comorbidities present: " + ", ".join(comorbs))
                    else:
                        status = "Missing"

                else:
                    # fallback: token match against criterion text
                    toks = re.findall(r"[a-zA-Z0-9\%\-]+", text_lower)
                    token_matches = [t for t in toks if t and t in search_text]
                    if token_matches:
                        status = "Partial"
                        evidence_fragments.append(" ".join(token_matches))
                    else:
                        status = "Missing"

            # Normalize status
            st_norm = "Missing"
            ss = str(status).strip().lower()
            if ss in ("met", "yes", "true", "satisfied"):
                st_norm = "Met"
            elif "part" in ss or ss in ("partial", "partially", "partial match"):
                st_norm = "Partial"
            else:
                st_norm = "Missing"

            # map to score contribution
            if st_norm == "Met":
                score = 5
            elif st_norm == "Partial":
                score = 2
            else:
                score = 0

            evidence_text = " ; ".join([str(x) for x in evidence_fragments if x]) if evidence_fragments else ""

            suggested_language = ""
            if st_norm == "Missing":
                if ctext_norm:
                    suggested_language = f"Consider documenting: {ctext_norm}"
                else:
                    suggested_language = "Consider documenting relevant clinical findings."

            # build EvaluatedCriterion (try dataclass, fallback to dict-like)
            try:
                evaluated_item = EvaluatedCriterion(
                    criterionId=cid,
                    criterionText=ctext,
                    category=ccat,
                    status=st_norm,
                    evidenceFound=evidence_text,
                    suggestedLanguage=suggested_language,
                    scoreContribution=score
                )
            except Exception:
                # fallback: attempt to construct as dict-like if EvaluatedCriterion is not a direct constructor
                try:
                    evaluated_item = EvaluatedCriterion(
                        **{
                            "criterionId": cid,
                            "criterionText": ctext,
                            "category": ccat,
                            "status": st_norm,
                            "evidenceFound": evidence_text,
                            "suggestedLanguage": suggested_language,
                            "scoreContribution": score
                        }
                    )
                except Exception:
                    # last fallback: simple dict
                    evaluated_item = {
                        "criterionId": cid,
                        "criterionText": ctext,
                        "category": ccat,
                        "status": st_norm,
                        "evidenceFound": evidence_text,
                        "suggestedLanguage": suggested_language,
                        "scoreContribution": score
                    }

            evaluated.append(evaluated_item)

        except Exception as ex:
            logger.exception("Error evaluating criterion: %s", ex)
            # safe fallback append
            try:
                evaluated.append(EvaluatedCriterion(
                    criterionId=_get_attr(crit, "id", _get_attr(crit, "criterionId", "ERR")),
                    criterionText=_get_attr(crit, "text", str(crit)),
                    category=_get_attr(crit, "category", "Unknown"),
                    status="Missing",
                    evidenceFound="",
                    suggestedLanguage="",
                    scoreContribution=0
                ))
            except Exception:
                evaluated.append({
                    "criterionId": _get_attr(crit, "id", _get_attr(crit, "criterionId", "ERR")),
                    "criterionText": _get_attr(crit, "text", str(crit)),
                    "category": _get_attr(crit, "category", "Unknown"),
                    "status": "Missing",
                    "evidenceFound": "",
                    "suggestedLanguage": "",
                    "scoreContribution": 0
                })
            continue

    logger.info("evaluate_criteria -> evaluated %d items", len(evaluated))
    return evaluated